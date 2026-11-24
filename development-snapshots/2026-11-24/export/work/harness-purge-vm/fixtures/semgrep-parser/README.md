# Semgrep 静态解析复现

只用于`node --check`与Semgrep静态扫描，不执行这两个文件。样例有意保留未定义依赖与空函数；它复现解析行为，不是可运行应用。

固定VM镜像Semgrep1.182.1：repro.mjs共11行，Node语法检查通过，扫描返回PartialParsing；escaped.mjs将正则中的`<`写为等价的`\x3c`，Node与Semgrep解析均通过。11行样例通过逐行删除检验，不能再删去单独一行且同时保留语法有效与故障；不声称全局最小。良性对照亦通过。

从1169行真实文件复制件，经测试块与行删除缩减。原项目未改写、未执行，保留不完整覆盖与95条待验证发现。1.183.0只在上一轮完整复制件验证过，不能把本次11行结果说成也测试了1.183.0。详见docs/ssh-clock-parser.md与docs/security-diagnostics-verification.json。
