"""A message-only Raw Input listener. Does not change any global key mapping."""
import ctypes as C
from ctypes import wintypes as W
import re
import threading


def matches_device(path):
    return bool(re.search(r'VID[&_](?:0*)?(?:01)?2717.*PID[&_](?:0*)?32B8', path, re.I))


def remote_device_count():
    """Live keyboard interfaces, not paired-device registry entries."""
    user=C.WinDLL('user32',use_last_error=True)
    class Device(C.Structure):_fields_=[('handle',W.HANDLE),('kind',W.DWORD)]
    listing=user.GetRawInputDeviceList
    listing.argtypes=[C.POINTER(Device),C.POINTER(W.UINT),W.UINT];listing.restype=W.UINT
    info=user.GetRawInputDeviceInfoW
    info.argtypes=[W.HANDLE,W.UINT,C.c_void_p,C.POINTER(W.UINT)];info.restype=W.UINT
    size=W.UINT()
    if listing(None,C.byref(size),C.sizeof(Device))==0xffffffff:raise C.WinError(C.get_last_error())
    devices=(Device*size.value)();length=listing(devices,C.byref(size),C.sizeof(Device))
    if length==0xffffffff:raise C.WinError(C.get_last_error())
    count=0
    for device in devices[:length]:
        if device.kind!=1:continue
        chars=W.UINT();info(device.handle,0x20000007,None,C.byref(chars))
        text=C.create_unicode_buffer(chars.value+1)
        if info(device.handle,0x20000007,text,C.byref(chars))!=0xffffffff and matches_device(text.value):count+=1
    return count


VKEYS = {0x26:1,0x28:2,0x25:3,0x27:4,0x0d:5,0x08:6,0x24:7,0x5d:8,0xc0:12}


def decode_keyboard(path, vkey, flags, scan=0):
    if not matches_device(path) or vkey == 0x74: return None
    position = VKEYS.get(vkey)
    if position is None and vkey == 0 and scan in (0, 0x5e): position = 0
    # RC003 power is an unmapped VK_FF with the observed E0 5E make/break.
    # Other unmapped or overrun reports must never become a power action.
    if position is None and vkey == 0xff and scan == 0x5e and flags in (2, 3): position = 0
    return None if position is None else (position, not bool(flags & 1))


class RawInputListener:
    def __init__(self, callback, trace=None):
        self.callback = callback
        self.trace = trace
        self.thread = self.hwnd = None
        self.ready = threading.Event()
        self.error = None
        self.decoder = None

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.ready.clear();self.error=None
        self.thread = threading.Thread(target=self._run, name='RC003-RawInput', daemon=True)
        self.thread.start()
        if not self.ready.wait(5): raise TimeoutError('Raw Input listener did not initialize')
        if self.error: raise RuntimeError(self.error)

    def stop(self):
        if self.hwnd:
            user32 = C.WinDLL('user32', use_last_error=True)
            post = user32.PostMessageW; post.argtypes = [W.HWND,W.UINT,W.WPARAM,W.LPARAM]
            post(self.hwnd, 0x10, 0, 0)
        if self.thread: self.thread.join(3)

    def _run(self):
        from .core import HidKeys
        self.decoder = HidKeys()
        user = C.WinDLL('user32', use_last_error=True); kernel = C.WinDLL('kernel32', use_last_error=True)
        def bind(dll, name, result, *args):
            f = getattr(dll, name); f.restype = result; f.argtypes = list(args); return f
        proc_type = C.WINFUNCTYPE(C.c_ssize_t, W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        class WindowClass(C.Structure):
            _fields_ = [('style',W.UINT),('proc',proc_type),('cls',C.c_int),('win',C.c_int),('instance',W.HINSTANCE),
                        ('icon',W.HICON),('cursor',W.HANDLE),('background',W.HBRUSH),('menu',W.LPCWSTR),('name',W.LPCWSTR)]
        class Registration(C.Structure):
            _fields_ = [('page',W.USHORT),('usage',W.USHORT),('flags',W.DWORD),('target',W.HWND)]
        class Header(C.Structure):
            _fields_ = [('type',W.DWORD),('size',W.DWORD),('device',W.HANDLE),('param',W.WPARAM)]
        get_data = bind(user,'GetRawInputData',W.UINT,W.HANDLE,W.UINT,C.c_void_p,C.POINTER(W.UINT),W.UINT)
        get_info = bind(user,'GetRawInputDeviceInfoW',W.UINT,W.HANDLE,W.UINT,C.c_void_p,C.POINTER(W.UINT))
        default = bind(user,'DefWindowProcW',C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        destroy = bind(user,'DestroyWindow',W.BOOL,W.HWND)
        quit_message = bind(user,'PostQuitMessage',None,C.c_int)
        paths = {}
        def path_for(device):
            if device not in paths:
                size = W.UINT(); get_info(device,0x20000007,None,C.byref(size))
                text = C.create_unicode_buffer(size.value+1)
                get_info(device,0x20000007,text,C.byref(size)); paths[device] = text.value
            return paths[device]
        @proc_type
        def procedure(hwnd, message, wparam, lparam):
            try:
                if message == 0xff:
                    size = W.UINT()
                    get_data(lparam,0x10000003,None,C.byref(size),C.sizeof(Header))
                    if 0 < size.value <= 65536:
                        buffer = C.create_string_buffer(size.value)
                        result = get_data(lparam,0x10000003,buffer,C.byref(size),C.sizeof(Header))
                        if result != 0xffffffff:
                            header = Header.from_buffer_copy(buffer)
                            path = path_for(header.device)
                            if matches_device(path):
                                payload = buffer.raw[C.sizeof(Header):size.value]
                                if header.type == 1 and len(payload) >= 16:
                                    import struct
                                    scan, flags, _, key, _, _ = struct.unpack_from('<HHHHII', payload)
                                    if self.trace:self.trace({'kind':'keyboard','vkey':key,'scan':scan,'flags':flags})
                                    edge = decode_keyboard(path,key,flags,scan)
                                    if edge: self.callback('key',edge)
                                elif header.type == 2 and len(payload) >= 8:
                                    import struct
                                    width, count = struct.unpack_from('<II',payload)
                                    if width and count*width <= len(payload)-8:
                                        for i in range(count):
                                            if self.trace:self.trace({'kind':'hid','hex':payload[8+i*width:8+(i+1)*width].hex()})
                                            for edge in self.decoder.feed(payload[8+i*width:8+(i+1)*width]):
                                                self.callback('key',edge)
                elif message == 0xfe and wparam == 2:
                    path = paths.pop(lparam, '')
                    if matches_device(path): self.callback('input_removed', None)
                elif message == 0x10: destroy(hwnd); return 0
                elif message == 2: quit_message(0); return 0
            except Exception as error:
                self.callback('input_error', str(error))
            return default(hwnd,message,wparam,lparam)
        try:
            instance = bind(kernel,'GetModuleHandleW',W.HMODULE,W.LPCWSTR)(None)
            name = 'CodexRc003RawInput_'+str(id(self))
            wc = WindowClass(0,procedure,0,0,instance,None,None,None,None,name)
            register = bind(user,'RegisterClassW',W.ATOM,C.POINTER(WindowClass))
            if not register(C.byref(wc)): raise C.WinError(C.get_last_error())
            create = bind(user,'CreateWindowExW',W.HWND,W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p)
            self.hwnd = create(0,name,name,0,0,0,0,0,W.HWND(-3),None,instance,None)
            if not self.hwnd: raise C.WinError(C.get_last_error())
            regs = (Registration*2)(Registration(1,6,0x2100,self.hwnd),Registration(12,1,0x2100,self.hwnd))
            register_input = bind(user,'RegisterRawInputDevices',W.BOOL,C.POINTER(Registration),W.UINT,W.UINT)
            if not register_input(regs,2,C.sizeof(Registration)): raise C.WinError(C.get_last_error())
            self.ready.set()
            message = W.MSG()
            get_message = bind(user,'GetMessageW',W.BOOL,C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT)
            dispatch = bind(user,'DispatchMessageW',C.c_ssize_t,C.POINTER(W.MSG))
            while get_message(C.byref(message),None,0,0) > 0: dispatch(C.byref(message))
        except Exception as error:
            self.error = str(error); self.ready.set()
        finally:
            if self.hwnd:
                destroy(self.hwnd)
            if 'name' in locals():
                bind(user,'UnregisterClassW',W.BOOL,W.LPCWSTR,W.HINSTANCE)(name,instance)
            self.hwnd = None
