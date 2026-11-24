**Scoped count/renderer review — no confirmed safety blocker**

Verified path is sound: `modelCount` returns `verified` only for `modelCallsProtocol===1` + valid integer `0..16` + `modelCallsState==='verified'`; task total is `null` unless every step is verified; static known-zero steps are protocol1; legacy/missing values do not become verified zeros. The supplied tests pass.

Concrete scoped gaps, not safety blockers:

1. **Unknown+0 still carries a recorded number at the view boundary.**  
   `view([{tool:'pentagi',modelCalls:0,modelCallsState:'unknown'}]).steps[0]` yields `modelCalls:null`, `modelCallsState:'unknown'`, but also `modelCallsRecorded:0`. That is not verified, but the number remains in payload. The test calls `modelRequestCountText({modelCalls:0,modelCallsState:'unknown'})` directly, not the view output. So “never renders a number” is test-evidenced, not source-verified here; `personal-security-client.mjs` was not supplied. If the helper prioritizes `modelCallsRecorded`, the requirement fails. Add a view-level assertion or ensure the helper ignores recorded values when state is unknown.

2. **Adapter receipts can mint legacy provenance.**  
   `adapterResult` validates `result.modelCalls` when present but never validates `result.modelCallsRecorded`. A receipt with missing/invalid `modelCalls` and bounded `modelCallsRecorded:5` becomes `modelCallsState:'legacy'` via `modelCount`. If legacy is only for historical persisted data, reject `modelCallsRecorded` on fresh adapter receipts or downgrade to unknown. Repro: call `adapterResult(data,step,{...base,modelCallsRecorded:5})`.

3. **Malformed “verified” claims are labeled legacy, not unknown.**  
   `{modelCalls:0,modelCallsState:'verified'}` without protocol1, or protocol `2`, yields step state `legacy` with `modelCallsRecorded:0` rather than an invalid/unknown label. The test checks only that the task total is `null`, so this mislabel is untested. It does not create a verified total, but provenance language is inaccurate.

Minor: an empty `steps` array yields a vacuous verified total `0`; `submit` rejects empty steps, so this is limited to corrupt/legacy views.

Budget initialization/flock/fsync was not in the supplied files; no new judgment. The pre-receipt orphan remains the previously recorded fail-closed lifecycle gap, not reclassified. Verifier behavior was not implemented or reviewed; no R3 or live acceptance claim.
