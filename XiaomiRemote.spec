from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path

root=Path(SPECPATH)
win_data,win_bins,win_hidden=collect_all('winrt')
datas=[(str(root/'ui'),'ui'),(str(root/'profiles'),'profiles'),(str(root/'vendor'),'vendor'),
       (str(root/'focus-codex.ps1'),'.'),(str(root/'enhanced_capture_v4.js'),'.')]+win_data
hidden=win_hidden+['rc003_bridge.__main__','rc003_bridge.transport_worker','rc003_bridge.rawinput',
    'rc003_bridge.qwen','rc003_bridge.standalone','enhanced_capture','capture_support','self_check']
a=Analysis(['launcher.py'],pathex=[str(root)],binaries=win_bins,datas=datas,hiddenimports=hidden,
    hookspath=[],runtime_hooks=[],excludes=['PyQt5','tkinter','rc003_bridge.ulanzi'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='XiaomiRemoteCore',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=True,disable_windowed_traceback=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='XiaomiRemoteAssistant')
