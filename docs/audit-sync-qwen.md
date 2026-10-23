# 独立版千问会话修复同步（2026-10-23）

## 直接来源

- `D:/codex/work/ulanzi-virtual-device/docs/control-audit-20261023.md`：本次用户指定的审计结论。
- `D:/codex/work/ulanzi-virtual-device/rc003_bridge/ulanzi.py` 的 `QwenState`，及根目录 `test_qwen_state.py`：实际 Python 日志格式、会话标识和 epoch → monotonic 迁移规则。
- `D:/codex/work/ulanzi-qwen-voice/plugin/voice.js`、`plugin/bridge.js`，及 `test/voice-runtime.test.mjs`、`test/voice-recovery.test.mjs`、`test/bridge.test.mjs`：停止归属、清理重试、IPC 确定未发送／明确拒绝／结果未知的已验证行为。

审计中提到的 Ulanzi 插件代码仅作为行为参考。独立版仍直接使用 Python Windows named-pipe IPC，无 Ulanzi 或 Node 运行依赖。本次未改旧服务、旧插件或生产千问状态。

## 差异与实现

1. 独立版原有解析器已支持 `begin`、`commit`、同 PID 且 5 秒内的 accepted runtime handoff，以及 `finished/cancel/abort/start_failed/runtime_terminal`。新增来源一致性回归保留这些已正确的逻辑。
2. 独立版原来把同一个 session 的更新 timestamp 当成新开始。现在有 session/id 时只比较身份；兼容旧 `id` 字段及 epoch 日志进入 monotonic 事务，时间只作无身份且同时间域的回退。
3. 新增 `start(owner=None)`、`stop_owned(owner=None)`、`toggle(owner=None)`，类标志 `supports_owners=True`。每次遥控器按下由派发层提供独立 owner，备用通用语音使用另一个 owner。迟到释放和旧清理不能结束后来另一 owner 的录音；显式 toggle 结束已持有的会话时保留原 owner。
4. `cleanup_required` 与 `stop_pending` 分开：前者表示已请求结束但还需确认；后者表示停止命令已接受或结果不明。日志暂时不可读、同会话仍 starting、确定未发送错误都不丢失所有权。`needs_cleanup(owner=...)` 供派发层独立重试。
5. `QwenIpcError.sent` 保持兼容，表示“命令可能已执行”。新增 `outcome=not_sent/rejected/unknown`。只将尚未写入或匹配事务的明确 `ok=0`／`handled=0` 判作可重发；缺少确认字段、错误事务 ID、损坏回包和写入后超时都是 unknown。
6. 已接受／unknown 停止后只继续确认。日志仍旧时不得再次 toggle；迟到终止日志到达后清理归属。新的 toggle 在已有清理责任时先完成原停止，不立即重新开麦。

## 验收

- 失败优先：新增测试首轮复现同会话时间戳误判、缺失 handled 误判、读日志失败丢清理、starting 被错误当成终止，以及缺少 owner API。记录：`evidence/audit-sync-20261023/qwen-red.log`。
- 最终局部回归：`python -m unittest discover -s tests -p '*qwen*.py' -v`，**37 项通过**（24 项新回归 + 13 项原有回归）。记录：`evidence/audit-sync-20261023/qwen-green.log`。
- 其中真实 Windows 本地 named-pipe 集成覆盖唯一测试管道：停止实际执行但回包丢失且日志延迟、明确拒绝、缺少 ack 字段、错误请求 ID、损坏 ack，以及管道不存在。该测试传输实际 QIPC 帧但不连接千问生产端点，不打开麦克风，不注入按键。
- owner 交叉清理、并发两次 stop 只执行一次、临时日志故障、accepted 停止后状态仍 starting/recording 等由内存会话模型验证。

此报告只证明对应软件与真实本地 IPC 路径的行为，不能替代另一台电脑的实体遥控器或真实千问音频验收。
