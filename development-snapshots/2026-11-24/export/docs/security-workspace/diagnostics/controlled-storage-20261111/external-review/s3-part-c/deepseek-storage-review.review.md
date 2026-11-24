**Scope:** Supplied part C capacity/launcher functions plus shared storage helpers. No tools/MCP/hooks used. This is not R3 or live acceptance.

## Verdict
The reservation-before-task ordering, capacity mutex, private-directory checks, and budget/disk admission are generally sound. I found one persisted-state validation blocker, one security condition requiring an untrusted writable parent, one recovery-accounting bug, and several conservative limitations.

## Concrete defects

### 1. Persisted ledger does not enforce the reservation invariant — condition/correctness blocker
`state_locked()` validates only that `row['bytes']` is an int and `>= RESERVATION_OVERHEAD_BYTES`. It never requires:

```python
row['bytes'] == row['inputBytes'] + RESERVATION_OVERHEAD_BYTES
```

and it does not validate `inputBytes` as a non-negative int. `reserve()` then treats an existing row as idempotent if only `inputBytes` matches:

```python
if identity in ledger['active']:
    row=ledger['active'][identity]
    if row.get('inputBytes')!=input_bytes: raise ...
    return row
```

**Reproduction:** create an active ledger row with `inputBytes=100*1024*1024` and `bytes=96*1024*1024` (still passes `bytes >= overhead`), then call `reserve(policy, id, 100*1024*1024, api)`. The existing row is returned, so only 96 MiB is accounted instead of 196 MiB. This violates the conservative budget invariant. It also means a changed `RESERVATION_OVERHEAD_BYTES` is not detected by `policySha256`, because the overhead is not part of the policy digest.

**Classification:** blocker only if the ledger can be corrupted, restored from an older version, or tampered by the same UID. Under the stated same-UID cooperative model it is a bounded limitation, but it is a concrete validator gap and should be fixed by requiring the exact row invariant.

### 2. `private(create=True)` has a symlink TOCTOU — security condition, not confirmed on default layout
`private()` checks `path.resolve()!=path` **before** `mkdir(exist_ok=True)`, then uses `path.stat()` after creation:

```python
if path.resolve()!=path: raise ...
if create: path.mkdir(mode=0o700, exist_ok=True)
value=path.stat()
```

If an attacker can write the parent directory and wins the race between the resolve check and `mkdir`, `mkdir(exist_ok=True)` can accept a symlink to an existing current-UID `0700` directory. `path.stat()` then follows the link and the private check passes, so `state_locked()` may create `policy.json`, `ledger.json`, and subdirectories inside the target.

**Reproduction condition:** world-writable cache parent, e.g. a user-selected attempts root under `/tmp`; race creation of the deterministic `.harness-storage-*` symlink to a current-UID `0700` directory such as `~/.ssh`. This is not confirmed for the default `~/.cache/...` parent, which is not normally writable by other users. It is still a real TOCTOU in a claimed private-directory boundary. A post-`mkdir` `lstat`/resolve recheck or `openat`-style no-follow creation would close it.

### 3. Post-rename ledger fsync failure can resurrect a settled reservation — recovery bug
`settle_locked()` writes the outcome, then:

```python
atomic(ledger_path, updated)
ledger.clear(); ledger.update(updated)
```

If `atomic()` replaces the ledger file but the subsequent parent-directory `fsync` raises `OSError`, `settle_locked()` catches the error and returns `False` without updating the caller’s in-memory `ledger`. `reserve()` can then later write that stale in-memory ledger back while creating another reservation, resurrecting the already-settled active row.

**Reproduction:** patch `os.fsync` to raise only on the ledger parent-directory fsync after `temporary.replace(path)`; call `reserve()` for a new identity while a settled active attempt exists and the budget allows admission. The old identity can reappear in `ledger.json`.

**Impact:** conservative over-reservation and possible budget blocking; it usually self-heals on the next `reconcile()`. Not a direct confidentiality/integrity breach, but it violates the “settled reservation is not retained” accounting invariant. `atomic()` should distinguish “replace committed, fsync failed” or callers should re-read the ledger under the capacity lock.

## Conservative limitations
- **Known preparation proof can stick after residue removal.** `cancel_preparation()` writes `sourceIdentity=[st_dev, st_ino]` before taking the capacity lock. If the lock is busy, the proof remains. If the partial residue directory is later removed before `reconcile()`, `settle_locked()` sees `path.exists()==False` and computes `source=None`, which does not match the recorded identity, so the reservation is retained indefinitely. This is availability-conservative, not unsafe. Reproduction: reserve, create a partial residue directory, hold `capacity_lock`, call `cancel_preparation()` (writes proof then raises busy), remove the residue, release the lock, call `reconcile()` — bytes remain reserved.
- **Proof-residue accounting is not task-locked/private-checked.** `usage_locked()`’s known-preparation branch calls `entry.stat()` and `logical_bytes()` without `task_lock()` or `private(entry)`. `logical_bytes()` counts regular files by size/nlink only, not owner/mtime. This falls under the stated same-UID cooperative mutation limitation; it is not a hard quota.
- **Silent settlement-pending state.** `_settle_storage()` and the `execute()` finally block print a warning on exceptions, but not when `storage.settle()` returns `False`. A retained reservation can therefore be silent, requiring the operator to run `storage-reconcile` without an explicit CLI warning.

## False positives / out of scope
- The `limits-red.txt` failures are archive-domain tests (`verify_archive`/`load_transaction`), not functions supplied in this part C excerpt. `archive-green.txt` reports 23/23 passing, so I do not treat those red lines as a current part C blocker.
- `cancel_preparation()` identity traversal is not a finding: `ID.fullmatch` rejects it before path use, and the ledger directory is fixed by `state_locked()`.
- `task_lock()`’s `unchanged()` check compares only device/inode and ignores nlink after open; that is within the same-UID mutation limitation, not a new boundary.
- Stage-relative key confinement in `_execute_verified()` depends on `verify()`/`inputs()` from part A; I did not independently verify that boundary in this partition.
