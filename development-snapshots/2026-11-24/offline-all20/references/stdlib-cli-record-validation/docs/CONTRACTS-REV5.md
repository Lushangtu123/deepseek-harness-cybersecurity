# 接口合同修订说明（第 5 轮，预检证据链与资源清理）

第 3 轮 `CONTRACTS-REV3.md`、第 4 轮 `CONTRACTS-REV4.md` 与本文件并存；既有字段语义不变。
本轮只修订预检许可/证据、布局字节绑定、观察器重建、资源生命周期与清理门控，不改变四个
夹具、16 项预期、源码 `pointId` 或运行 `bindingId` 的含义。

## 1. 预检许可、锁与一次性登记

`codex-review/preflight-admission.json` 新增/固定字段：

| 字段 | 含义 |
|---|---|
| `protocolRevision` | 固定为 `2` |
| `preflightId` | 32–64 位小写十六进制，唯一标识**一次**预检 |
| `protocolManifestSha256` | 候选 `protocol-manifest.json` 实际字节摘要 |
| `candidateManifestSha256` | 与上一字段相同；显式命名候选清单绑定 |
| `sourceReviewReceiptSha256` | 已完成源码审查回执实际字节摘要 |
| `allowedCommand` | 只能是 `preflight` |
| `maxTargetExecutions` / `fixturesImported` | 均为 `0` |

预检执行顺序（失败即阻断，不得回退到旧证据）：

1. 校验候选清单、许可、审查、封存 `observer-profile.lock.json`；
2. 获取固定路径 `preflight/.preflight.lock` 的**稳定独占 flock**；锁文件永不删除；
3. 在 `preflight/claims/<preflightId>.json` 以 `O_EXCL` 写入一次性 `consumed` 登记；
4. 创建 `preflight/evidence/<preflightId>/` 受控独立目录；
5. 之后才创建 stage、容器或进程。

同一许可再次执行、并发执行、断线后重试均拒绝：并发得到 `preflight-locked`，已消耗得到
`preflight-license-consumed`。未知结果用只读命令查询原 ID：

```text
tools/zero_target_preflight.py status --preflight-id <preflightId>
```

`status` 不创建目录、不获取写锁、不启动资源；`consumed` 但无 completed 记录时返回
`unknown-outcome`。

## 2. 单次证据与独立复算

- 该次调用的 `observer.raw`、`observer.bt`、`preflight-config.json`、`observation.json`、
  `layout.json`、`preflight-receipt.json`、失败记录均由该次调用以 `O_EXCL` **新建**，
  不覆写旧文件；同一预检 ID 的目录只能创建一次。
- 采集器退出码必须为 `0`，且必须在本次目录中新生成 observation；绝不读取共享或旧的
  `observation.json`。
- `tools/observation_pure.py` 是唯一受信解析函数。`collect_observer.py`、预检、正式 runner
  与 judge 均从本次 raw 字节复算；不得用 JSON 中的 `complete`/`accepted` 布尔值替代复算。
- 复算必须核对：唯一 `BEGIN`/`END`、END 为最后非空记录、`run=preflight`、本次 `tag`、
  预检 `preflightId`、固定 caller 路径与 `callOffset`、固定 `callerSha256`、整数零
  `{"t":"int","v":0}`、期望结构与代码摘要、恰好 1 个事件、END 的 `events=` 一致。
- 观察器必须由 runner 在目标退出后以 `SIGINT` 优雅停止并实际退出；TERM/KILL 升级、
  提前退出/丢失、流截断、drain 未完成、raw 读错、采集器失败均阻断，即使残留记录看似正常。
- 正式 runner 的 `verify_preflight_receipt` 与 judge 的 `verify_governance` 复用
  `tools/preflight_verify.py` 的同一独立验证函数，并重新读取 raw、layout、template、
  profile、claim、license、review、manifest。

## 3. 布局字节与封存运行身份

- 预检实测布局写入 `preflight/evidence/<preflightId>/layout.json`，只创建一次。
- `layoutSha256` 是**该文件实际字节**的 SHA-256；`layoutStructureSha256` 是布局结构的
  规范化摘要；两者语义分离。
- 布局文件绑定 `preflightId`、候选清单、固定镜像、解释器与库摘要、`profileSha256`。
- 封存 `tools/observer-profile.lock.json` 固定运行身份；比较的是实际字符串值
  （`imageId`、`pythonVersion`、`interpreterSha256`、`librarySha256` 等），不是“哈希形状”。
- 正式 `prepare-layout` 只验证并**使用预检回执所选字节**，不再重新测量或替换；
  已存在的 `prepare/layout/layout.json` 只有字节相同才可复用。
- bind、compile、render、judge 均重新核对布局字节摘要、布局结构摘要、模板字节摘要、
  profile 摘要与预检回执。改布局、改模板、错运行身份在创建 stage/容器前拒绝。
- judge 使用冻结模板字节和已核验布局**重建实际观察器字节**并与 `observer.bt` 精确比较。
- 旧协议回执保留在 `baseline/` 作为历史证据；新代码要求 `protocolRevision=2`，旧格式
  回执不能通过。

## 4. 统一资源意图与三态清理

预检、准备工具容器和正式 attempt 共用 `tools/resource_guard.py`：

- 创建资源前登记意图：随机 `tag`、容器名、镜像、entrypoint、interactive、挂载、env 键、
  stage 计划路径与 `(dev,ino)`、各进程 `spawnState`；
- spawn 前写 `spawn-attempted`；成功后写完整 `pid` 与 `(pgid, starttime, bootId,
  groupLeader)`；没有身份的已尝试 spawn 永久保持 `unknown`，不得视为已退出；
- 进程三态：`alive` / `exited` / `unknown`。只有明确 `not-started`，或成功查询证明
  PID 不存在/僵尸/整组成功空扫描，才算 `exited`；权限错误、畸形 stat、PID/进程组身份
  变化、leader 复用、孤儿组均为 `unknown`，不发信号、不释放预留；
- 删除只允许核验**完整 ID + 精确名称 + `sce.tag` + 固定镜像**的本任务容器；绝不按名称
  删除同名异属容器；
- 结算前必须用三次**成功**查询证明完整 ID、精确名称、归属标签均无匹配；确认所有已记录
  客户端/观察器退出后，才移除身份一致的 stage，并以 `lstat` 确认消失；
- 路径身份变化、链接、树内链接、残留、查询失败均保留 stage 与预留；
- `recover`/`cleanup` 只处理原 attempt 记录，不重启目标、不重放。

## 5. 判定与测试

- 判定顺序不变：文件字节摘要链 → 治理链 → 身份 → observation 完整性 → 先由实际事件推导 →
  再与冻结事件数/退出码/decision/reason 比较。
- 结构摘要、源码 `pointId`、运行 `bindingId` 的含义不变；`layoutSha256` 改为文件字节，
  另设 `layoutStructureSha256` 保留结构含义。
- `checks/repro_before.py` 先对冻结基线复现四类阻断；`checks/run_regressions.py` 在同一
  记录 shim 条件下验证修复后的具体拒绝原因与副作用。
- 所有模拟结果均标注 `simulated=true`，不得从假回执推导真机通过；`targetExecutions=0`、
  `fixturesImported=0`、`realContainers=0`。
