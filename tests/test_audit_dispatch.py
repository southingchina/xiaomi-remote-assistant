"""Audit regressions at native input/voice boundaries; never inject desktop input."""
import ctypes as C
import threading
import time
import unittest
from unittest.mock import patch

from rc003_bridge import standalone
from rc003_bridge.qwen import QwenIpcError, QwenState


def binding(kind, action, mode='tap', identity='daily:5'):
    return dict(standalone.COMMON, type=kind, action=action, mode=mode, actionId=identity)


class NativeSink:
    """Runs production INPUT encoding, replacing only user32.SendInput."""
    def __init__(self, refuse_up=0, refuse_mouse=None):
        self.accepted = []
        self.batches = []
        self.refuse_up = refuse_up
        self.refuse_mouse = dict(refuse_mouse or {})
        owner = self
        class Api:
            def __call__(self, count, pointer, size):
                events = C.cast(pointer, C.POINTER(owner.output.Input))
                owner.batches.append(count)
                for index in range(count):
                    event = events[index]
                    if event.type == 1:
                        vk, flags = event.payload.keyboard.vk, event.payload.keyboard.flags
                        if flags & 2 and owner.refuse_up:
                            owner.refuse_up -= 1
                            return index
                        owner.accepted.append(('key', vk, flags))
                    else:
                        flags = event.payload.mouse.flags
                        if owner.refuse_mouse.get(flags, 0):
                            owner.refuse_mouse[flags] -= 1
                            return index
                        owner.accepted.append(('mouse', flags, event.payload.mouse.data))
                return count
        api = Api()
        with patch.object(standalone.C, 'WinDLL') as library:
            library.return_value.SendInput = api
            self.output = standalone.WindowsInput()


class RecordingInput:
    def __init__(self):
        self.events = []
    def keyboard(self, vk, down):
        self.events.append(('key', vk, down))
    def mouse(self, action, dx=0, dy=0):
        self.events.append(('mouse', action, dx, dy))


class IdleThread:
    def __init__(self, **kwargs): pass
    def start(self): pass
    def join(self, **kwargs): pass
    def is_alive(self): return True


class InputAuditTests(unittest.TestCase):
    def test_enter_and_esc_use_one_batch_then_compensate_partial_down(self):
        for action, vk in [('Enter', 13), ('Esc', 27)]:
            with self.subTest(action=action):
                sink = NativeSink(refuse_up=1)
                dispatcher = standalone.NativeDispatcher(input_backend=sink.output)
                self.addCleanup(dispatcher.close)
                with self.assertRaises(OSError):
                    dispatcher.send(binding('keyboard', action), True)
                self.assertEqual(sink.batches, [2, 1])
                self.assertEqual(sink.accepted, [('key', vk, 0), ('key', vk, 2)])

    def test_failed_batch_compensation_is_retryable_without_duplicate_down(self):
        sink = NativeSink(refuse_up=2)
        dispatcher = standalone.NativeDispatcher(input_backend=sink.output)
        self.addCleanup(dispatcher.close)
        with self.assertRaises(OSError):
            dispatcher.send(binding('keyboard', 'Enter'), True)
        dispatcher.release_all()
        dispatcher.release_all()
        self.assertEqual(sink.batches[0], 2)
        self.assertEqual(sink.accepted, [('key', 13, 0), ('key', 13, 2)])

    def test_physical_up_retries_a_failed_batch_release(self):
        sink = NativeSink(refuse_up=2)
        dispatcher = standalone.NativeDispatcher(input_backend=sink.output)
        self.addCleanup(dispatcher.close)
        value = binding('keyboard', 'Esc')
        with self.assertRaises(OSError):
            dispatcher.send(value, True)
        dispatcher.send(value, False)
        self.assertEqual(sink.accepted, [('key', 27, 0), ('key', 27, 2)])

    def test_shared_hold_is_not_released_by_a_batched_tap(self):
        sink = NativeSink()
        dispatcher = standalone.NativeDispatcher(input_backend=sink.output)
        self.addCleanup(dispatcher.close)
        hold = binding('keyboard', 'Enter', 'hold', 'daily:5')
        dispatcher.send(hold, True)
        dispatcher.send(binding('keyboard', 'Enter', 'tap', 'daily:6'), True)
        self.assertEqual(sink.accepted, [('key', 13, 0)])
        dispatcher.send(hold, False)
        self.assertEqual(sink.accepted, [('key', 13, 0), ('key', 13, 2)])

    def test_mouse_release_retains_owner_until_native_retry_succeeds(self):
        sink = NativeSink(refuse_mouse={4: 1})
        dispatcher = standalone.NativeDispatcher(input_backend=sink.output)
        self.addCleanup(dispatcher.close)
        left = binding('mouse', 'left-click', 'hold')
        dispatcher.send(left, True)
        with self.assertRaises(OSError):
            dispatcher.send(left, False)
        self.assertIn('daily:5', dispatcher.held)
        dispatcher.release_all()
        self.assertEqual(sink.accepted, [('mouse', 2, 0), ('mouse', 4, 0)])
        self.assertFalse(dispatcher.held)

    def test_failed_left_release_does_not_skip_right_release(self):
        sink = NativeSink(refuse_mouse={4: 1})
        dispatcher = standalone.NativeDispatcher(input_backend=sink.output)
        self.addCleanup(dispatcher.close)
        dispatcher.send(binding('mouse', 'left-click', 'hold', 'daily:7'), True)
        dispatcher.send(binding('mouse', 'right-click', 'hold', 'daily:8'), True)
        with self.assertRaises(OSError):
            dispatcher.release_all()
        self.assertIn(('mouse', 16, 0), sink.accepted)
        dispatcher.release_all()
        self.assertEqual(sink.accepted.count(('mouse', 4, 0)), 1)
        self.assertEqual(sink.accepted.count(('mouse', 16, 0)), 1)


class WheelAuditTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('clock', __import__('inspect').signature(standalone.NativeDispatcher).parameters,
                      'The repeat scheduler needs an injectable monotonic clock')
        self.now = 0.0
        self.output = RecordingInput()
        self.dispatcher = standalone.NativeDispatcher(input_backend=self.output, clock=lambda: self.now)
        self.addCleanup(self.dispatcher.close)
        self.patch = patch.object(standalone.threading, 'Thread', IdleThread)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.value = binding('mouse', 'wheel-up', 'repeat')

    def test_lost_up_stops_at_thirty_seconds_without_final_notch(self):
        self.dispatcher.send(self.value, True)
        self.now = 29.9
        self.dispatcher._tick_repeats()
        self.assertEqual(len(self.output.events), 2)
        self.now = 30
        self.dispatcher._tick_repeats()
        self.now = 86400
        self.dispatcher._tick_repeats()
        self.assertEqual(len(self.output.events), 2)

    def test_duplicate_down_cannot_extend_or_restart_expired_hold(self):
        self.dispatcher.send(self.value, True)
        self.now = 29
        self.dispatcher.send(self.value, True)
        self.now = 30
        self.dispatcher._tick_repeats()
        self.dispatcher.send(self.value, True)
        self.now = 60
        self.dispatcher._tick_repeats()
        self.assertEqual(len(self.output.events), 1)

    def test_real_up_then_down_resets_deadline(self):
        self.dispatcher.send(self.value, True)
        self.now = 29
        self.dispatcher.send(self.value, False)
        self.dispatcher.send(self.value, True)
        self.now = 30
        self.dispatcher._tick_repeats()
        self.assertEqual(len(self.output.events), 3)
        self.now = 59
        self.dispatcher._tick_repeats()
        self.assertEqual(len(self.output.events), 3)


class OwnerVoice:
    supports_owners = True
    def __init__(self):
        self.calls = []
        self.stopping = threading.Event()
        self.allow_stop = threading.Event()
        self.allow_stop.set()
        self.refuse = 0
        self.stopped = threading.Event()
    def start(self, owner=None):
        self.calls.append(('start', owner))
    def toggle(self, owner=None):
        self.calls.append(('toggle', owner))
    def stop_owned(self, owner=None):
        self.calls.append(('stop', owner))
        self.stopping.set()
        self.allow_stop.wait(2)
        if self.refuse:
            self.refuse -= 1
            raise OSError('temporary voice stop failure')
        self.stopped.set()


class VoiceDispatchAuditTests(unittest.TestCase):
    def setUp(self):
        self.voice = OwnerVoice()
        self.output = RecordingInput()
        self.dispatcher = standalone.NativeDispatcher(self.voice, input_backend=self.output)
        self.addCleanup(self.dispatcher.close)
        self.remote = binding('voice', 'remote-mic', 'hold', 'daily:9')

    def test_each_remote_hold_has_unique_owner_separate_from_generic(self):
        self.dispatcher.send(self.remote, True)
        self.dispatcher.send(self.remote, False)
        self.dispatcher.send(self.remote, True)
        self.dispatcher.send(self.remote, False)
        self.dispatcher.send(binding('voice', 'qwen-generic'), True)
        self.dispatcher.release_all()
        starts = [owner for method, owner in self.voice.calls if method == 'start']
        generic = next(owner for method, owner in self.voice.calls if method == 'toggle')
        self.assertTrue(all(starts))
        self.assertEqual(len(set(starts)), 2)
        self.assertNotIn(generic, starts)
        stops = [owner for method, owner in self.voice.calls if method == 'stop']
        self.assertEqual(stops, [*starts, generic])

    def test_blocked_voice_stop_does_not_block_keyboard_dispatch(self):
        self.dispatcher.send(self.remote, True)
        self.voice.allow_stop.clear()
        releaser = threading.Thread(target=self.dispatcher.send, args=(self.remote, False))
        releaser.start()
        self.assertTrue(self.voice.stopping.wait(1))
        dispatched = threading.Event()
        sender = threading.Thread(target=lambda: (self.dispatcher.send(binding('keyboard', 'Enter'), True), dispatched.set()))
        sender.start()
        try:
            self.assertTrue(dispatched.wait(.3), 'Qwen confirmation must not hold the native dispatch lock')
        finally:
            self.voice.allow_stop.set()
            sender.join(2)
            releaser.join(2)

    def test_failed_remote_stop_is_retried_without_a_new_input_edge(self):
        self.dispatcher.send(self.remote, True)
        self.voice.refuse = 1
        with self.assertRaises(OSError):
            self.dispatcher.send(self.remote, False)
        self.assertTrue(self.voice.stopped.wait(1), 'An owned stop needs independent cleanup retry')
        self.assertEqual(len([c for c in self.voice.calls if c[0] == 'start']), 1)
        self.assertEqual(len([c for c in self.voice.calls if c[0] == 'stop']), 2)

    def test_generic_start_queued_after_cleanup_remains_owned_for_next_cleanup(self):
        generic = binding('voice', 'qwen-generic')
        self.dispatcher.send(generic, True)
        self.dispatcher.send(generic, False)
        self.voice.allow_stop.clear()
        cleaner = threading.Thread(target=self.dispatcher.release_all)
        cleaner.start()
        self.assertTrue(self.voice.stopping.wait(1))
        starter = threading.Thread(target=self.dispatcher.send, args=(generic, True))
        starter.start()
        try:
            self.voice.allow_stop.set()
            cleaner.join(2)
            starter.join(2)
            self.dispatcher.send(generic, False)
            self.dispatcher.release_all()
            self.assertEqual(len([c for c in self.voice.calls if c[0] == 'stop']), 2)
        finally:
            self.voice.allow_stop.set()

    def test_stale_remote_up_cannot_release_later_remote_press(self):
        self.dispatcher.send(self.remote, True)
        old = dict(self.remote)
        self.dispatcher.send(self.remote, False)
        self.dispatcher.send(self.remote, True)
        self.dispatcher.send(old, False)
        self.assertEqual(len([c for c in self.voice.calls if c[0] == 'stop']), 1)
        self.dispatcher.send(self.remote, False)
        self.assertEqual(len([c for c in self.voice.calls if c[0] == 'stop']), 2)


class QwenOwnershipIntegrationTests(unittest.TestCase):
    def test_old_generic_retry_cannot_stop_a_new_generic_recording(self):
        current = {'state': 0, 'session': '10:0', 'time': 0}
        calls = []
        session = [0]
        def toggle():
            calls.append(current['state'])
            if current['state'] == 0:
                session[0] += 1
                current.update(state=2, session=f'10:{session[0]}', time=current['time'] + 1)
            elif len(calls) > 2:
                current.update(state=0, time=current['time'] + 1)
            # First stop is accepted while its terminal log is delayed.
        qwen = QwenState(read_state=lambda: dict(current), send_toggle=toggle, timeout=0)
        dispatcher = standalone.NativeDispatcher(qwen, input_backend=RecordingInput())
        self.addCleanup(dispatcher.close)
        def press():
            value = binding('voice', 'qwen-generic')
            try:
                dispatcher.send(value, True)
            finally:
                dispatcher.send(value, False)
        press()
        with self.assertRaises(TimeoutError):
            press()
        current.update(state=0, time=current['time'] + 1)
        press()  # Confirms the previous cleanup without issuing toggle.
        press()  # Starts a distinct generic session.
        time.sleep(.35)
        self.assertEqual(current['state'], 2)
        self.assertEqual(current['session'], '10:2')
        self.assertEqual(calls, [0, 2, 0])

    def test_generic_stop_failure_retries_original_remote_owner_without_retoggle(self):
        current = {'state': 0, 'session': '10:0', 'time': 0}
        calls = []
        def toggle():
            calls.append(1)
            if current['state'] == 0:
                current.update(state=2, session='10:1', time=1)
            else:
                raise QwenIpcError('stop accepted but reply lost', sent=True)
        qwen = QwenState(read_state=lambda: dict(current), send_toggle=toggle, timeout=0)
        dispatcher = standalone.NativeDispatcher(qwen, input_backend=RecordingInput())
        self.addCleanup(dispatcher.close)
        remote = binding('voice', 'remote-mic', 'hold', 'daily:9')
        dispatcher.send(remote, True)
        with self.assertRaises(QwenIpcError):
            dispatcher.send(binding('voice', 'qwen-generic'), True)
        owner = remote['voiceOwner']
        self.assertTrue(qwen.needs_cleanup(owner))
        current.update(state=0, time=2)
        deadline = time.monotonic() + 1
        while qwen.owned is not None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNone(qwen.owned)
        self.assertEqual(calls, [1, 1])
        dispatcher.send(remote, False)
        dispatcher.release_all()
        self.assertEqual(calls, [1, 1])


if __name__ == '__main__':
    unittest.main()
