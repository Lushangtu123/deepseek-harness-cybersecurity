# Contracts revision 8 — final stage recheck and test isolation

`protocolRevision` remains **3**, the resource-context version remains **3**,
and the command surface remains exactly `preflight`, `status` and `recover`.

This revision closes the success-path gap reported as
`cached-absence-not-rechecked-at-success` and the missing-stage `KeyError`.
It does not change the formal experiment protocol, target syntax, fixed inputs
or the formal runner/judge lifecycle.

## 1. The plan lstat only schedules work

`_recovery_plan` still composes the stage path from the fixed root, the
original preflight ID and the claim-bound tag, and it still performs one
per-component `lstat` walk.  That early observation is used only to decide
whether a stage cleanup operation may be scheduled and to validate the
ownership graph.  It is **not** a success proof.

After the container, client and observer actions have completed, `recover`
takes a new explicit path query with `_final_stage_recheck`.  The query walks
the fixed root through `preflight/evidence/<preflightId>/stage-<tag>` one
component at a time using `os.lstat` only.  It rejects an intermediate symlink,
a non-directory intermediate component and a lexical escape.  The final
component is also required to be a directory before any deletion is attempted.

The recorded `stage.lstatAfter` and `stage.removed` values come from this new
query (and, after a deletion, from one more new query).  No branch constructs
`lstatAfter="absent"` from an earlier observation.

Outcomes for the new query:

| Final query result | State | Exit |
|---|---|---|
| `absent`, all other resources confirmed clear | `resources-cleared`, `removed=true`, `lstatAfter=absent` | 0 |
| `absent`, another resource unresolved | `incomplete` | 3 |
| a real directory, plan originally saw `absent` | directory retained, `state=appeared-after-plan`, `lstatAfter=present` | 3 |
| `unknown` (`PermissionError`, `NotADirectoryError`, other `OSError`) | `lstat-error`, `lstatAfter=unknown` | 3 |
| `symlink`, escape, final non-directory or identity mismatch | `blocked` | 78 |
| still present after a deletion attempt | `still-present`, `lstatAfter=present` | 3 |

`NotADirectoryError` is never mapped to `absent`.  It is a read failure when
raised by `lstat`; an observed non-directory component is a path contradiction
and is blocked.  A success return additionally requires every other resource
to be confirmed exited/removed, `stage.removed is True`, the final actual
`lstatAfter` to be `absent`, and the recovery journal to be persisted.

## 2. Missing stage and tri-state cleanup

`_cleanup_stage` and `_recover_stage` handle `absent`, `present` and `unknown`
explicitly.  A stage with a valid identity that is already absent returns
`removed=true`, `state=absent`, `lstatAfter=absent`; it no longer reads a
missing `symlink` key.  A read error stays `unknown` and is retained.  A stage
that is absent can be cleaned only after the other resources are confirmed
clear.  Repeated cleanup and recovery never replay the self-check and never
rewrite an old receipt or claim.

## 3. Test isolation

Pure unit tests replace container lookups, tag lookups, signals and deletion
entry points explicitly and count the calls.  In particular
`removed-true-but-final-lstat-present-is-not-confirmed` stubs both container
queries, requires the deletion recorder to be called exactly once, requires the
final stage lstat to execute at least twice, and forbids any real Docker call.
A permission failure on the host is no longer accepted as isolation.

Simulated integration suites call `regression_lib.verify_shims` before every
subprocess environment.  Both `docker` and `bpftrace` must resolve to the
controlled files under `checks/shims`; a missing or different executable is a
hard failure and there is no fallback to a real program.  Each suite records
the resolved paths and their SHA-256 digests.

The repeated-recovery check parses both recovery JSON files field by field and
requires all of the following simultaneously: exit 0 for both calls, both
states `resources-cleared`, both `cleanupConfirmed=true`, both
`selfCheckReplayed=false`, both `realMachinePass=false`, stage `removed=true`
and `lstatAfter=absent` in both records, zero new create/start calls, and
unchanged original receipt and claim bytes.  It no longer uses an `and`/`or`
expression that can pass vacuously.

## 4. Unchanged boundaries

The fixed image/runtime, observer profile, four fixtures, sixteen-attempt plan,
formal target count (0/16), R3 state (`blocked`) and the claim/receipt binding
are unchanged.  The conditional gaps recorded by the previous review
(container-name binding in the independent verifier and cleanup-plan field
consumption) remain recorded; this revision does not add a compatibility loop.
Formal runner lifecycle and formal judge recompute paths are out of scope.

The zero-target preflight is still not executed by this author.  A single
Codex-run fixed-tool self-check may follow only after source review and
external review; no license or admission is issued here.
