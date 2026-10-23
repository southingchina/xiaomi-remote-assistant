# 小米遥控助手 · Xiaomi Remote Assistant

把 **小米蓝牙语音遥控器 2 Pro（RC003）** 连接到 Windows，用遥控器移动鼠标、点击、滚动、输入快捷键和触发千问语音。提供独立桌面窗口、托盘和 **13 个实体按键的可视化配置**，安装和使用不依赖 Ulanzi Studio。

**当前版本：0.1.1 测试版，Windows 10 / 11 x64。** 已完成软件回归及安装验收，跨电脑蓝牙、按键和麦克风兼容性仍在测试。本项目为第三方社区工具，与小米、Ulanzi、千问及 OpenAI 无官方隶属关系。

**[下载安装包](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)** · [测试说明](TESTING.txt) · [更新记录](CHANGELOG.md) · [反馈问题](https://github.com/southingchina/xiaomi-remote-assistant/issues)

## 能做什么

- **直接控制鼠标**：方向键移动指针，按住持续移动，松开停止，可调速度；默认动作不向输入框发送方向键或小键盘 2/4/6/8。
- **点击、拖动与滚动**：支持左／右／中键、双击、滚轮；按住左键配合方向键拖动，滚轮可连续滚动。
- **键盘与快捷键**：Enter、Esc、Backspace、Delete，以及 `Ctrl + Shift + V` 等组合键；支持适用动作的点按、保持和连续重复。
- **程序与网页**：打开指定程序、网址，或聚焦 Codex 输入框。
- **两种语音动作**：实体语音键使用遥控器内置麦克风；备用“通用千问语音”沿用千问当前选择的输入设备。
- **配置管理**：点击遥控器图或功能卡片改绑；复制、切换、导入、导出方案，恢复单键或整套默认值。
- **状态与恢复**：显示连接、电量、按键服务和语音状态，提供暂停、恢复、停止及诊断入口；具备断线重试和输入释放处理。

## 安装前需要什么

| 项目 | 要求 |
| --- | --- |
| 系统 | Windows 10 / 11 x64；尚未提供 macOS、Linux 或 Windows ARM64 安装包 |
| 遥控器 | 目标型号为 RC003／小米蓝牙语音遥控器 2 Pro；其它型号未验证 |
| 蓝牙 | 可正常工作的蓝牙适配器，能够在 Windows 中配对遥控器 |
| 增强按键 | 启用时需要 Windows 管理员授权，用于处理该遥控器的原始按键报告 |
| 遥控器麦克风 | 另行安装并启动千问输入法、安装 VB-CABLE，再完成下方音频配置 |
| Codex 聚焦 | 目标电脑安装 Codex；可将此键改成其它动作 |

安装包自带 Python、Qt、WinRT 和按键组件。**普通用户无需安装 Python、Node.js 或 Ulanzi**；Node.js 只用于源码构建时运行测试。

同一台电脑只运行一套遥控控制核心。已有旧版遥控桥或 Ulanzi 遥控扩展时，请先退出其控制服务。如果程序提示共享驱动内仍有旧组件，退出旧软件后重启电脑再测试。

## 下载与首次连接

1. 打开 [Releases](https://github.com/southingchina/xiaomi-remote-assistant/releases/tag/v0.1.1)，下载 `XiaomiRemoteAssistant-0.1.1-test-win-x64-Setup.exe` 并安装。**Code → Download ZIP** 是源码，不是安装包。
2. 在 Windows **设置 → 蓝牙和设备** 中配对遥控器，然后打开“小米遥控助手”。
3. 点击 **启动控制**，按一下遥控器方向键唤醒它，等待界面显示连接成功。
4. 点击 **启用增强按键**，完成 Windows 管理员授权。
5. **短按一次实体语音键进行来源校准**，随后松开全部按键，等待“按键服务已就绪”。校准用于区分遥控器与普通键盘，不代表语音配置已经完成。
6. 把鼠标放在可滚动页面上，测试方向键、＋／－、返回键及鼠标点击，需要改键时按下节配置。

关闭设置窗口会收至托盘；完全退出请右键托盘图标，选择 **退出程序**。“登录启动”目前只启动窗口／托盘；每次登录后仍需手动启动控制和增强按键助手。

本测试包尚未做发布者代码签名。Release 提供 `SHA256SUMS.txt`；可用 PowerShell 检查下载文件，与清单对应项比较：

```powershell
Get-FileHash .\XiaomiRemoteAssistant-0.1.1-test-win-x64-Setup.exe -Algorithm SHA256
```

## 默认 13 键映射

| 实体按键 | 默认动作 | 按住时的行为 |
| --- | --- | --- |
| 电源 | 聚焦 Codex 输入框 | 执行一次 |
| 上 | 鼠标上移 | 持续移动 |
| 下 | 鼠标下移 | 持续移动 |
| 左 | 鼠标左移 | 持续移动 |
| 右 | 鼠标右移 | 持续移动 |
| 中间确认 | Enter | 执行一次 |
| 返回 `<` | Backspace，删除光标前的字符 | 延迟后连续退格，松开停止 |
| 主页 | 鼠标左键 | 保持按下，可配合方向键拖动 |
| 菜单 | 鼠标右键 | 保持按下，松开释放 |
| 语音 | 千问语音，使用遥控器内置麦克风 | 按住录音，松开结束 |
| ＋ | 滚轮向上 | 延迟后持续滚动，松开停止 |
| － | 滚轮向下 | 延迟后持续滚动，松开停止 |
| TV | Esc | 执行一次 |

返回键默认是 **Backspace**，可改为 **Delete**。Esc 的效果取决于当前应用，并非通用的“停止所有任务”。滚轮每次按住最多连续执行 **30 秒**，防止丢失松开信号后无限滚动；松开再按可继续。

## 怎样自定义按键

1. 点击遥控器图上的按键热点，或对应的功能卡片。
2. 在右侧选择动作类型与具体动作：键盘、鼠标、应用、千问语音或不执行。
3. 选择该动作支持的触发方式：**点按**每次按下执行一次；**按住保持**在松开时释放；**连续重复**按住后重复，松开停止。
4. 按需要填写快捷键、程序路径或网址，调整鼠标速度、重复延迟和间隔。
5. 点击 **保存按键配置**。如果提示等待松键，先松开全部实体按键，让新配置生效。

快捷键示例：`Ctrl + Shift + V`、`Alt + Tab`、`Win + D`、`F5`。一次组合最多包含一个普通按键及修饰键；当前不提供多步骤宏。连续重复的起始延迟为 0–2000 ms，间隔为 20–1000 ms；鼠标移动速度为 1–10。

顶部可复制、切换方案，并通过 JSON 导入／导出，最多保存 30 套方案。导入文件只用于按键方案，不包含蓝牙配对、校准或账号状态。

## 语音怎么接

### 使用遥控器内置麦克风

```text
遥控器麦克风 → 蓝牙 → 小米遥控助手 → CABLE Input
                                            ↓ VB-CABLE
                                    CABLE Output → 千问输入法
```

1. 在目标电脑安装 **千问输入法** 和 **VB-CABLE**；本包不安装这两项第三方软件／驱动。
2. 启动千问，将千问的麦克风／输入设备选为 **CABLE Output**。
3. 打开本程序的 **语音设置**，将输出端点选为 **CABLE Input**，确认已启动千问并完成上述路由。
4. 保持实体语音键绑定为“千问语音 · 遥控器麦克风”。按住说话，松开后等待千问处理。

本程序在实体语音键触发时开启遥控器音频通路，正常松开后排空并结束；未触发时不会主动持续转发遥控器音频。千问自身或其它软件是否使用别的麦克风，取决于其设置。清理失败时，程序保留清理责任并显示诊断，避免旧端点未关闭又新开一条录音。

**遥控器内置麦克风动作只支持实体语音键**，不能改到其它按键。当前千问连接使用其本机 IPC 与日志，千问版本变化可能影响兼容性。

### 使用电脑或耳机麦克风作为备用

将任意按键改成 **千问语音 → 通用千问语音**，并在千问中选好电脑／耳机输入设备。此动作切换千问语音状态，沿用**千问当前选择的设备**；不会自动选择 Windows 默认麦克风，也不会自动从 CABLE Output 切回电脑麦克风。

## 常见问题

| 现象 | 检查顺序 |
| --- | --- |
| Windows 已配对，程序仍未连接 | 按键唤醒遥控器 → 确认已启动控制 → 查看诊断中是否有旧程序占用或蓝牙错误 |
| 蓝牙已连接，但按键没反应 | 启用增强按键并授权 → 短按一次语音键校准 → 松开全部按键 → 等待按键服务就绪 |
| 方向键在输入框翻历史记录 | 检查增强按键是否就绪、当前映射是否为鼠标移动，并确认旧版控制程序已退出 |
| ＋／－或返回没效果 | 检查校准和按键服务状态，再确认鼠标位于可滚动内容／输入框已获焦点 |
| 麦克风无声或千问未出现 | 确认千问已运行、VB-CABLE 已安装，核对 CABLE Input／Output 方向及语音设置确认项 |
| 语音结束后显示正在收尾 | 等待音频排空；正常情况下其它按键仍可使用。持续不结束时查看诊断，不要反复启动录音 |
| 提示已有旧组件 | 退出旧遥控软件并重启电脑，再启动本程序；程序不会强行终止共享蓝牙驱动进程 |
| 断线或休眠后无反应 | 唤醒遥控器，查看恢复连接及增强按键状态；必要时按诊断提示重新校准 |

无法解决时，在 [Issues](https://github.com/southingchina/xiaomi-remote-assistant/issues) 提供：程序版本、Windows 版本、遥控器型号、蓝牙适配器型号、复现步骤和诊断错误。请去掉个人路径、设备地址和控制令牌后再粘贴日志。

## 配置、卸载与数据

- 本机数据目录为 `%LOCALAPPDATA%\XiaomiRemoteAssistant`；按键方案保存在 `profiles.json`。
- 安装与数据目录分开；覆盖安装保留方案，卸载也保留用户配置。
- 程序只处理已校准的目标遥控器，普通键盘不应被重映射。增强捕获使用 Frida 组件与 Windows 共享驱动进程交互，因此需要管理员授权。
- 卸载会停止本程序。共享驱动内已加载组件停止接管后，重启 Windows 可将其完全卸载；不会为此杀死其它蓝牙设备的共享驱动进程。
- 源码与安装包不包含开发电脑的账号、控制令牌或实际设备校准。个人方案可能含自定义程序路径，请自行决定是否分享。

## 当前验证范围

0.1.1 已完成 **199 项 Python 测试、19 项 JavaScript 测试**，以及最终安装产物的离线自检、13 张卡片／13 个热点的窗口加载、实际安装、同版本覆盖安装保留配置和卸载保留配置检查。

测试覆盖音频积压、异步收尾、千问会话所有权、IPC 不明结果、按键释放补偿、滚轮保护和设备限定捕获。软件测试不能保证每台电脑的蓝牙栈、音频驱动和千问版本都相同；**新独立包的跨机器实体硬件测试仍需完成**。请按 [TESTING.txt](TESTING.txt) 验收。

## 从源码运行与构建

开发环境：Windows x64、Python 3.11、Node.js（测试使用 `node --test`），以及 Inno Setup。构建脚本使用 Windows 的 .NET Framework 4.x C# 编译器创建无控制台启动器，需有 `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`。

```powershell
git clone https://github.com/southingchina/xiaomi-remote-assistant.git
cd xiaomi-remote-assistant
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt

# 打开桌面窗口；首次不会自动接管遥控器
.\.venv\Scripts\python.exe launcher.py
```

软件回归与离线检查：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
node --test tests/test_capture_v4.mjs tests/test_ui_save.mjs
.\.venv\Scripts\python.exe launcher.py --self-test result.json
.\.venv\Scripts\python.exe launcher.py --smoke-test gui-result.json
```

`--self-test` 检查依赖、协议回放、配置保存和蓝牙子进程 stdio；`--smoke-test` 检查窗口及页面初始化后退出。两项均不启动实际遥控控制或麦克风。

将完整的 Inno Setup 安装目录放到 `tools/InnoSetup/`，使编译器位于 `tools/InnoSetup/ISCC.exe`；或修改 `build.ps1` 的编译器路径，然后运行：

```powershell
.\build.ps1
```

构建依次执行测试、PyInstaller 打包、C# 启动器编译、源码 ZIP 打包和 Inno Setup 编译。产物在 `release/`，包括安装包、对应源码和 SHA256 清单。Inno Setup 编译器及 Python 虚拟环境不随 Git 提交。

`smoke_installer.ps1` 会实际安装、覆盖安装和卸载，**使用正式 AppId 和当前用户卸载注册项**。只在没有已安装正式副本的测试电脑／测试用户中运行；它隔离文件和配置目录，但不完全隔离注册表。

## 代码结构

| 路径 | 用途 |
| --- | --- |
| `desktop.py`、`desktop_backend.py` | Qt 窗口、托盘、服务启动、诊断和配置接口 |
| `ui/` | 桌面内嵌页面、按键图和编辑器；无需 HTTP 服务器 |
| `rc003_bridge/` | 蓝牙、协议、音频、千问会话、配置和 Windows 输入派发 |
| `enhanced_capture.py`、`enhanced_capture_v4.js` | 设备识别、增强按键捕获、校准和失效恢复 |
| `profiles/rc003-device.json` | 通用按键和设备描述，不含个人配对数据 |
| `tests/` | 软件回归与测试专用 IPC 端点 |
| `vendor/`、`THIRD-PARTY.txt` | 第三方组件、出处及许可 |
| `docs/audit-sync-*.md` | 控制链路审查和回归记录；历史工程路径用于溯源，不是运行依赖 |

Release 的 `source.zip` 是安装包随附的构建时源码快照；仓库首页及后续文档可能包含补充指引。

## 许可证与致谢

项目源代码按 [GNU GPL v3](LICENSE) 发布，第三方组件保留各自许可，详见 [THIRD-PARTY.txt](THIRD-PARTY.txt) 与 `vendor/`。Windows 注入原语参考 MiRemoteVibe／remote-bridge-hub；底层使用 Frida、PySide6／Qt、WinRT Python、sounddevice 和 NumPy 等项目。界面产品图片的来源和权利归属另见第三方说明，项目 GPL 不对该图片授予额外权利。
