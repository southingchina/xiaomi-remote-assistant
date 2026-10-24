# Xiaomi Remote Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md)

Use a Xiaomi Bluetooth Voice Remote 2 Pro (RC003) on Windows for pointer movement, clicking, dragging, scrolling, shortcuts, application launches and Qwen voice input. A standalone desktop window, tray and visual editor configure 13 physical buttons without Ulanzi Studio. The existing v0.1.1 beta installer targets Windows 10/11 x64 and bundles its Python, Qt, WinRT and button components; end users do not need Python or Node.js.

## Requirements

Windows 10/11 x64; RC003; Python 3.11 + Node.js + Inno Setup (source build)

## Configuration and entry points

`profiles.json`, `%LOCALAPPDATA%/XiaomiRemoteAssistant`, `Qwen Input Method`, `VB-CABLE`, `CABLE Input`, `CABLE Output`, `TESTING.txt`, `THIRD-PARTY.txt`

[v0.1.1 · Installer / SHA256SUMS.txt](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)

## Installation and usage

```powershell
Get-FileHash .\XiaomiRemoteAssistant-0.1.1-test-win-x64-Setup.exe -Algorithm SHA256
```


```text
遥控器麦克风 → 蓝牙 → 小米遥控助手 → CABLE Input
                                            ↓ VB-CABLE
                                    CABLE Output → 千问输入法
```


```powershell
git clone https://github.com/southingchina/xiaomi-remote-assistant.git
cd xiaomi-remote-assistant
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt

# 打开桌面窗口；首次不会自动接管遥控器
.\.venv\Scripts\python.exe launcher.py
```


```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
node --test tests/test_capture_v4.mjs tests/test_ui_save.mjs
.\.venv\Scripts\python.exe launcher.py --self-test result.json
.\.venv\Scripts\python.exe launcher.py --smoke-test gui-result.json
```


```powershell
.\build.ps1
```


## Scope and limitations

Download the installer from the v0.1.1 release; the Code ZIP is source only. Pair in Windows Bluetooth settings, start control, enable enhanced buttons with administrator authorization, briefly press the physical voice key for source calibration, release all keys and wait for readiness. Login startup opens the window/tray only: start control and the enhanced helper after each login. This beta is unsigned; compare the installer SHA-256 with SHA256SUMS.txt. The original release reports 199 Python and 19 JavaScript tests plus installation checks, but cross-computer Bluetooth, keys and microphone compatibility still needs testing. This documentation update does not create a new tested binary. GPL v3 applies to project code; THIRD-PARTY.txt preserves other licenses and image rights. There is no official affiliation with Xiaomi, Ulanzi, Qwen or OpenAI.

For the remote microphone, install Qwen Input Method and VB-CABLE separately. Route the assistant's output to CABLE Input and Qwen's input to CABLE Output. Hold the physical voice key to speak, release it to finish, and wait for audio to drain. This remote-microphone action is limited to that physical key. The generic Qwen voice action uses Qwen's currently selected device and does not switch it automatically. Keep only one remote-control core running. Back defaults to Backspace, TV to Esc; Esc is application-dependent, not a universal stop button. Held scrolling stops after 30 seconds and resumes with a new press. profiles.json under %LOCALAPPDATA%/XiaomiRemoteAssistant keeps up to 30 profiles; uninstall preserves settings. Source builds require Python 3.11, Node.js, Inno Setup and the documented Windows C# compiler. smoke_installer.ps1 uses the production AppId/uninstall registry entry: run it only on a separate test user or test PC without the installed production copy.

## Validation record

v0.1.1 · Python: 199 ✓; JavaScript: 19 ✓; cross-PC hardware testing pending

## License and attribution

[GNU GPL v3](LICENSE) · [THIRD-PARTY.txt](THIRD-PARTY.txt)

These are documentation editions. Application interfaces, CLI output and executable releases retain the behavior of the current implementation.

[Complete Chinese reference](README.zh-CN.md) · [Language maintenance policy](docs/LOCALIZATION.md)

[Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) — Report a reproducible issue with synthetic data. Remove credentials and private information from logs.
