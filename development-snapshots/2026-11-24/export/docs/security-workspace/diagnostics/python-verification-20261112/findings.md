# 已核对事实

预算缺文件 fallback0，Node汇总missing0为实际根因；validDeepSemgrepProfile逐字段精确匹配，旧shape-only判断不成立。现有sandbox证据仅字段校验，需真实运行产物绑定。既有三模块快照和存储生命周期可复用。CPython3.12 monitoring CALL回调给code/instruction_offset/callable/arg0，避免替换eval/exec改变作用域。Python钩子不能作为沙箱；Docker才是隔离边界。旧OWASP requirements固定Flask3.1.0/Werkzeug3.1.3/Jinja2 3.1.6/MarkupSafe3.0.2/itsdangerous2.2.0/click8.2.1/blinker1.9.0，helpers/utils.py仅标准库。

S1 implementation readiness confidence 0.95: root cause reproduced from code, existing budget architecture reused, docs and project implementations verified. S2 runtime feasibility must be demonstrated in fixed image before claims.

已从PyPI官方精确版本元数据固定7个wheel，核对上游SHA，解包178文件约2.17MB；仅隔离候选依赖，没有日常安装。S2原VM运行SKF确认/有限集排除，修正Cookie传输编码和负数切片后旧OWASP正确认/阴排除；不是新留出或R3。

S2复审确认固定探针碰撞、单纯nonce回显、同进程轨迹伪造不能建立通用可信确认。修复精确AST探针+内部标记+固定已审阅源码摘要边界。未知源码返回source-profile-not-reviewed不执行。首版scope为轮廓限定预检，无法据此启用新正式盲测；后续需独立观察/认证方法扩展，不能调低R3。四个旧执行点结果为2确认/1严格字符串排除/1有限集合合成排除，原始四文件中的无sink控制后续静态no-hit。
