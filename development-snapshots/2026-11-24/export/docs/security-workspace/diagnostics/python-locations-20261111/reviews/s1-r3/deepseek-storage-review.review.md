Confirmed defects/regressions:

1. **Import-evidence authentication is conditional and incomplete.** In `collectPythonEvidence`, caller/sink SHA checks run only when `e.callerLocation` / `e.sinkLocation` exist. If either is omitted, the check is skipped and the artifact is still emitted, with locations silently dropped. The adapter also never independently recomputes caller/sink point IDs; it only compares `sourceSha256`. A report with a missing caller location, or valid SHA but wrong/reused `callerLocation.id`, is accepted. The new test recomputes caller ID in `review_batch`, not in this managed adapter. This is the main safety-relevant gap.

2. **No-Python early return drops supported non-Python findings.** `if(!Object.keys(files).length)return null;` runs before supported findings are mapped. Repro: `snapshot.files=[app.js]`, `findings=[policy.harness.python.eval at app.js:1]` → returns `null`; the worker never sees the supported rule and the finding is not marked unmatched. That contradicts “every supported rule is sent to worker” and “non-Python/non-inventory findings also unmatched.”

3. **Worker-side unmatched status is discarded.** The adapter never reads or returns `report.findingLocations`. Malformed empty-path/missing-span, non-inventory, and non-Python cases can be marked unmatched by the worker, but the managed result contains only `artifacts`. If this result is the observable boundary, those findings remain silently filtered.

4. **Malformed finding elements crash before the `try`.** `findings.flatMap(f=>{ if(!rules.has(f.rule))...})` dereferences `f.rule` without a null/object guard. A `null` or primitive finding throws rather than returning `unavailable`. The Python `review_batch` test explicitly tolerates `None` results; the managed adapter does not.

Synthetic unittest `OK` is unit evidence only; not live VM acceptance.
