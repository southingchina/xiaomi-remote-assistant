"""Standalone dispatch tests; every native side effect is replaced at its boundary."""
import copy
import importlib
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

try:
    standalone = importlib.import_module('rc003_bridge.standalone')
except ModuleNotFoundError:
    standalone = None


def binding(kind, action, mode='tap', context='daily:5', **extra):
    return dict(type=kind, action=action, mode=mode, actionId=context,
                delay=50, interval=20, speed=6, shortcut='', target='', **extra)


class RecordingInput:
    def __init__(self):
        self.events = []
        self.changed = threading.Event()

    def keyboard(self, vk, down):
        self.events.append(('key', vk, down))
        self.changed.set()

    def mouse(self, action, dx=0, dy=0):
        self.events.append(('mouse', action, dx, dy))
        self.changed.set()


class FakeQwen:
    def __init__(self):
        self.events = []

    def start(self):
        self.events.append('start')

    def stop_owned(self):
        self.events.append('stop_owned')

    def toggle(self):
        self.events.append('toggle')


class FocusProcess:
    def __init__(self, blocked=False):
        self.blocked = blocked
        self.entered = threading.Event()
        self.finished = threading.Event()
        self.terminated = False
        self.returncode = None

    def communicate(self, timeout=None):
        self.entered.set()
        if self.blocked:
            self.finished.wait(2)
        if self.returncode is None:
            self.returncode = 0
        return b'', b''

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.finished.set()

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        self.finished.wait(.01)
        return self.returncode

    def poll(self):
        return self.returncode


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(standalone, 'Standalone configuration/dispatcher is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'profiles.json'
        self.resolver = standalone.ProfileResolver(self.path)

    def test_defaults_match_preview_and_resolve_is_detached(self):
        state = self.resolver.read_state()
        self.assertEqual((state['version'], state['current']), (1, 'daily'))
        self.assertEqual(set(state['profiles'][0]['bindings']), {str(i) for i in range(13)})
        self.assertEqual(self.resolver.resolve(9)['action'], 'remote-mic')
        self.assertEqual(self.resolver.resolve(6)['interval'], 33)
        value = self.resolver.resolve(7)
        self.assertEqual((value['actionId'], value['mode']), ('daily:7', 'hold'))
        value['action'] = 'right-click'
        self.assertEqual(self.resolver.resolve(7)['action'], 'left-click')

    def test_all_profiles_save_reload_and_current_selection(self):
        state = self.resolver.read_state()
        other = copy.deepcopy(state['profiles'][0])
        other['id'], other['name'] = 'work', '工作'
        other['bindings']['5']['action'] = 'Delete'
        state['profiles'].append(other)
        state['current'] = 'work'
        self.resolver.save_state(state)
        fresh = standalone.ProfileResolver(self.path)
        self.assertEqual(fresh.resolve(5)['action'], 'Delete')
        self.assertEqual(fresh.resolve(5)['actionId'], 'work:5')
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), state)

    def test_rejects_incomplete_profiles_without_changing_disk(self):
        self.resolver.save_state(self.resolver.read_state())
        before = self.path.read_bytes()
        state = self.resolver.read_state()
        del state['profiles'][0]['bindings']['12']
        with self.assertRaises(ValueError):
            self.resolver.save_state(state)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.resolver.resolve(12)['action'], 'Esc')

    def test_failed_atomic_replace_preserves_previous_memory_and_file(self):
        self.resolver.save_state(self.resolver.read_state())
        before = self.path.read_bytes()
        state = self.resolver.read_state()
        state['profiles'][0]['name'] = 'changed'
        with patch.object(standalone.os, 'replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                self.resolver.save_state(state)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.resolver.read_state()['profiles'][0]['name'], '日常控制')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_rejects_invalid_action_mode_numeric_and_voice_placement(self):
        for patch_value in [dict(type='unknown'), dict(action='bad'), dict(mode='hold'),
                            dict(speed=float('nan')), dict(speed=True), dict(interval=19),
                            dict(delay=2001), dict(delay=True)]:
            with self.subTest(value=patch_value):
                state = self.resolver.read_state()
                state['profiles'][0]['bindings']['1'].update(patch_value)
                with self.assertRaises(ValueError):
                    self.resolver.save_state(state)
        state = self.resolver.read_state()
        state['profiles'][0]['bindings']['5'] = copy.deepcopy(state['profiles'][0]['bindings']['9'])
        with self.assertRaises(ValueError):
            self.resolver.save_state(state)

    def test_rejects_missing_current_duplicate_ids_and_unsupported_version(self):
        for mutate in [lambda s: s.update(current='missing'), lambda s: s.update(version=2),
                       lambda s: s['profiles'].append(copy.deepcopy(s['profiles'][0]))]:
            state = self.resolver.read_state()
            mutate(state)
            with self.assertRaises(ValueError):
                self.resolver.save_state(state)

    def test_custom_shortcut_and_url_are_validated_before_save(self):
        for value in [dict(type='keyboard', action='custom', shortcut='Ctrl+Unknown'),
                      dict(type='keyboard', action='custom', shortcut='Ctrl++V'),
                      dict(type='keyboard', action='custom', shortcut='  '),
                      dict(type='app', action='url', target='file:///C:/Windows'),
                      dict(type='app', action='url', target='https://'),
                      dict(type='app', action='program', target='')]:
            state = self.resolver.read_state()
            state['profiles'][0]['bindings']['5'].update(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.resolver.save_state(state)

    def test_invalid_existing_file_is_reported_and_not_overwritten(self):
        self.path.write_text('{bad', encoding='utf-8')
        with self.assertRaises(ValueError):
            standalone.ProfileResolver(self.path)
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{bad')

    def test_invalid_position_is_rejected(self):
        for position in [-1, 13, True, '1']:
            with self.subTest(position=position), self.assertRaises(ValueError):
                self.resolver.resolve(position)

    def test_malformed_json_field_types_are_validation_errors(self):
        for field, value in [('action', []), ('mode', {}), ('type', {})]:
            state = self.resolver.read_state()
            state['profiles'][0]['bindings']['5'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.resolver.save_state(state)
        state = self.resolver.read_state()
        state['current'] = []
        with self.assertRaises(ValueError):
            self.resolver.save_state(state)


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(standalone, 'Standalone configuration/dispatcher is not implemented')
        self.output = RecordingInput()
        self.qwen = FakeQwen()
        self.dispatcher = standalone.NativeDispatcher(self.qwen, input_backend=self.output)
        self.addCleanup(self.dispatcher.close)

    def wait_events(self, count):
        deadline = time.monotonic() + 1
        while len(self.output.events) < count and time.monotonic() < deadline:
            self.output.changed.wait(.02)
            self.output.changed.clear()
        self.assertGreaterEqual(len(self.output.events), count)

    def test_construction_and_disabled_edges_have_no_effects(self):
        value = binding('disabled', 'none')
        self.dispatcher.send(value, True)
        self.dispatcher.send(value, False)
        self.dispatcher.release_all()
        self.assertEqual(self.output.events, [])
        self.assertEqual(self.qwen.events, [])

    def test_shortcut_modifiers_press_before_key_and_release_in_reverse(self):
        value = binding('keyboard', 'custom')
        value['shortcut'] = 'V + Shift + Ctrl'
        self.dispatcher.send(value, True)
        self.dispatcher.send(value, True)
        self.dispatcher.send(value, False)
        self.assertEqual(self.output.events, [('key', 0x11, True), ('key', 0x10, True),
                         ('key', ord('V'), True), ('key', ord('V'), False),
                         ('key', 0x10, False), ('key', 0x11, False)])

    def test_release_uses_down_snapshot_after_binding_edit(self):
        value = binding('keyboard', 'custom', 'hold')
        value['shortcut'] = 'Ctrl+A'
        self.dispatcher.send(value, True)
        value.update(type='disabled', action='none', shortcut='')
        self.dispatcher.send(value, False)
        self.assertEqual(self.output.events[-2:], [('key', 65, False), ('key', 17, False)])

    def test_overlapping_shortcuts_keep_shared_modifier_until_last_owner(self):
        first = binding('keyboard', 'custom', 'hold')
        first['shortcut'] = 'Ctrl+A'
        second = copy.deepcopy(first)
        second.update(actionId='daily:6', shortcut='Ctrl+B')
        self.dispatcher.send(first, True)
        self.dispatcher.send(second, True)
        self.dispatcher.send(first, False)
        self.assertNotIn(('key', 17, False), self.output.events)
        self.dispatcher.send(second, False)
        self.assertEqual(self.output.events.count(('key', 17, True)), 1)
        self.assertEqual(self.output.events[-1], ('key', 17, False))

    def test_hold_click_is_balanced_and_release_all_is_idempotent(self):
        value = binding('mouse', 'left-click', 'hold')
        self.dispatcher.send(value, True)
        self.dispatcher.send(value, True)
        self.dispatcher.release_all()
        self.dispatcher.release_all()
        self.dispatcher.send(value, False)
        self.assertEqual(self.output.events, [('mouse', 'left-down', 0, 0), ('mouse', 'left-up', 0, 0)])

    def test_wheel_repeats_then_stops_on_up(self):
        value = binding('mouse', 'wheel-down', 'repeat')
        self.dispatcher.send(value, True)
        self.assertEqual(self.output.events, [('mouse', 'wheel', -120, 0)])
        self.wait_events(3)
        self.dispatcher.send(value, False)
        count = len(self.output.events)
        time.sleep(.08)
        self.assertEqual(len(self.output.events), count)

    def test_backspace_repeat_stops_on_close_and_closed_dispatcher_rejects_down(self):
        value = binding('keyboard', 'Backspace', 'repeat')
        self.dispatcher.send(value, True)
        self.wait_events(4)
        self.dispatcher.close()
        count = len(self.output.events)
        time.sleep(.08)
        self.assertEqual(len(self.output.events), count)
        self.assertEqual(self.output.events[-1], ('key', 8, False))
        with self.assertRaises(RuntimeError):
            self.dispatcher.send(value, True)

    def test_mouse_movement_uses_relative_mouse_events_and_stops_on_release_all(self):
        value = binding('mouse', 'move-left', 'repeat')
        value.update(delay=2000, interval=1000)
        self.dispatcher.send(value, True)
        self.assertTrue(self.output.events, 'Movement must start on the down edge')
        self.wait_events(2)
        self.dispatcher.release_all()
        count = len(self.output.events)
        time.sleep(.08)
        self.assertEqual(len(self.output.events), count)
        self.assertTrue(all(e[0:2] == ('mouse', 'move') and e[2] < 0 and e[3] == 0 for e in self.output.events))

    def test_double_click_emits_two_balanced_clicks(self):
        self.dispatcher.send(binding('mouse', 'double-click'), True)
        self.assertEqual(self.output.events, [('mouse', 'left-down', 0, 0), ('mouse', 'left-up', 0, 0)] * 2)

    def test_voice_remote_uses_owned_stop_and_generic_only_toggles_on_down(self):
        remote = binding('voice', 'remote-mic', 'hold', 'daily:9')
        self.dispatcher.send(remote, True)
        self.dispatcher.send(remote, True)
        self.dispatcher.release_all()
        generic = binding('voice', 'qwen-generic')
        self.dispatcher.send(generic, True)
        self.dispatcher.send(generic, False)
        self.assertEqual(self.qwen.events, ['start', 'stop_owned', 'toggle'])
        self.assertEqual(self.output.events, [])

    def test_generic_voice_continues_on_up_and_stops_owned_session_on_cleanup(self):
        value = binding('voice', 'qwen-generic')
        self.dispatcher.send(value, True)
        self.dispatcher.send(value, False)
        self.assertEqual(self.qwen.events, ['toggle'])
        self.dispatcher.release_all()
        self.dispatcher.release_all()
        self.assertEqual(self.qwen.events, ['toggle', 'stop_owned'])

    def test_generic_voice_cleanup_failure_is_reported_and_retryable(self):
        value = binding('voice', 'qwen-generic')
        self.dispatcher.send(value, True)
        self.dispatcher.send(value, False)
        with patch.object(self.qwen, 'stop_owned', side_effect=OSError('stop refused')):
            with self.assertRaises(OSError):
                self.dispatcher.release_all()
        self.dispatcher.close()
        self.assertEqual(self.qwen.events, ['toggle', 'stop_owned'])

    def test_app_target_uses_no_shell_interpolation(self):
        value = binding('app', 'program')
        value['target'] = 'C:\\Apps\\Example App.exe'
        launched = threading.Event()
        with patch.object(standalone.os, 'startfile', create=True, side_effect=lambda target: launched.set()) as launch:
            self.dispatcher.send(value, True)
            self.dispatcher.send(value, True)
            self.assertTrue(launched.wait(1))
            self.dispatcher.send(value, False)
        launch.assert_called_once_with(value['target'])

    def test_url_requires_http_and_codex_focus_uses_bundled_script(self):
        value = binding('app', 'url')
        value['target'] = 'https://example.com/?name=hello&x=1'
        launched = threading.Event()
        with patch.object(standalone.os, 'startfile', create=True, side_effect=lambda target: launched.set()) as launch:
            self.dispatcher.send(value, True)
            self.assertTrue(launched.wait(1))
        launch.assert_called_once_with(value['target'])
        value = binding('app', 'codex-focus', context='daily:0')
        process = FocusProcess()
        with patch.object(standalone.subprocess, 'run'), patch.object(standalone.subprocess, 'Popen', return_value=process) as launch:
            self.dispatcher.send(value, True)
            self.assertTrue(process.entered.wait(1))
        args, kwargs = launch.call_args
        self.assertEqual(args[0][-2], '-File')
        self.assertTrue(args[0][-1].endswith('focus-codex.ps1'))
        self.assertFalse(kwargs.get('shell', False))
        self.assertEqual(kwargs['stdout'], standalone.subprocess.PIPE)

    def test_blocked_codex_focus_does_not_block_key_up(self):
        process = FocusProcess(blocked=True)
        key = binding('keyboard', 'Enter', 'hold')
        self.dispatcher.send(key, True)
        value = binding('app', 'codex-focus', context='daily:0')
        released = threading.Event()
        with patch.object(standalone.subprocess, 'run', side_effect=lambda *a, **k: process.communicate()), \
             patch.object(standalone.subprocess, 'Popen', return_value=process):
            sender = threading.Thread(target=self.dispatcher.send, args=(value, True))
            sender.start()
            self.assertTrue(process.entered.wait(1))
            releaser = threading.Thread(target=lambda: (self.dispatcher.send(key, False), released.set()))
            releaser.start()
            try:
                self.assertTrue(released.wait(.3), 'An app helper must not block physical key release')
                self.assertIn(('key', 13, False), self.output.events)
            finally:
                process.finished.set()
                sender.join(2)
                releaser.join(2)

    def test_close_terminates_owned_focus_and_cancels_queued_url(self):
        process = FocusProcess(blocked=True)
        value = binding('app', 'codex-focus', context='daily:0')
        url = binding('app', 'url', context='daily:1')
        url['target'] = 'https://example.com/'
        with patch.object(standalone.subprocess, 'run'), \
             patch.object(standalone.subprocess, 'Popen', return_value=process), \
             patch.object(standalone.os, 'startfile', create=True) as launch:
            self.dispatcher.send(value, True)
            self.assertTrue(process.entered.wait(1))
            self.dispatcher.send(url, True)
            self.dispatcher.close()
            self.assertTrue(process.terminated)
            launch.assert_not_called()

    def test_app_failure_is_reported_asynchronously(self):
        value = binding('app', 'program')
        value['target'] = 'C:\\Missing.exe'
        with patch.object(standalone.os, 'startfile', create=True, side_effect=OSError('program missing')):
            self.dispatcher.send(value, True)
            deadline = time.monotonic() + 1
            while self.dispatcher.last_error is None and time.monotonic() < deadline:
                time.sleep(.01)
        self.assertIn('program missing', self.dispatcher.last_error)

    def test_input_failure_releases_successful_prefix_of_shortcut(self):
        original = self.output.keyboard
        def failing(vk, down):
            if vk == 65 and down:
                raise OSError('injection refused')
            original(vk, down)
        self.output.keyboard = failing
        value = binding('keyboard', 'custom', 'hold')
        value['shortcut'] = 'Ctrl+A'
        with self.assertRaises(OSError):
            self.dispatcher.send(value, True)
        self.assertEqual(self.output.events[-1], ('key', 17, False))

    def test_repeat_failure_is_visible_and_does_not_continue(self):
        original = self.output.mouse
        def failing(action, dx=0, dy=0):
            if len(self.output.events) > 0:
                self.output.changed.set()
                raise OSError('repeat was refused')
            original(action, dx, dy)
        self.output.mouse = failing
        value = binding('mouse', 'wheel-up', 'repeat')
        self.dispatcher.send(value, True)
        deadline = time.monotonic() + 1
        while self.dispatcher.last_error is None and time.monotonic() < deadline:
            self.output.changed.wait(.02)
            self.output.changed.clear()
        self.assertIn('repeat was refused', self.dispatcher.last_error)
        self.assertEqual(self.dispatcher.held, {})
        self.assertEqual(len(self.output.events), 1)

    def test_motion_failure_stops_held_directions_and_is_visible(self):
        original = self.output.mouse
        def failing(action, dx=0, dy=0):
            if len(self.output.events) > 0:
                raise OSError('motion was refused')
            original(action, dx, dy)
        self.output.mouse = failing
        self.dispatcher.send(binding('mouse', 'move-right', 'repeat'), True)
        deadline = time.monotonic() + 1
        while self.dispatcher.last_error is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIn('motion was refused', self.dispatcher.last_error)
        self.assertEqual(self.dispatcher.held, {})
        self.assertEqual(len(self.output.events), 1)

    def test_default_constructor_does_not_initialize_native_input(self):
        with patch.object(standalone, 'WindowsInput', side_effect=AssertionError('native initialization')):
            dispatcher = standalone.NativeDispatcher()
            dispatcher.close()

    def test_release_failure_does_not_skip_other_held_bindings_and_can_retry(self):
        first = binding('mouse', 'left-click', 'hold')
        second = binding('keyboard', 'Enter', 'hold', 'daily:6')
        self.dispatcher.send(first, True)
        self.dispatcher.send(second, True)
        original = self.output.mouse
        def failing(action, dx=0, dy=0):
            if action == 'left-up':
                raise OSError('injection refused')
            original(action, dx, dy)
        self.output.mouse = failing
        with self.assertRaises(OSError):
            self.dispatcher.release_all()
        self.assertIn(('key', 13, False), self.output.events)
        self.output.mouse = original
        self.dispatcher.release_all()
        self.assertEqual(self.output.events[-1], ('mouse', 'left-up', 0, 0))


class MouseMotionTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(standalone, 'MouseMotion'), 'Smooth aggregated mouse movement is missing')

    def simulate(self, actions, speed=6, frames=62):
        now = [0.0]
        events = []
        motion = standalone.MouseMotion(lambda dx, dy: events.append((dx, dy)), clock=lambda: now[0])
        for index, action in enumerate(actions):
            motion.add(str(index), action, speed)
        motion.tick()
        for frame in range(1, frames + 1):
            now[0] = frame * .016
            motion.tick()
        return motion, events, now

    def test_default_speed_preserves_120_to_480_pixels_per_second_acceleration(self):
        _, events, _ = self.simulate(['move-right'])
        expected = sum(min(480, 120 + 360 * frame * .016) * .016 for frame in range(63))
        self.assertAlmostEqual(sum(dx for dx, _ in events), expected, delta=1)
        self.assertGreater(events[-1][0], events[0][0])

    def test_opposite_directions_cancel_without_drift(self):
        motion, events, now = self.simulate(['move-up', 'move-down'])
        self.assertEqual(events, [])
        motion.remove('1')
        now[0] += .016
        motion.tick()
        self.assertEqual(events[-1][0], 0)
        self.assertLess(events[-1][1], 0)

    def test_diagonal_is_normalized_to_same_total_speed(self):
        _, straight, _ = self.simulate(['move-right'])
        _, diagonal, _ = self.simulate(['move-right', 'move-down'])
        self.assertAlmostEqual(math.hypot(sum(x for x, _ in diagonal), sum(y for _, y in diagonal)),
                               sum(x for x, _ in straight), delta=2)
        self.assertEqual(sum(x for x, _ in diagonal), sum(y for _, y in diagonal))

    def test_speed_three_is_half_default_six(self):
        _, fast, _ = self.simulate(['move-right'], speed=6)
        _, slow, _ = self.simulate(['move-right'], speed=3)
        self.assertAlmostEqual(sum(x for x, _ in fast) / 2, sum(x for x, _ in slow), delta=1)

    def test_last_direction_release_stops_and_stall_does_not_burst(self):
        motion, events, now = self.simulate(['move-right'], frames=1)
        now[0] += 10
        motion.tick()
        self.assertLessEqual(events[-1][0], 25)
        motion.remove('0')
        count = len(events)
        now[0] += .016
        motion.tick()
        self.assertEqual(len(events), count)
        self.assertIsNone(motion.next_due)


class NativeInputTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(standalone, 'Standalone configuration/dispatcher is not implemented')
        self.events = []
        owner = self
        class Api:
            returned = 1
            def __call__(self, count, pointer, size):
                owner.events.append((count, copy.deepcopy(pointer._obj), size))
                return self.returned
        self.api = Api()
        class Library:
            SendInput = self.api
        with patch.object(standalone.C, 'WinDLL', return_value=Library()):
            self.output = standalone.WindowsInput()

    def test_pointer_size_and_extended_key_up_flags(self):
        self.output.keyboard(46, False)
        count, event, size = self.events[0]
        self.assertEqual(size, 40 if standalone.C.sizeof(standalone.C.c_void_p) == 8 else 28)
        self.assertEqual((count, event.type, event.payload.keyboard.vk, event.payload.keyboard.flags), (1, 1, 46, 3))

    def test_negative_wheel_delta_is_unsigned_mouse_data(self):
        self.output.mouse('wheel', -120)
        mouse = self.events[0][1].payload.mouse
        self.assertEqual((mouse.dx, mouse.dy, mouse.data, mouse.flags), (0, 0, 0xFFFFFF88, 0x800))

    def test_input_refusal_is_reported(self):
        self.api.returned = 0
        with self.assertRaises(OSError):
            self.output.keyboard(13, True)


if __name__ == '__main__':
    unittest.main()
