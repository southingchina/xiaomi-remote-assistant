"""Desktop operations. Importing this module never connects to a device."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from rc003_bridge.paths import DATA, ROOT, child_command


class DesktopBackend:
    def __init__(self, data=DATA, control=None):
        from rc003_bridge.standalone import ProfileResolver
        self.data=Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.store=ProfileResolver(self.data/'profiles.json')
        if control is None:
            from rc003_bridge.__main__ import control
        self.control=control
        self.process=None

    def load_state(self):
        self.store.reload()
        return self.store.read_state()

    def save_state(self,state):
        try:
            if self.control('status').get('pid'):
                result=self.control('reload-config',state=state)
                if result.get('error'):raise RuntimeError(result['error'])
                if not result.get('saved',result.get('ok',False)):
                    raise RuntimeError('控制服务未确认保存，原配置保留。')
                self.store.reload()
            else:self.store.save_state(state)
            return {'ok':True,'state':self.load_state()}
        except Exception as error:return {'ok':False,'error':str(error)}

    def status(self):
        try:value=self.control('status')
        except Exception as error:return {**self.stopped_status(),'lastError':str(error)}
        if not value.get('pid'):
            return self.stopped_status()
        keys=('pid','phase','pairedCount','deviceName','batteryLevel','batteryUpdatedAt','rawInputReady',
              'enhancedCaptureReady','capturePhase','directionFilter','voiceActive','audioReady',
              'lastError','voiceIssue','audioIssue','captureIssue','dispatchedEdges','receivedAudioBytes',
              'lastKeyPosition','lastKeyDown','lastKeyAt','dispatchEnabled','configurationPending','captureRequired',
              'paused','actionService','awaitingNeutral','nativeError','cleanupPending','cleanupIssue',
              'voiceFinishing','voiceReleasePending','audioPendingSeconds')
        return {key:value[key] for key in keys if key in value}

    def stopped_status(self):
        value={'phase':'stopped','batteryLevel':None,'running':False}
        try:
            saved=json.loads((self.data/'status.json').read_text(encoding='utf8'))
            if saved.get('phase')=='stopped' and saved.get('cleanupPending'):
                value.update(cleanupPending=True,cleanupIssue=str(saved.get('cleanupIssue') or '退出时未能完成输入释放。'))
        except (OSError,ValueError,AttributeError):pass
        return value

    def start(self):
        if self.control('status').get('pid'):return {'ok':True,'message':'服务已经启动。'}
        config=self.data/'config.json'
        defaults={'schemaVersion':1,'dispatchEnabled':True,'bluetoothDeviceId':None,
                'audioOutput':None,'retrySeconds':3,'qwenAudioRouteConfirmed':False,
                'inputMode':'filtered-remote','enhancedCaptureEnabled':True,'consumeRemoteDirections':True}
        if config.exists():defaults.update(json.loads(config.read_text(encoding='utf8')))
        from rc003_bridge.runtime import write_json
        write_json(config,defaults)
        (self.data/'capture-stop.json').unlink(missing_ok=True)
        with (self.data/'process.log').open('ab') as log:
            self.process=subprocess.Popen(child_command('rc003_bridge','run'),cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return {'ok':True,'message':'正在启动。配对后唤醒遥控器，再启用增强按键。'}

    def stop(self):
        (self.data/'capture-stop.json').write_text('{"stop":true}',encoding='utf8')
        return self.control('stop')

    def settings(self,changes=None):
        path=self.data/'config.json'
        value=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
        if changes is None:
            return {key:value.get(key) for key in ('audioOutput','qwenAudioRouteConfirmed','dispatchEnabled')}
        allowed={'audioOutput','qwenAudioRouteConfirmed','dispatchEnabled'}
        if set(changes)-allowed:raise ValueError('Unsupported setting')
        if self.control('status').get('pid'):
            result=self.control('settings',**changes)
            if result.get('error'):raise RuntimeError(result['error'])
        else:
            value.update(changes)
            from rc003_bridge.runtime import write_json
            write_json(path,value)
        return {'ok':True}

    def enable_capture(self):
        current=self.control('status')
        if not current.get('pid'):
            raise RuntimeError('请先启动控制服务。')
        if current.get('phase')!='ready':
            raise RuntimeError('请先配对并唤醒遥控器，等待蓝牙连接成功后再启用增强按键。')
        capture=self.data/'capture-status.json'
        try:
            value=json.loads(capture.read_text(encoding='utf8'))
            if time.time()-capture.stat().st_mtime<8 and value.get('phase') in ('ready','connecting','observing','waiting-neutral'):
                return {'ok':True,'message':'增强按键助手已运行。若尚未校准，请短按一次语音键。'}
        except (OSError,ValueError):pass
        import ctypes
        command=child_command('enhanced_capture')
        # Forward only this app's data directory, never a script from user input.
        if getattr(sys,'frozen',False):
            command=[sys.executable,'--data-dir',str(self.data),*command[1:]]
        args=subprocess.list2cmdline(command[1:])
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int]
        shell.ShellExecuteW.restype=ctypes.c_void_p
        result=shell.ShellExecuteW(None,'runas',command[0],args,str(ROOT),0)
        if not result or result<=32:raise RuntimeError('增强按键需要管理员权限，授权未完成。')
        return {'ok':True,'message':'已请求增强按键。首次请短按一次语音键进行设备校准。'}

    def check_start_result(self):
        if self.process and self.process.poll() is not None and not self.control('status').get('pid'):
            return '控制服务未启动：可能已有另一个遥控器程序占用。请先退出旧控制程序，再重试。'
        return None
