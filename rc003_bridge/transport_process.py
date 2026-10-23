"""One disposable native BLE owner; a stalled COM Close cannot freeze input."""
import asyncio
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .paths import ROOT, DATA, child_command
CLOSE_TIMEOUT = 2


class WorkerLifetime:
    """Windows releases the BLE child even if its controller crashes."""
    def __init__(self,pid):
        class Basic(ctypes.Structure):
            _fields_=[('processTime',ctypes.c_int64),('jobTime',ctypes.c_int64),('flags',W.DWORD),
                      ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',W.DWORD),
                      ('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
        class Limits(ctypes.Structure):
            _fields_=[('basic',Basic),('io',ctypes.c_uint64*6),('processMemory',ctypes.c_size_t),
                      ('jobMemory',ctypes.c_size_t),('peakProcess',ctypes.c_size_t),('peakJob',ctypes.c_size_t)]
        kernel=self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,W.LPCWSTR];kernel.CreateJobObjectW.restype=W.HANDLE
        kernel.SetInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD]
        kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
        kernel.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE]
        kernel.CloseHandle.argtypes=[W.HANDLE]
        self.handle=kernel.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Limits();limits.basic.flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process=None
        try:
            if not kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):raise ctypes.WinError(ctypes.get_last_error())
            process=kernel.OpenProcess(0x100|0x1,False,pid)
            if not process or not kernel.AssignProcessToJobObject(self.handle,process):raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self.close();raise
        finally:
            if process:kernel.CloseHandle(process)

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


def worker_command():
    # Windows venv launchers spawn a second interpreter. Own the actual process
    # so killing a hung transport also releases its native Bluetooth resources.
    if getattr(sys,'frozen',False):return child_command('rc003_bridge.transport_worker')
    return [sys._base_executable,'-X','utf8','-m','rc003_bridge.transport_worker']


class ProcessTransport:
    def __init__(self, callback, progress=None):
        self.callback = callback
        self.progress = progress or (lambda stage: None)
        self.process = None
        self.lifetime = None
        self.reader = self.monitor = None
        self.pending = {}
        self.sequence = 0
        self.closed = False
        self.received = time.monotonic()

    async def request(self, command, timeout, **data):
        self.sequence += 1
        number = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[number] = future
        try:
            self.process.stdin.write((json.dumps({'id':number,'command':command,**data})+'\n').encode())
            await self.process.stdin.drain()
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(number,None)

    async def read(self):
        try:
            while line := await self.process.stdout.readline():
                self.received = time.monotonic()
                message = json.loads(line)
                if 'id' in message:
                    future = self.pending.get(message['id'])
                    if future is not None and not future.done():
                        if 'error' in message: future.set_exception(RuntimeError(message['error']))
                        else: future.set_result(message.get('result'))
                elif not self.closed:
                    kind,data = message.get('kind'),message.get('data')
                    if kind == 'stage': self.progress(data)
                    elif kind == 'heartbeat': pass
                    else:
                        if kind in ('audio','control'): data=bytes.fromhex(data)
                        elif kind == 'battery': data=(bytes.fromhex(data[0]),data[1])
                        self.callback(kind,data)
        except asyncio.CancelledError: raise
        except Exception as error:
            if not self.closed: self.callback('transport_error',str(error))
        finally:
            for future in list(self.pending.values()):
                if not future.done(): future.set_exception(ConnectionError('Bluetooth worker exited'))
            if not self.closed: self.callback('disconnected',None)

    async def watch(self):
        while not self.closed:
            await asyncio.sleep(1)
            if time.monotonic()-self.received > 6:
                self.callback('transport_error','Native Bluetooth worker stopped responding')
                return

    async def connect(self, device_id):
        environment = dict(os.environ)
        environment['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path)
        DATA.mkdir(parents=True,exist_ok=True)
        log = (DATA/'ble-worker.log').open('ab')
        try:
            self.process = await asyncio.create_subprocess_exec(*worker_command(),cwd=ROOT,env=environment,
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        finally: log.close()
        self.lifetime=WorkerLifetime(self.process.pid) if os.name=='nt' else None
        self.reader = asyncio.create_task(self.read())
        self.monitor = asyncio.create_task(self.watch())
        return await self.request('connect',45,deviceId=device_id)

    async def write(self, data):
        return await self.request('write',4,data=bytes(data).hex())

    async def close(self):
        self.closed = True
        process = self.process
        if process is not None:
            if process.returncode is None:
                try: await self.request('close',CLOSE_TIMEOUT)
                except Exception: pass
                if process.stdin: process.stdin.close()
                try: await asyncio.wait_for(process.wait(),CLOSE_TIMEOUT)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            if process.stdin:
                try: await process.stdin.wait_closed()
                except (BrokenPipeError,ConnectionResetError,OSError): pass
        for task in (self.reader,self.monitor):
            if task is not None:
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
        self.reader = self.monitor = self.process = None
        if self.lifetime:self.lifetime.close();self.lifetime=None
