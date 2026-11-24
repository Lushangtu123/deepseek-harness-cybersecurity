# Scoped External Review: all20 Fixture-Link Lifecycle

## Verdict: **PASS-limited**

I found no actual blockers in the enclosed bytes. The pass covers only what was enclosed. It rests on text review and on comparing the declared hashes against each other. I did not compute any hashes and did not run anything.

## What this review covers

**Reviewed from enclosed bytes:**
- The `operator/full20_batch.py` quiescence-walk change (rev8-operator diff), in full context.
- The `rev8_support.py` and `run_rev8_checks.py` registration and closure diffs.
- Unchanged constants and deadlines in `full20_batch.py`, `transfer.py`, `linux_admission.py`, `START.json` and `suite-plan.json`.
- Whether the binding documents agree with each other: manifest, payload, policy, freeze and evidence.

**Not reviewable, so not covered by this PASS:**
- The `FixtureLinks` implementation in `candidate/checks/regression_lib.py` (`aeb94fbc…`).
- `checks/test_all20_links.py`.
- `implementation-shared/` and `implementation-fixtures/` diffs, which hold 7 of the 9 registered sites.
- `finalize_closure._FIXED_COUNTS` and its native-ID validation.
- `bounded.py`, `static_check.py` and `independent-component.py`.

The helper's semantics are accepted only as declared by the 19 test names and the red/green probes. If this review is meant to gate the helper itself, enclose those files. I could then review the helper directly.

## Binding consistency (declared values compared, not hashed)

- **Source manifest:** `affef050…` is identical in `START.json`, `suite-plan.json`, payload-manifest, closure-policy (`protocol-manifest.json`), the freeze and actual-contract-check.
- **Payload:** `cba4eb15…` is identical in payload-manifest, freeze (`payload.json`), actual-contract-check and frame-headroom.
- **Payload file count:** I enumerated the payload-manifest entries: candidate 188 (100 non-baseline + 88 baseline), checks/independent 14, operator 11, references 88. That totals **301**, matching the claim.
- **Candidate manifest counts:** the non-baseline candidate set minus 7 proof files and `protocol-manifest.json` gives **92**. This matches `assert len(old)==92`, and with the protocol manifest it matches `requiredCount: 93`.
- **Per-site hashes:** every inventory `sourceSha256` matches payload-manifest, closure-policy and freeze. Examples: consumer `794164a2`, recovery-close `8de5a125`, regressions `5be3cb6b`, rev6 `92eff580`, rev8 `32cd8e24`, unified `9432fcf3`, evidence-gate `36296ba2`.
- **Inventory line numbers:** the rev8 diff hunks reproduce the stated lines exactly (218/218 and 308→310).
- **Historical references:** `candidate/baseline/**` and `references/**` hashes are pairwise identical, so the historical sites are byte-identical copies.
- **Guest root:** identical across `START`, `PROTOCOL`, payload-manifest, `consumer_vm`, `status_guest` and `run_vm`.
- **Interpreter admission:** `linux_admission` expects sha256 `c86f21d0…`, 3.12.3, aarch64 and uid 1000. All four match `vm-readiness.json`.
- **Limits:** 2 MiB header, 64 MiB cap, 4 MiB stop, 512 MiB floor, deadlines of 100/120/2700 s in the batch and 3000 s SSH. These are unchanged in the enclosed code, and `emitterSha256` equals the `transfer.py` hash.
- **New tests:** `new19SourceSha256` equals the freeze entry for `test_all20_links.py`, and the stderr shows 19 tests OK.

## Operator walk change: assessment

`os.walk(followlinks=False)` decides placement with `entry.is_dir()`, which follows links. So:
- Directory links land in `dirs`. These were already rejected.
- File links and dangling links land in `names`. Only the new `lstat` check rejects them.

The new check sits before the `process.json` and `process-*-identity.json` handling. `lstat` errors map to `unknown`. The behaviour is correct and fails closed. The red evidence matches this: the rev6 `dangling` link was invisible to the old scan.

## Findings

### Actual blockers
None found in the enclosed bytes.

### Pre-submission risks
These all fail closed, but any one could stop the sole Linux batch.

**R1. Closure at product-touched sites has not been executed.** Red/green probes cover only `original-28` and `rev6`.

- At the rev8 `effect` site, `track_fixture_link` runs inside the product's `run_recover` callback. The product then continues acting on `box.stage`.
- The 19 test names include no case where a registered link is already absent at close time.
- "External link cannot be registered" may refer to where the link sits or to what it points at. Neither the tests nor the diff settles which.
- If close treats "absent" as a failure, or if rev8's `target` lies outside `box.sandbox`, rev8-13 (group 12) stops the batch.

*Recommendation:* run the existing pure-filesystem before/after probe harness on the two rev8 sites. Do the same for recovery-close B1/B2, unified B8 and consumer `damage_plan` where they are pure. This is local, needs no source change and is not a VM submission.

**R2. The unified B8 site moved backwards.** It went from old line 742 to new line 675, a shift of −67. Every other registration site shifts by +0 to +6, as purely additive edits would. The operation also changed form, from `(workspace.prepare / "plans").symlink_to` to `plans_link.symlink_to`, and B8 is where the interim digest failures occurred.

*Recommendation:* confirm in `implementation-fixtures/applied.diff` that no assertion was moved, merged or removed. `_FIXED_COUNTS` would catch a change in count but not necessarily a change in meaning.

**R3. Platform and interpreter gap.** All 170 checks and both probes ran on macOS with CPython 3.13.1. The target is Linux with CPython 3.12.3.

- Possible breakages include a pathlib or os API added in 3.13, or a difference in `dir_fd`/`lstat` behaviour.
- Running consumer-12 first mitigates this, because `damage_plan` exercises `FixtureLinks` close on Linux in the very first group.

*Optional:* run `test_all20_links.py` under a local 3.12 interpreter.

### Same-uid private-fixture races
These were disclosed and are not claimed to be protected.
- `FixtureLinks` has a window between checking a link and unlinking it.
- The quiescence walk's `lstat` results can be invalidated by later swaps.
- Both depend on a same-uid actor and stay within the sandbox, given the declared refusal of external registration.

### Unchanged route gaps
These predate this change and are not regressions.
- The quiescence walk covers only `candidate/` and `evidence/`. Under `operator/`, `checks/` and `references/`, only payload entries are checked, one file at a time, by `_verify_files`. Extra entries there, links included, are not scanned.
- Non-link special files (FIFO, socket) in `names` are skipped unless they are named `process.json` or `process-*-identity.json`.
- A file link at the top level of `evidence/` is reported with the reason `linked-directory`. Only the label is wrong; it still fails closed.
- Frame headroom of 484,513 B (≈23%) was measured on fabricated evidence. A larger real header would make `emit_frame` fail closed after the batch has already run.

### Optional suggestions
- **rev8 cleanup ordering:** in `rev8_support.close()` and the `test_intermediate_symlink_blocked` `finally`, an exception from `fixture_links.close()` skips `retire_sandbox` and replaces any original assertion exception, which survives only as `__context__`. This cannot produce a false pass, because the leftover sandbox link stops the batch. It does mean a native failure would be reported as a cleanup error. If diagnostics matter, record the close outcome rather than letting it replace the original error.
- **Red-probe provenance:** the red rev6 "before" hash `5554aae1…` is bound by no enclosed manifest. It is neither the baseline nor the current file.
- **"87 baseline":** I enumerated 88 `candidate/baseline/**` payload entries, including `protocol-manifest.json`. I could not reconcile "87" without `BASELINE-FREEZE.json`. `candidate/tools/experiment_runner.py` also differs from `baseline/tools`. That is consistent with "byte-original relative to the freeze", but I can only verify it against that file.

## Bottom line

No change to the reviewed code is required. The new scan is a sound fail-closed backstop, so any unclosed or mishandled link stops the batch rather than producing false acceptance. Before the single Linux submission, I recommend clearing R1 with local probes and R2 by inspecting the diff. Neither needs a correction revision.
