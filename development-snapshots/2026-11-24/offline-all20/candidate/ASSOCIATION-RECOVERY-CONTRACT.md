# Association Recovery Contract (B5–B7), protocolRevision 3

> Scope note: this document records the B5–B7 round. The subsequent unified
> B8/B9/B10/D1 scope is specified in `UNIFIED-RECOVERY-CONTRACT.md` and
> `UNIFIED-RECOVERY-SUPPORT.md`; its checks extend this contract without
> changing the public commands, receipt schema or `protocolRevision` 3.

Status: **offline source candidate, pending independent Codex check and host
review**. This is not a runtime receipt, admission, preflight result or formal
batch result. Real resources remain **0**; formal targets remain **0/16**; R3
remains **blocked**. No reviewer, selfcheck, target, fixture, container,
bpftrace program, license or admission is run in this phase.

Baseline is the exact 75-file recovery-close candidate
`3b88be8b9fd3b05c2add663295db49429b77555a302148e53bebc514333149c2`.
The only intended changed product tool is `tools/experiment_runner.py`. All
judge, parser, observer, preflight, launcher, compiler, template, fixture and
experiment-plan bytes remain protected and byte-identical to the baseline.

This contract separates three things that were previously conflated:

1. **historical resource-creation proof** — monotonic evidence that a stage,
   container or process *was* created;
2. **current cleanup/recovery status** — what a fresh check proves *now*;
3. **the permanently spent attempt budget** — never refunded, never replayed.

## B5 — creation proof is not current cleanup status

### Durable fields

Attempt records and preparation plans keep the historical creation proof:
`resourceProof` (`resource-phase-v1`) and its `sequence`/`notCreated` bytes.
Cleanup never moves that proof backward and never rewrites its sequence. New
records advance it only while resources are being created.

The current cleanup is recorded separately:

- `cleanupCheck = {protocol: "cleanup-check-v1", state: "checking" |
  "incomplete" | "confirmed", startedAt, startedCount, finishedAt, reason}`;
- `cleanup = {confirmed, state, ...evidence...}` for the current check;
- `cleanupReceipts` is an append-only, bounded list of completed checks, so a
  later incomplete check cannot erase an earlier completion receipt;
- `reservationHeld` and `settled` describe the current reservation.

### Required order

Before **every** recovery/cleanup operation, and before the first resource
query, the runner durably writes:

```
cleanup        = {confirmed: false, state: "checking", ...}
cleanupCheck   = {state: "checking", ...}
reservationHeld = true
settled         = false
```

Each durable write is read back. A missing/unreadable/mismatched journal is
unknown persistence: the command returns incomplete **3** and never reports
success. The write happens for the target attempt and for every preparation
plan whose resources are about to be queried.

### Reappeared or unknown resources

A fresh recovery always re-queries even an already-confirmed preparation. If a
stage/container/process reappears or its state is unknown:

- the current cleanup is unconfirmed and the command returns **3**;
- **both** the parent target and the associated child keep
  `reservationHeld=true` and the child plan is held;
- `settled` is false and `cleanup.confirmed` is false; a stale
  `settled=true`/`reservationHeld=false` is never reported;
- the historical creation phase is unchanged, so there is no
  `resource-phase-regression` **78**.

Success is cleared only after a full fresh check and a final durable log. A
later check may restore success when the resources are actually gone. The
attempt counter remains spent and no target/compile/selfcheck is replayed.
Historical completion receipts and `targetExecutions` are not rewritten to
claim new execution.

## B6 — atomic parent/child association

### Three durable writes under the existing batch lock

For a preparation that must belong to a target attempt:

1. **parent association intent first** — `associationIntents` receives
   `{protocol: "association-intent-v1", attempt, prepareId, state: "pending",
   startedAt}` and the parent is durably held (`reservationHeld=true`,
   `settled=false`);
2. **child `parentAttempt` second** — the original child plan records
   `parentAttempt=attempt` and `associationState="pending"`;
3. **parent association-complete last** — one parent write adds the child to
   `associatedPrepareIds` and flips the matching intent to `state: "complete"`.

The completion write is read back. If any write is interrupted, the parent
stays held. A pending intent, a child that is listed without `parentAttempt`, a
missing child, or a completion that cannot be read back is an incomplete
association. It prevents subsequent creation of a stage, container or process
for that association; no target stage/container is created merely because the
parent list is empty.

### Recovery reconciliation

Parent settlement reconciles all of:

- `associatedPrepareIds`;
- every `associationIntents` entry, pending or complete;
- reverse child→parent relations (`plan.parentAttempt == attempt`);
- preexisting standalone `compile-NNNN-*` plans for the attempt, and bind
  plans reverse-linked to the attempt.

An empty parent list is **not** proof that no child exists. The scan is bounded
to tool-owned plan files and never performs unrelated/global cleanup.

- A readable plan that claims the attempt with a different `prepareId`, role,
  attempt or parent, or that has contradictory stage/container/tag identity, is
  an ownership contradiction: **78 before any signal or delete**.
- A missing, unreadable, malformed or shape-damaged potentially relevant plan
  is incomplete. The parent and every known child stay held and no destructive
  operation runs.
- A pending intent identifies the original child. Recovery never invents an
  identity, never substitutes another readable child, never overwrites a
  contradictory `parentAttempt` and never auto-links a contradiction.
- Old records without an explicit link remain conservative: the link is used
  only when it is actually recorded (list, intent or reverse `parentAttempt`);
  otherwise the result is incomplete, not a guessed success.
- Reconciliation only queries and cleans the original resources. It never
  compiles, binds or executes the target.

## B7 — direct recovery classification

For `recover --prepare-id` and `cleanup --prepare-id`:

| Condition | Result | Resource operations |
| --- | --- | --- |
| Plan file missing | incomplete **3** | none |
| Malformed JSON / invalid shape | incomplete **3** | none |
| `PermissionError`, IO error or other `OSError` | incomplete **3** | none |
| Selector/filename/plan-ID/role/ownership contradiction | blocked **78** | none before block |
| Genuine held batch lock | **79** | none |
| CLI both/neither selector (argparse) | **2** | none |

The direct recovering interface uses a classification read
(`open_lifecycle_plan`) rather than the historical query/status diagnostic
path. On an incomplete direct read the parent reservation(s) exactly bound by
the requested ID are durably retained (`reservationHeld=true`, `settled=false`,
current cleanup incomplete) and no destructive operation is attempted.
`query`/`status` may keep their historical diagnostics; recovery classification
is the contract above.

A run-role plan whose attempt record is absent is also incomplete **3** in
recovery, not lock-busy **79**. `79` in recovery is reserved for a genuine
batch-lock conflict.

## Interfaces kept compatible

- `protocolRevision` remains **3**; observation protocol `buffer-v2`; framing
  `end-lf-padding-v1`.
- Existing commands `status`, `query`, `recover`, `cleanup`, `prepare-layout`,
  `prepare-bind`, `compile`, `run` remain; the mutually exclusive
  `--attempt` / `--prepare-id` selectors and exit codes 0/2/3/78/79 remain.
- New record fields are additive: `cleanupCheck`, `cleanupReceipts`,
  `associationIntents`, `associationCompleteAt`.
- Existing old records are read conservatively; no old record is promoted to a
  modern success merely because a field is absent.

## Explicit non-goals

No real Docker, BPF/bpftrace, compiler, sudo, target/fixture execution or
import, fixed selfcheck, dependency installation, subagent/reviewer, live
admission/license, daily configuration/deployment, GitHub push or host-rights
change. This phase issues no runtime or formal admission.
