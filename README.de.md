# Xiaomi Remote Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md)

Verwendet eine Xiaomi Bluetooth Voice Remote 2 Pro (RC003) unter Windows für Mausbewegung, Klicks, Ziehen, Scrollen, Tastenkürzel, Programmstarts und Qwen-Spracheingabe. Eigenes Fenster, Infobereich und visueller Editor für 13 Tasten benötigen kein Ulanzi Studio. Der vorhandene Beta-Installer v0.1.1 ist für Windows 10/11 x64 und enthält Python, Qt, WinRT und Tastenkomponenten; Endnutzer brauchen weder Python noch Node.js.

## Voraussetzungen

Windows 10/11 x64; RC003; Python 3.11 + Node.js + Inno Setup (source build)

## Konfiguration und Einstiegspunkte

`profiles.json`, `%LOCALAPPDATA%/XiaomiRemoteAssistant`, `Qwen Input Method`, `VB-CABLE`, `CABLE Input`, `CABLE Output`, `TESTING.txt`, `THIRD-PARTY.txt`

[v0.1.1 · Installer / SHA256SUMS.txt](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)

## Installation und Verwendung

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


## Umfang und Einschränkungen

Den Installer aus Release v0.1.1 herunterladen; Code ZIP enthält nur Quellcode. In Windows per Bluetooth koppeln, Steuerung starten, erweiterte Tasten mit Administratorfreigabe aktivieren, die physische Sprachtaste zur Quellenkalibrierung kurz drücken und alle Tasten loslassen. Der Login-Start öffnet nur Fenster/Infobereich; Steuerung und Helfer müssen je Anmeldung gestartet werden. Die Beta ist unsigniert; SHA-256 mit SHA256SUMS.txt vergleichen. Der ursprüngliche Release nennt 199 Python- und 19 JavaScript-Tests sowie Installationsprüfungen; geräteübergreifende Hardwarekompatibilität bleibt offen. Dieses Dokumentationsupdate validiert kein neues Binärpaket. Projektcode ist GPL v3; Drittanbieter- und Bildrechte stehen in THIRD-PARTY.txt. Keine offizielle Herstellerzugehörigkeit.

Für das Fernbedienungsmikrofon Qwen Input Method und VB-CABLE separat installieren. Die Assistentenausgabe auf CABLE Input und den Qwen-Eingang auf CABLE Output stellen. Physische Sprachtaste halten, sprechen, loslassen und Audioabschluss abwarten. Diese Mikrofonaktion ist auf diese Taste begrenzt. Die allgemeine Qwen-Sprachaktion verwendet das aktuell in Qwen gewählte Gerät unverändert. Nur einen Steuerungskern betreiben. Zurück ist standardmäßig Backspace, TV ist Esc; Esc ist anwendungsabhängig, kein universeller Stopp. Dauerscrollen endet nach 30 Sekunden. profiles.json unter %LOCALAPPDATA%/XiaomiRemoteAssistant speichert bis zu 30 Profile und bleibt bei Deinstallation erhalten. Der Quellbuild benötigt Python 3.11, Node.js, Inno Setup und den angegebenen Windows-C#-Compiler. smoke_installer.ps1 verwendet Produktions-AppId und Deinstallationsregistrierung: nur auf separatem Test-PC/-Benutzer ohne installierte Produktionskopie ausführen.

## Prüfstand

v0.1.1 · Python: 199 ✓; JavaScript: 19 ✓; cross-PC hardware testing pending

## Lizenz und Herkunft

[GNU GPL v3](LICENSE) · [THIRD-PARTY.txt](THIRD-PARTY.txt)

Dies sind Sprachfassungen der Dokumentation. Oberflächen, CLI-Ausgaben und ausführbare Pakete folgen weiterhin der aktuellen Implementierung.

[Vollständige chinesische Referenz](README.zh-CN.md) · [Pflege der Sprachfassungen](docs/LOCALIZATION.md)

[Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) — Reproduzierbare Probleme mit synthetischen Daten melden. Zugangsdaten und private Informationen aus Protokollen entfernen.
