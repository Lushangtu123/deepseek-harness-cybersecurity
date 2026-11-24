> 2026-11-02 `.11` 补充：PhishGuard旧脱敏副本额外引入的1条语法错误已修复；原始i18n文件的3处解析缺口仍保留。原文件/副本/转义控制的逐项归因见[本轮记录](template-model-parser.md)。未改项目或切换扫描器。

> 当前新增 Mac 统一启动器选项11，把本自检接入显式候选切换；输出目录已改为有容量限制的容器tmpfs。参见[候选准入说明](scanner-admission.md)。下文的手动自检入口仍可使用，已知解析缺口仍保留。

# Semgrep 解析缺口与离线自检

当前固定镜像 Semgrep 1.182.1 对仓库内11行合法 JavaScript 复现仍出现 `PartialParsing`。Node 语法检查通过，原样1169行文件的只读复制件也能复现。默认/Tree-sitter 后端均解析不完整；备用 PFFF 在第一行 `import.meta.url` 的 `import` 位置报语法错误，无法兜底。将复制件改用 TypeScript 方言仍失败。将该正则开头的 `<` 写成 `\x3c` 的对照可完整解析，但这不是原解析器修复，也不能据此自动改写真实项目。

此前记录中的官方发行核对为 [v1.183.0](https://github.com/semgrep/semgrep/releases/tag/v1.183.0)，此前该候选已对完整复制件验证仍有缺口，本轮未重新下载或更换镜像。固定安装版本的 `v1.182.1` GitHub 标签无法读取；[邻近 v1.182.0 的解析器选择源码](https://github.com/semgrep/semgrep/blob/v1.182.0/src/parsing/Parse_target.ml)仅用作机制参考，具体运行结论来自已安装镜像实测。

在 VM Shell 工作台中运行：

```sh
python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-parser-check.py
```

命令只扫描五个内置合成夹具：原始复现、转义对照、良性代码、带 `eval` 的规则阳性和非法语法。不执行夹具，不访问真实项目，不写审计发现，不调用模型。容器无网络、根文件系统只读、非 root、丢弃 capabilities，45秒超时；不拉取或安装镜像。只输出经过核对的文件名、诊断类型、计数与镜像身份，不输出原始诊断或源码。

| 退出码 | 含义 |
|---|---|
| `0` | 原始复现和全部正反例控制通过；只证明这组夹具通过 |
| `2` 且结构化控制通过 | 自检正常运行，但原始解析缺口仍存在 |
| `1` | 自检未完成，或控制、结果结构、清理检查未通过；不能认定解析器可用 |

参数格式错误可能在命令行解析阶段返回2且不产生JSON；这不代表执行过自检。须同时核对结构化的 `executionOk`、`controlsPassed` 和 `parserReady`，不能只凭退出码认定结果。

当前固定镜像预期返回 `executionOk: true`、`controlsPassed: true`、`parserReady: false`、退出码 `2`。这不是修复成功。解析统计命令本身可能在有解析错误时返回0，因此不能只看进程退出码；自检同时核对实际处理文件、语法错误和规则阳性/阴性。

若已有通过现有来源校验流程、已加载到 VM 的 Linux ARM64 候选镜像，可明确指定不可变内容 ID：

```sh
python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-parser-check.py --image-id sha256:IMAGE_CONTENT_ID
```

用实际64位摘要替换占位值。该选项不接受镜像标签、不下载镜像、不切换当前镜像。只有已审查的本地候选适合此流程；容器输出目录是可写挂载，结果读取上限不是磁盘配额。本工具提供人工候选验收依据，没有接管或自动阻止所有安装入口。即使退出0，仍需其他语言、规则、完整原样复制件和具体项目验收后，再考虑采用。

真实项目的原文件、原始解析诊断和95条待验证发现保持原样。有限文本补查继续作为提示；不把它计作语义完整覆盖，也不自动关闭发现。真实整夜休眠验收按用户要求推迟。
