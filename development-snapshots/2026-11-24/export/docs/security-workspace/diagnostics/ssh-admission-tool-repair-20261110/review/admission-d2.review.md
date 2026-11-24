门禁：D2静态通过（仅源码审读，未执行测试）。`required` 已含 admission、record-analysis、regression.test、analysis.test、r2.test、manage 六项；`contract.sources` 逐项摘要校验，缺失 `analysis.test.py` 会拒。serverEvent 逐项检查：`responseSent` 必须 bool、`requestBytes` 必须 int 0/1 且与前者一致；`acceptedMonoNs` 必须 int、≥release、按事件非降；响应事件须有唯一合法 `requestIndex`，对应 client 的 `commandCalls=1`、`connected=True`、`accept>=exchangeStarted`，complete 时还须 `accept<=exchangeEnded`；空请求 index 必须 None。失败响应无上界，仅记 `responsesWithoutClientCompletion`，不入 aggregates。独立重算 clients/connected/complete/failed/notSent/errors/notSentReasons 并与存储 aggregates 等值；`need` 显式 raise，无 assert，`-O` 不能跳过；完成回显通过 responded 索引与 accept 区间交叉，协议证据层可靠。

可证明缺陷：D2 范围内未发现，无需最小触发。

条件风险：1）零字节 accept 未绑定到具体 connected/attempted 客户端，理论上可在某失败客户端未连接时伪造空 accept；不影响 complete 计数，但削弱全量 accept 证据。2）缺字段/错容器可能抛 KeyError/TypeError 而非统一 ValueError，仍属失败关闭。3）complete 依赖 worker 的 complete bool 加响应事件存在；serverEvent 不存回显字节，不能独立证明回显内容。4）serverErrors/cleanup 明细未 schema 化。

最小必要修订：D2 无阻断性修订。可选硬化：将零字节 accept 绑定到 `commandCalls=1` 且 connected 的未响应客户端/attempt；补 serverErrors/cleanup schema；统一异常为 ValueError。未执行测试、未重算 SHA，不能声称生产根因已确认。
