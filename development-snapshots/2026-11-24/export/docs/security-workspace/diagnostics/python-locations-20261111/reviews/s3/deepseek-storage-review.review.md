**Verdict:** No confirmed safety blocker in the supplied S3 point-ID/scanner-span slices. I found two concrete non-safety defects and one acceptance-evidence gap. No R3/live claim is supported.

### 1. Malformed “bound” Python mapping can crash the managed run

`bindPythonExecutionPoints` compares `digest(m.scannerSpan)` for every bound map. `collectPythonEvidence` validates `m.point`, `m.pointId`, path and rule, but **does not require `m.scannerSpan`**. If an otherwise valid mapping omits `scannerSpan`, `digest(undefined)` evaluates `JSON.stringify(undefined).replace(...)` and throws `TypeError`.

The workbench calls `bindPythonExecutionPoints` outside the surrounding evidence try/catch:

```js
try { ... this.pythonEvidence(...) ... } catch { details.pythonEvidence = unavailable }
const points = bindPythonExecutionPoints(result.findings, details.pythonEvidence);
```

Repro: managed deep Semgrep with a bound `sourceLocation`, valid point/pointId, and `findingLocations[0].scannerSpan` absent. The run fails instead of marking the AST location unmatched/unavailable. This is fail-closed, not a security bypass, but it is a reproducible scoped regression for older or malformed worker output. Tests supply `scannerSpan`, so this path is not covered.

### 2. Missing PentAGI/model call counts are coerced to zero

`adapterResult` accepts a missing `result.modelCalls` as `0`:

```js
!Number.isSafeInteger(result.modelCalls??0) ...
step.modelCalls = result.modelCalls??0;
```

`view()` then sums undefined step counts as zero:

```js
modelCalls: data.steps.reduce((n,s)=>n+(s.modelCalls??0),0)
```

So an adapter receipt without a call count becomes a precise “0 次” claim in the task/UI. The client test “Missing model counts stay unknown” only exercises a raw task with `modelCalls` absent; the server `view()` normally supplies a number, so the server path is not covered. This is a material accuracy defect for paid/model usage, not a safety blocker.

### 3. Acceptance script does not enforce the historical uniqueness it claims

In `score.mjs`:

```js
must(file.points.length===0||p,'Historical point not unique');
```

This only proves a point exists, not that it is unique. If two historical points share the selected line, the first is used and the “not unique” guard still passes. The VM summary’s historical mapping is therefore weaker than the assertion name suggests. This is an acceptance-evidence defect, not a product-runtime blocker.

### Minor validation gap

`start()` checks `result.executedRules.sha256/count` against the requested deep profile, but only shape-validates `result.ruleProfile`; it does not compare `result.ruleProfile.id/rulesSha256/ruleCount` to the requested profile. The executed-rules hash is independently checked, so this is not a confirmed bypass, but stored `details.runtime.ruleProfile` can disagree with the requested metadata.

### Conservative limitations, not defects

- Ordinary/16-step mode intentionally does not run the Python point worker; deep-only point propagation is a scope choice.
- >64 Python files, insufficient remaining deadline, >2 MiB worker output, and >2 MiB reports degrade to unavailable.
- Prior-sample-only VM hits, zero new independent samples, no browser/native Chrome flow, no external verifier/R3, and no deployment are correctly deferred.
- The 14 raw / 13 bound / 1 unmatched / 8 unique point counts are internally consistent with `caseEvidence`, but they are authored/diagnostic evidence, not fresh independent acceptance.
