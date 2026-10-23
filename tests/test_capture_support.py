import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import capture_support as support


class InjectionPrimitiveTests(unittest.TestCase):
    def test_duplicate_capture_instance_cannot_take_ownership(self):
        singleton=getattr(support,'CaptureInstance',None)
        self.assertIsNotNone(singleton,'capture helper has no OS singleton')
        api=Mock();api.CreateMutexW.return_value=100
        with patch.object(support.ctypes,'WinDLL',return_value=api),patch.object(support.ctypes,'get_last_error',return_value=183):
            with self.assertRaises(RuntimeError):
                with singleton():self.fail('duplicate helper entered')
        api.CloseHandle.assert_called_once_with(100)
        api.ReleaseMutex.assert_not_called()

    def test_capture_mutex_releases_even_when_helper_raises(self):
        singleton=getattr(support,'CaptureInstance',None)
        self.assertIsNotNone(singleton,'capture helper has no OS singleton')
        api=Mock();api.CreateMutexW.return_value=100
        with patch.object(support.ctypes,'WinDLL',return_value=api),patch.object(support.ctypes,'get_last_error',return_value=0):
            with self.assertRaises(ValueError):
                with singleton():raise ValueError('test exit')
        api.CreateMutexW.assert_called_once_with(None,True,r'Local\XiaomiRemoteAssistantCapture')
        api.ReleaseMutex.assert_called_once_with(100)
        api.CloseHandle.assert_called_once_with(100)

    def test_admin_debug_privilege_is_enabled_without_touching_other_processes(self):
        enable=getattr(support,'enable_debug_privilege',None)
        self.assertIsNotNone(enable,'SYSTEM-host access needs an explicit admin privilege')
        kernel=Mock();security=Mock();kernel.GetCurrentProcess.return_value=123
        def open_token(process,rights,output):output._obj.value=100;return True
        security.OpenProcessToken.side_effect=open_token
        with patch.object(support.ctypes,'WinDLL',side_effect=lambda name,**_:security if name=='advapi32' else kernel),patch.object(support.ctypes,'get_last_error',return_value=0):
            enable()
        security.LookupPrivilegeValueW.assert_called_once()
        self.assertEqual(security.LookupPrivilegeValueW.call_args.args[1],'SeDebugPrivilege')
        security.AdjustTokenPrivileges.assert_called_once()
        kernel.CloseHandle.assert_called_once()
        kernel.OpenProcess.assert_not_called()

    def kernel(self,wait=0):
        api=Mock()
        api.OpenProcess.return_value=100
        api.VirtualAllocEx.return_value=200
        api.CreateRemoteThread.return_value=300
        api.GetModuleHandleW.return_value=400
        api.GetProcAddress.return_value=500
        api.WaitForSingleObject.return_value=wait
        def write(process,address,buffer,size,output):output._obj.value=size;return True
        def exit_code(thread,output):output._obj.value=1234;return True
        api.WriteProcessMemory.side_effect=write
        api.GetExitCodeThread.side_effect=exit_code
        return api

    def test_unknown_process_never_receives_injection(self):
        with patch.object(support,'is_wudfhost_process',return_value=False),patch.object(support.ctypes,'WinDLL') as api:
            with self.assertRaises(RuntimeError):support.inject_library(42,Path('test.dll'))
            api.assert_not_called()

    def test_load_timeout_does_not_free_path_still_owned_by_remote_thread(self):
        api=self.kernel(0x102)
        with patch.object(support,'is_wudfhost_process',return_value=True),patch.object(support.ctypes,'WinDLL',return_value=api):
            with self.assertRaises(TimeoutError):support.inject_library(42,Path('test.dll'))
        api.VirtualFreeEx.assert_not_called()
        self.assertEqual(api.CloseHandle.call_count,2)

    def test_finished_load_releases_path_and_handles(self):
        api=self.kernel()
        with patch.object(support,'is_wudfhost_process',return_value=True),patch.object(support.ctypes,'WinDLL',return_value=api):
            support.inject_library(42,Path('test.dll'),log=lambda _:None)
        api.VirtualFreeEx.assert_called_once_with(100,200,0,0x8000)
        self.assertEqual(api.CloseHandle.call_count,2)

    def test_short_write_refuses_to_start_remote_thread(self):
        api=self.kernel()
        def short_write(process,address,buffer,size,output):output._obj.value=size-2;return True
        api.WriteProcessMemory.side_effect=short_write
        with patch.object(support,'is_wudfhost_process',return_value=True),patch.object(support.ctypes,'WinDLL',return_value=api):
            with self.assertRaises(RuntimeError):support.inject_library(42,Path('test.dll'),log=lambda _:None)
        api.CreateRemoteThread.assert_not_called()
        api.VirtualFreeEx.assert_called_once()


if __name__=='__main__':unittest.main()
