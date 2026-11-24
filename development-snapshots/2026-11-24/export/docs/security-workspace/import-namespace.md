# 多参数执行 helper 的条件输入路径候选

本轮复用既有显式导入路径复核器，补充从规范Flask查询参数赋值、紧邻的单参数显式导入调用，到同级helper中双/三参数eval或exec的语法观察。新增支持只接受一个或两个空字典命名空间。旧单参数路径保持，调用方仍只接受一个名称参数；动态/非空命名空间、关键词、展开、转换输入、非直接helper主体等保持未知。

修改2个产品程序和4个测试文件：eval_import_review.py扩展callee语法支持，eval_guard_review.py补充共享泛型绑定检查。direct_call默认仍执行旧调用方协议，只有target_sink显式启用namespace_sink模式；因此callee参数支持不会放宽导入调用方。复用canonical_flask_request、绑定冲突检查、同级文件固定摘要、既有批量自动发现及python-import-flow证据格式。没有为这些组合新增模型工具、UI字段或扫描规则。

先新增7项导入专项，旧实现出现4个子用例失败；修订后7项通过。批量专项9项、namespace35项通过，包含新增的函数/类方法try主体固定集合guard × eval/exec四个对照。所有guard对照constraint保持unresolved、externalControl/builtinIdentity/disposition保持unverified。Mac1000项插件回归通过。外审后补充泛型遮蔽拒绝与净化检查，最终Mac/VM导入9项、批量9项、净化14项、结构35项均通过。泛型专项依赖Python3.12+，本轮两端均实际执行，未跳过。

专用VM临时候选173项程序在模块导入前与完成后逐项摘要核对。合成项目有routes.py与evaluator.py，扫描完成回执、工具就绪与规则执行身份均为夹具，不代表本轮运行过扫描器或完成真实工具准入。实际默认Python证据复核器在独立Python进程中解析受管副本，默认namespace worker在既有禁网只读受限Docker沙箱运行。没有导入、执行合成项目。

| 合成控制 | 条件导入路径观察 | namespace结构观察 |
| --- | ---: | ---: |
| eval + 1个空字典 | 1 | 1 |
| eval + 2个空字典 | 1 | 1 |
| exec + 1个空字典 | 1 | 1 |
| exec + 2个空字典 | 1 | 1 |
| eval + 动态scope | 0 | 1 |
| callee泛型参数eval | 0 | 1 |
| callee泛型参数exec | 0 | 1 |
| caller泛型参数request | 0 | 1 |
| caller泛型参数execute | 0 | 1 |

联合结果经真实受管副本、自动发现、持久化和报告分页读回。路径证据给出routes.py的查询读取第4行、调用第5行及evaluator.py定义/执行第1/2行，status保持unverified；原合成扫描命中也保持unverified。普通发现表新增0。动态scope没有新增导入路径证据，仍能保留单独结构观察。观察只说明固定源码中的条件语法链，不能证明运行时Flask来源、导入解析、eval/exec内建身份、实际对公网可达或可利用。

本轮没有新扫描、业务模型或独立准入样本。VM日常169项程序、运行规则与镜像清单前后匹配，候选临时目录与合成数据库已移除。尚未部署，普通R3保持未放行。新增合成源码摘要在本轮结束登记为已用，不能进入新的独立留出验收。首轮Claude因401登录过期失败，按持续授权使用同一份材料交给DeepSeek官方V4.1 Flash high，获得有限通过并指出泛型类型参数遮蔽缺口。该既有问题经六个失败子例复现后补上共享绑定守卫；最终修订再次先请求Claude，仍返回401；同一份固定材料由DeepSeek官方V4.1 Flash high完整复审，finish_reason=stop，本步范围有限通过，无新增确认阻断。两轮实际响应、原报告、材料摘要和回执均保留。


修订后的共享绑定检查遇到任意非空type_params即停止生成相关观察。该策略覆盖PEP695泛型函数、类或类型别名的未建模作用域，包括request、helper与eval/exec名称遮蔽，也会保守放弃无关泛型带来的本可观察路径。旧版曾在这些输入上产生条件语法观察，但始终unverified；本次并未证明它们是可利用漏洞。共享helper用于导入路径、固定标识符guard和字符串形状guard，三条入口均有回归。动态runtime绑定和第三方导入真实性仍未证明。

最终VM在新编号私有副本重复原四种正例、动态scope负例，并加入callee类型参数eval/exec和caller类型参数request/execute四种负例。共九组控制通过，原四正例各有一条import观察，五个负例均为0条import观察；九组仍各保留独立namespace结构观察及unverified原命中，普通发现表0新增。第二轮9组结果与第一轮5组结果分开保留，两个临时副本分别清理。无新增scanner/model调用，无独立准入样本，候选未部署。


最终复审与本地核对均保持有限结论。泛型函数专项已实际执行；泛型类、type别名没有专门执行样例，虽然共享AST守卫会保守拒绝，仍记为覆盖缺口。首轮验收清理回执未放入第二轮冻结材料，审查员据此没有将其认定为独立验证；该原始回执实际已存在，本次与第二轮回执一并归档，补充可见性，不改写审查原文。两个外部复审目录也在正常结束并保存结果后清理，日常程序169项摘要一致。

46份本轮已用合成源码经过逐份摘要核对，其中43个新摘要登记到样本台账。它们均不具备新独立准入资格。

[结构化结果](import-namespace-results.json) · [证据清单](diagnostics/import-namespace-20261110/manifest.json)


后续[真实扫描与Chrome组件验收](import-namespace-live.md)已对同一173项候选完成实际18文件扫描和完整组件报告检查；产品未改、未部署，完整聊天模型链和独立R3仍待完成。
