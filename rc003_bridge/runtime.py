"""One owner for BLE, bounded audio, and device-filtered native actions."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time

from .core import ActionRouter, AtvvSession, DirectionOwners
from .standalone import NativeDispatcher, ProfileResolver
from .qwen import QwenState
from .paths import ROOT, DATA, CONFIG, STATUS, CONTROL


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',prefix=path.stem+'-',suffix='.tmp',
                                     dir=path.parent,delete=False) as file:
        temporary = Path(file.name)
        json.dump(value,file,ensure_ascii=False,indent=2)
    try:
        for attempt in range(4):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 3: raise
                time.sleep(.02)
    finally:
        temporary.unlink(missing_ok=True)


def configuration():
    defaults = {'schemaVersion':1, 'dispatchEnabled':True, 'bluetoothDeviceId':None,
                'audioOutput':None, 'retrySeconds':3,'qwenAudioRouteConfirmed':False,
                'inputMode':'filtered-remote', 'enhancedCaptureEnabled':True,'consumeRemoteDirections':True}
    if not CONFIG.exists():
        write_json(CONFIG,defaults)
    stored=json.loads(CONFIG.read_text(encoding='utf8'))
    if not isinstance(stored,dict):raise ValueError('Hardware configuration must be an object')
    value={**defaults,**stored}
    for key in ('dispatchEnabled','qwenAudioRouteConfirmed','enhancedCaptureEnabled','consumeRemoteDirections'):
        if type(value[key]) is not bool:raise ValueError('Setting must be boolean: '+key)
    if type(value['retrySeconds']) not in (int,float) or not .1<=value['retrySeconds']<=60:raise ValueError('Invalid reconnect delay')
    return value


class BridgeRuntime:
    def __init__(self, config=None, resolver=None, dispatcher=None, qwen=None):
        self.config = configuration() if config is None else dict(config)
        self.stop = asyncio.Event()
        self.queue = asyncio.Queue(maxsize=256)
        self.overflow = False
        self.epoch = 0
        self.bound = False
        self.session = None
        self.transport = None
        self.output = None
        self.voice_active = False
        self.voice_requires_request = False
        self.voice_reject_until_release = False
        self.voice_release_pending = False
        self.voice_physical_down = False
        self.voice_physical_cycle = self.voice_failed_cycle = 0
        self.voice_stream_cycle = 0
        self.voice_finish_task = self.voice_finish_future = self.voice_finishing_output = None
        self.voice_finish_abort = None
        self.voice_release_lock = asyncio.Lock()
        self.voice_pending_binding = None
        self.voice_physical_changed = asyncio.Event()
        self.qwen = qwen or QwenState()
        self.dispatcher = dispatcher or NativeDispatcher(qwen=self.qwen)
        self.resolver = resolver or ProfileResolver()
        self.router = ActionRouter(self.resolver.resolve,self.dispatcher.send)
        self.action_lock = asyncio.Lock()
        self.physical = {'raw':set(),'enhanced':set()}
        self.observed = {'raw':set(),'enhanced':set()}
        self.input_revision = 0
        self.awaiting_neutral = False
        self.paused = False
        self.direction_owners = DirectionOwners()
        self.direction_generation = secrets.randbits(31)+1
        self.direction_lease_until = 0
        self.direction_pending_releases = set()
        self.direction_lock = asyncio.Lock()
        self.state = {'pid':os.getpid(),'phase':'starting','pairedCount':0,'audioReady':False,
                      'rawInputReady':False,'voiceActive':False,'receivedAudioBytes':0,
                      'batteryLevel':None,'batterySource':None,'batteryUpdatedAt':None,'batteryIssue':None,
                      'decodedSamples':0,'dispatchedEdges':0,'physicalHardwareVerified':False,
                      'captureBoundary':'All custom actions require device-filtered input; Raw Input is observation only',
                      'actionService':'capture_required','paused':False,'awaitingNeutral':False,
                      'specialKeyCapture':'requires v4 enhanced report source and real-device verification'}

    def publish(self, **changes):
        self.state.update(changes)
        self.state['at'] = datetime.now(timezone.utc).isoformat()
        self.state['heldButtons'] = len(self.router.held)
        self.state['paused'] = self.paused
        self.state['awaitingNeutral'] = self.awaiting_neutral
        self.state['dispatchEnabled'] = self.config.get('dispatchEnabled',False) and not self.paused
        self.state['configurationPending'] = self.awaiting_neutral
        self.state['nativeError'] = getattr(self.dispatcher,'last_error',None)
        output=self.output or self.voice_finishing_output
        self.state['audioPendingSeconds']=getattr(output,'pending_seconds',0)
        self.state['voiceFinishing']=self.voice_finish_pending() or (not self.voice_active and self.output is not None)
        self.state['voiceReleasePending']=self.voice_release_pending
        self.state['actionService'] = ('paused' if self.paused else 'awaiting_neutral' if self.awaiting_neutral
            else 'ready' if self.state.get('phase')=='ready' and self.state.get('enhancedCaptureReady') else 'capture_required')
        try:
            write_json(STATUS,self.state)
            self.state.pop('statusWriteError',None)
        except OSError as error:
            # Telemetry must never stop radio recovery or key-up cleanup.
            self.state['statusWriteError'] = str(error)

    def apply_battery(self, epoch, data, source):
        from .bluetooth import battery_level
        if not self.bound or epoch != self.epoch: return False
        value=battery_level(data)
        self.publish(batteryLevel=value,batterySource=source if value is not None else None,
                     batteryUpdatedAt=datetime.now(timezone.utc).isoformat() if value is not None else None,
                     batteryIssue=None if value is not None else 'Battery Level is invalid or unknown')
        return True

    def enqueue(self, epoch, kind, data):
        if kind in ('key','enhanced-key','enhanced-direction'):
            self.state['lastKeyPosition'],self.state['lastKeyDown'] = data
            self.state['lastKeyAt'] = datetime.now(timezone.utc).isoformat()
            position,down=data;source='raw' if kind=='key' else 'enhanced'
            if down:self.observed[source].add(position)
            else:self.observed[source].discard(position)
            data=(position,down,self.input_revision)
        try: self.queue.put_nowait((epoch,kind,data))
        except asyncio.QueueFull: self.overflow = True

    def raw_trace(self, event):
        self.state['rawInputEvents'] = self.state.get('rawInputEvents',0)+1
        self.state['lastRawKind'] = event.get('kind')
        self.state['lastRawVkey'] = event.get('vkey')
        self.state['lastRawScan'] = event.get('scan')
        self.state['lastRawFlags'] = event.get('flags')
        self.state['lastRawAt'] = datetime.now(timezone.utc).isoformat()
        # RawInputListener has already restricted these reports to the RC003.
        # F5 is physical voice, but never a global keyboard shortcut here.
        if event.get('kind') == 'keyboard' and event.get('vkey') == 0x74 and event.get('scan') == 0x3f and event.get('flags') in (0,1):
            down = event['flags'] == 0
            self.physical_voice(down)

    def physical_voice(self,down):
        if down and not self.voice_physical_down:self.voice_physical_cycle += 1
        if down != self.voice_physical_down:self.voice_physical_changed.set()
        self.voice_physical_down = down
        self.state.update(voicePhysicalDown=down,voicePhysicalCycle=self.voice_physical_cycle)

    def note(self, event, **fields):
        path = DATA/'events.jsonl'
        try:
            if path.exists() and path.stat().st_size > 256*1024:
                path.replace(DATA/'events.previous.jsonl')
            with path.open('a',encoding='utf8') as file:
                file.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'event':event,**fields},ensure_ascii=False)+'\n')
        except OSError as error:
            self.state['eventWriteError'] = str(error)

    async def control_client(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(),3)
            if len(line)>128*1024:raise ValueError('Control request exceeds 128 KiB')
            request = json.loads(line)
            if not secrets.compare_digest(str(request.get('token','')),self.token):
                result = {'error':'unauthorized'}
            else:
                try:result=await self.command(request)
                except Exception as error:result={'error':str(error)}
            writer.write(json.dumps(result,ensure_ascii=False).encode('utf8')+b'\n')
            await writer.drain()
        except Exception as error:
            try:
                writer.write(json.dumps({'error':'Invalid control request: '+str(error)},ensure_ascii=False).encode('utf8')+b'\n')
                await writer.drain()
            except (OSError,ConnectionError):pass
        finally:
            writer.close(); await writer.wait_closed()

    async def command(self,request):
        command=request.get('command')
        if command=='status':return dict(self.state,paused=self.paused,awaitingNeutral=self.awaiting_neutral)
        if command=='direction-filter-permit':
            allowed=self.direction_filter_allowed()
            self.direction_lease_until=time.monotonic()+1.8 if allowed else 0
            return {'allowed':allowed,'generation':self.direction_generation,'allKeys':True}
        if command=='enhanced-neutral':
            if request.get('source')!='filtered-remote' or request.get('generation')!=self.direction_generation:
                return {'error':'invalid neutral source or generation'}
            self.observed['enhanced'].clear()
            self.physical_voice(False)
            self.enqueue(0,'enhanced-neutral',None)
            return {'accepted':True}
        if command=='enhanced-edge':
            position=request.get('position');down=request.get('down')
            if type(position) is not int or not 0<=position<13 or type(down) is not bool:
                return {'error':'unsupported enhanced edge'}
            if request.get('source')!='filtered-remote' or request.get('generation')!=self.direction_generation or (down and (not self.direction_filter_allowed() or time.monotonic()>=self.direction_lease_until)):
                return {'error':'filter is not permitted for this source or generation'}
            if request.get('synthetic'):
                if down:return {'error':'synthetic down is unsupported'}
                async with self.action_lock:
                    self.awaiting_neutral=True
                    if position==9 and (self.voice_active or self.voice_release_pending):
                        await self.abort_voice();await self.abort_voice_finish()
                    await self.edge(position,False)
                    self.publish()
                return {'accepted':True}
            # Wake a pending ATVV control before the serialized input consumer.
            if position==9:self.physical_voice(down);self.voice_physical_changed.set()
            self.enqueue(0,'enhanced-key',(position,down))
            return {'accepted':True}
        if command in ('reload-config','settings','pause','resume','stop','reconnect'):
            async with self.action_lock:
                if command=='settings':
                    updates=request.get('settings',{key:value for key,value in request.items() if key not in ('command','token')})
                    if not isinstance(updates,dict):raise ValueError('settings must be an object')
                    allowed={'audioOutput','qwenAudioRouteConfirmed','enhancedCaptureEnabled','consumeRemoteDirections','dispatchEnabled'}
                    if set(updates)-allowed:raise ValueError('Unsupported setting')
                    for key,value in updates.items():
                        if key=='audioOutput':
                            if value is not None and type(value) not in (int,str):raise ValueError('Invalid audio output')
                        elif type(value) is not bool:raise ValueError('Setting must be boolean: '+key)
                self.input_revision+=1
                await self.quiesce()
                if command=='reload-config':
                    if 'state' in request:self.resolver.save_state(request['state'])
                    else:self.resolver.reload()
                elif command=='settings':
                    value={**self.config,**updates};write_json(CONFIG,value);self.config=value
                elif command=='pause':self.paused=True
                elif command=='resume':self.paused=False
                elif command=='stop':self.stop.set()
                elif command=='reconnect':self.enqueue(self.epoch,'disconnected',None)
                self.input_revision+=1
                self.awaiting_neutral=bool(any(self.physical.values()) or any(self.observed.values()) or self.voice_physical_down)
                self.publish()
                return {'ok':True,'paused':self.paused,'awaitingNeutral':self.awaiting_neutral,
                        'state':self.resolver.read_state() if command=='reload-config' else None}
        return {'error':'unknown command'}

    async def quiesce(self):
        self.awaiting_neutral=bool(any(self.physical.values()) or any(self.observed.values()) or self.voice_physical_down)
        if self.session and self.transport:await self.abort_voice()
        else:await self.voice_up(drain=False)
        await self.abort_voice_finish()
        async with self.voice_release_lock:await asyncio.to_thread(self.router.release_all)
        await asyncio.to_thread(self.dispatcher.release_all)

    async def confirm_neutral(self):
        async with self.action_lock:
            for position in list(self.physical['enhanced']):
                if position!=9 or not (self.voice_active or self.voice_finish_pending()):await self.edge(position,False)
            self.physical['enhanced'].clear()
            if not self.physical['raw'] and not any(self.observed.values()):self.awaiting_neutral=False
            if self.voice_active:await self.abort_voice(drain=True)
            self.publish()

    async def input_edge(self,source,position,down,revision=None):
        if source not in self.physical or type(position) is not int or not 0<=position<13:return
        async with self.action_lock:
            if revision is not None and revision!=self.input_revision:return
            if revision is None:
                if down:self.observed[source].add(position)
                else:self.observed[source].discard(position)
            held=self.physical[source];was_down=position in held
            if down:held.add(position)
            else:held.discard(position)
            if position==9 and revision is None:self.physical_voice(down)
            if self.awaiting_neutral:
                if not any(self.physical.values()) and not any(self.observed.values()) and not self.voice_physical_down:
                    self.awaiting_neutral=False;self.publish()
                return
            if source=='raw':return
            if down and was_down:return
            binding=self.router.held.get(position) or self.resolver.resolve(position)
            if position==9 and binding.get('type')=='voice' and binding.get('action')=='remote-mic':
                if not down and self.voice_active:await self.abort_voice(drain=True)
                return
            await self.edge(position,down)

    async def edge(self, position, down):
        if down and (not self.config.get('dispatchEnabled') or self.paused or self.awaiting_neutral): return
        await asyncio.to_thread(self.router.edge,position,down)
        self.state['dispatchedEdges'] += 1

    def direction_filter_allowed(self):
        if self.state.get('phase')!='ready' or self.stop.is_set():return False
        # Preserve suppression through the final real release during reconfiguration.
        if self.awaiting_neutral:return True
        return bool(self.config.get('consumeRemoteDirections') and self.config.get('enhancedCaptureEnabled') and self.config.get('dispatchEnabled') and not self.paused)

    async def direction_edge(self, source, position, down):
        async with self.direction_lock:
            changed=self.direction_owners.feed(source,position,down)
            if down:self.direction_pending_releases.discard(position)
            if changed is True:await self.edge(position,True)
            elif changed is False:await self._release_direction_locked(position)

    async def release_direction(self, position):
        async with self.direction_lock:await self._release_direction_locked(position)

    async def _release_direction_locked(self, position):
        if any(position in held for held in self.direction_owners.sources.values()):
            self.direction_pending_releases.discard(position)
            return
        try:await self.edge(position,False)
        except Exception as error:
            self.direction_pending_releases.add(position)
            self.note('direction_release_error',position=position,message=str(error))
        else:self.direction_pending_releases.discard(position)

    async def release_enhanced_directions(self):
        async with self.direction_lock:
            for position,down in self.direction_owners.clear('enhanced'):
                await self._release_direction_locked(position)

    async def expire_direction_filter(self):
        if time.monotonic()>=self.direction_lease_until:
            await self.release_enhanced_directions()
            if self.physical['enhanced']:
                async with self.action_lock:
                    self.awaiting_neutral=True
                    for operation in (lambda:self.voice_up(drain=False),
                                      self.abort_voice_finish,
                                      lambda:asyncio.to_thread(self.router.release_all),
                                      lambda:asyncio.to_thread(self.dispatcher.release_all)):
                        try:await operation()
                        except Exception as error:self.note('lease_release_retry_needed',message=str(error))
                    # Capture waits for an actual neutral report before rearming.
                    self.physical['enhanced'].clear()
        for position in sorted(self.direction_pending_releases):await self.release_direction(position)

    async def watch_inputs(self, listener):
        from .rawinput import remote_device_count
        while not self.stop.is_set():
            if not listener.thread or not listener.thread.is_alive():
                listener.stop()
                try:
                    listener.start()
                    self.state['rawInputRestarts']=self.state.get('rawInputRestarts',0)+1
                except Exception as error:self.state['inputIssue']=str(error)
            try:count=await asyncio.to_thread(remote_device_count)
            except OSError:count=0
            capture={}
            try:
                path=DATA/'capture-status.json'
                if time.time()-path.stat().st_mtime<6:capture=json.loads(path.read_text(encoding='utf8'))
            except (OSError,ValueError):pass
            if capture.get('phase')!='ready':
                await self.release_enhanced_directions()
            await self.expire_direction_filter()
            self.publish(rawInputReady=bool(listener.thread and listener.thread.is_alive()),rawInputDeviceCount=count,
                         enhancedCaptureReady=capture.get('phase')=='ready' and capture.get('directionFilter')=='armed' and not capture.get('nativeIssue') and not capture.get('permitIssue'),capturePhase=capture.get('phase','offline'),
                         directionFilter=capture.get('directionFilter','not-loaded'),
                         captureIssue=capture.get('nativeIssue') or capture.get('permitIssue') or capture.get('relayIssue') or capture.get('calibrationIssue') or capture.get('lastError') or capture.get('issue'),
                         captureDiagnostic=capture.get('directionDiagnostic'))
            try:await asyncio.wait_for(self.stop.wait(),2)
            except TimeoutError:pass

    async def voice_down(self):
        from .audio import PcmOutput
        if self.voice_active: return
        if self.voice_finish_pending() or self.output is not None:
            raise RuntimeError('The previous voice recording is still draining or cleaning up')
        if self.voice_release_pending or 9 in self.router.held:
            raise RuntimeError('The previous remote voice action has not released yet')
        if not self.config.get('qwenAudioRouteConfirmed',False):
            raise RuntimeError('Select the virtual microphone in Qianwen and confirm its audio route before enabling remote voice')
        if not self.remote_voice_allowed():raise RuntimeError('Remote microphone requires the filtered physical voice key and its microphone binding')
        before = await asyncio.to_thread(self.qwen.read)
        if before['recording']:
            raise RuntimeError('Qianwen is already recording another session')
        if before.get('state') in (1,3):
            raise RuntimeError('Qianwen is still '+('starting' if before['state']==1 else 'processing')+' another session')
        # Opening a missing endpoint fails before asking the input method to record.
        self.output = await asyncio.to_thread(PcmOutput,self.config.get('audioOutput'))
        await asyncio.to_thread(self.output.start)
        await self.edge(9,True)
        # NativeDispatcher and runtime share the same QwenState transaction.
        # Its start() returns only after the recording is confirmed.
        self.voice_active = True
        self.publish(voiceActive=True,audioReady=True,lastError=None,voiceIssue=None)

    def voice_finish_pending(self):
        # A done future can still await its callback's endpoint ownership handoff.
        return self.voice_finishing_output is not None or any(value is not None and not value.done() for value in
                   (self.voice_finish_task,self.voice_finish_future))

    async def release_voice_binding(self,binding):
        async with self.voice_release_lock:
            try:
                # A late finalizer can only release the exact original press.
                if binding is not None and self.router.held.get(9) is binding:await self.edge(9,False)
            finally:
                self.voice_pending_binding=binding if binding is not None and self.router.held.get(9) is binding else None
                self.voice_release_pending=self.voice_pending_binding is not None or self.output is not None
                self.publish(voiceActive=self.voice_active,voiceReleasePending=self.voice_release_pending)

    async def finish_voice_output(self,output,binding,drain,future,abort):
        waiter=asyncio.create_task(abort.wait())
        try:
            budget=min(4,max(0,getattr(output,'pending_seconds',0)))+2
            done,_=await asyncio.wait((future,waiter),timeout=budget,return_when=asyncio.FIRST_COMPLETED)
            if future not in done:
                request=getattr(output,'request_abort',None)
                if request:request()
                await asyncio.wait_for(asyncio.shield(future),1.5)
            else:future.result()
        except Exception as error:
            message=str(error) or 'Audio endpoint cleanup timed out; voice remains blocked until it completes'
            self.note('audio_stop_error',message=message)
            self.publish(voiceIssue=message)
            if future.done() and getattr(output,'stream',None) is not None and self.output is None:self.output=output
        finally:
            waiter.cancel()
            try:await self.release_voice_binding(binding)
            except Exception as error:self.note('voice_release_retry_needed',message=str(error))
            if self.voice_finish_future is future:
                if future.done():self.voice_finishing_output=None
                self.publish(voiceFinishing=not future.done() or self.output is not None)

    def begin_voice_finish(self,output,binding,drain):
        loop=asyncio.get_running_loop();future=loop.create_future();abort=asyncio.Event()
        self.voice_finish_future=future;self.voice_finish_abort=abort;self.voice_finishing_output=output
        self.voice_pending_binding=binding;self.voice_release_pending=binding is not None
        def completed(error):
            if not future.done():
                if error is None:future.set_result(None)
                else:future.set_exception(error)
        def finish():
            try:output.finish(drain);error=None
            except Exception as caught:error=caught
            try:loop.call_soon_threadsafe(completed,error)
            except RuntimeError:pass
        def consume_result(result):
            error=None if result.cancelled() else result.exception()
            task=self.voice_finish_task
            if self.voice_finish_future is result and task is not None and task.done():
                # A late close failure is not endpoint reclamation. The same
                # output must remain owned and retryable before another opens.
                if getattr(output,'stream',None) is not None:
                    self.output=output
                    self.voice_release_pending=True
                    message=str(error) if error else 'Audio endpoint remains open after cleanup'
                    self.note('audio_stop_error',message=message)
                    self.publish(voiceIssue=message)
                self.voice_finishing_output=None
                self.publish(voiceFinishing=self.output is not None,voiceReleasePending=self.voice_release_pending)
        future.add_done_callback(consume_result)
        # A permanently stuck native writer must not pin asyncio's executor at exit.
        threading.Thread(target=finish,name='RC003-PCM-Finish',daemon=True).start()
        self.voice_finish_task=asyncio.create_task(self.finish_voice_output(output,binding,drain,future,abort))
        self.voice_finish_task.add_done_callback(lambda task:None if task.cancelled() else task.exception())
        self.publish(voiceActive=False,voiceFinishing=True,voiceReleasePending=binding is not None)

    async def voice_up(self,drain=True):
        # Rejecting a new hold must not cancel the preceding recording's tail.
        if self.voice_finish_pending():return
        self.voice_active=False
        binding=self.voice_pending_binding or self.router.held.get(9)
        if self.output:
            output,self.output=self.output,None
            self.begin_voice_finish(output,binding,drain)
            if not drain:
                # Fast cleanup completes inline; slow native cleanup stays isolated.
                await asyncio.wait((self.voice_finish_task,),timeout=.05)
        elif binding is not None:
            self.voice_finish_task=asyncio.create_task(self.finish_voice_binding(binding))
            self.voice_finish_task.add_done_callback(lambda task:None if task.cancelled() else task.exception())
            await asyncio.wait((self.voice_finish_task,),timeout=.05)
        else:self.publish(voiceActive=False)

    async def finish_voice_binding(self,binding):
        try:await self.release_voice_binding(binding)
        except Exception as error:self.note('voice_release_retry_needed',message=str(error))

    async def abort_voice_finish(self):
        if self.voice_finish_abort:self.voice_finish_abort.set()
        request=getattr(self.voice_finishing_output,'request_abort',None)
        if request:request()
        task=self.voice_finish_task
        if task is not None and not task.done():
            try:await asyncio.wait_for(asyncio.shield(task),1.7)
            except asyncio.TimeoutError:self.note('audio_cleanup_pending',message='Endpoint cleanup is isolated; new voice is blocked')

    async def retry_voice_release(self):
        if not self.voice_release_pending or self.voice_active or self.voice_finish_pending():return
        try:await self.voice_up(drain=False)
        except Exception as error:self.note('voice_release_retry_needed',message=str(error))

    async def retry_action_releases(self):
        for position in list(self.router.held):
            if position==9 and (self.voice_active or self.voice_finish_pending() or self.voice_release_pending):continue
            physical=any(position in held for held in self.physical.values()) or any(position in held for held in self.observed.values())
            if not physical or self.awaiting_neutral or self.paused or not self.config.get('dispatchEnabled'):
                try:await self.edge(position,False)
                except Exception as error:self.note('action_release_retry_needed',position=position,message=str(error))

    async def abort_voice(self,drain=False):
        # Retire this stream, not the negotiated BLE/HID connection. A late
        # stream-start report carries its own ID and must be closed as well.
        closing = self.session.end()
        try:await self.voice_up(drain=drain)
        except Exception as error:self.note('voice_release_retry_needed',message=str(error))
        # Keep actual radio failures visible to the connection supervisor.
        for event in closing:
            if event.kind == 'write':await self.transport.write(event.data)

    def remote_voice_allowed(self):
        try:binding=self.resolver.resolve(9)
        except (OSError,ValueError,RuntimeError,KeyError):return False
        return (binding.get('type')=='voice' and binding.get('action')=='remote-mic' and
            self.config.get('dispatchEnabled') and not self.paused and not self.awaiting_neutral and
            self.voice_physical_down and (9 in self.physical['enhanced'] or 9 in self.observed['enhanced']) and
            time.monotonic()<self.direction_lease_until)

    async def control_event(self, data):
        self.state['lastVoiceControl'] = bytes(data[:16]).hex()
        if data and data[0] in (0x04,0x08):
            # Physical/GATT ordering is asynchronous; only a genuine filtered
            # press can authorize opening the remote microphone.
            if not self.voice_physical_down or not (9 in self.physical['enhanced'] or 9 in self.observed['enhanced']):
                self.voice_physical_changed.clear()
                try:await asyncio.wait_for(self.voice_physical_changed.wait(),.12)
                except TimeoutError:pass
            if not self.remote_voice_allowed() or not self.config.get('qwenAudioRouteConfirmed',False):
                if data[0]==0x04 and len(data)>=4:
                    await self.transport.write(bytes((0x0d,data[3])) if self.session.version>=0x100 else b'\x0d')
                if self.session.held:await self.abort_voice()
                changes={'voiceActive':False}
                if self.remote_voice_allowed() and not self.config.get('qwenAudioRouteConfirmed',False):
                    changes['voiceIssue']='Select the virtual microphone in Qianwen and confirm its audio route before enabling remote voice'
                self.publish(**changes)
                return
        # Some real RC003 holds start with 04, without a preceding 08. Recover
        # only after another physical F5 make (auto-repeat is not another make).
        if data and data[0] in (0x04,0x08) and self.voice_requires_request:
            deadline = time.monotonic()+.12
            while data[0] == 0x04 and self.voice_physical_cycle <= self.voice_failed_cycle:
                self.voice_physical_changed.clear()
                remaining = deadline-time.monotonic()
                if remaining <= 0:break
                try:await asyncio.wait_for(self.voice_physical_changed.wait(),remaining)
                except TimeoutError:break
            if self.voice_physical_cycle > self.voice_failed_cycle:
                self.voice_requires_request = self.voice_reject_until_release = False
        if data:
            if data[0] == 0x08:
                if self.voice_reject_until_release:return
                self.voice_requires_request = False
            elif data[0] == 0 and (len(data) == 1 or data[1] != 0):
                # 00 00 is merely the host-close ACK, not a physical release.
                self.voice_reject_until_release = False
        self.state.update(voiceRequiresRequest=self.voice_requires_request,
                          voiceFailedCycle=self.voice_failed_cycle,
                          voicePhysicalCycle=self.voice_physical_cycle)
        await self.protocol_events(self.session.control(data))

    async def protocol_events(self, events):
        for event in events:
            if event.kind == 'write': await self.transport.write(event.data)
            elif event.kind in ('down','up'):
                if event.kind == 'down' and self.voice_requires_request:
                    await self.abort_voice()
                    continue
                attempt_cycle = self.voice_physical_cycle
                try:
                    if event.kind == 'down':
                        await self.voice_down()
                        self.voice_stream_cycle=attempt_cycle
                    else:await self.voice_up()
                except Exception as error:
                    await self.voice_failure(event.kind,error,attempt_cycle)

    async def voice_failure(self,stage,error,cycle):
        self.voice_requires_request=True
        self.voice_reject_until_release=stage in ('down','audio')
        self.voice_failed_cycle=cycle
        self.note('voice_action_error',stage=stage,message=str(error))
        self.publish(voiceIssue=str(error),voiceActive=False,voiceRequiresRequest=True,
                     voiceFailedCycle=cycle,voicePhysicalCycle=self.voice_physical_cycle)
        await self.abort_voice()

    async def consume_connection(self):
        negotiation_deadline = time.monotonic()+8
        heartbeat = time.monotonic()
        while not self.stop.is_set():
            if time.monotonic()-heartbeat >= 5:
                self.publish();heartbeat=time.monotonic()
            if not self.session.ready and time.monotonic() > negotiation_deadline:
                raise TimeoutError('ATVV capability negotiation timed out')
            # Protocol keepalive and recording deadlines must also run while
            # notifications continuously fill the queue.
            async with self.action_lock:
                await self.retry_voice_release()
                await self.retry_action_releases()
                await self.protocol_events(self.session.tick())
            await self.expire_direction_filter()
            if self.overflow: raise RuntimeError('Hardware event queue overflowed')
            try: epoch,kind,data = await asyncio.wait_for(self.queue.get(),.25)
            except asyncio.TimeoutError:
                continue
            if epoch not in (0,self.epoch): continue
            if kind in ('disconnected','input_removed'):
                raise ConnectionError('Remote disconnected; releasing this connection')
            if kind in ('transport_error','input_error'): raise RuntimeError(str(data))
            if kind == 'battery': self.apply_battery(epoch,*data)
            elif kind=='enhanced-neutral':await self.confirm_neutral()
            elif kind == 'battery_issue':
                if epoch == self.epoch and self.bound:
                    self.publish(batteryLevel=None,batterySource=None,batteryUpdatedAt=None,batteryIssue=str(data))
            elif kind == 'control':
                async with self.action_lock:await self.control_event(data)
                if self.session.ready: self.publish(phase='ready',connectionStage='connected',lastError=None)
            elif kind == 'audio':
                self.state['receivedAudioBytes'] += len(data)
                try:
                    pcm = self.session.audio(data)
                    self.state['decodedSamples'] += len(pcm)//2
                    if pcm and self.voice_active and self.output:self.output.write(pcm)
                except Exception as error:
                    await self.voice_failure('audio',error,self.voice_stream_cycle)
            elif kind in ('key','enhanced-key','enhanced-direction') and self.session.ready:
                position,down = data[:2]
                try:
                    await self.input_edge('enhanced' if kind in ('enhanced-key','enhanced-direction') else 'raw',*data)
                except Exception as error:
                    self.note('action_error',position=position,message=str(error))
                    self.publish(lastError=str(error))

    async def cleanup_connection(self):
        self.bound = False
        self.publish(batteryLevel=None,batterySource=None,batteryUpdatedAt=None,batteryIssue=None)
        if self.session and self.transport:
            for event in self.session.disconnect():
                if event.kind == 'write':
                    try: await self.transport.write(event.data)
                    except Exception: pass
        try: await self.voice_up(drain=False)
        except Exception as error: self.note('voice_release_retry_needed',message=str(error))
        await self.abort_voice_finish()
        async with self.direction_lock:
            try:
                async with self.voice_release_lock:await asyncio.to_thread(self.router.release_all)
            except Exception as error: self.note('release_retry_needed',message=str(error))
            self.direction_owners = DirectionOwners()
            self.direction_lease_until = 0
            self.direction_pending_releases.update(position for position in self.router.held if position in (1,2,3,4))
        try:await asyncio.to_thread(self.dispatcher.release_all)
        except Exception as error:self.note('release_retry_needed',message=str(error))
        self.physical={'raw':set(),'enhanced':set()}
        self.observed={'raw':set(),'enhanced':set()}
        self.input_revision+=1
        self.voice_physical_down=False
        self.awaiting_neutral=False
        self.direction_generation=secrets.randbits(31)+1
        if self.transport:
            try: await self.transport.close()
            except Exception as error: self.note('transport_close_error',message=str(error))
        self.voice_active = False
        self.voice_requires_request = False
        self.voice_reject_until_release = False
        self.voice_release_pending = self.voice_pending_binding is not None and self.router.held.get(9) is self.voice_pending_binding or self.output is not None
        self.session = self.transport = None
        self.epoch += 1
        while not self.queue.empty(): self.queue.get_nowait()
        self.overflow = False

    async def supervise(self):
        from .bluetooth import paired_devices
        from .transport_process import ProcessTransport
        profile = json.loads((ROOT/'profiles/rc003-device.json').read_text(encoding='utf8'))
        loop = asyncio.get_running_loop()
        while not self.stop.is_set():
            try:
                devices = await paired_devices(profile['identity']['bluetoothNames'])
                self.publish(pairedCount=len(devices))
                wanted = self.config.get('bluetoothDeviceId')
                candidates = [d for d in devices if not wanted or d['id'] == wanted]
                if not candidates:
                    self.publish(phase='waiting_for_pairing')
                elif len(candidates) > 1 or len(devices) > 1:
                    self.publish(phase='device_selection_required',lastError='More than one compatible remote is paired; bind one raw input identity before dispatch')
                else:
                    if not wanted:
                        self.config['bluetoothDeviceId'] = candidates[0]['id']
                        write_json(CONFIG,self.config)
                    self.epoch += 1
                    epoch = self.epoch
                    self.session = AtvvSession()
                    self.transport = ProcessTransport(lambda kind,data:loop.call_soon_threadsafe(self.enqueue,epoch,kind,data),
                                                  progress=lambda stage:self.publish(connectionStage=stage))
                    self.publish(phase='connecting',connectionStage='opening_device',lastError=None,
                                 connectionAttempt=self.state.get('connectionAttempt',0)+1)
                    info = await self.transport.connect(candidates[0]['id'])
                    self.bound = True
                    await self.transport.write(AtvvSession.GET_CAPS)
                    self.publish(phase='negotiating',connectionStage='capability_negotiation',deviceName=info['name'])
                    await self.consume_connection()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                stage = self.state.get('connectionStage')
                message = str(error) or ('Bluetooth operation timed out: '+str(stage))
                self.note('connection_error',message=message,stage=stage)
                self.publish(phase='retrying',lastError=message)
            finally:
                await self.cleanup_connection()
            try: await asyncio.wait_for(self.stop.wait(),self.config.get('retrySeconds',3))
            except asyncio.TimeoutError: pass

    async def run(self):
        from .rawinput import RawInputListener
        from .audio import select_output
        import winrt.runtime
        winrt.runtime.init_apartment(winrt.runtime.ApartmentType.MULTI_THREADED)
        DATA.mkdir(parents=True,exist_ok=True)
        self.token = secrets.token_hex(24)
        server = await asyncio.start_server(self.control_client,'127.0.0.1',0,limit=128*1024)
        port = server.sockets[0].getsockname()[1]
        write_json(CONTROL,{'pid':os.getpid(),'port':port,'token':self.token})
        loop = asyncio.get_running_loop()
        listener = RawInputListener(lambda kind,data:loop.call_soon_threadsafe(self.enqueue,0,kind,data),
                                    trace=lambda event:loop.call_soon_threadsafe(self.raw_trace,event))
        try:
            listener.start()
            self.publish(rawInputReady=True)
            try:
                audio = select_output(self.config.get('audioOutput'))
                self.publish(audioReady=True,audioOutput=audio['name'])
            except Exception as error:
                self.publish(audioReady=False,audioIssue=str(error))
            worker = asyncio.create_task(self.supervise())
            inputs = asyncio.create_task(self.watch_inputs(listener))
            stopper = asyncio.create_task(self.stop.wait())
            try:
                done, _ = await asyncio.wait((worker,stopper),return_when=asyncio.FIRST_COMPLETED)
                if worker in done: await worker
            finally:
                stopper.cancel()
                worker.cancel()
                inputs.cancel()
                try: await inputs
                except asyncio.CancelledError: pass
                try: await worker
                except asyncio.CancelledError: pass
        finally:
            try:await self.finalize_run(listener,server)
            finally:winrt.runtime.uninit_apartment()

    async def finalize_run(self,listener,server):
        errors=[]
        try:listener.stop()
        except Exception as error:errors.append('Raw Input: '+str(error))
        try:await self.cleanup_connection()
        except Exception as error:errors.append('Connection: '+str(error))
        try:await asyncio.to_thread(self.dispatcher.close)
        except Exception as error:errors.append('Input release: '+str(error))
        try:
            server.close()
            await server.wait_closed()
        except Exception as error:errors.append('Control server: '+str(error))
        finally:
            try:
                if CONTROL.exists() and json.loads(CONTROL.read_text(encoding='utf8')).get('pid')==os.getpid():CONTROL.unlink()
            except (OSError,ValueError) as error:errors.append('Control state: '+str(error))
        self.publish(phase='stopped',rawInputReady=False,cleanupPending=bool(errors or self.router.held or self.output or self.voice_finish_pending()),
                     cleanupIssue='; '.join(errors) if errors else None)
