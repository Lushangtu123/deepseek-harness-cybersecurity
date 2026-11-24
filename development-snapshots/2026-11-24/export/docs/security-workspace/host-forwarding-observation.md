# 宿主转发端同步只读观察（2026-11-09，已完成本步骤外部复核）

本轮补足上一轮的观察缺口，没有对宿主或VM实施修复。Claude重新登录后，先用实际claude-opus-5-5/high完整复核上一轮最终材料；344秒、end_turn，无本步骤阻断。旧401回执保留。测试注释和文件计数口径、失败源端口保留前提已在原归档补充；当次审查不能确认底层根因。

## 工具与正控制

使用本机SDK和libproc，只读查询专用QEMULauncher的监听socket。每次采样核对当前用户、QEMULauncher名称、PID、进程出生秒/微秒、监听FD、socket生成身份以及IPv4回环/49223/TCP监听状态；变化、不可读或FD列表达到上限则失败，不输出“0”代替。只输出计数、队列及时间元数据，不读取内存、包正文或不相关文件路径。

字段依据本机SDK与 [Apple XNU proc_info定义](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/proc_info.h)和[实现](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/kern/proc_info.c)核对；[lsof Darwin实现](https://raw.githubusercontent.com/lsof-org/lsof/master/lib/dialects/darwin/dsock.c)同样使用这些队列字段。在线主分支不作为本机内核精确构建证明。

真实本机合成socket正控制：连接前queue=0，建立2个尚未accept的连接后queue=2，accept后queue=0；关闭后FD数量与自检前相等。采样时间使用C/Python一致的宿主POSIX CLOCK_MONOTONIC，子进程自检时间在Python调用前后同域区间内。PID出生时间不符的对照拒绝。非法参数、非QEMU进程拒绝；socket/FD传递、行读取和关联边界共12项检查通过，编译-Wall/-Wextra/-Werror无诊断。

## 这轮实际观察

一次20秒有界只读观察，最多6并发、实际96个固定无害VM命令，direct/fdpass各48。81次收到正确远端标记，15次无标记。两个主动断开场景中的成功先按标记判定，不以exit255认定失败。没有项目扫描或漏洞验证。

共3225个快照，FD从218升到峰值301，最高FD编号300；20秒尾部219，结束后的独立同身份查询为218。探针全部在采样时域范围内，最后探针之后仍有约17.46秒观察。首个低于/等于初始218的样本没有出现在该20秒窗口内；之后218的独立查询只能给出“后来已回落”，不倒填精确回收时刻。

因此，先前当前用户launchctl显示的256不能用作该QEMULauncher实际FD上限：本轮已有编号300的打开FD。**仍未读取该进程的RLIMIT_NOFILE，不能据此确诊或排除其他阈值下的瞬时耗尽。**

监听队列上限字段始终1，已采到的queueLength峰值1、incompleteQueueLength峰值1。15个失败各有1至9个时间区间相交的快照，其中2个失败区间观察到queueLength=1，其余已采快照为0。快照间最大间隔13.794毫秒；计数和队列读取并非原子的失败系统调用轨迹，短暂异常仍可能发生在采样之间，**不能把这些值直接解释为失败瞬间的状态或证明队列满导致重置**。

系统全局listen queue overflow计数前后都是0，差值0。若目标异常属于该单调全局计数的覆盖路径，零差值也约束目标增量为零；尚未核实本机内核的具体丢弃路径是否计入，因此不将其解释为“目标socket绝无瞬时队列问题”。也不因队列上限1就改变网络配置。

## 失败阶段与上轮数据分开

本轮15个无标记结果：

| 记录阶段 | 数量 | 能说明什么 |
| --- | --- | --- |
| direct-identification | 2 | SSH错误文本被既有分类器归为identification |
| direct-connect | 2 | 既有文本分类器标签，不是精确connect系统调用证据 |
| connected-and-descriptor-sent | 7 | fdpass在connect返回后记录了端口，SCM_RIGHTS sendmsg成功返回1，仍未收到远端标记 |
| no-connect-metadata | 4 | 没有连接完成元数据，不能直接断言具体在哪个系统调用失败 |

“描述符已发送”表示交给Unixsocket队列成功，不独立证明OpenSSH已取出/使用。原始stderr不保留，只有哈希和错误词分类。这轮没有新VM接口抓包，**不把这7次失败借用成上一轮8个端口无报文的证明**。

上轮12个失败另外在本机汇总：direct3、fdpass9，分布在10个六连接批次；批内位置0至5都有失败，并非固定“每批最后一个”。旧FD_META不证明FD发送成功；旧stderr没有保存，不能补造该证据。两组都是固定顺序的诊断，不能用失败比例评估FD-pass或观察器的因果影响。

## 清理、限制和下一方向

观察器已wait/reap。按本轮精确UUID检查的宿主同用户SSH/Python/观察器及VM同用户探针均无残留，不可读候选0；只表示检查时点。日常169项程序与既有基线匹配；原候选173/guest124和产品配置不操作。没有宿主sudo、抓包、注入、安装依赖、调整限额或VM网络配置；没有候选部署或GitHub推送。

已收窄的只是若干误推断：256不是实际测得进程上限，旧24次样本不能代表失败批次，部分失败发生在主机建连且FD已发送之后。**准确的转发组件、errno和底层原因仍未确认；历史侧栏首次读取原因没有新增证据。**

下一步优先寻找当前用户权限内、该VM实例专属的转发/连接状态或既有诊断日志，避免继续用全局计数猜根因。若需要新的VM/网络配置变更，应先准备具体可审阅方案；现有配置不由本步外部审查自动授权修改。普通R3独立质量样本及全产品发布保留项继续保留。


## 本步骤审查与归档限制

指定Claude Opus5.5 high已完整end_turn复核，394.2秒，0归档阻断；6项低严重度缺口已逐条核对，不表示无缺陷。诊断代码仍留在工作目录，不加入日常Harness工具箱。复用前应修正逻辑失败的陈旧errno输出、补backlog到queueLimit语义正控制及observe拒绝路径/其他阶段测试。

管理器manage.py和169基线来源补记了事后SHA，不能追认运行时管理器源码；基线map与独立更早HTTP169基线一致，没有用当前状态重建通过基线。自检只主张FD前后相等。post-burst独立查询由host-socket-observer --identify执行，出处事后记录。

同一原始记录另外在本机补算：socketError非零样本0，以及逐失败incqlen和7条FD_SENT最近样本。这个数据附录属于事后核对，未单独送模型，不用于产生新根因结论；原始结果/源码没有覆盖。缺FD_META也可能是连接建立后、Python检查异常前即收到RST，不能据此断言握手未建立。

观察器可能短暂竞争FD/socket锁，尚无随机观察器开关对照；固定批次与FD累积完全混杂，不拟合因果。清理只检查同用户精确任务标记，不覆盖所有sshd会话；仅代表检查时点。准确根因、历史侧栏和R3仍开放。


后续已完成[同次宿主与 VM 同步诊断](ssh-synchronized-diagnosis.md)：当前实验的 guest SYN/认证账本与宿主快照已配对；出现 2 个未归属 SYN 流，精确根因仍开放。旧实验事实保留，不跨轮借用失败归属。
