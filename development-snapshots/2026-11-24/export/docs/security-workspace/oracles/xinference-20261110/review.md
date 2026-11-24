# Xinference CWE-95 诊断切片 · F1–F10 复审（第二轮）

本轮由 Opus 5.5 审阅，工具关闭，仅做静态阅读，所有材料均按数据处理。effort 档位我无法自证，只能看到 `r1-claude-status.json` 中 harness 自己记录的 `high`。

## 结论

**本步通过，限诊断切片范围。本步没有新增的确认阻断。**

- F1–F10 在可追补的范围内已关闭，或已收窄为明确披露的限制。
- 质量门仍为 `blocked`，`r3Qualified` 为 false，准入新增数量为 0。
- 本结论不代表 R3 准入，也不代表全产品通过。

## 本轮实际核对的内容

**偏移量手算一致。** 我逐行累计了 `before.py` 第 1–45 行的字节数（按 LF、ASCII 计），结果为 1447。加上 12 格缩进和 `data = ` 共 19 字节，`eval` 的起始偏移为 1466。表达式长 26 字节，结束偏移为 1492。这与 Semgrep 结果和 `evaluation-replay.json` 一致。

**摘要交叉引用自洽。** 以下是材料内部声明值之间的比对，我没有重算哈希：

| 声明值 | 在以下位置出现且一致 |
| --- | --- |
| `protocol.json` 13fb47b5 | v2 的 `supersedes` |
| `advisory.json` 2f520472 | 内容净化补充记录 |
| `security-output.sh` f63f62c7 | identity-derivation、VM 169 项清单 |
| 复核器三文件摘要 | reviewer-dependencies、VM 清单、source-intent |
| worker d3a7e50e | attempt、protocol |
| witness b62fdb3f | protocol-v2、retry-embedded |
| 两份 VM 检查脚本摘要 | bridge 日志第 6、7 行，post-review state |
| receipt d76208f3 | status |
| ledger f9d4a3bf、policy e9b429fc | source-intent |

**归档内容逐段一致。**
- `input.json` 中的 `outputPolicy` 与 `security-output.sh` 逐段一致。
- `input.json` 中的 provenance 与 `source-provenance-pre-run.json` 一致。
- 原内嵌 witness 仍使用 `ast.dump` 和 `astSha256`，与首次失败的原因吻合。

**回顾性重算的逻辑正确。** 诊断版 dataset 与旧 freeze/run 的摘要不一致，因此产生 `dataset-changed-after-freeze` 和 `run-dataset-mismatch` 两个阻断，这是预期结果。两例都进入了 `excludedFromQualification`，CWE-95 的 qualification total 为 0，diagnostic 仍为 2。

## F1–F10 状态

| 项 | 状态 | 保留范围 |
| --- | --- | --- |
| F1 | 已关闭（文档） | 复核器不覆盖新规则 ID。候选命中仍为 unknown。复核器依赖闭包没有预冻结身份，保留为 R3 准入缺口。 |
| F2 | 已关闭 | 原 `source-provenance.json` 仍是原位修改后的版本，以 pre-run 副本为准。 |
| F3 | 在可追补范围内关闭 | 失败当时的环境状态永久无法证明。容器不存在只在 22:02 的事后检查中得到证实。 |
| F4 | 基本关闭 | 见下方 N1、N2。 |
| F5 | 本步已关闭 | 排除依赖 oracle kind 实现，质量门本身不读取 `selection` 字段（见 N3）。 |
| F6/F7 | 已关闭 | 容器 3.12.15 的 AST 摘要从未实际记录，“3.12 系列默认保留空列表”属于版本推断。 |
| F8 | 已关闭 | 没有扫描进程内部的逐文件测量，这一限制保留。 |
| F9 | 已关闭 | 本步复审有真实 receipt。effort 由 status 自记录，receipt 中没有 effort 字段。 |
| F10 | 措辞和许可证已关闭，台账待办 | 下次 freeze 之前必须登记 `bc10f7…`、`4e09cd…` 两份源码，以及 attempt1（失败）、diagnose、witness retry 和两轮扫描。 |

## 本轮新增的低级别发现（非阻断）

**N1 回放的依赖身份没有在运行时绑定。**
- 三个回放脚本按路径执行 `eval_evidence_batch.py` 和 `review_quality_gate.mjs`，运行前没有断言文件摘要。绑定只来自时间相近的另一次采集。
- 以下内容不在材料中，因此回放无法完全独立复核：`poll.json`（`replay-conversion.mjs` 依赖它）、`review_quality_gate.mjs`、`eval_guard_review.py` 的源码，以及回放使用的 python3 版本。

**N2 “完整调用记录”的措辞偏强。**
- `vm-bridge-calls.jsonl` 没有时间戳，只记录脚本摘要。
- diagnose 脚本（`0d101eef…`）的正文没有归档。
- `post-review-vm-state.json` 是宿主侧加工后的记录：增加了 `scriptSha256`，去掉了 `baselineRulesRaw`，不是原始 stdout。
- 建议改为“调用摘要日志（无时间戳；诊断脚本正文未附）”。

**N3 门禁的结构性缺口（R3 范围，不影响本步）。** `selection.qualificationEligible` 只是文档字段。今后如果有定向挑选的配对被误标为 `independent-vulnerability`，仍会被计入准入。

**N4 许可证的绑定不完整。** `LICENSE.upstream` 没有绑定 commit 或 blob 摘要，也没有核对上游是否存在 NOTICE 文件。

**N5 卫生建议。** `review-replay.json` 的 argv 中含有本机绝对路径和用户目录名。对外发布前建议脱敏。

N1、N2 只需修正措辞或补附文件，不影响诊断结论。N3 属于 R3 门禁的设计问题，留到准入阶段处理。
