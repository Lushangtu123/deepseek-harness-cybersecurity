# 接口合同修订说明（第 4 轮，零目标预检）

第 3 轮 `CONTRACTS-REV3.md` 与本文件并存；第 2 轮 `CONTRACTS.json` 的既有字段语义不变。
本轮只修订文件链、生命周期、清理、预检与治理绑定，不改变四个夹具或 16 项预期。

## 1. 所有回执链接统一使用“落盘文件字节摘要”

- `expectedSha256`、`bindingSha256`、`observationSha256`、`observationRawSha256`、
  `observerSha256`、`verificationSha256`、`bindSha256`、`layoutSha256` 都是对**实际写入磁盘的
  文件字节**计算的 SHA-256。
- 规范化 JSON 摘要仍用于结构、binding core 与 `bindingId`：
  - `structure.structure_digest(x)` 保留独立含义；
  - `bindingId = structure.digest(bindingCore)`，不参与文件字节链的替代。
- 首次编译分支写出 `prepare/compile-NNNN/expected.json` 后，运行器立即重新读回文件并记录
  读回字节摘要；复用分支读取同一文件并记录同一摘要。任何 canonical-JSON 摘要都不能冒充
  `expectedSha256`。
- `REPORT.md` 中给出的 `protocolManifestSha256` 由最终 `protocol-manifest.json` 字节计算。

## 2. `state/attempt-NNNN.json` 新增生命周期字段

| 字段 | 含义 |
|---|---|
| `resourceIntent` | 创建容器**之前**落盘：随机 `tag`、容器名、镜像、entrypoint、interactive、挂载、env 键、stage 路径与 `(dev,ino)`、config/launcher 摘要 |
| `containerId` / `containerCreated` | 创建后从 `docker inspect --type container` 读到的**完整 ID**；仅表示资源存在，不表示目标执行 |
| `stageIdentity` | `lstat` 得到的 stage 目录 `(dev, ino, mode)`；链接或身份改变时不删除 |
| `processes.client` / `processes.observer` | `(pid, pgid, starttime, bootId, groupLeader)`；用于恢复时重新查询原进程组 |
| `goState` | `not-attempted` / `writing` / `sent` / `write-unknown`；只有 `sent` 之后观察到的客户端退出才算执行证据 |
| `executionState` | `not-started` / `observed` / `timeout` / `unknown`；`targetExecutions=1` 只在 `goState=sent` 且观察到目标退出时写入 |
| `observerStop` / `observerEnd` | 优雅停止结果与 END 完整性（缺失、重复、truncated、END 后尾随记录） |
| `checkpoints[]` | `reserved`、`prepared`、`staged`、`created`、`client-started`、`observer-started`、`armed`、`go-sent`、`observed`、`failed` 等可恢复步骤；不再只存布尔标记 |
| `cleanup` | 重新查询后的容器/客户端/观察器/stage 事实与 `confirmed` |

## 3. `zero-target-preflight` 回执与许可

### 3.1 预检许可 `codex-review/preflight-admission.json`

```json
{
  "kind": "zero-target-preflight-admission",
  "state": "approved",
  "allowedCommand": "preflight",
  "maxTargetExecutions": 0,
  "fixturesImported": 0,
  "protocolManifestSha256": "<manifest bytes sha256>",
  "sourceReviewReceiptSha256": "<completed review bytes sha256>"
}
```

预检许可**不**要求、不读取、不写入正式 `experiment-admission.json`，因此权限路径不循环。

### 3.2 预检回执 `preflight/preflight-receipt.json`

```json
{
  "kind": "zero-target-preflight-receipt",
  "state": "accepted",
  "protocolManifestSha256": "<sha256>",
  "preflightLicenseSha256": "<sha256>",
  "sourceReviewReceiptSha256": "<sha256>",
  "imageId": "sha256:9479bc40...",
  "pythonVersion": "3.12.15",
  "entrypoint": "/usr/bin/python3.12",
  "interactive": true,
  "network": "none",
  "nonRoot": true,
  "toolDigests": {"preflight_selfcheck.py": "<sha256>", "...": "<sha256>"},
  "runtime": {"interpreterSha256": "<sha256>", "librarySha256": "<sha256>"},
  "observation": {
    "complete": true,
    "events": 1,
    "rawSha256": "<raw bpftrace bytes>",
    "observerSha256": "<rendered template bytes>",
    "intZero": true,
    "callerOffsetVerified": true,
    "structureVerified": true,
    "endComplete": true
  },
  "cleanup": {"confirmed": true, "container": {}, "client": {}, "observer": {}, "stage": {}},
  "targetExecutions": 0,
  "fixturesImported": 0,
  "realContainers": 1
}
```

`targetExecutions` 指实验目标；预检容器内的固定自检不计入。预检固定挂载只有
`/review/preflight`，其中只有 `preflight_selfcheck.py`、`layout_probe.py`、`structure.py`、
`observer_template.bt`，不得包含夹具、计划、`target_launcher.py` 或
`experiment_compile.py`。

### 3.3 正式许可新增绑定

`codex-review/experiment-admission.json` 新增：

| 字段 | 含义 |
|---|---|
| `preflightReceiptSha256` | 实际预检回执文件字节摘要 |
| `sourceReviewReceiptSha256` | 已完成源码审查回执文件字节摘要 |

运行时在创建任何资源之前拒绝 missing / tampered / cross-run（清单不同）预检回执或审查回执。

## 4. `expected.json` 的语法拒绝字段

- `payloadSyntax`：`valid` / `syntax-error` / `other-error` / `not-applicable`。
  - data 行按夹具实际行为编译 `str("<payload>")`；
  - computation 行编译原始 payload；
  - echo 行不编译动态程序，记 `not-applicable`。
- `syntaxRejectExpected`：仅当 data 行的**包装后源码**真实抛出 `SyntaxError` 且
  `dataBaseline is None` 时为 `true`。
- judge 的 Q4 判定必须同时满足：固定编译器对真实包装数据抛出明确 `SyntaxError`、目标真实退出 3、
  完整零事件、调用点/来源/摘要链一致。仅结构不支持、`ValueError` 等其他异常或普通零事件
  → `no-dynamic-event`，不得记 `syntax-reject`。

## 5. 观察器与清理

- `docker create` 必须显式 `--interactive`、`--entrypoint /usr/bin/python3.12`、`--label sce.tag=...`；
  `docker start -a -i <full-id>`。
- 观察器由 runner 在目标退出后发送 SIGINT；有时限地 TERM/KILL。END 前 `clear(@events)`，
  END 后不允许任何非空记录；否则 observation 为 invalid/unknown。
- 同名容器在创建前查询；存在即拒绝（`container-name-conflict`），绝不 `rm` 后重建。
- 删除容器前核对完整 ID、名称、`sce.tag`、镜像；查询失败、同名换 ID、标签不符 → 不删除不释放。
- 进程组按 `(pgid, leader starttime)` 核对；PID 复用、非组长、孤儿组 → unknown，不发送信号不释放。
- stage 按 `lstat` 的 `(dev, ino)` 核对；路径是链接、身份改变、树内出现链接 → 不删除不释放。
- 只有容器查询成功且无匹配、客户端进程组退出、观察器进程组退出、stage 经 `lstat` 证实不存在，
  才 `cleanup.confirmed=true`。语义 `unknown` 在清理确认后正常结算并释放预留。
