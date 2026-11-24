# Recovery Close Support Matrix (B1–B4)

This is the support/compatibility matrix for the offline B1–B4 repair. It does
not approve a runtime release. Final post-freeze counts, raw streams, return
codes, result SHA-256 values, source snapshots and shim resolutions are bound
by `checks/evidence-index.json` outside the source manifest.

## Environment actually used

- Source-only candidate; read-only `baseline/` is the exact 70-file old source.
- `protocolRevision` 3; observation protocol `buffer-v2`; framing
  `end-lf-padding-v1`.
- Real containers: **0**. Real bpftrace: **0**. Target executions: **0**.
  Fixtures imported/executed: **0**. Selfchecks: **0**. Formal targets:
  **0/16**. R3: **blocked**. Admission/preflight/licence issued: **no**.
- `checks/shims/docker` and `checks/shims/bpftrace` are the only permitted
  resource programs in executed suites. Suites that run the CLI verify
  `shutil.which` resolves to those shims. Pure in-process suites monkeypatch
  every resource function and count calls.
- Python 3.12 is required (the product pins 3.12.15).

## Affected suites and what they cover

| Suite | Surface | Native/simulated | B1–B4 relevance |
| --- | --- | --- | --- |
| `checks/run_recovery_close_checks.py` | new B1–B4 behavioural checks | in-process doubles + one lock subprocess | selector/file/ID binding, paths/links/NUL, role/attempt/name/tag/image, invalid-plan no-fallback, identity journals, lock 79, ambiguity 2, prep-role recovery, run-role linkage, associated compile isolation, reserve proof, association order/failure, unknown prep holding parent, old empty/orphan records, journals |
| `checks/formal_admission/run_checks.py` | formal admission and recovery | recorded shims + in-process cases | selectors, cleanup final-stage cases, plan-before-stage, cross-record rejection, no replay |
| `checks/formal_admission/red_checks.py` | RED/pass probes | in-process | plan-before-stage, identity-write unknown, early cleanup with plan only |
| `checks/run_regressions.py` | original 28 scenarios | recorded shims | fresh/reuse compile, Q4, cleanup conflicts, early recovery, settlement/no-replay, tamper |
| `checks/run_end_lf_checks.py` | END-LF contract and fixed bytes | recorded shims | protected modules unchanged, manifest binding, END-LF framing |
| `checks/run_rev6_checks.py` | rev6 diagnostics/observer/plan | in-process + shims | buffer/parser/layout and resource lifecycle regressions |
| `checks/run_rev7_checks.py` | rev7 recovery/plan binding | in-process | receipt/plan binding, recovery does not rewrite receipts |
| `checks/run_rev8_checks.py` | rev8 cleanup/recovery edge cases | in-process | missing stage, journal failure, clean final check |
| `checks/run_diagnostics_checks.py` | diagnostics contracts | in-process | zero-real boundary, strict metadata, cleanup branches |
| `checks/run_repair_checks.py` | stream/returncode repair | in-process | incomplete streams, cleanup constructor, scalar END grammar |
| `checks/run_buffer_preflight_checks.py` | buffer preflight/recovery | recorded shims + in-process | original-ID recovery, no replay, buffer marker/END |
| `checks/compile_check.py` | pure compile of tools/checks | pure | syntax only; not behavioural proof |
| `checks/verify_baseline.py` | recompute baseline manifest | pure | 70/70 baseline files and fixed fixture bytes |
| `checks/static_check.py` | delivery/static guards | pure | baseline 70, manifest/file binding, protected bytes, delivery files |

## Compatibility decisions

- **Intended changed product tool:** only `tools/experiment_runner.py`.
  `checks/static_check.py`, `checks/run_end_lf_checks.py` and
  `checks/formal_admission/run_checks.py` migrate old assumptions where the
  approved B1–B4 behaviour intentionally differs (for example, a role-invalid
  stage is now rejected at plan identity, and `judge.py` is protected/unchanged
  in this baseline rather than an intentional change).
- **Historical old-byte checks:** all protected modules, templates, profile,
  target launcher, compile tool, structure and experimental plan remain equal to
  the baseline. Only `tools/experiment_runner.py` is exempted from the
  old-byte-equality expectation.
- **Selectors:** `query/recover/cleanup --attempt` and mutually exclusive
  `--prepare-id` are preserved. `status` is read-only.
- **Exit codes:** success 0; argparse ambiguity 2; incomplete/unknown 3; blocked
  ownership 78; lock busy 79. Prep-role cleanup returns 0 only after confirmed
  resources and durable journals.
- **Old records:** records without explicit `resource-phase-v1` proof and without
  explicit resource intent are held incomplete, never promoted to success.
  Legacy records with explicit resource intent may still be cleaned by their
  recorded identity, because that is resource evidence, not an absence guess.
- **Attempt counter:** never refunded by any recovery/cleanup path.
- **Identity journals:** `<prepareId>.identity.json` is additive. When present it
  is read and bound before destruction; contradiction is 78, unreadable/damaged
  is incomplete.

## Evidence and limitations

- All runs are offline/simulated. RED evidence was produced against the actual
  read-only baseline before product repair; final evidence is produced against
  one frozen source manifest afterwards. Each invocation has its own directory.
- The historical supplied B1/B2 and B3/B4 script output is retained under a
  **history** label. Running the old scripts on the repaired source aborts or
  asserts because the old scripts encode the old outcomes; that is a behaviour
  change observation, **not** a new-source pass.
- No external review, Codex sign-off, real preflight, formal admission, target
  execution, deployment or Git push is claimed.
- Static substring checks are delivery guards only. Behavioural claims rest on
  the executed suites and counted operations, not source-string assertions.
- The repaired source still relies on the existing sealed shims/profiles for any
  future real run; this phase does not prove real-runtime behaviour.
