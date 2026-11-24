# P0 API 与数据草案（未注册、未部署）

依据 v1.3 B4/B5/B8/B12/B14。此文件定义下一批对接目标，不是现有 RPC 清单。旧 `securityStatus`、`securityStart`、`securityWait`、`securityReport` 和联合审查操作继续保持现有行为。

后续候选源码已经通过现有 `securityJoint plan mode=ordinary` 接入[只读规则计划](ordinary-calibration.md)，返回 `ordinaryPlan`。这不是新增 `workspacePreview` RPC，普通启动仍因缺 R3 拒绝；普通提交现已核对 v3 计划摘要、步骤和时限。候选版已补入副本身份与 S1 运行时限。下表的持久资源预留与完整工作区接口仍属草案。

## 操作与后台归属

| 候选操作 | 输入 | 返回/作用 | 阶段与约束 |
| --- | --- | --- | --- |
| workspacePreview | 绑定项目、模式、范围修订 | 后台构建路径清单/内容摘要，返回元数据计划及缺口 | P1；只读，不创建任务、不唤醒 Kali、不调用模型 |
| workspaceStart | 计划摘要、范围修订、请求 ID | 持久预留后返回原任务 ID | P1；再次核对内容、策略、工具/S1身份、期限、预算；不信任浏览器/模型提交的就绪或授权字段 |
| workspaceTask / workspaceWait | 原任务 ID、修订游标 | 四维状态、步骤、下一页游标 | P1；断线后查询原任务，未知结果不重发 start |
| workspaceCancel | 原任务 ID、请求 ID | 停止请求与清理核对 | P1；停止未确认单独表达，不先报告完成 |
| workspaceProblems | 项目、筛选快照、稳定游标 | 派生标签/排队、观察、总数 | P1；完整汇总与分页分开；换对象或旧修订不串数据 |
| workspaceDisposition | 问题 ID、修订、结论、理由/有效范围/期限 | 带历史的新修订 | P2；按类别及迁移表校验；风险失效同时暂停关联规则范围 |
| workspaceVerify | 项目、选择类型、问题/筛选快照、请求 ID | 原核实任务 ID与步骤 | P3；只为受支持且隔离就绪的问题选择验证器 |

不新增任意 Shell、工具参数或镜像选择字段。授权暂缓条款在实施相应操作前单独评估；本文不改动现有授权判定。

## 预览与持久记录

`previewWorkspacePlan()` 是本地纯函数的 P0 静态元数据预览。它接收未来后台产生的文件清单与就绪记录，不直接接受网页/模型提供的凭据、执行命令或授权结论。返回 `previewOnly:true`、`executable:false`；`eligible-preview` 只是候选选择，不可直接调用执行器。现已附`policy`与`budgetAssessment`，缺预算显式不可用；预算对象为`task/steps/nowMs/scopeExpiresAtMs`，步骤ID与选中工具一一对应。

Schema 的 `plan`/`step` 是持久对象草案，和纯函数的 DTO 分开：后台加入 `kind`，按“计划摘要＋工具”生成稳定步骤 ID，并生成 `stepIds`；逐步填写预算、身份和初始四维状态。未就绪步骤保留缺口；缺预算、来源或准入证据时，不能把候选预览转换为执行计划。普通计划与深度静态候选使用同一合同，动态/逆向步骤在后续阶段增加受管适配。

工具身份包括 `imageId` 与 `policyIdentity`。后者由版本化规则/配置/数据库等实际身份构成；后台生成，不能用输入路径或工具版本字符串代替。预览中的身份变化会改变计划摘要，执行时还须再次核对。

## 九类对象与语义

| 对象 | 关键边界 |
| --- | --- |
| plan | 输入/范围/模式/步骤/预算；P0 草案不可执行 |
| step | 目的、输入、工具/策略身份、隔离档位、额度、证据目的地与四维状态 |
| observation | 原生规则/严重性与统一严重性分别保留；置信度可未提供；证据可追踪 |
| problem | 检出/处置/修复三维、修订、回归标记、公告撤回原因、资料未知与临时标志 |
| evidence | 内容摘要、来源步骤、类型、大小、脱敏与留存；不保存凭据明文 |
| coverage | 文件/组件/HTTP 分母分开；未知分母为 null，不能补零伪装完整 |
| verification | 验证器/版本、条件、对照与证据；未复现不自动改成误报 |
| intelligenceMatch | 精确组件版本/公告身份/来源修订；匹配、撤回与补丁状态分别存储 |
| notification | 去重身份与实际送达状态；只在有意义变化时提醒 |

`problem` 投影给 `findingView()` 时只传显示需要的字段；`detectionReason:null` 与没有特殊原因等价。后台另行核对处置当前有效性，传 `dispositionValid`，不从“接受风险”标签推导适用事实。Schema 不自动产生 VEX 声明。

Schema 校验只证明结构；内容摘要真实性、步骤/证据外键、归属、覆盖计数不超过分母、范围与预算合计、状态迁移、到期、来源信任等由后台语义校验。这些检查在 P1/P2 的实现完成前仍属未交付。

## 旧数据与兼容

- 当前发现和审计表不迁移、不重写；95 条待验证发现保持原状态。
- 新维度从已有明确证据投影，证据不足记未知。旧 `completed` 或 `complete` 单字段不能推定收录、覆盖和清理都成功。
- 观察/证据只追加；问题变更携带修订并保留历史。VEX 单独保存事实及信任依据。
- 真实主界面接入时保留专业入口。原 Shell 的存在不能宣传为整个 VM 已纳入 S1/S2/S3。

## P0 验证入口

```sh
node --test work/harness-purge-improved/tests/workspace-contract.test.mjs
```

标准 Schema 正反例见同目录 `schema-validation.test.py`，需已经安装的 `jsonschema` 验证器。本轮使用 VM 现有固定 Semgrep 镜像的 Python，在禁网、非 root、只读容器中执行，未给宿主安装该依赖。示例对象全是合成数据，不是漏洞或执行结果。
