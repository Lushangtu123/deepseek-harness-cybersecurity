# 接口合同修订说明（第 3 轮，附加字段）

第 2 轮 `CONTRACTS.json` 原字节保留在 `prior/CONTRACTS.json`，本文件只记录本轮**新增的字段**，
不改变既有字段语义。既有字段的形状、摘要算法和校验顺序仍以 `CONTRACTS.json` 为准。

## 1. `prepare/bind/bind.json` — 每个 fixture 结果新增 `callerCandidates`

```json
{
  "callerCandidates": [
    {"qualname": "compute", "firstlineno": 12, "callerSha256": "<sha256>"},
    {"qualname": "beta",    "firstlineno": 18, "callerSha256": "<sha256>"}
  ]
}
```

- 内容：该 fixture 全部编译出的 code object 的 caller descriptor 摘要，按 `(firstlineno, qualname)` 排序。
- 作用：judge 只有在观察到的 caller 命中**未绑定候选**时才能给出 `excluded/caller-identity-mismatch`；
  命中不了任何候选 → `unknown/caller-attribution-unverified`。
- 来源：`tools/experiment_compile.py` 在 bind 阶段用 `structure.caller_descriptor` 纯编译推导，不导入 fixture。
- 兼容性：旧回执缺少该字段时，judge 把“caller 不匹配”一律判为 `unknown`（不会退回旧行为）。

## 2. `runs/NNNN/observation.json` — 新增观测身份

```json
{"targetPid": 4242, "targetUid": 65534}
```

- 由 runner 传给 collector（`--target-pid/--target-uid`），judge 要求与 attempt 记录一致。
- 这两个值同时出现在渲染后模板的过滤条件里（`/proc/<pid>/`、`pid != <pid>`、`uid != <uid>`），
  judge 逐字校验，防止把别的进程的事件当成目标事件。

## 3. `state/attempt-NNNN.json` — 新增字段

| 字段 | 含义 |
|---|---|
| `budget` | 预留时写入的预算快照（`maxAttempts`、`usedAfterReserve`、`admissionBudget`） |
| `resourceIdentity` | 创建容器**之前**写入：容器名、镜像、挂载清单（含 `readonly`）、env 键、stage 路径、config/launcher 摘要 |
| `containerId` | 创建后从 `docker inspect` 读到的容器 ID（用于归属确认） |
| `observerStopped` / `clientExited` / `stageDir` | 结算前置条件的事实来源 |
| `settled` | 清理确认后置 true；语义 `unknown` 也会置 true（预留释放） |

## 4. `verdict`（`runs/NNNN/verification.json`）— 版本 2

新增 `digestChecks`（6 项摘要链布尔值）、`identityChecks`（镜像/解释器/库/pid/uid）、
`derived`（纯事件推导结果）、`frozenExpectation`（冻结事件数/退出码/原因）。
`decision`/`reason` 语义不变；`unknown` 时 `derived` 仍保留推导细节，便于人工复核。

## 5. runner 命令面

`status`、`query`、`cleanup`（等价 `recover`）、`recover`、`prepare-layout`、`prepare-bind`、
`compile --attempt N`、`run --attempt N`。`recover` 只查询并清理原 attempt，不重放目标。
