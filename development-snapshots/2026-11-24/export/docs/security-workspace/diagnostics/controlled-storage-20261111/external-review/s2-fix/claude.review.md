# Review: S2-fix storage changes (`reviewer_storage.py` 6d4075c1…, `reviewer_snapshot.py` 1b1e40fd…)

This is a static review only. I ran nothing, so I could not check the SHA-256 values in `source-manifest.json` against the bytes. All findings are judged against the S2 scope you described: offline candidate, isolated VM acceptance only.

**Verdict:** I found no safety or under-counting blocker. Every path I traced fails closed, meaning it over-reserves or blocks admission rather than under-counting. One finding (N1) is a liveness defect outside the crash-gap retention you accepted as F5. I recommend fixing it, together with the small N2 fix, before S3. The rest are low-severity fixes or bounded limitations to document.

---

## Should fix before S3 (non-safety, liveness)

### N1. A failed preparation release is never retried and never reconciled
**Where:** `execute` finally → `cancel_preparation` → `capacity_lock` (`LOCK_EX|LOCK_NB`)

**What goes wrong:**
- If any other process holds the capacity lock at that moment, `cancel_preparation` raises `storage-busy`. The finally block catches it and prints the pending message.
- The ledger row has no `attempt.json` and no lock holder, so `settle_locked` can never release it. Both `reconcile` and the F4 loop in `reserve` return False forever.
- Nothing calls `cancel_preparation` again, and no CLI exposes it.
- The same happens if `logical_bytes` raises its retryable mtime-changed error during the cancel.

**Why it matters:**
- The settle path heals later through F4 and `reconcile`. The cancel path does not.
- This is ordinary contention, not a crash gap, so it falls outside F5.
- With the default policy (256 MiB budget, 96 MiB overhead), there are only two slots. Two such events permanently exhaust the budget until someone does forensic reconciliation.

**How to reproduce:**
1. Process B enters `with storage.capacity_lock(policy):` and holds it.
2. Process A runs `execute` and fails in `_execute_verified` before its first `_save`. For example, make `_private(base)` fail, or patch the stage write to raise.
3. Release B.
4. `reconcile` still shows A's row retained, with `reservedBytes` ≥ 96 MiB, on every later call.

**Fix:**
- In the `execute` finally, retry `storage-busy` with a bounded wait for both `cancel_preparation` and `settle`. A holds no other lock at that point, so this cannot deadlock.
- Optionally, give `capacity_lock` a blocking-with-deadline mode.
- Add a two-process red test for this scenario.

### N2. F4 regression: `settle_locked` races with an attempt's first lock acquisition
**Where:** `settle_locked` → `task_lock(path)`, which takes an exclusive lock before checking that `attempt.json` exists.

**What goes wrong:**
- `_retention_entry` explicitly avoids locking until a record exists ("Avoid competing with that initial lock acquisition"). `settle_locked`, now called for every active row on every admission, does not.
- If B's `reserve` loop takes the exclusive lock in the gap between A's `os.open(O_CREAT)` and `flock` in `operation_lock`, A raises `attempt still has an active operation`.
- A then calls `cancel_preparation` while B still holds the capacity lock, which lands directly in N1.
- The same contention makes a concurrent user `recover` fail spuriously with "active operation".

**Probability:** The window is microseconds. It is deterministic if you pause A's `fcntl.flock` in a test.

**Fix:** In `settle_locked`, `lstat` `attempt.json` first. If it is absent or not a regular file, return False without opening `operation.lock`.

---

## Low-severity defects (fold into S3 or fix now)

- **N3. A committed settlement can be reported as unsettled.** `task_lock` calls `unchanged()` again after the yield. That check runs after `settle_locked` has already written the outcome and ledger and updated the in-memory ledger. If it raises, the `except (OSError,ValueError)` returns False. `reconcile` then leaves the identity out of `settled` while also leaving it out of `retained`. Only the report is wrong; capacity accounting is unaffected. Fix: track a `committed` flag and return True once the commit is done.
- **N4. The reservation limit is checked too early.** In `reserve`, the `len(ledger['active'])>=1000` check runs before the F4 settle loop. A ledger full of terminal-but-unsettled rows is refused instead of settled. Move the check after the loop. This only matters under F6 custom budgets.
- **N5. Some errors in `usage_locked` escape the storage error handling.**
  - `proof.get` assumes the outcome JSON is a dict. A non-dict raises AttributeError outside the handler.
  - `private(cache)` and `cache.stat()` sit outside the `try`, so they surface as exit 1 or a traceback instead of `storage-blocked` exit 4. These fail closed; only the error reporting is wrong.
  - A `review-*` entry's `st_dev` is not compared to the cache's `st_dev`. `_retention_entry` does make this check.
- **N6. Side effects of F1 on non-run paths.** `capacity_lock` now runs `mkdir(parents=True)` on the cache parent and initializes the control root and `policy.json` for any canonical path. That includes `storage-reconcile` on a mistyped path. The first such call freezes the *default* policy, which then blocks a later F6 custom initialization with `storage-policy-changed`. Fix: `reconcile` and `settle` should report empty or not-initialized when the control root is absent, and only `reserve` should initialize.
- **N7. "F7 upgrade blocked" is not enforced on these paths.**
  - `_settle_storage` and `storage-reconcile` hash the installed `reviewer_storage.py` and then check it against that same hash, so the check always passes.
  - The ledger and policy carry no storage digest.
  - So recover and reconcile run whatever storage bytes are installed against old ledgers. Either bind `storageSha256` into the policy or ledger, or state that upgrade blocking is an operator procedure.

---

## Bounded design limitations (agree: document, don't block)

- **L1. Logical bytes, not disk blocks.**
  - `logical_bytes` sums `st_size`. It does not count directories or per-file block rounding. The `minFreeBytes` margin covers this.
  - The global caps of 20,000 entries and 1,000 attempts per `usage_locked` call block admission once roughly 800–1,000 attempts are retained. That is S3 archive territory.
- **L2. Active tasks are counted by reservation only.**
  - The reservation is assumed to bound the directory's real size.
  - Repeated `recover` runs add client logs (each stdout ≤ 2 MiB) without limit, consistent with F10 (cooperative, not a hard quota).
  - Docker's own storage is outside the accounting.
- **L3. One unsettled directory outside the ledger blocks all admission.** Example: `recover` re-run on an already-settled task ends `cleanup-unconfirmed` or crashes while `recovering`. `usage_locked` then raises `unsettled-task` globally. This fails closed, but it is a global wedge.
- **L4. Crash between the outcome write and the ledger write in `cancel_preparation`.** The row is retained with no release path. This is in the F5 class.
- **L5. Path-based identity checks are TOCTOU against a same-uid actor.**
  - Affected checks: `unchanged()`, the dev/ino proof, `is_symlink()` followed by `stat()`, and the ancestor `resolve()` in `capacity_lock`.
  - Ancestor permissions are not validated.
  - Intermediate directories from `mkdir(parents=True)` get umask-default modes; only the leaf gets 0700.
- **L6. F4 cost under the global lock.** Worst case is 1,000 × (16 MiB parse plus 16 MiB re-read) with a custom budget. The default policy limits the ledger to 2 rows.
- **Signals.** SIGTERM or SIGKILL during settlement leaves the row retained, which is the expected conservative result.

---

## Fix-claim check

| Claim | Status |
|---|---|
| F1 parent creation | Correct. Side effects noted in N6. |
| F2 broad catch, static stderr message, result preserved | Correct. In a `finally` block, the original return or exception survives. Swallowing KeyboardInterrupt is deliberate. |
| F2 malformed reservation retained | Correct (`isinstance(reservation, dict)`). |
| F3 residue proof and counting, never deleted | Correct. The proof mismatch case fails closed. |
| F4 reconcile before usage | Correct for accounting. Introduces N2 and interacts with N1. |
| F8 `unchanged()` before writes | Correct. The post-commit re-check causes N3. |
| F9 cross-device rejection and measuring the existing cache | Correct (btrfs subvolumes would fail closed). |

## Test and evidence gaps (synthetic; this is not product or R3 evidence)

- The red-first evidence covers F1, F2, and F3. **F4, F8, and F9 have no failing-first tests.** Missing cases:
  - `reserve` settling a terminal-but-pending row before computing usage.
  - Cross-device cache rejection.
  - `disk_usage` targeting the cache.
- `test_proven_preparation_residue_is_retained_and_counted` never asserts the count. It would still pass if the residue counted as 0. Fix: set `budgetBytes = 96 MiB + 6` and expect `cache-budget-exceeded` with `accountedBytes == 7`.
- `test_non_value_settlement_error_keeps_original_result` does not assert:
  - the stderr message,
  - that the row is retained,
  - the `cancel_preparation` path,
  - KeyboardInterrupt handling.
- `test_three_processes_cannot_over_reserve` passes `api=None`, and the cache never exists. It proves flock serialization of ledger admission only. It exercises neither the F4 settle loop nor `usage_locked` scanning under contention; with a real `review-*` directory, `None._load_attempt` would raise AttributeError. It also cannot catch N1 or N2.
- The green results (22 storage, 87 launcher, 45 Node) are consistent with the diff. They are synthetic and say nothing about VM acceptance or R3.
