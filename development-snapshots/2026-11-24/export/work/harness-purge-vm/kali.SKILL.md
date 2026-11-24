---
name: kali
description: 在用户明确要求使用 Kali Linux 时，通过专用 SSH 连接调用 Kali VM 内的命令行工具，并返回真实输出。
---

# Kali Linux VM

从 Harness 的原生 bash 工具运行 `/home/purge/.local/bin/kali-vm`。

```sh
kali-vm status
kali-vm exec -- nmap --version
kali-vm exec -- python3 --version
kali-vm shell
```

`exec --` 后是命令及独立参数，客户端保留参数边界。需要管道或重定向时，明确使用 `kali-vm exec -- sh -c '命令'`。命令在 Kali 中运行；Harness 本身的工作区文件不会自动出现在 Kali。

只按用户已授权的任务、目标和动作调用工具。先确认 `status` 的主机名、普通用户和持久化标记，不要把 Harness VM 本机执行当成 Kali 结果。版本查看和只读状态检查不发起扫描。新增扫描、修改或管理操作需要对应的明确范围。

连接使用专用普通用户 `harness`、VM 内私钥及固定主机公钥。不自动 sudo、切换 root、启动 Kali 或重试远端命令。需要额外权限时说明原因、具体对象及拟执行动作，取得同意后再做；不得因连接失败改用其他主机、清除主机密钥校验或开启宿主共享。

Kali 未启动、已记录的固定地址不可达、主机密钥变化或认证失败时，报告实际错误并停止。地址变化应由宿主重新核对 Kali VM 的 MAC 和公钥后维护固定地址，不自动发现其它内网机器。SSH 失败或超时不证明远端命令没有执行；涉及写入的命令先只读核对结果，避免重复执行。

单条代理隧道沿用 10 分钟连接上限。长任务应在 Kali 中采用可观察的后台任务，保存任务标识并单独读取状态；不要将 SSH 请求已接受当成任务完成。不要自动重放长任务。

私钥和主机信任保存在 `/home/purge/.config/harness-kali/`，不得读取到对话、日志、提示词或公开仓库。此连接不提供图形桌面操作、任意内网代理或宿主文件访问。
