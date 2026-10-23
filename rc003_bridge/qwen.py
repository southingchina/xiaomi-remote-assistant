"""Independent Qianwen IPC and recording ownership; no plugin runtime required."""
import getpass
import os
from pathlib import Path
import re
import secrets
import struct
import threading
import time


class QwenIpcError(RuntimeError):
    def __init__(self,message,*,sent,outcome=None):
        super().__init__(message)
        # `sent` is conservative: a command may have executed, not merely that
        # bytes entered the pipe. Only a matching, explicit refusal is retryable.
        self.sent=sent
        self.outcome=outcome or ('unknown' if sent else 'not_sent')


def encode_packet(command, payload='', request_id=None):
    request_id = secrets.randbits(63) if request_id is None else request_id
    body = payload.encode('utf8')
    return struct.pack('<4sHHIIQQ', b'QIPC', 1, 32, command, len(body), request_id, 0) + body + b'QIPT'


def decode_packet(packet):
    if len(packet) < 36:
        raise ValueError('Incomplete Qianwen response')
    magic, version, width, command, size, request_id, _ = struct.unpack_from('<4sHHIIQQ', packet)
    if magic != b'QIPC' or version != 1 or width != 32 or size > 1024*1024-36:
        raise ValueError('Invalid Qianwen response header')
    if len(packet) != size+36 or packet[-4:] != b'QIPT':
        raise ValueError('Invalid Qianwen response length or tail')
    fields = dict(line.split('=',1) for line in packet[32:-4].decode('utf8').splitlines() if '=' in line)
    return {'command':command, 'id':request_id, 'fields':fields}


def pipe_request(endpoint, command, payload='', timeout=2):
    """One bounded overlapped pipe transaction. Ambiguous commands are never retried."""
    import ctypes as C
    from ctypes import wintypes as W
    if os.name != 'nt': raise OSError('Qianwen named pipes require Windows')
    class Overlapped(C.Structure):
        _fields_=[('internal',C.c_size_t),('internalHigh',C.c_size_t),('offset',W.DWORD),('offsetHigh',W.DWORD),('event',W.HANDLE)]
    kernel=C.WinDLL('kernel32',use_last_error=True)
    def bind(name,result,*args):
        function=getattr(kernel,name);function.restype=result;function.argtypes=list(args);return function
    create=bind('CreateFileW',W.HANDLE,W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE)
    wait_pipe=bind('WaitNamedPipeW',W.BOOL,W.LPCWSTR,W.DWORD)
    close=bind('CloseHandle',W.BOOL,W.HANDLE)
    event_create=bind('CreateEventW',W.HANDLE,C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR)
    event_wait=bind('WaitForSingleObject',W.DWORD,W.HANDLE,W.DWORD)
    result=bind('GetOverlappedResult',W.BOOL,W.HANDLE,C.POINTER(Overlapped),C.POINTER(W.DWORD),W.BOOL)
    cancel=bind('CancelIoEx',W.BOOL,W.HANDLE,C.POINTER(Overlapped))
    read=bind('ReadFile',W.BOOL,W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.POINTER(Overlapped))
    write=bind('WriteFile',W.BOOL,W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.POINTER(Overlapped))
    deadline=time.monotonic()+timeout
    if not wait_pipe(endpoint,max(1,int(timeout*1000))): raise QwenIpcError(str(C.WinError(C.get_last_error())),sent=False)
    handle=create(endpoint,0xC0000000,0,None,3,0x40000000,None)
    if handle == C.c_void_p(-1).value: raise QwenIpcError(str(C.WinError(C.get_last_error())),sent=False)
    issued=False
    def transfer(operation,buffer,size):
        nonlocal issued
        event=event_create(None,True,False,None)
        if not event:raise C.WinError(C.get_last_error())
        pending=Overlapped();pending.event=event;done=W.DWORD()
        try:
            if operation is write:issued=True
            ok=operation(handle,buffer,size,C.byref(done),C.byref(pending))
            error=C.get_last_error()
            if not ok and error not in (997,234):raise C.WinError(error)
            if not ok and error==997:
                remaining=max(0,int((deadline-time.monotonic())*1000))
                if event_wait(event,remaining)!=0:
                    cancel(handle,C.byref(pending))
                    result(handle,C.byref(pending),C.byref(done),True)
                    raise TimeoutError('Qianwen IPC timed out; command was not retried')
                if not result(handle,C.byref(pending),C.byref(done),False) and C.get_last_error()!=234:
                    raise C.WinError(C.get_last_error())
            return done.value
        finally:close(event)
    try:
        packet=encode_packet(command,payload);request_id=struct.unpack_from('<Q',packet,16)[0]
        buffer=C.create_string_buffer(packet)
        if transfer(write,buffer,len(packet))!=len(packet):raise OSError('Incomplete Qianwen request write')
        received=bytearray()
        while True:
            buffer=C.create_string_buffer(4096);count=transfer(read,buffer,len(buffer))
            if not count:raise OSError('Qianwen IPC closed before complete response')
            received.extend(buffer.raw[:count])
            if len(received)>1024*1024:raise ValueError('Oversized Qianwen response')
            if len(received)>=32:
                length=36+struct.unpack_from('<I',received,12)[0]
                if length>1024*1024:raise ValueError('Oversized Qianwen response')
                if len(received)>=length:break
        response=decode_packet(received)
        if response['command']!=command or response['id']!=request_id:raise ValueError('Qianwen response mismatch')
        if response['fields'].get('ok')!='1':
            rejected=response['fields'].get('ok')=='0'
            raise QwenIpcError(response['fields'].get('diagnostic','Qianwen did not acknowledge request'),
                               sent=not rejected,outcome='rejected' if rejected else 'unknown')
        return response
    except QwenIpcError:raise
    except Exception as error:
        raise QwenIpcError(str(error),sent=issued) from error
    finally:close(handle)


def parse_surface_state(text):
    current=legacy=None
    terminal={'finished','cancel','abort','start_failed','runtime_terminal'}
    for line in text.splitlines():
        fields=dict(re.findall(r'\b(component|stage|session|pid|monotonic_ms|event|reason|status)=([^\s]+)',line))
        if 'voice_shortcut_txn' in line and fields.get('component')=='utility' and all(fields.get(key) for key in ('pid','session','monotonic_ms')):
            try:stamp=int(fields['monotonic_ms'])
            except ValueError:continue
            session=fields['pid']+':'+fields['session'];stage=fields.get('stage')
            if stage in ('begin','commit'):current={'state':1 if stage=='begin' else 2,'session':session,'time':stamp}
            elif stage in terminal and (current is None or current['session']==session):current={'state':0,'session':session,'time':stamp}
        if current and current['state']==1 and fields.get('component')=='voice_runtime' and fields.get('event')=='runtime_handoff_complete' and fields.get('reason')=='accepted' and fields.get('status')=='0' and fields.get('pid')==current['session'].split(':')[0]:
            try:stamp=int(fields.get('monotonic_ms',''))
            except ValueError:continue
            if 0<=stamp-current['time']<=5000:current={**current,'state':2,'time':stamp}
        if 'event=surface_state' in line:
            values=dict(re.findall(r'\b(state|overlay_session|epoch_ms)=(\d+)',line))
            if len(values)==3:legacy={'state':int(values['state']),'session':values['overlay_session'],'time':int(values['epoch_ms'])}
    return current if current is not None else legacy


class QwenState:
    supports_owners=True

    def __init__(self,path=None,read_state=None,send_toggle=None,timeout=3):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'QianwenIME/logs/qianwen_voice_shortcut.log'
        self.endpoint='\\\\.\\pipe\\QianwenIME_'+getpass.getuser()+'_Pipe'
        self._read=read_state;self._toggle=send_toggle or self._send_toggle
        self.timeout=timeout;self.owned=None;self.pending_start=None;self.pending_session=None;self.stop_pending=False
        self.owned_owner=None;self.pending_owner=None;self.cleanup_required=False
        self.lock=threading.RLock()

    def read(self):
        if self._read: value=self._read()
        else:
            with self.path.open('rb') as file:
                file.seek(0,2);file.seek(max(0,file.tell()-65536));value=parse_surface_state(file.read().decode('utf8',errors='replace'))
        if value is None:raise RuntimeError('Qianwen has no confirmed recording transaction')
        return {**value,'recording':value['state']==2,'id':value['session']}

    def _send_toggle(self):
        response=pipe_request(self.endpoint,50,'voice_event=1\nime_text_insertion_available=0\nime_notification_window=0\n')
        if response['fields'].get('handled')!='1':
            rejected=response['fields'].get('handled')=='0'
            raise QwenIpcError('Qianwen did not handle the voice command',sent=not rejected,
                               outcome='rejected' if rejected else 'unknown')

    def wait_for(self,predicate,timeout=None):
        deadline=time.monotonic()+(self.timeout if timeout is None else timeout)
        while True:
            value=self.read()
            if predicate(value):return value
            if time.monotonic()>=deadline:raise TimeoutError('Qianwen recording state was not confirmed')
            time.sleep(.025)

    @staticmethod
    def newer(value,before):
        # Identity wins over timestamps. A legacy epoch and a new monotonic
        # transaction are incomparable; an updated old session is not a start.
        identity=lambda item:item.get('session') or item.get('id')
        current_id,before_id=identity(value),identity(before)
        if current_id and before_id:return current_id!=before_id
        def clock(item):
            token=identity(item) or ''
            return item.get('clock') or ('monotonic' if ':' in token else 'epoch' if token.isdecimal() else None)
        return clock(value)==clock(before) and value['time']>before['time']

    def wait_started(self,before,timeout=None):
        return self.wait_for(lambda value:value['state']==2 and self.newer(value,before),timeout)

    def _forget(self):
        self.owned=None;self.owned_owner=None
        self.pending_start=None;self.pending_session=None;self.pending_owner=None
        self.stop_pending=False;self.cleanup_required=False

    def needs_cleanup(self,owner=None):
        with self.lock:
            token=self.pending_owner if self.pending_start is not None else self.owned_owner
            return self.cleanup_required and token==owner

    def start(self,owner=None):
        with self.lock:
            if self.cleanup_required:raise RuntimeError('The previous Qianwen recording must stop before starting another')
            before=self.read()
            if self.owned and before['state']==2 and before['session']==self.owned and self.owned_owner==owner and not self.stop_pending:return
            if self.pending_start is not None:raise RuntimeError('The previous Qianwen start is unresolved')
            if before['state']==2:raise RuntimeError('Qianwen is already recording another session')
            if before['state'] in (1,3):raise RuntimeError('Qianwen is still starting or processing the previous recording')
            self._forget();self.pending_start=before;self.pending_owner=owner
            try:
                self._toggle()
                current=self.wait_started(before)
                self.owned=current['session'];self.owned_owner=owner;self.pending_start=None;self.pending_owner=None
            except Exception as error:
                if isinstance(error,FileNotFoundError) or getattr(error,'sent',True) is False:
                    self._forget()
                    raise
                try:
                    current=self.read()
                    if current['state']==2 and self.newer(current,before):
                        self.owned=current['session'];self.owned_owner=owner;self.pending_start=None;self.pending_owner=None
                    elif current['state']==1 and self.newer(current,before):self.pending_session=current['session']
                    elif current['state']==0 and self.newer(current,before):self._forget()
                except (OSError,RuntimeError):pass
                raise

    def stop_owned(self,owner=None):
        with self.lock:
            if not self.owned and self.pending_start is None:return
            token=self.pending_owner if self.pending_start is not None else self.owned_owner
            if token!=owner:return
            self.cleanup_required=True
            current=self.read()
            if self.pending_start is not None:
                if not self.newer(current,self.pending_start):raise RuntimeError('The previous Qianwen start is unresolved')
                if current['state']==2 and self.pending_session and current['session']==self.pending_session:
                    self.owned=current['session'];self.owned_owner=owner;self.pending_start=None;self.pending_session=None;self.pending_owner=None
                elif current['state']==0:self._forget();return
                else:raise RuntimeError('Qianwen recording start has not settled or its session is unowned')
            session=self.owned
            if current['session']!=session or current['state'] in (0,3):
                self._forget();return
            if current['state']!=2:raise RuntimeError('Qianwen is still starting the recording to stop')
            if not self.stop_pending:
                self.stop_pending=True
                try:self._toggle()
                except Exception as error:
                    # An unopened/refused pipe did not issue a toggle. Keep
                    # ownership and permit cleanup to send the stop again.
                    if isinstance(error,FileNotFoundError) or getattr(error,'sent',True) is False:
                        self.stop_pending=False
                    raise
            self.wait_for(lambda value:value['session']!=session or value['state'] in (0,3))
            self._forget()

    def toggle(self,owner=None):
        with self.lock:
            if self.cleanup_required:
                token=self.pending_owner if self.pending_start is not None else self.owned_owner
                self.stop_owned(owner=token)
                return
            if self.pending_start is not None:raise RuntimeError('The previous Qianwen start is unresolved')
            current=self.read()
            if current['state']==2:
                # An explicit toggle may stop current recording. Existing
                # ownership stays with its original press until it is ended.
                if self.owned!=current['session']:
                    self._forget();self.owned=current['session'];self.owned_owner=owner
                self.stop_owned(owner=self.owned_owner)
            else:self.start(owner=owner)
