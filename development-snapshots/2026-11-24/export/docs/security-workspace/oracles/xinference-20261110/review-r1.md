# Xinference CWE-95 诊断切片审查（Opus 5.5，工具关闭，仅静态阅读）

## 结论

**有限通过。** 在诊断切片的声明范围内，本步没有确认的阻断项。

以下核心结论与数据自洽：

- 16 规则漏报 `before.py:46` 的三参数 `eval`，17 规则命中同一位置。
- 补丁文件两套规则均未报警。
- 方法级见证显示旧方法第 46 行确实执行动态求值，补丁方法没有。
- 质量门保持 `blocked`，`r3Qualified` 为 false。
- 原 VM 任务仍记为 `failed`。

不过有 5 项中等问题需要修正或补充证据，才能完整支撑报告中的部分措辞（见第二节）。这些问题都不推翻诊断结果。

工具关闭，下列内容我**未能独立重算**：各文件 SHA-256、Git blob SHA-1、规范化 JSON 摘要（freeze、dataset、policy、ledger）、第 46 行的 offset 1466、retry 脚本内嵌 witness 与 `witness.py` 是否逐字节相同。GHSA-x2rj-828p-hx9m / CVE-2026-61539 的公告正文在我的知识截止之后，也未包含在材料中，所以公告内容同样无法核实。

---

## 一、已核对且一致的部分

**1. 源身份与行列**
- 逐行计数后确认如下：
  - `before.py` 中方法位于第 26–49 行，`data = eval(model_output, {}, {})` 在第 46 行。缩进 12 格加 `data = ` 共 19 字符，所以 `eval` 起始于第 20 列。表达式长 26 字符，结束列为 46，与 Semgrep 的 start/end 完全一致。
  - `fixed.py` 中方法位于第 28–62 行，`json.loads` 在第 49 行第 20 列，`ast.literal_eval` 在第 56 行。
- commit、路径、URL 在 source-intent、provenance、protocol v1/v2 和 dataset 之间一致。
- check_id 带 `policy.` 前缀，这是 Semgrep 按配置所在目录 `/policy/` 自动加的，属正常现象。

**2. 规则差异能解释漏报**
- 17 规则文件逐条计数确为 17 条。其中 `harness.python.eval` 只匹配单参数 `eval($VALUE)`，因此会漏掉三参数调用。新规则覆盖 2 参数和 3 参数形式的 `eval` 与 `exec`。
- 基线规则文件本身不在材料中，只有摘要 `44ab40…`。一个旁证是 prefilter 比例：基线 0.2 约等于 2/10，候选 0.2727 约等于 3/11，正好相差一条 Python 规则。但这只是间接证据。

**3. freeze 与台账**
- 我手工计数 `developmentSourceSha256`，共 229 条，其中没有 `bc10f7…` 或 `4e09cd…`。`developmentOverlap` 为 `[]`。
- 时序正确：source-intent 21:41:29，早于 protocol 21:45:28，早于 freeze 21:45:36.94Z，早于 run 21:47:03。
- `policy.json` 的文件摘要 `e9b429fc…` 与 source-intent 中固定的值一致。

**4. 质量输出**
- 我按 `review_quality_gate.mjs` 的逻辑对两份输出逐项手算，计数、比率和 blockers 全部吻合：
  - 基线：recall 0，FNR 1。
  - 候选：raw recall 1，reviewed unknown 1/2 = 0.5，confirmedRecall 0，FNR 为 null（分母为 0）。
- 候选命中的 line、sourceSha、language、cwe 都与 dataset 匹配，因此没有触发 `scan-location-mismatch`。

**5. 见证逻辑**
- `eval(s, {}, {})` 在 globals 缺少 `__builtins__` 时会自动注入内建函数，这正是 `str(...)` 能执行的原因，也是漏洞本质：`{}` 不构成沙箱。
- 各输入的行为都符合预期：
  - `true` 触发 NameError，返回原文。
  - 无效文本在编译阶段失败，不产生帧。
  - `[]` 求值后取键时报 TypeError，返回原文。
- 补丁方法中 `json` 和 `literal_eval` 的帧都不属于 `<string>`，因此记录为空帧是正确的。

**6. 身份修订没有掩盖篡改**
- 修订后的 witness 仍然先校验整文件 SHA-256（第 29–30 行，未改动）。方法源码段、编译执行的 AST 都来自这份已验证的字节。所以方法段摘要只是派生值，不会削弱防篡改能力。
- 修订链一致：
  - `attempt1/witness.py` 摘要 `fa6a2f20` 等于 protocol v1 记录的值。
  - 修订后 `b62fdb3f` 等于 protocol-v2 记录的值，也等于 retry-intent 记录的值。
  - patch 只改了身份校验那两行和输出字段名。
- diagnose 的失败点在 `attempt1/witness.py:38`（方法摘要），没有在第 30 行（整文件摘要）失败。这说明 VM 内的样本字节与固定字节一致。
- 方法源码摘要 `66a025ea…` 和 `7db08475…` 在宿主 3.13 与容器 3.12.15 下相同，从实测上证明了跨版本稳定。

**7. 失败状态保留**
- `analysis.json` 中 `initialAttempt.state` 为 `failed`。两份原始扫描保留，内容与 poll 中的嵌入副本一致。
- cleanup 的白名单很严格：如果 diagnose 或 retry 遗留临时目录，cleanup 会拒绝执行。retry 依赖 scratch 中的 `status.json`，因此在逻辑上必然发生在 cleanup 之前。

---

## 二、条件性发现（需修正或补证据）

**F1（中）自动复核器在结构上不覆盖新规则**
- `eval_evidence_batch.py` 的 `GUARD_RULES` 只包含 `policy.harness.python.{eval,exec,request-to-dynamic-code}`。新规则的 ID `policy.harness.python.dynamic-code-namespace` 会直接被 `continue` 跳过。
- 因此“0 项 guard 检查”与代码内容无关，结果是必然的，不提供任何信息。报告应写明“现有复核器不覆盖该规则 ID”，而不是只写“返回 0 项”。
- 另外两点：
  - `eval_import_review.py` 在任何地方都没有固定摘要。
  - 复核的调用方式（manifest、scanSha256 绑定）没有存档。基线与候选的 review 输出逐字节相同。

**F2（中）预运行工件被事后原位修改**
- `source-provenance.json` 现在含有 `method.sourceSha256` 和 `astDigestRuntime: "3.13.1"`。这些字段只可能在定位根因之后才写入，而且 `witness-retry.py` 选择内联 provenance 而不读文件，也印证了这一点。失败前的原版本没有单独归档，只存在于宿主机的 `input.json` 中，而该文件不在材料里。
- `protocol-v2.json` 的 `createdAt` 原样复制了 v1 的时间戳，掩盖了真实的修订时间。
- 建议：
  - 从 `input.json` 中取出原版 provenance 单独存档，并用 inputSha256 `1422013d…` 核对。
  - 给 v2 填写真实的 `createdAt`，并加上 `supersedes` 字段指向 v1 摘要。
- 这些问题不影响诊断结论，因为整文件摘要没有变化，结论有可靠锚点。

**F3（中）失败路径及后续容器缺少环境不变性核验**
- `worker.py` 在 witness 失败时异常直接上抛，导致以下检查都被跳过：
  - `containerAbsent`（`docker ps`）
  - `rules.json` 与 `images.json` 复核
  - 169 项日常程序复核
- diagnose 和 retry 都只执行 `docker rm -f`，不检查返回码，也不运行 `docker ps`。两者使用同一个容器名。
- `final-vm-state.json` 没有对应的生成脚本、时间戳或调用记录。
- 因此在补交证据之前，报告中“169 项一致”和“临时容器均清理”只能视为已声明、未验证。

**F4（中）工具实际调用的证据不完整**
- 以下文件缺失：
  - `vm-bridge-calls.jsonl`（含每次远程脚本摘要）、`attempt.json`、`submitted.json`、`input.json`、`dataset-digest.json`
  - `security-output.sh`（容器内实际入口，没有固定摘要）
  - 从 scan 生成 run 的转换脚本（例如 `before` 如何映射为 `xinference-before`）
  - freeze 和质量门的实际命令行
- `identity.scanner` 的值 `4730ae28…` 对应不到材料中的任何文件。
- `witness-retry.py` 发送前没有校验内嵌 witness 的摘要，`b62fdb3f` 目前只是 intent 中的声明。
- 最终 `witness.json` 缺少 worker 版本会附带的 `sandboxArgs` 和 `containerAbsent`。

**F5（中，方法）oracle 标签的适用条件**
- 两个样本都标注为 `independent-vulnerability`，且 verified 为 true，所以被计入 qualification 口径，`excludedFromQualification` 为 `[]`。但实际情况是：
  - 它们是定向挑选、非盲、同一 CVE 的相关一对。
  - 阴性样本是同一位置的补丁版本，里面根本没有 2 参数或 3 参数的 `eval`，未命中几乎是必然的。
- 质量门没有字段能表达“定向选择”。如果今后继续往 20 阳性、30 阴性的门槛上累加，这类配对会夸大能力。建议增加 selection 元数据，并把这类样本排除出 qualification，或者至少把一对按 1 个独立单元计算。
- `conditionsVerified` 依赖的公告正文没有存档，没有摘要。`external-content-report` 也只覆盖了两份源码。

**F6（低）阴性标签仅适用于 CWE-95**
- `literal_eval` 消除了代码执行，但没有消除深层嵌套或超大字面量导致的资源耗尽。这超出 CWE-95，但标签说明里应写明“仅限 CWE-95”。
- 补丁方法“无动态帧”的判断依据是 `<string>` 文件名，属于启发式，不是对“不存在 eval”的一般性证明。

**F7（低）见证的适用范围措辞**
- 编译时额外加了 `annotations` future flag，而原 `before.py` 没有。这对方法体语义没有影响，但应披露。namespace 只有 `ast`、`json` 和自动注入的内建函数，`self` 为 `None`。
- 根因诊断在 VM 宿主 Python 3.12.3 上计算 AST，而真正失败的是容器内的 3.12.15，容器侧的 AST 摘要没有记录，结论是按同一次版本推断的。建议在 `analysis.json` 中把“guest 3.12.3”和“witness 3.12.15”分开表述。

**F8（低）扫描结果没有绑定实际扫描的字节**
- 扫描 JSON 里的 `datasetSha256` 只是透传的标签，没有逐文件的摘要。实际扫描字节与固定字节一致，目前只有间接支撑：launch 前的校验，加上 diagnose 时整文件摘要通过。
- 可以离线核对 offset 1466 是否正好对应第 46 行第 20 列。

**F9（低）模型路由无法核实**
- 没有逐步记录实际使用的模型 ID 和 effort。`external-content-report` 中的 reviewer 写的是 `"current Codex agent"`，与“先 Opus 5.5 high，必要时回退 DeepSeek V4.1 Flash high”的规定不一致，或者至少没有说明。
- 本次审查由 `claude-opus-5-5` 完成，但我无法自证 effort 档位，也无法证明其他步骤用了哪个模型。

**F10（低）台账与报告措辞**
- `usageRequired` 要求在任何下一次 freeze 之前登记。草稿写的“外部审查后登记”可以接受，前提是确实在下次 freeze 之前完成，而且失败的 attempt1 与 witness retry 都要作为尝试记录下来。
- 报告标题“普通检查 R3”容易被理解为已获 R3 准入，建议改成“R3 诊断切片（非准入）”。
- “上游许可证一并保留”在材料中找不到对应文件。

---

## 三、范围外（不在本步结论内）

- 完整 API、模型或部署环境下的远程利用，以及资源耗尽类问题。
- CWE-94（本次没有新样本）。
- 总体误报率和召回率。单个补丁文件未报警不能推出误报率为 0，这一点草稿已经正确声明。
- 扫描器准入、部署、发布。
- commit 签名验证。
- 质量门自身的设计问题：列号不参与比对，oracle 的布尔值由提交方自行声明。
- 日常扫描超时和传输故障。

## 四、建议的离线补验（交给有工具的执行者）

1. 对所有工件运行 `sha256sum` 与清单比对，对两份源码运行 `git hash-object`，与 `de87ad7f…` 和 `bba9aa28…` 比对。
2. 从 `witness-retry.py` 中提取内嵌 witness，对其求摘要并与 `b62fdb3f` 比较。
3. 用质量门的 `digest()` 重新计算 dataset、policy、ledger、freeze 的规范化摘要，再用同一组输入重跑质量门。
4. 核对 `before.py` 第 46 行第 20 列的字节偏移是否为 1466。
5. 补齐 F2、F3、F4 列出的缺失工件。

本报告只是对诊断方法和证据边界的审查。它不证明真实漏洞存在，也不构成全产品结论，更不能替代发布或扫描器的准入审查。
