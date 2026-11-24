# VM 安全审计工作台

> 当前版本、恢复点和完成状态统一见[当前状态](current-status.md)。本文的历史验收段落只描述当时结果。

2026-10-29，安装在现有改进版中，保留 personal.2 包版本。打开日常入口，进入演练台的 **安全审计** 页。现有 REA、reverse-skill、PentAGI 和原版能力继续使用原来的入口。

该阶段运行126项插件程序，该阶段恢复点`ready-security-background-20261029`；后台审计与自动校时已验收，见[操作说明](background-audits-clock.md)及[验收](security-background-verification.json)。其余历史阶段按当时数量与生命周期解释。

## 使用

1. 选择本次项目。填写 `/home/purge/workspace/` 内的仓库绝对路径，勾选检查工具，填写到期时间；确认目录和网址可供检查后保存。期限最长 31 天。
2. 代码检查使用 Semgrep；依赖、配置和凭据痕迹使用 Trivy。ZAP 第一期只接受 VM 内 `http://127.0.0.1:明确端口/`，并排除 Harness 和其他已知管理端口。它会发起网页请求和短时爬取。
3. 运行检查，等待持久任务 ID 对应的结果。失败、取消、中断、覆盖不完整都不表示安全；同一服务一次只运行一个任务。后台标签页可能延后轮询，可点本页“刷新”。
4. 命中先进入“待验证”。写下验证依据后确认或标记误报；确认的发现可记录修复，再点“复测此发现”。未覆盖原文件、策略变化或扫描不完整时保留原状态；同规则同文件的问题移行后仍存在，会重新打开。
5. 使用“导出报告”下载 Markdown。读取资料时禁用导出，导出期间显示“正在导出…”。刷新或重新核对资料后，旧导出失效，请重新点击以获取当前报告。页面显示最近 500 条发现和 30 次任务及总数；导出独立读取各 20000 条，超过上限会声明报告不完整。

聊天要使用模型工具，须先把聊天绑定到同一项目，再让它调用 `redteam_security_audit`。工具支持 status/start/cancel/report/compare；启动要引用范围版本和唯一请求号，同一请求重试复用请求号。它不能保存范围、扩大范围或替用户确认发现。日常模式的专业工具过滤继续沿用，需在提供红队工具的模式中使用。

## 覆盖和权限

范围校验覆盖本页和新增审计工具。**VM 的通用 Shell、浏览器、PentAGI 和原版能力继续沿用原来的权限，不能把这里的项目范围理解成整台 VM 的强制访问边界。** Mac 的共享目录、剪贴板、USB 和出口规则未扩大。

扫描器使用固定官方 ARM64 镜像摘要、只读仓库挂载、非 root UID 1000、限制 CPU/内存/进程数、4 分钟超时和输出上限。Semgrep/Trivy 容器禁用网络。ZAP 的临时 API 用固定 hook 绑定到 VM 的 127.0.0.1；原生验收观察到 `[::ffff:127.0.0.1]:49090`，没有发布宿主端口。扫描结束后容器和 API 监听均已关闭。

规范化发现隐藏源码片段、凭据值和原始 HTTP 内容；私有原始扫描结果保存在 VM 项目 `runs/security/<任务ID>/`，权限受运行目录保护，不进入 GitHub 导出。模型可使用的通用 Shell 仍能访问 VM 中的这些文件。

## 资料校验与异常读取

2026-10-29补充：安全审计页采用新资料前验证当前项目、范围字段、三个运行资源卡、任务与发现的必要字段、记录ID及修订号。任务页最多30条、发现页最多500条，重复ID或矛盾/非法总数会拒绝采用；总数若存在，须与当前页的既有固定上限相符。旧返回值缺少可选总数字段仍兼容，此时页面不声明全量总数。未知字符串状态继续原样展示，不因对象原型同名而取到其他值；工具名必须为已支持工具的字符串，不接受数组等隐式转换。

首次读取结构异常时显示资料无效/结果未确认；刷新异常时保留上次成功结果与未保存范围草稿，并明确标明是上次资料。保存、扫描、发现复核、重试、取消及导出按钮暂停，点击“刷新”或“重新核对运行资源”取得合法资料后恢复。只读刷新不自动重放写入，不修改后端数据或授权。字段校验服务于页面渲染和操作参数，不是新的服务端权限或恶意客户端隔离机制。

6个新增回归覆盖异常嵌套字段、重复/页限/计数、失败刷新及恢复、旧可选字段与未知状态、数组工具名及原型同名状态；最终20项客户端、395项完整插件回归通过（客户端计数与完整套件重叠）。独立复核找到后两组遗漏，反例实际失败后修正并复核关闭。真实HTTP资料经生产组件接受；首次本地验收误用了夹具项目a，正确被拒绝，指定实际项目后通过，失败回执保留。

真实浏览器正常显示2次任务/3条发现，重新核对运行资源后保留未保存草稿，导出在读取完成后恢复。测试草稿未保存，切页后已丢弃并恢复原范围。异常响应注入和恢复路径使用受控组件测试，未在浏览器或生产数据库注入故障；**尚无证据把历史偶发空白归因于这些字段问题**。本轮没有新扫描、模型调用、后端/schema、扫描资产或权限变更。

安装前3个前端文件备份位于`/home/purge/downloads/security-status-20261030T032530Z`，当前122项程序与VM匹配。整机恢复点仍不含本轮更新。详见[security-status-verification.json](security-status-verification.json)。

## 报告汇总与历史范围

2026-10-29更新“导出报告”和模型工具的report结果。Markdown先列发现状态、严重性和任务状态三份统计表，再列当前保存范围、发现明细及每次任务保存的范围与运行资料。统计是**全部已保存发现/任务记录**的计数，明细各最多20000条；超过限制仍保留完整汇总并声明明细不完整。统计与明细使用同一SQLite读取事务。发现状态统计包含待验证、已确认、误报、已记录修复、复测通过、再次出现和未识别状态；严重性统计包括所有状态，不能当作未修复漏洞数量。

“未完整结束的任务”仅将state=completed且complete=1视为完整结束；失败、取消、中断、覆盖不完整、运行中或未识别状态都保留为未完整结束。没有任务或没有发现不产生“项目安全”的结论。当前保存范围只代表当前配置，不适用于全部历史任务；每次任务的仓库、工具、期限、版本、规则、漏洞库更新时间、覆盖文件数和覆盖策略取自当时保存的记录，不用当前运行资源补填。历史字段缺失显示“未记录”，明确保存url=null才显示“未配置”。记录提交号不证明未提交修改已固定或可复现。

动态正文再次执行现有脱敏并转成单行字面Markdown，避免标题换行、表格符号或HTML被当成报告结构；不会修改数据库中的发现及备注。该格式保护不是完整秘密检测或项目安全结论。结构化报告新增summary和generatedAt字段，原findings/runs/profile字段及项目授权继续沿用，前端下载方式不变。

5个新增回归先失败后修复，包括20001条发现的全量计数、范围变化后的历史版本、空/旧/未完整任务、字面文本与脱敏，以及缺网址和明确空网址的区别。最终389项插件回归通过，独立只读复核没有Important/Critical发现。真实owner接口与浏览器下载当前合成项目3条待验证发现、2次完整任务，记录版本一致；下载与接口正文除生成时间外相同。未登录401、异源403。第一次HTTP验收在SSH取登录入口时退出255，随后只读连接和重试成功，原因未确定；保留失败记录，不归因为报告故障。

该阶段122项程序与VM摘要一致，运行资源预检通过；本轮没有新扫描、模型调用、数据库结构或权限变更。安装前备份为`/home/purge/downloads/security-report-20261030T024230Z`，末次旧网址显示修正前备份为`/home/purge/downloads/security-report-legacy-20261030T024743Z`。整机恢复点仍不含本轮更新。使用SQLite接口依据[SELECT](https://www.sqlite.org/lang_select.html)和[SAVEPOINT](https://www.sqlite.org/lang_savepoint.html)。结构化记录见[security-report-verification.json](security-report-verification.json)。

## 报告下载保护

2026-10-29补充：审计报告的返回值必须明确成功、项目一致且正文为字符串，否则显示“报告未确认”。下载回调绑定当前资料读取代次；刷新、重新核对、卸载后的旧结果和错误失效，旧按钮不能另发请求。同步锁阻止快速连点，只有对应请求能解除忙状态；刷新可开始新的读取，旧请求不会解除新导出的锁。页面现有项目key隔离继续沿用，本轮没有改动写入回执、扫描、后端或数据库。

4个新增组件回归先复现失败，再修复通过；完整384项插件回归通过，独立只读复核未发现Important/Critical问题。实际IAB观察到读取时禁用、导出时“正在导出…”、完成后恢复；下载当前合成项目3条unverified发现和2次任务，正文项目及规则版本核对一致。延迟响应、异常返回和快速连点由受控组件测试验证，未在真实浏览器注入延迟或故障。未发起新扫描或模型调用。接口使用[React effect清理](https://react.dev/reference/react/useEffect)及[项目key隔离](https://react.dev/learn/preserving-and-resetting-state)的既有模式。

本轮三个文件安装前备份为`/home/purge/downloads/security-download-20261030T022716Z`，当前仍121项程序。镜像、规则、漏洞库和权限保持原配置；整机恢复点不包含本轮修复。详见[security-download-verification.json](security-download-verification.json)。

## 扫描结果对比

在“安全审计→扫描结果对比”选择“基线任务”和“本次任务”，点击“对比所选任务”。可选列表来自最近30次任务中的完整完成记录；旧记录会标注没有完整快照。成功后可展开明细并下载对比报告。模型使用`redteam_security_audit`的`action: compare`，传入`baseRunId`和`currentRunId`；仍须绑定同一项目。比较本身只读，不启动扫描、不修改发现或请求模型。

比较要求两个不同任务属于同项目、同扫描器、同覆盖策略标识，且均完整完成。规则、固定镜像、数据库或范围策略变化会拒绝比较；旧任务缺少快照不会从当前发现表反推历史。新任务完成时把规范化观察快照与发现、完成状态放在同一SQLite保存点中提交；快照写入失败会回滚该次结果并标记任务失败。后续手动验证或修复发现不改写已有快照。

| 分类 | 含义 |
| --- | --- |
| 新增命中位置 | 本次存在、基线没有的规则与完整位置组合 |
| 仍存在的命中位置 | 两次都有的规则与完整位置组合 |
| 已覆盖文件中未再次命中 | 基线命中不在本次集合中，且本次明确覆盖了原文件 |
| 覆盖未证实 | 基线命中缺席，但无法确认本次覆盖原位置；ZAP缺失项均保留在此类 |

匹配依据是规则ID与含行号的位置；代码移行可能同时表现为新增与未再次命中。**未再次命中不等于已修复**，不会自动关闭发现。快照最多保存2000条规范化发现、20000个覆盖文件、4MiB JSON；超过限制或无法保存有效快照时，扫描可完成但对比明确不可用。每类界面和Markdown最多展示100条明细，数量依据完整已保存快照，截断时会提示；下载报告也遵循该明细限制。快照仅含规则、标题、严重度、位置和覆盖文件名，不另存源码或原始证据。

2026-10-29（America/Los_Angeles）：380项插件回归通过；独立复核18项聚焦测试重复覆盖，不累计。真实固定Semgrep对自有合成文件运行两次，得到新增1、仍存在1、已覆盖文件中未再次命中1、覆盖未证实0，3条发现全部保留待验证。新网页进程读取持久快照，HTTP验证owner成功、未登录401、异源403、跨项目与非法ID拒绝、旧任务缺快照不可用。真实浏览器显示同一结果并下载字节完全一致的Markdown。本轮没有模型调用、真实项目或公网扫描。

该阶段121项插件程序与VM摘要一致，规则、镜像和漏洞库未变。安装前精确源码备份位于`/home/purge/downloads/security-compare-20261030T021036Z`。新增`security_run_snapshot`表仅存在各项目VM私有数据库中，不进入Git导出。退回先前源码时须结束活动任务，恢复备份文件并移除本轮新增模块；保留数据库和新增表，旧源码会忽略该表，不能为回退而删除项目数据。整机恢复点仍未包含本轮功能，也未新增快照。结构化记录见[security-comparison-verification.json](security-comparison-verification.json)。SQLite事务接口参考[Node DatabaseSync](https://nodejs.org/api/sqlite.html#class-databasesync)与[SQLite SAVEPOINT](https://www.sqlite.org/lang_savepoint.html)。

## 运行资源核对与恢复预检

安全审计页新增“重新核对运行资源”：只读检查本地固定镜像的存在、ARM64/Linux 架构和摘要、Semgrep 规则摘要，以及漏洞库的完整 SHA-256、大小与元数据。普通读取最多复用 30 秒内的检查结果并标出缓存；显式重检和扫描启动前重新核对。检查结果不代表 GitHub 上的最新版本。

界面显示资源检查时间、漏洞库更新时间与天数。超过 7 天是本地提醒，保留现有库的使用；缺失、损坏、路径不安全或时间元数据无效时禁止报告对应工具就绪。严格拒绝数值、日期简写、无效日历日期、矛盾或明显超前的时间。没有自动下载或更新资源；手动漏洞库维护见下文。

在专用 VM 执行独立只读预检：

```bash
/home/purge/.local/node/bin/node /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-runtime-preflight.mjs
```

它返回 JSON 和退出码：0 表示所列运行资源通过检查，1 表示有缺项、差异或未确认项。不会运行扫描器、请求模型、下载镜像或修改权限。原有 `scripts/restore_preflight.py` 继续核对配置与依赖，恢复验收时应同时执行这两项；它们各自覆盖不同资源。

此次登记的原始数据库摘要与 Mac 上先前已验证的官方下载文件一致，见运行锁中的 `database.fileSha256/fileBytes`。该锁不替代数据库文件本身。新增原始备份为 `/home/purge/downloads/security-runtime-20261029T223017Z`，日期校验补丁前备份为 `/home/purge/downloads/security-runtime-20261029T223311Z`；运行清单也分别保存在 `images-before-runtime-<同一时间>.json`。回退本次更新应逆序恢复程序文件及对应清单；不修改现有发现、范围和聊天数据。

检查和扫描间没有冻结整份 VM 文件系统；运行资源应由现有维护流程管理，避免扫描期间并发替换。该检查不防止拥有 VM 完全访问权限的进程自行改写资源。

## 当前工具与限制

| 工具 | 验收版本 | 第一期覆盖 |
| --- | --- | --- |
| Semgrep CE | 1.182.1 | 16条本地复核规则（local-reviewed-2），覆盖Python/JS/TS动态执行、Shell、反序列化、SQL、证书/JWT校验关闭及网页注入模式；具体列表与限制见下文 |
| Trivy | 0.76.1 | 离线漏洞库、镜像内嵌配置规则、凭据痕迹；不代表所有语言/依赖和配置都已识别 |
| ZAP | 2.17.0 | 传统基线爬取和被动检查；没有登录态录制或主动攻击；JSON 报告缺少完整 URL 覆盖证明，因此“未再次命中”不会自动关闭 ZAP 发现 |

漏洞库数据更新于 2026-10-29，摘要和时间见 [security-runtime-lock.json](security-runtime-lock.json)。本期未增加自动更新任务，扫描器镜像固定在验收版本，漏洞库可由统一启动器显式维护；使用前应核对数据库新鲜度。模型工具可读到实际资源检查与固定镜像对应的版本；不会每次运行 `--version`，也不会自动检查上游最新版本。

## 安装、备份和恢复

VM 运行资产位于 `/home/purge/tools/security-workbench/`：`images.json`、`rules.json`、`cache/db/` 和三份 Docker 镜像。该目录、Docker数据和新增审计数据库已纳入该阶段恢复点`ready-security-audit-20261029`。旧点`ready-recovery-proof-20261029`仍未包含这些内容，恢复旧点会回退，需要重新安装。

一期程序从 116 项增为 118 项；运行资源核对补充后为 120 项，当前扫描对比补充后为121项，全部摘要与当前 VM 匹配。安装采用精确基线校验、原子文件替换及失败回滚；原始安装前备份为 `/home/purge/downloads/security-phase1-20261029T215152Z`。随后三个小修正分别有独立备份，最终安装前备份为 `/home/purge/downloads/security-phase1-20261029T221648Z`。回退整个一期应按逆序恢复每次精确文件备份，不能只恢复最后一次的两个文件；审计数据独立保留。

仓库保存程序、规则和无密钥运行锁，**不包含 Docker 层和漏洞库大文件**，也没有承诺从 Git 一步重建全部运行资产。原 Mac 任务目录 `work/harness-security-phase1-20261029/image-assets/` 保留已校验的离线镜像包及数据库下载包。重新导入需先验证运行锁中的归档 SHA-256，再在 VM 使用 Docker load，并核对架构、配置和层摘要；Docker 29 的本地镜像摘要与上游配置摘要不同，不要混用。导入过程不需要在 Mac 运行这些镜像，也不需要放宽 VM 出口。

## 验收

355 项插件回归通过。真实页面验收了保存范围、三种扫描器、取消后重启任务、验证/修复/复测、刷新保留草稿、项目切换隔离和下载报告。合成 eval 问题修复后进入“复测通过”；最新页面保留 6 次任务、29 条合成发现。

通过已安装的原生 SDK 注册 66 项工具，确认新审计工具可读当前绑定范围，跨项目覆盖和未绑定显式项目均被拒绝。对 Phishing-Scam-Email-Detection 只做本地静态检查：Semgrep 覆盖 146 个文件、Trivy 识别 5 个目标，62 条命中均未作为已确认漏洞；临时验收数据库已移除，真实项目文件未更改。没有发起模型请求、扫描公共目标或进行真实漏洞利用。

真实 HTTP 检查确认 owner 读取 200、未登录 401、异源 403；范围版本冲突以 `ok:false` 明确拒绝并保留原范围。ZAP 的跨端口链接/跳转合成检查未访问范围外监听器。详情见 [security-audit-verification.json](security-audit-verification.json)。

运行资源核对补充阶段通过 364 项插件回归；原生验证实际镜像检查调用次数、强制重检和缓存路径，损坏/过期数据控制使用独立临时夹具，生产数据库保持原状。元数据字段与离线数据库全文摘要已核对。技术接口依据 [Docker image inspect](https://docs.docker.com/reference/cli/docker/image/inspect/) 和 [Trivy 数据库说明](https://trivy.dev/docs/latest/configuration/db/)。

本期运行资源核对的结构化记录见 [security-runtime-verification.json](security-runtime-verification.json)。

## 手动更新漏洞库

在Mac双击仓库根目录`Harness.command`，选9：1只读核对官方版本，2更新（需输入“更新”），3恢复中断前原库（需输入“恢复”）。安全审计页的“漏洞库更新”按钮提供同样说明；Trivy卡片显示最近一次已完成维护的结果和时间。网页与模型工具不会直接下载或提升权限。

Mac匿名访问官方`ghcr.io/aquasecurity/trivy-db:2`，仅接受GHCR及其固定官方CDN的HTTPS重定向，跨域去掉临时匿名授权头。manifest摘要、layer摘要/压缩大小、解压数据库全文SHA-256、字节数及metadata在导入前后核对。解包只接受两个普通文件，扩展头、链接、重复/额外文件、路径穿越与不支持的时间被拒绝。下载总期限180秒，单次连接/读取超时35秒；数据库大小上限2GiB，压缩包上限768MiB。导入通过既有固定SSH通道，不放宽VM出口。

存在管理扫描时拒绝维护。所有下载和暂存校验完成后才创建维护标记、暂停Harness，再次确认无活动扫描；原数据库目录和精确清单进入独立事务备份。新文件通过预检才恢复服务并完成记录。验证或启动失败尝试恢复原库；过程丢失留下维护标记，普通资源检查与新扫描先拒绝，不沿用健康缓存。请明确恢复，不重复提交更新。专用只读CLI的内部`--validating-update`仅让事务检查暂存后资源，不启动扫描或绕过网页/模型启动检查。

备份位于`/home/purge/tools/security-workbench/backups/<事务ID>/`；失败或进程丢失可能留下`incoming-*`暂存目录，需核对事务后处理，不自动清理不确定状态。备份不自动删除。本机制覆盖进程中断恢复，不承诺突然断电的跨文件原子性，也不限制用户在完全访问VM中自行运行的其他进程。扫描器镜像、通用Shell、原版能力和Mac隔离规则保持既有设置。

2026-10-29验收：366项插件、22项启动器及13项Python回归通过；同一13项Python测试在VM临时目录重复通过。现有官方数据库包通过新解析器；SSH导入传输以只读status验证。真实更新入口发现当前库与官方一致，仅保存核对记录，没有替换生产数据库或升级镜像。替换、校验失败和替换后进程意外退出的恢复使用自有合成夹具验证。当前120项程序及94项导出来源摘要匹配。安装前源码备份为`/home/purge/downloads/security-db-update-20261029T225823Z`；旧VM恢复点仍不含本期程序与运行资产。结构化验收见[security-db-update-verification.json](security-db-update-verification.json)。

## 恢复与真实模型验收

2026-10-29（America/Los_Angeles）：新建`ready-security-audit-20261029`，旧5点保留。停止服务后采集1568项证明，其中包括120项当前插件程序和4项安全资产（运行清单、规则、metadata、完整漏洞库摘要）；正常离线创建快照，附带5个宿主工具及2个启动定义。独立APFS磁盘副本实际恢复、注入辅助文件替换失败后的回滚和正常恢复通过，主盘未在该验收中改动，副本未注册/启动。随后日常VM冷启动1568/1568证明、120/120插件、固定镜像与全文漏洞库检查均通过，五组恢复覆盖matches。126项控制器回归通过；独立复核12项为重复覆盖，不累计。

真实DeepSeek使用已安装Harness原生headless入口及既有受限代理完成一次合成任务。当前会话先绑定`personal-security-model-20261029`，再由审计工具读取已确认范围、仅启动一次Semgrep、读取完成状态并取得报告，共5次工具调用。任务`00b5ba93-e595-4120-92c5-e9c6fb385e0c`完成，覆盖1文件，发现1条`policy.harness.python.eval`命中，保持unverified。持久SQLite、工具回执和完整Markdown报告一致；合成文件字节未改，真实项目未编辑。网页冷启动后可查看同一任务与发现。

验收保留三次尝试：首次测试命令未带现有代理环境，连接失败且未调用工具；第二次验收监督器误读官方JSON字段，在绑定时停止，核对没有扫描记录；修正事件解析并验证允许/拒绝控制后，第三次完成。不是一次无故障成功，也不由模型自述证明未发生任何网络或写入。模型连接有实际API用量，但未依据余额差值推算本次成本。headless profile中两个依赖agentPresets的预设入口处于pending，审计工具本身已通过实际调用；本次未测试网页发送聊天、全套工具或公网目标。

新恢复点和私有离线副本保存在本机，不上传Git。当前数据库、镜像与scope的边界仍按前文；副本恢复与主VM冷启动不等于已验证副本启动。结构化记录见[security-acceptance-verification.json](security-acceptance-verification.json)。

## 本地规则集 v2

2026-10-29（America/Los_Angeles），local-reviewed-2共16条本地规则，继续使用固定Semgrep CE1.182.1镜像。源码位于`work/harness-purge-improved/security-rules.json`，合成样例位于`tests/security-rules/cases.py/js/ts`；这些样例只供静态扫描，不能执行。每条都有预期命中与排除控制，按规则ID、文件及行号逐一核对。

| 规则 | 语言 | CWE | 预期命中 / 排除样例 | 复核重点 |
| --- | --- | --- | ---: | --- |
| `harness.python.eval` | python | CWE-95 | 1 / 2 | 动态 eval：请核对输入来源，优先使用受限解析器 |
| `harness.python.pickle` | python | CWE-502 | 2 / 1 | pickle 反序列化：请验证数据可信度，勿直接接受外部输入 |
| `harness.python.shell` | python | CWE-78 | 2 / 2 | subprocess shell=True：请核对命令构造，优先参数数组与 shell=False |
| `harness.python.yaml-load` | python | CWE-502 | 2 / 3 | yaml.load：请核对 Loader，优先 safe_load 或 SafeLoader |
| `harness.javascript.eval` | javascript, typescript | CWE-95 | 2 / 4 | 动态 eval：请核对输入来源，优先 JSON.parse 等受限解析器 |
| `harness.python.sql-fstring` | python | CWE-89 | 1 / 2 | SQL f-string 含插值：请验证绑定参数，避免拼接不可信值 |
| `harness.python.exec` | python | CWE-95 | 1 / 1 | 动态 exec：请核对输入来源，避免运行不可信代码 |
| `harness.python.os-system` | python | CWE-78 | 1 / 1 | 动态 os.system：请核对命令来源，优先无 Shell 的参数数组 |
| `harness.python.requests-verify-false` | python | CWE-295 | 2 / 2 | requests 关闭证书验证：请恢复证书校验或配置可信 CA |
| `harness.python.tempfile-mktemp` | python | CWE-377 | 1 / 1 | mktemp 只生成路径：请检查竞态，优先 mkstemp 或 NamedTemporaryFile |
| `harness.python.jwt-noverify` | python | CWE-347 | 1 / 2 | JWT 签名验证被关闭：请核对验证流程和允许的算法 |
| `harness.javascript.child-process-exec` | javascript, typescript | CWE-78 | 4 / 4 | 动态 child_process.exec：请核对命令构造，优先 execFile 参数数组 |
| `harness.javascript.dom-innerhtml` | javascript, typescript | CWE-79 | 2 / 4 | innerHTML 接收动态值：请核对转义/净化，纯文本优先 textContent |
| `harness.javascript.document-write` | javascript, typescript | CWE-79 | 2 / 2 | document.write 接收动态值：请核对输入与上下文编码 |
| `harness.javascript.tls-reject-disabled` | javascript, typescript | CWE-295 | 6 / 6 | HTTPS/TLS 证书验证被关闭：请核对并恢复证书校验 |
| `harness.javascript.sql-concat` | javascript, typescript | CWE-89 | 4 / 4 | query 字符串含拼接或插值：请验证占位符/绑定参数，核对实际数据库 API |

原6个ID保留；动态eval不再把纯字符串常量算作此项命中，subprocess规则限定标准库API而非任意shell=True关键字，yaml规则排除SafeLoader/CSafeLoader，SQL f-string要求实际插值。这些排除不意味着程序安全；例如恒定代码仍需按业务上下文审查。innerHTML经过自定义净化器仍可能命中，需要人工复核；规则不承诺跨文件数据流、所有别名/框架或可利用性证明。

运行时仅从SHA-256匹配且结构有效的规则文件生成版本、数量和语言摘要，空列表、重复ID或未知语言不报告就绪。新任务将该摘要写入持久记录和Markdown报告；旧任务不会回填为新策略。规则摘要变化会改变复测覆盖标识，旧策略下的清洁结果不能默认为新策略下已复测通过。默认忽略路径、单目标1MB上限、文件超时和总扫描预算继续有效。

真实固定镜像验证：34个预期命中、41个排除样例完全对应，Python/JS/TS三文件无解析错误。HTTPS Agent构造写法曾暴露漏检，补显式new-pattern后通过；失败记录保留。370项插件回归通过。安装后实际工作台任务覆盖3文件、收录34条unverified发现，合成字节未改；报告包含local-reviewed-2/16条。没有模型调用、真实项目扫描或公网请求。样例符合预期不等于生产环境零误报/零漏报。

本轮只升级本地策略与显示，不更换扫描器或漏洞库，不下载外部规则包，不自动修复或扩大权限。安装前备份`/home/purge/downloads/security-rules-20261030T015220Z`保留7个变更文件。当前整机恢复点仍为ready-security-audit-20261029，恢复会回到先前6条规则；本轮没有新快照。结构化验收见[security-rules-verification.json](security-rules-verification.json)。规则语法与样例标注参考[Semgrep规则语法](https://docs.semgrep.dev/writing-rules/rule-syntax)及[规则测试](https://docs.semgrep.dev/writing-rules/testing-rules)，规则为本地启发式编写，并非上游完整规则库。

## 依赖包身份与真实项目验收

2026-10-29（America/Los_Angeles）：Trivy依赖漏洞按规则、位置和原始包身份去重；同一CVE在同一锁文件里的不同包、版本或安装位置分别保留。页面、Markdown和扫描对比显示包名/版本，已有CVE和位置字段继续可用。新增security_finding_subject表，与发现/任务/观察快照同一保存点提交，不改写旧记录；旧Trivy缺包身份时明确提示，旧快照不推断新增/消失或干净复测。复测按包名及可用安装位置识别同一家族，升级后仍有同规则命中会重开；安装位置缺失时采取保守判断。

固定Trivy真实夹具返回18条、入库18条，同CVE/文件共6组跨包或版本记录。移除夹具中全部lodash版本而保留lodash-es后，指定lodash记录复测通过；对比仍存在6、未再次命中12、未知0。其余未命中记录不自动标成修复。夹具依赖未安装、样例未执行。桌面浏览器显示包身份并实际下载报告，同一CVE的三个包/版本均保留。

真实模型首次暴露工具加载早于资产库的问题。工具模块和组合配置均新增redteam硬依赖，先等待服务，再注册工具；已安装Cordis的延迟发布控制由66个提前注册变为0，发布后真实会话绑定通过。不是固定等待或自动重试。404项完整插件回归、126项控制器回归通过；22项客户端与7项身份测试均与完整套件重叠，不重复累计。

真实项目Phishing-Scam-Email-Detection：Semgrep检查146个文件，37条unverified，因website/static/i18n.test.mjs部分解析警告而保留partial/complete=0；该文件Node语法检查通过，本轮不修改源文件或放宽扫描完整性规则。Trivy完成5个依赖清单，58条unverified。完整报告共95条、3个任务（含一次headless中断），全部未验证；459个已跟踪文件摘要与Git提交未变，不把它们称为已确认漏洞。

长扫描使用持续网页会话。一次性headless在模型结束时会关闭工作台，因此本轮旧Trivy任务被标记interrupted且容器清理；核对后才在网页以新请求号启动一次。网页两轮共8次原生工具调用，先bind/status/start，再核对终态并report。原生会话归档中的部分工具文本被截断，完整报告由后端全库读取另行核对，不声称事件文本保留了所有返回字节。使用Standard或提供审计工具的红队预设；日常精简继续过滤专业工具。未运行ZAP、公网测试或自动修改发现。

最新整机点ready-security-validated-20261029包含123项程序、16条规则、运行资产、验收数据库和对应宿主入口。独立临时磁盘副本实际恢复、辅助文件替换故障回滚及磁盘检查通过，随后清理该临时磁盘；旧6个快照和既有离线副本保留，没有新增注册VM。主VM冷启动2051项字节摘要匹配；第2052项为活动聊天归档，原175058字节压缩内容摘要完整保留，只追加81字节的空session/end-seed事件，单独通过严格追加校验。五组程序/工具/配置覆盖均matches，不能将其写作2052项字节完全相同。副本没有启动，主VM冷启动与副本恢复分别验收。

[结构化验收与限制](security-trivy-verification.json)。旧合并证据不能自动复原；本轮未验证发现可达性、可利用性或项目整体安全性。未扩展Mac权限、共享或出网范围，未升级扫描器/漏洞库，未推送Git。

## 模型分页与长任务等待

模型工具redteam_security_audit的status现在返回全库计数、当前范围、工具就绪状态及最近3个任务的简要结果；不再返回500条发现。report默认section=findings、limit=5，支持1–10，按6000 UTF-8字节预算可能返回更少。必须原样传回page.nextCursor直到page.complete=true；section=runs用于任务历史。项目/范围/发现版本或任务状态改变时旧cursor会拒绝，从第一页重新读取，不能把读到的单页称为完整报告。显示字段可能缩短，完整证据和Markdown继续使用安全审计页“导出报告”。所有结果最终经项目脱敏后再检查预算，脱敏遮蔽任务/分页身份时明确报错，不能恢复秘密或猜测cursor。

启动start仍异步返回run.id，同一请求重试复用requestId。用action=wait、id=原任务ID、waitSeconds=30等待；默认15秒，范围0–30秒。timedOut=true只表示该次等待到时，不取消任务、不重发start；继续wait同一id。completed/partial/failed/cancelled/interrupted均应如实报告。这一阶段的一次性headless原本会在进程结束时关闭扫描；当前已改为VM独立后台持有，会话退出后任务继续，VM或后台服务停止仍中断，不自动重扫。本轮真实模型两次wait均取得扫描终态、3页读完；不是把headless改成常驻守护进程。

新任务保存扫描诊断的类型、路径、可用行号，最多20项并保留全部条数与截断标记；不收录原始报错消息/源码片段。页面和Markdown显示具体诊断，Semgrep的PartialParsing仍保持覆盖不完整，不通过忽略文件、删除警告或放宽complete来消除缺口。旧任务当时没有保存诊断则显示未知，不据当前结果回写历史。真实项目的解析缺口尚未消除，扫描器版本未升级。

411项完整回归、原生工具95条合成分页、真实DeepSeek9次调用及独立原生诊断任务通过。95条真实项目发现保持待验证，数据表未改。[结构化验收](security-followups-verification.json)。分页开发当期未新增整机快照；现在该接口和页面更新已纳入ready-security-workflow-20261029，独立文件备份仍保留，见restore.md。

## 解析缺口的上游核验

2026-10-29核对官方1.183.0发行，并下载验证ARM64候选镜像的15层及完整配置。实际在隔离VM无网络、源目录只读挂载同一i18n.test.mjs复制件，候选仍报告PartialParsing。没有采用候选替换现有1.182.1，也没有改写真实源文件、排除测试文件、忽略警告或把partial标成completed。候选已清理，保留小型验收记录；这是已确认的剩余解析限制，尚无经过本环境验证的修正，不以“升级最新版”作为已修复证据。真实95条发现未验证或修改。

[官方发行说明](https://github.com/semgrep/semgrep/releases/tag/v1.183.0) · [本机实测与恢复验收](security-workflow-recovery-verification.json)。

## 11行解析复现与受限绕过

已将1169行复制件缩到11行语法有效、逐行删除不可再约简的复现，不声称全局最小。单独正则与测试块能通过，组合上下文才触发，不能把HTML正则本身判为非法。repro/escaped/良性对照在固定1.182.1运行；正则`<`转义为`\x3c`后复制件解析通过，12组自建文本的匹配/替换一致。原项目未改变、未执行，仍保持partial，不将绕过样例说成扫描器修复。[复现文件](../work/harness-purge-vm/fixtures/semgrep-parser/repro.mjs) · [对照文件](../work/harness-purge-vm/fixtures/semgrep-parser/escaped.mjs)

## 独立后台任务所有者

当前网页与模型审计工具通过0600私有Unix socket共用VM后台所有者。原范围确认、发现状态转换、分页字节预算、扫描器/容器限制均保留。后台不可用时拒绝操作，不在调用进程内另起扫描。重试启动须复用requestId，wait超时不取消。实际合成验收包含调用方进程退出后完成、取消、服务重启中断与冷启动状态持久；没有新增模型API调用或修改真实项目。[完整边界](background-audits-clock.md)
