"""Bounded PCM output, only to an explicitly selected virtual audio endpoint."""
import audioop
import queue
import threading
import time


def outputs():
    import sounddevice as sd
    hosts = sd.query_hostapis()
    return [{'index':i,'name':d['name'],'host':hosts[d['hostapi']]['name'],
             'channels':d['max_output_channels'],'sampleRate':int(d['default_samplerate'])}
            for i,d in enumerate(sd.query_devices()) if d['max_output_channels'] > 0]


def select_output(selected=None):
    devices = outputs()
    if selected is not None:
        matches = [d for d in devices if d['index'] == selected] if isinstance(selected,int) else [d for d in devices if d['name'] == selected]
    else:
        matches = [d for d in devices if 'CABLE INPUT' in d['name'].upper() or
                   ('(VB-AUDIO VIRTUAL CABLE)' in d['name'].upper() and '16 CH' not in d['name'].upper())]
    preferred = [d for d in matches if 'WASAPI' in d['host'].upper()]
    matches = preferred or matches
    if len(matches) != 1:
        raise RuntimeError('Choose one virtual audio output; VB-CABLE is not installed or its endpoint is ambiguous')
    return matches[0]


class PcmOutput:
    PCM_BYTES_PER_SECOND = 16000*2
    MAX_BUFFER_SECONDS = 4

    def __init__(self, selected=None):
        self.device = select_output(selected)
        self.stream = None
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self.pending_bytes = 0
        self.accepting = False
        self.abort_requested = threading.Event()
        self.thread = None
        self.running = False
        self.error = None
        self.converter = None
        self.samples = 0

    def start(self):
        import sounddevice as sd
        self.stream = sd.RawOutputStream(device=self.device['index'],samplerate=self.device['sampleRate'],
                                         channels=min(2,self.device['channels']),dtype='int16',latency='low')
        self.stream.start(); self.running = self.accepting = True
        self.thread = threading.Thread(target=self._worker,name='RC003-PCM',daemon=True); self.thread.start()

    def write(self, pcm):
        if not pcm:return
        if len(pcm)%2:raise ValueError('PCM input must contain whole samples')
        with self.lock:
            if self.error: raise RuntimeError(self.error)
            if not self.running or not self.accepting: raise RuntimeError('Audio endpoint is not running')
            if self.pending_bytes+len(pcm)>self.PCM_BYTES_PER_SECOND*self.MAX_BUFFER_SECONDS:
                raise RuntimeError('Virtual audio buffer is full (4 seconds); stopping this recording')
            self.pending_bytes+=len(pcm)
            self.queue.put_nowait(pcm)

    @property
    def pending_seconds(self):
        with self.lock:return self.pending_bytes/self.PCM_BYTES_PER_SECOND

    def request_abort(self):
        self.abort_requested.set()

    def _worker(self):
        try:
            while self.running:
                try: pcm = self.queue.get(timeout=.05)
                except queue.Empty: continue
                size=len(pcm)
                try:
                    if not self.running: continue
                    self.samples += len(pcm)//2
                    pcm,self.converter = audioop.ratecv(pcm,2,1,16000,self.device['sampleRate'],self.converter)
                    if min(2,self.device['channels']) == 2: pcm = audioop.tostereo(pcm,2,1,1)
                    self.stream.write(pcm)
                finally:
                    with self.lock:self.pending_bytes-=size
                    self.queue.task_done()
        except Exception as error:
            self.error = str(error)

    def finish(self, drain=True):
        with self.lock:
            self.accepting=False
            remaining=self.pending_bytes/self.PCM_BYTES_PER_SECOND
        deadline = time.monotonic()+remaining+.5
        while drain and self.pending_seconds and not self.error and not self.abort_requested.is_set() and time.monotonic()<deadline:
            self.abort_requested.wait(.01)
        drained = drain and not self.pending_seconds and not self.error and not self.abort_requested.is_set()
        if drain and not drained and not self.error and not self.abort_requested.is_set():
            self.error='Audio drain timed out; stopping this recording'
        self.running = False
        if self.stream:
            try:
                if drained: self.stream.stop()
                else: self.stream.abort()
            except Exception as error: self.error = self.error or str(error)
        if self.thread: self.thread.join(1)
        if self.thread and self.thread.is_alive():
            self.error=self.error or 'Audio worker did not stop; endpoint retained for cleanup'
            # Runtime runs this sole finalizer in a daemon and bounds its await.
            # Retain ownership until the native writer really releases the stream.
            self.thread.join()
        while not self.queue.empty():
            try:
                pcm=self.queue.get_nowait()
                with self.lock:self.pending_bytes-=len(pcm)
                self.queue.task_done()
            except queue.Empty: break
        if self.stream: self.stream.close()
        self.stream = None
        if self.error: raise RuntimeError(self.error)
