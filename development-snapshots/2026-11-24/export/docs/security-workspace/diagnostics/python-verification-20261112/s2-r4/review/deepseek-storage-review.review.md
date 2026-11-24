No confirmed safety blocker in the tiny-fix scope.

- `work.mkdir(mode=0o700, exist_ok=True)` fixes the reported availability failure. Fixed `/tmp/probe-N` reuse is acceptable only under the stated fresh disposable-container assumptions; it is not hardened against a hostile shared `/tmp`.
- The real `run_probe` test does fail closed: unapproved bytes return `source-profile-not-reviewed` before `sys.path.insert`, monitoring setup, compile, or project exec. The code order matches the claim.
- `APPROVED_SOURCES` and `passive_source` gates precede path injection and import. Dependency-shadowing check is also before the gate release.

Conservative limitations, not blockers:
1. The new test proves no execution of unapproved source, but does not assert `sys.path` is unchanged. “Injection after gate” is therefore code-inspected, not test-enforced.
2. `exist_ok=True` with predictable `/tmp/probe-N` trusts the disposable container; `mkdtemp`/no-follow would be stronger if `/tmp` is assumed hostile.
3. `run_probe` checks only manifest `files`; extra importable files under `sourceRoot` are outside the source-profile gate and rely on the trusted readonly snapshot closure.

The prior profile-gate and exact-probe AST/type binding remain coherent. Controller root binding and fresh-container creation are not verifiable from this file and remain S3 scope. Close the S2 availability/test issue; this is not an R3 or live-acceptance claim.
