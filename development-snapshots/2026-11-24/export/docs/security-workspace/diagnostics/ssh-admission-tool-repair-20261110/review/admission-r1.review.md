门禁：本批（R1+R3静态审读，材料自述的合成证据范围内）**条件通过，未发现可确认阻断**；不能据此判全8trial集成、生产根因或工具可复用安全通过。

确认缺陷/最小触发：本批**零确认阻断**。前轮五项均见对应修复：资源前安装、mask包围安装/恢复、逐项恢复并记录、非主线程/缺上下文ok=false、cleanup不改handler、body异常保留并附`.cleanup/notes`、`CleanupFailure`携带报告、`wait_ready`非阻塞分片和完整行校验。未找到能越过这些检查仍造成资源泄漏的静态最小触发。

条件风险（非本批阻断）：
1. `run_signals`最终恢复失败只记录/抛错，失败handler可能残留；恢复窗口到达的旧handler信号或最后一个安全点后的信号可能未被报告，依赖进程退出/外层`check_cancel`。
2. `cleanup_owned`缺上下文/非主线程不抛拒绝，而是`ok=false`+`UnsupportedCleanupContext`；调用方忽略`.ok`或`.cleanup/notes`仍可能误用。
3. 2s清理预算后`communicate/wait/join`仅约1ms，真实子进程/线程可能短暂存活；SIGKILL、不可中断OS调用、外部并发改handler不保证。
4. `wait_ready`对同一次读到的READY尾随会拒，但`READY\n`之后才到的额外字节不检测；`finally`恢复blocking失败可替换原异常。
5. 材料中的合成4套/45方法通过不等于8trial控制实验或生产集成；未执行测试/SHA重算。

最小必要修订：若要提升门禁，补测并约束恢复失败、body异常+cleanup false、调用方忽略ok、READY尾随/`set_blocking`异常；调用方必须把`cleanup.ok=false`及`.cleanup/notes`视为失败，恢复失败显式标不可复用。无需在本步要求SIGKILL等不可能保证。
