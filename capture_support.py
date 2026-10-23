"""GPL-3.0 injection primitives from MiRemoteVibe. See vendor/miremote/LICENSE.
Only host identity inspection, admin privilege and explicit injection are retained.
Host termination/restart paths are deliberately not included.
"""
import ctypes
from ctypes import wintypes
from pathlib import Path


class CaptureAlreadyRunningError(RuntimeError):
    pass


class CaptureInstance:
    """A helper singleton; the authenticated backend owns the hardware mutex."""
    def __enter__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateMutexW(None, True, r'Local\XiaomiRemoteAssistantCapture')
        error = ctypes.get_last_error()
        if not self.handle:
            raise ctypes.WinError(error)
        if error == 183:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise CaptureAlreadyRunningError('Capture helper is already running')
        return self

    def __exit__(self, *_):
        if self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None

def is_wudfhost_process(pid: int) -> bool:
    """只接受仍存活且进程名精确为 WUDFHost.exe 的目标。"""
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32")
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k32.Process32FirstW.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W))
    k32.Process32NextW.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W))
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)

    snapshot = k32.CreateToolhelp32Snapshot(2, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return False
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if not k32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return False
        while True:
            if entry.th32ProcessID == pid:
                return entry.szExeFile.casefold() == "wudfhost.exe"
            if not k32.Process32NextW(snapshot, ctypes.byref(entry)):
                return False
    finally:
        k32.CloseHandle(snapshot)


def inject_library(pid: int, dll_path: Path, log=print) -> None:
    """经典 LoadLibraryW 远程线程注入（仅限已验证的 WUDFHost 目标）。"""
    if not is_wudfhost_process(pid):
        raise RuntimeError('Target is no longer a WUDFHost process')
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.VirtualAllocEx.restype = ctypes.c_void_p
    k32.VirtualAllocEx.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD,
        wintypes.DWORD,
    )
    k32.WriteProcessMemory.restype = wintypes.BOOL
    k32.WriteProcessMemory.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    )
    k32.VirtualFreeEx.restype = wintypes.BOOL
    k32.VirtualFreeEx.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD,
    )
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    k32.GetProcAddress.restype = ctypes.c_void_p
    k32.GetProcAddress.argtypes = (ctypes.c_void_p, wintypes.LPCSTR)
    k32.CreateRemoteThread.restype = ctypes.c_void_p
    k32.CreateRemoteThread.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    )
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.WaitForSingleObject.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    k32.GetExitCodeThread.restype = wintypes.BOOL
    k32.GetExitCodeThread.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)

    rights = 0x0002 | 0x0400 | 0x0008 | 0x0010 | 0x0020  # CREATE_THREAD|QUERY|VM_*
    process = k32.OpenProcess(rights, False, pid)
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    remote_path = None
    thread = None
    thread_finished = False
    try:
        encoded = (str(dll_path.resolve()) + "\0").encode("utf-16-le")
        remote_path = k32.VirtualAllocEx(
            process, None, len(encoded), 0x3000, 0x04  # MEM_COMMIT|RESERVE, RW
        )
        if not remote_path:
            raise ctypes.WinError(ctypes.get_last_error())
        buf = ctypes.create_string_buffer(encoded)
        written = ctypes.c_size_t()
        if not k32.WriteProcessMemory(
            process, remote_path, buf, len(encoded), ctypes.byref(written)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value != len(encoded):
            raise RuntimeError('Incomplete remote DLL path write')
        kernel = k32.GetModuleHandleW("kernel32.dll")
        load_library = k32.GetProcAddress(kernel, b"LoadLibraryW")
        if not load_library:
            raise ctypes.WinError(ctypes.get_last_error())
        tid = wintypes.DWORD()
        thread = k32.CreateRemoteThread(
            process, None, 0, load_library, remote_path, 0, ctypes.byref(tid)
        )
        if not thread:
            raise ctypes.WinError(ctypes.get_last_error())
        if k32.WaitForSingleObject(thread, 20_000) != 0:
            raise TimeoutError("远程 LoadLibraryW 超时")
        thread_finished = True
        code = wintypes.DWORD()
        if not k32.GetExitCodeThread(thread, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value == 0:
            raise RuntimeError("远程 LoadLibraryW 返回 NULL（DLL 加载失败）")
        log(f"注入成功 pid={pid} 模块句柄={code.value:#x}")
    finally:
        if thread:
            k32.CloseHandle(thread)
        # On timeout the remote thread may still read this path. Retain this
        # small allocation until the host naturally exits, never free under it.
        if remote_path and (not thread or thread_finished):
            k32.VirtualFreeEx(process, remote_path, 0, 0x8000)
        k32.CloseHandle(process)


def enable_debug_privilege() -> None:
    """提权 helper 里启用 SeDebugPrivilege（附加 SYSTEM 进程需要）。"""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class LUID(ctypes.Structure):
        _fields_ = (("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long))

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = (("Luid", LUID), ("Attributes", ctypes.c_ulong))

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = (
            ("PrivilegeCount", ctypes.c_ulong),
            ("Privileges", LUID_AND_ATTRIBUTES * 1),
        )

    # 句柄宽度敏感：GetCurrentProcess 的伪句柄(0xFF..FF)必须按 64 位传递，
    # 不设 restype 会被截成 32 位导致 OpenProcessToken 报"句柄无效"
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.argtypes = ()
    advapi32.OpenProcessToken.argtypes = (
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.LookupPrivilegeValueW.argtypes = (
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p,
    )
    advapi32.LookupPrivilegeValueW.restype = ctypes.c_int
    advapi32.AdjustTokenPrivileges.argtypes = (
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.c_void_p, ctypes.c_void_p,
    )
    advapi32.AdjustTokenPrivileges.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(
            None, "SeDebugPrivilege", ctypes.byref(luid)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 2  # SE_PRIVILEGE_ENABLED
        ctypes.set_last_error(0)
        adjusted = advapi32.AdjustTokenPrivileges(
            token, False, ctypes.byref(tp), 0, None, None
        )
        err = ctypes.get_last_error()
        if not adjusted:
            raise ctypes.WinError(err)
        if err == 1300:
            raise PermissionError("SeDebugPrivilege 未分配（需要管理员）")
        if err:
            raise ctypes.WinError(err)
    finally:
        kernel32.CloseHandle(token)



