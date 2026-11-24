# Observer strict-diagnostics repair contract

> Historical scope note: the baseline and RED paths quoted below describe the
> prior bounded-repair phase, not this new root. In this root `baseline/` is the
> frozen 54-file buffer-v1 candidate with manifest
> `1c0a196fbacddd91fc3a42429090c47ac4003999550c738fa69c910d9abd9f8e`.
> See `BUFFER-V2-CONTRACT.md` for the active contract.

Status: implementation and local simulated evidence complete; `pending-codex-review`.
Protocol revision remains `3`; diagnostic version remains `1`. R3 remains
`blocked`; formal targets remain `0/16`.

This contract covers exactly three bounded production repairs plus focused
tests/contracts/manifest updates. It does not admit a run, does not execute a
preflight, target, fixture, container or observer, and does not claim real BPF
compilation or attachment.

## 1. Frozen baseline and recorded RED evidence

`baseline/` is the read-only previous delivery:

* manifest: `cfd163a4cdd4c61d3c17db828f0c3a43d8efc97784a19c613e8a713909454dd5`;
* source-only file count: `48`;
* `codex-baseline/` is immutable Codex evidence created before implementation.

The already-recorded real failures this repair responds to are:

* two `bpftrace -d` compiler-only tests on the old template fail with
  `count`-vs-`int64` and `count`-printf type errors;
* the independent harmless-child checks were `4/5`: an unfinished stream had
  `completed=false`, `eof=false` and `returncode=null`, but the document also
  reported `captureComplete=true` / `confirmed=true`;
* `PreflightFailure(reason, cleanup={...})` raised
  `TypeError: unexpected keyword argument 'cleanup'` instead of preserving a
  `preflight-cleanup-unconfirmed` failure.

No old module-absent baseline-20 run was repeated. The focused RED evidence was
produced by running `checks/run_repair_checks.py --root baseline` through the
existing bounded evidence runner:

* final RED run: `checks/evidence-runs/20261114T073029Z-bfc63c6c-red`
  (`2/11` focused checks passed; nine exact failures preserved);
* retained superseded RED attempts:
  `20261114T072416Z-748c1b87-red` (a copied shim lacked execute mode, so the
  controller scenario could not run) and `20261114T072559Z-93136e0c-red`
  (valid RED, recorded before the runner digest field was added).
  They were not deleted, rewritten or relabelled.

Every RED and post-fix run directory contains its own actual UTC command,
before/after source digests, raw stdout/stderr and result JSON.

## 2. Change 1 — scalar observer counter

File: `tools/observer_template.bt`.

The old `@events = count()` aggregation type is replaced by a plain integer map
counter:

```text
@events = @events + 1;
if (@events > __MAX_EVENTS__) { return; }
```

The END block still copies the scalar to `$events`, clears `@events` before the
END record, and prints `$events` with `%d`. The pid/uid/caller/offset filters,
structure extraction, maximum-four event semantics, unique BEGIN/END and the
map clear before END/default dump are unchanged. Unroll limits, ABI offsets,
source bindings, image, profile, renderer and permissions are untouched. No
event grammar changed.

This is a single-thread fixed-selfcheck counter. It is **not** a claim of a
multi-thread atomic resource budget, and simulated parser coverage is **not**
real BPF compiler validation.

## 3. Change 2 — strict diagnostics predicate

File: `tools/preflight_diagnostics.py`.

* One strict predicate (`_strict_stream_problems`) now governs both the
  persisted document outcome and the returned summary.
* Completeness requires, for every attached stream: `completed` and `eof`, no
  read `error`, no `writeError`, no `truncated`, and exact persisted
  byte/digest metadata verified by re-reading the file after the exclusive
  write.
* Every attached role needs a known integer final returncode. Negative signal
  codes are valid; an actual unknown remains JSON `null` with `known=false`.
  Unattached/never-started roles are not fabricated into empty streams or a
  zero code; they remain conservative/incomplete.
* A drain deadline that expires before EOF records
  `drain-deadline:<role>.<stream>` (or `drain-incomplete` on a drain error).
  A bounded prefix is never silently called complete.
* `process-diagnostics.json` and the returned summary expose
  `incompleteReasons`. The status reader recomputes the same strict predicate
  from on-disk primitives and re-reads the stream files; a stored
  `confirmed=true` flag alone cannot make an incomplete document `present`.
* Idempotent finalization, native early-exit vs deliberate cleanup signal
  distinction, bounded draining/waiting, exclusive output, cross-ID refusal and
  identity checks are preserved. No arbitrary process execution or new
  permission was added.

## 4. Change 3 — cleanup-unconfirmed keyword repair

File: `tools/zero_target_preflight.py`.

`PreflightFailure(reason, detail=None, cleanup=None)` now accepts optional
cleanup evidence already observed at the raising site. The outer failure handler
preserves it with the original reason under `cleanup.raised` and top-level
`cleanupEvidence`. The `preflight-cleanup-unconfirmed` route remains exit `79`,
`state=blocked`, `cleanup.confirmed=false`, with the stage retained and no
accepted receipt. It cannot become a `TypeError`, success or completed claim.
No unrelated lifecycle was rewritten.

## 5. Tests and expected counts

New focused suite: `checks/run_repair_checks.py` (11 checks).

It covers: unfinished stdout/stderr; EOF with an alive child; known vs unknown
returncode; negative signal code; normal complete capture and read-only status;
stream read failure; truncation; diagnostic write failure (exact reason and
artifact state); repeated finalize; constructor plus controller
cleanup-unconfirmed path with no-effect cleanup/container/stage recorders and
zero forbidden removal calls; and scalar-counter/END grammar at parser and
simulation level for `0`, `1`, `4` and an over-budget stream of `5` (which stays
invalid under the unchanged `MAX_EVENTS=4`, never silently accepted).

Final post-fix simulated results expected in the bound evidence run:

* existing diagnostics: `20/20`;
* focused repair: `11/11`;
* original simulations: `28/28`;
* revision-6 simulations: `24/24`;
* revision-7 simulations: `12/12`;
* revision-8 simulations: `13/13` (77 total simulations);
* pure compile: all current `tools/*.py` and `checks/*.py` (32 files);
* static/delivery: all checks, including final source-only manifest binding.

## 6. Retained limitations

* No real preflight, probe attach, target, fixture, NLTK/tqdm, Docker or
  bpftrace invocation was performed by the implementer. Docker/bpftrace remain
  recorded shims for controller tests.
* Real fixed-image ABI, real bpftrace v0.20.2 `-d` compilation and real
  attachment remain for Codex after source admission. The two NEW compiler-only
  checks are not consumed here.
* A controller hard crash/kernel kill/OOM before finalization, evidence
  filesystem loss/full disk, double interrupt and double-forked/escaped-pipe
  processes remain disclosed unsupported loss windows.
* Historical receipts/diagnostic documents are never rewritten or backfilled.
  An old document that lacks the strict persisted fields is read as
  `incomplete`, not retroactively promoted by its old aggregate flags.
* `targetExecutions=0`, `fixturesImported=0`, `realContainers=0`,
  `preflightExecuted=false`, `admissionIssued=false`, `r3=blocked`.

The implementation stops here. Codex owns independent NEW compiler-only checks,
source review and at most one fixed live selfcheck after source admission.
