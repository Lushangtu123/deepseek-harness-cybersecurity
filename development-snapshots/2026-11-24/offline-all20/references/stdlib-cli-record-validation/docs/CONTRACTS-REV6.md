# 接口合同修订说明（第 6 轮，资源记录与独立证据校验）

第 3、4、5 轮合同 `CONTRACTS-REV3.md`、`CONTRACTS-REV4.md`、`CONTRACTS-REV5.md`
与本文件并存。既有字段语义、四个夹具、16 项预期、源码 `pointId` 与运行
`bindingId` 均不变；本轮只修订预检资源生命周期、恢复入口、独立证据绑定和协议版本。
旧协议材料（`baseline/` 内的轮次）只作历史诊断，不能通过新校验。

## 1. protocolRevision=3

新许可、claim、预检日志、回执、布局、配置和恢复记录统一：

| 字段 | 值 |
|---|---|
| `protocolRevision` | `3` |
| 新文档 `version` | `3` |
| 旧 `protocolRevision=2` 材料 | 仅历史诊断，校验拒绝 |

新准入要求完整的新版证据。新增证据摘要写入回执：

- `preflightIntentSha256`
- `stageIntentSha256`、`stageStartedSha256`、`stageCreatedSha256`
- `containerIntentSha256`、`containerCreatedSha256`、`containerPidSha256`
- `processClientIntentSha256`、`processClientIdentitySha256`
- `processObserverIntentSha256`、`processObserverIdentitySha256`
- `cleanupSha256`
- `frozenTemplateSha256`（冻结模板字节摘要；`observerTemplateSha256` 仍表示实际
  `observer.bt` 字节摘要）
- `evidenceDigests`：上述证据文件名的字节摘要映射

`checks/regression_lib.py` 的模拟许可与正式 admission 同步为 `protocolRevision=3`。
`experiment_runner.py` 与 `judge.py` 继续只调用
`preflight_verify.verify_preflight_evidence` 这一个共享校验入口。

## 2. 外层资源上下文与“先意图、后创建”

外层预检在创建任何资源前持有唯一资源上下文，包含 stage、container、client、
observer 四条记录。顺序固定为：

1. 持久化创建意图（`preflight-intent.json`、`stage-intent.json`、
   `container-intent.json`、`process-<role>-intent.json`）；
2. 执行创建/启动；
3. 创建/启动返回后，**先**把句柄或身份写入共享上下文；
4. **再**做可能失败的身份日志 I/O（`stage-started.json`、
   `container-created.json`、`process-<role>-identity.json`、`container-pid.json`）。

因此外层不再依赖函数“成功返回元组”才知道资源已存在。以下情况一律保守：

- 身份日志写入或目录 `fsync` 失败：记录 `persistFailure`，资源保持未知，
  不生成通过回执，也不生成清理确认；
- 进程身份读取失败：`spawnState=unknown`，不视为从未启动，不发信号；
- 容器创建返回非零或返回零但缺少完整 ID：`create-result-unknown`，按名称/标签
  查询；只有名称与 `sce.tag` 两次成功查询都为空才可记为 `not-created`；
- `stage` 部分构建失败：`stageBuildState=partial`，`stage-identity` 在目录建立后
  立即持久化；清理保留该 stage，恢复入口可在资源证明清除后按原身份处理。

`persistFailure` 存在时 `cleanup.confirmed` 必为 `false`，stage 状态为
`persistence-failed`，不得写出 accepted receipt。

## 3. 许可顺序与中断语义

持稳定独占锁时：

1. 以 `O_EXCL` 写入 `preflight/claims/<preflightId>.json` 并同步（含目录 `fsync`）；
2. 再创建本次 `preflight/evidence/<preflightId>/`；
3. 再创建 stage、容器和进程。

`preflight/claims/` 控制目录的建立属于登记设施。已存在 evidence 但缺少 claim 的
旧目录以 `preflight-evidence-untracked` 拒绝，不自动补成成功，也不消费许可。

- claim 已写、目录未建：`status` 返回 `unknown-outcome`，恢复入口按原 ID 只读查询；
- claim 已写、无完成标记：`unknown-outcome`；
- 完成回执写成、`<id>.completed.json` 未写成：预检返回非零，保存
  `completion-failure.json`，`status` 仍为 `unknown-outcome`；恢复只保存资源清理
  结果，不能伪造实机通过。

## 4. `recover --preflight-id <id>`

保留 `preflight` 与 `status`，新增恢复入口。恢复入口：

- 使用同一个稳定独占锁；锁忙返回非零并输出 `state=locked`；
- 先核对冻结清单、许可、源码审查、封存 profile 和原 claim，不能绕过原冻结材料；
- 只查询/清理原 `preflightId` 记录的资源，不重放自检，不启动容器、bpftrace 或目标；
- 容器先核对完整 64 位 ID、精确名称、`sce.tag` 和固定镜像，再用三次成功查询证明
  完整 ID、名称、标签均无匹配；
- 进程先核对 `pid/pgid/starttime/bootId/groupLeader`；身份缺失、不可读、损坏 stat、
  starttime 变化或无法证明时不发信号；
- 只有容器证明退出、client/observer 均证明退出后，才按 `(dev,ino)` 身份移除 stage，
  并以 `lstat` 复查消失；
- 权限错误、损坏、链接/悬空链接、同名替换、路径身份变化、锁忙、写日志失败或无法
  证明时保持 `incomplete`；
- 恢复记录以 `recovery-<随机>.json` 新文件保存，绝不修改旧回执；
- 即使资源全部清除，恢复记录也只写 `state=resources-cleared`、
  `cleanupConfirmed=true`、`realMachinePass=false`、`receiptAccepted=false`。

`status` 额外只读列出该 ID 的恢复记录（`recoveries`），不创建目录、不加写锁。

## 5. 独立证据校验

`preflight_verify.verify_preflight_evidence` 现在：

1. 从冻结 `tools/observer_template.bt`、已核验 `layout.json` 实际字节、profile、
   `run=preflight`、tag、固定 caller 路径/`callOffset`、`targetPid`/`targetUid` 调用
   现有 `observer_render.render`，与实际 `observer.bt` **逐字节**比较；仅同步修改回执
   摘要不能通过；
2. 读取并核对 `preflight-intent`、`stage-intent`、`stage-started`、`stage-created`、
   `container-intent`、`container-created`、`container-pid`、
   `process-client-intent/identity`、`process-observer-intent/identity`、`cleanup`；
3. 核对归属：intent 的 tag/名称/镜像/挂载与 stage、容器、进程一致；容器 ID、名称、
   `sce.tag`、固定镜像一致；client 的 `docker start -a -i <完整ID>` 一致；observer 的
   `bpftrace -q <本次 observer.bt>` 一致；
4. 核对时序：intent → stage-intent → stage-started → stage-created →
   container-intent → container-created → client-intent → client-identity →
   container-pid → observer-intent → observer-identity → cleanup → receipt 的
   ISO 时间非递减；
5. 从 `cleanup.json` 重新推导 `confirmed`：容器清理结果含清理前身份查询和清理后
   ID/名称/标签三次成功空查询；client/observer 为 `exited` 且身份等于身份日志；
   stage 身份等于 stage-created 身份、`lstatAfter=absent`、状态为 removed/absent；
   再要求回执 `cleanup` 与 `cleanup.json` 的 cleanup 完全一致；不信任单个布尔摘要；
6. 继续从本次 `observer.raw` 重新解析 observation，要求整数零、唯一完整
   BEGIN/END、END 为最后记录、事件数和结构摘要一致。

`container-pid.json` 保存有界查询原文（`returncode`、`stdout`、`stderr` 截断）和
`targetPid`；独立校验重新解析 stdout 并要求其等于回执 `targetPid`、事件 target pid
和观察器重建 pid。创建查询同样保存有界原文，并核对最后一行等于完整容器 ID。

## 6. 错误合同

`expectedStructure`、`frameOffsets`、layout offsets 等嵌套配置的缺失、类型错误、
畸形常量或越界偏移，必须在 `preflight_verify` 中转换为明确的
`PreflightError("config-...")`，在预检中转换为 `PreflightFailure("preflight-...")`；
runner 将其映射为合同内非零退出。不得泄漏未处理的 `KeyError`、`AttributeError`、
`TypeError` 或 traceback。

## 7. 测试与历史证据

- `checks/repro_v6.py --all`：在 `checks/tmp` 内对冻结 baseline 复现启动进程后身份
  写失败、容器创建后写记录失败、部分 stage 失败和目录 `fsync` 失败，再对当前源码
  验证修复；
- `checks/run_rev6_checks.py`：恢复、锁忙、consumed 中断、未知进程、损坏 stat、
  pid 变化、同名替换、链接/悬空链接、路径身份变化、正常已退出/删除、observer/
  layout/pid/callerOffset/资源日志/raw-receipt 互换、畸形配置等行为检查；
- `checks/run_regressions.py`：原 28 项模拟回归继续通过；
- `checks/static_check.py`：更新后的静态与交付检查；
- 所有模拟结果标注 `simulated=true`，`targetExecutions=0`、`realContainers=0`，
  不得据此推导真机通过。R3 保持 `blocked`。
