# Xiaomi Remote Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md)

Use um Xiaomi Bluetooth Voice Remote 2 Pro (RC003) no Windows para mover o ponteiro, clicar, arrastar, rolar, executar atalhos, abrir aplicativos e ativar voz Qwen. Janela independente, bandeja e editor visual dos 13 botões funcionam sem Ulanzi Studio. O instalador beta v0.1.1 existente é para Windows 10/11 x64 e inclui Python, Qt, WinRT e componentes dos botões; usuários finais não precisam de Python ou Node.js.

## Requisitos

Windows 10/11 x64; RC003; Python 3.11 + Node.js + Inno Setup (source build)

## Configuração e pontos de entrada

`profiles.json`, `%LOCALAPPDATA%/XiaomiRemoteAssistant`, `Qwen Input Method`, `VB-CABLE`, `CABLE Input`, `CABLE Output`, `TESTING.txt`, `THIRD-PARTY.txt`

[v0.1.1 · Installer / SHA256SUMS.txt](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)

## Instalação e uso

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


## Escopo e limitações

Baixe o instalador da versão v0.1.1; Code ZIP é apenas código-fonte. Faça o pareamento Bluetooth no Windows, inicie o controle, ative os botões aprimorados com autorização de administrador, pressione brevemente a tecla física de voz para calibrar a origem e solte todas as teclas. A inicialização no login abre somente janela/bandeja: inicie controle e auxiliar a cada sessão. A beta não é assinada; compare o SHA-256 com SHA256SUMS.txt. A versão original informa 199 testes Python, 19 JavaScript e verificações de instalação; a compatibilidade física entre PCs ainda precisa ser testada. Esta atualização documental não valida um novo binário. O código usa GPL v3; THIRD-PARTY.txt preserva licenças e direitos de imagens. Não há vínculo oficial com os fabricantes.

Para o microfone do controle, instale Qwen Input Method e VB-CABLE separadamente. Defina a saída do assistente como CABLE Input e a entrada Qwen como CABLE Output. Segure a tecla física de voz, fale, solte e aguarde o fim do áudio. Essa função é limitada à tecla física de voz. A voz Qwen genérica usa o dispositivo atual do Qwen sem trocá-lo automaticamente. Execute apenas um núcleo de controle. Voltar usa Backspace e TV usa Esc; Esc depende do aplicativo, não é parada universal. A rolagem contínua para após 30 segundos. profiles.json em %LOCALAPPDATA%/XiaomiRemoteAssistant guarda até 30 perfis e é preservado na desinstalação. A compilação exige Python 3.11, Node.js, Inno Setup e o compilador C# indicado. smoke_installer.ps1 usa o AppId e registro de desinstalação de produção: execute somente em usuário ou PC de testes sem a cópia de produção instalada.

## Registro de validação

v0.1.1 · Python: 199 ✓; JavaScript: 19 ✓; cross-PC hardware testing pending

## Licença e créditos

[GNU GPL v3](LICENSE) · [THIRD-PARTY.txt](THIRD-PARTY.txt)

São versões da documentação. Interfaces, saídas CLI e executáveis mantêm o comportamento da implementação atual.

[Referência completa em chinês](README.zh-CN.md) · [Política de manutenção dos idiomas](docs/LOCALIZATION.md)

[Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) — Relate problemas reproduzíveis com dados sintéticos. Remova credenciais e informações privadas dos logs.
