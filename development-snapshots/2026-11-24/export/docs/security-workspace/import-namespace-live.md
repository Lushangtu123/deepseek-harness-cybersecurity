# 多参数跨文件路径的真实扫描与 Chrome 组件验收

173项候选产品源码保持不变。本轮把上一批已用9组helper/caller控制合并成18个文件，经正式createJointPanel、真实VM RPC、默认Semgrep17规则与默认Python/namespace复核执行。不是扫描JSON回放。验收服务仅绑定回环并限制到一个合成engagement和一次启动，其他工具不可选。没有完整Harness主聊天、插件路由或模型链验收，也没有候选部署。

首次扫描18/18完成，9条warning、4条import证据，但namespace unavailable。原始回执与后续诊断保留。问题由本轮验收脚本的umask077引起：复制的worker权限0600，而容器UID65534不能读取只读挂载的/review.py。原始错误为Permission denied。只把该固定worker改成0644后，同9个输入直接在原默认沙箱得到9项观察；容器UID、禁网、只读根和资源限制均不改。此修订属于验收脚本，产品没有改动。

新的独立编号实例从Chrome启动所选Semgrep步骤，对固定18文件完整执行：Semgrep1.182.1覆盖18/18，无解析诊断；9条完整范围warning绑定到同一固定副本。空字典命名空间的4个正对照各生成1条条件import观察，动态scope和泛型caller/callee5个负对照没有import观察；9个执行点均保留namespace结构观察。所有命中和证据仍待核实，普通finding数据库新增0行，同时存在9条未验证扫描warning。

扫描器运行中Docker inspect核对了固定镜像、实际17规则摘要、只读受管副本、网络none、UID1000、根只读、capabilities清空、no-new-privileges及CPU/内存/PID限制。namespace由既有UID65534默认沙箱运行，回执Python3.12.15，worker摘要固定，停止清理确认。inspect是本地运行观察，不是远程密码学证明。

Chrome原生CUA检查实际任务和规则合同，读完5页命中(2+2+2+2+1)和4页证据(5+3+3+2)。limit是上限，6000字节预算会缩小每页。13条证据为4条import+9条namespace。下载JSON34544字节，与后台task/snapshot及5个章节逐值一致。刷新后恢复相同任务和副本，后台仍仅一个启动事件和一次扫描；任务不会因本次刷新重复启动。测试标签页已关闭。

两次完整扫描分别留存，不把首次namespace失败改记为通过；另有两次直接namespace诊断(失败/修复)。这两轮均不调用业务模型，不执行项目源码。18份源码全部在已有295条来源台账中，无新独立准入样本、无新增来源摘要。临时实例、端口、中继及所属扫描容器均清理，日常169程序、42项目库逻辑摘要、运行清单与账号配置前后匹配。逻辑摘要不代表SQLite物理文件完全没有写入。

本轮先请求Claude Opus5.5 high，因401登录过期失败；按持续授权把同一固定材料交给DeepSeek官方V4.1 Flash high，实际响应deepseek-flash、stop完成，本步有限通过，无确认阻断。审查仅静态阅读，不代替执行。R3仍未放行，完整安全工作区及候选的完整Harness聊天/模型链验收仍待完成。


外审的记录性建议已逐项处理：收紧“完整扫描”和“0发现”措辞；归档原始下载JSON及其摘要；从原cleanup-full响应恢复两份guest final证据对象；补存两处宿主回环端口明确ECONNREFUSED及原exec会话exit0的关闭回执。新增补充材料未交给本次模型，原始审查意见与冻结材料不改写。逻辑恢复的final JSON不冒充guest原文件字节摘要。

Chrome5页/4页边界目前依赖原生CUA观察摘要与后台RPC记录；没有归档原始AX或截图用于第三方逐页重放。不含其他私人浏览器内容。扫描proof保留No-such-object观察错误，之后取得完整Running观察并核对通过；“早于创建的竞态”是可能解释，但未记录逐错误时间，不把它写成已确定根因。没有宣称零观察错误。

[结构化结果](import-namespace-live-results.json) · [证据清单](diagnostics/import-namespace-live-20261110/manifest.json)


后续[完整Harness原生受管链验收](import-namespace-native.md)已对同一173候选完成原生聊天/preset/工具/RPC及一次真实扫描；未部署，独立R3及全产品准入仍待完成。
