"""Installed read-only resources and separate per-user mutable state."""
import os
import sys
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
DATA = Path(os.environ.get('RC003_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'XiaomiRemoteAssistant')))
CONFIG = DATA / 'config.json'
STATUS = DATA / 'status.json'
CONTROL = DATA / 'control.json'

def child_command(module, *args):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--module', module, *args]
    return [sys.executable, '-X', 'utf8', '-m', module, *args]
