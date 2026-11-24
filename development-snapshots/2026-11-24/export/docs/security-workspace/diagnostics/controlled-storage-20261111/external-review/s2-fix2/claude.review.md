# Review: N1/N2 positive-proof retry and reconciliation delta (`scripts/reviewer_storage.py` 2ddeb4e6…)

I read only the quoted sources and evidence. I did not see `reviewer_snapshot.py`, so any claim that depends on how `execute` or `_load_attempt` behave is marked as a verification item, not a finding.

## Verdict

- **No unconditional safety, deletion, or under-counting blocker in the delta.**
- **One conditional under-count (C1).** Close it before S3, either by citing `execute` code or with a small guard.
- **One input-validation regression (R1).** It is a one-line fix.
- **N1** is closed for the stated case, subject to C1.
- **N2** is closed for the missing-record case. A residual dependency on snapshot lock ordering remains (V1).

## C1 (conditional under-count): the proof is not fenced against reuse of the identity

**Where:** `cancel_preparation` writes the `known-preparation-failure` proof before taking the capacity lock. Meanwhile, the idempotent branch of `reserve` (`if identity in ledger['active']: return row`) does not check `outcomes/{id}.json`.

**How to reproduce:**
1. Controller A reserves `X`. Preparation fails before `review-X` is created.
2. `cancel_preparation` writes a proof with `sourceIdentity: null`, then gets `storage-busy` (retryable=True).
3. A caller treats the retryable error as "retry execute" and runs `execute` again with the same deterministic identity `X`. `reserve` returns the still-active row.
4. A reconcile, or any other `reserve` (through the new settle loop), runs `settle_locked(X)` before the retry runs `mkdir review-X`. `attempt.json` is absent, the proof matches, and both `source` and `None` are `None`, so the reservation is released.
5. The retry now creates the directory and runs without a reservation. A third `reserve` in the window between the release and the `mkdir` sees nothing for `X` in `usage_locked` and admits.

Once `review-X` exists unsettled, `usage_locked` fails closed, because the `sourceIdentity` mismatch falls through to `task_lock`. That bounds the overrun to one admission in a short window, but it is still over budget. The proof also stays as `known-preparation-failure` for an attempt that actually ran.

**Applies only if** identities can repeat across `execute` calls, or the CLI or launcher re-runs analysis on a retryable cancel error. The test name `…without_retrying_analysis` suggests the intent is not to retry, but the storage layer does not enforce that.

**Fix (either):**
- In `reserve`'s active-identity branch, raise `reservation-already-settled` (or a new `reservation-cancelled`) when an outcome file exists.
- Or show from `reviewer_snapshot.py` that identities are fresh per `execute` and never reused after cancel.

Add a red test: reserve → busy cancel → `reserve(same id)` must refuse.

## R1 (regression): `cancel_preparation` writes before validating its inputs

Previously, the outcome write ran only after `ledger['active'].get(identity)` matched a validated `ID` key. Now `cancel_preparation` writes `outcomes/{identity}.json` with no `ID.fullmatch` and no `validate_policy`.

**Reproduction:** `identity='../ledger'` makes `atomic` replace `controlRoot/ledger.json` with the proof object. All active reservations are lost, and `state_locked` then raises "invalid reservation ledger" on every call. That fails closed, but if an operator "repairs" it by deleting the ledger, every in-flight reservation is under-counted. `'../policy'` similarly wedges the store with `storage-policy-changed`.

**Severity:** low if the only caller passes a `reserve()` row id, but it is a regression with a trivial fix. At the top of `cancel_preparation`, add:
- `validate_policy(policy)`
- `ID.fullmatch(identity)`
- `private(controlRoot/'outcomes')`

## V1 (verify, outside this file): N2 depends on lock ordering in the snapshot

The missing-record branch of `settle_locked` correctly avoids `task_lock`, and the red/green test pins that. However, the delta also adds `for previous in ledger['active']: settle_locked(...)` to `reserve`. As a result, every `reserve` now takes a non-blocking exclusive `task_lock` on every active attempt that has an `attempt.json`.

This is safe only if the snapshot controller does both of the following:
- creates and holds `operation.lock` before publishing `attempt.json`;
- holds it continuously until settlement, or tolerates `task-busy` on any later re-acquire.

If the controller drops and re-takes the lock between phases, a concurrent `reserve` or `reconcile` can make that re-acquire fail spuriously. Please confirm against the execute and recover code paths.

## Bounded design limitations (document; not blockers)

- **L1 (writer quiescence).** The proof binds only `(st_dev, st_ino)` of the directory. If anything can still write into `review-X` after `cancel_preparation` returns (for example a detached copy subprocess), reconcile releases the 96 MiB overhead while contents can still grow. `usage_locked` counts the actual bytes at each later `reserve`, but growth between admissions is unreserved. State the precondition that all preparation writers are joined before cancel.
- **L2 (inode reuse).** `(dev, ino)` is vulnerable to ABA if a directory is ever removed and recreated. That is not possible today, since this module never deletes. If S3 adds recycle or removal, bind the proof to something non-reusable (a nonce file or birth time) in addition to the inode.
- **L3 (fail-closed liveness on malformed state).** `usage_locked` calls `proof.get(...)` on a non-dict proof, and `settled_job(job)` runs on a non-dict job. `_load_attempt` can also raise non-`OSError`/`ValueError` errors, as does `api=None` once an `attempt.json` exists. All of these propagate out of `reserve` and `reconcile` as raw exceptions. That is safe, but one malformed record wedges admission, and the CLI may print a traceback instead of exiting with code 4 and a reason. This fits into the N3–N7 reporting work.

## Confirmed correct in the delta

- **Crash recovery after the proof is durable:** if the process crashes after the proof `atomic` (file and directory fsync) but before the ledger delete, the reservation stays retained. Then `reconcile` or the `reserve` loop releases it only if `attempt.json` is absent, it is not a symlink, `container.cid` is absent, and the directory identity matches.
- **No proof, no release:** a missing, mismatched, or `settled` proof, or a `logical_bytes` failure, returns `False`. Unknown reservations are still never age-expired (`test_unknown_reservation_is_not_expired_by_age`).
- **Residue is kept and counted:** proven-preparation residue is never deleted and is counted by `usage_locked`'s proof branch. A dangling or linked entry trips `logical_bytes`, which fails closed.
- **Pre-settlement recheck:** the `unchanged()` recheck before the settled-outcome write in `settle_locked` is an improvement. A malformed `storageReservation` now stays pending.

## Test notes (synthetic coverage only; not product or R3 evidence)

- `test_busy_preparation_release…` should assert `code == 'storage-busy'`. It currently accepts any `StorageError`.
- `test_proven_preparation_residue…` asserts the residue still exists but not that it was counted. Add a tight-budget case where the residue bytes push the next `reserve` over budget.
- Missing cases:
  - proof with `null` source, then the directory appears → retained;
  - proof present, then `attempt.json` appears → task path;
  - proof whose `id` mismatches;
  - C1's same-identity re-reserve;
  - R1's traversal identity.

## Before S3

1. Fix R1.
2. Either guard C1 in `reserve` or cite the `execute` code that rules it out.
3. Confirm V1 against `reviewer_snapshot.py`.
4. Document L1 and L2 as preconditions.

This review covers only the stated delta for the VM offline candidate. It is not a complete product review and not R3 acceptance.
