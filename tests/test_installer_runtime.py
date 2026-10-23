import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rc003_bridge.core import AtvvSession
from rc003_bridge.runtime import BridgeRuntime


class Resolver:
    def __init__(self):self.action='old';self.saved=[]
    def resolve(self,position):return {'actionId':str(position),'type':'keyboard','action':self.action,'mode':'hold','shortcut':'Enter'}
    def save_state(self,state):self.saved.append(state);self.action=state['action']
    def read_state(self):return {'action':self.action}
    def reload(self):pass


class Dispatcher:
    def __init__(self):self.sent=[];self.releases=0
    def send(self,binding,down):self.sent.append((binding['action'],down))
    def release_all(self):self.releases+=1
    def close(self):pass


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self):
        dispatcher=Dispatcher();resolver=Resolver()
        runtime=BridgeRuntime(config={'dispatchEnabled':True,'enhancedCaptureEnabled':True,'consumeRemoteDirections':True},resolver=resolver,dispatcher=dispatcher,qwen=SimpleNamespace(owned=None))
        runtime.publish=lambda **changes:runtime.state.update(changes)
        runtime.note=lambda *args,**kwargs:None
        runtime.state['phase']='ready';runtime.session=AtvvSession();runtime.session.ready=True
        runtime.writes=[]
        async def write(data):runtime.writes.append(data)
        runtime.transport=SimpleNamespace(write=write)
        return runtime

    async def test_raw_input_never_duplicates_native_effect(self):
        runtime=self.runtime()
        await runtime.input_edge('raw',5,True);await runtime.input_edge('raw',5,False)
        self.assertEqual(runtime.dispatcher.sent,[])
        await runtime.input_edge('enhanced',5,True);await runtime.input_edge('enhanced',5,True)
        await runtime.input_edge('enhanced',5,False)
        self.assertEqual(runtime.dispatcher.sent,[('old',True),('old',False)])

    async def test_reload_releases_old_binding_then_waits_for_physical_neutral(self):
        runtime=self.runtime()
        await runtime.input_edge('enhanced',5,True)
        result=await runtime.command({'command':'reload-config','state':{'action':'new'}})
        self.assertTrue(result['awaitingNeutral'])
        await runtime.input_edge('enhanced',5,True)
        self.assertEqual(runtime.dispatcher.sent,[('old',True),('old',False)])
        await runtime.input_edge('enhanced',5,False)
        await runtime.input_edge('enhanced',5,True)
        self.assertEqual(runtime.dispatcher.sent[-1],('new',True))

    async def test_pause_releases_and_resume_does_not_retrigger_held_key(self):
        runtime=self.runtime();await runtime.input_edge('enhanced',7,True)
        await runtime.command({'command':'pause'})
        self.assertTrue(runtime.direction_filter_allowed())
        await runtime.command({'command':'resume'})
        await runtime.input_edge('enhanced',7,True)
        self.assertEqual(len(runtime.dispatcher.sent),2)
        await runtime.input_edge('enhanced',7,False);await runtime.input_edge('enhanced',7,True)
        self.assertEqual(len(runtime.dispatcher.sent),3)

    async def test_all_bindings_and_positions_can_receive_filtered_edges(self):
        runtime=self.runtime();self.assertTrue(runtime.direction_filter_allowed())
        permit=await runtime.command({'command':'direction-filter-permit'})
        for position in range(13):
            result=await runtime.command({'command':'enhanced-edge','position':position,'down':True,'source':'filtered-remote','generation':permit['generation']})
            self.assertTrue(result.get('accepted'),(position,result))
        for bad in ({'source':'raw'},{'generation':-1},{'position':13},{'down':1}):
            request={'command':'enhanced-edge','position':5,'down':True,'source':'filtered-remote','generation':permit['generation'],**bad}
            self.assertIn('error',await runtime.command(request))

    async def test_remapped_voice_key_runs_action_and_denies_remote_audio(self):
        runtime=self.runtime();await runtime.input_edge('enhanced',9,True)
        await runtime.control_event(b'\x08');await runtime.control_event(bytes.fromhex('04030207'))
        await runtime.input_edge('enhanced',9,False)
        self.assertEqual(runtime.dispatcher.sent,[('old',True),('old',False)])
        self.assertEqual(runtime.writes,[b'\x0d\x07'])
        self.assertFalse(runtime.voice_active);self.assertIsNone(runtime.output)

    async def test_remote_mic_physical_edge_does_not_dispatch_without_audio_request(self):
        runtime=self.runtime();runtime.resolver.resolve=lambda p:{'actionId':str(p),'type':'voice','action':'remote-mic'}
        await runtime.input_edge('enhanced',9,True);await runtime.input_edge('enhanced',9,False)
        self.assertEqual(runtime.dispatcher.sent,[])

    async def test_unconfirmed_route_never_opens_output(self):
        runtime=self.runtime();runtime.resolver.resolve=lambda p:{'actionId':str(p),'type':'voice','action':'remote-mic'}
        await runtime.input_edge('enhanced',9,True)
        with patch('rc003_bridge.audio.PcmOutput',side_effect=AssertionError('opened')):
            await runtime.control_event(b'\x08')
        self.assertFalse(runtime.voice_active);self.assertEqual(runtime.dispatcher.sent,[])
        self.assertTrue(runtime.session.ready)

    async def test_release_is_allowed_when_dispatch_disabled(self):
        runtime=self.runtime();await runtime.edge(1,True);runtime.config['dispatchEnabled']=False;await runtime.edge(1,False)
        self.assertEqual(runtime.dispatcher.sent,[('old',True),('old',False)])

    async def test_authentication_precedes_command_dispatch(self):
        runtime=self.runtime();runtime.token='secret'
        reader=asyncio.StreamReader();reader.feed_data(b'{"command":"stop","token":"wrong"}\n');reader.feed_eof()
        class Writer:
            data=b''
            def write(self,value):self.data+=value
            async def drain(self):pass
            def close(self):pass
            async def wait_closed(self):pass
        writer=Writer();await runtime.control_client(reader,writer)
        self.assertEqual(json.loads(writer.data),{'error':'unauthorized'});self.assertFalse(runtime.stop.is_set())

    async def test_settings_reject_unknown_or_wrong_types_without_partial_write(self):
        runtime=self.runtime();before=dict(runtime.config)
        for changes in ({'qwenAudioRouteConfirmed':'yes'},{'arbitrary':'bad'},{'audioOutput':{}}):
            with self.assertRaises(ValueError):await runtime.command({'command':'settings','settings':changes})
        self.assertEqual(runtime.config,before)

    async def test_synthetic_release_does_not_rearm_until_real_neutral(self):
        runtime=self.runtime();await runtime.input_edge('enhanced',5,True)
        permit=await runtime.command({'command':'direction-filter-permit'})
        result=await runtime.command({'command':'enhanced-edge','position':5,'down':False,'source':'filtered-remote','generation':permit['generation'],'synthetic':True})
        self.assertTrue(result['accepted']);self.assertTrue(runtime.awaiting_neutral)
        self.assertEqual(runtime.dispatcher.sent,[('old',True),('old',False)])
        self.assertIn(5,runtime.physical['enhanced'])
        await runtime.command({'command':'enhanced-neutral','source':'filtered-remote','generation':permit['generation']})
        await runtime.confirm_neutral()
        self.assertFalse(runtime.awaiting_neutral);self.assertFalse(runtime.physical['enhanced'])

    async def test_failed_save_preserves_active_configuration_and_is_quiescent(self):
        runtime=self.runtime();await runtime.input_edge('enhanced',5,True)
        runtime.resolver.save_state=lambda state:(_ for _ in ()).throw(ValueError('invalid profile'))
        with self.assertRaisesRegex(ValueError,'invalid profile'):await runtime.command({'command':'reload-config','state':{}})
        self.assertEqual(runtime.resolver.action,'old');self.assertEqual(len(runtime.dispatcher.sent),2)
        self.assertTrue(runtime.awaiting_neutral)

    async def test_voice_route_failure_isolated_from_connection(self):
        runtime=self.runtime();runtime.resolver.resolve=lambda p:{'actionId':str(p),'type':'voice','action':'remote-mic'}
        runtime.router.resolve=runtime.resolver.resolve
        runtime.direction_lease_until=10**20
        await runtime.input_edge('enhanced',9,True)
        with patch('rc003_bridge.audio.PcmOutput',side_effect=AssertionError('opened')):
            await runtime.control_event(b'\x08')
        self.assertTrue(runtime.session.ready);self.assertFalse(runtime.session.held)
        self.assertIn('confirm',runtime.state['voiceIssue'])
        self.assertEqual(runtime.writes,[])

    async def test_failed_ordinary_release_is_retried_without_new_down(self):
        runtime=self.runtime();original=runtime.dispatcher.send;attempts=[]
        def send(binding,down):
            if not down and not attempts:attempts.append(1);raise OSError('temporary keyup refusal')
            original(binding,down)
        runtime.router.send=send
        await runtime.input_edge('enhanced',5,True)
        with self.assertRaises(OSError):await runtime.input_edge('enhanced',5,False)
        await runtime.retry_action_releases()
        self.assertEqual(runtime.dispatcher.sent,[('old',True),('old',False)])
        self.assertFalse(runtime.router.held)

    async def test_partial_hardware_configuration_merges_safe_defaults(self):
        from rc003_bridge.runtime import configuration
        with TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text('{"audioOutput":"test","qwenAudioRouteConfirmed":true}')
            with patch('rc003_bridge.runtime.CONFIG',path):value=configuration()
        self.assertTrue(value['dispatchEnabled']);self.assertTrue(value['enhancedCaptureEnabled']);self.assertEqual(value['audioOutput'],'test')

    async def test_raw_voice_trace_alone_never_authorizes_audio(self):
        runtime=self.runtime();runtime.resolver.resolve=lambda p:{'actionId':str(p),'type':'voice','action':'remote-mic'}
        runtime.config['qwenAudioRouteConfirmed']=True;runtime.direction_lease_until=10**20
        runtime.raw_trace({'kind':'keyboard','vkey':116,'scan':63,'flags':0})
        with patch('rc003_bridge.audio.PcmOutput',side_effect=AssertionError('opened')):
            await runtime.control_event(b'\x08')
        self.assertEqual(runtime.writes,[])

    async def test_large_authenticated_profile_request_gets_response(self):
        runtime=self.runtime();runtime.token='secret'
        reader=asyncio.StreamReader(limit=128*1024)
        request={'token':'secret','command':'reload-config','state':{'action':'new','extra':'x'*12000}}
        reader.feed_data(json.dumps(request).encode()+b'\n');reader.feed_eof()
        class Writer:
            data=b''
            def write(self,value):self.data+=value
            async def drain(self):pass
            def close(self):pass
            async def wait_closed(self):pass
        writer=Writer();await runtime.control_client(reader,writer)
        self.assertTrue(json.loads(writer.data)['ok']);self.assertEqual(runtime.resolver.action,'new')

    async def test_neutral_confirmation_does_not_drop_queued_short_tap(self):
        runtime=self.runtime();permit=await runtime.command({'command':'direction-filter-permit'})
        for down in (True,False):await runtime.command({'command':'enhanced-edge','position':5,'down':down,'source':'filtered-remote','generation':permit['generation']})
        await runtime.command({'command':'enhanced-neutral','source':'filtered-remote','generation':permit['generation']})
        while not runtime.queue.empty():
            _,kind,data=runtime.queue.get_nowait()
            if kind=='enhanced-key':await runtime.input_edge('enhanced',*data)
            elif kind=='enhanced-neutral':await runtime.confirm_neutral()
        self.assertEqual(runtime.dispatcher.sent,[('old',True),('old',False)])

    async def test_unfinished_audio_stop_is_retained_for_cleanup_retry(self):
        runtime=self.runtime();calls=[]
        class Output:
            stream=object()
            def finish(self,drain=True):
                calls.append(drain)
                if len(calls)==1:raise RuntimeError('audio worker is still closing')
                self.stream=None
        output=runtime.output=Output()
        await runtime.voice_up(drain=False)
        self.assertIs(runtime.output,output);self.assertTrue(runtime.voice_release_pending)
        await runtime.retry_voice_release()
        self.assertIsNone(runtime.output);self.assertFalse(runtime.voice_release_pending)

    async def test_capture_fault_is_visible_without_claiming_action_ready(self):
        runtime=self.runtime()
        with TemporaryDirectory() as folder:
            Path(folder,'capture-status.json').write_text(json.dumps({'phase':'standby','nativeIssue':'native capture failed','permitIssue':'lease stale'}))
            original_publish=runtime.publish
            def publish(**values):original_publish(**values);runtime.stop.set()
            runtime.publish=publish
            listener=SimpleNamespace(thread=SimpleNamespace(is_alive=lambda:True))
            with patch('rc003_bridge.runtime.DATA',Path(folder)),patch('rc003_bridge.rawinput.remote_device_count',return_value=1):await runtime.watch_inputs(listener)
        self.assertFalse(runtime.state['enhancedCaptureReady']);self.assertIn('native capture failed',runtime.state['captureIssue'])

    async def test_capture_ready_phase_also_requires_armed_filter(self):
        runtime=self.runtime()
        with TemporaryDirectory() as folder:
            Path(folder,'capture-status.json').write_text(json.dumps({'phase':'ready','directionFilter':'waiting-neutral'}))
            original_publish=runtime.publish
            def publish(**values):original_publish(**values);runtime.stop.set()
            runtime.publish=publish
            listener=SimpleNamespace(thread=SimpleNamespace(is_alive=lambda:True))
            with patch('rc003_bridge.runtime.DATA',Path(folder)),patch('rc003_bridge.rawinput.remote_device_count',return_value=1):await runtime.watch_inputs(listener)
        self.assertFalse(runtime.state['enhancedCaptureReady'])

    async def test_queued_old_press_cannot_use_new_configuration(self):
        runtime=self.runtime()
        permit=await runtime.command({'command':'direction-filter-permit'})
        await runtime.command({'command':'enhanced-edge','position':5,'down':True,'source':'filtered-remote','generation':permit['generation']})
        await runtime.command({'command':'reload-config','state':{'action':'new'}})
        self.assertTrue(runtime.awaiting_neutral)
        epoch,kind,data=runtime.queue.get_nowait()
        await runtime.input_edge('enhanced',*data)
        self.assertEqual(runtime.dispatcher.sent,[])
        await runtime.input_edge('enhanced',5,False)
        await runtime.input_edge('enhanced',5,True)
        self.assertEqual(runtime.dispatcher.sent,[('new',True)])

    async def test_freeze_worker_command_uses_role_entrypoint(self):
        from rc003_bridge.transport_process import worker_command
        import sys
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable','C:/app/Remote.exe'):
            self.assertEqual(worker_command(),['C:/app/Remote.exe','--module','rc003_bridge.transport_worker'])

    async def test_source_worker_owns_real_interpreter_not_venv_proxy(self):
        from rc003_bridge.transport_process import worker_command
        import sys
        with patch.object(sys,'frozen',False,create=True),patch.object(sys,'_base_executable','C:/Python/python.exe'),patch.object(sys,'executable','C:/venv/python.exe'):
            self.assertEqual(worker_command()[0],'C:/Python/python.exe')

    async def test_shutdown_closes_control_server_even_when_action_cleanup_fails(self):
        runtime=self.runtime();calls=[]
        async def cleanup():calls.append('cleanup');raise OSError('release failed')
        def close_dispatcher():calls.append('dispatcher');raise OSError('still owned')
        async def server_wait():calls.append('server-wait')
        runtime.cleanup_connection=cleanup;runtime.dispatcher.close=close_dispatcher
        listener=SimpleNamespace(stop=lambda:calls.append('listener'))
        server=SimpleNamespace(close=lambda:calls.append('server'),wait_closed=server_wait)
        with TemporaryDirectory() as folder,patch('rc003_bridge.runtime.CONTROL',Path(folder)/'control.json'):
            await runtime.finalize_run(listener,server)
        self.assertEqual(calls,['listener','cleanup','dispatcher','server','server-wait'])
        self.assertTrue(runtime.state['cleanupPending']);self.assertEqual(runtime.state['phase'],'stopped')


if __name__=='__main__':unittest.main()
