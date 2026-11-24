> 当前版本、恢复点和完成状态统一见[当前状态](current-status.md)。本文的历史验收段落只描述当时结果。

<!-- security-reload:start -->
# 历史阶段：恢复点：ready-security-reload-20261030

当时127项程序，新点`ready-security-reload-20261030`。独立磁盘副本实际启动后2614项选定稳定摘要与127项程序匹配，原盘换回运行、临时副本清理；旧12点保留，共13点，5个宿主辅助工具覆盖匹配。部署前备份为VM的`/home/purge/downloads/security-reload-ssh-20261030`与宿主原安装根的`setup/before-reload-ssh-20261030`。

本地196项Python（23文件，其中控制器155项/19文件）、443项插件Node、124项入口Node、客户端重建一致性及7项部署故障控制通过，定向复测不累加。真实浏览器在后台成功后收到损坏回执，完整重载与关闭重开仍保留原请求，明确重试未产生重复事件；原VM冷启动后稳定入口读取及恢复徽标通过。SSH真实受控异常和独立菜单采样通过，但旧断连未复现，根因仍未确定。

真实项目459项受跟踪文件、HEAD与6张审计表不变，95条全待验证；无新模型调用或扫描，无运行中审计任务或扫描容器。宿主权限、VM网络/共享及另外3台停止VM不变。整机恢复会回退点后数据；Git不含磁盘和密钥，不能仅靠clone恢复整机。[结构化验收](security-reload-verification.json) · [操作、存储与采样限制](reload-recovery-ssh.md)。以下为历史分阶段记录。
<!-- security-reload:end -->

<!-- security-pagination:start -->
# 历史阶段：恢复点：ready-security-pagination-20261030

包含127项插件程序、分页/诊断更新、扫描运行资源及当前来宾配置，5个宿主辅助工具均匹配。保留旧11点，共12点。2612项选定稳定摘要与127项程序已在独立无backing磁盘副本实际启动后匹配；复用原虚拟硬件，换回原盘并正常运行，临时副本已清理，没有注册新VM。选定摘要不是整盘文件数。

部署前程序备份在VM的`/home/purge/downloads/security-pagination-ci-20261030`，宿主控制器备份在既有安装根的`setup/before-pagination-ci-20261030`。回退前结束审计并停止所有者和网页服务，保留数据库；整机恢复沿用原确认流程，会回退点后文件、聊天和项目数据。Git不包含磁盘、Docker层、密钥或审计数据库，不能仅靠clone恢复整机。[本轮验收](security-pagination-verification.json) · [诊断与操作](audit-pagination-diagnostics-ci.md)。以下为历史恢复说明。
<!-- security-pagination:end -->

<!-- security-lifecycle:start -->
# 历史阶段：恢复点：ready-security-lifecycle-20261030

纳入停机探针修复及当前来宾配置，保留旧10点，共11点。此点已在独立磁盘副本上实际启动：2609项选定稳定摘要、126项程序与原生状态查询匹配；自动换回原盘并恢复日常入口通过。复用原UTM虚拟硬件，没有新注册VM；三个临时测试磁盘已清理。选定摘要不等于整盘文件数，恢复仍会回退点后数据，沿用原确认流程。[详细验收](security-lifecycle-verification.json)。以下为历史说明。
<!-- security-lifecycle:end -->

<!-- security-background:start -->
# 历史阶段：后台版本恢复点

使用`ready-security-background-20261029`：126项插件程序、私有后台用户服务与socket定义、最新合成后台验收数据库均纳入整机。原VM冷启动2607项选定稳定摘要全部匹配；独立离线副本恢复/故障回滚通过，副本未启动/注册。旧9点保留，共10点。

恢复会回退点后数据，仍按原确认流程。VM后台服务与socket配置随整盘恢复；服务恢复后不自动重跑中断扫描。Mac本机入口在运行期间调度校时，没有新增LaunchAgent或外部NTP。[验收](security-background-verification.json)。以下为历史恢复说明。
<!-- security-background:end -->

<!-- security-diagnostics:start -->
# 历史阶段：诊断版本恢复点

使用`ready-security-diagnostics-20261029`：覆盖当前124项插件程序、5个宿主辅助工具、2个启动定义及解析复现资料。原VM冷启动2580项选定稳定摘要全部匹配；独立离线副本恢复/故障回滚通过，副本未启动/注册。保留旧8点，共9点。宿主SSH私有诊断历史属于运行记录，不导出到Git，不能把guest-proof称为完整整盘清单。

恢复会回退点后VM数据，仍按原确认流程操作。Mac共享、剪贴板、USB与出口限制不变。[本轮验收](security-diagnostics-verification.json)。以下为历史恢复说明。
<!-- security-diagnostics:end -->

<!-- security-current:start -->
# 历史阶段：整机恢复点

使用`ready-security-workflow-20261029`。包含当前124项插件程序、固定运行资源、最新分页/等待/具体诊断和验收数据库，5个宿主辅助工具与2个启动定义。2058项选定稳定摘要在服务停止后采集，正常关机创建快照；原VM冷启动全部匹配，程序/核心运行时/工具/配置/已导入插件五组覆盖matches。

独立临时磁盘副本的恢复、故障回滚及磁盘检查通过，副本未启动/注册并已清理。保留旧7点，共8个快照；UTM注册总数4，只有1台是本任务的Harness，另外3台已停止且未动。仅排除已知活动聊天归档的跨启动字节对比，聊天仍在整机磁盘恢复点内。

恢复仍需原有明确确认，会回退点后聊天与项目数据。此前源码/SQLite备份继续保留；其“最新源码不在整机点”是历史状态，现在本轮功能已纳入新点。宿主控制器安装前备份见结构化回执。没有增加VM共享、剪贴板、USB或宿主完全访问。以下为各历史阶段。
<!-- security-current:end -->

<!-- security-followups:start -->
# 本轮模型工具与诊断更新的回退

当时运行124项插件程序。7个程序文件安装前字节/权限保存在`/home/purge/downloads/security-followups-20261030T045426Z`，并备份11个现有项目SQLite库；最终标识边界单模块修正前保存在`/home/purge/downloads/security-followups-boundary-20261030T045508Z`，并备份12个库。两批项目有重叠，不能相加视为23个独立项目。回退全部本轮更新时，在结束活动任务后按第一份备份恢复6个既有文件，并处理本轮新增personal-security-model.mjs，然后重启、核对摘要；只回退后续单模块补丁使用第二份备份。本轮未改schema，无需删除表或还原项目数据库来回退源码。

整机点仍`ready-security-validated-20261029`，包含上轮123项程序和16条规则。本轮源码、模型合成会话及诊断任务未纳入该点；恢复会回退本轮及点后数据，沿用原明确确认入口。本轮无新整机镜像/快照，旧恢复点和宿主隔离不变。以下保存历史阶段说明，以本节为最新状态。
<!-- security-followups:end -->

# 恢复与路径说明

## 历史阶段：恢复点与本轮备份

当前为`ready-security-validated-20261029`，已包含123项插件、local-reviewed-2的16条规则、运行资产、真实项目/合成验收记录及5个宿主辅助工具、2个启动定义。独立离线副本的恢复/故障回滚/磁盘检查及原VM冷启动验收通过；2051项字节摘要匹配，1项聊天归档通过原压缩前缀及单条初始化追加校验。保留旧6点，共7个快照；仍只有1台注册VM。本轮临时磁盘副本验收后已清理，原先离线镜像不动，未验收副本启动。

第一批7个程序变更的备份为`/home/purge/downloads/security-trivy-20261030T035659Z`，同时备份9个现有项目SQLite库。服务依赖修复前3个文件备份为`/home/purge/downloads/security-service-order-20261030T040759Z`，同时备份11个库。两批有重叠，不能将其相加当作20个不同项目。宿主控制器另有安装前备份，见结构化回执。

回退源码须先结束任务并核对所选批次；新增security_finding_subject表可保留，不应为回退源码删除表、重写旧发现或丢弃原证据。整机恢复会回退该点之后的聊天/项目任务数据，沿用已有明确确认入口。旧包证据曾合并的记录无法靠新增表复原。

[本轮验收](security-trivy-verification.json)。以下保留历史阶段的文件数量、恢复点及当期描述，以本节为当前状态。


## 审计资料结构校验的源码备份

当时仍122项插件程序。本轮仅更新`client.js`、`lib/redteam/personal-security-client.mjs`及`PERSONAL-CHANGES.md`，原字节与权限保存在`/home/purge/downloads/security-status-20261030T032530Z`。需要回退时先结束活动任务，恢复这三个文件后重启并核对；无需删除数据库或更换扫描资产。当前整机恢复点未更新，仍不含本轮修复。下文保留历史阶段备份。

## 报告汇总与历史范围的源码备份

当时122项插件程序。报告汇总更新的安装前备份为`/home/purge/downloads/security-report-20261030T024230Z`，保存原`PERSONAL-CHANGES.md`和`lib/redteam/personal-security-workbench.mjs`；新增`lib/redteam/personal-security-report.mjs`当时不存在。单独的旧网址缺项显示修正前备份为`/home/purge/downloads/security-report-legacy-20261030T024743Z`，只含新报告模块的先前版本。

回退整个报告汇总更新须在无活动扫描时恢复第一份备份的两个旧文件，并移除本轮新增报告模块，再重启并检查。只回退旧网址显示修正则使用第二份单文件备份。无需删除或回退项目数据库；本轮没有schema或扫描资产变更。当前整机恢复点仍为较早的120项程序/6条规则，不含最新报告功能；本轮未创建整机快照。以下小节保留各历史阶段的文件数量与备份。

## 报告下载保护的源码备份

本轮仅更新`client.js`、`lib/redteam/personal-security-client.mjs`及`PERSONAL-CHANGES.md`，安装前字节与权限保存在`/home/purge/downloads/security-download-20261030T022716Z`。当前121项程序摘要一致，扫描器、规则、漏洞库及项目数据库未更新。需要回退时先结束任务，恢复这三个备份文件并重启服务；无需删除数据。当前整机恢复点仍不含本轮修复。

## 扫描对比更新的恢复差异

当前插件121项程序，新增同项目扫描观察快照及只读对比。精确源码备份位于`/home/purge/downloads/security-compare-20261030T021036Z`，覆盖5个已有文件；新增`lib/redteam/personal-security-comparison.mjs`在回退源码时移除。先结束活动任务再恢复，保留项目数据库及新增`security_run_snapshot`表，旧源码忽略该表；不删除历史数据。数据快照不进入Git导出。

整机恢复点`ready-security-audit-20261029`仍为创建时的120项程序与6条规则，不含最新16条策略及扫描对比；恢复会回退之后的数据和程序。本轮没有新增整机快照，部署仅改变插件源码并通过运行资源预检。当前文件备份不等同于最新整机恢复点。详见[对比使用与验收](security-audit.md#扫描结果对比)。

## 本轮规则更新的恢复差异

当前运行local-reviewed-2（16条规则），恢复点ready-security-audit-20261029保留上一轮6条规则及旧页面源码。因此当前恢复覆盖显示差异是预期结果；本轮没有新增整机快照。7个变更文件（5个插件文件、规则、运行清单）安装前原始字节与权限保存于`/home/purge/downloads/security-rules-20261030T015220Z`。回退本轮必须在无扫描时同时恢复程序、rules.json和images.json，并执行运行资源预检；不要单独更换规则以绕过摘要核对。

## 历史阶段：安全审计恢复边界

当时恢复点`ready-security-audit-20261029`已包含120项插件程序、已安装扫描器Docker数据、Trivy漏洞库和对应宿主入口；1568项证明摘要在服务停止后采集，正常关机创建磁盘快照，日常VM冷启动后全部匹配。恢复点元数据、规则和漏洞库metadata进入固定覆盖检查；完整数据库另做全文摘要与运行资源预检，不在页面轮询中反复哈希大文件。

独立APFS磁盘副本实际执行了恢复、宿主辅助文件替换故障的回滚与正常重试，磁盘检查通过；副本没有注册或启动，主盘没有在副本验收中回退。日常VM冷启动是单独验证，不能把两者合称“副本启动通过”。Git仓库仍不包含Docker层、漏洞库或审计数据，单靠clone不能重建整机。详见[验收记录](security-acceptance-verification.json)。

手动漏洞库维护通过Mac统一启动器选项9执行，数据库事务备份独立于整机恢复点。恢复后同时执行原Python配置预检与安装目录中的`security-runtime-preflight.mjs`，见[安全审计说明](security-audit.md)。恢复该点会回退创建后产生的文件、会话和数据库；先结束任务并正常关机。

## 历史阶段：机器

日常网页入口为 `http://127.0.0.1:49226/`；底层转发为49224，SSH为49223，受限出口为49222。仅允许本机连接。私有登录链接由当前机器的启动器更新，不保存在仓库中。

当前 VM 用户为 `purge`，改进版配置根为 `/home/purge/.dsh-improved`。`guest-home/` 下文件按 `/home/purge/` 的相对路径排列。改进版程序部署位置是 `/home/purge/tools/dsh-purge-personal-1.1.77-personal.1`，对应仓库的 `work/harness-purge-improved/package/`。

`runtime-overrides/@deepseek-ai/<模块>/` 对应 VM 中 `/home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai/<模块>/`。这些文件是当前 VM 的改动副本，配套安装版本是0.2.1-rc.3；不要覆盖Mac的官方运行时或其它版本。

保留的完整原版使用独立配置 `/home/purge/.dsh`；合并版共用 `/home/purge/.dsh-improved`，通过 `.config/harness-original-capabilities` 选择日常运行时或 `/home/purge/tools/harness-original-capabilities` 原版运行时副本。启用状态会保留至明确停用，不能通过同一个端口同时运行两套服务。[界面开关说明](original-capabilities.md)。

仓库保存当前开启状态的标记、切换控制器和插件适配源码，不包含完整原版安装或62,988项运行时副本，不能仅凭本仓库重新创建原版底层补丁。原版 dsh-purge 为1.1.77，原有98项程序在合并恢复准备时核对未改。当前本机恢复点为 `ready-security-audit-20261029`；保留ready-recovery-proof-20261029、ready-recovery-resume-20261029、ready-recovery-guard-20261029、ready-original和ready-toolchain-20261025，共6个快照。先前1份离线镜像与本期1份独立验收磁盘副本均保留。历史校验归档仍保留，但已删除快照的旧点无法仅凭这些元数据恢复。四角停靠、窄屏排版和桌宠恢复入口继续可用，贴角选择仍为当前站点本地偏好，不在VM磁盘或Git中。

恢复管理首批同时读取两份清单，之后按快照或镜像独立续读、独立缓存；镜像续读不再重复查询磁盘快照或核对恢复归档，快照续读不扫描镜像目录。首批固定当前恢复点、原版与工具链基线及最近三个改进恢复点；基线缺失或磁盘元数据不可读也保留对应说明。磁盘快照每批最多80项，镜像每批最多16个归档条目。两份列表各自保留已加载记录和重试位置。实际快照和状态待确认项显示在主表，已确认无磁盘快照的历史记录另行折叠展示，不计入快照数量。公开快照名称最长240字符，无法公开显示的名称明确提示缺口；读取期间目录或快照集合发生变化后请刷新。

恢复manifest/proof JSON上限2 MiB，辅助脚本与启动定义上限8 MiB，摘要以64 KiB分块读取。路径从固定目录逐级拒绝链接，非普通文件立即拒绝，损坏结构、错误时间或摘要不匹配使对应归档校验失败。建立恢复点使用已校验的证明文件字节；恢复时在首次写入前固定目标及回滚辅助文件的字节，再执行和应用。归档错误不会阻断VM实际版本读取；这些保护不构成对恶意宿主并发修改的全过程事务或数字签名认证。

镜像扫描保留512目录、80镜像、5层深度和2秒预算，跳过已知辅助代码目录；单归档达到目录、镜像或时间预算时返回有界内部游标，下次可继续该归档。目录条目、深度或读取错误仍显示缺口。正常存在下一批不等于扫描缺口，页面只读且不删除恢复资料。历史v28/v29扫描限制记录仅说明当轮实现。

异常列表结构拒绝读取，保留旧行及续读位置；无法显示的记录、未知限制或条数裁剪显示不完整，不能当成正常空清单。失败提示显示固定错误分类和请求编号，`/__harness/health` 可核对同一编号的阶段、耗时及允许公开的退出码/信号。控制器超时或被终止合并为一个分类，不从信号猜测唯一原因。最多保留100条进程内记录，重启入口即清空；不保存查询参数、原始stderr、路径、正文或凭据。此更新不能补回旧验收缺失的请求信息，历史偶发失败的触发原因仍未证实。

此前清单可靠性修复阶段没有新建恢复点；其宿主入口更新现在已纳入ready-security-audit-20261029。较早小节中的恢复点名称和验证数量属于历史阶段，不表示当前仍使用旧点。

恢复当前机器使用统一入口 `Harness.command` 的选项6正常关机，再选7恢复，并保留完整离线恢复归档。恢复会回退恢复点之后的文件与会话，先正常结束任务并关闭 VM；控制器会检查版本、VM身份、隔离和归档完整性。仓库中的恢复点名称是来源记录，git clone 不会创建这些磁盘快照。v19的只读恢复预检不是恢复命令；在VM内从本仓库运行 `python3 -B scripts/restore_preflight.py --json` 只列出安装缺项和差异。

## 新机器或仅恢复配置

先准备匹配架构的 Linux VM、用户 `/home/purge`、Node/Harness、REA、Ghidra、Java、CodeGraph、reverse-skill 和 PentAGI 等依赖；`inventory/export.json` 中记录版本及来源。插件的当前 profile 使用固定 `file:` 路径，须先恢复或安装到对应目录，不能直接在仓库目录运行这个 profile。

按相对路径核对配置，备份目标机器现有内容后再手动迁移。配置包含 Harness 的 `!!js` 标签，它是运行时配置语法；普通 PyYAML SafeLoader 不支持此标签。备份本身保留原字节，完整性检查不会执行该标签。

DeepSeek API 凭据须在目标 VM 的本地凭据存储重新配置；本仓库没有密钥，也不复制宿主其它账号。PentAGI 的 `secrets.env`、管理员信息、连接令牌及数据库必须另外在 VM 内重新准备。保留 Compose 里的 `${...}` 引用，不将实际值提交 Git。

Mac宿主工具以当前UTM单机安装为目标，位于 `~/Library/Application Support/Harness Purge Original/host-tools`；VM UUID、端口、LaunchAgent和固定安装路径需要与本机一致。五个工具的源代码已保存；SSH信任、密钥、seed ISO、磁盘、恢复清单、LaunchAgent实际安装状态均不能从仓库凭空恢复。不要在陌生机器直接运行管理脚本来替代VM初始化。

VM内自动执行授权仅适用于这台隔离VM，不授权宿主完全访问或其它外部目标。保留宿主共享、剪贴板和USB关闭，以及受限出口代理。

## v20 执行权限预检

`executionRequirements` 记录七个固定 VM 启动入口的权限：启动器和 PentAGI CLI 为0700，其余五个命令入口为0755。预检同时核对内容、精确权限与当前用户可执行性，缺项、差异或不安全路径都失败；不会 chmod 或自动修复。Git 只保存可执行类别，clone 后0700可能成为0755：仓库字节/类别校验可以通过，VM精确权限预检仍会报告差异，由你决定如何恢复权限。预检观察不能保证稍后执行成功，也不认证令牌、服务或容器可用性。

## v22 环境配置读取失败

环境页配置路径为 `/home/purge/.dsh-improved/redteam/config.json`，整个VM共用。损坏或无法读取时先保留原文件和错误状态，核对权限与格式，或从本机有效备份恢复；页面不会覆盖重置。不存在的文件仍使用默认值，首次明确保存才初始化。不要删除故障文件来绕过保护。

同目录原子替换保留普通权限位，不承诺原所有者、ACL、并发进程统一锁或断电恢复。保存结果未确认时先只读核对当前状态，避免重复写入；读回一致也不代表原保存请求取得了有效回执。
