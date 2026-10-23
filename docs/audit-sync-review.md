# 0.1.1 控制审计同步：独立复核

审查日期：2026-10-23。审查目录：`D:/codex/work/rc003-remote`。

## 结论

规格符合性：通过。当前源码覆盖旧审计中适用于独立程序的要求；AS1、AS2 及 AS1 补充交接窗口均已修复并通过独立复核。

代码质量：通过。本次未发现剩余的严重或重要源码阻塞项。千问等待位于原生输入锁外；资源实际关闭、会话所有权、停止确认与按键释放责任分别有明确状态及故障回归。对关键异步边界同时检查了实际代码与确定性时序复现，未仅依赖整套测试结果。

本报告是源码和软件行为审查。冻结包、安装／覆装保留配置／卸载验收由主任务完成；本轮未进行实体按键、BLE、实际声卡或生产千问验收。

## 依据和范围

- 用户指定直接来源：`D:/codex/work/ulanzi-virtual-device/docs/control-audit-20261023.md`。
- 本轮实现说明：`docs/audit-sync-runtime.md`、`docs/audit-sync-qwen.md`、`docs/audit-sync-dispatch.md`。
- 实际审查：`rc003_bridge/audio.py`、`runtime.py`、`qwen.py`、`standalone.py`，以及独立生命周期、桌面状态转发和 UI 提示。
- 旧服务只作为只读来源；独立程序没有引入 Ulanzi、旧工程路径或 Node 运行依赖。当前独立 `audio.py` 与旧审计后的直接来源 SHA256 均为 `50C08C558F6D3BD69DA197701AC8C95DDC7A86827DA444D508E3F7B01D32B41B`。
- 审查者只写本报告。所有故障复现使用替身端点／输入／BLE 或测试专用 named pipe，没有打开生产千问管道、注入实际按键或修改旧服务。

## 审查发现与处理

### AS1：迟到关闭失败必须一直持有旧音频端点

最初问题位于 `runtime.py` 的 `begin_voice_finish.consume_result`。异步收尾任务超时后，原生收尾线程才返回关闭错误；旧代码把 future 完成当成资源回收，即使 `output.stream` 仍存在也清除最后的引用。独立复现得到：旧流仍存在、`output` 和 `voice_finishing_output` 均不持有它、允许新录音。

第一轮修复在迟到失败时将旧对象转回 `self.output`，保留 `voice_release_pending`，直到重试实际关闭成功。`test_late_failed_close_keeps_endpoint_owned_and_can_retry` 验证保留所有权、拒绝新录音和最终成功重试。

复核又发现一个同根因交接窗口：future 的完成函数已经运行，`consume_result` 尚在事件循环待运行队列中；此时 task/future 都为 done，但旧对象尚未转回 `self.output`。同一轮待运行的新 `voice_down` 可通过检查，在读取千问状态之后覆盖回调刚恢复的旧对象。确定性无硬件复现得到 `openedNew=1`、`oldStreamStillOpen=True`、`oldOwnerRetained=False`。

最终修复在 `runtime.py:393` 的 `voice_finish_pending` 中将仍持有的 `voice_finishing_output` 也计为 pending，在所有权交接完成前持续禁止新录音。`test_done_future_before_owner_handoff_cannot_open_second_endpoint` 精确安排“future 完成 → 新录音任务 → 所有权回调”的事件循环顺序，验证没有创建第二个输出对象，旧对象仍可清理，成功重试后门控正常解除。该修复和两项 AS1 回归均已独立复核，最终完整回归通过。

### AS2：旧 generic 清理重试不得停止下一次 generic 会话

问题位于 `standalone.py` 的 `_scan_voice_cleanup`。generic owner 在派发器生命周期内固定；一次已接受停止遇到迟到日志时留下重试，随后用户通过 toggle 确认旧停止，再启动新会话，旧重试仍能按同 owner 停止新录音。

使用实际 `QwenState` 和实际 `NativeDispatcher`、仅替换日志及 IPC 边界复现：启动 A → 停止已接受而日志仍旧 → 终止日志到达 → 确认 A 停止 → 启动 B → 等待 250ms 以上，旧实现额外 toggle 停止 B。

现已修复：确认无需清理时删除旧重试；每个排队 generic toggle 实际执行前恢复清理责任标记，避免前一个 cleanup 清掉下一次录音的责任。`test_old_generic_retry_cannot_stop_a_new_generic_recording` 在上述实际组合中验证 B 保持录音且没有额外 toggle。当前源码复核通过。

## 规格逐项核对

| 旧审计要求 | 独立版实现与验收依据 | 当前判断 |
| --- | --- | --- |
| 音频故障不重启 BLE；真实 GATT 故障交给连接监督器 | `consume_connection` 的音频异常只调用 `voice_failure`；关闭写入异常仍向连接监督器传播。故障注入验证原连接、epoch 及其他按键保留。 | 符合 |
| PCM 以 4 秒积压计量，包含正在写出的数据；启动积压可排空 | `PcmOutput.pending_bytes` 在原生写出完成后才递减；测试覆盖 4 秒边界、450ms 启动确认积压、完整有序排空和慢写超时。 | 符合 |
| 独立收尾不阻塞其他按键，未回收端点禁止再次打开 | 独立原生 daemon 收尾线程和 asyncio 收尾任务；键盘继续执行、失败释放异步重试、原绑定对象身份匹配及 AS1 完成回调交接均有回归。 | 符合 |
| 日志会话判断、epoch→monotonic、同会话时间变化不算新录音 | `QwenState.newer` 优先会话身份；解析 begin／handoff／cancel／失败，时间仅作兼容回退。 | 符合 |
| 停止保留原 owner；旧松开、备用和长按不误停后来的会话 | 每次 remote 按下有新 owner；绑定保留临时 owner；generic 停止当前 remote 会话保留原 owner；精确组合回归覆盖 AS2。 | 符合 |
| 已接受或不确定的停止只确认，不盲目 retoggle | `cleanup_required` 和 `stop_pending` 分离；匹配事务明确拒绝与未发送可重发；写入后损坏／缺失／错误事务确认按 unknown。真实测试 pipe 覆盖执行停止后丢回包及日志仍旧。 | 符合 |
| 原生输入失败后保留释放责任；Enter/Esc 批量 down/up 与补偿 | 成功释放后才移除资源，多个资源独立清理；批量部分写入立即补 up，补偿失败由真正 up、后续输入或总清理继续释放。 | 符合 |
| 滚轮最长 30 秒，重复 down 不续期 | 到期停止重复但保留按下锁存，必须真正 up/down 才重新开始。 | 符合 |
| ensure 尊重暂停；日志故障隔离及限额 | 生命周期回归验证暂停标记和运行中暂停均不被 ensure 清除；日志写入失败不逃逸、256KiB 轮转、动作错误仍上报。 | 符合 |
| 独立程序状态诚实、不影响现有服务 | 桌面白名单转发 voiceFinishing／voiceReleasePending／audioPendingSeconds，UI 显示语音收尾；停止状态保留清理失败。无旧服务运行依赖。 | 源码符合；安装验收由主任务记录 |

## 验证记录

最终稳定源码的独立完整运行：

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
node --test tests/test_capture_v4.mjs tests/test_ui_save.mjs
node --check ui/app.js
.venv/Scripts/python.exe -X utf8 -m py_compile rc003_bridge/audio.py rc003_bridge/runtime.py rc003_bridge/qwen.py rc003_bridge/standalone.py desktop_backend.py desktop.py
```

结果：**199 项 Python 测试通过（14.336 秒），19 项 JavaScript 测试通过，JS 语法与 Python 编译检查通过**。所有命令退出码为 0。整套包含实际 QwenState 与派发器组合、实际 Windows 测试管道、15 项音频审计回归，以及捕获、桌面、协议恢复和既有派发测试。

此前 198 项 Python 回归也通过，但未覆盖 AS1 的完成回调窗口；随后独立定序复现发现该问题，再补测试和修复。最终结果采用修复后的 199 项完整运行。

测试边界：Windows named-pipe 测试使用唯一测试端点和真实 QIPC 帧；原生 INPUT 编码测试替换 SendInput；音频测试替换 sounddevice 端点；BLE 测试替换 transport。旧服务文档中的真机结论未计入新包验收。
