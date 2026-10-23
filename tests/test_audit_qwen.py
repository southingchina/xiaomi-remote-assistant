"""Audit regressions. All metadata and pipe endpoints are isolated test fixtures."""
import ctypes as C
from ctypes import wintypes as W
import os
import threading
import time
import unittest
import uuid

from rc003_bridge import qwen


def state(value=0, session='7:1', stamp=100):
    return {'state': value, 'session': session, 'time': stamp}


def transaction(stage, session=123, stamp=100, pid=7):
    return f'component=utility pid={pid} monotonic_ms={stamp} voice_shortcut_txn stage={stage} session={session}'


class Recording:
    def __init__(self):
        self.current = state()
        self.calls = 0

    def read(self):
        return dict(self.current)

    def toggle(self):
        self.calls += 1
        self.current = state(0 if self.current['state'] == 2 else 2,
                             self.current['session'] if self.current['state'] == 2 else f'7:{self.calls + 1}',
                             self.current['time'] + 1)

    def voice(self, **kwargs):
        return qwen.QwenState(read_state=self.read, send_toggle=self.toggle, timeout=0, **kwargs)


class AuditQwenTests(unittest.TestCase):
    def test_later_commit_for_same_session_cannot_confirm_a_new_start(self):
        before = state(0, '7:123', 100)
        voice = qwen.QwenState(read_state=lambda: state(2, '7:123', 200), timeout=0)
        with self.assertRaises(TimeoutError):
            voice.wait_started(before)

    def test_new_monotonic_session_can_follow_legacy_epoch_timestamp(self):
        before = state(0, '2329', 1792750000000)
        voice = qwen.QwenState(read_state=lambda: state(2, '7:123', 3456789), timeout=0)
        self.assertEqual(voice.wait_started(before)['session'], '7:123')

    def test_legacy_id_field_is_accepted_by_wait_started(self):
        voice = qwen.QwenState(read_state=lambda: state(2, '7:123', 3456789), timeout=0)
        self.assertEqual(voice.wait_started({'id':'2329', 'recording':False, 'time':1792750000000})['session'], '7:123')

    def test_new_begin_handoff_and_terminal_stages_match_audited_log_contract(self):
        for stage in ('finished', 'cancel', 'abort', 'start_failed', 'runtime_terminal'):
            with self.subTest(stage=stage):
                log = '\n'.join((transaction('commit', 111, 50), transaction('begin'),
                    'component=voice_runtime pid=7 monotonic_ms=120 event=runtime_handoff_complete reason=accepted status=0',
                    transaction(stage, stamp=130)))
                self.assertEqual(qwen.parse_surface_state(log), state(0, '7:123', 130))

    def test_handoff_requires_matching_pid_accepted_status_and_valid_time_window(self):
        for pid, stamp, reason, status in ((8,120,'accepted','0'), (7,99,'accepted','0'),
                (7,5101,'accepted','0'), (7,120,'rejected','0'), (7,120,'accepted','1')):
            with self.subTest(pid=pid, stamp=stamp, reason=reason, status=status):
                log = transaction('begin') + f'\ncomponent=voice_runtime pid={pid} monotonic_ms={stamp} event=runtime_handoff_complete reason={reason} status={status}'
                self.assertEqual(qwen.parse_surface_state(log)['state'], 1)

    def test_pending_stop_cannot_be_overridden_by_duplicate_start(self):
        recording = Recording()
        voice = recording.voice()
        voice.start()
        voice._read = lambda: (_ for _ in ()).throw(OSError('temporary unreadable log'))
        with self.assertRaises(OSError): voice.stop_owned()
        voice._read = recording.read
        with self.assertRaisesRegex(RuntimeError, 'previous.*stop'):
            voice.start()
        voice.stop_owned()
        self.assertEqual(recording.calls, 2)

    def test_same_session_starting_state_retains_cleanup_and_never_toggles(self):
        recording = Recording(); voice = recording.voice(); voice.start()
        recording.current['state'] = 1
        with self.assertRaises(RuntimeError): voice.stop_owned()
        self.assertEqual(voice.owned, '7:2')
        self.assertEqual(recording.calls, 1)
        recording.current['state'] = 2
        voice.stop_owned()
        self.assertEqual(recording.calls, 2)

    def test_different_owner_release_cannot_stop_current_recording(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        voice.stop_owned(owner='generic')
        self.assertEqual(recording.calls, 1)
        self.assertEqual(voice.owned_owner, 'remote-1')
        voice.stop_owned(owner='remote-1')
        self.assertEqual(recording.calls, 2)

    def test_old_remote_release_cannot_stop_later_generic_recording(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        voice.toggle(owner='generic')
        voice.toggle(owner='generic')
        voice.stop_owned(owner='remote-1')
        self.assertEqual(recording.calls, 3)
        self.assertEqual(voice.owned_owner, 'generic')
        self.assertEqual(recording.current['state'], 2)

    def test_old_generic_cleanup_cannot_stop_later_remote_recording(self):
        recording = Recording(); voice = recording.voice(); voice.toggle(owner='generic')
        voice.toggle(owner='generic'); voice.start(owner='remote-2')
        voice.stop_owned(owner='generic')
        self.assertEqual(recording.calls, 3)
        self.assertEqual(voice.owned_owner, 'remote-2')

    def test_duplicate_start_from_a_different_owner_cannot_claim_same_session(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        with self.assertRaises(RuntimeError): voice.start(owner='remote-2')
        voice.stop_owned(owner='remote-2')
        self.assertEqual(recording.calls, 1)

    def test_toggle_retries_pending_confirmation_instead_of_reopening_after_late_terminal(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='generic')
        def stop_loses_reply():
            recording.toggle()
            raise TimeoutError('reply lost')
        voice._toggle = stop_loses_reply
        with self.assertRaises(TimeoutError): voice.toggle(owner='generic')
        voice.toggle(owner='generic')
        self.assertEqual(recording.calls, 2)
        self.assertEqual(recording.current['state'], 0)

    def test_owned_stop_failure_is_retryable_only_by_original_owner(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        voice._toggle = lambda: (_ for _ in ()).throw(qwen.QwenIpcError('absent', sent=False))
        with self.assertRaises(qwen.QwenIpcError): voice.stop_owned(owner='remote-1')
        self.assertTrue(voice.needs_cleanup(owner='remote-1'))
        self.assertFalse(voice.needs_cleanup(owner='generic'))
        voice._toggle = recording.toggle
        voice.stop_owned(owner='remote-1')
        self.assertFalse(voice.needs_cleanup(owner='remote-1'))

    def test_missing_handled_ack_is_uncertain_not_definite_rejection(self):
        from unittest.mock import patch
        voice = qwen.QwenState()
        with patch.object(qwen, 'pipe_request', return_value={'fields':{'ok':'1'}}):
            with self.assertRaises(qwen.QwenIpcError) as caught: voice._send_toggle()
        self.assertTrue(caught.exception.sent)
        self.assertEqual(caught.exception.outcome, 'unknown')

    def test_explicit_unhandled_ack_is_rejected_and_retryable(self):
        from unittest.mock import patch
        voice = qwen.QwenState()
        with patch.object(qwen, 'pipe_request', return_value={'fields':{'ok':'1', 'handled':'0'}}):
            with self.assertRaises(qwen.QwenIpcError) as caught: voice._send_toggle()
        self.assertFalse(caught.exception.sent)
        self.assertEqual(caught.exception.outcome, 'rejected')

    def test_unreadable_owned_state_retries_without_affecting_new_foreign_session(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        voice._read = lambda: (_ for _ in ()).throw(OSError('log temporarily inaccessible'))
        with self.assertRaises(OSError): voice.stop_owned(owner='remote-1')
        self.assertTrue(voice.needs_cleanup(owner='remote-1'))
        recording.current = state(2, '99:foreign', 999)
        voice._read = recording.read
        voice.stop_owned(owner='remote-1')
        self.assertEqual(recording.calls, 1)
        self.assertIsNone(voice.owned)
        self.assertFalse(voice.needs_cleanup(owner='remote-1'))

    def test_explicit_generic_stop_retries_under_original_remote_owner(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        voice._toggle = lambda: (_ for _ in ()).throw(qwen.QwenIpcError('refused', sent=False, outcome='rejected'))
        with self.assertRaises(qwen.QwenIpcError): voice.toggle(owner='generic')
        self.assertEqual(voice.owned_owner, 'remote-1')
        self.assertTrue(voice.needs_cleanup(owner='remote-1'))
        self.assertFalse(voice.needs_cleanup(owner='generic'))
        voice._toggle = recording.toggle
        voice.stop_owned(owner='generic')
        self.assertEqual(recording.calls, 1)
        voice.stop_owned(owner='remote-1')
        self.assertEqual(recording.calls, 2)

    def test_concurrent_stop_requests_send_only_one_toggle(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        barrier = threading.Barrier(3); errors = []
        def stop():
            barrier.wait()
            try: voice.stop_owned(owner='remote-1')
            except BaseException as error: errors.append(error)
        workers = [threading.Thread(target=stop) for _ in range(2)]
        for worker in workers: worker.start()
        barrier.wait()
        for worker in workers: worker.join(1)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(recording.calls, 2)

    def test_accepted_stop_keeps_ownership_while_same_session_reverts_to_starting(self):
        recording = Recording(); voice = recording.voice(); voice.start(owner='remote-1')
        def stop_pending():
            recording.calls += 1
            recording.current['state'] = 1
        voice._toggle = stop_pending
        with self.assertRaises(TimeoutError): voice.stop_owned(owner='remote-1')
        self.assertEqual(voice.owned, '7:2')
        self.assertTrue(voice.needs_cleanup(owner='remote-1'))
        recording.current['state'] = 2
        with self.assertRaises(TimeoutError): voice.stop_owned(owner='remote-1')
        self.assertEqual(recording.calls, 2)
        recording.current['state'] = 3
        voice.stop_owned(owner='remote-1')
        self.assertIsNone(voice.owned)


class PipeSimulator:
    """A real local Windows pipe, never the Qianwen production endpoint."""
    def __init__(self, handler):
        self.endpoint = r'\\.\pipe\RC003AuditTest_' + uuid.uuid4().hex
        self.handler = handler
        self.calls = 0
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.errors = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        if not self.ready.wait(3): raise RuntimeError('Test pipe did not start')
        return self

    def __exit__(self, *args):
        self.closed.set()
        self.thread.join(3)
        if self.thread.is_alive(): raise RuntimeError('Test pipe did not close')
        if self.errors: raise self.errors[0]

    def run(self):
        kernel = C.WinDLL('kernel32', use_last_error=True)
        def bind(name, result, *args):
            function = getattr(kernel, name); function.restype = result; function.argtypes = list(args); return function
        create = bind('CreateNamedPipeW', W.HANDLE, W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_void_p)
        connect = bind('ConnectNamedPipe', W.BOOL, W.HANDLE, C.c_void_p)
        read = bind('ReadFile', W.BOOL, W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p)
        write = bind('WriteFile', W.BOOL, W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p)
        disconnect = bind('DisconnectNamedPipe', W.BOOL, W.HANDLE)
        close = bind('CloseHandle', W.BOOL, W.HANDLE)
        # Nonblocking message mode keeps teardown bounded even after one request.
        try:
            while not self.closed.is_set():
                handle = create(self.endpoint, 3, 7, 1, 65536, 65536, 100, None)
                if handle == C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
                self.ready.set()
                try:
                    while not self.closed.is_set():
                        if connect(handle, None) or C.get_last_error() == 535: break
                        if C.get_last_error() not in (536, 232): raise C.WinError(C.get_last_error())
                        time.sleep(.002)
                    received = bytearray()
                    while not self.closed.is_set():
                        buffer = C.create_string_buffer(65536); count = W.DWORD()
                        ok = read(handle, buffer, len(buffer), C.byref(count), None)
                        if count.value: received.extend(buffer.raw[:count.value]); break
                        if not ok and C.get_last_error() not in (232, 233): raise C.WinError(C.get_last_error())
                        time.sleep(.002)
                    if self.closed.is_set(): return
                    self.calls += 1
                    response = self.handler(qwen.decode_packet(bytes(received)), self.calls)
                    if response is None:
                        self.closed.wait(.08)
                    else:
                        buffer = C.create_string_buffer(response); count = W.DWORD()
                        if not write(handle, buffer, len(response), C.byref(count), None): raise C.WinError(C.get_last_error())
                        # Permit the client to consume the response before disconnect.
                        time.sleep(.02)
                finally:
                    disconnect(handle); close(handle)
        except BaseException as error:
            self.errors.append(error); self.ready.set()


@unittest.skipUnless(os.name == 'nt', 'Windows named pipe integration')
class AuditQwenPipeTests(unittest.TestCase):
    def test_absent_pipe_is_definitely_not_sent(self):
        endpoint = r'\\.\pipe\RC003AuditAbsent_' + uuid.uuid4().hex
        with self.assertRaises(qwen.QwenIpcError) as caught: qwen.pipe_request(endpoint, 50, timeout=.03)
        self.assertFalse(caught.exception.sent)
        self.assertEqual(caught.exception.outcome, 'not_sent')

    def test_real_pipe_missing_ok_is_unknown_and_explicit_refusal_is_rejected(self):
        for body, outcome, sent in (('diagnostic=incomplete\n', 'unknown', True),
                                    ('ok=0\ndiagnostic=refused\n', 'rejected', False)):
            with self.subTest(outcome=outcome):
                with PipeSimulator(lambda request, calls: qwen.encode_packet(request['command'], body, request['id'])) as server:
                    with self.assertRaises(qwen.QwenIpcError) as caught: qwen.pipe_request(server.endpoint, 50, timeout=.5)
                    self.assertEqual(caught.exception.outcome, outcome)
                    self.assertEqual(caught.exception.sent, sent)

    def test_real_pipe_mismatched_rejection_remains_unknown(self):
        with PipeSimulator(lambda request, calls: qwen.encode_packet(request['command'], 'ok=0\n', request['id'] + 1)) as server:
            with self.assertRaises(qwen.QwenIpcError) as caught: qwen.pipe_request(server.endpoint, 50, timeout=.5)
            self.assertTrue(caught.exception.sent)
            self.assertEqual(caught.exception.outcome, 'unknown')

    def test_real_pipe_corrupt_ack_is_unknown(self):
        def malformed(request, calls):
            return b'FAIL' + qwen.encode_packet(request['command'], 'ok=1\n', request['id'])[4:]
        with PipeSimulator(malformed) as server:
            with self.assertRaises(qwen.QwenIpcError) as caught: qwen.pipe_request(server.endpoint, 50, timeout=.5)
            self.assertTrue(caught.exception.sent)
            self.assertEqual(caught.exception.outcome, 'unknown')

    def test_real_pipe_executed_stop_with_lost_ack_and_stale_log_never_reopens(self):
        observed = state(2, '7:2', 101)
        actual = {'recording': True}
        def execute_and_drop(request, calls):
            actual['recording'] = not actual['recording']
            return None
        with PipeSimulator(execute_and_drop) as server:
            voice = qwen.QwenState(read_state=lambda: dict(observed),
                send_toggle=lambda: qwen.pipe_request(server.endpoint, 50, timeout=.03), timeout=0)
            voice.owned = '7:2'
            with self.assertRaises(qwen.QwenIpcError) as caught: voice.stop_owned()
            self.assertTrue(caught.exception.sent)
            with self.assertRaises(TimeoutError): voice.stop_owned()
            self.assertEqual(server.calls, 1)
            self.assertFalse(actual['recording'])
            observed['state'] = 0
            voice.stop_owned()
            self.assertIsNone(voice.owned)


if __name__ == '__main__': unittest.main()
