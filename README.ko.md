# Xiaomi Remote Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md)

Xiaomi Bluetooth Voice Remote 2 Pro(RC003)를 Windows에 연결해 마우스 이동, 클릭, 드래그, 스크롤, 단축키, 앱 실행 및 Qwen 음성 입력에 사용합니다. 독립 설정 창, 트레이 및 13개 물리 버튼의 시각적 편집기를 제공하며 Ulanzi Studio가 필요 없습니다. 기존 v0.1.1 베타 설치 프로그램은 Windows 10/11 x64용이며 Python, Qt, WinRT 및 버튼 구성 요소를 포함합니다. 일반 사용자는 Python이나 Node.js를 설치할 필요가 없습니다.

## 필요 환경

Windows 10/11 x64; RC003; Python 3.11 + Node.js + Inno Setup (source build)

## 설정 및 진입점

`profiles.json`, `%LOCALAPPDATA%/XiaomiRemoteAssistant`, `Qwen Input Method`, `VB-CABLE`, `CABLE Input`, `CABLE Output`, `TESTING.txt`, `THIRD-PARTY.txt`

[v0.1.1 · Installer / SHA256SUMS.txt](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)

## 설치 및 사용

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


## 공개 범위와 제한

v0.1.1 릴리스의 설치 프로그램을 다운로드하세요. Code ZIP은 소스입니다. Windows Bluetooth에서 페어링한 뒤 제어 시작, 관리자 승인으로 향상된 버튼 활성화, 물리 음성 키 짧게 눌러 출처 보정, 모든 키를 놓고 준비 완료 대기 순으로 진행합니다. 로그인 시작은 창/트레이만 열며 제어와 보조 도구는 매번 시작해야 합니다. 베타는 서명되지 않았으므로 SHA256SUMS.txt를 확인하세요. 원래 릴리스는 Python 199개와 JavaScript 19개 테스트 및 설치 검사를 보고하지만 다른 PC의 실물 호환성 검증은 남아 있습니다. 이번 문서 업데이트는 새 바이너리 검수가 아닙니다. 코드는 GPL v3이며 타사 라이선스와 이미지 권리는 THIRD-PARTY.txt를 따릅니다. 제조사와 공식 제휴 관계가 없습니다.

리모컨 마이크에는 Qwen 입력기와 VB-CABLE을 별도로 설치하세요. 앱 출력은 CABLE Input, Qwen 입력은 CABLE Output으로 설정합니다. 물리 음성 키를 누르고 말한 뒤 놓고 오디오 처리가 끝나기를 기다립니다. 이 마이크 기능은 물리 음성 키 전용입니다. 범용 Qwen 음성 기능은 Qwen에서 현재 선택한 입력 장치를 사용하며 자동 변경하지 않습니다. 제어 코어는 하나만 실행하세요. 뒤로 키 기본값은 Backspace, TV는 Esc이며 Esc는 모든 작업을 멈추는 공통 버튼이 아닙니다. 연속 스크롤은 30초 후 중단되며 다시 누르면 이어집니다. %LOCALAPPDATA%/XiaomiRemoteAssistant의 profiles.json은 최대 30개 프로필을 저장하며 제거 후에도 설정은 남습니다. 소스 빌드는 Python 3.11, Node.js, Inno Setup과 지정 Windows C# 컴파일러가 필요합니다. smoke_installer.ps1은 실제 AppId와 제거 레지스트리를 사용하므로 정식 사본이 없는 별도 테스트 PC/사용자에서만 실행하세요.

## 검증 기록

v0.1.1 · Python: 199 ✓; JavaScript: 19 ✓; cross-PC hardware testing pending

## 라이선스 및 출처

[GNU GPL v3](LICENSE) · [THIRD-PARTY.txt](THIRD-PARTY.txt)

프로젝트 문서의 언어별 버전입니다. 앱 화면, CLI 출력과 실행 파일은 현재 구현을 따릅니다.

[중국어 상세 참고 문서](README.zh-CN.md) · [언어 문서 유지 관리 정책](docs/LOCALIZATION.md)

[Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) — 재현 가능한 문제는 합성 데이터로 보고하고 로그의 자격 증명과 개인 정보를 제거하세요.
