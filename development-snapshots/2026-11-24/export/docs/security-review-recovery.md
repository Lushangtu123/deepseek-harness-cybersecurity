# 当前网络安全版的恢复与解析验收

2026-11-01（America/Los_Angeles），建立 `ready-security-review-20261101`。Harness 新增第25个离线恢复点，原24个均保留；Kali 另有完整私有 UTM 导出。二者分别备份，并非跨虚拟机的原子快照。它们位于同一台 Mac，不能替代异机备份。

## 已恢复启动验证的范围

Harness 正常关机后建立磁盘恢复点，记录2671项选定文件摘要，覆盖139项改进程序、原版运行时选定文件、插件、审计数据库和非敏感 Kali 桥接入口。随后对独立 COW 磁盘副本应用该恢复点并实际启动；全部选定摘要匹配，恢复后的 Kali SSH 调用可用。分页、审计历史、私有后台 socket 和8样例解析自检也实际运行。原磁盘在此期间保留，最后换回并运行。

Kali 的应用目录受 macOS 隐私保护，因此通过 UTM 自带 Share 功能在正常关机后导出完整 VM，没有申请完全磁盘访问。归档包含系统盘和 EFI 变量文件，4项文件摘要核对、qcow2完整性检查及无 backing file 检查通过。独立副本使用新 UUID、保持其余配置，原 Kali 关闭期间启动；普通用户身份、系统身份和12项系统/工具文件摘要匹配，固定 SSH 连接成功。副本关闭后原 Kali 重新启动并复核。临时快捷方式与本轮启动副本已移除，归档保留。

恢复介质在私有本机目录：

- Harness：`~/Library/Application Support/Harness Purge Original/recoveries/ready-security-review-20261101/`，配合原 Harness qcow2 内同名恢复点。
- Kali：`~/Library/Application Support/Harness Purge Original/kali-recoveries/ready-security-review-20261101/Kali.utm`，同目录 `manifest.json` 保留选定系统/工具和整个归档的校验清单。

Harness 磁盘包含本地模型配置及专用 SSH 连接材料；Kali 磁盘包含其账户和服务配置。这些私有恢复文件不进入公开 Git。运行恢复前，应先核对归档及磁盘身份，正常关闭对应 VM，再从归档制作副本；不可让原 Kali 与保持相同网络身份的恢复副本同时运行。不要直接运行唯一归档副本。公开仓库仍只提供脱敏源码与安装说明。

宿主入口会显示新的 Harness 恢复点；其摘要状态覆盖固定程序/工具/配置清单，不实时代表 Kali 归档健康，也不代表全系统每个文件均已检查。

## Semgrep 解析缺口：本轮确认到哪一层

在同一离线、只读受限容器中，对已安装1.182.1和官方1.183.0候选核心分别测试8个合成文件。除故意损坏的样例外，Node语法检查通过；不执行这些源码。

| 样例 | 两个引擎的观察 |
| --- | --- |
| 原11行复现、加分号、缺口后追加eval | 均存在6行解析错误 |
| `<`写成等价`\x3c`、移除HTML注释正则分支 | 解析错误为0 |
| 良性JSON.parse、阳性eval | 解析错误为0 |
| 故意无效语法 | 识别出解析错误 |

这将问题限定到上游 JavaScript 解析器处理该正则与周围语法的组合；不是Node语法不合法或Harness传输失败。内部具体状态转换仍未完全定位，不能声称已修复上游语法。加分号不能消除缺口。候选核心单独提取时曾因动态库缺失退出127；补齐同一官方wheel自带库后才完成上述比较，原失败保留。

本轮修复了Harness自身的另一处问题：之前对分组解析错误仅读取第一个位置，造成其余诊断与文本补查路径遗漏。现在保留所有诊断位置，返回前20项并明确截断；文本补查仍限制20个文件、每文件1MB、总8MB，并增加跨分组累计20000个位置预算。文本提示继续只是信息提示，不能补成语义覆盖。

候选版本自检从5样例扩展至8样例，要求缺口后的eval阳性对照也被识别。已安装版本的实际结果仍为 `executionOk=true`、`controlsPassed=true`、`parserReady=false`、退出码2；这是拒绝升级门槛，不能当作解析问题通过。扫描器身份未改变，没有改写真实源码、添加隐藏排除或确认任何发现。

官方参考：[Semgrep1.183.0发布](https://github.com/semgrep/semgrep/releases/tag/v1.183.0)、[官方Python分发](https://pypi.org/project/semgrep/1.183.0/)、[QEMU离线镜像工具](https://www.qemu.org/docs/master/tools/qemu-img.html)。具体实际验收和限制见[结构化摘要](security-review-recovery-verification.json)。
