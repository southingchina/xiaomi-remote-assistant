# Xiaomi Remote Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md)

小米 Bluetooth Voice Remote 2 Pro（RC003）を Windows に接続し、マウス移動、クリック、ドラッグ、スクロール、ショートカット、アプリ起動、千問音声入力に使います。独立した設定画面、トレイ、13 個の物理ボタンのビジュアル設定を備え、Ulanzi Studio は不要です。既存の v0.1.1 ベータ導入パッケージは Windows 10/11 x64 向けで Python、Qt、WinRT、ボタン部品を同梱し、一般利用者が Python や Node.js を導入する必要はありません。

## 必要な環境

Windows 10/11 x64; RC003; Python 3.11 + Node.js + Inno Setup (source build)

## 設定とエントリーポイント

`profiles.json`, `%LOCALAPPDATA%/XiaomiRemoteAssistant`, `Qwen Input Method`, `VB-CABLE`, `CABLE Input`, `CABLE Output`, `TESTING.txt`, `THIRD-PARTY.txt`

[v0.1.1 · Installer / SHA256SUMS.txt](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)

## 導入と使用方法

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


## 公開範囲と制限

v0.1.1 リリースのインストーラーを使ってください。Code ZIP はソースです。Windows で Bluetooth ペアリングし、制御開始、管理者承認付き拡張ボタン有効化、物理音声キーの短押しによる発信元校正、全キーを離して準備完了を待つ順に進めます。ログイン起動は画面/トレイのみで、制御と拡張補助は毎回開始します。ベータは未署名のため SHA256SUMS.txt と照合してください。元リリースは Python 199 件と JavaScript 19 件のテストおよび導入検査を報告していますが、異なる PC の実機互換性は未完了です。今回の文書更新で新バイナリを検収したわけではありません。コードは GPL v3、第三者の許諾や画像権利は THIRD-PARTY.txt に従います。各メーカーとの公式関係はありません。

リモコンマイクには千問入力法と VB-CABLE を別途導入し、本アプリ出力を CABLE Input、千問入力を CABLE Output に設定します。物理音声キーを押して話し、離して音声の後処理を待ちます。このマイク動作は物理音声キー専用です。汎用千問音声は千問で現在選択中の入力機器を使い、自動で切り替えません。制御コアは一つだけ起動してください。戻るの既定は Backspace、TV は Esc で、Esc は全タスク共通の停止ではありません。連続スクロールは 30 秒で停止し、再押下で継続します。%LOCALAPPDATA%/XiaomiRemoteAssistant の profiles.json は最大 30 設定を保存し、アンインストール後も残ります。ソースビルドには Python 3.11、Node.js、Inno Setup と指定の Windows C# コンパイラーが必要です。smoke_installer.ps1 は正式 AppId とアンインストール登録を使うため、正式版未導入のテスト PC/ユーザーでのみ実行してください。

## 検証記録

v0.1.1 · Python: 199 ✓; JavaScript: 19 ✓; cross-PC hardware testing pending

## ライセンスと出典

[GNU GPL v3](LICENSE) · [THIRD-PARTY.txt](THIRD-PARTY.txt)

これらは文書の言語版です。アプリ画面、CLI 出力、実行ファイルは現在の実装に従います。

[中国語の詳細リファレンス](README.zh-CN.md) · [言語版の保守方針](docs/LOCALIZATION.md)

[Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) — 再現できる問題は合成データで報告し、ログの認証情報や個人情報を除いてください。
