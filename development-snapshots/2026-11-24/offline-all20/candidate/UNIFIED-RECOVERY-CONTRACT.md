# Unified Recovery Scope Contract (B8/B9/B10/D1), protocolRevision 3

Status: **offline source candidate, pending independent Codex check and host
review**. This is not a runtime receipt, admission, preflight result or formal
batch result. Real resources remain **0**; formal targets remain **0/16**; R3
remains **blocked**. No reviewer, selfcheck, target, fixture, container,
BPF/bpftrace program, license or admission is executed in this phase.

Baseline is the exact 79-file candidate
`a9879a41aa8f755351e5d80033cf413ccc0785ff44cac86d82557a4d73a3980a`
with the source runner
`2a1f936c38304e77ddb55895a41e1a0ec0f059f44c5ad9f4b454fc631400e04e`.
The only changed product tool is `tools/experiment_runner.py`. Judge, parser,
observer render/collector, preflight, launcher, compiler, templates, fixtures
and `experiment-plan.json` bytes remain protected and byte-identical to the
baseline.

This contract unifies the recovery scope previously split across B5-B7. The
public commands, receipt schema and `protocolRevision` remain **3**. A direct
`recover/cleanup --prepare-id`, a parent `recover/cleanup --attempt` and the
internal original-task cleanup all use the same association-scope and
historical/current-state path:

* `scan_association_candidates` proves directory enumeration and reconciles the
  parent list, intents, reverse child links and standalone plans;
* `assess_associations` classifies complete/unknown/contradictory scope before
  any signal or delete;
* `resolve_prepare_parent` binds a direct child to an actually recorded parent;
* `_hold_plan`, `hold_attempt_scope` and `hold_association_candidates` durably
  invalidate only the exact current success that the selected scope covers.

## Historical state versus current state

| Layer | Fields | Rule |
| --- | --- | --- |
| Historical resource creation | `resourceProof` (`resource-phase-v1`), its `sequence`/`notCreated`, `targetExecutions`, creation timestamps | Preserved byte-for-byte during recovery. Never moved backward, never rewritten to prove current absence. |
| Historical completion receipts | `cleanupReceipts` entries with `state` `confirmed` or `incomplete` | Append-only and bounded. A later incomplete check never erases an earlier completion. |
| Current cleanup check | `cleanupCheck = {protocol: "cleanup-check-v1", state: "checking" | "incomplete" | "confirmed", startedAt, startedCount, finishedAt, reason}` | Written and read back before the resources it covers are queried. |
| Current cleanup result | `cleanup = {confirmed, state, ...evidence...}` | Describes only the latest check. A stale confirmed value is never reported after a failed discovery or hold. |
| Current reservation | `reservationHeld`, `settled` (attempts), `reservationHeld` (plans) | A held parent/child has `reservationHeld=true`; an attempt in doubt has `settled=false`. |
| Permanent budget | attempt counter `used` | Never refunded and never replayed. |

A recovery never upgrades an old record merely because a newer field is absent,
and never replaces a damaged/missing original with invented metadata merely to
mark it held. The unmodified original bytes are retained and the result is an
explicit unconfirmed diagnostic.

## B8 - enumeration must complete

`Path.glob` is not used for association discovery. The runner explicitly
enumerates the exact `prepare/plans` directory with `os.scandir` and proves that
iteration reached `StopIteration` without error.

| Condition | Result | State | Resource operations |
| --- | --- | --- | --- |
| Directory missing (`lstat` `ENOENT`) | known absent | parent still needs the original not-created proof and no durable associated reference; absence alone is not success | none |
| Directory fully enumerated, no entries | known empty | same not-created/no-reference rule | none |
| `PermissionError` or other `OSError` during open/iteration | incomplete **3** | parent held, known readable children held, explicit unknown diagnostic | none |
| Partial iteration after some entries | incomplete **3** | entries already read are reconciled and their readable children are held | none |
| Path is a symlink | contradiction **78** | no signal/delete | none |
| Path is a non-directory | contradiction **78** | no signal/delete | none |
| Directory `st_uid` differs from the runner uid | contradiction **78** | no signal/delete | none |
| Directory device/inode or entry set changes between discovery and deletion | contradiction **78** (or **3** if re-enumeration becomes unknown) | no destructive call after the change is observed | none |

A partially read or unreadable list is never treated as empty. The recorded
parent list and intents are still checked, so a child reference that is missing
or unreadable remains an explicit `associationIncomplete` /
`associationUnreadable` fact rather than disappearing.

## B9 - direct child cleanup binds the exact parent first

A direct `recover/cleanup --prepare-id <bind-or-compile>` resolves its parent
only from the current durable `parentAttempt`, the parent `associatedPrepareIds`,
`associationIntents`, and reverse `parentAttempt` plans. It never guesses a
parent, never substitutes another readable child and never auto-links a
contradiction.

1. A valid standalone preparation with no durable parent remains independently
   recoverable and creates no parent record.
2. When exactly one parent is bound, the runner durably writes the parent's
   `reservationHeld=true`, `settled=false` and an incomplete current cleanup
   with reason `parent-full-recheck-required` **before** the child plan's
   cleanup check and before any child resource query.
3. A successful child-only cleanup may return **0** for that child. The parent
   stays held with reason `parent-full-recheck-required`; it is not marked
   cleared, and no parent container/process/stage is cleaned merely because the
   child was selected.
4. A later complete `recover --attempt <parent>` re-reconciles every child and
   the target scope. It may settle the parent only after that complete check
   proves its entire scope clear.
5. A child whose parent link is one-sided (`parentAttempt` without a matching
   parent list/intent, or vice versa), whose parent attempt journal is
   missing/malformed/unreadable, or which is claimed by multiple parents is
   incomplete **3** or contradiction **78** before child resource handling. The
   selected child and any readable claiming parent are held.
6. Failure to persist the required parent hold is incomplete **3** with no
   child resource operation and no success claim. A failure of the child's own
   final journal is incomplete **3** and cannot report success.

## B10 - known children survive an unavailable main plan

Before a parent recovery reads its target plan, it reconciles and durably holds
every readable known child. This includes children named by the parent list,
completed/pending intents, reverse `parentAttempt`, and standalone
`compile-NNNN-*` plans for the attempt. The parent plan may then be:

* missing;
* malformed JSON;
* top-level non-object/type-damaged;
* non-UTF-8/Unicode-damaged;
* `PermissionError`-unreadable;
* other IO-unreadable.

In every case the result is incomplete **3**, the parent remains held and
unsettled, every readable known child has `reservationHeld=true` and a current
`cleanup.confirmed=false`, historical `resourceProof`/`cleanupReceipts` are
preserved, inaccessible child files are retained untouched with explicit
unknown diagnostics, and no signal/delete/stage operation runs. Ownership
contradictions are **78** before any such call. If any necessary hold cannot be
confirmed, the result is incomplete **3** with no destructive call.

A recovered parent is not allowed to settle merely because its target plan is
absent from the disk scan; empty lists are not used as an association or
absence inference.

## D1 - recovering reads are classified, not leaked

| Read/condition | Result |
| --- | --- |
| Selected preparation missing | incomplete **3** |
| Selected preparation malformed JSON / wrong top-level type | incomplete **3** |
| Selected preparation non-UTF-8 / `UnicodeDecodeError` | incomplete **3** |
| Selected preparation `PermissionError` or other IO | incomplete **3** |
| Nested attempt record missing / malformed / wrong type / Unicode / Permission / IO | incomplete **3** |
| Selector, filename, plan-ID, role, parent or ownership contradiction | **78** |
| Genuine held batch lock | **79** |
| Argparse both/neither selector | **2** |

`query` and `status` remain read-only and keep their historical diagnostics.
A damaged attempt journal is never rewritten; the command returns an explicit
`attempt-incomplete:<state>:<detail>` diagnostic. A missing attempt is not a
busy lock. A real batch-lock conflict remains **79**.

## Interfaces and non-goals

Commands `status`, `query`, `recover`, `cleanup`, `prepare-layout`,
`prepare-bind`, `compile`, `run` remain. The `--attempt`/`--prepare-id`
mutually exclusive selectors and exit codes 0/2/3/78/79 remain. New record
fields are additive: `cleanupCheck`, `cleanupReceipts`, `associationIntents`,
`associationCompleteAt`; plans may carry `parentAttempt` and the current hold
fields. No real Docker, BPF/bpftrace, compiler, sudo, target/fixture execution
or import, fixed selfcheck, dependency installation, subagent/reviewer, live
admission/license, daily configuration/deployment, GitHub push or host-rights
change is part of this phase.
