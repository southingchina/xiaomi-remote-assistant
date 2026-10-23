"""Offline package verification; never pair, connect, inject or record."""
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import subprocess
from rc003_bridge.paths import ROOT, child_command

def run():
    modules=('PySide6.QtWebEngineWidgets','PySide6.QtWebChannel','sounddevice',
        'winrt.windows.devices.bluetooth','winrt.windows.devices.bluetooth.genericattributeprofile',
        'winrt.windows.devices.enumeration','winrt.windows.storage.streams',
        'rc003_bridge.rawinput','rc003_bridge.qwen','rc003_bridge.standalone','rc003_bridge.transport_worker',
        'enhanced_capture','capture_support')
    imported=[]
    for module in modules:importlib.import_module(module);imported.append(module)
    from rc003_bridge.__main__ import self_test
    from rc003_bridge.standalone import ProfileResolver
    result=self_test()
    with tempfile.TemporaryDirectory(prefix='rc003-package-check-') as folder:
        resolver=ProfileResolver(Path(folder)/'profiles.json')
        state=resolver.read_state();state['profiles'][0]['bindings']['6']['action']='Delete'
        resolver.save_state(state)
        assert ProfileResolver(Path(folder)/'profiles.json').resolve(6)['action']=='Delete'
    resources=['ui/index.html','ui/app.js','ui/desktop.js','ui/style.css','ui/rc003-official-front.svg',
        'profiles/rc003-device.json','focus-codex.ps1','enhanced_capture_v4.js',
        'vendor/frida/frida-gadget-17.15.3-windows-x86_64.dll.xz']
    for name in resources:
        if not (ROOT/name).is_file():raise RuntimeError('Missing package resource: '+name)
    archive=ROOT/resources[-1]
    assert hashlib.sha256(archive.read_bytes()).hexdigest()=='b566d70189b6d551ad8f4e0bea24de08a3d4c0f559bb35b2bdb67d45182240c2'
    worker=subprocess.run(child_command('rc003_bridge.transport_worker'),
        input='{"id":1,"command":"invalid-self-test"}\n{"id":2,"command":"close"}\n',
        capture_output=True,text=True,encoding='utf8',timeout=10,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=ROOT)
    messages=[json.loads(line) for line in worker.stdout.splitlines() if line.strip()]
    assert worker.returncode==0,worker.stderr
    assert any(item.get('id')==1 and 'error' in item for item in messages)
    assert any(item.get('id')==2 and 'result' in item for item in messages)
    return {**result,'version':'0.1.1-test','standalone':True,'imports':imported,'resources':resources,
            'profilesPersisted':True,'workerStdioVerified':True,'hardwareStarted':False,'microphoneOpened':False}
