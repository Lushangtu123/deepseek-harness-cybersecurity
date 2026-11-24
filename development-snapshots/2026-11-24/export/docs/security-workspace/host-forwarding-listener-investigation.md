# 宿主转发实现定位（2026-11-10，已外部复核，生产逐例根因仍开放）

本步没有修改 UTM、VM 或 Harness 日常程序。检查实际加载路径上的 QEMU/libslirp 文件、启动参数与同 PID 现有日志，并在自己新建的临时回环端口做了独立 TCP 对照，没有新的 VM SSH 请求。

## 已证实的实现与版本

专用 QEMULauncher PID 39674、进程出生时刻、监听 FD21 与 socket generation 前后相同；UUID 与专用 VM 配置匹配。当前监听 queueLimit 字段为1，读取时队列为0，不是故障时刻快照。磁盘打开元数据绑定正确，没有读 VM 磁盘正文。

本机 UTM4.6.4/build107，QEMU9.1.2；已加载路径的 libslirp 框架版本字符串4.7.0，框架SHA256为5b5222874c68e9c499c80fcf9891d7eca1572b5920b2c92d884379771ccaddd4。只核对磁盘映像和加载路径，没有读 live memory 或证明逐字节映像仍与已映射页一致。

[UTM v4.6.4 依赖清单](https://github.com/utmapp/UTM/blob/v4.6.4/patches/sources)指定上游libslirp v4.7.0归档与QEMU9.1.2-utm。官方[libslirp v4.7.0源码归档](https://gitlab.freedesktop.org/slirp/libslirp/-/archive/v4.7.0/libslirp-v4.7.0.tar.gz)已下载并只提取相关源码，meson版本为4.7.0。该UTM标签的libslirp补丁只改iOS构建的resolv链接条件，没有改本步TCP路径。不用未固定master分支证明具体版本。

上游socket.c的tcpx_listen调用listen(s,1)。本机arm64框架对应函数在listen调用前把w1设为1，符合既有queueLimit观测；这个值来自转发库实现，不是Harness界面中的队列设置。

另一个在tcp_connect中“accept后立即close”的路径依赖soassign_guest_addr_if_needed返回负值。确切v4.7.0源码和本机arm64逻辑显示，正常IPv4路径返回0，缺地址返回-1的是IPv6路径；当前运行使用IPv4 hostfwd且ipv6=off。此分支不符合本次正常IPv4配置，不能把看到该分支就当作已发生的故障。

版本材料也有一份未采用的矛盾来源：UTM镜像的v4.9.1-release-mirror标签指向的提交，其meson文本声明4.0.0，故不能据此判断真正4.9.1或“升级即可解决”。原失败获取/版本冲突记录保留。

## 独立回环对照

运行前由同一脚本进程写入脚本SHA与固定种子的分块随机顺序，紧接着执行；没有外部时间戳认证，也没有执行前的外部审查。4块，每块含backlog1/128×接受延迟0/25ms四种条件；每次6并发、独立随机临时端口，总96个客户端。没有使用49222至49226端口，也没有连接VM或外网；只有echo一个合成字节。所有服务端线程退出，脚本完成退出，监听socket均随上下文及进程退出关闭。没有改全局参数。

| 请求backlog | 请求accept延迟 | 客户端 | 完成 | 失败 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 24 | 11 | 13 |
| 1 | 25ms | 24 | 4 | 20 |
| 128 | 0 | 24 | 24 | 0 |
| 128 | 25ms | 24 | 24 | 0 |

backlog1共33个失败：9个connect阶段ConnectionResetError/54、22个read阶段ConnectionResetError/54、2个send阶段BrokenPipeError/32。backlog128的48个客户端均完成。backlog1无延迟组还有2个服务端错误，不能把这组每个失败均解读为应用accept之前。

延迟25ms、backlog1组的20个失败都结束于释放客户端后0.694ms以内，早于预设接受等待的25ms；每个trial有一个成功回包，所以stop事件不是提前打断等待的原因。acceptedMonoNs采在accept返回后，仅比较该时间戳不等于系统调用入口跟踪；这里还核对了预设等待范围，不只比较accept后采样值。这20个失败在本对照中不是echo处理器主动close造成。

这是受控参数下本机TCP行为的复现，不是原QEMU监听器的内核队列跟踪。没有测对照监听器的实际内核队列上限、内核drop原因或生产QEMU调度延迟，也没有把25ms当成QEMU真实延迟。不能把对照失败率当作原VM或日常流量的失败率。

## 日志与边界

本次只读查询PID39674、调用时刻以前1小时的统一日志：0条，输出未截断；专属VM包内未发现现有.log文件，配置中的debug日志字段未提供。时间窗口不是旧采集窗口，零日志也不排除静默失败。没有连接既有spiceport QMP通道、读stderr管道、启用调试、注入或提升宿主权限。

collect-inventory第一次因ps格式化-netdev参数内部含空格而解析失败，未读取日志、未执行VM命令。已保留旧脚本及失败记录，再改为匹配已知的完整格式化参数字符串。它不是原始argv边界的独立证明，也不是运行配置漂移。

## 结论与下一步

小监听队列配合瞬时并发，是当前最具体且可复现的候选机制；它与之前“宿主建连/发送描述符后，guest没有相应SYN”的现象相容。当前没有证明原VM的13个失败逐条都走了该机制，更没有关闭旧两条未知SYN、pre-READY认证身份、历史侧栏或普通R3。

下一步优先在工作区准备Harness连接入口的排队/复用候选及交叉对照，保持现有VM隔离、宿主库和日常配置不动；其目的先验证可用性改善，仍不能替代原内核分支的直接归因。未部署、未推送，也不凭旧版或一次对照直接升级UTM/修改系统库。


## 复核及归档补充

指定 Claude Opus5.5/high 完整复核200.3秒/end_turn，归档阻断0，统计错误0，认可L1–L4范围内的静态/独立对照证据，L5生产逐例因果仍是候选。工具和MCP为空，自定义插件/hooks关闭；CLI builtin插件仍可能列在初始化中，不称全部插件已卸载。模型只做静态审读和手工复算，没有执行工具或重算SHA。本轮Claude可用，未启动DeepSeek替代请求。

F1–F4按现有数据和文书核对处理，没有再次运行回环或VM探针：

- **F1**：原binary-functions.json是最初的一组函数列表，未同步后来的tcpx_listen和soassign。主审查manifest其实已包括这两个.s文件，已逐一核对，纠正模型“未在manifest”这一部分说法。新增r2元数据绑定完整反汇编SHA、实际3个相关函数、提取规则、Apple LLVM21版本与命令；原文件均保留。首次Mach-O命令的符号筛选没有生效、工具显示被截断，随后重新完整落盘再提取，不能用首次截断输出充作全部证据。
- **F2**：补读同一份v4.7.0 slirp.c的slirp_add_hostxfwd：正常AF_INET、零guest地址也会替换为vdhcp_startaddr。QEMU fork实际调用哪个入口未审，因此将“该懒地址拒绝路径不符”明确限定于正常非零IPv4 guest地址这一前提；不把它当排除其他转发路径。
- **F3**：原两份派生分析由内联本机脚本生成，现保存可重现脚本及源/输入SHA，重算结果与原rows完全一致；新加强记录产生于外部复核之后，没有另做独立模型审查，不追认模型看过新记录。
- **F4**：原run2295…的96份记录按旧摘要校验。存在峰值6条重叠probe；13个失败各与5条其他probe重叠，10个有端口的FD连接完成时刻各有另一连接完成在1ms内。错误词为2次connection reset和10次broken pipe/banner exchange，另1次连接器明确报告connect/系统errno54。SSH文本不是原始syscall errno，probe寿命也不是未accept队列长度；因此只是生产突发条件与候选相容，没有测出原监听同时未accept的连接数。

静态强化：反汇编断言携带的源码行号与精确v4.7.0源码相符，例如soassign的1202/1207/1223以及tcp_connect的484/487。这加强版本一致性，但不等于整个构建逐字节可复现或已读live-memory。

补核lsof显示：两个框架的已映射vnode inode与当前路径inode一致，mtime/ctime均早于进程出生。PID39674的FD21明确绑定127.0.0.1:49223。上述为复核后的只读元数据，仍没有读取进程内存。统一日志没有覆盖旧失败时段，且DEBUG输出受开关控制并走glib相关路径，零条统一日志对这些分支缺乏区分力。

对照的6个客户端经Barrier一起释放，实际SSH子进程启动时序不相同。serverStopped/listenerClosedOnReturn是join/with/成功退出提供的结构保证，不是lsof逐socket点查；没有测TIME_WAIT具体时长。连接重置指socket异常及errno，未抓包证明RST报文或定位内核丢弃代码；模型的“内核RST”不升级为本步观测事实。

当前证据最适合支持下一步低影响候选对照：在Harness连接建立阶段加入排队或复用，比较可用性。此方案不是已部署修复，也不能单凭改善就证明原13例的唯一根因。继续保持宿主和VM隔离边界。


后续[现有SSH队列隔离交叉对照](ssh-existing-queue-control.md)已完成本步骤复核：一次性25ms停顿的4个配对分块中，直接并发每块1/6完成、既有队列每块6/6完成。无新的VM请求；不外推到生产故障率，研究工具D1/D2/R1仍须修复后才能复用。
