# 私有会话到期与页面恢复

安全审计的“私有会话配置状态”只读取 VM 私有文件的格式、版本与到期时间，展示有效、五分钟内到期、过期或不可用。状态读取不会访问目标网址，也不证明仍处于登录状态。扫描仍须通过控制器与 ZAP 各自的前后登录核对；过期配置不能发起认证扫描。

在 VM Shell 工作台使用以下入口（不在 Mac 上运行）：

```sh
python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-local-lab.py status old-session --origin http://127.0.0.1:18780
```

需要续期时，先自行完成真实登录或 MFA，在 VM 私有目录准备权限为 `600` 的 JSON 文件，仅包含 `value` 和 `expiresAt`。不要把 Cookie、Bearer 或该文件发到聊天、网页或 GitHub，也不要写进命令参数。`expiresAt` 必须在未来且不超过 31 天；单 Cookie 的名称与原配置一致。

```sh
python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-local-lab.py renew-session old-session new-session --origin http://127.0.0.1:18780 --expected-revision ORIGINAL_UUID --confirm < /home/purge/downloads/private-renewal.json
```

用 `status` 输出中的 revision 替换 `ORIGINAL_UUID`。此命令继承原配置的目标、校验路径、登录标记与排除路径，只生成一个新名称、全新 revision 的私有文件。原配置保持不变；缺少确认、版本不匹配、新名称已占用或并发同名导入会拒绝。命令输出只有元数据。原配置过期仍可作为来源，不可读取时改用 [import-session](authenticated-zap.md) 导入完整的新配置。

导入成功后，在安全审计范围中填入新配置名，勾选确认并保存，才会切换后续扫描。扫描运行中不能更换范围；正在使用原配置的任务不会自动切换。旧文件和输入文件不会自动删除，确认不再需要后自行清理。

页面从后台返回、重新获得焦点或从浏览器缓存恢复时，会取消旧状态读取并重新核对。30 秒检查周期可发现超过 60 秒的时间间隔、时钟回拨，或继续重试失败的只读状态读取；可见且选中私有会话时也按此周期更新到期状态。慢读取不会被周期轮询不断取消。请求沿用已有 15 秒期限，资料未经重新确认时暂停写入与导出。

未保存草稿和未确认操作的请求号会保留。恢复只读取状态，不自动重发扫描、范围保存、发现审核或取消请求；未确认操作仍须人工核对并明确重试。后台扫描由 VM 服务持有，VM 关机或服务停止会中断任务，不自动重跑。浏览器冻结或休眠期间无法即时提醒，到期后扫描端仍严格拒绝。

这些功能不会自动登录、刷新真实 Cookie、处理 MFA，也不保证扫描期间持续登录。真实项目发现继续保持原状态；Semgrep 语义解析缺口与历史 QEMU SSH 具体缺陷不因此消失。
