# 阶段 B 有限机制预实验协议（实验准入修订 · 第 5 轮，预检证据链与资源清理）

**状态：`pending-codex-review`。本文件不产生目标尝试、不产生正式准入、不启动真实容器或
observer。`targetExecutions = 0`。正式批准文件由主持方在源码审查与零目标预检通过后写入
`codex-review/experiment-admission.json`；预检许可单独写入
`codex-review/preflight-admission.json`，两者都不由作者生成。**

本版本只修订预检许可/证据、布局字节绑定、观察器重建、资源生命周期与清理门控。四个合成
夹具、输入探针模板和 16 项预期保持基线字节不变；源码 `pointId` 与运行 `bindingId` 的
含义不变。

---

## 1. 范围与硬上限（不变）

- 只做一批：四类合成对照，每类最多 4 个输入，合计最多 **16 次串行目标尝试**。失败和结果
  不明也占名额；不得重放、不得追加第二批。
- 固定镜像 `sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7`，
  CPython 3.12.15。
- 目标限制：非 root（65534）、禁网、只读根、`cap-drop ALL`、`no-new-privileges`、512 MiB、
  1 CPU、64 pids、32 MiB `/tmp`、256 KiB 输出、既有限时。不挂载凭据、模型环境、Docker socket
  或宿主目录。
- 环境白名单固定为 `PATH`、`LANG`、`LC_ALL`、`PYTHONHASHSEED`、
  `PYTHONDONTWRITEBYTECODE`、`PYTHONNOUSERSITE`、`HOSTNAME`；`target_launcher.py` 在 GO 后清除
  所有继承变量并只安装该白名单。
- 固定实验源码、探针、预期和清单后不得为结果改动或追加。预实验只证明有限机制，不是真实项目
  检测效果，也不是任意恶意源码防伪证明。

---

## 2. 两条互不循环的许可路径

### 2.1 零目标预检许可（唯一 ID、独占锁、一次性登记）

`codex-review/preflight-admission.json` 只绑定：

- 唯一 `preflightId`（32–64 位小写 hex）；
- `protocol-manifest.json` 与 `candidateManifestSha256` 的实际字节摘要；
- 已完成的源码审查回执 `codex-review/source-review-receipt.json` 的实际字节摘要；
- `protocolRevision = 2`、`allowedCommand = "preflight"`、`maxTargetExecutions = 0`、
  `fixturesImported = 0`。

它**不要求**正式实验准入。入口固定为：

```text
tools/zero_target_preflight.py preflight
tools/zero_target_preflight.py status --preflight-id <id>   # 只读查询原 ID
```

入口不接受脚本、目标、夹具、attempt 或任意挂载参数。固定挂载只有 `/review/preflight`，
内容固定为 `preflight_selfcheck.py`、`layout_probe.py`、`structure.py`、
`observer_template.bt`、`observer-profile.lock.json`；不得包含四个夹具、`experiment-plan.json`、
`target_launcher.py` 或 `experiment_compile.py`。

执行顺序（失败即阻断）：

1. 校验清单、许可、审查、封存 `observer-profile.lock.json`；
2. 获取稳定独占 flock：`preflight/.preflight.lock`（锁文件永不删除）；
3. 在 `preflight/claims/<id>.json` 以 `O_EXCL` 写入一次性 `consumed` 登记；
4. 创建 `preflight/evidence/<id>/` 受控独立目录；
5. 以上完成后才创建 stage、容器或进程；
6. 所有证据文件以 `O_EXCL` 新建，不覆写；同一 ID 的目录只创建一次；
7. 预检在同一固定镜像中完成：容器显式 `--entrypoint /usr/bin/python3.12`、
   `--interactive`、非 root、只读根、禁网、资源限制；固定自检源码先做纯布局推导、
   `int 0` 编码、自身 `eval("0")` CALL 偏移与预期结构；渲染观察器，等待 BEGIN，
   发送唯一 `GO`；实际观察一个无副作用自检事件；
8. 采集器退出码必须为 0，observation 必须由本次调用新建；用 `observation_pure.parse_receipt`
   从本次 raw 字节复算，核对唯一完整 BEGIN/END、tag、预检身份、caller 路径/偏移/摘要、
   整数零、结构和事件数；
9. 观察器必须 SIGINT 优雅停止并实际退出；TERM/KILL 升级、提前退出、流截断、drain 未完成、
   raw 读错、采集失败均阻断；
10. 容器用完整 ID、精确名称、`sce.tag`、固定镜像核验；结算前三次成功查询确认 ID/名称/
    归属标签均无匹配，客户端/观察器均已退出；之后才移除身份一致的 stage 并以 lstat 确认；
11. 写出 `preflight/evidence/<id>/preflight-receipt.json`，再写
    `preflight/claims/<id>.completed.json`。

并发得到 `preflight-locked`；同一许可重试/重放得到 `preflight-license-consumed`。
`status --preflight-id` 只读；`consumed` 但无 completed 记录返回 `unknown-outcome`。

### 2.2 正式实验许可

`codex-review/experiment-admission.json` 在正式 runner 中校验：

- `protocolRevision = 2`、`state=approved`、reviewer/receipt 非空；
- `protocolManifestSha256` 等于实际清单字节摘要，清单每个文件实际字节匹配；
- `sourceReviewReceiptSha256` 等于已完成审查回执字节摘要，且该审查无 blockers；
- `preflightId` 与 `preflightReceiptPath` 指向 `preflight/evidence/<id>/preflight-receipt.json`；
- `preflightReceiptSha256` 等于实际回执字节摘要；
- `verify_preflight_evidence` 独立复算预检回执：清单、许可、审查、claim、profile、layout、
  template、raw、observation、整数零、调用点、结构、END、采集器退出码、drain、优雅停止、
  清理全部一致；不信任 JSON 中的通过布尔值；
- attempt 列表唯一、1–16、`maxTargetExecutions == len(allowedAttempts) ≤ 16`；
- prepare step 在 `layout-v1`、`bind-all`、`compile-per-attempt` 中。

缺失、被篡改、跨清单、旧协议或 claim/completed 不一致 → 退出码 78，且在创建目录、写状态
或启动容器之前拒绝。

---

## 3. 每次目标尝试的顺序

1. **admission**：校验正式许可、清单、审查、预检回执与 claim；失败 78。
2. **layout/template/profile**：再次核对 `prepare/layout/layout.json` 字节摘要、
   `prepare/layout-receipt.json`、冻结模板字节、封存 profile 实际身份；失败 79，未创建任何
   attempt/stage/容器。
3. **batch lock**：`flock` 独占；失败 79 `batch-locked`。
4. **reserve**：先写 counter（失败也占名额），再写 attempt（`state=reserved`、随机 challenge、
   预算快照、`executionState=not-started`、`goState=not-attempted`）。
5. **expected**：若 `prepare/compile-NNNN/expected.json` 不存在，纯编译首次生成；写出后立即
   读回，`expectedSha256` 为文件字节摘要。复用分支读同一文件并记录同一摘要。
6. **stage**：`runs/NNNN/stage-<random-tag>/{runroot,config,tools}`，文件 0444、目录 0555；
   `lstat` 记录 `(dev,ino)` 身份。
7. **resource intent**：创建容器之前落盘随机 tag、容器名、镜像、entrypoint、interactive、
   挂载、env 键、stage 身份、config/launcher 摘要、各进程 `spawnState=not-started`。
8. **create**：先按名称查询；同名存在 → `container-name-conflict`，绝不删除后重建。
   显式 `--interactive`、`--entrypoint`、`--label sce.tag=...`；创建后用完整 ID + 名称 + 标签 +
   镜像 + 配置 + 只读挂载核对。
9. **start**：`docker start -a -i <full-id>`；spawn 前写 `client=spawn-attempted`，成功后记录
   完整 `(pid,pgid,starttime,bootId,groupLeader)`；身份缺失保持 `unknown`。
10. **config 校验**：容器内 `sha256sum /review/config/run.json` 等于 stage 字节摘要。
11. **observer arm**：用冻结模板与已核验布局渲染观察器，记录模板/布局/profile 摘要；启动
    bpftrace；在有限时间内看到 BEGIN。spawn 身份规则同上。
12. **GO**：先持久化 `goState=writing`，写唯一一行 `GO` 后 `goState=sent`；失败记
    `write-unknown`。
13. **target**：launcher 清环境 → 读 config → detach stdin → 设 argv/sys.path → 安装 import
    guard → 首次 import。退出码即入口返回值（0–255）；stdout/stderr 只作诊断。
14. **observe**：目标客户端退出后向观察器发送 SIGINT，有限时间内确认退出；不允许 TERM/KILL
    升级作为成功证据。持续有界消费 stdout/stderr；drain 完成且未截断。END 必须唯一且为最后
    一条非空记录；缺失、重复、截断、END 后 map 输出 → invalid/unknown。
15. **collect**：严格解析原始流；事件数从实际 `EVENT` 记录推导；observation 文件必须本次新建。
16. **judge**：摘要链、身份、来源、调用点、事件数、归属、结构；用冻结模板和已核验布局重建
    observer 字节并精确比较；与冻结预期比较；见 §5。
17. **cleanup**：重新查询容器（完整 ID/名称/标签/镜像）、客户端/观察器进程组与 stage
    `(dev,ino)`；只有容器三次成功查询无匹配、两个进程均 `exited`、stage 经 lstat 消失才
    `confirmed`。
18. **settle**：`confirmed`/`excluded` 且清理确认 → completed；语义 `unknown` 但清理确认 →
    unknown 且释放预留；清理未确认 → 预留保留。

---

## 4. 16 个预先编号尝试（不变）

见 `experiment-plan.json`（与基线逐字节相同）。S1–S4 结构对照，Q1–Q4 数据包装/语法拒绝，
E1–E4 回显无动态事件，W1–W4 错误函数。`${challenge}` 是每次启动前生成的 32 位小写 hex。

---

## 5. 判定规则

按顺序：

1. **文件字节摘要链**：`attempt.bindingSha256 / expectedSha256 / observationSha256 /
   observationRawSha256 / observerSha256 / layoutSha256 / observerTemplateSha256 /
   profileSha256` 与 judge 复算的落盘字节摘要逐一相等；`observation.rawSha256` 与
   `rawBytes` 等于原始流；任一不符 → unknown。
2. **治理链**：admission / manifest / preflight receipt / claim / source review receipt /
   attempt / expected / binding 交叉链接；预检或审查缺失、篡改、跨清单、旧协议 → unknown 或 78。
3. **布局/模板/profile**：`layoutSha256` 是布局文件实际字节摘要；
   `layoutStructureSha256` 是结构摘要；bind、compile、expected、attempt 与预检回执一致；
   冻结模板字节摘要与预检 `toolDigests["observer_template.bt"]` 一致；profile 实际身份与
   预检 `profile` 一致；judge 重建 observer 字节必须与 `observer.bt` 精确相等。
4. **身份**：binding 与 expected 的解释器/库摘要一致；镜像与 python 版本固定；attempt 的
   `targetPid/targetUid` 与 observation 一致；渲染模板含 `/proc/<pid>/`、`pid != <pid>`、
   `uid != <uid>`、`!= "<callerPath>"`、`!= <callOffset>`。
5. observation 必须 `complete`、`targetSelfReportUsed=false`、callerPath/callOffset 与 binding
   一致、无解析错误。
6. cleanup 必须确认。
7. **先由事件推导**：
   - 0 事件：
     - 若 expected 是 data 行、包装后源码真实 `SyntaxError`、`dataBaseline is None`、
       `syntaxRejectExpected=true`，且目标退出 3 → `excluded/syntax-reject`；
     - 否则 → `excluded/no-dynamic-event`；
     - 上述语法拒绝候选若退出不是 3 → `unknown/syntax-reject-target-exit`；若出现事件 →
       `unknown/syntax-reject-with-events`。
   - >1 事件 → unknown。
   - 1 事件：caller 等于 binding → bound；等于 bind 阶段记录的未绑定候选 → `unbound:<qualname>`；
     否则 → unknown。结构等于 expected → 匹配；等于 data baseline → `data-only`；否则 unknown。
8. **再与冻结比较**：事件数、退出码、decision、reason 任一不一致 → unknown（偏差交人工复核）。
9. 只有“1 事件 + caller 绑定 + 结构等于 expected + 退出/事件数/原因全一致”才 confirmed。
10. 目标 stdout/stderr/自报摘要一律不参与判定。

Q4 的特殊要求：只有固定编译器对**真实包装数据**抛出明确 `SyntaxError`、真实退出 3、完整零
事件、身份/来源/摘要链正确，才是 `syntax-reject`。仅结构不支持、`ValueError` 等其他异常或
普通零事件不算语法拒绝。

---

## 6. 资源所有权、恢复与清理

- 预检、准备与正式 attempt 统一登记资源意图；容器名称含随机唯一 tag；创建前同名冲突拒绝，
  不删除同名异属资源。
- 创建后使用完整 ID；启动、exec、删除前核对完整 ID、精确名称、`sce.tag`、固定镜像。
- spawn 前登记 `spawn-attempted`；成功后记录 `(pid,pgid,starttime,bootId,groupLeader)`；
  没有身份的已尝试 spawn 永久 `unknown`。
- 进程三态：只有明确未启动，或成功查询证明 PID 不存在/僵尸/整组成功空扫描才 `exited`；
  权限错误、畸形 stat、PID 复用、非组长、孤儿组 → `unknown`，不发送信号、不释放预留。
- stage 记录 `lstat` 的 `(dev,ino)`；路径是链接、身份改变、树内出现链接、残留或查询失败 →
  不删除、不释放。
- 结算前用三次成功查询确认完整 ID、精确名称、归属标签均无匹配；确认客户端/观察器退出后，
  才移除身份一致的 stage，并以 lstat 确认消失。
- `recover`/`cleanup` 只重新查询并清理原 attempt，不重放目标；早期失败后必须能重新查询原
  进程组与目录，不能只复用布尔标记。
- 失败或状态不明仍消耗原尝试名额。只有清理确认后，语义 unknown 才正常结算并释放预留。

---

## 7. 观察器格式（bpftrace v0.20.2）

- 模板固定，渲染后不得残留占位符；调用点、caller 路径、pid/uid 过滤逐字校验。
- `BEGIN` 只用于确认程序已启动，**不是**事件可用性的唯一证明；预检必须实际观察一个自检事件。
- 正常停止由 runner 在目标客户端退出后发送 SIGINT；bpftrace 执行 END。END 前 `clear(@events)`，
  避免默认 map 输出污染 END。
- 事件数从实际 `EVENT` 行推导，END 的 `events=` 只用于一致性校验。
- 任一流截断、缺失 END、END 后尾随记录、强制退出、丢事件、drain 未完成 → unknown。
- 判定端用冻结模板和已核验布局重建 observer 字节并精确比较；改模板或改布局 → 使用前拒绝。

---

## 8. 模拟测试与本阶段边界

本阶段只做源码修订、纯编译、静态解析和带记录 shim 的模拟测试：

- Docker shim 用真实编译/布局函数回答纯工具容器，但不创建容器；目标只记录 GO/退出码；
- 观察器 shim 从**实际编译出的 expected 回执**生成事件，不预写判定回执；
- `checks/repro_before.py` 对冻结基线复现修复前反例；`checks/run_regressions.py` 覆盖
  采集失败残留旧结果、跨次 raw/解析/回执混用、相同许可并发与断线重试、正常采集、绑定后改
  布局和模板、进程读取权限失败/畸形/已启动身份缺失、同名替换、资源未知时不调用 stage 删除、
  正确结算与恢复不重放、首次编译、回执复用、Q4；
- 每项记录具体拒绝原因与副作用；
- 所有“通过”均为模拟结果，不是固定镜像内的真机证据；不得从假回执推导真实通过。

---

## 9. 执行前实机核验（本阶段不执行）

1. 固定镜像 `docker image inspect`、解释器/库摘要与封存 profile 完全一致；
2. 零目标预检入口在主持方签发的预检许可下实际运行，观察一个自检事件、整数零、完整 END，
   并确认资源清理；
3. 预检回执、源码审查回执与正式许可绑定后，才允许正式 `prepare-layout`/`prepare-bind`/
   `compile`/`run`；
4. 固定镜像 ABI、bpftrace arm、流丢失/截断、Docker 交互式 GO 仍需实机确认。

---

## 10. 冻结与记录

- `protocol-manifest.json` 列出协议、合同、四个夹具、计划、工具、预检自检源码、封存
  profile、检查脚本与结果；生成后不得修改。
- 第 3/4 轮材料原样保存在 `baseline/`；四个夹具与 `experiment-plan.json` 与基线逐字节相同。
- 本阶段结果：`checks/repro-before-results.json`、`checks/regression-results.json`、
  `checks/static-checks.json`、`checks/regression-evidence/`、`checks/diffs/`。
- 不生成正式准入或预检回执，不启动合成批次，不执行 tqdm，不改封存产品、日常 VM 与 GitHub。
  R3 保持 blocked，正式盲测保持未开始。
