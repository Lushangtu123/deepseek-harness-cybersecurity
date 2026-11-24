**门禁（本批范围）**：D1 静态复核**通过**。未发现本轮架构引入的 D1 回归；无重放门禁保持。仅限静态审读，未执行测试、未重算 SHA、未确认生产根因。

**可证明缺陷**：零。  
关键保持：
- `summarize` 只允许 `commandCalls∈{0,1}`；0 次仅接受 `queue|SSHNotSent` 且无连接/交换时间戳，计入 `notSent`；1 次未完成计入 `failed`；1 次完成计入 `complete`。故 `clients = complete + failed + notSent`。
- `exchange` 第二次调用先增计数再抛 `Replay refused`，汇总/独立分析均拒绝 `commandCalls=2`；未见重试路径。
- `record-analysis.py` 独立重算分母，拒绝非法调用数、伪造聚合、错误事件类型及完成/响应矛盾；失败客户端收到响应仅计辅助诊断，不升为成功。

**条件风险**：
1. 汇总层信任 worker 产出的 JSON；完全同形的伪造 `not-sent` 无法仅由 `summarize` 区分，依赖源码哈希与进程边界。
2. `summarize` 对 0 次记录未强制 `requestEntered/EndedMonoNs`；独立分析有此检查，故不影响本批 D1 分母，但汇总自证强度弱于独立分析。
3. `run_signals` 非抛异常 + 60s 软期限：若局部阻塞/清理累计超期，会在下一安全点失败且不写结果，不会错误计数；但可能使控制运行失败。
4. cleanup 在已有取消信号时 `ok=false`，成功 body 可能以 `CleanupFailure` 结束；属严格失败，非 D1 误分类。

**最小必要修订**：无阻断修订。可选加固：`summarize` 对 `commandCalls=0` 也要求请求起止时间为合法、有序整数；或显式化 60s 软期限与单 trial 预算关系。非本批通过必要条件。
