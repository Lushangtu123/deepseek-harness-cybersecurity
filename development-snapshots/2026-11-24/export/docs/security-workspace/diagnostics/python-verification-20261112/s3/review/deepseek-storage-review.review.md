Read-only review; no execution. I found one confirmed safety blocker in the verifier closure plus test-evidence inconsistency. No R3/live-acceptance claim.

**Safety blocker — verifier bytes are double-read after hashing**
`verifier_snapshot.tree()` does:

```python
raw = p.read_bytes()
actual[name] = sha256(raw).hexdigest()
...
return {n: (root / n).read_bytes() for n in actual}
```

`reviewer_snapshot.execute()` then passes those returned bytes to `_execute_verified()`, which writes them into `stage/` and executes them in the VM. A writer to the verifier bundle can swap a file after the hash check; `tree()` still matches `lock`/`value['code']`, but the VM receives and executes the replacement bytes. This defeats “only verified bytes” for code and dependencies. It even reaches `python_execution_verify.py`: `verifier_snapshot.verify()` compares `value['code']['python_execution_verify.py']` to the shipped worker hash, not to the returned bytes.

The same function also has a symlink race: it checks `p.is_symlink()`, then uses `p.stat()`/`p.read_bytes()` with follow semantics. A swapped symlink can escape `dependencies/`. Fix by reading each file once under `O_NOFOLLOW`, `fstat`, hashing and returning that same buffer, and requiring a private/owned verifier bundle or a final re-verification immediately before staging.

**Test/integration regression, not the product API**
`controller-red.txt` reports `module 'snapshot' has no attribute 'verify_execution'`, but the supplied `reviewer_snapshot.py` defines `verify_execution()`. The failure is in the old controller test’s dynamic import/`self.api` binding, not evidence that the API is absent. Likewise `gate-red.txt` and `gate-green.txt` contradict each other at the supplied SHA: red shows v4 tests failing; green shows 54 passing. These logs cannot be used as acceptance evidence.

**Conservative limitations, not confirmed bypasses**
- v4 main-loop evidence check requires `output.evidence.every(e => e.kind === 'sandbox-verification' ...)`. A confirmed/excluded output carrying both sandbox and `human-review` evidence is forced to `unknown`. Human evidence is therefore not merely supplementary; it cannot coexist with a main-score sandbox artifact.
- v3 negatives with `pointId: null` get no verification-plan request. A raw hit on such a case cannot obtain `actualVerification`, so any `excluded` decision becomes `unknown`. This is safe but limits negative-hit exclusion.
- `freezeLocations`/`rowBound` require a negative file to contain zero execution points; an unrelated `eval`/`exec` in that file blocks freezing.
- Static snapshot and dependency lock remain content-bound/self-attested rather than independently sealed; `_settle_storage()` can print pending and leave reservations while cleanup is confirmed. These are trust/operational limitations, not demonstrated score bypasses.

**Conclusion**
The `verifier_snapshot.tree()` double-read is a concrete scoped safety blocker in the S3 verifier path. The red/green evidence is internally inconsistent and should be reconciled before any acceptance claim. Other findings above are conservative scope limitations, not safety blockers.
