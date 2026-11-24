**Scoped verdict:** Not accepted as a fully demonstrated closed source/dependency execution set. Exact listed source hashes and locked dependency file bytes are bound, and the listed container isolation controls are supported; however the observer leaves an unchecked import surface, and dependency package metadata is not closed. No R3 or live acceptance implied.

**Findings**

1. **Safety blocker — unchecked `sourceRoot` imports.** `run_probe` hashes only `request['files']`, then inserts the entire `sourceRoot` at `sys.path[0]`. It never enumerates `sourceRoot` or rejects extra `.py` files. Approved code can import an unlisted sibling; that file bypasses `APPROVED_SOURCES`, `passive_source`, and the source-shadowing check. Because `sourceRoot` precedes dependencies on `sys.path`, such a file can also shadow locked dependencies. Closure holds only if staging is separately proven to contain exactly `request['files']`; this code does not prove it.

2. **Dependency-closure limitation.** `verifier_snapshot.tree` binds dependency file bytes by lock digest with read/fstat checks, so the file map is hash-closed. But `freeze` accepts `lock['packages']` without validation, and `verify` never checks `dependencyPackages`. Package provenance/metadata should be treated as unattested; only the file map is bound. The green tests do not close this metadata gap.

3. **Conservative proof defect.** In `exclusion_proof`, the finite-literal-set branch calls `literal_expression(v.value)`, which parses the constant’s content as source. Ordinary string sets such as `x not in ('safe','bad')`, and integer sets, are rejected; valid exclusions degrade to `unknown`. This is conservative, not an unsafe exclusion.

**Isolation conclusion:** Supported for the stated controls: non-root 1000, `--network none`, read-only rootfs, cap-drop ALL, no extra caps/privileged, `no-new-privileges`, 512 MiB memory/swap cap, 1 CPU, 64 pids, 32 MiB tmpfs, single read-only stage mount. No custom seccomp is specified; the daemon default remains a residual limitation, not evidence of a hardened syscall allowlist.
