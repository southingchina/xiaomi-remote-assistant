"""Local desktop shell and tray. Does not depend on a browser installation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from PySide6.QtCore import QObject, Slot, QUrl, QTimer, QLockFile
from PySide6.QtGui import QAction, QDesktopServices, QCloseEvent
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,
    QLabel,QSystemTrayIcon,QMenu,QMessageBox,QFileDialog,QDialog,QDialogButtonBox,QComboBox,QCheckBox,QPlainTextEdit,QStyle)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineUrlRequestInterceptor
from PySide6.QtWebChannel import QWebChannel
from rc003_bridge.paths import ROOT,DATA,child_command
from desktop_backend import DesktopBackend


def instance_name():
    return 'XiaomiRemoteAssistant-'+hashlib.sha256(str(DATA).lower().encode()).hexdigest()[:16]

def send_existing(message):
    socket=QLocalSocket()
    socket.connectToServer(instance_name())
    if not socket.waitForConnected(250):return False
    socket.write(message.encode());socket.waitForBytesWritten(250);socket.disconnectFromServer()
    return True

class LocalOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self,info):
        url=info.requestUrl()
        if url.scheme() in ('qrc','data'):return
        if url.isLocalFile():
            try:Path(url.toLocalFile()).resolve().relative_to((ROOT/'ui').resolve());return
            except ValueError:pass
        info.block(True)

class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self,url,kind,main):
        return url.isLocalFile() and Path(url.toLocalFile()).resolve()==(ROOT/'ui/index.html').resolve()

class NativeBridge(QObject):
    def __init__(self,backend,window):
        super().__init__(window);self.backend=backend;self.window=window

    @Slot(str,str,result=str)
    def request(self,method,payload):
        try:
            if len(payload)>100000:raise ValueError('配置内容过大。')
            data=json.loads(payload)
            if method=='load':result=self.backend.load_state()
            elif method=='status':result=self.backend.status()
            elif method=='save':result=self.backend.save_state(data)
            elif method=='export':
                filename,_=QFileDialog.getSaveFileName(self.window,'导出按键方案','小米遥控配置.json','JSON (*.json)')
                if filename:
                    Path(filename).write_text(json.dumps({'format':'xiaomi-remote-assistant','version':1,'state':self.backend.load_state()},ensure_ascii=False,indent=2),encoding='utf8')
                result={'ok':bool(filename)}
            elif method=='import':
                filename,_=QFileDialog.getOpenFileName(self.window,'导入按键方案','','JSON (*.json)')
                if not filename:result={'cancelled':True}
                else:
                    source=Path(filename)
                    if source.stat().st_size>100000:raise ValueError('配置文件过大。')
                    incoming=json.loads(source.read_text(encoding='utf-8-sig'))
                    if incoming.get('format')!='xiaomi-remote-assistant' or incoming.get('version')!=1:raise ValueError('请选择本程序导出的配置文件。')
                    result=self.backend.save_state(incoming['state'])
            else:raise ValueError('不支持的操作。')
        except Exception as error:result={'error':str(error)}
        return json.dumps(result,ensure_ascii=False)

class Window(QMainWindow):
    def __init__(self,backend):
        super().__init__();self.backend=backend;self.quitting=False
        self.setWindowTitle('小米遥控助手 0.1.1 · 测试版');self.resize(1420,920);self.setMinimumSize(950,650)
        self.setWindowIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        central=QWidget();self.setCentralWidget(central);layout=QVBoxLayout(central);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        bar=QWidget();row=QHBoxLayout(bar);row.setContentsMargins(14,8,14,8)
        actions=[('启动控制',self.start_control),('暂停 / 恢复',self.pause_control),('停止控制',self.stop_control),
                 ('启用增强按键',self.enable_capture),('蓝牙配对',lambda:QDesktopServices.openUrl(QUrl('ms-settings:bluetooth'))),
                 ('语音设置',self.voice_settings),('诊断',self.diagnostics)]
        for title,fn in actions:
            button=QPushButton(title);button.clicked.connect(fn);row.addWidget(button)
        row.addStretch()
        self.startup=QCheckBox('登录启动');self.startup.setChecked(self.read_startup());self.startup.toggled.connect(self.write_startup);row.addWidget(self.startup)
        layout.addWidget(bar)
        self.notice=QLabel('首次使用：蓝牙配对 → 启动控制 → 启用增强按键 → 短按语音键校准。');self.notice.setWordWrap(True)
        self.notice.setStyleSheet('color:#bec7ce;background:#202a2b;padding:8px 18px;font-size:12px;');layout.addWidget(self.notice)
        self.view=QWebEngineView();self.profile=QWebEngineProfile(self.view);self.interceptor=LocalOnly(self.profile);self.profile.setUrlRequestInterceptor(self.interceptor)
        self.page=LocalPage(self.profile,self.view);self.view.setPage(self.page)
        self.channel=QWebChannel(self.page);self.bridge=NativeBridge(backend,self);self.channel.registerObject('bridge',self.bridge);self.page.setWebChannel(self.channel)
        self.view.load(QUrl.fromLocalFile(str(ROOT/'ui/index.html')));layout.addWidget(self.view,1)
        self.tray=QSystemTrayIcon(self.windowIcon(),self);self.tray.setToolTip('小米遥控助手')
        menu=QMenu(self)
        for title,fn in [('打开设置',self.show_window),('启动控制',self.start_control),('停止控制',self.stop_control),('退出程序',self.quit_app)]:
            action=menu.addAction(title);action.triggered.connect(fn)
        self.tray.setContextMenu(menu);self.tray.activated.connect(lambda reason:self.show_window() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None);self.tray.show()
        self.timer=QTimer(self);self.timer.timeout.connect(self.check_process);self.timer.start(2000)

    def message(self,fn):
        try:
            result=fn()
            if isinstance(result,dict) and result.get('error'):raise RuntimeError(result['error'])
            self.notice.setText(result.get('message','操作已完成。') if isinstance(result,dict) else '操作已完成。')
        except Exception as error:self.notice.setText(str(error))

    def start_control(self):self.message(self.backend.start)
    def stop_control(self):self.message(self.backend.stop)
    def enable_capture(self):self.message(self.backend.enable_capture)
    def pause_control(self):
        status=self.backend.status()
        self.message(lambda:self.backend.control('resume' if status.get('paused') or status.get('dispatchEnabled') is False else 'pause'))

    def check_process(self):
        error=self.backend.check_start_result()
        if error:self.notice.setText(error)

    def voice_settings(self):
        dialog=QDialog(self);dialog.setWindowTitle('遥控器麦克风与千问');dialog.resize(540,250);layout=QVBoxLayout(dialog)
        label=QLabel('遥控器声音输出到虚拟音频线；请在千问中把输入设备设为对应的 CABLE Output。\n电脑／耳机语音请绑定“通用千问语音”，沿用千问当前输入设备。');label.setWordWrap(True);layout.addWidget(label)
        combo=QComboBox();combo.addItem('自动选择 VB-CABLE',None)
        try:
            from rc003_bridge.audio import outputs
            for item in outputs():
                if 'CABLE' in item['name'].upper():combo.addItem(item['name']+' / '+item['host'],item['name'])
        except Exception as error:label.setText(label.text()+'\n音频设备读取失败：'+str(error))
        current=self.backend.settings();index=combo.findData(current.get('audioOutput'));combo.setCurrentIndex(max(0,index));layout.addWidget(combo)
        confirmed=QCheckBox('我已在千问中选择 CABLE Output，并已启动千问');confirmed.setChecked(bool(current.get('qwenAudioRouteConfirmed')));layout.addWidget(confirmed)
        note=QLabel('本安装包不安装千问或第三方虚拟音频驱动。未确认时，遥控器录音保持关闭。');note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.message(lambda:self.backend.settings({'audioOutput':combo.currentData(),'qwenAudioRouteConfirmed':confirmed.isChecked()}))

    def diagnostics(self):
        dialog=QDialog(self);dialog.setWindowTitle('连接诊断');dialog.resize(700,480);layout=QVBoxLayout(dialog);box=QPlainTextEdit();box.setReadOnly(True)
        status=self.backend.status();status['version']='0.1.1-test';status['dataDirectory']=str(DATA)
        try:
            capture=json.loads((DATA/'capture-status.json').read_text(encoding='utf8'))
            status['enhancedCapture']={key:value for key,value in capture.items() if key not in ('token','identity','instance','calibration')}
        except (OSError,ValueError):status['enhancedCapture']='尚未启动'
        box.setPlainText(json.dumps(status,ensure_ascii=False,indent=2));layout.addWidget(box)
        tip=QLabel('增强按键需要管理员权限；首次校准请短按语音键。若提示已有旧组件，请退出旧软件并重启电脑。');tip.setWordWrap(True);layout.addWidget(tip)
        dialog.exec()

    def read_startup(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                return bool(winreg.QueryValueEx(key,'XiaomiRemoteAssistant')[0])
        except OSError:return False

    def write_startup(self,enabled):
        import winreg
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                if enabled:
                    entry=Path(sys.executable).parent/'XiaomiRemoteAssistant.exe'
                    if not entry.exists():raise RuntimeError('请安装测试包后再启用登录启动。')
                    winreg.SetValueEx(key,'XiaomiRemoteAssistant',0,winreg.REG_SZ,subprocess.list2cmdline([str(entry),'--tray']))
                else:
                    try:winreg.DeleteValue(key,'XiaomiRemoteAssistant')
                    except FileNotFoundError:pass
        except Exception as error:self.notice.setText(str(error));self.startup.blockSignals(True);self.startup.setChecked(self.read_startup());self.startup.blockSignals(False)

    def show_window(self):self.showNormal();self.raise_();self.activateWindow()
    def closeEvent(self,event):
        if self.quitting:event.accept();return
        if QSystemTrayIcon.isSystemTrayAvailable():event.ignore();self.hide()
        else:self.quit_app();event.accept()
    def quit_app(self):
        self.quitting=True;self.timer.stop()
        try:self.backend.stop()
        except Exception:pass
        self.tray.hide();QApplication.quit()

def main(args=()):
    app=QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName('XiaomiRemoteAssistant');app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet('QWidget{background:#1b1d21;color:#dce1e5;font-family:"Microsoft YaHei UI";} QPushButton{padding:7px 10px;border:1px solid #3a4246;border-radius:5px;} QPushButton:hover{background:#2d3938;} QCheckBox{padding:4px;}')
    DATA.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(DATA/'desktop.lock'));lock.setStaleLockTime(30000)
    if not lock.tryLock(0):send_existing('show');return
    QLocalServer.removeServer(instance_name());server=QLocalServer();server.listen(instance_name())
    window=Window(DesktopBackend())
    def on_connection():
        sock=server.nextPendingConnection()
        if not sock:return
        def read():
            command=bytes(sock.readAll()).decode(errors='replace');sock.disconnectFromServer()
            if command=='quit':window.quit_app()
            else:window.show_window()
        sock.readyRead.connect(read)
        if sock.bytesAvailable():read()
    server.newConnection.connect(on_connection)
    if '--tray' not in args:window.show()
    if '--smoke-test' in args:
        output=Path(args[args.index('--smoke-test')+1]);result={'guiStarted':True,'pageLoaded':False,'hardwareStarted':False}
        def finish_ui(value):
            if isinstance(value,str):
                try:value=json.loads(value)
                except ValueError:value={}
            if isinstance(value,dict):result.update(value)
            result['uiReady']=result.get('cards')==13 and result.get('hotspots')==13 and bool(result.get('selectedName'))
            output.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8');window.quit_app()
        def loaded(ok):
            result['pageLoaded']=bool(ok)
            QTimer.singleShot(1200,lambda:window.page.runJavaScript(
                "JSON.stringify({cards:document.querySelectorAll('.key-card').length,hotspots:document.querySelectorAll('.remote-hotspot').length,selectedName:document.getElementById('selected-name')?.textContent||''})",finish_ui))
        window.view.loadFinished.connect(loaded)
        QTimer.singleShot(15000,lambda:finish_ui({'timedOut':True,'cards':0,'hotspots':0}))
    app.exec();server.close();lock.unlock()
