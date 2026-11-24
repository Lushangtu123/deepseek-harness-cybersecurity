## 复核结论

**本步确认阻断：无。** 静态词法审读未发现会使新观察变成错误放行、越界观察或证据身份不一致的缺陷。

### 已核对且成立

- **owner 查找与边界**：`while` 停在 FunctionDef/AsyncFunctionDef/ClassDef/Lambda；`method` 仅当 owner 的直接父是 `tree.body` 中的顶层 ClassDef 才为真。嵌套函数、方法内嵌函数、嵌套类内方法、async 方法、lambda、类体直接调用均被拒（`owner=None`）。`not isinstance(owner,ast.FunctionDef) or statement not in owner.body or owner not in tree.body and not method` 的 and/or 优先级符合预期。
- **前缀/控制流**：`execution_prefix` 先验 `direct_statement`（仅 Return/Expr/单 Name Assign 值为 call）；每层只认 `container is Try` 且 `statement in container.body`，故 orelse/finalbody/handler、if/for/while/with/match、外层 `return`/`raise` 前置语句、嵌套调用 `consume(eval(...))`、默认参数求值（owner=None）均不获得观察。合并顺序为外到内、只取 `[:index]`；循环上界 9 次对应 8 层 Try，与声明一致。
- **写入/绑定语义**：`scope_nodes(prefix)` 见 Name Store/Del、定义名、alias、ExceptHandler、Match 捕获，`writes` 非空→`local-reassignment-observed`，否则 `binds`→`local-binding-observed`；>64 行仍整体 unmatched。前缀中更早 Try 的 handler 写入被计入属**过度保守**（只降级，不升为参数来源），方向安全。
- **类属性/全文件影响**：类体 `eval = custom`、`from x import eval` 不被 `binds(scope_nodes(tree))` 误判（跳过类体、只取 header）；裸名不沿类属性字典解析，符合 Python 名称规则。但 `binding_hint` 的全文件 `ast.walk` 与 owner 全体的 `binds` 仍照旧运行，同文件其他裸 `eval`/`exec` Load 仍会升级为 `namespace-effects-observed`。
- **方法约束固定 unresolved**：`constraint_hint(None if method else owner,…)` 使方法立即返回 `unresolved`，`fixed-set-guard` 语法也无法成立；`disposition`/`builtinIdentity`/`externalControl` 恒为 `unverified/unverified/unverified`。顶层直线函数仍走原路径。
- **兼容与 schema**：managed/batch 输出字段、kind/binding 枚举、projection 校验（`checks==locations.size`、`observations+unmatched==checks`、`assignmentLines ≤ anchor.line` 允许同行）均能容纳新组合；`personal-namespace-evidence.mjs` 内容未改。
- **身份 pin**：沙箱常量 `6c8c7446…` 与 candidate worker、`analysis.workerSha256`、`frozen-inputs.programFiles` 一致；运行前 `digest(readFileSync(worker))` 校验不变。

### 条件性观察（不影响本步通过）

1. **范围扩张未在声明中单独点名**：顶层函数 try 内参数名由 `expression-unresolved` 变为 `parameter-name-observed`（约束仍 `unresolved`）。与“受保护 try 主体补观察”一致，但与“原顶层直线函数行为保留”并列时建议显式区分“直线”与“try 内”。
2. **方法 constraint 的 reason 复用 `callee-or-scope-unresolved`**：语义上把“方法策略固定 unresolved”表述为 callee/scope 未解析。字段不变、单条证据可解释；若下游按 reason 归类会产生轻微误读。
3. **前缀写入过度保守**：前缀中更早 Try 的 handler/else 写入被纳入 `writes`，可能把本可观测的参数名降级。安全方向，无假阳性风险。
4. **边界测试缺口**：8 层 Try 通过、9 层拒绝未被显式测试（仅到 2 层）；代码上界看似正确，属覆盖不足而非缺陷。

### 范围外 R3 缺口（不在本步）

`externalControl`、`builtinIdentity`、`constraint` 仍 `unverified/unverified/unresolved`；未放行 R3；未部署 daily；本步 0 新扫描、0 业务模型调用、0 独立准入样本；toolStatus/scanner receipt 为夹具。声明与之一致。

### 测试证据是否支持声明

记录材料自洽：`red.txt` 旧实现 7 失败恰为本次新增 7 项（类属性、方法参数、方法固定集合、方法前缀×3、嵌套前缀），`green.txt` 32 OK、`vm-python-tests` 32+4 OK、`node-tests.tap` 30/30、`plugin-regression-summary` 1000/1000、`route.json` 回放给出 before.py:46 单条 `parameter-name-observed`/`no-direct-conflict-observed`/`unresolved` 且 `programFilesRechecked=173`、daily 169 未变。这些是夹具回放，非本次实际执行；作为静态审读，不足以确认“无回归”，但与声明不矛盾。
