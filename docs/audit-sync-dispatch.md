# 控制审计同步：独立派发器

日期：2026-10-23。来源为旧项目只读文档 `ulanzi-virtual-device/docs/control-audit-20261023.md`，以及 `rc003_bridge/ulanzi.py`、`mouse_worker.py`、`core.py`、`test_input_release_recovery.py`、`test_remote_extra.py`。本轮只修改独立项目的 `rc003_bridge/standalone.py`、新增 `tests/test_audit_dispatch.py` 和本报告；没有修改旧服务、版本、安装器或用户映射。

## 审计逐项归类

| 审计条目 | 派发层结论 | 独立实现与证据 |
| --- | --- | --- |
| 音频写出错误/队列满不应重启 BLE | not-applicable | 音频与 BLE 恢复属于 runtime/audio 同步任务；本模块不持有音频端点或 BLE 连接。语音清理错误只记录并重试自己的 owner。 |
| 4 秒 PCM 积压、独立结束任务、端点回收 | fixed（派发等待）/ not-applicable（PCM） | PCM 时长与回收由 runtime/audio 处理。这里将千问调用移至独立 FIFO 线程，`send`、松开和 `release_all` 在 native Condition 外等待；阻塞千问 stop 时普通 Enter 仍可完成。 |
| 统一千问日志会话判断、epoch→monotonic、不接管旧会话更新时间 | not-applicable | 日志解析由 `qwen.py` 同步任务负责。本模块仅调用其 owner API，没有复制日志解析逻辑。 |
| 停止失败独立清理、备用与长按不误停后来会话、原 owner 停止 | fixed | 每次 remote down 分配不同 owner，generic 使用另一独立 owner。绑定快照携带临时 `voiceOwner`，旧 up 不能释放新 press。每 250 ms 检查停止待办，包括 generic 操作触发但仍由 remote 持有的停止；仅调用 `stop_owned(owner=...)`。普通 generic up 不结束录音。 |
| 已执行停止但回包丢失时不得再次 toggle | fixed（派发契约） | 清理重试调用 owner-aware `stop_owned`，由 QwenState 保留已发送/结果不明的确认状态。使用真实 QwenState 和替代读日志/IPC 边界，验证 generic 请求结束 remote 会话失败后，由原 owner 重试确认，总 toggle 数不增加。 |
| 鼠标 up 失败后保留所有权、各按钮独立清理 | already-equivalent | 原独立实现已在 SendInput 成功后才删除资源，失败资源仍能由 up/`release_all` 重试。本轮新增替代 user32.SendInput 的生产 INPUT 编码测试，验证左键失败不跳过右键释放。 |
| Enter/Esc 同一 SendInput 批次及部分 down 补偿 | fixed | `WindowsInput.tap_keyboard` 用同批次发送 down/up；部分写入立刻补发 up。补偿失败保留 pending key，真正 up、后续键盘动作或 `release_all` 再清理，不重发 down。若另一个绑定仍持有该键，则保留既有引用计数路径，避免 tap 提前释放它。 |
| 滚轮最长持续 30 秒、重复 down 不续期、真实 up 重置 | fixed | 首次 down 固定截止时间，在发下一格前检查。超时保留物理按下锁存，重复 down 不仅不能续期，也不能重新开启滚动；真正 up 后新 down 才重新计时。 |
| 插件 ensure 启动不得清除主动暂停 | not-applicable | 独立派发器不负责插件启动；独立运行核心启动/暂停契约由 runtime 任务核对。没有导入 Ulanzi 插件启动行为。 |
| 插件日志失败隔离及日志限额 | not-applicable | 派发器没有插件日志写入或日志回调；动作错误通过异常与 `last_error` 返回运行核心。运行核心日志由其同步任务核对。 |

## 跨 owner 和排队边界

- 使用 `QwenState.supports_owners = True` 契约：`start(owner)`、`toggle(owner)`、`stop_owned(owner)`、`needs_cleanup(owner)`。无 owner 标志的旧测试替身保持兼容；生产 QwenState 使用 owner API。
- FIFO 维持 down、stop 的先后关系，等待千问确认不会持有键鼠锁。失败停止保留对应 press，并自动重试；成功后才释放。关闭失败仍向上报告，后续关闭可再次清理。
- generic 显式操作结束 remote 录音时，不转移原 owner。即使实体语音键仍按着，独立重试也能找到原 owner。
- 已确认旧清理后删除过期重试，不让后来的 generic 会话沿用旧停止任务。回归使用真实 QwenState，执行“启动 generic1 → 停止已接受但日志延迟 → 确认旧停止 → 启动 generic2 → 等待旧重试期限”，generic2 保持录音且没有多发 toggle。
- 较早排队的 cleanup 完成后，后续 generic toggle 会重新记录其清理责任，避免新录音被遗漏。

## 保留行为

13 键默认映射、自定义动作、多方案数据、原子保存与 API 不变；没有写入用户配置。16 ms 汇总移动、默认速度 6 的 120→480 px/s 加速、相反方向抵消、斜向归一化保留。滚轮和键盘重复参数保留。应用异步队列与仅终止自有聚焦助手的规则保留。

## 验证记录

先运行新增测试，复现同批次缺失、30 秒保护缺失、千问占用键鼠锁、owner 缺失和停止无独立重试。后续排队测试额外复现并修复“旧 cleanup 清掉新 generic 责任标记”，物理 up 测试复现并修复“批次补偿失败只能等全量清理”。

最终执行：

```powershell
& 'D:/codex/work/ulanzi-virtual-device/runtime/.venv/Scripts/python.exe' -m unittest discover -s tests -p test_audit_dispatch.py -q
& 'D:/codex/work/ulanzi-virtual-device/runtime/.venv/Scripts/python.exe' -m unittest discover -s tests -p test_standalone.py -q
& 'D:/codex/work/ulanzi-virtual-device/runtime/.venv/Scripts/python.exe' -m py_compile rc003_bridge/standalone.py tests/test_audit_dispatch.py
```

结果：新增 16 项、原有 40 项均通过，编译检查通过。旧项目路径仅用于复用本机已有测试解释器，不是独立程序运行依赖。

原生故障测试运行生产 INPUT 编码，仅替换 user32.SendInput 返回值；语音集成运行生产 QwenState，仅替换日志读取与 IPC 发送。没有真实 SendInput、实际录音、麦克风切换、BLE 接管、旧服务重载或 UI 操作。真机和重建安装包验收由主任务继续完成；永久注入拒绝或不可恢复的语音状态仍会报告失败，不宣称保证恢复。
