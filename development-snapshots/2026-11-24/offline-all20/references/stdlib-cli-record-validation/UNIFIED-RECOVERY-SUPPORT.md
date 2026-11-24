# Unified Recovery Support Matrix (B8/B9/B10/D1)

Status: offline source candidate, **pending Codex independent check**; real
resources 0, formal targets 0/16, R3 blocked. This matrix is descriptive only.
It is not a runtime receipt or an admission. Exact run counts and raw results
live in the non-source evidence index, not in this frozen document.

## Behaviour matrix

| ID | Selector / trigger | Durable effect | Exit | Resource operations | Primary checks |
| --- | --- | --- | --- | --- | --- |
| B8-permission | parent `recover/cleanup --attempt` while `prepare/plans` cannot be listed | parent held/unsettled, current cleanup incomplete, known readable children held, directory-unknown diagnostic | 3 | none | `B8-directory-permission-parent-incomplete3` |
| B8-io | enumeration raises `OSError` | same, reason `association-directory-unknown` | 3 | none | `B8-directory-io-child-held-incomplete3` |
| B8-partial | iteration fails after some entries | already-read readable child held; parent incomplete | 3 | none | `B8-directory-partial-iteration-incomplete3` |
| B8-empty | fully enumerated empty directory, no associated reference, original not-created proof | parent may settle normally | 0 | none | `B8-empty-directory-success-with-proof` |
| B8-absent | actual absent directory, no associated reference, original not-created proof | parent may settle normally; absence is not an empty-list inference | 0 | none | `B8-absent-directory-success-with-proof` |
| B8-absent-ref | absent directory plus a durable child reference | reference preserved; parent held | 3 | none | `B8-absent-directory-known-ref-incomplete3` |
| B8-link | plans path is a symlink | contradiction; no signal/delete | 78 | none | `B8-directory-symlink-blocked78` |
| B8-nondir | plans path is a regular file/non-directory | contradiction; no signal/delete | 78 | none | `B8-directory-not-directory-blocked78` |
| B8-owner | directory owner uid differs from runner uid | contradiction; no signal/delete | 78 | none | `B8-directory-ownership-blocked78` |
| B8-change | directory dev/ino or entry set changes after discovery | contradiction before deletion | 78 | none after change | `B8-directory-identity-change-blocked78` |
| B9-bound | direct child `recover/cleanup --prepare-id` with one exact durable parent | parent held with reason `parent-full-recheck-required` before child check; child may clean | 0 child / parent held | child only | `B9-direct-child-invalidates-bound-parent`, `B9-cleanup-alias-invalidates-bound-parent` |
| B9-multiple | selected child has siblings | parent remains held; a later full parent recovery must prove all siblings clear | child 0, parent 3 until clear | selected child only | `B9-multiple-known-children-parent-full-recheck` |
| B9-standalone | direct child with no recorded parent | child independently recoverable, no parent invented | 0 | child only | `B9-standalone-child-independent` |
| B9-parent-read | parent attempt missing/malformed/type/Unicode/Permission/IO | child held, no child resource operation | 3 | none | `B9-parent-attempt-unreadable-variants` |
| B9-unconfirmed | `parentAttempt` set but no matching parent list/intent | child and claimed/readable parent held, no auto-link | 3 | none | `B9-parent-link-unconfirmed-incomplete3` |
| B9-ambiguous | multiple durable parents claim one child | selected child and claiming parents held; contradiction | 78 | none | `B9-ambiguous-parent-blocked78` |
| B9-parent-journal | parent hold cannot be persisted | child held; no child resource operation | 3 | none | `B9-parent-journal-failure-before-child` |
| B9-child-journal | child final journal cannot be persisted | parent held; no success claim | 3 | child cleanup may have run; no success | `B9-child-final-journal-failure-no-success` |
| B10-missing | parent target plan missing, known children readable | all readable known children held; parent held | 3 | none | `B10-target-plan-unavailable-child-held-variants` |
| B10-malformed | parent target plan malformed JSON | same | 3 | none | same family |
| B10-unicode | parent target plan non-UTF-8 | same; damaged bytes retained | 3 | none | same family |
| B10-type | parent target plan wrong top-level type | same; damaged bytes retained | 3 | none | same family |
| B10-permission | parent target plan read denied | same | 3 | none | same family |
| B10-io | parent target plan IO read failure | same | 3 | none | same family |
| B10-unreadable-child | one known child file is damaged | damaged child bytes retained; readable children held; explicit unknown | 3 | none | `B10-unreadable-child-retained-unknown` |
| B10-contradiction | child plan ownership contradicts | contradiction before signal/delete | 78 | none | `B10-ownership-contradiction-blocked78` |
| D1-attempt | selected attempt missing/JSON/type/Unicode/Permission/IO | explicit `attempt-incomplete`; no busy 79, no traceback | 3 | none | `D1-recover-attempt-read-variants` |
| D1-nested | run-role preparation selects a damaged nested attempt | explicit incomplete; plan held/marked; damaged attempt retained | 3 | none | `D1-run-prepare-nested-attempt-variants` |
| D1-contradiction | selector/ownership contradiction | blocked | 78 | none | existing B1/B2/B3/B6 checks |
| D1-lock | genuine held batch lock | busy | 79 | none | `D1-actual-lockbusy-and-selector-ambiguity` |
| D1-ambiguity | argparse both/neither selector | usage error | 2 | none | `D1-actual-lockbusy-and-selector-ambiguity` |
| D1-readonly | `status` / `query` | no record/plan mutation | 0 | none | `D1-query-status-read-only` |

## Current versus historical state

| Question | Read from | Recovery rule |
| --- | --- | --- |
| Was a resource ever created? | `resourceProof`, `targetExecutions`, creation timestamps | Preserve exactly; never infer current absence from it and never move it backward. |
| Was a cleanup ever completed? | `cleanupReceipts[]` | Preserve append-only; do not delete an earlier confirmed receipt because the current check is incomplete. |
| Is the current cleanup started/finished? | `cleanupCheck`, `cleanup` | Start durably as `checking`, finish as `incomplete` or `confirmed`; a failed final journal cannot be success. |
| Is the reservation still held? | `reservationHeld`, `settled` | Hold before resource operations; release an attempt only after a complete confirmed scope and durable settlement. |
| Was the attempt budget spent? | attempt counter | Never refund or replay. |
| Is this child bound to this parent? | `parentAttempt`, `associatedPrepareIds`, `associationIntents`, validated reverse plans | Use only recorded links; one-sided or multiple links are incomplete/contradictory. |

## Scope and evidence boundaries

All checks are pure/offline. `checks/run_unified_recovery_checks.py` is
source-parameterised and was run against the untouched baseline to retain RED
desired-behaviour failures before the product edit, then against the frozen
candidate for GREEN. `checks/capture_suite.py` records the exact argv, cwd,
PATH/shim resolution, raw stdout/stderr, return code, result digest and full
manifest entries before and after each invocation in a new run directory.

Protected bytes: `tools/judge.py`, `tools/observation_pure.py`,
`tools/collect_observer.py`, `tools/observer_render.py`,
`tools/preflight_verify.py`, `tools/preflight_selfcheck.py`,
`tools/preflight_diagnostics.py`, `tools/zero_target_preflight.py`,
`tools/buffer_protocol*.py`, `tools/experiment_compile.py`,
`tools/target_launcher.py`, `tools/structure.py`, `tools/resource_guard.py`,
all observer templates, all fixtures and `experiment-plan.json` remain
byte-identical to the baseline. Only `tools/experiment_runner.py` is the
changed product tool; the manifest/evidence/test helpers and this contract
support the freeze.

No real Docker, BPF/bpftrace, compiler, sudo, target/fixture execution or
import, fixed selfcheck, dependency installation, subagent/reviewer, live
admission/license, daily deployment/config, GitHub push or host-rights change
was performed. The external Claude-first/authorized Flash fallback review is
outside this implementation deliverable.
