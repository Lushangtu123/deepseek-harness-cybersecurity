# SSH 诊断工具修复与新一轮有界实机验收（2026-11-09，本步骤已完成复审，根因仍开放）

本步完成认证时间窗、源码快照装载和失败收尾修订，随后实际运行一次新的隔离 VM 同步诊断。它是新工具的一次实机验收，精确 SSH 故障根因与历史侧栏同因关系仍未确认。

## 修复及先审后运行

正控制认证只使用 guest ARM 至 DONE 内的事件；同 peer 二元组的窗口外事件另桶保留。宿主候选模块经内存缓冲装载，间接 association→guest_sync 导入有证明。发往 VM 的预检/采集源码来自固定快照，连接器期望摘要和合约摘要与 manifest 门控；外部管理器与独立 169 程序基线仍按固定摘要加载。默认 sshd-T 完整输出只取摘要，前后比较不输出配置正文；这是不带 -C 的默认上下文，不代表所有连接 Match 上下文。

R1 指定 Claude Opus5.5/high 复核 309.9 秒后指出检查点写入失败会跳过收尾，暂不放行。这与本机合成复现一致。修复后加入真实 main 的合成失败反例：写 checkpoints 抛 OSError 时，最终源码检查仍执行、status 为 failed、没有成功汇总。清理记录写失败也不跳过源码检查。已启动控制 SSH 却没有 READY 的情况标为 cleanup-unconfirmed，不能记作已确认清理。

修订后 19 套、97 个测试方法通过；其中一项依赖真实 49223 监听进程做宿主只读集成检查，其余主要为合成或纯函数检查。C 观察器源码与二进制未改。R2 指定 Claude 复核 153.5 秒，状态为 completed，确认 D1 关闭、快照来源门控落实、范围内 0 阻断，才执行下面的新 run。

## 新运行的实际结果

run：`2295c70a-c434-4460-a87d-e9d7368ea299`，仅一次，96 个无害标记连接，最多 6 并发，direct/fdpass 各 48。

| 结果 | 数量/观察 |
| --- | --- |
| 正确远端标记 | 83，均对应 guest SYN 与窗口内 accepted-key |
| 无标记 | 13：2 个 direct 文本 identification 标签，10 个 connect 返回且描述符发送成功，1 个 connect 系统错误 |
| 成功 FD-pass 正控制 | 37，观察到端口保留；失败端口仍不能据此确认为保留 |
| 已知端口失败 | 10，在失败端口也被保留的假设下均没有候选 guest SYN；另 3 个失败端口未知 |
| guest 初始 SYN | 83 个唯一流，全部属于成功标记；无额外未归属流、无同四元组多初始序号复用 |
| TCP 标志采集 | 332 captured / 332 received / 0 dropped；boot、时钟增量、接口接收异常计数校验通过 |
| sshd 日志 | 422 行、未触及截断上限 |
| accepted-key 事件 | 85 = 83 个成功 peer 事件 + 0 个正控制窗外事件 + 1 个控制 peer 事件 + 1 个未知事件 |

未知认证事件发生在 READY 前 690.352794 毫秒，保留未知会话身份，不能追认成预检。peer 哈希是可关联假名，低熵端口可以枚举，不称匿名。

这次没有额外 SYN，不代表上一轮的两个未归属 SYN 已被解释或关闭。不同实验的失败不能跨轮合并成同一组件故障。此处只支持继续检查转发至 guest 接口的路径；没有定位确切组件、系统调用或底层原因。

## 宿主观察与完整性

20 秒内 2,795 个快照。FD 初始 222、峰值 303、最高编号 302、尾部 220；queueLength 与 incompleteQueueLength 峰值各 1，最大采样间隔 15.298 毫秒。快照非原子且离散，未测实际 RLIMIT_NOFILE，不能归因为 256 上限、耗尽或队列满。固定 direct 再 fdpass 的顺序有时间混杂，不比较两组失败率。FD_SENT 不独立证明 OpenSSH 已消费描述符，connect 错误不证明握手未完成。

联合门控全部通过：

- status 为 collected-awaiting-review，finalChecks.ok=true，hostChildrenReaped=true。
- collection-summary 完整，97 项检查的当前候选与 18 项冻结输入一致。
- runtime-final-check.ok=true；11 个宿主候选模块有已验证内存来源证明，包括 vm、probes、association 和 guest_sync。
- guest-cleanup 的本轮捕获 PID 条目和精确探针标记残留均为空；DONE 前宿主代理检查也为空。仅表示相应检查时点。
- environment-check.matches=true，boot、记录的 sshdLimits、版本及完整默认 sshd-T 摘要一致；169 项独立程序基线前后匹配。

另外核对了远端源码意图、连接器固定摘要、合约摘要、prepare 文件与 BOOTSTRAP 摘要、原始记录摘要等 20 项运行检查。prepare 摘要属于启动器记录与本机对照，不是对抗恶意宿主的认证。C 二进制仍按路径执行，同用户恶意篡改后恢复的 TOCTOU 不在已解决范围。

宿主没有 sudo、抓包、注入、权限或配置更改；VM 内现有 root 仅读取元数据、日志与标志摘要。日常程序、VM 网络配置、项目发现状态未操作，没有候选部署或 GitHub 推送。原始私有采集文件不进入外部审查包或导出包。

## 保留项

非原子汇总写入必须结合最终 status 判读；非 Exception 中断、提前失败的 best-effort 后态、失败路径所有宿主探针复查仍有限制。本轮成功路径不能替代所有真实故障注入。具体转发根因、旧两条 SYN 身份、pre-READY 认证身份、历史侧栏及普通 R3/全产品发布保留项继续开放。


## 最终外部审查与归档证据链

最终指定 Claude Opus5.5/high 已完整结束：375.5 秒、end_turn，确认缺陷 0、归档阻断 0，允许把这一轮有界采集记为完成。本轮三个审查请求分别为 309.9、153.5、375.5 秒；第一轮 D1 阻断修复并复审关闭后才开始实机，顺序没有倒置。本轮 Claude 均可用，没有发起 DeepSeek 替代请求。执行工具和 MCP 为空，自定义插件/hooks 关闭；CLI 的 builtin 插件仍列在初始化元数据中。

模型仅静态核对所给源码和元数据，没有执行测试、重算 SHA 或查看原始私有样本。最终包没有提供 observations、metadata、manage、target_binding、C 等源码正文，其相关行为沿用前轮审查与测试，不能称本轮重新全面复核。

归档按三条要求补充边界：

1. **派生链**：最终审查当时，validate-live 尚未重新核对 hostSamplesSha256；host-observations/association 原文件及摘要、live-evidence-summary 的生成器也未随包提供。彼时宿主指标与失败账本属于采集进程内计算后的本机转录，不能写成模型看过原始记录。
   归档时另外只读核对了原始 host 样本摘要，并用原冻结源码的纯分析器重新计算宿主和关联结果，均与原派生文件完全一致，转录的两个段落也一致；9 项核对通过，派生文件摘要另存。这个加强核对未再交模型审查，不追认成最终模型已看到的证据。原运行、原审查包和所有原始产物均未修改。
2. **R-D**：保留 journald 接收时钟延迟造成严格窗口保守失败的风险。本轮正控制窗外计数为 0，不能据此保证以后没有延迟，也没有放宽窗口。
3. **R2 回执**：最终包给的是 R2 status，其中没有 stop_reason 字段，所以正文使用 completed。完整 R2 receipt 本地保留，另核对 stop_reason=end_turn，SHA 3446c79ceae9931b13d0450a980339bfdf5822bc87e6f349c1dab3dc73ee7a24；不能声称最终模型从 status 独立看到了该字段。

新增登记：cleanup 外层使用依赖 PATH 的 python3 -B -，未启用 -I，内层 sudo Python 已隔离；当前清理证明以 VM 用户环境可信为前提。未发现实际遮蔽证据，但后续应显式指定解释器并隔离外层导入。原生观察器的恶意同用户 TOCTOU、默认 sshd-T 的 -C 上下文限制、中断/写入/提前失败边界均保留。

原 collection-summary 的 notExternallyReviewedYet=true 表示采集当时状态，不作覆盖。新的归档 JSON 引用原 summary、manifest、当前审查和本机加强核对摘要，作为后续审查状态；这是证据归档，不是 SSH 故障修复或产品发布。


后续[转发监听实现定位与独立回环对照](host-forwarding-listener-investigation.md)已复核：库中的listen1及本机小队列突发重置可复现，形成更具体的候选机制；未修改原VM、未新增VM请求，也未证明原失败逐例同因。
