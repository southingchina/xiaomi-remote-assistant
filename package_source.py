"""Allowlisted corresponding source: excludes credentials and machine state."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import shutil

ROOT=Path(__file__).resolve().parent
out=ROOT/'release';out.mkdir(exist_ok=True)
files=['launcher.py','launcher.cs','desktop.py','desktop_backend.py','self_check.py','enhanced_capture.py',
       'enhanced_capture_v4.js','capture_support.py','focus-codex.ps1','XiaomiRemote.spec','installer.iss',
       'build.ps1','smoke_installer.ps1','package_source.py','requirements-build.txt','TESTING.txt','README.md','CHANGELOG.md','LICENSE','THIRD-PARTY.txt']
files += [str(path.relative_to(ROOT)) for path in (ROOT/'docs').glob('audit-sync-*.md')]
folders=['rc003_bridge','ui','profiles','tests','vendor']
with ZipFile(out/'XiaomiRemoteAssistant-0.1.1-source.zip','w',ZIP_DEFLATED) as archive:
    for name in files:
        path=ROOT/name
        if path.is_file():archive.write(path,name)
    for name in folders:
        for path in (ROOT/name).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
            archive.write(path,path.relative_to(ROOT))
destination=ROOT/'dist/XiaomiRemoteAssistant'
for name in ('LICENSE','THIRD-PARTY.txt','TESTING.txt'):
    if (ROOT/name).exists():shutil.copy2(ROOT/name,destination/name)
