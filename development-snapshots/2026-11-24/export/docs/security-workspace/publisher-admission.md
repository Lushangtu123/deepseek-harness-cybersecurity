# 发布者证据与候选准入

2026-11-03，按固定摘要查询候选的官方注册表、OCI 引用、旧式签名标签和 GitHub 构建证明接口。记录保留每个查询位置、HTTP 状态、实际取得的证明摘要和适用范围。当前 Semgrep 和 Trivy DB 均未取得满足发布者准入的证据，候选更新继续停在替换前。[结构化核对记录](publisher-discovery.json)

| 资源 | 本轮取得的证据 | 更新结论 |
| --- | --- | --- |
| Semgrep 1.182.1 与 1.183.0 | 附在镜像索引内的 SLSA 构建说明，内容摘要和 ARM64 目标摘要对应 | 发布者身份仍未验证，候选不替换 |
| Trivy DB 现用库与本次观察到的新库 | 官方注册表的固定清单与压缩层摘要，已查位置未返回可用签名或发布证明 | 发布者准入仍未通过，新库不导入 |
| Trivy 0.76.1 程序镜像 | 证书、签名与透明日志已验证，证书身份绑定到官方发布工作流与版本标签 | 这份证明只适用于该程序镜像 |

Semgrep 的两个 ARM64 构建说明均为 in-toto/SLSA JSON，目标摘要匹配，取得的内容没有内嵌签名或 Sigstore 证书材料。已查询对应索引与 ARM64 清单的 OCI 引用、Cosign 签名与证明标签。Docker 文档说明了这类附加构建说明与目标清单的关联方式。[Docker 构建说明存储格式](https://docs.docker.com/build/metadata/attestations/attestation-storage/)

Trivy DB 的固定现用摘要和本次查询 `:2` 得到的摘要均已检查。GHCR 与 Docker Hub 的本次标签结果分别保存，标签会随时间变化。GitHub 组织证明接口的匿名查询返回 401，使用现有登录状态重查后返回 404。所有结论仅限记录中的位置与摘要。Semgrep GHCR 的同版本和候选摘要查询也返回 404。

公开流程核对固定到提交。Trivy DB 的所查流程用 ORAS 上传数据库，流程中未见签名或构建证明步骤。Semgrep 的所查流程是构建测试，推送关闭，无法据此确认实际发行镜像的完整发布流程。[Trivy DB 所查流程](https://github.com/aquasecurity/trivy-db/blob/4baa24d2b7c41f704d93f7658416dc239f9345c1/.github/workflows/cron.yml) · [Semgrep 所查流程](https://github.com/semgrep/semgrep/blob/4fe07d805dd2a4b64fed486e95136923f08648d0/.github/workflows/build-test-docker.yml)

## 当前处置

两个更新入口的发布者准入表仍为空。取得新证明后，先验证证书或密钥的可信身份、证明的目标摘要和候选内容，再更新准入；单独的版本号、注册表摘要或构建说明不触发放行。现有 Semgrep 1.183.0 候选另有此前实测的解析缺口，发布者证据通过后仍需重新通过功能回归。[已有解析验收](../security-workflow-recovery-verification.json)

独立代码复核覆盖发布者准入、只读检查和事务恢复分支，53 项相关测试通过。更新与回滚的成功路径使用测试夹具临时登记的合成候选验证，真实候选尚未获准入。生产部署、镜像替换和漏洞库更新仍待后续验收。本节的外部证据缺口不阻止继续进行当前固定版本的隔离运行与工作台联调。
