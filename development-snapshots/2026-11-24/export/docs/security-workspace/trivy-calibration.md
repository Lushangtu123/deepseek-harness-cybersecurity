# Trivy 依赖、配置与凭据对照

2026-11-03，在专用 Harness VM 中使用固定的 Trivy 0.76.1 和现有离线库，测试临时合成项目。[用例清单](trivy-calibration-cases.json)固定输入和预期，[结构化结果](trivy-calibration-results.json)记录用例摘要、两次回执摘要及镜像和数据库的准入身份。

| 对照 | 观察 |
| --- | --- |
| Python Jinja2 3.1.4／3.1.5 | 前者报告 CVE-2024-56326，后者未报告该编号。维护者安全公告的修复版本字段与发布说明有差异，本例以维护者 3.1.5 发布说明标注修复。[安全公告](https://github.com/pallets/jinja/security/advisories/GHSA-q2x7-8rv6-6q7h) · [发布说明](https://github.com/pallets/jinja/releases/tag/3.1.5) |
| npm lodash 4.17.20／4.17.21 | 前者报告 CVE-2021-23337，后者未报告该编号。[维护者安全公告](https://github.com/advisories/GHSA-35jh-r3h4-6jhm) |
| PHP Symfony HttpFoundation 5.4.45／5.4.46 | 前者报告 CVE-2024-50345，后者未报告该编号。[维护者安全公告](https://github.com/symfony/symfony/security/advisories/GHSA-mrqx-rp3w-jpjp) |
| npm 开发依赖 | 原命令未证明开发依赖组件版本。候选离线命令启用 `--include-dev-deps` 后，识别出样本中的 lodash 版本并报告所选公告。覆盖标识已更新，历史任务保留原记录。 |
| Dockerfile | root 和 UID 0 报告 AVD-DS-0002，非 root 及最终阶段使用非 root 的对照符合预期。[规则说明](https://avd.aquasec.com/misconfig/dockerfile/general/avd-ds-0002/) |
| 合成凭据 | 原文报告合成令牌模式。两条正例使用同一模式，其中一条专门验证可交接路径。解析后持久化与报告中均未观察到完整合成令牌。 |

原命令为 **12 符合／0 不符／3 未知**，候选命令为 **13 符合／0 不符／2 未知**。单独追加 `--list-all-pkgs` 的探针没有改变各自的评估。Python 未锁定版本范围缺少可核对的固定版本，凭据占位符缺少对应扫描目标回执，均保留未知。修复对照只评价表中指定的历史公告，同一个版本仍可能命中其他公告。

联合任务扫描脱敏副本。候选实测原文 30 条待验证命中，副本 28 条，副本改写 1 份文件、排除 2 项，未观察到原文的合成凭据模式。审计、联合结果、模型工具投影和 Markdown 标明“原始凭据检出覆盖未证明”。报告共 6 页，单页传输最大 5831 字节。模型投影经结构验证，实际模型调用为 0。两次运行的临时容器及固定输入均已清理，正式程序和扫描器清单摘要一致。

首轮对照发现 `secret-` 目录会被既有交接规则排除，随后使用可交接路径分离“被排除”和“内容被脱敏”的观察。解析器也对这一条 Dockerfile 规则统一使用其短编号和正式编号，其他规则编号保留原样。此批改动仅在 VM 候选源码及临时运行中验收。

## 普通检查准入

R3 仍未通过。剩余条件包括独立漏洞真值和更广覆盖集、D-16 效果门槛、候选 Semgrep 规则发布及 Trivy 离线库发布者证明，以及普通检查的计划执行绑定和预算回归。凭据覆盖评估需区分原始输入与可交接副本。
