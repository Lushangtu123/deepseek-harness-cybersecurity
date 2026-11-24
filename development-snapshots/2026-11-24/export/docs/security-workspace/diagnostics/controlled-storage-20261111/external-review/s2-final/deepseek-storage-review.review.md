Scoped result: C1 and R1 are present and the supplied red2→green evidence matches the claims. I see no safety blocker in these two guards under the stated launcher assumptions. I do see one low-severity hardening inconsistency and one conservative concurrency limitation.

C1 — verified
- `reserve()` validates policy/identity/input size, enters `capacity_lock`, loads `state_locked`, and checks the outcome file before the active-idempotent branch. The busy-lock regression now leaves proof and the next same-ID reserve raises `reservation-already-settled`.
- This satisfies the stated C1 guard in the normal serialized launcher path.

R1 — verified for validation order
- `cancel_preparation()` does `validate_policy` → strict `ID.fullmatch` → `private(controlRoot/outcomes)` before constructing the ID-derived `review-<id>` path. The traversal test’s ledger-preservation assertion is consistent with the green run.
- No ID-derived write occurs before policy/ID validation.

Launcher ordering — matches cited V1
- `execute()` generates `uuid.uuid4().hex` each call.
- `_execute_verified()` creates staging synchronously, then enters `operation_lock(attempt)` before the first `_save(attempt, job)`, and holds that lock through the final commit `_save`.
- `_recover_core()` wraps `_recover_locked` in `operation_lock(root)`.
- No subprocess/engine work starts before `phase['enginePossible']=True`; the shown staging path has no detached writer.

Residual scoped issue — low-severity hardening, not a safety blocker
- `cancel_preparation()` checks `attempt.json` and `container.cid` with `.exists()` only. A dangling symlink is treated as absent, while `settle_locked()` explicitly rejects `is_symlink()`. If `logical_bytes()` does not itself reject that residue, `cancel_preparation` could write the known-preparation-failure proof and drop the active row for an unconfirmed marker. To be consistent with `settle_locked`, the guard should treat `exists()` or `is_symlink()` as unconfirmed for both markers, and probably `path.is_symlink()` too. Normal launcher operation should not create dangling symlinks, so this is hardening, not a blocker.

Conservative concurrency limitation — not a blocker under stated assumptions
- `reserve()` checks the outcome before active-idempotent return, but `cancel_preparation()` intentionally publishes proof before taking `capacity_lock`. A cross-process same-ID reserve could therefore miss a proof written mid-call. With fresh UUIDs, synchronous staging, and no detached preparation writers, this is not reachable in the cited launcher flow. If you ever intend C1 to be linearizable across processes for the same ID, proof publication would need coordination; otherwise this remains a limitation.

The red run shows exactly the two expected regressions; the green run shows 26/26 storage tests OK. I do not claim R3, live acceptance, archive assessment, or that the tracked low-severity notes are fixed.
