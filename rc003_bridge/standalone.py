"""Independent profile storage and owned Windows input dispatch.

Importing this module or constructing a dispatcher never injects input. The
dispatcher accepts only device edges from its caller; it installs no hooks and
does not remap or suppress physical keyboards.
"""
from copy import deepcopy
from collections import deque
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit


ACTIONS = {
    'keyboard': {'Backspace', 'Delete', 'Enter', 'Esc', 'custom'},
    'mouse': {'move-up', 'move-down', 'move-left', 'move-right', 'left-click',
              'right-click', 'middle-click', 'double-click', 'wheel-up', 'wheel-down'},
    'app': {'codex-focus', 'program', 'url'},
    'voice': {'remote-mic', 'qwen-generic'},
    'disabled': {'none'},
}
COMMON = dict(delay=500, interval=70, speed=6, shortcut='', target='')
MODIFIERS = {'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'shift': 0x10,
             'win': 0x5B, 'windows': 0x5B, 'meta': 0x5B}
MODIFIER_ORDER = (0x11, 0x12, 0x10, 0x5B)
KEYS = {'backspace': 8, 'tab': 9, 'enter': 13, 'return': 13, 'esc': 27,
        'escape': 27, 'space': 32, 'pageup': 33, 'pagedown': 34, 'end': 35,
        'home': 36, 'left': 37, 'up': 38, 'right': 39, 'down': 40,
        'insert': 45, 'delete': 46, 'capslock': 20, 'printscreen': 44,
        'plus': 0xBB, 'minus': 0xBD, 'comma': 0xBC, 'period': 0xBE,
        'slash': 0xBF, 'backslash': 0xDC, 'semicolon': 0xBA,
        'quote': 0xDE, 'leftbracket': 0xDB, 'rightbracket': 0xDD,
        'volumeup': 0xAF, 'volumedown': 0xAE, 'volumemute': 0xAD,
        'mediaplaypause': 0xB3, 'medianext': 0xB0, 'mediaprevious': 0xB1}


def parse_shortcut(shortcut):
    """Return modifiers first and the single main key last, without sending it."""
    if not isinstance(shortcut, str) or not 0 < len(shortcut.strip()) <= 60:
        raise ValueError('快捷键应为 1–60 个字符，例如 Ctrl + Shift + V。')
    modifiers, keys = set(), []
    for part in shortcut.split('+'):
        token = part.strip().lower()
        if token in MODIFIERS:
            vk = MODIFIERS[token]
            if vk in modifiers:
                raise ValueError('快捷键包含重复修饰键。')
            modifiers.add(vk)
            continue
        if token in KEYS:
            vk = KEYS[token]
        elif re.fullmatch(r'[a-z0-9]', token):
            vk = ord(token.upper())
        elif re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])', token):
            vk = 0x6F + int(token[1:])
        else:
            raise ValueError(f'不支持的快捷键名称：{part.strip() or "空白"}')
        keys.append(vk)
    if len(keys) > 1 or not (keys or modifiers):
        raise ValueError('快捷键只能包含一个普通按键及修饰键。')
    return tuple(vk for vk in MODIFIER_ORDER if vk in modifiers) + tuple(keys)


def allowed_modes(binding):
    kind, action = binding['type'], binding['action']
    if kind == 'keyboard':
        return ('tap', 'hold', 'repeat')
    if kind == 'mouse':
        if action.startswith('move-'):
            return ('repeat',)
        if action.startswith('wheel-'):
            return ('tap', 'repeat')
        return ('tap',) if action == 'double-click' else ('tap', 'hold')
    return ('hold',) if kind == 'voice' and action == 'remote-mic' else ('tap',)


def validate_binding(value, position):
    if not isinstance(value, dict):
        raise ValueError('每个实体按键都需要完整绑定。')
    kind, action = value.get('type'), value.get('action')
    if not isinstance(kind, str) or kind not in ACTIONS or not isinstance(action, str) or action not in ACTIONS[kind]:
        raise ValueError('方案包含不支持的动作。')
    result = {**COMMON, **{k: value[k] for k in COMMON if k in value},
              'type': kind, 'action': action, 'mode': value.get('mode')}
    if result['mode'] not in allowed_modes(result):
        raise ValueError('该动作不支持所选触发方式。')
    if kind == 'voice' and action == 'remote-mic' and position != 9:
        raise ValueError('内置麦克风目前只支持实体语音键。')
    for key, lower, upper in (('delay', 0, 2000), ('interval', 20, 1000)):
        if type(result[key]) is not int or not lower <= result[key] <= upper:
            raise ValueError('起始延迟须为 0–2000 ms，重复间隔须为 20–1000 ms。')
    if type(result['speed']) not in (int, float) or not math.isfinite(result['speed']) or not 1 <= result['speed'] <= 10:
        raise ValueError('速度应为 1–10。')
    for key, maximum in (('shortcut', 60), ('target', 500)):
        if not isinstance(result[key], str) or len(result[key]) > maximum or '\0' in result[key]:
            raise ValueError(f'{key} 格式或长度无效。')
    if kind == 'keyboard' and action == 'custom':
        parse_shortcut(result['shortcut'])
    if kind == 'app' and action == 'program' and not result['target'].strip():
        raise ValueError('请填写程序路径。')
    if kind == 'app' and action == 'url':
        url = urlsplit(result['target'])
        if url.scheme not in ('http', 'https') or not url.hostname or any(c.isspace() for c in result['target']):
            raise ValueError('网址须为完整的 http:// 或 https:// 地址。')
    return result


def default_state():
    def make(kind, action, mode='tap', **extra):
        return {**COMMON, 'type': kind, 'action': action, 'mode': mode, **extra}
    values = [make('app', 'codex-focus'),
              *[make('mouse', f'move-{direction}', 'repeat') for direction in ('up', 'down', 'left', 'right')],
              make('keyboard', 'Enter'), make('keyboard', 'Backspace', 'repeat', interval=33),
              make('mouse', 'left-click', 'hold'), make('mouse', 'right-click', 'hold'),
              make('voice', 'remote-mic', 'hold'),
              make('mouse', 'wheel-up', 'repeat', delay=300),
              make('mouse', 'wheel-down', 'repeat', delay=300), make('keyboard', 'Esc')]
    return {'version': 1, 'current': 'daily', 'profiles': [
        {'id': 'daily', 'name': '日常控制', 'bindings': {str(i): value for i, value in enumerate(values)}}]}


def validate_state(state):
    if not isinstance(state, dict) or type(state.get('version')) is not int or state['version'] != 1:
        raise ValueError('不支持的配置版本。')
    profiles = state.get('profiles')
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 30:
        raise ValueError('配置应包含 1–30 套方案。')
    result, seen = [], set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError('方案格式无效。')
        identity, name = profile.get('id'), profile.get('name')
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identity) or identity in seen:
            raise ValueError('方案标识无效或重复。')
        if not isinstance(name, str) or not name.strip() or len(name) > 40:
            raise ValueError('方案名称应为 1–40 个字符。')
        bindings = profile.get('bindings')
        if not isinstance(bindings, dict) or set(bindings) != {str(i) for i in range(13)}:
            raise ValueError('方案必须包含全部 13 个实体按键。')
        result.append({'id': identity, 'name': name.strip(), 'bindings': {
            str(i): validate_binding(bindings[str(i)], i) for i in range(13)}})
        seen.add(identity)
    if not isinstance(state.get('current'), str) or state['current'] not in seen:
        raise ValueError('当前方案不存在。')
    return {'version': 1, 'current': state['current'], 'profiles': result}


class ProfileResolver:
    def __init__(self, path=None):
        if path is None:
            from .paths import DATA
            path = DATA / 'profiles.json'
        self.path = Path(path)
        self._lock = threading.RLock()
        self._state = default_state()
        self.reload()

    def reload(self):
        with self._lock:
            if self.path.exists():
                if self.path.stat().st_size > 1_000_000:
                    raise ValueError('配置文件过大。')
                state = validate_state(json.loads(self.path.read_text(encoding='utf-8-sig')))
                self._state = state
            return deepcopy(self._state)

    def read_state(self):
        with self._lock:
            return deepcopy(self._state)

    def save_state(self, state):
        clean = validate_state(state)
        encoded = json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                                 dir=self.path.parent, prefix='.profiles-', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self._state = clean
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return deepcopy(clean)

    def resolve(self, position):
        if type(position) is not int or not 0 <= position < 13:
            raise ValueError('Invalid logical key')
        with self._lock:
            current = self._state['current']
            profile = next(p for p in self._state['profiles'] if p['id'] == current)
            return {**deepcopy(profile['bindings'][str(position)]), 'actionId': f'{current}:{position}'}


class WindowsInput:
    """Thin SendInput boundary, with pointer-size-correct Windows structures."""
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Native input requires Windows')
        class Mouse(C.Structure):
            _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('data', W.DWORD),
                        ('flags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]
        class Keyboard(C.Structure):
            _fields_ = [('vk', W.WORD), ('scan', W.WORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('extra', C.c_size_t)]
        class Payload(C.Union):
            _fields_ = [('mouse', Mouse), ('keyboard', Keyboard)]
        class Input(C.Structure):
            _fields_ = [('type', W.DWORD), ('payload', Payload)]
        self.Input, self.Mouse = Input, Mouse
        self.api = C.WinDLL('user32', use_last_error=True).SendInput
        self.api.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
        self.api.restype = W.UINT
        self._pending_keys = set()

    def _send(self, event):
        if self.api(1, C.byref(event), C.sizeof(self.Input)) != 1:
            raise OSError('Windows refused input; check foreground application elevation')

    def _keyboard_event(self, vk, down):
        event = self.Input()
        event.type = 1
        event.payload.keyboard.vk = vk
        extended = vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C)
        event.payload.keyboard.flags = (0 if down else 2) | int(extended)
        return event

    def keyboard(self, vk, down):
        if down:
            self.release_pending_keys()
        event = self._keyboard_event(vk, down)
        self._send(event)

    def release_pending_keys(self):
        errors = []
        for vk in sorted(self._pending_keys):
            try:
                self._send(self._keyboard_event(vk, False))
                self._pending_keys.remove(vk)
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[0]

    def tap_keyboard(self, vk):
        self.release_pending_keys()
        events = (self.Input * 2)(self._keyboard_event(vk, True), self._keyboard_event(vk, False))
        self._pending_keys.add(vk)
        try:
            count = self.api(2, events, C.sizeof(self.Input))
            if count != 2:
                raise OSError(f'Windows refused keyboard input ({count}/2 events)')
        except Exception:
            # A partial native write may have accepted down without up. Keep
            # failed compensation owned until a later cleanup really succeeds.
            self.release_pending_keys()
            raise
        self._pending_keys.remove(vk)

    def mouse(self, action, dx=0, dy=0):
        flags = {'move': 1, 'left-down': 2, 'left-up': 4, 'right-down': 8,
                 'right-up': 16, 'middle-down': 32, 'middle-up': 64, 'wheel': 0x800}[action]
        event = self.Input()
        event.payload.mouse = self.Mouse(0 if action == 'wheel' else dx,
                                        0 if action == 'wheel' else dy,
                                        dx & 0xFFFFFFFF if action == 'wheel' else 0,
                                        flags, 0, 0)
        self._send(event)


@dataclass
class _Press:
    binding: dict
    resources: list = field(default_factory=list)
    due: float | None = None
    voice_started: bool = False
    expires_at: float | None = None
    voice_owner: str | None = None
    voice_stop: object = None
    release_requested: bool = False


@dataclass
class _VoiceCommand:
    method: str
    owner: str
    press: object = None
    done: object = field(default_factory=threading.Event)
    error: object = None


class MouseMotion:
    """Aggregate direction holds using the existing 120→480 px/s curve.

    A speed setting of six preserves the original curve. Direction vectors are
    summed before normalization, so opposites cancel and diagonals do not run
    faster. Different speed settings use the fastest participating hold.
    """
    FRAME = .016
    DIRECTIONS = {'move-up': (0, -1), 'move-down': (0, 1),
                  'move-left': (-1, 0), 'move-right': (1, 0)}

    def __init__(self, send, clock=time.monotonic):
        self.send, self.clock = send, clock
        self.held = {}
        self.last = clock()
        self.remainder = [0.0, 0.0]

    @property
    def next_due(self):
        return self.last + self.FRAME if self.held else None

    def add(self, identity, action, speed):
        if identity in self.held:
            return
        now = self.clock()
        if not self.held:
            # Start on the down edge; subsequent movement is frame paced.
            self.last = now - self.FRAME
        self.held[identity] = (self.DIRECTIONS[action], speed, now)
        self.remainder = [0.0, 0.0]

    def remove(self, identity):
        if identity in self.held:
            del self.held[identity]
            self.remainder = [0.0, 0.0]
        if not self.held:
            self.last = self.clock()

    def tick(self):
        now = self.clock()
        dt = max(0, min(.05, now - self.last))
        self.last = now
        if not self.held:
            return
        moves = list(self.held.values())
        x, y = sum(v[0] for v, _, _ in moves), sum(v[1] for v, _, _ in moves)
        length = math.hypot(x, y)
        if not length:
            self.remainder = [0.0, 0.0]
            return
        age = max(0, now - min(started for _, _, started in moves))
        speed = min(480, 120 + 360 * age) * max(speed for _, speed, _ in moves) / 6
        self.remainder[0] += x / length * speed * dt
        self.remainder[1] += y / length * speed * dt
        dx, dy = map(int, self.remainder)
        self.remainder[0] -= dx
        self.remainder[1] -= dy
        if dx or dy:
            self.send(dx, dy)


class NativeDispatcher:
    def __init__(self, qwen=None, *, input_backend=None, clock=time.monotonic):
        self.qwen = qwen
        self._input = input_backend
        self._condition = threading.Condition(threading.RLock())
        self._held = {}
        self._owners = {}
        self._closed = False
        self._worker = None
        self._clock = clock
        self._motion = MouseMotion(lambda dx, dy: self._output().mouse('move', dx, dy), clock=clock)
        self._generic_voice_used = False
        self._generic_owner = 'generic:' + secrets.token_hex(12)
        self._generic_stop = None
        self._voice_jobs = deque()
        self._voice_retries = {}
        self._voice_worker = None
        self._app_jobs = deque()
        self._app_generation = 0
        self._app_worker = None
        self._app_process = None
        self.last_error = None

    @property
    def held(self):
        with self._condition:
            return {identity: deepcopy(press.binding) for identity, press in self._held.items()}

    def _output(self):
        if self._input is None:
            self._input = WindowsInput()
        return self._input

    def _resource_edge(self, resource, down):
        kind, value = resource
        if kind == 'key':
            self._output().keyboard(value, down)
        else:
            self._output().mouse(f'{value}-{"down" if down else "up"}')

    def _acquire(self, press, resources):
        for resource in resources:
            count = self._owners.get(resource, 0)
            if not count:
                self._resource_edge(resource, True)
            self._owners[resource] = count + 1
            press.resources.append(resource)

    def _release_resources(self, press):
        errors = []
        for resource in list(reversed(press.resources)):
            try:
                count = self._owners[resource]
                if count == 1:
                    self._resource_edge(resource, False)
                    del self._owners[resource]
                else:
                    self._owners[resource] = count - 1
                press.resources.remove(resource)
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[0]

    def _gesture(self, press):
        value = press.binding
        kind, action, mode = value['type'], value['action'], value['mode']
        resources = []
        if kind == 'keyboard':
            keys = parse_shortcut(value['shortcut'] if action == 'custom' else action)
            resources = [('key', key) for key in keys]
            tap = getattr(self._output(), 'tap_keyboard', None)
            if mode != 'hold' and len(keys) == 1 and not self._owners.get(resources[0]) and callable(tap):
                tap(keys[0])
                return
        elif kind == 'mouse':
            if action.startswith('wheel-'):
                self._output().mouse('wheel', 120 if action == 'wheel-up' else -120, 0)
                return
            resources = [('button', 'left' if action == 'double-click' else action.split('-')[0])]
        else:
            return
        for _ in range(2 if action == 'double-click' else 1):
            self._acquire(press, resources)
            if mode != 'hold':
                self._release_resources(press)

    def _open_app(self, value, generation):
        with self._condition:
            if self._closed or generation != self._app_generation:
                return
        if value['action'] in ('program', 'url'):
            os.startfile(value['target'])
            return
        from .paths import ROOT
        script = ROOT / 'focus-codex.ps1'
        if not script.is_file():
            raise FileNotFoundError('Codex focus helper is missing from the installation')
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                   'Bypass', '-File', str(script)]
        with self._condition:
            if self._closed or generation != self._app_generation:
                return
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._app_process = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)
                raise
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        finally:
            with self._condition:
                if self._app_process is process:
                    self._app_process = None

    def _app_loop(self):
        while True:
            with self._condition:
                while not self._app_jobs and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                generation, value = self._app_jobs.popleft()
            try:
                self._open_app(value, generation)
            except Exception as error:
                with self._condition:
                    if generation == self._app_generation and not self._closed:
                        self.last_error = str(error)

    def _cancel_apps(self):
        self._app_generation += 1
        self._app_jobs.clear()
        process = self._app_process
        # Only the focus-helper process created by this dispatcher is owned.
        # Programs/URLs started through the shell belong to the user.
        if process is not None and process.poll() is None:
            process.terminate()

    def _queue_voice(self, method, owner, press=None):
        if method == 'stop_owned':
            pending = press.voice_stop if press is not None else self._generic_stop
            if pending is not None and not pending.done.is_set():
                return pending
        command = _VoiceCommand(method, owner, press)
        if method == 'stop_owned':
            if press is not None:
                press.voice_stop = command
            else:
                self._generic_stop = command
            self._voice_retries.pop(owner, None)
        self._voice_jobs.append(command)
        if self._voice_worker is None or not self._voice_worker.is_alive():
            self._voice_worker = threading.Thread(target=self._voice_loop, name='remote-voice-actions', daemon=True)
            self._voice_worker.start()
        self._condition.notify_all()
        return command

    @staticmethod
    def _wait_voice(command):
        if command is not None:
            command.done.wait()
            if command.error is not None:
                raise command.error

    def _scan_voice_cleanup(self):
        needs_cleanup = getattr(self.qwen, 'needs_cleanup', None)
        if not callable(needs_cleanup):
            return
        with self._condition:
            owners = [(press.voice_owner, press) for press in self._held.values() if press.voice_started]
            if self._generic_voice_used:
                owners.append((self._generic_owner, None))
        for owner, press in owners:
            required = needs_cleanup(owner=owner)
            with self._condition:
                if required:
                    pending = press.voice_stop if press is not None else self._generic_stop
                    if owner not in self._voice_retries and (pending is None or pending.done.is_set()):
                        self._voice_retries[owner] = (time.monotonic() + .25, press)
                else:
                    # A manual toggle may have completed the old cleanup.
                    # Never carry its retry into a later generic session.
                    self._voice_retries.pop(owner, None)

    def _voice_loop(self):
        while True:
            command = None
            with self._condition:
                if self._voice_jobs:
                    command = self._voice_jobs.popleft()
                elif self._closed:
                    self._voice_worker = None
                    return
                else:
                    ready = next(((owner, press) for owner, (due, press) in self._voice_retries.items()
                                  if time.monotonic() >= due), None)
                    if ready:
                        owner, press = ready
                        self._queue_voice('stop_owned', owner, press)
                        command = self._voice_jobs.popleft()
                    else:
                        self._condition.wait(.25)
            if command is not None:
                try:
                    if command.method == 'toggle':
                        with self._condition:
                            # Earlier queued cleanup may have cleared the flag
                            # after this new toggle was accepted by send().
                            self._generic_voice_used = True
                    method = getattr(self.qwen, command.method)
                    if getattr(self.qwen, 'supports_owners', False):
                        method(owner=command.owner)
                    else:
                        method()
                    with self._condition:
                        if command.method == 'stop_owned':
                            self._voice_retries.pop(command.owner, None)
                            if command.press is not None:
                                press = command.press
                                press.voice_started = False
                                press.voice_stop = None
                                identity = press.binding['actionId']
                                if press.release_requested and not press.resources and self._held.get(identity) is press:
                                    self._held.pop(identity, None)
                            else:
                                self._generic_voice_used = False
                                self._generic_stop = None
                except Exception as error:
                    command.error = error
                    with self._condition:
                        self.last_error = str(error)
                        if command.method == 'stop_owned':
                            self._voice_retries[command.owner] = (time.monotonic() + .25, command.press)
                finally:
                    command.done.set()
            try:
                # A generic toggle can request stop for a still-held remote
                # owner. Its confirmation must be retried under that owner.
                self._scan_voice_cleanup()
            except Exception as error:
                with self._condition:
                    self.last_error = str(error)

    def _release(self, identity):
        press = self._held[identity]
        press.due = None
        press.expires_at = None
        press.release_requested = True
        self._motion.remove(identity)
        errors = []
        try:
            self._release_resources(press)
        except Exception as error:
            errors.append(error)
        voice = self._queue_voice('stop_owned', press.voice_owner, press) if press.voice_started else None
        if not press.resources and not press.voice_started:
            self._held.pop(identity, None)
        if errors:
            raise errors[0]
        return voice

    def send(self, binding, down):
        identity = binding.get('actionId') if isinstance(binding, dict) else None
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}:(?:[0-9]|1[0-2])', identity):
            raise ValueError('Invalid binding actionId')
        voice = None
        press = None
        with self._condition:
            if not down:
                if identity in self._held:
                    held = self._held[identity]
                    if binding.get('voiceOwner') and binding['voiceOwner'] != held.voice_owner:
                        return
                    voice = self._release(identity)
                release_pending = getattr(self._input, 'release_pending_keys', None)
                if callable(release_pending):
                    release_pending()
                self._condition.notify_all()
            elif self._closed:
                raise RuntimeError('Dispatcher is closed')
            elif identity in self._held:
                return
            else:
                clean = validate_binding(binding, int(identity.rsplit(':', 1)[1]))
                clean['actionId'] = identity
                if clean['type'] == 'disabled':
                    return
                press = _Press(clean)
                self._held[identity] = press
                try:
                    if clean['type'] == 'voice':
                        if self.qwen is None:
                            raise RuntimeError('Qianwen voice service is unavailable')
                        if clean['action'] == 'remote-mic':
                            press.voice_started = True
                            press.voice_owner = 'remote:' + secrets.token_hex(12)
                            binding['voiceOwner'] = press.voice_owner
                            voice = self._queue_voice('start', press.voice_owner, press)
                        else:
                            self._generic_voice_used = True
                            voice = self._queue_voice('toggle', self._generic_owner)
                    elif clean['type'] == 'app':
                        self._app_jobs.append((self._app_generation, clean))
                        if self._app_worker is None:
                            self._app_worker = threading.Thread(target=self._app_loop, name='remote-app-actions', daemon=True)
                            self._app_worker.start()
                        self._condition.notify_all()
                    elif clean['type'] == 'mouse' and clean['action'].startswith('move-'):
                        self._motion.add(identity, clean['action'], clean['speed'])
                        self._motion.tick()
                    else:
                        self._gesture(press)
                    if clean['mode'] == 'repeat':
                        if not (clean['type'] == 'mouse' and clean['action'].startswith('move-')):
                            press.due = self._clock() + clean['delay'] / 1000
                        if clean['type'] == 'mouse' and clean['action'].startswith('wheel-'):
                            press.expires_at = self._clock() + 30
                        if self._worker is None:
                            self._worker = threading.Thread(target=self._repeat_loop, name='remote-input-repeat', daemon=True)
                            self._worker.start()
                        self._condition.notify_all()
                except Exception:
                    try:
                        self._release(identity)
                    except Exception as cleanup_error:
                        self.last_error = str(cleanup_error)
                    raise
        try:
            self._wait_voice(voice)
        except Exception:
            if down:
                with self._condition:
                    cleanup = self._release(identity) if self._held.get(identity) is press else None
                try:
                    self._wait_voice(cleanup)
                except Exception as cleanup_error:
                    self.last_error = str(cleanup_error)
            raise

    def _tick_repeats(self):
        with self._condition:
            now = self._clock()
            if self._motion.next_due is not None and now >= self._motion.next_due:
                try:
                    self._motion.tick()
                except Exception as error:
                    self.last_error = str(error)
                    for identity in list(self._motion.held):
                        self._release(identity)
            due = [(identity, press) for identity, press in self._held.items() if press.due is not None]
            for identity, press in due:
                if press.expires_at is not None and now >= press.expires_at:
                    # Keep the physical-down latch after expiry. Repeated down
                    # reports cannot restart it; only a genuine up clears it.
                    press.due = press.expires_at = None
                    continue
                if now < press.due:
                    continue
                try:
                    self._gesture(press)
                    press.due = self._clock() + press.binding['interval'] / 1000
                except Exception as error:
                    self.last_error = str(error)
                    try:
                        self._release(identity)
                    except Exception as cleanup_error:
                        self.last_error += '; cleanup: ' + str(cleanup_error)

    def _repeat_loop(self):
        with self._condition:
            while not self._closed:
                self._tick_repeats()
                times = [press.due for press in self._held.values() if press.due is not None]
                times.extend(press.expires_at for press in self._held.values() if press.expires_at is not None)
                if self._motion.next_due is not None:
                    times.append(self._motion.next_due)
                self._condition.wait(max(0, min(times) - self._clock()) if times else None)

    def release_all(self):
        errors, voices = [], []
        with self._condition:
            try:
                self._cancel_apps()
            except Exception as error:
                errors.append(error)
            for identity in list(self._held):
                try:
                    voice = self._release(identity)
                    if voice is not None:
                        voices.append(voice)
                except Exception as error:
                    errors.append(error)
            if self._generic_voice_used:
                voices.append(self._queue_voice('stop_owned', self._generic_owner))
            release_pending = getattr(self._input, 'release_pending_keys', None)
            if callable(release_pending):
                try:
                    release_pending()
                except Exception as error:
                    errors.append(error)
            self._condition.notify_all()
        for voice in voices:
            try:
                self._wait_voice(voice)
            except Exception as error:
                errors.append(error)
        if errors:
            self.last_error = str(errors[0])
            raise errors[0]

    def close(self):
        try:
            with self._condition:
                self._closed = True
            self.release_all()
        finally:
            with self._condition:
                self._condition.notify_all()
            if self._worker is not None and self._worker is not threading.current_thread():
                self._worker.join(timeout=2)
            if self._app_worker is not None and self._app_worker is not threading.current_thread():
                self._app_worker.join(timeout=2)
            voice_worker = self._voice_worker
            if voice_worker is not None and voice_worker is not threading.current_thread():
                voice_worker.join(timeout=2)
