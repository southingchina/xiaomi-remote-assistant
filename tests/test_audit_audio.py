"""Audit-sync regressions using real worker threads and simulated audio only."""
import asyncio
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rc003_bridge import audio
from rc003_bridge.core import AtvvSession, ImaDecoder
from rc003_bridge.runtime import BridgeRuntime


class PacedSink:
    def __init__(self,**kwargs):self.frames=[];self.events=[];self.aborted=threading.Event()
    def start(self):self.events.append('start')
    def write(self,pcm):
        self.aborted.wait(len(pcm)/32000)
        if not self.aborted.is_set():self.frames.append(pcm)
    def stop(self):self.events.append('stop')
    def abort(self):self.events.append('abort');self.aborted.set()
    def close(self):self.events.append('close')


def audio_patches(sink=PacedSink):
    return (patch('rc003_bridge.audio.select_output',return_value={'index':0,'sampleRate':16000,'channels':1}),
            patch.dict(sys.modules,{'sounddevice':SimpleNamespace(RawOutputStream=sink)}))


def runtime():
    sent=[]
    resolver=SimpleNamespace(resolve=lambda p:{'type':'voice' if p==9 else 'keyboard','action':'remote-mic' if p==9 else 'Enter','actionId':'default:'+str(p)})
    dispatcher=SimpleNamespace(send=lambda b,d:sent.append((b['actionId'],d)),release_all=lambda:None,close=lambda:None)
    result=BridgeRuntime(config={'dispatchEnabled':True,'enhancedCaptureEnabled':True,'consumeRemoteDirections':True,'qwenAudioRouteConfirmed':True},resolver=resolver,dispatcher=dispatcher,
                         qwen=SimpleNamespace(read=lambda:{'recording':False,'state':0,'session':'old','time':1}))
    result.publish=lambda **fields:result.state.update(fields)
    result.notes=[];result.note=lambda name,**fields:result.notes.append((name,fields))
    result.state['phase']='ready';result.epoch=4;result.bound=True;result.sent=sent;result.writes=[]
    result.session=AtvvSession();result.session.control(bytes.fromhex('0b0100020300780000'))
    async def write(data):result.writes.append(data)
    async def close():pass
    async def no_expiry():pass
    result.transport=SimpleNamespace(write=write,close=close);result.expire_direction_filter=no_expiry
    result.direction_lease_until=time.monotonic()+100
    result.physical['enhanced'].add(9);result.observed['enhanced'].add(9);result.physical_voice(True)
    return result


class PcmBudgetTests(unittest.TestCase):
    def test_budget_counts_inflight_samples_and_accepts_four_seconds(self):
        entered=threading.Event();release=threading.Event()
        class HeldSink(PacedSink):
            def write(self,pcm):entered.set();release.wait(2)
            def abort(self):super().abort();release.set()
        first,second=audio_patches(HeldSink)
        with first,second:
            output=audio.PcmOutput();output.start()
            try:
                output.write(bytes(32000));self.assertTrue(entered.wait(1))
                output.write(bytes(3*32000))
                with self.assertRaisesRegex(RuntimeError,'full'):output.write(bytes(2))
                self.assertEqual(output.pending_seconds,4)
            finally:release.set();output.finish(drain=False)

    def test_half_second_backlog_drains_all_frames_instead_of_fixed_350ms_cutoff(self):
        first,second=audio_patches()
        with first,second:
            output=audio.PcmOutput();output.start();sink=output.stream
            packets=[bytes([index])*480 for index in range(34)]
            try:
                for packet in packets:output.write(packet)
                output.finish()
            finally:
                if output.stream is not None:output.finish(drain=False)
            self.assertEqual(b''.join(sink.frames),b''.join(packets))
            self.assertEqual(sink.events,['start','stop','close'])

    def test_slow_native_writer_is_aborted_after_duration_budget(self):
        entered=threading.Event();release=threading.Event()
        class SlowSink(PacedSink):
            def write(self,pcm):entered.set();release.wait(2)
            def abort(self):super().abort();release.set()
        first,second=audio_patches(SlowSink)
        with first,second:
            output=audio.PcmOutput();output.start();output.write(bytes(3200));sink=output.stream
            self.assertTrue(entered.wait(1));started=time.monotonic()
            try:
                with self.assertRaisesRegex(RuntimeError,'drain timed out'):output.finish()
            finally:release.set()
            self.assertLess(time.monotonic()-started,1.5)
            self.assertEqual(sink.events,['start','abort','close'])


class RuntimeAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_failure_keeps_same_connection_and_continues_filtered_keys(self):
        r=runtime();session,transport=r.session,r.transport;r.session.control(bytes.fromhex('04030207'))
        r.voice_active=True;r.router.edge(9,True);r.voice_stream_cycle=1;finished=[]
        class Output:
            def write(self,pcm):raise RuntimeError('audio buffer is full')
            def finish(self,drain=True):finished.append(drain)
        r.output=Output();original=r.edge
        async def edge(position,down):
            await original(position,down)
            if position==5 and not down:r.stop.set()
        r.edge=edge
        for kind,data in [('audio',bytes(120)),('enhanced-key',(5,True)),('enhanced-key',(5,False))]:r.queue.put_nowait((4,kind,data))
        await asyncio.wait_for(r.consume_connection(),1)
        if getattr(r,'voice_finish_task',None):await asyncio.wait_for(r.voice_finish_task,1)
        self.assertIs(r.session,session);self.assertIs(r.transport,transport);self.assertEqual(r.epoch,4)
        self.assertTrue(session.ready);self.assertFalse(session.streaming);self.assertFalse(r.voice_active)
        self.assertEqual(finished,[False]);self.assertEqual(r.writes,[b'\x0d\x07'])
        self.assertIn(('default:5',False),r.sent);self.assertIn('full',r.state['voiceIssue'])

    async def test_actual_gatt_close_error_still_propagates(self):
        r=runtime();r.session.control(bytes.fromhex('04030207'));r.voice_active=True;r.router.edge(9,True)
        class Output:
            def write(self,pcm):raise RuntimeError('audio failed')
            def finish(self,drain=True):pass
        async def broken(data):raise OSError('Bluetooth close failed')
        r.output=Output();r.transport.write=broken;r.queue.put_nowait((4,'audio',bytes(120)))
        with self.assertRaisesRegex(OSError,'Bluetooth close failed'):await asyncio.wait_for(r.consume_connection(),1)
        if getattr(r,'voice_finish_task',None):await asyncio.wait_for(r.voice_finish_task,1)

    async def test_normal_finish_returns_while_audio_drains_and_releases_original_binding(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True;entered=threading.Event();release=threading.Event()
        class Output:
            pending_seconds=.1
            def finish(self,drain=True):entered.set();release.wait(2)
            def request_abort(self):release.set()
        r.output=Output()
        try:
            await asyncio.wait_for(r.voice_up(),.15)
            self.assertTrue(await asyncio.to_thread(entered.wait,.3))
            await r.input_edge('enhanced',5,True);await r.input_edge('enhanced',5,False)
            self.assertEqual(r.sent,[('default:9',True),('default:5',True),('default:5',False)])
            release.set();await asyncio.wait_for(r.voice_finish_task,1)
            self.assertEqual(r.sent[-1],('default:9',False));self.assertFalse(r.router.held)
        finally:release.set()

    async def test_startup_backlog_then_release_preserves_samples_while_keys_continue(self):
        r=runtime();entered=asyncio.Event();loop=asyncio.get_running_loop();outputs=[];key_counts=[]
        original_output=audio.PcmOutput
        class Output(original_output):
            def start(self):super().start();self.sink=self.stream;outputs.append(self)
        def send(binding,down):
            if binding['actionId']=='default:9' and down:loop.call_soon_threadsafe(entered.set);time.sleep(.45)
            r.sent.append((binding['actionId'],down))
        r.router.send=send;original=r.edge
        async def edge(position,down):
            await original(position,down)
            if position==5 and not down:key_counts.append(len(outputs[0].sink.frames));r.stop.set()
        r.edge=edge;packets=[bytes([index])*120 for index in range(27)]
        async def producer():
            r.queue.put_nowait((4,'control',bytes.fromhex('04030207')));await entered.wait()
            for packet in packets:r.queue.put_nowait((4,'audio',packet));await asyncio.sleep(.015)
            r.queue.put_nowait((4,'control',b'\x00\x02'))
            for data in ((5,True),(5,False)):r.queue.put_nowait((4,'enhanced-key',data))
        first,second=audio_patches()
        with first,second,patch('rc003_bridge.audio.PcmOutput',Output):
            await asyncio.wait_for(asyncio.gather(r.consume_connection(),producer()),3)
            self.assertIsNone(r.state.get('voiceIssue'))
            self.assertLess(key_counts[0],len(packets))
            await asyncio.wait_for(r.voice_finish_task,2)
        decoder=ImaDecoder();expected=b''.join(decoder.decode(packet) for packet in packets)
        self.assertEqual(b''.join(outputs[0].sink.frames),expected)
        self.assertEqual(outputs[0].sink.events,['start','stop','close'])

    async def test_starting_or_processing_qwen_does_not_open_audio(self):
        for state in (1,3):
            r=runtime();r.qwen.read=lambda:{'recording':False,'state':state}
            with patch('rc003_bridge.audio.PcmOutput') as output:
                with self.assertRaisesRegex(RuntimeError,'starting|processing'):await r.voice_down()
                output.assert_not_called()

    async def test_rejected_new_hold_does_not_abort_previous_drain(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True;entered=threading.Event();release=threading.Event();aborts=[]
        class Output:
            pending_seconds=.1
            def finish(self,drain=True):entered.set();release.wait(2)
            def request_abort(self):aborts.append(True);release.set()
        r.output=Output()
        try:
            await r.voice_up();self.assertTrue(await asyncio.to_thread(entered.wait,.4))
            r.voice_physical_cycle+=1
            await r.protocol_events(r.session.control(bytes.fromhex('04030208')))
            self.assertEqual(aborts,[]);self.assertEqual(r.sent,[('default:9',True)])
            release.set();await asyncio.wait_for(r.voice_finish_task,1)
            self.assertEqual(r.sent,[('default:9',True),('default:9',False)])
        finally:release.set()

    async def test_disconnect_aborts_pending_drain_and_releases_owned_binding(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True;release=threading.Event();aborts=[]
        class Output:
            pending_seconds=3
            def finish(self,drain=True):release.wait(2)
            def request_abort(self):aborts.append(True);release.set()
        r.output=Output()
        try:
            await r.voice_up();await asyncio.wait_for(r.cleanup_connection(),1)
            self.assertTrue(aborts);self.assertEqual(r.sent,[('default:9',True),('default:9',False)])
            self.assertIsNone(r.transport);self.assertFalse(r.router.held)
        finally:release.set()

    async def test_stuck_endpoint_blocks_new_mic_until_real_reclamation_and_cannot_release_replacement(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True;release=threading.Event();calls=[]
        class Output:
            pending_seconds=0
            def finish(self,drain=True):calls.append('finish');release.wait(4)
            def request_abort(self):calls.append('abort')
        r.output=Output()
        try:
            await r.voice_up();await asyncio.wait_for(r.cleanup_connection(),2)
            self.assertTrue(r.voice_finish_pending());self.assertEqual(calls.count('finish'),1)
            with self.assertRaisesRegex(RuntimeError,'cleaning up'):await r.voice_down()
            r.router.edge(9,True);replacement=r.router.held[9]
            release.set();await asyncio.wait_for(asyncio.shield(r.voice_finish_future),1);await asyncio.sleep(0)
            self.assertIs(r.router.held[9],replacement);self.assertEqual(r.sent.count(('default:9',False)),1)
            r.router.edge(9,False)
        finally:release.set()

    async def test_real_pcm_writer_retains_endpoint_after_abort_does_not_unblock_it(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True;entered=threading.Event();release=threading.Event()
        class StuckSink(PacedSink):
            def write(self,pcm):entered.set();release.wait(5)
            def abort(self):self.events.append('abort')
        first,second=audio_patches(StuckSink)
        with first,second:
            output=audio.PcmOutput();output.start();output.write(bytes(3200));r.output=output
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                await r.voice_up();await asyncio.wait_for(r.abort_voice_finish(),2)
                self.assertTrue(output.thread.is_alive());self.assertIsNotNone(output.stream);self.assertTrue(r.voice_finish_pending())
                with self.assertRaisesRegex(RuntimeError,'cleaning up'):await r.voice_down()
            finally:
                release.set()
                with self.assertRaisesRegex(RuntimeError,'retained for cleanup'):await asyncio.wait_for(asyncio.shield(r.voice_finish_future),1)
            self.assertFalse(output.thread.is_alive());self.assertIsNone(output.stream);self.assertFalse(r.voice_finish_pending())

    async def test_failed_background_release_remains_retryable_without_blocking_keys(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True;original=r.router.send;attempts=[];entered=threading.Event();release=threading.Event()
        def send(binding,down):
            if binding['actionId']=='default:9' and not down:
                attempts.append(1)
                if len(attempts)==1:raise OSError('temporary voice release refusal')
                entered.set();release.wait(2)
            original(binding,down)
        r.router.send=send
        class Output:
            pending_seconds=0
            def finish(self,drain=True):pass
        r.output=Output();await r.voice_up();await asyncio.wait_for(r.voice_finish_task,1)
        self.assertTrue(r.voice_release_pending)
        try:
            await asyncio.wait_for(r.retry_voice_release(),.15)
            self.assertTrue(await asyncio.to_thread(entered.wait,.4))
            await r.input_edge('enhanced',5,True);await r.input_edge('enhanced',5,False)
            self.assertEqual(r.sent[-1],('default:5',False))
            release.set();await asyncio.wait_for(r.voice_finish_task,1)
            self.assertFalse(r.voice_release_pending);self.assertEqual(r.sent.count(('default:9',False)),1)
        finally:release.set()

    async def test_late_failed_close_keeps_endpoint_owned_and_can_retry(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True;release=threading.Event();calls=[]
        class Output:
            pending_seconds=0
            stream=object()
            def finish(self,drain=True):
                calls.append(drain)
                if len(calls)==1:release.wait(4);raise OSError('late endpoint close failed')
                self.stream=None
            def request_abort(self):pass
        output=r.output=Output()
        try:
            await r.voice_up();await asyncio.wait_for(r.abort_voice_finish(),2)
            self.assertTrue(r.voice_finish_pending())
            release.set()
            with self.assertRaisesRegex(OSError,'late endpoint close failed'):await asyncio.wait_for(asyncio.shield(r.voice_finish_future),1)
            await asyncio.sleep(0)
            self.assertIs(r.output,output);self.assertIsNotNone(output.stream)
            with self.assertRaisesRegex(RuntimeError,'cleaning up'):await r.voice_down()
            self.assertIn('late endpoint close failed',r.state['voiceIssue'])
            await r.retry_voice_release()
            await asyncio.wait_for(r.voice_finish_task,1)
            self.assertIsNone(output.stream);self.assertIsNone(r.output)
            self.assertFalse(r.voice_finish_pending());self.assertEqual(len(calls),2)
        finally:release.set()

    async def test_done_future_before_owner_handoff_cannot_open_second_endpoint(self):
        r=runtime();r.router.edge(9,True);r.voice_active=True
        release=threading.Event();finished=threading.Event();calls=[]
        class Output:
            pending_seconds=0
            stream=object()
            def finish(self,drain=True):
                calls.append(drain)
                if len(calls)==1:
                    release.wait(4);finished.set();raise OSError('late endpoint close failed')
                self.stream=None
            def request_abort(self):pass
        output=r.output=Output()
        try:
            await r.voice_up();await asyncio.wait_for(r.abort_voice_finish(),2)
            self.assertTrue(r.voice_finish_task.done());self.assertFalse(r.voice_finish_future.done())
            loop=asyncio.get_running_loop()
            loop.call_soon(r.voice_finish_future.set_exception,OSError('late endpoint close failed'))
            # Future completion and a fresh press are already on the ready queue;
            # the ownership-transfer callback is appended behind the fresh press.
            with patch('rc003_bridge.audio.PcmOutput') as new_output:
                press=asyncio.create_task(r.voice_down())
                with self.assertRaisesRegex(RuntimeError,'cleaning up'):await press
                new_output.assert_not_called()
            await asyncio.sleep(0)
            self.assertIs(r.output,output);self.assertIsNotNone(output.stream)
            release.set();self.assertTrue(await asyncio.to_thread(finished.wait,1))
            await r.retry_voice_release();await asyncio.wait_for(r.voice_finish_task,1)
            self.assertIsNone(r.output);self.assertIsNone(output.stream);self.assertFalse(r.voice_finish_pending())
        finally:release.set()


if __name__=='__main__':unittest.main()
