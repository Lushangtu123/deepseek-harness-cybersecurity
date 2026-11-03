# VM 运行应用与源码副本关联

此入口用于自己拥有的、单文件且仅使用标准库的 Python HTTP 应用。先在“安全审计”保存目录、ZAP 工具、VM 回环网址与有效期。其他框架、依赖安装、构建脚本、真实账号自动登录不在这个启动器的支持范围内。

在 VM Shell 工作台明确启动，替换项目编号和入口文件：

```sh
DSH_HOME=/home/purge/.dsh-improved /home/purge/.local/node/bin/node /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-runtime-source.mjs --engagement YOUR_SAVED_PROJECT_ID --entry app.py --seconds 360 --confirm-execute
```

应用须读取 `HOST=0.0.0.0` 和 `PORT=8080`，根路径在十秒内返回 HTTP 200。启动器不跟随就绪探测重定向；探测被授权到期或取消中止。启动会实际执行固定脱敏副本，请先检查要运行的代码。采用与联合审查相同的凭据脱敏；脱敏可能改变语法。不支持的文件与依赖目录不会交接。解释器使用 `python3 -I -B`，不执行启动 shell、构建钩子或依赖下载；应用自己仍可在容器内创建子进程。

启动器使用现有固定 Semgrep 镜像中的 Python，保留镜像摘要；非 root、只读副本和根文件系统、删除 capabilities、限制 CPU/内存/进程及临时空间，不挂载 VM 凭据或 Docker socket。专属 Docker 内部网络限制外部路由，但不隔离 VM 网关服务，不能据此把任意不可信程序当作安全。固定 VM 回环转发只连接本次容器 IP:8080，拒绝其他 Host、绝对网址和 CONNECT/升级。

期限取指定秒数（最多900秒）与范围到期时间中较早者。容器启动由 VM 内独立临时用户 systemd 单元持有，期限结束后强制清理该容器；容器内程序暂停自己的计时进程也不能取消外部单元。停止和清理允许有界核对时间，不等于到期瞬间所有资源消失。正常 Ctrl-C 会先关闭转发入口，再核对容器、网络并释放原网址记录。没有新增 Mac 或 VM 永久启动项。

若启动器被强制终止、SSH 回执丢失或清理未确认，保留原网址记录，不会覆盖或自动重启。用同一网址显式核对停止：

```sh
DSH_HOME=/home/purge/.dsh-improved /home/purge/.local/node/bin/node /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-runtime-source.mjs --stop --origin http://127.0.0.1:18080 --confirm-stop
```

清理仅针对记录中所属的进程、单元、容器和网络。无法核对归属或原转发关闭时保留记录。私有运行记录与副本留在 VM，公开仓库不包含它们。0600 记录与显式 CLI 确认防止项目内容和受限工具自行填写关联证明；它们不限制已获授权的同 UID 原版 Shell。

之后可让 DeepSeek 用 `redteam_joint_review` 选择已授权的 Semgrep、ZAP 等步骤。模型不能通过该工具启动应用、填写容器 ID 或自行声明版本匹配。ZAP 前后均核对原入口监听进程、独立期限单元、容器 ID/镜像/启动身份、只读挂载、原项目范围版本，以及副本完整文件集合与哈希。

只有前后都通过时，`webTarget.appRevision` 和 `artifacts.runtimeSource.state` 才为 `managed-source-copy-matched`。中途停止、到期、来源变化或核对缺失为 `unconfirmed`；没有受管入口仍为 `not-proven`。HTTP 发现始终 `snapshotId:null`，`repositorySnapshotId` 只关联源码审查上下文；所有命中保持待验证。此关联不证明依赖或构建完全可复现、进程内存未变化、所有响应只由某段源码产生，也不证明应用安全。
