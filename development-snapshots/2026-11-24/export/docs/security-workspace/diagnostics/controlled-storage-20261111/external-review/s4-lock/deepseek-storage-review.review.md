No concrete scoped safety blocker or regression found in the supplied change.

Verified points:

- `ReviewTaskBusy(ValueError)` preserves the old `ValueError` behavior while adding the required static interface: `code='task-busy'`, `retryable=True`, and instance `details={'directory': str(root)}`.
- `operation_lock` still uses the same `fcntl.LOCK_EX | fcntl.LOCK_NB` call and still closes the descriptor in `finally`. The only behavior change is converting `BlockingIOError` into `ReviewTaskBusy(root) from None`.
- The existing generic CLI handler catches the new exception because it is a `ValueError` with a string `code`, emits JSON with `reason='task-busy'`, `retryable=true`, `details.directory`, and exits `4`.
- The regression evidence is coherent: `lock-red.txt` shows the old path exiting `1`; `archive-green.txt` shows the new busy-lock CLI test passing; archive, storage, Python, and gate suites are green.
- The busy case does not enter recovery or storage settlement, so it does not create a new action path.

Conservative limitations, not scoped defects:

- This is not final-byte VM acceptance. The earlier 196-test/native run predates this launcher change, so it cannot be cited as final acceptance.
- The new test asserts exit `4`, `reason='task-busy'`, and `retryable=true`, but not `details.directory` or the preserved human message. Source inspection shows both are retained; this is test-coverage conservatism, not a demonstrated bug.
- The reused generic JSON label `state='storage-blocked'` is semantically broad for a lock-busy condition, but `reason='task-busy'` and `retryable=true` distinguish it. Under the stated interface contract, that is not a blocker.

R3 remains false; no daily deployment or push indicated. Final isolatedVM rerun is still required before any final-byte acceptance claim.
