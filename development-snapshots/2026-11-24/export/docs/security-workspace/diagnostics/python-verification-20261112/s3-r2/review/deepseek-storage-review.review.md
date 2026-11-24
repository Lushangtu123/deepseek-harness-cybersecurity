**Confirmed evidence blocker (not a runtime read-once defect):**  
`test_returned_dependency_bytes_are_the_same_bytes_that_were_hashed` patches `Path.read_bytes`, but current `tree()` never calls it. The implementation uses `os.open`/`os.stat`/`os.dup`/`os.fdopen(...).read`. Therefore the injected “second read returns different bytes” race is dead code, `reads` remains empty, and the test passes without exercising the modified read path. It cannot detect a reintroduced double-read via `os.read`/`fdopen`. This is a concrete regression-evidence blocker; the test should inject/patch the actual fd read seam or assert the number of underlying reads.

**Runtime read path:** I found no confirmed double-read blocker in `tree()`. It opens with `O_NOFOLLOW|O_NONBLOCK`, `fstat`s before, reads one logical buffer from a duplicated fd, `fstat`s after, hashes that buffer, and returns the same `raw` object without rereading. Buffered `.read(n)` may do multiple underlying reads, but the before/after `dev/ino/size/mtime/ctime` comparison is the guard; that is a conservative implementation, not a confirmed bypass.

**Worker raw fields:** `returned` now emits `returnValue` and `markerValue`, but `verification_report()` still sets `confirmed` from `evalWitness`/`execWitness` only. In the supplied file there is no validation that the raw values equal the challenge. If Node independently enforces that check, this is an external evidence dependency; if not, the worker’s `confirmed` decision is still flag-based and not independently raw-checked. This is a scoped evidence gap/limitation unless Node enforcement is present outside this material.

**Conservative limitations, not blockers:** raw values are omitted for non-`str`/over-128 returns and after 16 captured returns; trace output remains bounded. These can force `unknown`, not false confirmation.

No R3 or live-acceptance claim.
