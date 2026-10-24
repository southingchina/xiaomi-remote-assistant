# Xiaomi Remote Assistant

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md)

Utilisez une télécommande Xiaomi Bluetooth Voice Remote 2 Pro (RC003) sous Windows pour déplacer le pointeur, cliquer, glisser, faire défiler, lancer des raccourcis, des applications et la saisie vocale Qwen. Fenêtre autonome, zone de notification et éditeur visuel des 13 boutons fonctionnent sans Ulanzi Studio. L'installateur bêta v0.1.1 existant cible Windows 10/11 x64 et embarque Python, Qt, WinRT et les composants de boutons ; l'utilisateur final n'a besoin ni de Python ni de Node.js.

## Prérequis

Windows 10/11 x64; RC003; Python 3.11 + Node.js + Inno Setup (source build)

## Configuration et points d’entrée

`profiles.json`, `%LOCALAPPDATA%/XiaomiRemoteAssistant`, `Qwen Input Method`, `VB-CABLE`, `CABLE Input`, `CABLE Output`, `TESTING.txt`, `THIRD-PARTY.txt`

[v0.1.1 · Installer / SHA256SUMS.txt](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)

## Installation et utilisation

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


## Périmètre et limites

Téléchargez l'installateur de la version v0.1.1 ; Code ZIP ne contient que les sources. Appairez sous Windows, démarrez le contrôle, activez les boutons améliorés avec autorisation administrateur, appuyez brièvement sur la touche vocale physique pour calibrer la source puis relâchez toutes les touches. Le lancement à l'ouverture de session ouvre seulement fenêtre/zone de notification : démarrez contrôle et auxiliaire à chaque connexion. La bêta n'est pas signée ; comparez son SHA-256 à SHA256SUMS.txt. La version originale indique 199 tests Python, 19 JavaScript et des vérifications d'installation ; la compatibilité matérielle entre PC reste à tester. Cette mise à jour documentaire ne valide pas de nouveau binaire. Le code est sous GPL v3 ; THIRD-PARTY.txt conserve les licences et droits d'images tiers. Aucune affiliation officielle aux fabricants.

Pour le microphone de la télécommande, installez séparément Qwen Input Method et VB-CABLE. Sélectionnez CABLE Input comme sortie de l'assistant et CABLE Output comme entrée Qwen. Maintenez la touche vocale physique, parlez, relâchez et attendez la fin du traitement audio. Cette action est limitée à cette touche. La voix Qwen générique conserve le périphérique actuellement choisi dans Qwen. N'exécutez qu'un noyau de contrôle. Retour utilise Backspace et TV utilise Esc ; Esc dépend de l'application, ce n'est pas un arrêt universel. Le défilement continu s'arrête après 30 secondes. profiles.json sous %LOCALAPPDATA%/XiaomiRemoteAssistant contient jusqu'à 30 profils et survit à la désinstallation. La compilation exige Python 3.11, Node.js, Inno Setup et le compilateur C# Windows indiqué. smoke_installer.ps1 utilise l'AppId et la clé de désinstallation de production : réservez-le à un PC/utilisateur de test sans copie de production installée.

## Historique de validation

v0.1.1 · Python: 199 ✓; JavaScript: 19 ✓; cross-PC hardware testing pending

## Licence et attribution

[GNU GPL v3](LICENSE) · [THIRD-PARTY.txt](THIRD-PARTY.txt)

Il s’agit de versions de la documentation. Interfaces, sorties CLI et exécutables conservent le comportement de l’implémentation actuelle.

[Référence complète en chinois](README.zh-CN.md) · [Politique de maintenance des langues](docs/LOCALIZATION.md)

[Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) — Signalez les problèmes reproductibles avec des données synthétiques. Retirez identifiants secrets et informations privées des journaux.
