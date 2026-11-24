# Scoped review: all20 fixture-link lifecycle change

**Verdict: PASS-limited.** I found no blocker in the enclosed bytes. The PASS does not cover several changed files that were not enclosed (section 2). One of them is consumer-12, the first smoke suite.

**Method.** I did a text-only review of the enclosed file bodies, the diffs and the qualified evidence JSON. I used no tools, did no hashing and executed nothing. The hash statements below are consistency checks between declared values only. I did not hash any bytes myself.

---

## 1. Actual blockers in enclosed scope

None.

**`FixtureLinks` (`candidate/checks/regression_lib.py`)**

- `track` rejects paths outside the root using a lexical `commonpath` check.
- It rejects a non-directory parent and a symlinked intermediate component, because each chain element is `lstat`'d and must be `S_IFDIR`. It also rejects non-symlink targets and non-owned links.
- `close` checks everything before unlinking anything:
  - root identity
  - a full `lstat` walk for unregistered links
  - every record's chain, link identity and `readlink` contents
- `_unlink_record` does the following:
  - Opens the parent with `O_DIRECTORY|O_NOFOLLOW`.
  - Checks the parent's identity with `fstat`.
  - Rechecks the link's identity and contents relative to the parent fd.
  - Unlinks relative to that fd, then confirms the link is absent.
- It never follows the link, so the external sentinel cannot be touched.
- `_links` is cleared only when every record succeeds.

**Close ordering at all four call-site patterns**

| Call site | Close placement | On close error |
|---|---|---|
| `scenario_stage_identity` | `passed` computed in `try`, then close in `finally` | retire skipped |
| `test_recover_stage_link_and_identity` | same as above | retire skipped |
| rev8 `test_final_symlink_blocked` / `test_intermediate_symlink_blocked` | `checks` and `record()` both run inside `try` before `box.close()`; `linkRetained` / `actualPathIsLink` are evaluated before close | retire skipped |
| `SyntheticRecovery.close` / recovery-close `Workspace.close` | links closed after globals are restored | `retire_sandbox` is unreachable; the test `test_recovery_close_error_does_not_retire_unknown` asserts this |

**Close failures fail closed in every runner `main`**

- rev6 and rev8: the native PASS row is already recorded, then an `-exception` FAIL row is added. `total` becomes native+1, `failed` is non-empty and the exit code is 1. The fixed-count reader would also reject the result.
- `run_regressions`: the exception row replaces the native row, `failed` is non-empty and the exit code is 1.

**Operator walker change (`operator/full20_batch.py`)**

- Every `names` entry is now `lstat`'d, and any link yields `linked-file`.
- This closes the old gap where `os.walk(followlinks=False)` placed file links and dangling links in `names`, where they were never inspected. Directory links already landed in `dirs` and were caught as `linked-directory`; the red probe's reason confirms this.
- I saw no change in the enclosed bytes to CAP 64 MiB, STOP 4 MiB, FLOOR 512 MiB, `BATCH_DEADLINE_SECONDS=2700`, ORDER/20 or the publication flow.
- The `GUEST` path edits in `consumer_vm.py`, `status_guest.py` and `run_vm.py` match `newGuestRoot` in `actual-contract-check.json`.

**Line numbers.** The inventory's line numbers for the regressions and rev6 sites (293, 665, 669) match the diff hunk offsets I counted by hand.

**Tests (`checks/test_all20_links.py`)**

- The corrected `test_replaced_parent_retained` now reaches the parent-identity branch: the walk finds `sub/link` at the registered path string, so the earlier "unregistered" branch is not triggered first.
- The link-replacement tests accept `identity|contents`. That makes them robust to immediate inode reuse after unlink and recreate, which ext4 can do; the contents check still differs.

---

## 2. Scope gaps (not reviewed, so not covered by this PASS)

1. **`implementation-shared/applied.diff` and final bytes of `run_unified_recovery_checks.py` and `run_consumer_closure_checks.py` were not enclosed.**
   - The inventory shows unified `b8_directory_symlink` moving from line 742 to line 675, a net 67 lines removed before b8. That is probably a prior file-local link helper consolidated into `FixtureLinks`, but I cannot verify it.
   - `nativeIdsPreserved` / `assertStatementsPreserved` for unified and consumer are declared, not reviewed here.
   - Consumer-12 is the first smoke suite.
   - **Action:** do not treat this review as covering unified-27 or consumer-12 source unless another review receipt covers `implementation-shared`.
2. **`run_evidence_gate_checks.py` was not enclosed.** It is unclear whether its "existing finally rmtree closure" is a direct `shutil.rmtree` (which removes the link) or `retire_sandbox` (which refuses a tree containing a link). Either way the walker now fails closed.
3. **"Generic `retire_sandbox` unchanged."** I can see the final body, but not the before-image, so I cannot compare it against baseline `e7ae3f…`.
4. **Recovery-close final file.** Only hunks were enclosed. It is unverified whether b1 or b2 run in a loop that re-creates `link-stage` in the same workspace, which would leave a stale record and make close raise.

---

## 3. Same-uid private-fixture races (accepted, consistent with prior disclosure)

- **Ancestor swap** between chain validation and the parent `os.open`. This is mitigated by the parent `fstat` identity check. The worst case is unlinking the exact registered link inode wherever it now sits.
- **Same-path recreate** with the same inode and identical contents after unlink. The link would be removed. Harmless.
- **New link created after `_walk_links`** but before unlink. It is retained, and the batch walker then fails closed.
- **Re-creation between unlink and the post-unlink `lstat`.** Raises `still present`, which fails closed.
- **Unreadable subdirectory** makes `_walk_links` raise. This is fail-closed; it is the robustness limitation already disclosed.
- None of this amounts to general adversarial cleanup protection, and I am not claiming it does.

---

## 4. Unchanged route gaps (pre-existing, not introduced here)

- **Non-disposable sandboxes accumulate.** Under the lock, `retire_sandbox` returns `False` silently for non-disposable trees. `SyntheticRecovery` sandboxes contain `recoveries` and `recovery-*` names, which match the `recover` token, so they are never retired. Link-free leftovers accumulate in `checks/tmp` against the 64 MiB cap.
- **Special files are not checked.** The walker checks symlinks only; FIFOs and sockets in `names` are not inspected.
- **Close strictness is untested against product behaviour.** If product code renames, quarantines or replaces a registered link, for example the consumer's dangling plan link or recovery-close b2's `identity_path`, close raises and the suite fails. This fails closed, not as a false pass. Only an immediate close without product action is unit-tested (`test_consumer_damage_plan_registers_its_link`). Native20 is the first real exercise.
- **Linux code paths not run offline.** `FixtureLinks` runs on Linux only through native suites. The new19 ran on the host with Python 3.13.1/macOS; the guest has 3.12.3. The `dir_fd` forms of `readlink`, `lstat` and `unlink` are supported on Linux, but this is not yet executed evidence.

---

## 5. Evidence observations

- **Red rev6 probe source hash is unbound.** It is `5554aae1…`, which is neither baseline `3f193e9a…` nor final `92eff580…`. It is presumably the pre-change candidate, which is the correct before-image for the diff. It is not bound in `SOURCE-REVIEW-FREEZE.json`, and the diff carries no before-hash. The red/green comparison for rev6 therefore relies on that undeclared before-image.
- **Declared values are internally consistent:**
  - green probe hashes equal the freeze entries
  - red `run_regressions` equals baseline
  - `new19StdErrSha256` equals the freeze entry
  - payload, manifest and emitter hashes are consistent across `actual-contract-check`, `frame-headroom` and the freeze
- **Unit-only probe.** The probe replaced `_validate_managed_lock`, so the real lock and `flock` path was not exercised.

---

## 6. Optional suggestions (not corrections)

1. In `track`, reject a path that is already registered. This avoids a confusing partial-unlink failure if a site is ever tracked twice. No current enclosed site does this.
2. Record the rev6 red before-image hash `5554aae…` in the evidence freeze, or state explicitly that it is the pre-change candidate.
3. If permitted, run consumer-12 locally in a scratch copy with shims before the Linux batch. This would exercise product interaction with the registered dangling plan link. Otherwise accept that consumer-12 is the first real test of it.

---

## Summary

No correction is required within the enclosed scope. The one-correction allowance is unused.

The Linux20 consumer12-first smoke may proceed on the basis of this review only if `implementation-shared` (unified and consumer source) is covered by another review receipt. Otherwise, that coverage gap should be delivered before Linux.
