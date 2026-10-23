"""Retained protocol/recovery regressions with isolated storage and no live hardware."""

import importlib

import unittest

import audioop

import struct

import uuid

import tempfile

from pathlib import Path

import json

import subprocess

import sys

import asyncio

from unittest.mock import patch

def feature(name):
    try:
        module = importlib.import_module('rc003_bridge.core')
    except ModuleNotFoundError:
        raise AssertionError('The runnable RC003 protocol/dispatch core is missing')
    value = getattr(module, name, None)
    if value is None:
        raise AssertionError('Missing runtime feature: ' + name)
    return value

CAPS = bytes.fromhex('0b0100020300780000')


from types import SimpleNamespace
class IsolatedRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        resolver=SimpleNamespace(resolve=lambda p:{'actionId':str(p),'action':'test'},read_state=lambda:{})
        dispatcher=SimpleNamespace(send=lambda *a:None,release_all=lambda:None,close=lambda:None)
        values={'configuration':lambda:{'dispatchEnabled':True},'ProfileResolver':lambda:resolver,'NativeDispatcher':lambda **kw:dispatcher,'DATA':Path(self.directory.name),'STATUS':Path(self.directory.name)/'status.json'}
        for key,value in values.items():
            p=patch('rc003_bridge.runtime.'+key,value);p.start();self.addCleanup(p.stop)

class Rc003Tests(IsolatedRuntimeTest):

    def test_pcm_output_drains_samples_before_closing_endpoint(self):
            from rc003_bridge.audio import PcmOutput
            class Sink:
                def __init__(self, **kwargs): self.frames=[]; self.events=[]
                def start(self): self.events.append('start')
                def write(self, pcm): self.frames.append(pcm)
                def stop(self): self.events.append('stop')
                def abort(self): self.events.append('abort')
                def close(self): self.events.append('close')
            device = {'index':0,'sampleRate':16000,'channels':1}
            with patch('rc003_bridge.audio.select_output',return_value=device), patch('sounddevice.RawOutputStream',Sink):
                output = PcmOutput(); output.start(); sink=output.stream
                pcm=struct.pack('<240h',*range(240))
                output.write(pcm); output.finish()
            self.assertEqual(b''.join(sink.frames),pcm)
            self.assertEqual(sink.events,['start','stop','close'])
            self.assertFalse(output.thread.is_alive())

    def test_cleanup_still_releases_other_keys_when_voice_release_fails(self):
            from rc003_bridge.runtime import BridgeRuntime
            runtime = BridgeRuntime()
            attempts = []
            class Transport:
                async def close(self): attempts.append('closed')
            async def failed_voice(**kwargs): raise OSError('voice release failed')
            runtime.voice_up = failed_voice
            runtime.transport = Transport()
            runtime.note = lambda *a, **k: None
            runtime.router = feature('ActionRouter')(lambda p:{'actionId':str(p)},lambda b,d:attempts.append(d))
            runtime.router.edge(1,True)
            asyncio.run(runtime.cleanup_connection())
            self.assertEqual(attempts,[True,False,'closed'])
            self.assertIsNone(runtime.transport)

    def test_command_line_replay_checks_software_path_without_hardware(self):
            process = subprocess.run([sys.executable, '-m', 'rc003_bridge', 'self-test'], capture_output=True, text=True, encoding='utf8')
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads(process.stdout)
            self.assertTrue(report['passed'])
            self.assertEqual(report['voiceEdges'], ['down', 'up'])
            self.assertEqual(report['decodedSamples'], 240)
            self.assertFalse(report['hardwareVerified'])

    def test_raw_keyboard_input_filters_other_devices_and_ignores_voice_f5(self):
            try: module = importlib.import_module('rc003_bridge.rawinput')
            except ModuleNotFoundError: self.fail('Windows device-scoped input adapter is missing')
            decode = getattr(module, 'decode_keyboard', None)
            self.assertIsNotNone(decode)
            path = r'\\?\HID#Dev_VID&012717_PID&32b8_REV&00a4'
            self.assertEqual(decode(path, 0x26, 0), (1, True))
            self.assertEqual(decode(path, 0x26, 1), (1, False))
            self.assertIsNone(decode('USB keyboard', 0x26, 0))
            self.assertIsNone(decode(path, 0x74, 0))

    def session(self):
            protocol = feature('AtvvSession')()
            protocol.control(CAPS)
            return protocol

    def test_repeated_request_and_start_do_not_duplicate_voice_down(self):
            s = self.session()
            events = s.control(b'\x08') + s.control(b'\x08')
            events += s.control(bytes.fromhex('04030207'))
            events += s.control(bytes.fromhex('04030207'))
            self.assertEqual([e.kind for e in events].count('down'), 1)
            self.assertEqual([e.data for e in events if e.kind == 'write'], [b'\x0c\x00'])

    def test_release_then_old_close_ack_does_not_stop_the_next_hold(self):
            s = self.session()
            s.control(b'\x08'); s.control(bytes.fromhex('04030207'))
            self.assertEqual([e.kind for e in s.control(b'\x00\x02')].count('up'), 1)
            self.assertEqual(s.control(b'\x00\x00'), [])
            s.control(b'\x08'); s.control(bytes.fromhex('04030208'))
            self.assertEqual(s.control(b'\x00\x00'), [])
            self.assertTrue(s.held)

    def test_audio_decoder_matches_independent_stdlib_reference(self):
            s = self.session()
            s.control(bytes.fromhex('04030207'))
            pcm = struct.pack('<240h', *[int(15000 * ((i % 40) / 20 - 1)) for i in range(240)])
            encoded, _ = audioop.lin2adpcm(pcm, 2, (0, 0))
            expected, _ = audioop.adpcm2lin(encoded, 2, (0, 0))
            # audioop's independently implemented wire format is already high-first.
            high_first = encoded
            self.assertEqual(s.audio(high_first[:17]), b'')
            self.assertEqual(s.audio(high_first[17:]), expected)
            s.control(b'\x00\x02')
            self.assertEqual(s.audio(high_first), b'')

    def test_disconnect_releases_voice_and_drops_stale_audio(self):
            s = self.session(); s.control(b'\x08')
            events = s.disconnect()
            self.assertEqual([e.kind for e in events].count('up'), 1)
            self.assertFalse(s.ready)
            self.assertEqual(s.audio(bytes(120)), b'')
            self.assertEqual(s.disconnect(), [])

    def test_invalid_caps_never_opens_microphone(self):
            s = feature('AtvvSession')()
            with self.assertRaises(ValueError):
                s.control(bytes.fromhex('0b0100010300780000'))
            self.assertEqual(s.control(b'\x08'), [])

    def test_mapping_change_during_hold_releases_original_action(self):
            first, second = str(uuid.uuid4()), str(uuid.uuid4())
            current = {'actionId': first, 'action': 'test.audit'}
            sent = []
            router = feature('ActionRouter')(lambda position: dict(current), lambda binding, down: sent.append((binding['actionId'], down)))
            router.edge(4, True)
            current['actionId'] = second
            router.edge(4, True)
            router.edge(4, False)
            self.assertEqual(sent, [(first, True), (first, False)])

    def test_failed_keyup_is_retained_for_cleanup_retry(self):
            attempts = []
            def send(binding, down):
                attempts.append(down)
                if attempts == [True, False]:
                    raise OSError('temporary dispatch error')
            router = feature('ActionRouter')(lambda pos: {'actionId': str(uuid.uuid4()), 'action': 'test'}, send)
            router.edge(0, True)
            with self.assertRaises(OSError): router.edge(0, False)
            router.release_all()
            self.assertEqual(attempts, [True, False, False])
            self.assertEqual(router.held, {})

    def test_hid_reports_produce_individual_edges_including_three_special_keys(self):
            decoder = feature('HidKeys')()
            report = lambda keys: b'\x01\x00\x00' + b''.join(k.to_bytes(2, 'little') for k in keys)
            self.assertEqual(decoder.feed(report([0xF1, 0x80, 0])), [(6, True), (10, True)])
            self.assertEqual(decoder.feed(report([0, 0, 0])), [(6, False), (10, False)])
            self.assertEqual(decoder.feed(report([0x3E, 0, 0])), [])

import asyncio

import importlib

import json

from pathlib import Path

import tempfile

import sys

import subprocess

import io

from contextlib import redirect_stdout

import unittest

from unittest.mock import patch

class NativeOperation:
    """WinRT cancellation can remain pending until the radio responds."""
    cancelled = False

    def __init__(self, value=None):
        self.value = value
        self.callback = None

    @property
    def completed(self):
        raise NotImplementedError('PyWinRT delegates are writable but not readable')

    @completed.setter
    def completed(self, callback):
        self.callback = callback

    def cancel(self):
        self.cancelled = True

    def get_results(self):
        return self.value

    def finish(self):
        self.callback(self, 1)

    def __await__(self):
        from winrt.runtime._internals import wrap_async
        return wrap_async(self).__await__()

class RecoveryTests(IsolatedRuntimeTest):

    def test_busy_audio_cannot_starve_the_voice_session_stop_deadline(self):
            from rc003_bridge.runtime import BridgeRuntime
            from rc003_bridge.core import AtvvSession
            import time
            async def scenario():
                runtime=BridgeRuntime();runtime.epoch=1
                session=runtime.session=AtvvSession()
                session.ready=session.held=session.streaming=True
                session.started=time.monotonic()-181;session.last_audio=time.monotonic()
                sent=[]
                class Transport:
                    async def write(self,value):sent.append(value)
                runtime.transport=Transport()
                async def up():sent.append('up');runtime.stop.set()
                runtime.voice_up=up
                for _ in range(100):runtime.queue.put_nowait((1,'audio',bytes(120)))
                await asyncio.wait_for(runtime.consume_connection(),.1)
                self.assertEqual(sent,[b'\x0d\x00','up'])
                self.assertFalse(session.streaming)
            asyncio.run(scenario())

    def test_input_listener_restart_discards_previous_startup_error(self):
            from rc003_bridge.rawinput import RawInputListener
            listener=RawInputListener(lambda *args:None)
            listener.error='old listener failure';listener.ready.set()
            listener._run=lambda:listener.ready.set()
            try:listener.start()
            finally:listener.stop()
            self.assertIsNone(listener.error)

    def test_watchdog_respects_an_explicit_manual_stop(self):
            from rc003_bridge.__main__ import main
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder)/'bridge-paused.json').write_text('{"paused":true}')
                output=io.StringIO()
                with patch('rc003_bridge.runtime.DATA',Path(folder)),patch.object(sys,'argv',['rc003_bridge','ensure']),redirect_stdout(output):
                    main()
                self.assertEqual(json.loads(output.getvalue()),{'paused':True})

    def test_winrt_deadline_does_not_wait_for_native_cancellation(self):
            module = importlib.import_module('rc003_bridge.bluetooth')
            wait = getattr(module, 'wait_operation', None)
            self.assertIsNotNone(wait, 'Native GATT deadlines still wait indefinitely for cancellation')
    
            async def scenario():
                closed = []
                operation = NativeOperation('late device')
                task = asyncio.create_task(wait(operation, .02, closed.append))
                done, _ = await asyncio.wait([task], timeout=.15)
                self.assertIn(task, done, 'Reconnect deadline is blocked by native cancellation')
                with self.assertRaises(TimeoutError):
                    await task
                self.assertTrue(operation.cancelled)
                operation.finish()
                await asyncio.sleep(0)
                self.assertEqual(closed, ['late device'])
                next_op = NativeOperation('reconnected')
                asyncio.get_running_loop().call_soon(next_op.finish)
                self.assertEqual(await wait(next_op, .1), 'reconnected')
            asyncio.run(scenario())

    def test_shutdown_does_not_wait_for_native_cancellation(self):
            wait = getattr(importlib.import_module('rc003_bridge.bluetooth'), 'wait_operation', None)
            self.assertIsNotNone(wait)
    
            async def scenario():
                operation = NativeOperation()
                task = asyncio.create_task(wait(operation, 10))
                await asyncio.sleep(0)
                task.cancel()
                done, _ = await asyncio.wait([task], timeout=.1)
                self.assertIn(task, done)
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(operation.cancelled)
                operation.finish()
                await asyncio.sleep(0)
            asyncio.run(scenario())

    def test_status_file_lock_cannot_prevent_releasing_held_keys(self):
            from rc003_bridge.runtime import BridgeRuntime
            from rc003_bridge.core import ActionRouter
            runtime = BridgeRuntime()
            sent = []
            runtime.router = ActionRouter(lambda pos: {'actionId': str(pos), 'action': 'audit'},
                                          lambda binding, down: sent.append(down))
            runtime.router.edge(10, True)
            with patch('rc003_bridge.runtime.write_json', side_effect=PermissionError('file held by reader')):
                asyncio.run(runtime.cleanup_connection())
            self.assertEqual(sent, [True, False])
            self.assertFalse(runtime.router.held)
            self.assertIn('statusWriteError', runtime.state)

    def test_atomic_status_retries_temporary_windows_reader_lock(self):
            from rc003_bridge.runtime import write_json
            replace = Path.replace
            attempts = []
    
            def locked_once(source, target):
                attempts.append(source)
                if len(attempts) == 1:
                    raise PermissionError('Windows reader has no delete sharing')
                return replace(source, target)
    
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'status.json'
                with patch.object(Path, 'replace', locked_once):
                    write_json(path, {'phase': 'ready'})
                self.assertEqual(json.loads(path.read_text()), {'phase': 'ready'})
                self.assertEqual(len(attempts), 2)
                self.assertEqual(list(Path(folder).iterdir()), [path])
