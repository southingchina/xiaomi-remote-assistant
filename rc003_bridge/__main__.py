"""Independent bridge command line and authenticated local control client."""
import argparse
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys


def report(value): print(json.dumps(value,ensure_ascii=False))


def control(command, **payload):
    from .paths import CONTROL
    try:
        info = json.loads(CONTROL.read_text(encoding='utf8'))
        with socket.create_connection(('127.0.0.1',info['port']),timeout=1 if command=='status' else 12) as connection:
            connection.sendall(json.dumps({**payload,'token':info['token'],'command':command}).encode()+b'\n')
            return json.loads(connection.makefile('rb').readline(1024*1024))
    except (OSError,ValueError): return {'running':False}


def self_test():
    from .core import AtvvSession, ActionRouter, HidKeys
    session = AtvvSession(); edges = []; writes = []
    session.control(bytes.fromhex('0b0100020300780000'))
    packets = [b'\x08',b'\x08',bytes.fromhex('04030207'),bytes.fromhex('04030207')]
    for packet in packets:
        for event in session.control(packet):
            if event.kind == 'write': writes.append(event.data.hex())
            else: edges.append(event.kind)
    pcm = session.audio(bytes.fromhex('12345678')*30)
    for event in session.control(b'\x00\x02'):
        if event.kind == 'write': writes.append(event.data.hex())
        else: edges.append(event.kind)
    assert edges == ['down','up'] and len(pcm)//2 == 240 and not session.held
    sent = []
    router = ActionRouter(lambda p:{'actionId':str(p),'action':'audit'},lambda b,d:sent.append((b['actionId'],d)))
    for p in range(13): router.edge(p,True)
    router.release_all()
    assert len(sent) == 26 and not router.held
    return {'passed':True,'scope':'software protocol and dispatch replay only','voiceEdges':edges,
            'decodedSamples':len(pcm)//2,'logicalKeyEdges':len(sent),'remainingHeld':len(router.held),
            'commands':writes,'hardwareVerified':False,'microphoneOpened':False}


async def diagnose():
    from .bluetooth import paired_devices
    from .audio import outputs
    from .rawinput import RawInputListener
    from .runtime import ROOT
    profile = json.loads((ROOT/'profiles/rc003-device.json').read_text(encoding='utf8'))
    listener = RawInputListener(lambda kind,data:None)
    listener.start(); listener.stop()
    devices = await paired_devices(profile['identity']['bluetoothNames'])
    audio = outputs()
    return {'rawInputInitialized':True,'pairedDevices':[{'name':d['name']} for d in devices],
            'pairedCount':len(devices),'virtualAudioOutputs':[d for d in audio if 'CABLE' in d['name'].upper()],
            'microphoneOpened':False,'hardwareVerified':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['self-test','diagnose','start','ensure','status','stop','reconnect','run','audio-devices','pause','resume','reload-config','settings'])
    parser.add_argument('--json',default='{}',help='JSON payload for settings or reload-config')
    args = parser.parse_args()
    if args.command == 'self-test': report(self_test()); return
    if args.command == 'diagnose': report(asyncio.run(diagnose())); return
    if args.command == 'audio-devices':
        from .audio import outputs
        report(outputs()); return
    from .runtime import BridgeRuntime, DATA, ROOT
    from .paths import child_command
    paused=DATA/'bridge-paused.json'
    if args.command in ('status','stop','reconnect','pause','resume','reload-config','settings'):
        if args.command=='stop':
            from .runtime import write_json
            write_json(paused,{'paused':True})
        payload=json.loads(args.json)
        if not isinstance(payload,dict):raise ValueError('Command payload must be an object')
        report(control(args.command,**payload)); return
    if args.command=='ensure' and paused.exists():report({'paused':True});return
    if args.command=='start':paused.unlink(missing_ok=True)
    if control('status').get('pid'):
        report({'alreadyRunning':True,**control('status')}); return
    if args.command in ('start','ensure'):
        DATA.mkdir(parents=True,exist_ok=True)
        with (DATA/'process.log').open('ab') as log:
            process = subprocess.Popen(child_command('rc003_bridge','run'),
                                       cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
        import time
        for _ in range(40):
            time.sleep(.1)
            status = control('status')
            # Windows venv python.exe redirects to a child interpreter: its
            # Popen PID is not necessarily the authenticated daemon PID.
            if status.get('pid') and status.get('rawInputReady'):
                report(status); return
            if process.poll() is not None: break
        from .paths import STATUS
        try:last=json.loads(STATUS.read_text(encoding='utf8'))
        except (OSError,ValueError):last={}
        report({'started':False,'error':last.get('lastError','Bridge did not start; inspect '+str(DATA/'process.log')),'phase':last.get('phase','start_failed')});return
    # All old/new hardware bridges intentionally share this OS mutex.
    import ctypes
    from ctypes import wintypes as W
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,W.BOOL,W.LPCWSTR]; kernel.CreateMutexW.restype = W.HANDLE
    handle = kernel.CreateMutexW(None,False,'Local\\CodexRc003HardwareBridge')
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        from .runtime import write_json
        from .paths import STATUS
        result={'alreadyRunning':True,'phase':'hardware_conflict','lastError':'Another RC003 hardware bridge is running. Stop its owner before starting this program.'}
        write_json(STATUS,result)
        kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle(handle)
        report(result); return
    try: asyncio.run(BridgeRuntime().run())
    finally:
        kernel.CloseHandle.argtypes = [W.HANDLE]; kernel.CloseHandle(handle)


if __name__ == '__main__': main()
