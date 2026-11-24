# 在 Harness 中调用 Kali Linux

在 VM 改进版新聊天中说：“使用 Kali 技能，检查 Kali 状态和 Nmap 版本。”模型会读取 `kali` 技能，并通过原生 bash 调用独立 Kali。Shell 工作台也能执行：

```sh
kali-vm status
kali-vm exec -- nmap --version
kali-vm exec -- python3 --version
kali-vm shell
```

`exec --` 后每个参数保持独立；管道和重定向需要显式使用 `sh -c`。文件保存在 Kali 中，Harness 的项目不会自动复制过去。此次验收未扫描任何目标；后续任务应明确授权目标、动作和范围。

## 演练台「环境适配」

页面新增“工具执行位置”：选择“远程 Kali · 专用 SSH”后点“保存”，顶部显示远程 Kali 和实际找到的工具数。刷新只通过既有 SSH 连接读取系统及工具可执行文件位置，不扫描目标。当前已保存远程 Kali，工具目录扩展到26项，实际找到25项。首次接入时的6/15项记录保留为历史。Chrome 已核对25/26状态、保存成功和整页刷新后仍选中远程 Kali；不是仅凭后端结果推断界面。

页面列出的 `~/.local/lib/harness-kali-tools/<工具ID>` 是 Harness 内调用入口，实际执行发生在 Kali。输入、输出、词表和模板参数都应为 Kali 内路径；文件、FOFA/VPS凭据和本机环境变量不会自动传过去。返回 Harness 的是 stdout、stderr 和退出码。本机路径配置保留，切回“本机”后生效；选择 Kali 时缺失或未确认的工具不会回退到本机。

连接探测异步执行，最多12秒/64KiB，并发请求共用在途探测；失败清除当前工具结果。成功观察90秒后过期，长暂停或时钟回退不重标为新结果。刷新页面或模型预检会重新探测；工具入口执行时仍实时连接并查找工具，SSH失败不重试或改信任。远程预检不假装检查过本机技能资源，缺失项单列。工具就绪不代表所有技能、模板、FOFA/VPS或网络目标已配置。

## 工具补充与调用

2026-11-01在 Kali 普通用户目录 `~/.local/bin` 安装官方 Linux ARM64 发布文件：fscan 2.2.2、gogo 2.15.0、suo5 2.2.0、frpc/frps 0.71.1、chisel 1.12.0、dnsx 1.3.1、subfinder 2.17.0。每个下载的大小与 GitHub 发布资产 SHA256 摘要一致，安装前核对 ELF AArch64；这不是独立代码审计或签名认证。未使用 root、sudo、APT、额外 capabilities 或新服务。

同时将 Kali 原有的 curl、wget、dig、OpenSSL、tcpdump、TShark、WhatWeb、Nikto、sqlmap、file、strings 加入环境适配目录及固定 SSH 入口。可在聊天要求使用 Kali 技能，或在 Shell 工作台运行：

```sh
kali-vm inventory
kali-vm tool dnsx -version -duc
kali-vm tool subfinder -version -duc
kali-vm tool openssl version
```

所有已找到的25项均通过 Harness 固定入口实际执行过版本或帮助查询。Masscan 1.3.2 的 `--version` 正常打印版本后按上游源码退出1，入口保留该原始退出码；其余24项本次查询退出0。未执行目标扫描、实时抓包、隧道服务或提权；安装或发现工具不代表抓包权限、模板、词表和外部账户已配置。

唯一未找到的 ksubdomain 保持不可用：检查的官方 v2.4.0 发布资产没有 Linux ARM64 版本，未安装 AMD64 文件，也未增加编译器进行源码构建。工具检索忽略相对和空 PATH 目录，再补充普通用户的绝对 bin 目录，避免把当前目录同名程序误认为已安装工具。

公开备份只包含客户端、26项入口和[发布来源/摘要锁定清单](../work/harness-purge-vm/kali-tools-lock.json)，不含二进制和安装包。恢复公开源码后，Kali 中这些二进制仍需单独按清单安装；旧恢复点也未覆盖本次补充。

## 当前部署

独立 Kali 2026.3 ARM64 从 64 GiB 虚拟盘启动，根分区 `/dev/vda3` 为 ext4。安装前已核对目标 VM、MAC、磁盘容量和空白盘；仅对用户明确授权的 Kali 磁盘分区，未操作宿主或 Harness 系统盘。官方安装器完整 SHA256 与官方签名均已验证；派生启动镜像仅改动 GRUB 配置及其校验记录，原始镜像保留。安装结束已正常关机、弹出光盘，再从磁盘启动。

连接链为 Harness bash → `~/.local/bin/kali-vm` → SSH 经已有代理 → Kali `harness` 普通用户。当前主机名为 `kali`，UID 1000，Nmap 7.99。Kali 重启后 boot ID 实际变化，持久化标记和专用 SSH 连接仍可用。Harness 远程连接仍仅使用密钥登录；按用户后续要求，现有 `harness` 账号已设置本地登录密码并通过本地密码校验，密码不写入公开仓库。SSH 密码认证继续关闭；用户组和 sudo 规则未修改，无密码 sudo 没有新增。

宿主代理只将精确别名 `kali.harness.internal:443` 映射到已由宿主核实的 `192.168.64.7:22`。原公共来源白名单、DNS 非公网地址拒绝、16路并发、10分钟连接上限及现有进程配额不变。没有新守护进程、共享目录、剪贴板、USB 或宿主完全访问权限。

代理固定的是地址和端口，不实时验证 UTM UUID；实际 Kali 身份由专用 SSH 客户端固定的主机公钥在客户端认证前验证。DHCP 地址复用时，原始隧道可能连接该地址的另一 SSH 服务，但标准 `kali-vm` 客户端会拒绝错误公钥，不执行命令。地址变化后应由宿主重新核对指定 Kali 的 MAC 和公钥，再维护固定地址；不自动发现其它内网机器。

## 身份与恢复

Harness 中 `~/.config/harness-kali/` 的目录权限为0700，私钥、SSH配置和固定主机公钥文件为0600。连接使用 `BatchMode yes`、`IdentityAgent none`、`IdentitiesOnly yes`、`StrictHostKeyChecking yes`，不使用全局 known_hosts。Kali 禁止密码/交互式认证、root登录和转发，仅允许 `harness`。

公开仓库只保存客户端、技能和配置范例；不保存私钥、实际 known_hosts、聊天、安装光盘或 VM 磁盘。公开源码恢复不会自动恢复账号连接。需要在新的 Harness VM 内生成专用密钥，只把其公钥安装到已确认的 Kali；独立核对 Kali 公钥后写入私有 known_hosts，再安装下方配置范例。不能从网络首次响应直接接受未知主机公钥。旧恢复点 `ready-storage-dashboard-20261101` 和24个既有点均保留，尚未覆盖此次桥接和独立 Kali 系统盘；它们不能当作 Kali 的完整备份。

参考范例为 `work/harness-purge-vm/kali-ssh-config.example`。该文件不包含密钥，也不自动安装或格式化任何磁盘。

## 故障与限制

Kali 需要已启动；工具不会自动启动、提权、修改信任或重放远端命令。10分钟隧道上限仍有效，长任务需保存远端任务标识并单独读取状态。SSH 失败不能证明写入未发生，先核对结果再决定重试。

本轮发现并修复：代理请求时启动 `utmctl` 会碰到现有 UID 进程配额而返回502。现在直接连接固定地址，不产生子进程或 DNS 查询，保留原配额。验收脚本另外适配了新版 OpenSSH 输出配置名保留大小写的行为。安装晚期下载服务刷新造成的一次连接拒绝及 `in-target` 的 `/run/sshd` 绑定目录问题已分别定位、补齐并验证；没有重新格式化。

真实验收涵盖聊天读取技能、两条原生 bash 命令成功；正常SSH、错误主机公钥与错误客户端密钥拒绝；参数中的空格、分号、命令替换文本保留字面值；远端退出码23传回；无密码 sudo 拒绝；Kali真实重启后连接恢复。首次桥接验收时，受保护项目459项文件、HEAD、六张审计表、95条待验证发现和134项程序匹配原基线。本轮环境适配新增模块后为135项程序，已核对当前源码摘要；项目与审计记录仍保持原状。验收没有发起扫描、验证或利用。

官方安装与身份校验参考：[Kali 安装说明](https://www.kali.org/docs/installation/hard-disk-install/)、[官方镜像校验](https://www.kali.org/docs/introduction/download-official-kali-linux-images/)、[OpenSSH 配置](https://man.openbsd.org/ssh_config)。
