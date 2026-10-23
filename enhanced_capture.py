"""Admin launcher for device-scoped HID observation and leased all-key filtering.

Injection primitives reused from the vendored GPL-3.0 MiRemoteVibe source.
Only a calibrated RC003 may consume keys; no global keyboard remapping.
"""
import ctypes,hashlib,json,lzma,os,re,secrets,socket,sys,time,winreg
from collections import deque
from ctypes import wintypes as W
from pathlib import Path
from rc003_bridge.paths import ROOT,DATA
CAPTURE_SCRIPT_NAME='enhanced_capture_v4.js'
ARCHIVE_HASH='b566d70189b6d551ad8f4e0bea24de08a3d4c0f559bb35b2bdb67d45182240c2'
DLL_HASH='6fca4007b2284c765a6c15c967a741f536b5865bf83867326a54029a3b752748'

def target_identity():
 base=r'SYSTEM\CurrentControlSet\Enum\BTHLEDevice';found=[];hosts=[]
 with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,base) as root:
  i=0
  while True:
   try:name=winreg.EnumKey(root,i);i+=1
   except OSError:break
   if not name.lower().startswith('{00001812-'):continue
   with winreg.OpenKey(root,name) as key:
    j=0
    while True:
     try:inst=winreg.EnumKey(key,j);j+=1
     except OSError:break
     try:
      with winreg.OpenKey(key,inst+r'\Device Parameters\WUDFDiagnosticInfo') as diagnostic:
       pid=int(winreg.QueryValueEx(diagnostic,'HostPid')[0])
       lifetime=str(winreg.QueryValueEx(diagnostic,'LifetimeID')[0])
      hosts.append((pid,name))
      if 'vid&012717_pid&32b8' in name.lower():found.append({'pid':pid,'lifetime':lifetime,'instance':name+'\\'+inst})
     except OSError:pass
 if len(found)!=1:raise RuntimeError('Expected exactly one active RC003 HID instance')
 # Hosts can be shared. The in-host tap must additionally verify each handle's
 # object identity before reading a report; host PID alone is insufficient.
 return found[0]

def target_host():
 return target_identity()['pid']

def host_started(pid):
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
 kernel.GetProcessTimes.argtypes=[W.HANDLE,*([ctypes.POINTER(W.FILETIME)]*4)]
 kernel.CloseHandle.argtypes=[W.HANDLE]
 process=kernel.OpenProcess(0x1000,False,pid)
 if not process:raise ctypes.WinError(ctypes.get_last_error())
 values=[W.FILETIME() for _ in range(4)]
 try:
  if not kernel.GetProcessTimes(process,*[ctypes.byref(v) for v in values]):raise ctypes.WinError(ctypes.get_last_error())
  return (values[0].dwHighDateTime<<32)|values[0].dwLowDateTime
 finally:kernel.CloseHandle(process)

def attachment_reusable(previous,identity,version,started):
 old=previous.get('identity',{})
 if previous.get('version')!=version or old.get('pid')!=identity['pid'] or old.get('instance')!=identity['instance']:return False
 if previous.get('hostStarted') is None:return False
 return previous['hostStarted']==started

def positions(usages):
 mapping={0x66:0,0x52:1,0x51:2,0x50:3,0x4f:4,0x28:5,0xf1:6,0x4a:7,0x65:8,0x3e:9,0x80:10,0x81:11,0x35:12}
 if not isinstance(usages,list) or len(usages)>3 or any(type(x) is not int or x not in mapping for x in usages):raise ValueError('Invalid remote usage report')
 return {mapping[u] for u in usages}

def attachment_mode(previous,identity,version,started,resident):
 """Never load a second Gadget into a host which already owns one."""
 old=previous.get('identity',{})
 same_host=old.get('pid')==identity['pid'] and previous.get('hostStarted')==started
 if same_host:
  if old.get('instance')!=identity['instance']:return 'restart-required'
  return 'reuse' if previous.get('version')==version else 'restart-required'
 if attachment_reusable(previous,identity,version,started):return 'reuse'
 return 'restart-required' if resident else 'fresh'

def resident_gadgets(pid):
 """An unreadable module list is an error, never permission to inject again."""
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 class Module(ctypes.Structure):
  _fields_=[('size',W.DWORD),('id',W.DWORD),('pid',W.DWORD),('globalUsage',W.DWORD),('processUsage',W.DWORD),
            ('base',ctypes.c_void_p),('baseSize',W.DWORD),('module',W.HMODULE),('name',W.WCHAR*256),('path',W.WCHAR*260)]
 kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
 kernel.Module32FirstW.argtypes=[W.HANDLE,ctypes.POINTER(Module)];kernel.Module32FirstW.restype=W.BOOL
 kernel.Module32NextW.argtypes=kernel.Module32FirstW.argtypes;kernel.Module32NextW.restype=W.BOOL
 kernel.CloseHandle.argtypes=[W.HANDLE]
 handle=kernel.CreateToolhelp32Snapshot(0x18,pid)
 if handle in (None,ctypes.c_void_p(-1).value):raise ctypes.WinError(ctypes.get_last_error())
 found=[]
 try:
  entry=Module();entry.size=ctypes.sizeof(entry)
  if not kernel.Module32FirstW(handle,ctypes.byref(entry)):raise ctypes.WinError(ctypes.get_last_error())
  while True:
   path=entry.path.lower()
   if 'rc003readonlytap' in path or 'codexrc003capture' in path or 'miremote-tap' in path or 'frida-gadget' in path:found.append(entry.path)
   if not kernel.Module32NextW(handle,ctypes.byref(entry)):
    if ctypes.get_last_error()!=18:raise ctypes.WinError(ctypes.get_last_error())
    break
  return found
 finally:kernel.CloseHandle(handle)

def voice_proof_matches(probe_time,raw_times,now):
 return type(probe_time) in (int,float) and 0<=now-probe_time<=1000 and any(abs(probe_time-raw)<=150 for raw in raw_times)

def calibration_scope(name):
 if not isinstance(name,str) or not re.fullmatch(r'\\device\\umdfctrldev-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',name):raise ValueError('Invalid UMDF device identity')
 return name

class VoiceCalibration:
 """Commit only a unique object after the entire fresh proof window closes."""
 def __init__(self):
  self.probes=deque(maxlen=128);self.used=set();self.issue=None
 def add(self,name,at,now):
  if type(at) not in (int,float) or not 0<=now-at<=4000:return
  try:name=calibration_scope(name)
  except ValueError:return
  # Delayed competing traffic still invalidates an uncommitted proof, but a
  # stale report can never be the positive evidence for a new binding.
  self.probes.append((name,at,now-at<=1000))
 def choose(self,raw_times,now,current_scope=None):
  # A probe may be 150ms after raw input and arrive up to 1000ms late.
  # 1250ms closes that entire interval; no first/last-event-wins binding.
  for raw in raw_times:
   if raw in self.used or not 1250<=now-raw<=3000:continue
   self.used.add(raw)
   matching=[(name,fresh) for name,at,fresh in self.probes if abs(at-raw)<=150]
   candidates={name for name,_ in matching}
   if len(candidates)>1:self.issue='ambiguous-voice-proof';continue
   if not candidates:continue
   if not any(fresh for _,fresh in matching):continue
   name=next(iter(candidates))
   if current_scope and name!=current_scope:
    self.issue='existing-calibration-retained';continue
   self.issue=None
   return name
  self.used.intersection_update(raw_times)
  while self.probes and now-self.probes[0][1]>4000:self.probes.popleft()
  return None

def filter_phase(acknowledged,allowed,armed,native_issue,permit_issue,relay_issue,diagnostic):
 if native_issue is not None:return 'filter_fault'
 if permit_issue or relay_issue:return 'waiting_bridge'
 if not acknowledged:return 'calibrating'
 if not allowed:return 'standby'
 if armed:return 'ready'
 if (diagnostic or {}).get('gate')=='waiting-neutral':return 'waiting_neutral'
 return 'standby'

def configured_address(config):
 identity=config.get('bluetoothDeviceId') if isinstance(config,dict) else None
 if not isinstance(identity,str):raise RuntimeError('Remote Bluetooth identity unavailable; wait for the bridge to connect')
 address=identity.rsplit('-',1)[-1].lower()
 if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',address):raise RuntimeError('Remote Bluetooth identity unavailable; wait for the bridge to connect')
 return address

def bridge_request(request):
 control=json.loads((DATA/'control.json').read_text())
 with socket.create_connection(('127.0.0.1',control['port']),3) as client:
  client.sendall((json.dumps({'token':control['token'],**request})+'\n').encode())
  reply=json.loads(client.makefile('rb').readline(8192))
  return reply

def command(position,down,generation=None,synthetic=False):
 request={'command':'enhanced-edge','position':position,'down':down,'source':'filtered-remote','generation':generation}
 if synthetic:request['synthetic']=True
 reply=bridge_request(request)
 if not reply.get('accepted'):raise RuntimeError(reply.get('error','Bridge rejected enhanced edge'))

def filtered_positions(event,scope,generation,allowed,acknowledged,fault):
 """Ignore stale/foreign reports; revoke current holds when permission is lost."""
 if (event.get('objectName')!=scope or type(event.get('generation')) is not int
     or event['generation']!=generation or event.get('allKeysFiltered') is not True
     or event.get('directionFiltered') is not True):return None
 if not allowed or not acknowledged or fault is not None:return set()
 return positions(event.get('usages'))

def capture_running():
 return not (DATA/'capture-stop.json').exists()

def attachment_permitted(permit,live_devices):
 return (live_devices==1 and permit.get('allowed') is True
         and type(permit.get('generation')) is int and permit['generation']>0)

class BridgeGuard:
 def __init__(self):self.last_seen=time.monotonic()
 def refresh(self):
  permit=bridge_request({'command':'direction-filter-permit'})
  if type(permit.get('generation')) is not int or permit['generation']<=0:raise ValueError('Bridge has no valid generation')
  self.last_seen=time.monotonic()
  return permit
 def alive(self):return capture_running() and time.monotonic()-self.last_seen<=10

class EdgeRelay:
 def __init__(self,deliver=command,release=None):
  self.deliver=deliver;self.release=release or deliver;self.held=set();self.issue=None
 def feed(self,current,synthetic=False):
  try:
   for position in sorted(self.held-current):
    (self.release if synthetic else self.deliver)(position,False);self.held.remove(position)
   for position in sorted(current-self.held):
    self.deliver(position,True);self.held.add(position)
   self.issue=None
  except (OSError,ValueError,RuntimeError) as error:
   issue=str(error)
   if issue!=self.issue:print('BRIDGE WAIT:',issue,flush=True)
   self.issue=issue
 def clear(self):self.feed(set(),synthetic=True)

def read_events(client,still_valid,ticks=False):
 """Unbuffered framing can resume after socket timeouts, unlike makefile()."""
 buffer=b'';last=time.monotonic()
 while still_valid():
  try:chunk=client.recv(8192)
  except socket.timeout:
   if time.monotonic()-last>6:raise ConnectionError('Capture heartbeat lost; waiting for reconnect')
   if ticks:yield {'kind':'tick'}
   continue
  if not chunk:return
  last=time.monotonic();buffer+=chunk
  if len(buffer)>32768:raise ValueError('Oversize capture message')
  while b'\n' in buffer:
   line,buffer=buffer.split(b'\n',1)
   yield json.loads(line)

def same_target(identity):
 try:return target_identity()==identity
 except (OSError,RuntimeError):return False

def read_saved(path):
 try:return json.loads(path.read_text(encoding='utf8'))
 except (OSError,ValueError):return {}

def capture_status(phase,**details):
 from rc003_bridge.runtime import write_json
 try:write_json(DATA/'capture-status.json',{'pid':os.getpid(),'phase':phase,'at':time.time(),**details})
 except OSError:pass

def serve(server,identity,token,raw_times,guard=None):
 from rc003_bridge.runtime import write_json
 cache_path=DATA/'capture-calibration.json'
 calibration=read_saved(cache_path)
 generation=None
 guard=guard or BridgeGuard()
 relay=EdgeRelay(lambda position,down:command(position,down,generation),lambda position,down:command(position,down,generation,synthetic=True))
 while guard.alive() and same_target(identity):
  try:client,_=server.accept()
  except socket.timeout:
   capture_status('waiting_capture');relay.clear()
   try:guard.refresh()
   except (OSError,ValueError,RuntimeError):pass
   continue
  try:
   with client:
    client.settimeout(.5)
    events=read_events(client,lambda:guard.alive() and same_target(identity),ticks=True)
    hello=next(events)
    while hello.get('kind')=='tick':hello=next(events)
    if hello.get('kind')!='hello' or hello.get('pid')!=identity['pid'] or not secrets.compare_digest(str(hello.get('token','')),token):raise ValueError('Invalid capture session')
    capable=hello.get('protocol')==3 and hello.get('build')=='remote-filter-v4'
    if not capable:raise ValueError('Legacy capture requires a normal Windows restart')
    allowed=False;permit_issue=None;permit_checked=False;native_issue=None;native_scope=None;direction_diagnostic=None
    print('CAPTURE: connected; a short Voice press calibrates a new HID object',flush=True)
    capture_status('calibrating')
    scope=calibration.get('objectName') if calibration.get('identity')==identity else None
    acknowledged=False
    proof=VoiceCalibration()
    def permit_status():
     return {'protocol':hello.get('protocol',1),'directionPermitAllowed':allowed,'generation':generation,
             'permitIssue':permit_issue,'calibrated':acknowledged,'permitChecked':permit_checked,'nativeIssue':native_issue,
             'captureBuild':hello.get('build'),'directionDiagnostic':direction_diagnostic,
             'relayIssue':relay.issue,'calibrationIssue':proof.issue}
    def publish(armed=False):
     phase=filter_phase(acknowledged,allowed,armed,native_issue,permit_issue,relay.issue,direction_diagnostic)
     detail=permit_status()
     detail['lastError']=(native_issue or {}).get('reason') or permit_issue or relay.issue
     direction_state='armed' if phase=='ready' else 'waiting-neutral' if phase=='waiting_neutral' else 'fault' if phase=='filter_fault' else 'standby'
     capture_status(phase,directionFilter=direction_state,**detail)
    def native_fault(fault):
     nonlocal native_issue,native_scope
     if not capable or not acknowledged or not isinstance(fault,dict) or type(fault.get('generation')) is not int or fault['generation']!=generation or fault.get('objectName')!=scope:return False
     native_issue={key:fault.get(key) for key in ('objectName','generation','reason','ret','iosbStatus')};native_scope=scope
     relay.clear()
     return True
    def renew():
     nonlocal generation,allowed,permit_issue,permit_checked,native_issue,native_scope
     if native_scope is not None and native_scope!=scope:native_issue=None;native_scope=None
     permit_checked=True
     try:
      permit=guard.refresh()
      next_generation=permit.get('generation')
      if type(next_generation) is not int or next_generation<=0:raise ValueError('Direction filter permit has no valid generation')
      if generation is not None and generation!=next_generation:
       # The old backend has exited; its held state no longer exists.
       relay.held.clear()
       native_issue=None;native_scope=None
      generation=next_generation;allowed=permit.get('allowed') is True;permit_issue=None
     except (OSError,ValueError,RuntimeError) as error:
      allowed=False;permit_issue=type(error).__name__+': '+str(error)
     if not capable or not acknowledged or not scope:return
     client.sendall((json.dumps({'kind':'direction-filter','token':token,'objectName':scope,'enabled':allowed,
                                'ttlMs':1500,'generation':generation or 1})+'\n').encode())
     if not allowed:relay.clear()
    def bind(name):
     client.sendall((json.dumps({'kind':'bind','token':token,'objectName':calibration_scope(name)})+'\n').encode())
    if scope:bind(scope)
    for event in events:
     kind=event.get('kind')
     if kind=='source' and scope and event.get('objectName')==scope:bind(scope)
     if kind=='voice-probe' and event.get('objectName'):
      proof.add(event['objectName'],event.get('at'),time.time()*1000)
     # Only settle after draining queued lines: choosing while iterating a
     # multi-line receive buffer could ignore a second already-arrived object.
     next_scope=proof.choose(list(raw_times),time.time()*1000,current_scope=scope) if kind=='tick' else None
     if next_scope and not acknowledged:
      scope=next_scope;bind(scope)
     if kind=='tick' and not acknowledged:publish()
     if kind=='bound':
      # A cached binding is valid only for this exact host lifetime and object.
      if not scope or event.get('objectName')!=scope:continue
      scope=calibration_scope(event['objectName'])
      acknowledged=True
      calibration={'identity':identity,'objectName':scope}
      try:write_json(cache_path,calibration)
      except OSError as error:print('Calibration cache write delayed:',error,flush=True)
      print('CALIBRATED:',scope,flush=True)
      renew()
      direction_diagnostic={'gate':'waiting-neutral'}
      publish()
     if kind=='keys':
      current=filtered_positions(event,scope,generation,allowed,acknowledged,native_issue)
      if current is None:continue
      relay.feed(current,synthetic=not allowed or not acknowledged or native_issue is not None)
      if not event.get('usages') and acknowledged:
       bridge_request({'command':'enhanced-neutral','source':'filtered-remote','generation':generation})
     elif kind=='neutral' and acknowledged and event.get('objectName')==scope and type(event.get('generation')) is int and event['generation']==generation:
      relay.feed(set())
      bridge_request({'command':'enhanced-neutral','source':'filtered-remote','generation':generation})
     elif kind=='filter-fault':
      if native_fault(event):publish()
     elif kind=='heartbeat':
      if capable:client.sendall((json.dumps({'kind':'keepalive','token':token})+'\n').encode())
      diagnostic=event.get('directionFilterDiagnostic')
      if isinstance(diagnostic,dict):
       direction_diagnostic={key:diagnostic[key] for key in ('gate','scopeHits','selectorAccepted','neutralSeen','clearsVerified','completionAccepted','lastRet','lastIosbStatus') if key in diagnostic}
      native_fault(event.get('directionFilterFault'))
      renew()
      armed=event.get('directionFilterArmed') is True and event.get('directionFilterGeneration')==generation
      publish(armed=armed)
      if relay.issue:relay.clear()
  except (OSError,ValueError,RuntimeError,StopIteration) as error:
   print('CAPTURE WAIT:',str(error),flush=True)
  finally:relay.clear()
 capture_status('waiting_device')

def run():
 from capture_support import CaptureInstance,CaptureAlreadyRunningError
 try:
  with CaptureInstance():
   if not ctypes.windll.shell32.IsUserAnAdmin():raise RuntimeError('Run this helper as administrator')
   return _run_owned()
 except CaptureAlreadyRunningError:
  # A duplicate cannot overwrite the status of the session's active owner.
  raise
 except Exception as error:
  capture_status('error',directionFilter='standby',lastError=type(error).__name__+': '+str(error))
  raise

def _run_owned():
 import capture_support as tap
 from rc003_bridge.rawinput import RawInputListener,remote_device_count
 from rc003_bridge.runtime import write_json
 DATA.mkdir(parents=True,exist_ok=True)
 # Only an explicit launcher invocation revives a stopped helper.
 (DATA/'capture-stop.json').unlink(missing_ok=True)
 device=configured_address(json.loads((DATA/'config.json').read_text()))
 guard=BridgeGuard()
 if not attachment_permitted(guard.refresh(),1):raise RuntimeError('Remote bridge is not ready; connect the remote and enable dispatch first')
 tap.enable_debug_privilege()
 archive=ROOT/'vendor/frida/frida-gadget-17.15.3-windows-x86_64.dll.xz'
 packed=archive.read_bytes()
 if hashlib.sha256(packed).hexdigest()!=ARCHIVE_HASH:raise RuntimeError('Gadget archive hash mismatch')
 dll=lzma.decompress(packed)
 if hashlib.sha256(dll).hexdigest()!=DLL_HASH:raise RuntimeError('Gadget DLL hash mismatch')
 raw_times=deque(maxlen=32)
 raw_voice_down=False
 def raw_trace(event):
  nonlocal raw_voice_down
  if event.get('kind')=='keyboard' and event.get('vkey')==0x74:
   down=not event.get('flags',1)&1
   if down and not raw_voice_down:raw_times.append(time.time()*1000)
   raw_voice_down=down
 listener=RawInputListener(lambda kind,data:None,trace=raw_trace)
 listener.start()
 server=None;active_generation=None;token=None
 try:
  while guard.alive():
   # A registry host can outlive the device. Live input and the authenticated
   # bridge owning the shared hardware mutex must both agree before attaching.
   try:permitted=attachment_permitted(guard.refresh(),remote_device_count())
   except (OSError,ValueError,RuntimeError) as error:
    capture_status('waiting_bridge',issue=str(error));time.sleep(.5);continue
   if not permitted:capture_status('waiting_device');time.sleep(.5);continue
   try:identity=target_identity()
   except (OSError,RuntimeError):capture_status('waiting_device');time.sleep(2);continue
   pid=identity['pid']
   if not tap.is_wudfhost_process(pid):time.sleep(2);continue
   script=(ROOT/CAPTURE_SCRIPT_NAME).read_text()
   version=hashlib.sha256((script+device).encode()).hexdigest()
   attachment_path=DATA/'capture-attachment.json'
   previous=read_saved(attachment_path)
   try:
    started=host_started(pid);generation=(pid,started,version)
    if server is None or active_generation!=generation:
     if server:server.close();server=None
     old=previous.get('identity',{})
     same_host=old.get('pid')==pid and previous.get('hostStarted')==started
     mode=attachment_mode(previous,identity,version,started,[] if same_host else resident_gadgets(pid))
     if mode=='restart-required':
      capture_status('restart_required',directionFilter='restart-required');time.sleep(2);continue
     reuse=mode=='reuse'
     server=socket.socket()
     server.bind(('127.0.0.1',previous['port'] if reuse else 0));server.listen(4);server.settimeout(1)
     token=previous['token'] if reuse else secrets.token_hex(24)
     if not reuse:
      folder=DATA/'capture'/secrets.token_hex(8);folder.mkdir(parents=True)
      library=folder/'Rc003ReadOnlyTap.dll';library.write_bytes(dll)
      (folder/'Rc003ReadOnlyTap.config').write_text(json.dumps({'interaction':{'type':'script','path':'tap.js','on_change':'ignore'},'runtime':'qjs'}))
      code=script.replace('__CONFIG__',json.dumps({'port':server.getsockname()[1],'token':token,'address':device}))
      (folder/'tap.js').write_text(code,encoding='utf8')
     if not guard.alive() or not same_target(identity) or not attachment_permitted(guard.refresh(),remote_device_count()):server.close();server=None;continue
     # Record the attempted attachment before loading. An uncertain native
     # timeout may finish later; keep listening rather than loading more DLLs.
     write_json(attachment_path,{'identity':identity,'hostStarted':started,'port':server.getsockname()[1],'token':token,'version':version})
     active_generation=generation
     if not reuse:
      try:tap.inject_library(pid,library,log=lambda text:print(text,flush=True))
      except (OSError,RuntimeError) as error:print('HOST WAIT: one attach attempted; awaiting callback:',error,flush=True)
    elif previous.get('identity')!=identity:
     write_json(attachment_path,{'identity':identity,'hostStarted':started,'port':server.getsockname()[1],'token':token,'version':version})
    serve(server,identity,token,raw_times,guard)
   except (OSError,ValueError,RuntimeError) as error:
    print('HOST WAIT: retrying listener or telemetry:',error,flush=True)
    if server:server.close();server=None
    active_generation=None;time.sleep(2)
 finally:
  listener.stop()
  if server:server.close()
  capture_status('stopped',directionFilter='standby')

if __name__=='__main__':
 try:run()
 except Exception as error:print('ERROR:',error,flush=True);sys.exit(1)
