"""Device protocol and action ownership; no Windows or audio device I/O."""
from dataclasses import dataclass
import struct
import time


@dataclass(frozen=True)
class Event:
    kind: str
    data: bytes = b''


class ImaDecoder:
    STEPS = (7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,
             60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,
             337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,
             1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,
             4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,
             13899,15289,16818,18500,20350,22385,24623,27086,29794,32767)
    INDEX = (-1,-1,-1,-1,2,4,6,8)

    def __init__(self):
        self.reset()

    def reset(self, predictor=0, index=0):
        if not -32768 <= predictor <= 32767 or not 0 <= index <= 88:
            raise ValueError('Invalid ADPCM synchronization')
        self.predictor, self.index = predictor, index

    def decode(self, frame):
        result = bytearray()
        for byte in frame:
            for nibble in (byte >> 4, byte & 15):
                step = self.STEPS[self.index]
                difference = (step >> 3)
                if nibble & 4: difference += step
                if nibble & 2: difference += step >> 1
                if nibble & 1: difference += step >> 2
                self.predictor = max(-32768, min(32767, self.predictor + (-difference if nibble & 8 else difference)))
                self.index = max(0, min(88, self.index + self.INDEX[nibble & 7]))
                result.extend(struct.pack('<h', self.predictor))
        return bytes(result)


class AtvvSession:
    GET_CAPS = bytes.fromhex('0a0100000303')

    def __init__(self):
        self.ready = self.held = self.streaming = False
        self.version = 0x100
        self.frame_size = 120
        self.session_id = self.reason = 0
        self.decoder = ImaDecoder()
        self.pending = bytearray()
        self.last_audio = self.started = self.last_extend = 0.0

    def control(self, data):
        if not data: return []
        op = data[0]
        now = time.monotonic()
        if op == 0x0b:
            if len(data) < 7: raise ValueError('Truncated ATVV capabilities')
            version = int.from_bytes(data[1:3], 'big')
            codec = data[3] if version >= 0x100 else data[4]
            if not codec and len(data) == 9: codec = data[4]
            size = int.from_bytes(data[5:7], 'big')
            if not codec & 2 or not 20 <= size <= 512:
                raise ValueError('Remote does not offer supported 16 kHz ADPCM frames')
            self.version, self.frame_size, self.ready = version, size, True
            return []
        if not self.ready: return []
        if op == 0x08:
            if self.held: return []
            self.held = True
            self.started = self.last_audio = self.last_extend = now
            payload = b'\x0c\x00' if self.version >= 0x100 else b'\x0c\x00\x02'
            return [Event('write', payload), Event('down')]
        if op == 0x04:
            if len(data) < 4 or data[2] != 2:
                raise ValueError('Invalid ATVV stream start')
            if self.streaming:
                if data[3] != self.session_id: raise ValueError('Voice session changed during hold')
                return []
            events = []
            if not self.held:
                self.held = True
                events.append(Event('down'))
            self.streaming = True
            self.reason, self.session_id = data[1], data[3]
            self.started = self.last_audio = self.last_extend = now
            self.pending.clear(); self.decoder.reset()
            return events
        if op == 0x00:
            # A delayed host-close ACK is not a release of the next physical hold.
            if len(data) > 1 and data[1] == 0 and (not self.streaming or self.reason != 0):
                return []
            return self.end()
        if op == 0x0a and self.streaming:
            if len(data) < 7: raise ValueError('Truncated ATVV audio sync')
            self.pending.clear()
            self.decoder.reset(int.from_bytes(data[4:6], 'big', signed=True), data[6])
        return []

    def audio(self, data):
        if not self.ready or not self.streaming: return b''
        if len(data) > 4096 or len(self.pending)+len(data) > 8192:
            raise ValueError('ATVV audio buffer exceeded its bound')
        self.last_audio = time.monotonic()
        self.pending.extend(data)
        result = bytearray()
        while len(self.pending) >= self.frame_size:
            result.extend(self.decoder.decode(self.pending[:self.frame_size]))
            del self.pending[:self.frame_size]
        return bytes(result)

    def end(self):
        if not self.held: return []
        self.held = self.streaming = False
        self.pending.clear()
        close = bytes((0x0d, self.session_id)) if self.version >= 0x100 else b'\x0d'
        return [Event('write', close), Event('up')]

    def tick(self):
        if not self.held: return []
        now = time.monotonic()
        if now-self.last_audio > 3 or now-self.started > 180:
            return self.end()
        if self.streaming and self.version >= 0x100 and now-self.last_extend >= 4:
            self.last_extend = now
            return [Event('write', bytes((0x0e, self.session_id)))]
        return []

    def disconnect(self):
        events = self.end()
        self.ready = False
        return events


class ActionRouter:
    def __init__(self, resolve, send):
        self.resolve, self.send = resolve, send
        self.held = {}

    def edge(self, position, down):
        if down:
            if position in self.held: return
            binding = self.resolve(position)
            self.held[position] = binding
            self.send(binding, True)
        elif position in self.held:
            self.send(self.held[position], False)
            del self.held[position]

    def release_all(self):
        errors = []
        for position in list(self.held):
            try: self.edge(position, False)
            except Exception as error: errors.append(str(error))
        if errors: raise RuntimeError('; '.join(errors))


USAGE_POSITION = {0x66:0, 0x52:1, 0x51:2, 0x50:3, 0x4f:4, 0x28:5,
                  0xf1:6, 0x4a:7, 0x65:8, 0x80:10, 0x81:11, 0x35:12}


class HidKeys:
    def __init__(self): self.held = set()

    def feed(self, report):
        if len(report) == 9 and report[:3] == b'\x01\x00\x00':
            usages = {int.from_bytes(report[i:i+2], 'little') for i in (3,5,7)}
        elif len(report) == 8:
            usages = set(report[2:8])
        else: raise ValueError('Unrecognized RC003 HID report shape')
        current = {USAGE_POSITION[u] for u in usages if u in USAGE_POSITION}
        edges = [(p, False) for p in sorted(self.held-current)] + [(p, True) for p in sorted(current-self.held)]
        self.held = current
        return edges


MOUSE_ACTIONS={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0),'leftbutton':(0,0),'rightbutton':(0,0)}

class DirectionOwners:
    """Keep raw fallback and consumed-report directions from releasing each other."""
    def __init__(self): self.sources={'raw':set(),'enhanced':set()}

    def feed(self, source, position, down):
        if source not in self.sources or position not in (1,2,3,4): raise ValueError('Invalid direction source')
        before=any(position in values for values in self.sources.values())
        if down:self.sources[source].add(position)
        else:self.sources[source].discard(position)
        after=any(position in values for values in self.sources.values())
        return after if after!=before else None

    def clear(self, source):
        result=[]
        for position in sorted(self.sources[source].copy()):
            value=self.feed(source,position,False)
            if value is not None:result.append((position,value))
        return result


class WheelState:
    def __init__(self,send,clock=time.monotonic):
        self.send,self.clock=send,clock
        self.held={};self.details={}

    def edge(self,context,action,down):
        if action not in ('wheelup','wheeldown'):raise ValueError('Unknown wheel action')
        if down:
            if context in self.held:return
            delta=120 if action=='wheelup' else -120
            self.send('wheel',delta,0)
            now=self.clock();self.held[context]=(delta,now+.30)
            self.details[context]={'started':now,'notches':1,'action':action}
        elif context in self.held:
            self.held.pop(context,None);details=self.details.pop(context)
            return {'action':details['action'],'seconds':round(self.clock()-details['started'],3),'notches':details['notches']}

    def tick(self):
        now=self.clock()
        for context,(delta,due) in list(self.held.items()):
            if now+1e-9>=due:
                self.send('wheel',delta,0)
                self.details[context]['notches']+=1
                # Never replay a burst after a stalled event loop.
                self.held[context]=(delta,now+.08)

    def release_all(self):self.held.clear();self.details.clear()


class BackspaceState:
    """One held Backspace with bounded repeat and balanced release."""
    def __init__(self,send,clock=time.monotonic,delay=.5,interval=.05):
        self.send,self.clock=send,clock
        self.delay,self.interval=delay,interval
        self.held=set();self.due=None;self.started=None

    def edge(self,context,down):
        if down:
            if context in self.held:return
            if not self.held:
                self.send('backspace-down',0,0)
                self.started=self.clock();self.due=self.started+self.delay
            self.held.add(context)
        elif context in self.held:
            if len(self.held)==1:self.send('backspace-up',0,0)
            self.held.remove(context)
            if not self.held:self.due=self.started=None

    def tick(self):
        if not self.held:return
        now=self.clock()
        if now-self.started>=30:self.release_all();return
        if now+1e-9>=self.due:
            self.send('backspace-down',0,0)
            self.due=now+self.interval

    def release_all(self):
        if self.held:self.send('backspace-up',0,0)
        self.held.clear();self.due=self.started=None


class MouseState:
    def __init__(self,send,clock=time.monotonic):
        self.send,self.clock=send,clock
        self.held={};self.last=clock();self.remainder=[0.0,0.0]

    def edge(self,context,action,down):
        if action not in MOUSE_ACTIONS:raise ValueError('Unknown mouse action')
        if down:
            if context in self.held:return
            was_button=any(a==action for a,t in self.held.values())
            self.held[context]=(action,self.clock())
            if action in ('leftbutton','rightbutton') and not was_button:self.send(('left' if action=='leftbutton' else 'right')+'-down',0,0)
        elif context in self.held:
            action,_=self.held.pop(context)
            if action in ('leftbutton','rightbutton') and not any(a==action for a,t in self.held.values()):self.send(('left' if action=='leftbutton' else 'right')+'-up',0,0)
        if not self.held:self.remainder=[0.0,0.0];self.last=self.clock()

    def tick(self):
        import math
        now=self.clock();dt=max(0,min(.05,now-self.last));self.last=now
        for context,(action,started) in list(self.held.items()):
            if now-started>=30:self.edge(context,action,False)
        moves=[(MOUSE_ACTIONS[a],t) for a,t in self.held.values() if a not in ('leftbutton','rightbutton')]
        if not moves:return
        x=sum(v[0] for v,t in moves);y=sum(v[1] for v,t in moves)
        length=math.hypot(x,y)
        if not length:self.remainder=[0.0,0.0];return
        speed=min(480,120+360*(now-min(t for v,t in moves)))
        self.remainder[0]+=x/length*speed*dt;self.remainder[1]+=y/length*speed*dt
        dx,dy=map(int,self.remainder)
        self.remainder[0]-=dx;self.remainder[1]-=dy
        if dx or dy:self.send('move',dx,dy)

    def release_all(self):
        for context,(action,_) in list(self.held.items()):self.edge(context,action,False)


def configure_mouse_page(page):
    from copy import deepcopy
    result=deepcopy(page)
    keys=next(c['Actions'] for c in result['Controllers'] if c['Type']=='Keypad')
    for slot,action,name in [('1_0','up','鼠标上移'),('2_0','down','鼠标下移'),('3_0','left','鼠标左移'),('4_0','right','鼠标右移'),('0_1','leftbutton','鼠标左键')]:
        keys[slot]={'ActionID':keys[slot]['ActionID'],'Action':'com.codex.xiaomi.buttons.mouse-'+action,
                    'Name':name,'ActionParam':{},'LinkedTitle':False,
                    'Plugin':{'Name':name,'UUID':'com.codex.xiaomi.buttons','Version':'0.2.0'},
                    'ViewParam':[{'Icon':'','Text':name}]}
    return result
