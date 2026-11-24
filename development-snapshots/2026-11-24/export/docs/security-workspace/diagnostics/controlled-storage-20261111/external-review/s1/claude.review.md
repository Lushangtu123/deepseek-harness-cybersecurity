# S1 只读审查结论：存储模块加入快照 v2 闭包

**结论：在本步范围内（身份/版本兼容、受信代码加载、Node 门槛回归）没有发现阻断问题。** 以下全部是基于所给源码和差异的静态推演，没有运行代码，不构成真实漏洞确认。R3 仍未放行，S4 的隔离 VM 端到端验证仍需完成。

## 已核对符合要求的点

- **`verify` 存储检查**：同时校验三项：
  - `manifest.storageSha256` 等于安装字节的摘要；
  - bundle 内的存储字节等于安装字节；
  - 字段是格式合法的哈希字符串。

  检查顺序是：launcher → storage → reviewer 文件，失败即拒绝。存储模块缺失时抛 `FileNotFoundError`，此时还没创建 attempt 目录，属于 fail-closed。
- **`storage_module` 加载**：
  - 只从 `Path(__file__).resolve()` 的同级读取；
  - 有 `read()` 的 canonical 检查和 `O_NOFOLLOW` 防护；
  - 只读一次，同一个 `raw` 先比对摘要，再 `compile`/`exec`，没有 TOCTOU；
  - `expected` 只用于和安装字节比对，所以即使调用方传入 bundle 提供的值，也只可能执行安装的代码。
- **存储模块不进容器**：`execute` 只暂存 `FILES`，没有 `reviewer_storage.py`。`imports()` 的白名单不含 `reviewer_storage`，reviewer 模块无法 import 它。
- **项目代码不会被执行**：bundle 内的存储副本只做字节比对，没有任何路径会执行 bundle 或项目指定的代码。
- **v1 快照**：Python 侧会拒绝执行。Node 侧 `freezeReviewInputs` 要求 `version===2`，评估时保留 v1 的历史分析，同时新增 `reviewer-snapshot-legacy-storage-unbound`。身份不符阻断与 legacy 阻断并存，已修复原来 `else if` 互斥导致的问题。
- **跨语言摘要一致**：Python `digest` 与 Node `canonical` 对新键集合（全 ASCII 键，十六进制值）的排序和序列化结果一致。
- **兼容性**：`status`/`recover` 不调用 `verify`，旧 attempt 在升级后或安装不完整时仍可查询和恢复。回执 v2 不变；`snapshotSha256` 通过 manifest 摘要间接绑定了 storage。

## 非阻断问题

### N1：Python 侧 legacy 诊断先于身份校验（低）
- **触发**：bundle 只有 3 个文件加 `snapshot.json`，且 `version==1`，同时调用方给的 `expected` 也不匹配。
- **影响**：报错是 `legacy snapshot…`，不是 `snapshot digest mismatch`。两者都会拒绝，不影响安全，但身份不符的诊断被掩盖了，和 Node 侧"两种阻断并存"的语义不一致。另外，v1 manifest 如果同时带有存储文件，会落到 `invalid snapshot manifest`，而不是 legacy 提示。
- **建议**：可以先做摘要比对，再给 legacy 提示；也可以在消息里同时注明摘要是否匹配。

### N2：v6 报告语义变化但版本号未变（低，决策项）
- **触发**：同一份基于 v1 快照的历史 freeze/run 输入。
- **影响**：以前可能得到 `eligible-for-release-review`，现在得到 `blocked`，并多出一个新的 blocker 字符串，但报告仍标为 `version:6`。只看版本号的消费方无法区分新旧语义。
- **建议**：这符合本步目标，不必改版本，但应在变更记录中写明"v6 自 S1 起对 v1 快照新增 legacy 阻断"。另外 `definitions.reviewerValidation` 没有提到 storage 绑定，建议补一句。

### N3：Node 测试没有覆盖 `storageSha256` 变动（低）
- **触发**：`review-quality-gate.test.mjs:192` 只遍历 files、`imageId`、`launcherSha256`。
- **影响**：按逻辑，`digest` 已覆盖该字段，所以行为正确，只是缺少回归保护。
- **建议**：把 `storageSha256` 加入字段列表。再补一个用例：v2 快照格式合法、但 `identity.reviewer` 不符时，`freezeReviewInputs` 应抛错。现有的 "New freezes reject a reviewer identity that disagrees…" 用例传的是 `{version:1}`，实际只测了结构非法，没有测到身份不符。

### N4：Python 测试的覆盖缺口与命名（低）
- `test_rebound_bundle_storage_is_rejected_without_execution`（约第 1101 行）里"未执行"的断言是空断言，因为 `verify` 本来就没有任何执行路径。
- 缺少 `storage_module` 的负向测试：错误或格式非法的 `expected`、安装文件是符号链接、摘要不符时不执行。可以用 patch `read` 返回写标记文件的字节来验证 `exec` 前就拒绝。
- 缺少以下用例：
  - bundle 存储字节被篡改但 manifest 不变；
  - 已安装存储在 freeze 之后漂移；
  - 安装缺少 `reviewer_storage.py`；
  - v2 形态的 manifest 里写 `version:1`（int）或 `version:3`。
- `test_snapshot_version_requires_integer_one` 现在测的是 v2，函数名已经过时。

### N5：后续步骤的约束（提示，本步不适用）
- 等 `reviewer_storage.py` 有了真正的代码：它在控制器进程内以控制器权限运行，不受 `imports()` 闭包约束。到时应为它加 import 闭包检查，或确认启动器以 `-I` 运行。
- 调用方应传入已经 `verify` 过的 `manifest['storageSha256']`，而不是现场重新计算的摘要。这样可以保证执行的字节和快照身份一致。
- 升级 `reviewer_storage.py` 会让所有现有 v2 快照失效（和 launcher 行为相同），属于预期，但需要写进运维文档。

## 范围外 / 未确认

- 归档、容量、回收等功能还没有实现。存储模块里的常量不算已交付的功能。
- Docker、VM 内核和真实部署环境没有验证，需要等到 S4。
