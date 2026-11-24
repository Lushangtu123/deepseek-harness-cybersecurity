复核结论：**本步范围有限通过**。仅依据所给静态源码、补丁、红/绿测试日志和 VM 回执做对照，未自行执行。**本步范围内未发现新增确认阻断；首轮指出的 PEP695 类型参数遮蔽缺口，在“不生成相关条件观察”的意义上已关闭**。但仍只是条件语法观察，不证明运行时内建身份、真实 Flask 来源或第三方导入解析，不放行 R3。

### 1. 类型参数拒绝与旧输入行为

- `candidate/.../eval_guard_review.py` 的 `has_unambiguous_bindings` 在 `ast.walk` 开头增加了：任意节点 `type_params` 非空即返回 `False`。该 helper 同时被 `canonical_flask_request` 和 `eval_import_review.target_sink` 使用，因此覆盖：
  - caller 的 import-flow；
  - callee 的 import-flow；
  - literal-identifier guard；
  - plain-string guard。
- `type-parameters-red.txt` 的 6 个失败，与候选测试中泛型 callee 3 个子例、泛型 caller 3 个子例对应；候选测试现均期望 `None`，VM import 专项 9 项通过。
- 非泛型节点上 `type_params` 为空列表或字段不存在，新增检查为 no-op；因此旧单参数路径和四个 namespace 正例保持。正例在 VM 中仍各产生 1 条 import 观察。
- **过度保守性确实存在**：任意无关泛型，例如 `def route[T]`，也会使导入/guard 路径放弃观察；guard/string 测试用 `T` 覆盖了这一点，import 测试用 `request`、`execute`、`eval` 覆盖。该策略只减少观察，不放宽准入，且材料已披露。
- 测试样例主要是泛型函数；泛型类/`type` 别名没有专门样例，但实现按“任意节点非空 `type_params`”拒绝，静态上覆盖，未执行验证。运行时 PEP 695 语义仍未建模。

### 2. 共享 helper 与 namespace 默认隔离

- `direct_call(statement, line=None, *, namespace_sink=False)` 默认仍执行旧调用方协议；只有 `target_sink` 显式传 `namespace_sink=True`。
- `request_call_sites` 和 `discover_import_calls` 均未启用 namespace 模式，因此调用方仍只接受单个 `ast.Name` 参数；`execute(code, {})`、`execute(code=code)`、`execute(*code)`、常量输入、自定义 `args.get` 等均被测试要求为 `None`。
- callee 仅接受 `eval`/`exec` 加 1 或 2 个空字典字面量；动态 scope、非空字典、3 个字典、关键字、展开、转换后的第一参数、`execute` 等均拒绝。
- 旧单参数路径保持；新增 namespace 支持没有泄漏到 guard 路径，guard 测试仍拒绝 `eval(value, {})`。

### 3. 测试与 VM 回执对应

- `vm-python-tests.json`：import 9、batch 9、guard 14、namespace 35，均 `OK`，无 skip；模块与测试源码哈希同候选/identity 对齐。
- `route.json` 九组控制：
  - 控制 0–3：各 1 条 import 观察 + 1 条 namespace 结构；
  - 控制 4–8：各 0 条 import 观察 + 1 条 namespace 结构；
  - 全部仍各 1 条合成 finding，`status=unverified`；普通 `security_finding` 表 0 行；
  - `scannerInvocations=0`、`modelCalls=0`、`qualificationCasesAdded=0`、`ordinaryR3Qualified=false`；
  - 173 项程序逐项哈希复核，日常 169 项前后不变，运行规则/镜像清单不变。
- 单元 batch 夹具的行号为 `sourceLine=8/callLine=9`，VM route 夹具为 `sourceLine=4/line=5`，两者是不同合成源码，内部均一致，不构成回执矛盾。
- guard 14 项是在 VM Python 单测中通过；route 的合成 finding 是 `dynamic-code-namespace`，不会产生 guardEvidence，因此 route 中不出现 guard artifact 与测试通过并不矛盾。
- 合成 scanner/tool 就绪与规则回执仍是夹具；namespace 沙箱和默认 Python 证据进程按材料是真实执行路径，但未执行合成项目源码，也未证明真实导入/内建身份。

### 4. 关闭判断与范围外

- **首轮 PEP695 缺口：已按保守拒绝关闭**。不再对泛型 caller/callee 生成 import-flow 或 guard 观察；但这只是保守拒绝，不是精确作用域解析。
- **本步新增阻断发现：0**。
- 仍范围外且未关闭：类方法 import-flow、更长调用链、第三方 runtime 导入来源证明、复杂数据流、真实 Flask 请求/内建身份证明、R3 独立准入。
- 清理方面，本包可见 `acceptance-r2/vm-cleanup.json` 对应第二轮私有副本清理；首轮副本清理无独立回执文件，故该项仅作材料陈述，未作为代码层已验证项。
