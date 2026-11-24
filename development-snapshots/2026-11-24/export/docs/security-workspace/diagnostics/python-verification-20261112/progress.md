# 进度

已固定当前实际工作树文件，不使用旧HEAD。先做S1红/绿回归。

S1 红/绿：预算9、Node计数+source client56、旧adapter Python9、联合/规则合同34通过。Claude周额度不足。首次fallback在SSH connect阶段拒绝（VM stopped）；启动既有隔离VM并仅恢复既有代理；原intent目录不存在时按同一intent提交，没有重发已存在任务。

S2 首轮VM能力预检：SKF确认、有限集合合成排除；OWASP Cookie二次解码导致+空格、负数切片未证明，两者unknown，未误排除。修正固定入口Cookie传输编码和受限字符串类型切片后新任务复验；旧结果 live-result.json 保留，首轮VM目录 /home/purge/.cache/python-execution-live-f1e62199ec，第二轮intent固定。

S3 集成：第一轮配置挂载路径/policy.json导致Semgrep前缀harness而非policy.harness，所有原始命中保留为unsupported；first-failure-detail和failed-evidence存档。第二轮恢复原固定/policy/rules.json路径，在新VM目录完成5raw/5mapped/4point,2confirmed/2excluded,0wrongExclusion,no-sinknot-required；本机/VM v8完全一致；日常169program/42DB/configruntime一致。每点status/recover查询原任务不重放。新增实际VM产物7项篡改回归（重算摘要也不能借ID、回显挑战或危险有限集合），人审单列不计工具主分。S3外审进行。

S3-r3 completed: actual FD-read tests4 green, DeepSeek no confirmed safety blocker after Claude weekly quota; S3 closed. S4 final source acceptance prepared.

S4 bookkeeping: archive script used nonexistent notes key, stopped before writing export.json. Corrected to actual securityWorkspaceP0 container; source/ledger writes already completed and idempotent. No product or daily VM changes. Final native acceptance 15 inspect/11 refusal cases; current local225 Python+154 Node tests green.

S4 parent DeepSeek length/empty archived. Split isolation, scoring and acceptance reports returned. Two Node regressions reproduced and fixed; Python rejects alternate dependency lock. Current S4-r2 VM repeated 4 approved points and 11 boundary cases. Each of 15 stage mounts inspected with exact source map. A synthetic unlisted file present in project did not reach the stage. 5 mapped hits across 4 points, Mac/VM v8 exactly equal and blocked. Final scoped follow-up pending.

Final S4 review closed after inspecting raw report and current source. Local226 Python/156 Node tests; final VM 2confirm2exclude,11 source refusal,15 policies; Mac/VM scores same blocked,169program/42DB protected. No new independent samples, daily deploy or push. Export rechecked after final review archive.
