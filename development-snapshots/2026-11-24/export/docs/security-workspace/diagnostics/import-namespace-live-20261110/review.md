## 结论

**本步有限通过（附记录性修订项，不阻断本轮扫描证据链）。**  
仅能支持：**验收脚本的临时权限修复、隔离 VM 中正式 `createJointPanel` 组件经真实 RPC 对固定 18 文件完成一次所选 Semgrep 扫描，并完成下载/刷新行为核对。**  
不能外推为完整产品准入、完整 Harness 聊天/模型链验收或 R3 放行。建议将报告中两处表述收紧，并补充临时中继关闭的直接回执。

---

## 1. 权限模式根因与“只修验收脚本”

**材料支持该根因判断，且没有把同一失败重试冒充成功。**

可核对证据：

- `diagnostic-result.json`：worker 模式 `0o600`，UID `1000`，容器 UID `65534`，实际错误为  
  `python3: can't open file '/review.py': [Errno 13] Permission denied`。
- `diagnostic-fixed-result.json`：同一 worker SHA-256，改为 `0o644` 后同一 9 个输入得到 `9 checks / 9 observations`，`cleanupVerified:true`。
- `stage-changes.patch` 仅增加验收 staging 中的 `chmod(0o644)` 行；`stage-intent.json` 中 `package/scripts/python_namespace_review.py` 仍为原 SHA-256 `6c8c...`，未改产品源码。
- 首次失败任务仍保留为 `collection-initial.json` 的 `db63bf15...`，其中 `namespaceReview.state:"unavailable"`；新编号任务为 `f015ad49...`，`namespaceReview.state:"completed"`。这不是把原失败任务改记为成功。

确定性：**较高。**  
限制：这是静态阅读两份诊断回执与补丁得出，我未重新执行 chmod、未重跑容器、未重算实际文件哈希。

---

## 2. Scanner 17 规则、18 文件、9 warnings、4 import + 9 namespace 证据

**材料内部自洽。**

`acceptance-r2/collection-after-browser.json` 显示：

- 任务 `f015ad49-c78f-4cb0-9fbd-9cbfaf7fe01b`，snapshot `9b0ffc...`。
- Semgrep `1.182.1`，`executedRules.count:17`，规则 SHA-256 `e70603...` 与 `semgrep-deep17.json` / `stage-intent` 一致。
- `fileCoverage: scanned 18 / total 18 / uncovered 0`。
- `findings:9`，全部为同一 `policy.harness.python.dynamic-code-namespace` warning，`sourceLocations.total:9 bound:9 unavailable:0`。
- `artifacts:13`，即 4 条 `python-import-flow` + 9 条 `python-namespace-structure`。
- `namespaceReview`：`eligible:9 checked:9 observations:9 unmatched:0 retained:9 cleanupVerified:true`，Python `3.12.15`。

与 `controls.json` 对照：

- `case0` 至 `case3` 是空字典命名空间正对照，且仅这 4 个 file 生成 import 证据。
- `case4` 动态 scope、`case5/6` 泛型 callee、`case7/8` 泛型 caller 为负对照，未生成 import 证据；但仍有 namespace 结构观察，这与“9 个执行点均保留结构观察”一致。
- `ordinaryFindingRows:0` 表示普通 finding 表未新增，不等于 9 条扫描 warning 不存在。

Docker 观察方面，proof 中记录：

- image `sha256:9479...`、规则挂载 SHA `e706...`；
- `/src` 只读、`network:none`、`user:1000:1000`、root read-only、cap drop ALL、no-new-privileges、内存/PID/CPU 限制；
- `outcome:"passed"`，`sourceHashesMatch:true`、`manifestHashesMatch:true`。

`observerErrors` 中有一次 `docker inspect ... no such object`，从时序看是容器尚未创建时的观察竞态；随后 proof 仍有完整 observed 并最终通过，不构成扫描成功后的验证失败。但应保留该竞态说明，避免把它误读为“零观察错误”。

确定性：**较高，但依赖回执而非重新运行。**  
清理方面，`cleanup.json` 与 `acceptance-r2/cleanup.json` 均确认容器缺失、guest 端口关闭、owned 进程不存在、临时 root 删除、169 程序与 42 数据库逻辑摘要匹配。

---

## 3. Chrome 5 页命中 / 4 页证据、下载 5 章节、刷新单次启动

**足以支持“原生 Chrome 中的正式组件 + 隔离 VM RPC + 一次真实扫描”的有限结论；不足以支持完整 Harness 或原始 UI 证据的完全独立复核。**

材料显示：

- `browser-observations.json` 明确 surface 为“Google Chrome native CUA, production createJointPanel component in isolated VM service”；
- 5 页命中、9 行，4 页证据、13 行；
- 下载文件 34544 字节，`download-verification.json` 记录 task/snapshot 匹配，五章节 counts 为 findings 9、files 18、exclusions 0、diagnostics 0、artifacts 13；
- 刷新后恢复同一 `f015ad49...` 任务和同一 snapshot；
- `collection-after-browser.json` 的 `events` 只有一次 `start`，无第二次启动；22 次 report 请求与观察记录中的 22 次报告请求一致；
- `modelCalls:0`，未执行项目源码；
- `analysis.json` 明确 `fullHarnessChatModelChainTested:false`、`fullHarnessReleaseNotAsserted:true`。

限制：

- `browser-observations.json` 是叙述性记录，没有截图、原始 CDP 事件或每页原始 items；5 页/4 页的页边界只能按摘要接受。
- `download-verification.json` 是下载校验摘要，未附原始下载 JSON；不能从现有材料重算 34544 字节内容。
- 因此足够支持“正式组件在原生浏览器中完成有限 RPC 流程”，**不能**表述为完整 Harness 聊天、插件路由或模型链验收。

---

## 4. 未验证 / R3 不放行 / 无新独立样本

**没有发现明显过度结论，但有两处措辞应收紧。**

正面证据：

- `analysis.json`：`allFindingsAndArtifacts:"unverified"`、`ordinaryR3Qualified:false`、`independentSamplesAdded:0`、`candidateDeployed:false`；
- `report-draft.md` 明确 R3 未放行、完整安全工作区及完整 Harness 聊天/模型链仍待完成；
- `controls.json` 标记 `allAlreadyUsed:true`，没有把它包装成新的独立 R3 样本。

建议修订的表述：

1. “重新从 Chrome 发起一次完整扫描”宜改为  
   **“所选 Semgrep 步骤对固定 18 文件的完整执行”**。  
   材料本身有 `coverageComplete:false` 和手工检查未覆盖项，不能读成完整安全审查。
2. “普通发现表 0 新增”宜明确为  
   **“普通 finding 数据库新增 0 行；同时存在 9 条未验证扫描 warning”**，避免被误读为“0 条发现”。

既有泛型覆盖、手工认证/授权/业务逻辑/架构等缺口，是既有覆盖限制，不应记为本轮新缺陷。

---

## 5. 源材料、只读绑定、清理与临时中继

**源材料和只读绑定未见本步阻断。**

- `acceptance-r2/prepare-live.py` 对 package 文件与 baseline 期望哈希进行比对，再写入 stage intent。
- stage 中 173 个 package 文件 hash 校验通过；worker hash 未变。
- scanner proof 的 `/src` 为只读挂载；namespace sandbox 的 `/review.py` 也为只读 bind mount，容器 UID `65534`。
- 清理回执确认两个临时 root 删除、容器缺失、guest 端口关闭、owned 进程不存在。

**唯一应修订的清理记录缺口：临时 host relay。**

`analysis.json` 写有 `bothHostRelaysClosed:true`，但 `cleanup.json` 与 `acceptance-r2/cleanup.json` 只明确记录：

- guest 端口关闭；
- guest owned 进程不存在；
- 容器不存在；
- 临时 root 删除。

`relay.py` 的代码逻辑上在 `/__stop` 后 `done.set()` 并 `server.shutdown()`，但现有回执没有记录 host relay 的 PID/端口关闭确认。因此：

- 不应把 `bothHostRelaysClosed` 当作已直接验证事实；
- 建议降级为“按 relay.py 退出逻辑推断”，或补充 host relay 进程/端口关闭回执。

这不推翻本轮扫描结论，但影响“临时中继已闭环清理”的表述强度。

---

## 最终意见

**本步有限通过。**  
可支持：权限模式根因归因、仅修验收 staging、R2 新编号任务、17 规则/18 文件/9 warning/4 import+9 namespace、Docker 只读与限制观察、Chrome 正式组件的有限 RPC 流程、下载五章节摘要一致、刷新未重复启动、R3 不放行。

**建议修订但不作为本轮扫描结论阻断：**

1. 把 `bothHostRelaysClosed:true` 改为“代码推断/未直接确认”，或补充 host relay 关闭回执；
2. 附上 `final-evidence.json` 或明确其为清理脚本内部断言，避免只依赖 `cleanup.json` 摘要；
3. 将“完整扫描”限定为“所选 Semgrep 对固定 18 文件的完整执行”；
4. 明确“普通发现表 0 新增”不等于 0 条扫描 warning；
5. 对 Chrome 5 页/4 页和下载逐值一致，标注为叙述性 UI 记录 + 下载摘要，不是原始截图/原始下载文件复核。

不把完整 Harness 聊天/模型链、完整安全工作区、R3 或既有泛型覆盖缺口计入本轮通过范围。
