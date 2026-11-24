**Scope:** S1 model-count/budget accuracy only. Current Python adapter `7daa08…`, Node joint review `9d35e9…`, client `9eb4c6…`. I found **no confirmed S1 safety blocker** in the current code.

**Verified behaviors**
- `ModelBudget.initialize()` is explicit, locked, refuses overwrite/symlink, and writes `version/identity/maxCalls/maxOutput` before the worker/gateway starts.
- `reserve()`/`snapshot()` fail closed on missing, corrupt, wrong-identity, or wrong-limit counters. Missing counter does not become zero; no counter file is created by reserve.
- `flock` serializes instances; `atomic()` writes temp, fsyncs file, replaces, then fsyncs parent before forwarding. A reservation is not refunded on uncertain upstream result.
- `model_count_view()` only treats protocol1 PentAGI counts as verified from the budget; REA is fixed zero; legacy/missing counts are projected as `null`/`legacy` plus `modelCallsRecorded`, without rewriting the receipt.
- Node `modelCount()`/`view()` produce a task total only when every step is verified; otherwise total is `null` with `knownModelCalls` subtotal. UI labels legacy recorded numbers as unverified.
- The red logs are **not current-SHA evidence**. `python-red` reports missing `initialize`/`model_count_view`, which exist in `7daa08…`; `durability-red` reports no parent fsync, but current `atomic()` does fsync the directory; `node-red` fails the old `view()` behavior while the supplied green suite passes the four model-count tests. Those red results cannot support a current defect.

**Non-blocking, concrete limitations**
1. **Pre-receipt recovery wedge.** `main(run)` creates the job, payload, and source before `ModelBudget.initialize()` and before writing `receipt.json`. If initialization fails or the process dies in that window, a duplicate `run` hits `read(job/'receipt.json')` and fails; `status`/`cancel` also require the receipt. This does not create a zero count or forward a request, but it leaves a manually recoverable orphan job. Confirmed from control flow.
2. **Node trusts the adapter’s `verified` assertion.** `adapterResult()` validates `modelCalls` as integer `0..16`, but does not require `modelCallsProtocol===1` and does not independently prove `modelCallsState:'verified'`. It also accepts any integer `modelCallsRecorded`, which `modelCount()` can surface as “legacy.” Under the trusted local adapter this is acceptable; it is not independent Node re-verification, and the later verifier is not implemented.
3. **Client validation does not bind total state to count.** `validTask()` allows `modelCalls:0` with `modelCallsState:'unknown'` because it only checks numeric/null `modelCalls`. The renderer prints `task.modelCalls??'未知'`, so such a malformed response would display `0` rather than unknown. The server normally emits `null` for unknown totals, so this is a defensive-validation gap, not a demonstrated live path.

I do not re-raise the shape-only deep-rule finding: the supplied regression explicitly exercises altered mode/count/hashes and added fields. No R3 or live-acceptance claim is made.
