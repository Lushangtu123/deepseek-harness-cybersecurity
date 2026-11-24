# R3 复核器依赖快照

2026-11-11，本轮增加离线复核器快照与运行回执绑定。原先的入口摘要无法发现辅助模块变化；历史 Xinference 记录的补充依赖清单是在运行后披露，仍按历史诊断保留，不补写成预先冻结。

`scripts/reviewer_snapshot.py` 固定 `eval_evidence_batch.py`、`eval_guard_review.py`、`eval_import_review.py` 的完整字节、启动器摘要，以及本地不可变容器镜像 ID。三个模块当前只使用这些本地模块和受支持的标准库导入。新增静态 import 声明超出支持范围时先拒绝创建快照，后续扩展需独立评审。静态导入检查不是通用 Python 代码安全分析器。

快照创建后，原工作树修改不会影响已保存的字节。运行前核对调用者保存的快照摘要、全部文件和启动器，读取并核对项目清单、源码、扫描输出，然后把已读取的字节写入独立临时目录。容器只读挂载这份目录，以固定镜像、普通 UID、无网络、无额外能力和资源限制执行 Python `-I -B -S`。只分析项目代码，不执行被测模块。

运行结果保留快照、输入文件摘要清单、原始报告 JSON 和完成回执。回执绑定快照、数据集、质量冻结、输入、原始报告及起止时间。完成路径在清理命令成功、临时目录移除后返回；失败或超时不返回完成回执。超时可能遗留启动客户端，尚待补上进程组终止、CID 跟踪及独立 inspect 恢复核对；当前清理回执不证明强制终止路径已通过。调用方须保存返回结果及输入原件，并将每次真实验收使用的来源写入台账。

离线质量报告版本更新为 5，数据集、运行、冻结和策略输入仍为版本 2。冻结 API 的第五参数为快照清单；`identity.reviewer` 必须等于该清单的规范 JSON SHA-256。新运行在 `reviewerExecutions` 数组中提供对应回执。旧冻结和旧运行仍可诊断读取，缺少完整快照或回执会增加明确阻断原因。

## 操作顺序

1. 在隔离 VM 中，以当前受审源码创建快照，保存返回清单及其规范摘要。固定镜像必须已存在；工具不拉取镜像。
2. 将完整清单交给 `freezeReviewInputs(dataset, policy, identity, ledger, reviewerSnapshot)`，保存冻结原件与摘要；随后才开始扫描与复核。
3. 对每个复核批次调用 `execute(bundle, expectedSnapshotSha256, root, manifestPath, scanPath, datasetSha256, freezeSha256)`。`manifestPath` 使用既有批量复核格式：`files` 逐文件摘要、`scanSha256`、可选的导入请求或自动发现标志。所有路径使用绝对规范路径。
4. 保存每批完整返回值，把对应 `reviewerExecution` 收入运行记录的 `reviewerExecutions`。各批的项目副本、扫描结果、报告、来源台账、输出汇总映射交给独立发布复核。
5. 再运行离线质量评估。结构正确只表示绑定一致，普通检查 R3 仍须通过独立样本和真实证据验收。

CLI 对应 `freeze SOURCES DESTINATION IMAGE_ID`、`verify BUNDLE EXPECTED_SHA256` 和 `run BUNDLE EXPECTED_SHA256 ROOT MANIFEST SCAN DATASET_SHA256 FREEZE_SHA256`；使用 VM 的 `python3 -I -B -S` 启动。`review_quality_gate.mjs --freeze` 可在原参数后追加快照清单文件；不提供时兼容生成旧格式，后续准入会被阻断。

## 本轮验收与边界

Mac 和 VM 各 10 项快照专项、32 项质量门槛专项通过；Mac 全部 1,009 项插件回归通过。VM 用已有合成夹具完成真实容器运行，得到 1 条约束观察和 1 条跨文件观察，均保持未核实；入口不变时改动辅助模块也被摘要核对拒绝。Python 与 Node 的快照摘要、冻结与回执绑定一致。已有 Xinference 记录回放后保留全部旧阻断，增加依赖与回执缺口，诊断计数不变。

日常 VM 的 169 项程序、42 个项目库逻辑摘要及关键配置核对一致，临时目录已清理。本轮不改变扫描规则、阈值、来源台账或生产部署，没有新增独立准入样本。Claude Opus 5.5 high 完成本轮复审，无本轮阻断；[结构化结果](reviewer-dependencies-results.json)保存实际源码与运行摘要、测试和全部待处理建议。

这是受支持复核器的代码与运行时内容绑定。摘要和回执由本地流程声明，不证明封存时间、发布者身份、所有批次的完整汇总、真值正确或样本独立。运行仍信任 VM 内 Docker、启动器的宿主 Python 和 VM 内核；系统镜像 ID 固定 Python 与标准库，但不证明镜像发布者可信。增加复核模块或其他语言时需扩展清单与测试，不能套用现有三模块身份。

参考：[Python 隔离启动参数](https://docs.python.org/3/using/cmdline.html)、[Docker 容器运行与镜像标识](https://docs.docker.com/engine/containers/run/)。

发布前继续处理：回执来源覆盖机械核对和重复回执拒绝、超时/信号清理、大小上限与类型统一、VM UID/挂载路径校验及负面用例。清单与回执支持本轮受审闭包绑定，这些建议仍未完成。

后续[回执来源覆盖](reviewer-coverage.md)已补齐输入成员关系与相同输入批次去重；本页历史审查中的异常清理及其他建议仍按该步骤记录继续处理。

后续[超时、中断与原任务恢复](reviewer-cleanup.md)已按该步骤边界加固 N2；创建未知、长期记录保留及其他准入缺口仍继续记账。

后续[输入与类型边界](reviewer-input-boundaries.md)已处理 N3/N4 的当前固定合同，并限制完整任务记录的大小/嵌套以保证可重新读取；保留策略、独立证据与准入样本仍未关闭。
