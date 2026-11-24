# 空白 VM 基础安装

当前部署与完成状态见[当前状态](current-status.md)。本页说明基础安装入口；实际验收范围以结构化记录为准。

这一步只安装官方 Harness、改进版 dsh-purge 和网页服务。需要新建的 Ubuntu 24.04 ARM64 专用 VM、名为 `purge` 的 UID 1000 用户、`/home/purge`、Python 3.12+、systemd 用户服务、无密码 sudo，以及已由宿主准备的隔离网络。安装器不会创建 VM、修改 Mac 权限或安装网络代理。

将安装源码放在工作区之外，例如 `/home/purge/bootstrap-input/source`，避免把安装源码误当成已有用户项目。先只读核对：

```sh
python3 -B scripts/bootstrap_guest.py
```

确认在空白 VM 后执行：

```sh
python3 -B scripts/bootstrap_guest.py --apply
```

`--apply` 拒绝已有的 `.dsh`、`.dsh-improved`、`tools`、`.local`、`.config`、`.npmrc`、安装标记，以及已有内容或符号链接的 `workspace`。不能用它升级日常 VM。失败后保留 `.harness-bootstrap` 和私有日志，不自动重试、覆盖或回滚已有安装；排查后使用新的空白环境重测。

安装前需备好 `build-essential`、`python3`、`pkg-config`、`ca-certificates` 和 `git`。网络沿用专用 VM 已有的 `10.0.2.100:3128` 代理；网页监听 VM 的 `10.0.2.15:3080`，只信任已有宿主回环入口 `127.0.0.1:49224`。这些固定地址适用于本项目的现有隔离模板，不能当成任意云服务器的一键部署脚本。

Node、Harness 和 pnpm 的直接下载版本及摘要见 `inventory/bootstrap-lock.json`，下载后先核对摘要。依赖初次解析结果保存在新 VM 的 `tools/harness-improved-runtime/package-lock.json`；这不是预先锁定全部传递依赖的离线安装。Node 解压明确使用 Python 的 `data` 过滤器；安装先禁止生命周期脚本，再仅重建列明的五组原生依赖。

安装成功会启动 `dsh-original` 和私有 `harness-security.socket`。如果 `/home/purge/workspace` 已存在，安装器要求目录为空、归 `purge` 所有，且 `purge` 可以读取、写入和进入。`webResponding: true` 表示服务已响应，`workspaceInitializationChecked: false` 表示安装器没有验证默认工作区是否已创建。首次打开空白实例时，浏览器会请求 Harness 创建默认工作区。如需安装专业资产，请在首次打开网页前完成该步骤，因为专业安装器要求工作区目录仍为空。

网页登录链接仅在 VM 的服务日志中生成，含本地令牌，请不要公开日志。模型账号需要在本地配置。安装过程不调用模型或扫描器。

基础安装不复制日常 VM 的账号、聊天、项目、扫描数据、REA、reverse-skill、PentAGI、扫描器资产、桌宠/市场等可选插件，也不启用原版能力运行时或复制本仓库的四个运行时覆盖模块。这些由后续[专业资产安装](professional-bootstrap.md)提供；模型账号和新工作区仍单独配置，不能用网页启动成功推断全部工具已恢复。

恢复预检仍检查完整日常环境；基础安装不应被它判定为整套恢复完成。现有整机恢复点属于原 Mac 的另一个恢复路径，见[恢复说明](restore.md)。

Chrome 验收使用现有宿主串行入口。原始 `49224` 转发口在普通和无痕 Chrome 都出现过资源连接重置，独立顺序读取相同资源成功；复用现有 `createWebEntry` 后完整首屏及插件详情正常。暂不能把这个观察当成已完全定位 SLiRP 底层根因，也不能宣称原始端口直连已通过。

在已准备好本项目 VM 转发、Node 与源码的宿主上，基础环境可临时复用已验收入口（先确保 `63782` 空闲；不会安装 Mac 服务或调用生产管理器）：

```sh
node --input-type=module <<'JS'
import { createWebEntry } from './work/harness-purge-vm/web-entry.mjs'
const unavailable = async () => { throw Error('Basic VM management metadata unavailable') }
const server = createWebEntry({
  environmentReader: unavailable,
  recoveryReader: unavailable,
  capabilityRun: unavailable,
})
server.listen(63782, '127.0.0.1')
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => server.shutdown())
}
JS
```

将新 VM 私有登录链接中的本机端口 `49224` 改成 `63782`，只在本地 Chrome 打开；不要将令牌粘贴到聊天或公开资料。临时入口仍校验 Host、Origin 与 VM 所有者认证，版本/恢复管理明确不可用。完成后按 Ctrl+C 关闭；日常环境继续用原 `49226` 受管入口。

依赖策略依据 [npm rebuild 的项目 allowScripts 规则](https://docs.npmjs.com/cli/v11/commands/npm-rebuild/#allow-scripts)，归档处理依据 [Python tarfile 提取过滤器](https://docs.python.org/3/library/tarfile.html#extraction-filters)。
