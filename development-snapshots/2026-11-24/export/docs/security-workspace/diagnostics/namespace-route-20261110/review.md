**结论：有限通过（仅限“既有结构复核路径受控验收”）。**  
本轮未发现需要在本次范围内确认阻断的新证据；不得外推为 R3 准入、真实扫描/工具准入、日常169全流程或漏洞确认。以下为静态阅读结论，不替代实际执行。

**核对通过项**
1. **覆盖判断更正成立**：旧 `eval_evidence_batch` 的 `GUARD_RULES` 不含 `dynamic-code-namespace`；联合深入口在 `semgrep && workspace` 后调用 `bench.namespaceEvidence`，输出 `eligible=1/checked=1/observations=1`。旧入口0检查只能说明旧入口不适用。
2. **默认 collector/沙箱边界清楚**：driver 仅包裹默认 `namespaceEvidence` 记录摘要，未替换该 collector；沙箱走默认 Docker helper，校验 worker SHA、镜像、禁网/只读/UID/capability/资源限制及清理。但 `toolStatus` 与 scanner runner 是回放夹具，`scannerInvocations=0/replays=2/modelCalls=0`，不能证明真实扫描或工具准入。
3. **回放与 fixture 身份边界已声明**：阳性回放完整候选扫描；阴性是清空 `results`、仅留 `fixed.py` 的过滤子集，输出 `patched-only / not-applicable / eligible=0`。首次 `coverageKey` 非 SHA256 被原回执守卫拒绝并保留，修正为 SHA256 后通过，未放宽产品校验。
4. **全量摘要检查时序正确**：动态导入前检查173项程序摘要，结束再次检查；`job.py` 断言 `programFilesRechecked=173`，并核对日常169程序前后不变、运行规则/镜像清单不变。
5. **worker/source 绑定可信**：worker SHA 与候选脚本一致，镜像 ID 与候选扫描一致；第46行 artifact 的 offset `1466–1492`、`sourceSha256` 与 `before.py` 匹配，保留 `unverified`。
6. **原 warning 与普通表零新增**：联合发现保留1条原 warning 且 `status=unverified`；driver 断言 `security_finding` 计数为0，普通表零新增。
7. **输出保守**：`unsupported-scope`、`expression-unresolved`、`builtinIdentity=unverified`、`externalControl=unverified`、`constraintState=unresolved`，且 `ordinaryR3Qualified=false`、`qualificationCasesAdded=0`。
8. **失败与清理证据一致**：占位符污染在本机复现、原 root 不存在、修复后前置变量赋值并发送前 compile；首次实际回放因 `coverageKey` 被拒的原错误和清理回执保留；最终 `vm-cleanup` 为 cleaned。

**范围外 R3 缺口（不构成本次阻断）**
- 无真实扫描、真实工具准入或新增独立准入样本；`toolStatus`/scanner 回执是夹具。
- 未完成 R3 评测；不能声称 R3 准入。
- 类方法/try 作用域仍 `unsupported-scope`；外部输入可达性、跨函数数据流、内建身份仍未证明。
- 日常169仅做源码 substring 检查路由及 workspace 条件，未执行本批完整流程；173候选联合编排与169不同。
- 无 Chrome、原生模型或完整 API 业务流程验收。

**可验证发现：零新增阻断项。**  
上述均为已声明的夹具边界或范围外 R3 缺口。建议记录为“结构复核路径有限通过；R3/真实准入保持未完成”。
