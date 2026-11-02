# 本地认证 ZAP 与解析缺口补查

personal.7 也可在同页“联合安全审查”中手动选择 ZAP，或让模型通过 `redteam_joint_review` 选择已授权步骤。保存范围、命名私有会话与目标条件相同；刷新不会自动选择 ZAP。联合 HTTP 证据不绑定为源码字节证据，详见[联合审查](joint-security-review.md)。

2026-11-01，专用 VM 改进版支持按名称选择私有 Cookie/Bearer 会话，并为 Semgrep 解析失败文件提供有限文本提示。[验收记录](authenticated-zap-verification.json) · [当前状态](current-status.md)。

## 先用合成靶场试用

在 VM 的 Shell 工作台运行，保持终端运行：

```sh
python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-local-lab.py serve --profile my-local-lab
```

脚本仅监听 VM 回环的 18780/18781，创建一次性合成账号，执行一次表单登录，输出 `repository`、`origin`、`profile` 等配置名称，不回显密码或会话值。默认会话有效 15 分钟；`--ttl` 可设 60–3600 秒。第二个端口用于范围外请求的对照记录，不转发到 Mac。

在演练台选中自己的测试项目，打开“安全审计”：把输出的 `repository` 填入“仓库绝对路径”，`origin` 填入“VM 本地网址”，`profile` 填入“ZAP 会话配置名”。勾选 ZAP，确认范围并保存，再点 ZAP 卡片的“开始检查”。不要选择真实项目做合成验收。

停止时在靶场终端按 Ctrl-C。脚本关闭两个监听端口并移除它自己创建的账号与私有会话文件；保留合成项目、无凭据请求记录与关闭回执，便于核对。若改用新的靶场，须更新项目范围和配置名。

## 接入自己的本地应用

本阶段支持单个 Cookie（`name=token`）或 `Authorization: Bearer token`，只限明确的 `http://127.0.0.1:端口`。不自动登录真实账号、处理 MFA 或刷新会话；过期后需自行取得新会话，用新配置名导入并重新确认范围。

在 VM 私有目录准备 JSON 文件，权限设为 0600，勿放入被扫描仓库或公开仓库，也勿粘贴到聊天、网页输入框或命令行参数。下列字段仅是结构示例，值须按自己的应用填写：

```json
{
  "origin": "http://127.0.0.1:18080",
  "header": "Cookie",
  "value": "sid=YOUR_CURRENT_SESSION_TOKEN",
  "verifyPath": "/account",
  "loggedInMarker": "UNIQUE_AUTHENTICATED_PAGE_MARKER",
  "excludePaths": ["/logout"],
  "expiresAt": "REPLACE_WITH_FUTURE_ISO_TIME"
}
```

从标准输入导入，命令参数只含配置名和本机文件路径：

```sh
python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-local-lab.py import-session my-app < /home/purge/downloads/private-session.json
```

导入器仅在专用 Linux VM 的 purge 账号运行，生成新的 revision，校验配置并写入 `~/.dsh-improved/security-auth/my-app.json`；目录须为 0700、文件须为 0600，不接受链接、公共文件或已有名称覆盖。校验页必须是匿名请求无法以 200 状态看到该标记、带会话才能访问的页面；退出路径不可覆盖校验页。

项目范围只保存 `my-app`。原始值不进入范围数据库、网页表单或模型结果。ZAP 每次运行的临时私有副本在结束、失败或取消后清理；原始导入配置由用户管理。原始扫描文件仍保存在 VM 私有任务目录，公开导出不包含这些文件。

## 结果应如何理解

控制器与 ZAP 实际发请求的路径会在扫描前后分别核对登录标记。完整认证结果须同时通过四项核对；配置无效或前置核对失败时不提交扫描。扫描途中登录失效会保留已有结果，标为覆盖不完整与认证未确认，不会把部分扫描计为完整认证扫描。该核对不保证扫描全程持续登录，也不证明整个应用的身份验证安全。

凭据通过精确 origin 的 Replacer 规则注入，不使用 ZAP 环境变量的子串站点匹配。爬虫关闭表单提交，并排除配置的退出路径。固定 ZAP 镜像使用 `-silent` 抑制基线 CLI 启动时下载插件，保留只读容器、资源上限与 VM 原有隔离。范围限制针对审计模块；通用 Shell、浏览器和原版能力仍沿用原权限。

当前固定镜像的 CLI 用 `SourceFileLoader.exec_module(ModuleType(...))` 加载 hook，不提供 `__file__`。认证 hook 依据固定 `/out` 工作目录定位私有副本和核对回执；该兼容性已经按实际加载器回归，并经真实扫描验证。[ZAP hooks](https://www.zaproxy.org/docs/docker/scan-hooks/) 与[自行处理认证](https://www.zaproxy.org/docs/getting-further/authentication/handling-auth-yourself/)可作为背景资料。

## Semgrep 解析失败时

仅对当前扫描报告里的解析失败文件做固定字样匹配：eval 调用、innerHTML 赋值、Function 构造。最多尝试前 20 个候选，每个最多 1MB、总读取最多 8MiB；越界、链接、硬链接、二进制、超大或无法读取的文件会跳过。仓库根目录在扫描开始时固定身份，补查时发现根路径或身份改变会拒绝继续。

提示使用 `harness-text.*` 规则，严重性为 info，状态为待验证。注释或字符串也可能命中；不收录源码片段，不执行文件，不补造语义解析覆盖。原始 PartialParsing、任务 partial 状态和未确认发现保持原样，补查不能自动关闭发现。UI、报告、模型均分别显示候选数、检查数、跳过数、提示数和窗口截断状态。

本轮更新了扫描覆盖策略标识。旧任务不直接当作新策略的同覆盖基线；需要重新扫描取得同策略记录后再比较。Semgrep 本身的解析缺口仍存在。

## 验收边界

真实验收只使用 VM 本地合成数据：认证成功、匿名对照、过期前置拒绝、Bearer 会话途中失效、范围外接收端对照，以及复制的最小有效 JavaScript 解析失败样本。日常界面另外提交了各一次 ZAP 与 Semgrep，报告实际下载成功；测试账号、私有会话与监听端口已清理。

本轮没有调用模型、重扫真实项目或改变其发现状态。真实项目 459 项受跟踪文件、HEAD 与六张审计表保持原样，95 条发现继续待验证。新环境的真实账号、复杂登录流程和完整安全覆盖仍需另外验收。
