# 2026-10-23 控制链审核修复：独立版音频与运行核心同步

本次仅修改 `rc003_bridge/audio.py`、`rc003_bridge/runtime.py`，新增 `tests/test_audit_audio.py` 和本报告；未修改版本或构建配置。旧服务、旧插件、驱动及其运行配置均未改动，也未启动实际硬件桥、音频端点、麦克风或增强捕获助手。

## 直接来源

- `D:/codex/work/ulanzi-virtual-device/docs/control-audit-20261023.md`：2026-10-23 最终控制链审核说明，SHA256 `56787C1BE963705E13B0C0EE6DEEBCECCAC581814F35A0F78DE98D483F74C23D`。
- 同目录 `rc003_bridge/audio.py`：按 PCM 时长计量、排空及端点回收实现，SHA256 `50C08C558F6D3BD69DA197701AC8C95DDC7A86827DA444D508E3F7B01D32B41B`。独立版 `audio.py` 与该直接来源逐字节一致，没有旧服务依赖。
- 同目录 `rc003_bridge/runtime.py`：原始审核后的独立音频收尾任务及语音故障隔离实现，SHA256 `7FFF0FBBD4E89DCB91D0B937AA392A7C8786655246A6C548154CFCC4090CA422`。仅按独立版动作所有权和过滤输入契约移植适用逻辑，未复制 Ulanzi 配置、派发器或外部脚本依赖。
- 同目录 `test_audio_startup_buffer.py`、`test_audio_fault_isolation.py`、`test_voice_fault_isolation.py`：端点、启动积压、持续按键、故障重试与真实按下代次的回归依据。

修改前快照由父任务保存在 `evidence/audit-sync-20261023`。

## 复现与修复

第一轮新增 8 项测试在旧独立版上全部失败（4 failures、4 errors）：以块数限制的队列既无法正确限制大块音频，也会拒绝不足一秒的启动积压；固定 350ms 排空截断尾音；声卡错误逃逸为整条连接错误；正常结束阻塞后续按键；千问正在开始/处理时仍先打开输出。

已同步的行为：

1. PCM 积压预算为 16kHz、16-bit 单声道的 4 秒，包含队列和正在写出的数据，不限制正常录音总时长。按剩余 PCM 时长加余量排空，超时明确报告并请求中止。
2. 正常音频收尾在单个 daemon 原生收尾线程及对应 asyncio 任务中执行。端点未真正回收前始终保留所有权，新的遥控麦克风录音被拒绝；不可回收的声卡线程不会占住 asyncio 默认执行器退出。
3. 其他按键在排空期间继续处理。千问动作的失败释放也在独立任务中重试；新增失败注入先复现其重试阻塞，再修复，避免重试重新冻结输入循环。
4. 收尾仅释放开始时的同一个绑定对象；更改配置、断连清理后形成的新绑定不会被旧收尾任务释放。等待中的新录音被拒绝时不取消上一段录音尾音。
5. 真正断连、暂停/配置切换、租约丢失等清理可显式中止待排空音频，并保留尚未完成的端点诊断。普通物理语音键松开按正常排空处理，随后到达的中立帧不会截断尾音。
6. 解码或输出故障调用仅作用于语音流的 `voice_failure`，保留 BLE/HID 会话、epoch 和其他按键；真正的 GATT 关闭写入错误仍交给连接监督器。
7. 保留独立配置路径、冻结子进程角色、认证控制接口、全部按键的 `filtered-remote` 限定及输入代次屏障；千问继续通过同一个独立 `QwenState` 和动作派发器执行。
8. 复核补充：收尾任务已超时后，声卡线程迟到报错且 `stream` 仍存在时，保留原输出对象与待清理标记，不将线程完成误当作端点已回收；下一次清理成功前拒绝新麦克风。针对性测试先复现丢失所有权，再验证保留、拒绝新录音和成功重试。
9. 复核补充的完成回调交接竞态：`Future` 已完成但回调尚未移交旧端点时，仍将非空的 `voice_finishing_output` 视为清理未完成。精确 `call_soon(set_exception)` 与新按下排队的回归先复现第二端点被打开，再验证拒绝新开麦、晚回调保留旧对象，以及清理成功后门控解除。

状态字段：`voiceFinishing`、`voiceReleasePending`、`voiceIssue`、`audioPendingSeconds`、`cleanupPending`、`cleanupIssue`。音频收尾不把蓝牙状态改成离线；声卡永久挂起时，状态继续显示语音收尾未完成。

## 验证

- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_audit_audio.py -q`：15 项通过，约 9.6 秒，包含完成回调交接竞态回归。
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_installer_runtime.py -q`：既有 25 项通过。
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_protocol_recovery.py -q`：既有 19 项通过。
- 与同期千问/派发修复集成后，复核代理独立执行 `.venv/Scripts/python.exe -m unittest discover -s tests -q`：199 项通过，14.336 秒；19 项 JavaScript 测试、`node --check` 和 6 个核心/桌面 Python 文件编译检查通过。复核结论见 `docs/audit-sync-review.md`；本任务另行执行两个实现文件的 `compileall` 通过。

专项覆盖：4 秒预算含 inflight；0.51 秒突发完整按顺序排空；450ms 启动确认期间 27 帧积压；排空时键盘动作继续；慢写超时；拒绝新录音保留旧尾音；断连中止；真正未回收的声卡保留；旧任务无法释放替换绑定；失败释放异步重试；音频错误保留原连接；真实 GATT 错误上抛；千问开始/处理状态不打开声卡。

测试全部使用模拟 `sounddevice.RawOutputStream`、替身动作派发器和替身 BLE transport，未运行实际声音通路。旧服务上的真机验收属于来源证据，不等同于独立安装包的真机验收；新包仍需安装后验证千问、VB-CABLE、实体按键与恢复行为。
