# Association Recovery Support Matrix (B5–B7)

This is the support/compatibility matrix for the offline B5–B7 repair. It does
not approve a runtime release, formal batch or admission. Final post-freeze
counts, commands, raw streams, return codes, result digests, source snapshots
and bundle hashes are bound by `checks/evidence-index.json`, which is outside
`protocol-manifest.json`.

## Environment actually used

- Source-only candidate; read-only `baseline/` is the exact 75-file
  recovery-close candidate
  `3b88be8b9fd3b05c2add663295db49429b77555a302148e53bebc514333149c2`.
- Python 3.12 (the product pins 3.12.15); observation protocol `buffer-v2`;
  framing `end-lf-padding-v1`; `protocolRevision` 3.
- Real containers: **0**. Real bpftrace: **0**. Target executions: **0**.
  Fixtures imported/executed: **0**. Selfchecks: **0**. Formal targets:
  **0/16**. R3: **blocked**. Admission/preflight/license issued: **no**.
- New B5–B7 checks are pure in-process tests with counting doubles. No Docker,
  bpftrace, signal, target, fixture or admission file is created. Existing
  recorded-shim suites are run only with their controlled shims and verify the
  shim resolution.

## New and affected suites

| Suite | Surface | Native/simulated | B5–B7 relevance |
| --- | --- | --- | --- |
| `checks/run_association_recovery_checks.py` | new B5–B7 desired-behaviour checks (21) | in-process doubles, one lock subprocess | cleanup-check durability/receipts, reappearance and restoration, journal failure, association order/interruption/reverse links/standalone and bind plans/unreadable/contradiction/original intent, direct read classification, genuine lock and CLI ambiguity |
| `checks/run_recovery_close_checks.py` | previous B1–B4 checks (24) | in-process + one lock subprocess | regression gate for exact identity, no fallback, role routing, reservation and association basics |
| `checks/run_regressions.py` | original recorded-shim scenarios (28) | recorded shims | fresh/reuse compile, Q4, cleanup conflict, early recovery, no replay, tamper |
| `checks/formal_admission/run_checks.py` | simulated formal admission (15) | recorded shims + in-process | cleanup final-stage cases, reservation/settlement, cross-record rejection |
| `checks/formal_admission/red_checks.py` | formal RED/pass probes (6) | in-process | plan-before-stage, identity write unknown, early cleanup |
| `checks/run_end_lf_checks.py` | END-LF contract (13) | recorded shims | protected bytes, manifest binding, END-LF framing |
| `checks/run_rev6_checks.py` | rev6 (24) | in-process + shims | diagnostics/observer/plan regression |
| `checks/run_rev7_checks.py` | rev7 (12) | in-process | recovery/plan binding, receipt preservation |
| `checks/run_rev8_checks.py` | rev8 (13) | in-process | final stage recheck, journal failure classification |
| `checks/run_diagnostics_checks.py` | diagnostics (20) | in-process | zero-real boundary, strict metadata, cleanup branches |
| `checks/run_repair_checks.py` | repair (11) | in-process | stream/returncode repair, cleanup constructor |
| `checks/run_buffer_preflight_checks.py` | buffer preflight (29) | recorded shims + in-process | original-ID recovery, no replay, buffer marker/END |
| `checks/compile_check.py` | pure compile (49 files) | pure | syntax only, not behavioural proof |
| `checks/verify_baseline.py` | baseline recompute (75) | pure | 75/75 baseline bytes and fixed fixture bytes |
| `checks/static_check.py` | delivery/static guards | pure | baseline 75, manifest binding, protected bytes, delivery files |

## Intended changes and compatibility decisions

- **Changed product tool:** only `tools/experiment_runner.py`. Every other
  `tools/` file remains byte-identical to the 75-file baseline.
- **New source/test/document files:** `ASSOCIATION-RECOVERY-CONTRACT.md`,
  `ASSOCIATION-RECOVERY-SUPPORT.md`,
  `checks/run_association_recovery_checks.py`,
  `checks/make_association_evidence_index.py`, and the additive documentation
  in `checks/evidence_capture.py` / `checks/static_check.py` /
  `checks/make_source_manifest.py`.
- **Static baseline migration:** `checks/static_check.py` previously hard-coded
  the 70-file/`d06e…` baseline. It now compares the correct 75-file
  `3b88…` baseline and still protects all intended unchanged tool bytes.
  Initial pre-migration evidence is retained (`static-initial`, 260/266, with
  the four expected 70-file baseline mismatches plus missing phase-result and
  manifest); the migration reason is the approved 75-file baseline.
- **Selectors/exit codes:** `query/recover/cleanup --attempt` and the mutually
  exclusive `--prepare-id` remain; success 0; argparse ambiguity 2;
  incomplete/unknown 3; ownership contradiction 78; genuine lock busy 79.
- **Direct recovery read errors:** missing/malformed/PermissionError/IO/OSError
  on `--prepare-id` are 3, not the historical 79. Query/status diagnostics stay
  compatible; direct recovery classification is the B7 contract.
- **Current vs historical:** `resourceProof` is historical creation evidence;
  `cleanupCheck`, `cleanup`, `cleanupReceipts`, `reservationHeld` and `settled`
  are current state. Cleanup never rewrites the historical sequence.
- **Association:** parent intent → child `parentAttempt` → parent completion.
  Pending/incomplete associations block new stage/container/process creation.
  Recovery reconciles list, intents, reverse links and standalone compile/bind
  plans. Empty parent list is not absence proof. Unreadable/malformed
  potentially relevant plans keep the parent held and are not skipped.
- **Attempt budget:** never refunded by any recovery/cleanup path; repeated
  recovery does not replay compile, bind, selfcheck or target execution.
- **Old records:** records without explicit links/proof stay conservative and
  are never promoted to success by guesswork.

## Test-first, freeze and evidence rules

- RED desired-behaviour tests were written before product edits and run against
  the untouched `baseline/tools` (initial 18 checks: 16 desired failures and 2
  regression gates passing; a supplemental expanded 21-check run records the
  two later additions and keeps the original output).
- Every invocation, including smoke, failure and interim runs, uses a new
  evidence directory under `checks/evidence-runs/`. The exact argv, PATH,
  source snapshot before/after, stdout/stderr bytes, return code, result-file
  digest and bundle digest are captured by `checks/evidence_capture.py`.
- Exploratory/interim evidence is retained; result files and evidence
  directories are never overwritten or reused.
- After source/tests/contracts are final, `protocol-manifest.json` is written
  once (source-only; excludes `baseline/`, evidence, `checks/tmp/`, results,
  `REPORT.md`, `phase-result.json` and the evidence index). All final affected
  suites then run on the same frozen bytes. Any later source change requires a
  new freeze and a full affected rerun while keeping earlier evidence.

## Limitations

- All evidence is offline/simulated. The repaired source still relies on the
  existing sealed shims/profile for any future real run; this phase does not
  prove real-runtime behaviour.
- The association scan is deliberately conservative. An unreadable plan file
  with a tool-owned ID can hold a parent even if it later proves unrelated.
  That is an incomplete result, not destructive cleanup.
- Static substring checks are delivery guards only. Behavioural claims rest on
  executed suites and counted operations.
- No external review, Codex sign-off, real preflight, formal admission, target
  execution, deployment or Git push is claimed.
