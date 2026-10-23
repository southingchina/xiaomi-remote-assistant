"""Private stdin-controlled mouse executor for the installed Xiaomi plugin."""
import ctypes as C
from ctypes import wintypes as W
import json
import queue
import sys
import threading
from .core import BackspaceState,MouseState,WheelState


def keyboard_repeat_settings():
    api=C.WinDLL('user32',use_last_error=True).SystemParametersInfoW
    api.argtypes=[W.UINT,W.UINT,C.c_void_p,W.UINT];api.restype=W.BOOL
    delay=W.UINT(1);speed=W.UINT(20)
    if not api(0x16,0,C.byref(delay),0):delay.value=1
    if not api(0x0A,0,C.byref(speed),0):speed.value=20
    return .25*(1+min(3,delay.value)),1/(2.5+27.5*min(31,speed.value)/31)


class WindowsMouse:
    def __init__(self):
        class Mouse(C.Structure):
            _fields_=[('dx',W.LONG),('dy',W.LONG),('data',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
        class Keyboard(C.Structure):
            _fields_=[('vk',W.WORD),('scan',W.WORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
        class Payload(C.Union):_fields_=[('mouse',Mouse),('keyboard',Keyboard),('padding',C.c_byte*(32 if C.sizeof(C.c_void_p)==8 else 24))]
        class Input(C.Structure):_fields_=[('type',W.DWORD),('payload',Payload)]
        self.Mouse,self.Input=Mouse,Input
        self.send=C.WinDLL('user32',use_last_error=True).SendInput
        self.send.argtypes=[W.UINT,C.POINTER(Input),C.c_int];self.send.restype=W.UINT
        self._appswitch_release_pending=False

    def keyboard_inputs(self,sequence):
        events=(self.Input*len(sequence))()
        for event,(key,flags) in zip(events,sequence):
            event.type=1;event.payload.keyboard.vk=key;event.payload.keyboard.flags=flags
        return events

    def release_appswitch(self):
        if not self._appswitch_release_pending:return
        events=self.keyboard_inputs(((0x1b,2),(0xa4,2)))
        try:
            if self.send(2,events,C.sizeof(self.Input))==2:
                self._appswitch_release_pending=False;return
        except Exception:pass
        failed=[]
        for event in events:
            try:
                if self.send(1,C.byref(event),C.sizeof(self.Input))!=1:failed.append(event.payload.keyboard.vk)
            except Exception:failed.append(event.payload.keyboard.vk)
        if failed:raise RuntimeError('Windows refused application switch modifier release: '+','.join(hex(key) for key in failed))
        self._appswitch_release_pending=False

    def __call__(self,kind,dx,dy):
        if kind=='appswitch':
            self.release_appswitch()
            events=self.keyboard_inputs(((0xa4,0),(0x1b,0),(0x1b,2),(0xa4,2)))
            self._appswitch_release_pending=True
            try:
                count=self.send(4,events,C.sizeof(self.Input))
                if count!=4:raise RuntimeError(f'Windows refused application switch input ({count}/4 events)')
            except Exception:
                self.release_appswitch();raise
            self._appswitch_release_pending=False
            return
        if kind in ('backspace-down','backspace-up'):
            event=self.Input();event.type=1;event.payload.keyboard.vk=8;event.payload.keyboard.flags=2 if kind.endswith('-up') else 0
            if self.send(1,C.byref(event),C.sizeof(event))!=1:raise RuntimeError('Windows refused keyboard input')
            return
        if kind in ('backspace','enter','esc'):
            for flags in (0,2):
                event=self.Input();event.type=1;event.payload.keyboard.vk={'backspace':8,'enter':13,'esc':27}[kind];event.payload.keyboard.flags=flags
                if self.send(1,C.byref(event),C.sizeof(event))!=1:raise RuntimeError('Windows refused keyboard input')
            return
        flags={'move':1,'left-down':2,'left-up':4,'right-down':8,'right-up':16,'wheel':0x800}[kind]
        event=self.Input();event.payload.mouse=self.Mouse(0 if kind=='wheel' else dx,0 if kind=='wheel' else dy,dx & 0xffffffff if kind=='wheel' else 0,flags,0,0)
        if self.send(1,C.byref(event),C.sizeof(event))!=1:
            raise RuntimeError('Windows refused mouse input (check application elevation)')


def main():
    events=queue.Queue(maxsize=256);finished=threading.Event()
    def reader():
        try:
            while True:
                line=sys.stdin.buffer.readline(2049)
                if not line:return
                if len(line)>2048:raise ValueError('Mouse command exceeds its bound')
                events.put(json.loads(line),timeout=1)
        finally:finished.set()
    threading.Thread(target=reader,daemon=True).start()
    mouse=MouseState(WindowsMouse())
    wheel=WheelState(mouse.send)
    delay,interval=keyboard_repeat_settings()
    backspace=BackspaceState(mouse.send,delay=delay,interval=interval)
    print(json.dumps({'event':'ready','inputSize':C.sizeof(mouse.send.Input),'wheelRepeat':'hold-v2','initialDelayMs':300,'repeatIntervalMs':80,'backspaceRepeat':'hold-v1','backspaceDelayMs':round(delay*1000),'backspaceIntervalMs':round(interval*1000)}),flush=True)
    try:
        while not finished.is_set() or not events.empty():
            try:
                timeout=.016 if backspace.due is None else max(0,min(.016,backspace.due-backspace.clock()))
                event=events.get(timeout=timeout)
                if event.get('cmd')=='clear':
                    backspace.release_all();mouse.release_all();wheel.release_all()
                    release=getattr(mouse.send,'release_appswitch',None)
                    if release:release()
                elif event.get('cmd') in ('down','up'):
                    context=event.get('context')
                    if not isinstance(context,str) or not 0<len(context)<=256:raise ValueError('Invalid mouse context')
                    if event['action'] in ('wheelup','wheeldown'):
                        result=wheel.edge(context,event['action'],event['cmd']=='down')
                        if result:print(json.dumps({'event':'wheel-hold',**result}),flush=True)
                    elif event['action']=='backspace':backspace.edge(context,event['cmd']=='down')
                    elif event['action'] in ('enter','esc','appswitch'):
                        if event['cmd']=='down':
                            mouse.send(event['action'],0,0)
                    else:mouse.edge(context,event['action'],event['cmd']=='down')
                    print(json.dumps({'event':'edge','cmd':event['cmd'],'action':event['action'],'held':len(mouse.held)+len(wheel.held)+len(backspace.held)}),flush=True)
            except queue.Empty:pass
            mouse.tick()
            wheel.tick()
            backspace.tick()
    finally:
        try:backspace.release_all()
        finally:
            try:
                release=getattr(mouse.send,'release_appswitch',None)
                if release:release()
            finally:mouse.release_all();wheel.release_all()


if __name__=='__main__':main()
