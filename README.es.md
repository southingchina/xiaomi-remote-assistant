# Xiaomi Remote Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md)

Usa un Xiaomi Bluetooth Voice Remote 2 Pro (RC003) en Windows para mover el puntero, hacer clic, arrastrar, desplazarte, ejecutar atajos, abrir aplicaciones y activar voz Qwen. Incluye ventana independiente, bandeja y editor visual para 13 botones, sin Ulanzi Studio. El instalador beta v0.1.1 existente es para Windows 10/11 x64 e incluye Python, Qt, WinRT y componentes de botones; el usuario final no necesita Python ni Node.js.

## Requisitos

Windows 10/11 x64; RC003; Python 3.11 + Node.js + Inno Setup (source build)

## Configuración y puntos de entrada

`profiles.json`, `%LOCALAPPDATA%/XiaomiRemoteAssistant`, `Qwen Input Method`, `VB-CABLE`, `CABLE Input`, `CABLE Output`, `TESTING.txt`, `THIRD-PARTY.txt`

[v0.1.1 · Installer / SHA256SUMS.txt](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)

## Instalación y uso

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


## Alcance y limitaciones

Descarga el instalador de la versión v0.1.1; Code ZIP contiene solo el código. Empareja por Bluetooth en Windows, inicia el control, activa los botones mejorados con autorización de administrador, pulsa brevemente la tecla física de voz para calibrar el origen y suelta todas las teclas. El inicio de sesión solo abre ventana/bandeja: inicia el control y el auxiliar en cada sesión. La beta no está firmada; compara SHA-256 con SHA256SUMS.txt. La versión original informa de 199 pruebas Python, 19 JavaScript y comprobaciones de instalación; la compatibilidad física entre equipos sigue pendiente. Esta actualización documental no crea un binario recién validado. El código usa GPL v3; THIRD-PARTY.txt conserva otras licencias y derechos de imágenes. No hay afiliación oficial con los fabricantes.

Para el micrófono del mando, instala por separado Qwen Input Method y VB-CABLE. Envía la salida del asistente a CABLE Input y selecciona CABLE Output como entrada Qwen. Mantén la tecla física de voz, habla, suéltala y espera al vaciado del audio. Esta función solo admite esa tecla física. La acción de voz Qwen genérica conserva el dispositivo actual de Qwen y no lo cambia automáticamente. Ejecuta un único núcleo de control. Atrás usa Backspace y TV usa Esc; Esc depende de la aplicación, no es una parada universal. El desplazamiento continuo se detiene a los 30 segundos. profiles.json en %LOCALAPPDATA%/XiaomiRemoteAssistant admite hasta 30 perfiles y se conserva al desinstalar. La compilación exige Python 3.11, Node.js, Inno Setup y el compilador C# de Windows indicado. smoke_installer.ps1 usa el AppId y registro de desinstalación de producción: ejecútalo solo en un usuario o equipo de pruebas sin la copia de producción instalada.

## Registro de validación

v0.1.1 · Python: 199 ✓; JavaScript: 19 ✓; cross-PC hardware testing pending

## Licencia y atribución

[GNU GPL v3](LICENSE) · [THIRD-PARTY.txt](THIRD-PARTY.txt)

Son versiones de la documentación. Las interfaces, salidas CLI y ejecutables mantienen el comportamiento de la implementación actual.

[Referencia completa en chino](README.zh-CN.md) · [Política de mantenimiento de idiomas](docs/LOCALIZATION.md)

[Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) — Comunica problemas reproducibles con datos sintéticos. Elimina credenciales e información privada de los registros.
