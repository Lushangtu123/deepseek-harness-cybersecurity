# Recovery Close Contract (B1–B4), protocolRevision 3

Status: **offline source candidate, pending independent Codex check and external
source review**. This contract is not a runtime receipt, an admission, a
preflight result or a formal-batch result. Real Docker, bpftrace, targets,
fixtures, selfchecks and formal attempts are **0**; R3 remains **blocked**;
formal targets remain **0/16**.

The only intended changed product tool is `tools/experiment_runner.py`. The
other tools, the three templates, the profile, `structure.py`,
`target_launcher.py`, `experiment_compile.py`, fixture bytes and
`experiment-plan.json` remain byte-identical to the 70-file baseline
`d06e9fa16daa68edf3645a027ef594a50b725e94fabe773fb9bfabc8bee7f877`.

## B1 — exact identity and predetermined paths

1. `read_lifecycle_plan(requestedId)` binds, exactly and together:
   the requested selector, the filename `<requestedId>.json`, and the stored
   `plan.prepareId`. A filename whose content names a different plan is an
   ownership contradiction (78), not a copy to operate.
2. The same reader/guard is used by plan updates, `query`, `recover`, `cleanup`
   and target/preparation resource settlement — not only by the CLI parser.
3. Only three tool-owned roles are accepted:
   `run-NNNN`, `bind-XXXXXXXX`, `compile-NNNN-XXXXXXXX`. `operationRole` and
   `role` must agree. Unknown roles are rejected before resource calls.
4. Stage paths are predetermined and exact:
   - `run-NNNN`: `RUNS/NNNN/stage-<tag>`, `plan.attempt == NNNN`;
   - `bind-XXXXXXXX`: `PREPARE/stage-bind-<tag>`, tag prefix `XXXXXXXX`,
     no attempt number;
   - `compile-NNNN-XXXXXXXX`: `PREPARE/stage-compile-NNNN-<tag>`, tag prefix
     `XXXXXXXX`, `plan.attempt == NNNN`.
   A stage equal to a `PREPARE`/`RUNS` root, outside its role pattern, containing
   `..` or NUL, or reached through a symlink is rejected before any signal,
   deletion or settlement.
5. Container name, tag, image ID and the stored stage identity are validated as
   one identity. Cross-record contradictions against `resourceIntent`,
   `resourceIdentity`, `stageDir`, `containerId` and `stageIdentity` are blocked
   before destruction.
6. `prepareId` is immutable through update fields. A role change through an
   update is also rejected.

## B2 — no invalid-plan fallback

If an attempt carries `prepareId`, a missing, unreadable, damaged, malformed or
identity-invalid plan is **never** permission to reconstruct identity from
`resourceIntent`.

| Condition | Result |
| --- | --- |
| Selector/file/plan-id/role/name/tag/image/path contradiction | blocked **78**, before destructive calls |
| Missing plan, permission/IO error, JSON/shape damage, unconfirmed identity journal | incomplete **3**, intent/files/reservation preserved |
| Batch lock busy | **79** |
| CLI selector ambiguity (both/neither) | argparse **2** |

`SystemExit(78/79)` is not swallowed and never followed by deletion. An optional
`<prepareId>.identity.json` journal, when present, is read and bound before
resource handling; a contradiction is 78, an unreadable/damaged journal is
incomplete. Old incomplete records remain unknown; they are not promoted into a
modern success. There is no fallback merely because a plan is absent.

## B3 — route by role, not by integer attempt

1. `bind-*` and `compile-*` roles always recover **their original preparation
   plan/resources**, even when `plan.attempt` is an integer association with a
   future parent target. They work with no target attempt record.
2. Only `run-NNNN` routes into target cleanup. That route requires:
   `selector == plan.prepareId == targetRecord.prepareId` and
   `plan.attempt == targetRecord.attempt`. A mismatch is blocked before
   destruction.
3. `query/recover/cleanup --attempt` and the mutually exclusive
   `--prepare-id` interface remain. `status` remains read-only.
4. Recovery/cleanup never redoes compile, bind, selfcheck or a target. It only
   queries and cleans resources and writes durable journals.
5. Associated preparation plans are never confused with the parent target: a
   compile selector recovers the compile plan only.

## B4 — durable resource-free proof and parent associations

### resource-phase-v1

A new target reservation persists, before any resource can exist:

- explicit `processes.client` and `processes.observer` records with
  `spawnState: not-started`;
- `resourceProof = {protocol: "resource-phase-v1", phase: "reserved",
  notCreated: {stage: true, container: true, client: true, observer: true},
  sequence: [...], targetAttempt: n}`.

Phases advance monotonically: `reserved → plan-created → stage-creation →
stage-created → container-creation → container-created → client-spawn →
observer-spawn → running → cleanup-unconfirmed/cleanup-confirmed`. A backward
transition is blocked. Each `notCreated` flag may only change true → false.

### Association order

Every associated preparation plan ID is written to the parent target
(`associatedPrepareIds`) and `parentAttempt` is written to the preparation plan
**before** that preparation creates a stage, container or process. Failure
between plan creation and association cannot create resources. Failure or
unknown state after association keeps the parent reservation held.

### Releasing a target reservation

Before a target reservation is released, the runner requires one of:

1. explicit resource-phase not-created proof for the target, or
2. actual cleanup/accounting of every associated preparation and run resource,
   under the stable batch lock.

An absent plan, elapsed time or `processes={}` is not a proof. An active or
unknown preparation keeps the parent held. Old records without the explicit new
proof remain incomplete.

### Settlement versus attempt counter

Resource reservation settlement is separate from the permanently spent target
attempt counter. A target slot is never refunded — including failed, aborted or
reserve-only attempts. Cleanup never writes the counter.

### Final stage and logs

Successful cleanup/settlement requires the final stage `lstat` to be absent
**after** all container/process/associated-resource handling, and durable final
plan/attempt journals. Any journal write/fsync failure is incomplete (3), not
success. On a final attempt-journal failure the plan is best-effort held again;
the reservation remains held.

## Interfaces kept compatible

`protocolRevision` remains **3**. The existing CLI commands, exit codes 0/2/3/
78/79, attempt-record fields, preparation receipts and judge interface are kept.
New fields are additive: `resourceProof`, `associatedPrepareIds`,
`parentAttempt`, `associationState`, `settlement`. No new executable helper or
project-chosen command is introduced.

## Explicit non-goals

No real resource execution, no new preflight/admission/license, no formal batch,
no deployment, no Git push, no daily configuration change, and no claim of
external review or runtime success. See `RECOVERY-CLOSE-SUPPORT.md` for the
suite matrix and evidence limits.
