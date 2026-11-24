# Python 执行点定位与冻结绑定

离线候选；日常 VM 未部署。定位表示源码中存在对应语法，不表示内建函数身份、外部可控、可达性或漏洞已确认。动态沙箱核实、独立留出盲测和日常交付仍是后续阶段。

## 坐标与身份

统一使用 UTF-8 字节坐标：`line/col` 从 1 开始，`offset` 从 0 开始，结束位置不含。原始 LF/CRLF 字节保留。Python AST 的列偏移按字节解释，见 [Python 3.12 AST](https://docs.python.org/3.12/library/ast.html#ast.AST)。

支持 `eval(...)`、`exec(...)`、`builtins.eval(...)` 和 `builtins.exec(...)` 的语法位置。别名及动态属性不推断。每个位置包含：

- `sourceSha256`、`callee`、完整 `call` 范围、首个位置参数的 `argument` 范围；不支持的首参为 `null`。
- `id = SHA256(canonicalJSON({sourceSha256, callee, call}))`。规范 JSON 按键排序、紧凑编码。ID 按调用派生，首参另由完整清单摘要绑定。规则和文件别名不进入 ID。
- `builtinIdentity: unverified`。同一调用的多规则命中共用 ID，同一行不同调用具有不同 ID。

扫描器原范围保存在 `scannerSpan`，不会改写成 AST 范围。完整调用规则关联包含的唯一调用；参数聚焦规则可关联完全一致的首参范围。范围存在多个支持的执行点（包括混合 eval/exec 和嵌套）时保留歧义，不按规则猜选。位置缺失、UTF-8 字符内部坐标、错误规则等保留未匹配原因。跨文件结构观察分别记录调用端和执行点身份。

## 定位、复核和恢复

`scripts/reviewer_snapshot.py` 的快照仍为 v2，复核器仍是现有三模块；存储模块是工具自身的受信代码。不得从项目或输入清单导入执行模块。

在 Linux VM 普通用户中运行，镜像必须使用已有固定内容摘要：

```sh
python3 -I -B scripts/reviewer_snapshot.py freeze REVIEWER_MODULES SNAPSHOT IMAGE_ID
python3 -I -B scripts/reviewer_snapshot.py locations SNAPSHOT SNAPSHOT_SHA SOURCE_ROOT FILE_MANIFEST --attempts-root PRIVATE_ATTEMPTS
python3 -I -B scripts/reviewer_snapshot.py run SNAPSHOT SNAPSHOT_SHA SOURCE_ROOT REVIEW_MANIFEST SCAN_JSON DATASET_SHA FREEZE_SHA --attempts-root PRIVATE_ATTEMPTS
python3 -I -B scripts/reviewer_snapshot.py status ORIGINAL_ATTEMPT
python3 -I -B scripts/reviewer_snapshot.py recover ORIGINAL_ATTEMPT
```

`FILE_MANIFEST.files` 是 ASCII 相对 Python 路径到源码 SHA-256 的映射。`locations` 内部生成空扫描；可传入旧 `locationBinding` 要求一致性核对。新生成的结果包含 `locationBinding`：固定源码清单、解析器版本、协议、镜像、执行 UID 和复核快照摘要。

正式复核输入 `REVIEW_MANIFEST` 包含原有 `files/scanSha256`，以及之前的完整 `locationBinding`。运行会重新计算定位并逐字节身份比较，变化时拒绝完成并要求重新冻结。复核必须提供原始扫描文件，不能以空扫描替代。新报告版本为 2，完成回执版本为 3，显式区分 `operation: locations/review`。定位回执不能充当复核回执。

`locations` 复用容量准入、锁、禁网只读容器、限时、清理及原任务恢复。已完成任务只返回原结果，不重复分析。不要因客户端断线盲目提交新任务。

## 精确评估 v3

数据集、冻结及运行版本为 3；质量报告为 7。执行点样本包含 `path/sourceSha256/pointId/location`，其中 `location.line/column` 是完整调用起点。无执行点的阴性文件使用 `pointId: null, location: null`，且定位清单必须证明该文件没有支持的执行点。同一执行点在数据集中只出现一次。

冻结入口多接收定位结果数组（`locations` 原始完成结果可直接组成数组）：

```sh
node scripts/review_quality_gate.mjs --freeze DATASET POLICY IDENTITY LEDGER SNAPSHOT_JSON LOCATION_EXECUTIONS
node scripts/review_quality_gate.mjs DATASET RUN FREEZE POLICY LEDGER
```

每个完成复核结果提供 `reviewerExecution` 和 `reviewArtifact`。构建 `RUN.reviewerExecutions` 与对应的 `RUN.reviewArtifacts` 数组时，保留同一索引顺序，使用这些原始对象。`reviewArtifact` 内含原始 `scanJson/manifestJson/reportJson` 和 `locationBinding`，不重新格式化。评分会核对实际摘要、源文件集合、冻结身份、逐命中位置及确定性映射，不能仅凭声明的 `raw: hit` 得分。

同一执行点跨规则命中在原始扫描中全部保留，计分只算一次。报告的 `executionPoints` 提供逐例 ID、源摘要、位置和实际映射汇总。解析失败、未覆盖、超时或位置未知保持未知。确认/排除仍需要单独的核实证据；定位和结构观察不提高证据等级。

## 兼容与上限

- 历史 v2 评估输入继续输出诊断指标；即使指标满足，也只返回 `diagnostic-only`，不作为新精确正式评估。现有阻断仍保留。
- 历史行号扫描可以读取；没有精确 ID 的观察不得借用其他调用的证据。
- 单批最多 64 个文件、8 MiB 源码、每文件 1 MiB、每文件最多 64 个支持的执行点、扫描最多 2000 条。报告/适配器输出上限 2 MiB，超限降级为不可用，不产生确认结论。
- 每个源文件在一次精确评估中对应一个定位批次和一个复核批次；重复覆盖会阻断，避免选择性拼接证据。
- 清单和回执是内容绑定和本机完成记录，不是发布者签名或外部封印。Docker、VM 内核、受信启动器及固定复核器仍在信任边界内。


## 本轮验收

[结构化结果](python-execution-locations-results.json) · [逐轮审查](python-execution-locations-reviews.json)。范围内外部复审已完成；Claude 周额度失败后按既定授权使用 DeepSeek V4.1 Flash high，原始材料摘要和回执均保留。

四个已用诊断文件与合成边界固定在 VM 中运行：14 条原始命中完整保留，13 条关联、1 条嵌套歧义未知，归入 8 个唯一命中执行点。本机与 VM 的 v7 评分逐项一致；固定镜像的 8 项边界测试通过。原任务查询和恢复不重放分析。日常 169 个程序文件、42 个数据库逻辑内容及配置/runtime 摘要前后一致。

本轮没有使用新留出样本，未确认新的项目漏洞，未部署日常 VM，未推送 GitHub。复审另发现现有 PentAGI 缺失调用次数显示为零的准确性问题，已记为后续待办；本轮不宣称已修复。普通检查 R3 仍阻断。
