Scoped review only; no R3/live claim.

The `scannerSpan` correction is fail-closed in `collectPythonEvidence`: a v2 `bound` row without `scannerSpan`, with a forged `pointId`, or with a mismatched span digest makes the whole managed result unavailable. `bindPythonExecutionPoints` independently requires `scannerSpan`, rechecks the point identity/SHA/span, and on failure removes stale `pointId`, `executionPoint`, and `executionMapping`. The isolated test covers the missing-span path. No security bypass was found in that fix.

Confirmed scoped robustness defect: `bindPythonExecutionPoints` is not null-safe while `collectPythonEvidence` is. `collectPythonEvidence([null, ...])` is explicitly tested, but binding does `findings.filter(f=>rules.has(f.rule))`, which throws on a null row. Repro: `bindPythonExecutionPoints([null], evidence)`. The binder should use `f?.rule` and preserve null/non-rule rows unchanged or mark them unmatched. This is an availability/scope regression, not a privilege bypass.

Scoped binding gap: bind consumes `maps[index]` positionally but never checks `m.index===index`. `collectPythonEvidence` validates `m.index`, so the current pipeline is safe only if bind is called exclusively with collect output. A direct caller can pass reordered `findingLocations` containing otherwise valid same-path/rule/span points and bind a finding to another valid point. Add an index check or normalize before binding. Defense-in-depth, not a confirmed pipeline exploit.

VM uniqueness guard: same-line uniqueness for files with points is correct. The zero-point branch is unconditional: `file.points.length===0 || matches.length===1`. A positive historical case whose points failed extraction passes and becomes `pointId:null`/`no-hit`; the score only rejects `unknown`, not `no-hit`. Allow zero points only for known no-hit/control cases, or fail positive cases with no points. Current four files may satisfy this, but the guard itself cannot distinguish the cases.

Conservative limitation: one malformed bound mapping collapses the whole collect result to unavailable. That is acceptable fail-closed behavior. No Chrome/new holdout/daily deploy/R3.
