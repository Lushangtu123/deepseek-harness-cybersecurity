# 无桌面 VM 的默认工作区初始化

在 Ubuntu 24.04 VM 中，`xdg-user-dir DOCUMENTS` 正常退出并返回 `/home/purge`。Harness SDK `0.2.1-rc.3` 将等于主目录的返回值视为 Documents 目录未配置，控制器随后抛出 `system Documents directory is unavailable`。客户端在工作区列表和会话列表为空时调用该入口。

修订在 VM 导出的网页配置和新安装器中设置 `workspace-controller.config.documentsDirectory` 为 `/home/purge/workspace`。SDK 使用这个绝对路径创建 `/home/purge/workspace/deepseek-harness/default-workspace`。这两个入口使用相同设置。导出清单同步了网页配置摘要。SDK 在已有默认工作区时直接返回原记录。在已有其他工作区或会话时，跳过默认创建。

- 真实 SDK 注册器在原配置下拒绝初始化。修订版创建了预期目录，两次调用返回同一个工作区 ID。
- Chrome 在两个隔离的空白 SDK 实例中发起原生初始化。原配置的首次打开和刷新各出现一次 Documents 错误，界面停在 `Choose workspace`。修订版自动显示 `Default workspace` 并打开空白会话，刷新后仍只有一条默认工作区记录。后端事件证实创建只发生一次。Chrome 取证未直接捕获短暂的错误提示。
- 安装器 8 项回归、专业安装器 17 项回归和 Ubuntu VM 的 6 组真实目录权限对照均通过。浏览器实例使用 SDK 的基础和 Web 组件，未进行日常服务启动或 dsh-purge 全配置联测。所有临时应用与中继均已退出，清理时核对了日常 VM 的 169 个程序文件、42 个数据库的逻辑摘要及配置。
- 首轮临时清理因验收脚本把 SDK 自动创建的本地授权记录误判为异常而提前退出。核对记录结构后重新清理通过，保留了首次失败的回执。记录没有包含凭据值。

首轮复审发现基础安装会接受不可写的空工作区。修订后，已有目录须为空、归 `purge` 所有，且可以读取、写入和进入。基础安装回执将 HTTP 就绪与默认工作区创建分别标明。专业资产安装需要使用原始的空工作区，因此应先完成专业资产安装，再首次打开网页。

状态为本地候选验收。完整的新 VM 安装、日常 VM 部署及正式发布另行验收。

Claude Opus 5.5 high 因额度终止。同一份材料由 DeepSeek 官方 V4.1 Flash high 完成复审。逐条核对后，本轮没有确认的阻断问题。

[验收记录](diagnostics/workspace-bootstrap-20261110/manifest.json) · [复审摘要](diagnostics/workspace-bootstrap-20261110/review-summary.json)
