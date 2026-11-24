No R3/live acceptance claimed. Within the supplied excerpts I find one code-backed validation defect and one conditional fail-closed reconciliation gap; the rest of the remaining issues are same-UID/cooperative limitations, not new cross-user safety blockers.

**1. Confirmed: `validate_plan` parses `generatedAt` before type-checking it**
- In `validate_plan`:
  `generated=datetime.fromisoformat(plan['generatedAt'])`
  occurs before the later
  `not isinstance(plan['generatedAt'],str)` check.
- A plan with `generatedAt=None` (or any non-string, non-`ValueError`-compatible value) raises `TypeError`, not `ValueError`. The red archive test `test_ancillary_plan_shapes_are_validated_before_action` is code-backed here.
- Impact is fail-closed: no archive is applied, but the validation contract is wrong and A2/A3 “strict ancillary types” is not fully confirmed for non-string `generatedAt`. The green archive run cannot cover this exact line as shown.
- Fix: check `isinstance(plan.get('generatedAt'),str)` before `fromisoformat`; keep the aware-timestamp and `expiresAt` type checks before timestamp arithmetic. Catch `TypeError`/`ValueError` uniformly at the validation boundary.

**2. Scoped fail-closed gap in reconciliation (conditional on B4 scope)**
- `cleanup_inventory` catches `OSError`/`ValueError` only around `load_transaction`, and reports those as `transactionUnknown`. That fixes the missing/corrupt `transaction.json` case.
- But before that try block it does:
  `if not ID.fullmatch(path.name): raise ValueError('unknown transaction directory')`
  so a transaction directory with a noncanonical name aborts the whole reconciliation rather than being retained in `transactionUnknown`.
- If B4 is intended to cover any corrupt/noncanonical transaction directory, this remains a scoped availability defect. It is fail-closed, not a safety bypass. If B4 covers only valid-ID directories with missing/corrupt `transaction.json`, the shown handling is sufficient.

**Conditional same-UID limitations — not counted as general blockers**
These are real but require same-UID mutation or a broken cooperative process model:
- `capacity_lock` validates the lock file on open but does not revalidate its inode after acquisition. A same-UID process can unlink/recreate `capacity.lock` and break mutual exclusion.
- `private` does post-`mkdir` `lstat`/`resolve` checks, which closes the deterministic symlink insertion test, but does not bind the checked inode across a same-UID swap after `lstat` or between `resolve` and later use.
- In archive apply/restore, `task_lock`’s final `unchanged()` check occurs after rename and after the transaction state is saved. A same-UID swap in that window can leave a committed/restored record while the wrong object was moved. This is the stated arbitrary-same-UID limitation, not a new guardrail failure.

**Cooperative budget limitation**
- `archive_restore` checks cache budget with `used + row['manifest']['bytes']`, while the filesystem-free check adds `len(row['manifest']['files'])*4096`. So restore can exceed `budgetBytes` by per-member directory overhead unless `usage_locked` already accounts for it. It remains guarded by `minFreeBytes`, so this is cooperative accounting, not a safety blocker. Archive apply’s free-space estimate does include the per-member 4096.

**Evidence note**
- The three red storage failures do not match the shown source paths: the ledger exact `inputBytes+overhead` check, post-settlement re-read, and post-`mkdir` `lstat` rejection are present. I would not count those red storage failures against this source without a matching execution.
- The red archive ancillary failure does match the shown `generatedAt` ordering. The green archive `OK` is not sufficient evidence for that specific non-string case.

No other scoped safety blocker is confirmed from the supplied excerpts. B3 remains process-crash, not physical-power-loss certification; B5/B6/B7 remain intentional fail-closed behavior.
