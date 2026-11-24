## 2026-11-02 · personal.11 认证头源码脱敏

修复JavaScript认证头值被原始HTTP脱敏截断的问题。原始HTTP整行隐藏；源码仅接受有明确边界的字符串、简单模板或字面前缀加动态标识符，整个值替换，复杂形式拒绝。改动后的JavaScript使用Node语法检查，不执行源码；审计与运行副本共用同一逻辑。保留真实Semgrep解析缺口、受管范围、原请求与待验证状态。

## 2026-11-02 · personal.10 PhishGuard隔离运行模板

运行应用面板可选择固定PhishGuard FastAPI离线模板；依赖来自现有安装树的完整文件哈希和固定GNU/Python镜像，使用专用依赖目录及-I -S启动，不执行项目安装/构建脚本。运行容器network none，审计通过固定、限时的docker exec HTTP通道访问；静态运行资源和审计文本分别记录摘要，源码/资源变化会使关联未确认。ML模型、账号与外部核验关闭；服务器禁网不限制浏览器外链。保留标准库模板、明确确认、原请求恢复与独立期限。Mac入口与权限不变。

## 2026-11-02 · personal.9 运行应用面板

VM改进版安全审计页新增用户确认的标准库Python副本运行面板：显示副本摘要、就绪状态、估算期限、当前完整性和联合ZAP前后关联。预览不执行源码，临时文件立即删除；启动重新核对源码/范围/镜像。原请求先持久记录，子进程原子领取；取消会阻止延迟启动，页面/后台重启不重放启动。独立VM临时服务持有启动器；切换未确认时后台阻止扫描/联合任务/范围变更。模型不能通过新增RPC启动或停止应用，Mac入口和权限不变。

## 2026-11-01 · 容量网页与持续预警

存储工具新增 `--capacity-only`，复用逐层固定目录描述符读取文件系统计数，不遍历目录、不调用 Docker。现有 Mac 本机入口每60秒共享采样，网页展示宿主/VM容量、VM inode与预留线，聊天VM状态栏显示容量提醒。停止、失败、过期及睡眠/时钟变化有明确状态；数据只存于入口内存。没有清理、任务限额、系统通知、新启动项或宿主权限扩展。

## 2026-10-29 · Trivy依赖包身份

漏洞记录保留原CVE与文件位置，另以完整受限包名、版本、路径、PkgID/PURL区分身份；不同包不再相互覆盖。包身份在独立SQLite表中与发现及快照同事务提交，旧记录不回填或删除，明确提示历史可能已合并。快照v2保留包身份，新旧Trivy策略不混比，旧Semgrep/ZAP快照继续可读。复测按同包名/包路径核对，升级后同类命中仍会重开，缺包身份的旧Trivy记录不自动得出复测结论。页面、审计报告和对比报告展示包信息，动态Markdown保持字面文本。

## 2026-10-29 · 安全审计资料结构校验

页面采用新资料前核对范围、任务、发现、运行资源和可选总数的实际渲染字段，拒绝重复ID、页上限及矛盾计数。异常读取保留上次成功资料和草稿，明确标为未确认并暂停写入/导出，正常刷新后恢复。未知字符串状态和旧资料缺少可选总数继续兼容；后端扫描、数据库与权限不变，不将历史偶发空白归因于此。

## 2026-10-29 · 安全审计报告范围与汇总

Markdown增加全量发现状态/严重性和任务状态汇总，当前保存范围与各任务历史范围分别展示；任务版本、规则、漏洞库时间与覆盖取自持久记录，缺项明确未记录。汇总在明细达到20000条上限时仍覆盖全部记录；同一SQLite读取事务保持计数与明细一致。动态文本再次脱敏并按字面Markdown展示，不更改发现状态或推断安全结论。

## 2026-10-29 · 安全审计报告下载保护

导出报告绑定当前资料读取代次并核对返回项目；刷新、重检、卸载后的旧响应和旧按钮不再触发下载或覆盖错误。同步请求锁阻止快速连点，只有对应请求能解除导出忙状态；页面显示“正在导出…”。父组件既有项目key隔离保留，不更改扫描、数据库、范围或权限。

## Workbench v20 — 会话契约与只读恢复权限检查

- 会话响应校验完整数组、记录 ID、展示字段及统计；异常数据保持未确认，刷新前不提供记录操作，保留项目与请求代次保护。
- “复制 URL”只复制地址，保留成功/失败反馈和旧视图保护。
- 导出清单记录七个固定启动入口的 VM 权限；只读预检报告权限差异，仓库校验检查 Git 能保存的可执行标记，不自动 chmod。

# 独立改进版 1.1.77-personal.1

基于 YuJunZhiXue 的 dsh-purge 1.1.77（原仓库固定版本 ac58b3e）修改。原作者 NOTICE、Apache-2.0 LICENSE 以及原文件归属保留。这是本地个人派生版，不代表上游发行。

- 使用未打补丁的官方 Harness 0.2.1-rc.3 和独立 DSH_HOME；启动不安装无限授权提示词、不切换现有会话权限。默认采用人工审批；用户明确授权的专用 Linux VM 可配置 executionMode=vm-autonomous，仅当会话为 danger-full-access / never 时自动执行。其他部署不获得该例外，人工审批档位继续逐次确认。
- 面板及包入口禁用原版宿主 Apply、Revert、Update、Restart 和卸载补丁路径。需要重启请通过虚拟机版本入口；完整原版在另一个运行环境中保留。
- 证据默认是 claimed/operator-input。只有同一演练、操作、目标、参数和结果均匹配的原生工具回执才能升级；失败调用不生成成功回执，原声明保留。公开 verify 的默认值与 record 一致。
- 默认列表、HTTP 证据、报告和工具结果脱敏；凭据只允许单条显式查看。API 要求认证传输、严格 HTTP 同源和 application/json。脱敏不等同于加密或完整 DLP。
- 更新事务使用独立暂存、互斥锁和失败回滚；保留文件模式与启动器符号链接。不是跨进程崩溃原子事务；崩溃遗留目录需要人工恢复。改进版禁止自动安装上游覆盖包。
- 前端加入请求超时、过期响应隔离、凭据隐藏和漏洞列表分页。

回执目前覆盖 bash/read/glob/grep/write/edit/working_directory；不将任意 MCP 或模型自述作为真实回执。摘要和 SQLite 约束用于一致性检查；拥有 VM 完全控制的用户仍能修改数据库和程序，不能当作防篡改证明。

用户于 2026-10-25 明确选择保留改进版功能并允许 VM 内完全访问、自动执行。当前 VM 新会话默认 danger-full-access / never；现有会话保留原选择，可通过官方菜单改档位。专用 VM 身份由 Linux、/home/purge 和独立 DSH_HOME 配置范围共同限定；Mac 不获得完全访问。

VM 完全访问档位不使用工作区沙盒；人工审批档位仍受官方沙盒约束，其 Landlock 报告部分能力。VM 外围网络限制、宿主共享/剪贴板/USB 禁用保持不变。自动执行不授予访问 Mac 或更改隔离的权限。

2026-10-26：当前测试页切换/刷新取消旧请求并按请求身份释放锁；Shell工作台加入手动只读工具版本卡片，复用专用VM固定检查器及原有owner/同源认证，关闭取消查询；恢复状态扩展为程序、固定版本工具和非秘密配置的覆盖核对。没有自动升级或新增网络出口。

2026-10-26 wb5：版本检查每项目18秒独立预算，超时仅标记该项目，保留其他完成结果；恢复覆盖实时核对两份固定宿主启动定义摘要；界面只显示允许范围的变更文件名和处理建议，不显示配置正文或秘密。

2026-10-26 wb6：本机入口为普通HTTP正文增加15秒空闲期限和完整性诊断，SSE/WS保持长连接，不重放部分响应或写入；恢复核对增加固定6项官方核心模块及Harness包/入口依据，旧点明确显示未纳入；工具版本卡片显示分类中文原因、独立检查时间及单项重查，其他结果和时间保留，迟到或取消结果不会覆盖新结果。没有新增依赖、自动升级、网络出口或宿主权限。

2026-10-26 wb7：版本卡片使用客户端请求代次合并结果，VM校时回拨不再阻止新请求更新，UTC继续独立展示；专用VM控制器为启动/关闭/切换/恢复点/恢复加入统一进程间互斥与忙提示，内部嵌套可重入，状态读取不加变更锁；本机状态标识显示核对年龄，60秒后提示待重新核对，返回页面时节流只读刷新。原版、权限与网络隔离不变。

2026-10-26 wb8：导入项目分阶段显示，目录核对最多10秒、添加/打开最多15秒，可停止等待或关闭；未知结果只读核对、不自动重发，同页保留操作记录并用官方beforeOpen阻止迟到导航。终端进程核对有15秒期限和上次时间，失败历史标待核对，不关闭进程。恢复状态列出固定5个宿主辅助文件的差异，磁盘核对使用已校验归档辅助程序。原版、权限和网络隔离不变。

2026-10-26 wb9：导入确认前只读检查失败可重新检查，不混同已提交结果未知；当前ready工作区列表优先旧回执，移除记录需重新检查与明确确认才添加，替换ID使用当前值。诊断页增加HTTP最近异常和同类别后续完整成功事件，时间/递增序号/阶段与当前状态分开，最多100条，不展示原始错误正文或请求秘密。未知提交继续保护，不自动重发或重启。

2026-10-27 wb10：明确的 Gateway 参数/输入校验拒绝可重新检查后确认；仅在 create 阶段且保留 WorkspaceCreateError 结构时释放记录，invalid-path 可能包含落盘失败，仍按未知处理。超时、断连、未识别错误和成功注册后的打开失败不重发。诊断页显示记录读取/逐层观察时间与60秒到期，返回页面5秒节流读取，不把刷新记录当健康探测。宿主恢复写入采用独立临时文件和清理，失败时分别回滚磁盘/工具并检查，原版与权限边界不变。

## 2026-10-27 · v11 日常工具模式

新增 VM 专用“日常精简”原生预设，沿用当前官方 Standard 配置并在该预设内过滤 REA 与 redteam 原生工具。Standard、红队和既有会话保持；终端、文件、技能、浏览器及 CodeGraph 可继续使用。默认仅影响后续新会话；需要完整原生工具时在空白新会话选择 Standard/红队。筛选同时覆盖 schema 与分发，并随工具动态注册/移除刷新；不改变权限或 CLI。


## 2026-10-27 · v12 红队声明与入口

VM改进版直接用包内模板声明独立Red team mode，保留其指挥角色和流程，不运行上游预设安装器，不写另一套原版home。日常精简、Standard与PTC保持。窄窗口的工作台入口所在行允许换行；宿主入口提供只读恢复点/副本清单和保留建议，不恢复或删除数据，分配块不被当作可释放空间。


## 2026-10-27 · v13 角色项目隔离与隐藏焦点

角色提示词与数据工具共用持久会话/受信父链解析，从所属 RedteamStore 读取角色稿，不再读取全局 current。子会话有角色标记但绑定缺失、冲突或已失效时，装配明确报错并要求修正绑定；普通会话不受影响。隐藏挂件使用 inert 和 aria-hidden，已有焦点移至可见 VM 摘要，重新显示恢复原始属性且不抢焦点。


## 2026-10-27 · v14 项目配额与角色文件报错

项目内所有根会话共享名额，使用UUID预留并按原生子代理ID/运行批次关联释放；未知注册表或不完整分支拒绝新增占位。工具与面板共用状态，不以未核实状态表示空闲。名额仅覆盖redteam_agent_slot管理及原生注册表观察，不构成所有委派入口的强制拦截。角色稿缺失、读取失败或空白明确报错，附项目、角色和恢复路径。演练台区分当前聊天绑定与面板浏览，旧响应不覆盖新聊天，核对超过60秒显示待核对。


## 2026-10-27 · v15 编辑归属与状态时效

角色编辑器按项目核对读取代次和草稿归属；切项目清空旧稿并禁止未完成读取的保存/恢复，旧读取和写入结果不更新新项目。写操作不重放，切视图不声称撤销服务端已提交的保存。并发设置采用同目录临时文件、fsync及原子替换；损坏/不可读明确报错并拒绝新增名额，缺配置才按既定环境/默认策略。名额显示读取时间，60秒或时钟回拨后待核对；页面返回时节流只读刷新，不后台轮询请求。完整原版、宿主权限及VM隔离保持。


## 2026-10-27 · v16 重新核对与会话归档

恢复角色稿从提交起禁用旧稿保存；明确区分恢复已提交与回读失败，提供只读“重新核对角色稿”，旧界面回调也不能重存旧稿。并发字段只接受1至10整数和兼容的规范数字字符串，拒绝数组、布尔和隐式转换。项目根会话通过64条数据库分页完整核查，注册表最多8路并行并保留5秒期限，未知状态继续拒绝新增名额。智能体面板增加按需32条分页的会话绑定记录和可撤销归档；归档仅整理列表，保留会话与绑定，仍全部参与名额核查。完整原版、宿主权限和VM隔离保持。


## 2026-10-27 · v17 当前视图刷新与设置范围

并发保存成功后只核对当前面板项目；旧项目/旧刷新回调不能清空新视图或注入迟到状态，写入不因切视图撤销或重放。当前已挂载编辑器在保存期间锁定输入和重复提交，完成后解锁；页签卸载后成功结果通过页面内通知重新核对当前已挂载项目，不更新旧组件。全页刷新重新读取已展开的会话绑定列表并保留游标和筛选，收起时不查询，旧结果不覆盖新读取。界面明确“所有项目共用此上限设置，名额按项目分别计算”，保存说明影响所有项目；原有设置文件和计数语义保持。无新依赖、API、权限或网络出口。


## 2026-10-27 · v18 保存核对、草稿与诊断

并发设置写前校验明确返回拒绝；传输失败、超时、无效回执等保留结果未确认，失效旧名额并只读核对当前值，不重发保存，不把读回值当原保存回执。当前页面通知同时覆盖已确认和未知结果，不同步独立窗口。输入草稿与名额快照分开，同项目后台/全页刷新保留已编辑输入；可明确采用当前核对值，提交反馈保留至下一次提交/手动关闭/切项目。核查摘要记录时间、完成/总数、失败根会话和最多8条查询中的根会话；注册表异常只给固定类别，不回显原始异常。失败/超时摘要为当时快照，迟到结果不改写。保持8路、5秒、全部根（含归档）核查及未知时拒绝新增名额，原版/权限/隔离保持。

## 2026-10-27 · v19 会话隧道与恢复预检

会话隧道页按项目/刷新代次隔离读取，切换即隐藏旧记录，迟到读取、旧按钮、卸载回调不能操作当前视图；标记期间防重复，结果未知只读核对且不重发。面板主动检测继续禁用，界面提前说明原因与会话内按范围使用工具的方式。私有配置备份增加优化模式同样有效的完整性校验和只读恢复预检；不自动安装、覆盖配置、验证令牌或扩大宿主权限。

## Workbench v21 — 项目归属与环境编辑保护

- 得分表单、保存/删除与回执按项目和读取代次归属；切换立即隐藏旧操作，迟到响应/旧回调不影响新项目，未知结果仅只读核对。攻击链同样隔离旧读取。
- 环境页把核对快照与编辑稿分开，刷新保留未保存输入；“使用当前配置”才显式采用当前值。分配回执保留其他已编辑字段，请求期间的新输入也保留。
- 保存、自动分配按钮与Enter共用同步互斥；读取失败时暂停写入，修改结果未知时只读核对、不重发。无新增依赖或权限。

## Workbench v22 — 配置落盘、回执核对与未确认提示

- 环境配置在同目录私有暂存中写入/核对并同步后替换；替换前失败保留原文件，替换后同步/读回失败按未知结果处理。坏文件、不可读或不支持结构不自动重置，普通保存与分配被拒绝；首次缺文件仍可初始化。
- 环境保存回执携带请求标识并核对规范化提交字段；缺失/矛盾回执保留草稿并只读核对，不重发写入。标识仅用于关联，不是认证或幂等键。
- 得分未确认提示按当前挂载页的项目独立保留，刷新/A→B→A不清除；明确关闭只隐藏提示，不标记成功。不持久化原始参数或秘密。

## Workbench v23 — 完整报告、复现语义与项目归属

- 报告按完整命中集统一计分、过滤和封顶，Markdown完整导出；显式limit/offset仅对合并后的明细分页，coverage说明总量、已返回条数和是否完整。面板每页25条，导出和总分仍完整。
- 合成HTTP保留Host、查询串和正文，curl保留已知HTTPS、请求头与字面参数，原有真实curl保持原样。完整抓包不再裁到20k；分块等不能安全转换的请求保留原文并说明缺口，不伪称等价。Markdown代码块保留内容与换行，敏感内容仍按既有规则脱敏。
- 报告快照、复制/下载和异步反馈绑定项目及读取代次；旧首帧与回调不影响新视图。必要结构及直接渲染字段不完整时显示未确认，保留合法空报告和旧host无阶段分组的兼容路径。

## 2026-10-28 · v24 安全报告交付包

CLI `scripts/export-engagement-report.mjs --engagement <id> --out <父目录>` 每次新建 `report-随机值/bundle/`，包含 `report.md`、`manifest.json` 及正文实际引用的 `shots/`。`--out` 不再是平铺文件位置；原交付包保留，不提供覆盖模式。拒绝输出与整个 Redteam 数据目录相同、互相包含或经符号链接形成重叠；拒绝项目、数据库和图片中的不受支持链接。

报告在生成正文图片引用时同时生成完整附件元数据，与详情分页无关。只复制这些已登记附件；缺文件、非普通文件、缺登记摘要、字节数或 SHA256 不一致均失败。逐文件独占写入、读回校验，完成后在本次私有容器内重命名发布。发布前失败仅清理本次容器；发布后同步报错保留包并提示核对。清单提供正文和附件的大小及 SHA256，不含绝对源路径。它用于一致性复核，不是签名，也不证明证据真实性；图片像素不自动脱敏。未承诺断电原子性，意外终止可能留下未发布暂存，不能据此认定导出成功。无新依赖、自动上传、模型调用或权限变更。

## 2026-10-28 · v25 证据与初始化保护

截图登记使用独占创建，显式同名拒绝且保留原文件/记录；自动命名竞争重新选择名字，SQL或写入失败仅清理本次拥有的新文件。原摘要不被自动改写以掩盖损坏。文件系统与SQLite之间没有跨资源崩溃原子性保证。

旧得分迁移先独占写入完整点/命中归档，fsync、读回核对后以不覆盖旧文件的方式发布。无命中旧点也归档；归档或删除失败通过保存点回滚数据库并报错，已经完成的有效归档保留。归档目录异常/链接不被当作成功；既有得分页将读取错误显示为记录未确认。归档不是自动恢复工具或签名，仍保留既定内置旧点清理规则。

默认阶段和得分点补种采用针对code的冲突处理；阶段齐全时保留只读快路径，不额外竞争写锁；事务内在读取决策前取得写锁，支持外层事务，不覆盖阶段编辑或自建得分点。真实I/O/SQL错误继续传播，不重放任意写入；并发可等待既有5秒SQLite预算，持续锁定仍明确失败。不新增依赖、模型调用、权限或网络出口，原版保留。

## 2026-10-29：选择性回移上游1.1.82稳定性修复

个人版本1.1.77-personal.2，参考YuJunZhiXue/dsh-purge提交0c933dc7d3252698f3f0f9756932dcc88355f532。ZIP显式目录项改为创建目录；skills补fs导入恢复realpath重叠保护；主插件停用时清理旧redteam默认选择，热重载延迟清理可取消，服务重启时若profile仍引用插件则保留预设；只改完整预设ID，支持cordis.yml并避开符号路径。原版能力开关关闭不等同停用整个插件，不删除用户角色文件。

pnpm键污染修复仅通过统一启动器的显式维护动作执行，作用于合并版web profile。缺失workspace/构建配置不创建，健康文件不重写，false保留，重复的非本插件键或无法确认许可时停止；改写前保存私有备份并保留权限。没有引入上游自动profile插入、自动授权构建、父子会话权限继承、DSH NEXT适配或整包更新。core原子写权限保留及npm启动器软链保护已在本地版本实现，继续沿用。保留原版提示词、补丁表和既有角色/项目绑定。

安装目录保留tools/dsh-purge-personal-1.1.77-personal.1，以保持既有file:依赖引用；实际包版本以package.json为准。


## 2026-10-29 · Security audit phase 1

- Added project-scoped Semgrep CE, offline Trivy and VM-loopback ZAP baseline adapters; pinned official ARM64 images, read-only repository mount, one worker per service, bounded time/memory/output.
- Added the 安全审计 page and `redteam_security_audit` tool. Scope and finding review use owner-authenticated same-origin UI operations; the model audit tool cannot expand scope or approve findings. Existing VM shell/original capabilities retain their existing access.
- Durable request/run IDs, explicit uncertain-write retry, Unicode project support, cancellation and restart interruption handling. Findings begin unverified; equivalent-policy retests must prove original-file coverage; moved-line recurring hits reopen. Baseline ZAP JSON alone does not prove original-URL coverage, so absence cannot automatically close a ZAP finding.
- Markdown export independently reads up to 20000 findings and 20000 runs, declares any truncation; UI shows latest 500 findings and 30 runs with totals. No raw secrets/source snippets in normalized findings. Raw scanner artifacts remain private inside VM run directories and are excluded from the repository.
- External scanner images/databases are installed separately; a source restore does not itself recreate those large runtime assets. Semgrep uses six local starter rules, not a comprehensive rule pack; Trivy configuration checks use its embedded checks.

- Native socket verification caught upstream baseline startup retaining its first wildcard `-host`. A fixed per-run baseline hook now rewrites every upstream host argument to 127.0.0.1 and refuses an unrecognized startup shape; it does not alter the upstream image. Classic baseline mode is selected explicitly.

- Tool SDK lookup now handles the VM runtime's direct `<root>/lib/bin.js` installation independently of current directory. Registration and project binding are checked using the installed native SDK without a model request.

- Security API business rejections now use a structured `ok:false` acknowledgement after owner/origin admission, so the browser can distinguish a known revision rejection from an uncertain transport failure. Unauthenticated and cross-origin requests retain HTTP 401/403. Real HTTP coverage checks all three cases.


## 2026-10-29 · Runtime readiness verification

Scanner readiness now verifies local pinned ARM64/Linux Docker images, safe regular files, the Semgrep rule digest, Trivy metadata and the complete database digest/size. Thirty-second cached evidence is labelled; an explicit read-only recheck and each launch force a new inspection. Invalid/future metadata and missing/corrupt resources refuse readiness. A database older than seven days remains usable with a visible warning; this is a local reminder, not a vendor support policy.

Added a dedicated-VM-only `scripts/security-runtime-preflight.mjs` CLI. It inspects existing resources without running a scanner, fetching updates, changing access or claiming GitHub-latest status. No image/database update or new VM recovery point is performed.

## 2026-10-29 · Manual vulnerability database maintenance

Mac unified launcher option 9 checks the official GHCR Trivy DB schema-2 revision and supports explicitly confirmed update/recovery. Anonymous HTTPS downloads stay on Mac, with bounded archive entries and SHA-256 checks repeated in the dedicated VM. Active managed scans block replacement; a journal preserves the old database and exact manifest. Harness pauses only after staging and validation. Failed validation/startup restores the old files; process loss leaves a maintenance marker requiring explicit recovery. Readiness checks that marker before cached evidence. The UI shows instructions and the last controlled maintenance result. Scanner images, VM egress and Mac permissions are unchanged. This is process-interruption recovery, not a power-loss atomicity guarantee.

## 2026-10-29 · Local Semgrep review policy 2

Expanded the local offline policy from six to sixteen Python/JavaScript/TypeScript heuristics with positive and benign-control fixtures. Kept original rule IDs and reduced constant-eval, SafeLoader and unrelated shell-keyword noise. Runtime verifies rule identity and exposes version/count/languages; each new scan records that policy in its durable run and Markdown report. Changed rule digests produce different retest coverage identities. Hits still require manual verification; this policy does not establish data flow, exploitability or whole-project coverage. No automatic fix, external rule download, scanner upgrade or permission/network change.

## 2026-10-29 · Scan observation comparison

New complete scans store bounded normalized observations in a separate per-run SQLite table within the findings/completion savepoint. No historical backfill or automatic finding-status changes. A read-only same-project comparison requires matching scanner and policy identity, distinguishes new/persisting positions, covered-file absence and unconfirmed coverage, and never calls absent hits fixed. Exact rule/location matching can classify moved lines as changed positions. Legacy, incomplete, incompatible or oversized observations are explicitly unavailable. UI and bound model tool support exact run pairs; stale/foreign responses do not populate the current view. Each category and Markdown comparison detail is capped at 100 with full saved-snapshot counts and explicit truncation. Existing full-access VM capabilities and host isolation are unchanged.

Native real-project acceptance exposed a service-order race: tools captured an empty fallback if the asset store had not yet published. Both the tools export and bundle now require tools plus redteam, so Cordis waits for the store; no fixed sleep or retry is used. The installed Cordis integration control activates the tools before publishing the store, then checks a real session binding after publication.

2026-10-29 Harness follow-ups: model-only status is a compact summary; report uses version-checked finding/run pages and a6000UTF8-byte budget instead of returning a full Markdown blob. Native tool serialization preserves compactJSON; full UI/export unchanged. New wait action observes one exact task for0–30seconds without launch/retry and documents one-shot headless lifetime. Source-free scanner diagnostics (type/path/line,20items with total/truncation) persist with results and display in audit/report. Old partial runs have unknown reasons unless originally recorded; no silent backfill or weakened coverage rules.


## 2026-11-01：本地会话扫描与解析缺口补查

安全审计范围可保存可选的 ZAP 私有会话配置名。Cookie 或 Bearer 值仅存在 VM 用户私有配置及临时扫描副本，不存入网页范围、模型结果或公开导出。配置绑定明确的本地 origin、期限和校验页面，控制器与 ZAP 在扫描前后各自核对；核对失败不计完整认证扫描，不保证全程持续登录。退出路径排除、跨 origin 头隔离、临时副本清理与固定镜像禁止动态插件下载一并启用。

VM 脚本 `scripts/security-local-lab.py serve` 提供临时合成表单登录靶场；`import-session NAME` 从标准输入导入私有 JSON，不通过命令行参数接收凭据，不覆盖已有名称，不自动处理真实登录、MFA 或续期。

Semgrep 解析失败文件可获得有限文本补查：最多尝试20个候选文件，每个1MB、总读取8MiB，跳过链接及越界/二进制/超大文件。只匹配 eval、innerHTML 赋值、Function 构造字样；注释及字符串也可能命中。提示为 info/待验证，原 PartialParsing 和不完整覆盖保留，不能据此自动关闭发现。

## 私有会话生命周期与恢复

新增仅元数据的到期状态及显式新名称重新导入；不修改旧私有文件，不通过页面接收凭据。安全审计可见恢复会取消旧状态读取，按已有15秒期限重新核对；30秒周期检查长间隔/时钟回拨、只读失败和所选会话到期，不自动重发写入，保留草稿与未确认请求。使用方法见导出仓库 docs/session-lifecycle.md。

## Semgrep 离线解析自检

新增 scripts/security-parser-check.py，只在专用 VM 对五个内置合成夹具运行固定本地镜像，不拉取或升级，不执行源码或扫描真实项目。原始复现、转义对照、良性、规则阳性与非法语法均参与门禁；当前已知缺口返回 exit 2，控制失败返回 1，全部通过才返回 0。这个手动候选验收工具不修复解析器，不改变已有 partial 或待验证发现。

## 扫描器候选准入与输出限制

新增固定本地 Semgrep 镜像候选的合成自检、显式切换和中断恢复；重新核对清单摘要并保留原清单，候选不合格不切换，不下载镜像。Mac 统一启动器选项11。扫描器输出改用64MiB容器临时目录，自检16MiB，输入只读、日志不落Docker日志文件，结果按8MiB/认证回执1KiB有界输出。既有Semgrep解析缺口仍保留；本轮不更换扫描器镜像。

## 存储监测与清理预览

新增VM只读容量、inode、目录元数据与Docker汇总；Mac启动器选项12复用恢复目录显示主盘、快照及归档镜像的保留/待核对依据。当前没有删除、apply或自动清理入口，也不自动启动VM或设置定时监测。读不到、预算截断、COW共享空间均明确标注；候选不代表删除授权。
