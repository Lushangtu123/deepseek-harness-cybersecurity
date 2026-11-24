# Observer early-exit diagnostics contract (version 1)

> Historical scope note: this additive diagnostic contract is retained from the
> v1 candidate. In this new root the active preflight protocol is buffer-v2; the
> frozen 54-file baseline manifest is
> `1c0a196fbacddd91fc3a42429090c47ac4003999550c738fa69c910d9abd9f8e`.
> See `BUFFER-V2-CONTRACT.md` for the active contract.

Status: additive diagnostic interface for the zero-target preflight. Protocol
revision remains `3`. This document does not admit a run, does not change
`preflight`/`status`/`recover` exit-code semantics, and does not modify the
observer template, renderer, profile, image, ABI, limits, environment or
permissions.

## 1. Purpose and non-goal

The previous preflight exited `79` with `preflight-observer-not-armed`. The
observer identity had been persisted and, about `0.125 s` later, the observer
was already gone before cleanup. Raw stdout/stderr and the native exit code
were lost. This diagnostic version only makes the next failure inspectable:

* distinguish a pre-cleanup exit from a signal that the controller deliberately
  sent during cleanup;
* preserve bounded stdout/stderr from the moment each child is spawned,
  including when the identity-journal write or readiness check fails;
* record lifecycle milestones, readiness observations and honest returncode
  knowledge.

It does **not** diagnose, guess or repair the unknown root cause and it does not
make the observer start.

## 2. New exclusive artifacts

For a new preflight invocation, five exclusive files are added under the
original `preflight/evidence/<preflightId>/` directory:

| file | meaning |
| --- | --- |
| `diagnostic-client.stdout` | bounded bytes actually read from the client's stdout |
| `diagnostic-client.stderr` | bounded bytes actually read from the client's stderr |
| `diagnostic-observer.stdout` | bounded bytes actually read from the observer's stdout |
| `diagnostic-observer.stderr` | bounded bytes actually read from the observer's stderr |
| `process-diagnostics.json` | `kind=zero-target-preflight-process-diagnostics`, `version=1`, `diagnosticVersion=1` metadata |

The existing `observer.raw` and `observation.json` are never overwritten and
never replaced by these files. `observer.raw` remains the observer-stream
evidence used by the existing collector/verifier; the diagnostic file is a
separate copy of the bytes that were drained. No diagnostic file is accepted as
observation evidence, and no log, model statement or target output can produce
accepted observation evidence.

Bounded capture reuses `resource_guard.StreamDrain` with the existing limit of
`262144` bytes per stream. The reader continues draining to EOF so the child
cannot block; only the first bounded prefix is retained. No pipe is consumed
twice and `communicate()` is never used while a drainer owns the pipe.

## 3. Runtime ownership

`tools/preflight_diagnostics.py::InvocationRuntime` is one outer
invocation-owned object. It is the only place that stores Python `Popen`
handles, stream drainers and locks. JSON documents contain primitives only.

`spawn_process` attaches the already-owned `Popen` handle and both drainers
**immediately after `Popen` returns**, before the identity-journal write can
fail. Therefore a failure of
`process-<role>-identity.json` no longer loses the process streams. A role that
is never spawned has no streams; its diagnostic entries are explicitly marked
`stream-not-attached` rather than fabricated.

Diagnostics never replace the conservative process-group identity checks. A
`Popen.poll()`/`wait()` result is evidence only; it neither authorizes a signal
nor proves that an unknown process group is safe. Only pre-existing,
already-owned `Popen` children are polled or waited. Descendants and unknown
group members keep the existing `resource_guard` safeguards.

## 4. `process-diagnostics.json` fields

Top-level binding and runtime fields include:

* `preflightId`, `tag`, `evidenceDir`-relative `path`;
* `protocolManifestSha256`, `candidateManifestSha256`,
  `preflightLicenseSha256`, `sourceReviewReceiptSha256`, `claimSha256`;
* the exact `resourcePlan` and `resourcePlanSha256`;
* `controller`: effective UID/GID, `CapEff` and `NoNewPrivs` read from
  `/proc/self/status`;
* `bpftrace`: resolved path from `shutil.which`, the sealed profile's declared
  version (if present), an optional externally supplied observed version and
  `probeSpawned=false`. The controller never spawns a second bpftrace to ask for
  its version;
* `roles.client` and `roles.observer`: role, original PID, original identity if
  known, identity-journal persisted flag, command, spawn timing, observed-exit
  timing, pre-cleanup poll, all poll snapshots, post-cleanup returncode and
  deliberate cleanup signals;
* `lifecycle`: `configAcquired`, `observerReadyObserved`, `goSendAttempted`,
  `goFlushCompleted`, `clientExited`, each with observed/count/UTC/monotonic;
* `readiness`: `ready` / `early-exit` / `stream-error` / `timeout` / `unknown`;
* `outcome`: phase, original failure reason, separate capture error,
  persistence/capture completeness and confirmation;
* `files`: per-stream byte length, SHA-256, cap, `truncated`, `completed`, `eof`,
  `error`, `freshness`, phase, returncode-known and write status.

Returncode rules:

* `preCleanupPoll` is captured before cleanup requests any signal. For the
  observer, the first snapshot is taken immediately before the existing
  graceful stop; a second snapshot is taken at general cleanup.
* `postCleanupReturncode` is obtained with `Popen.poll()` and, when still
  unknown, a bounded `Popen.wait(timeout=...)`.
* A native signal is preserved as a negative returncode (for example `-2` for
  `SIGINT`).
* If no result can be confirmed, the value is JSON `null` with
  `known=false`. It is never coerced to `0`.
* Deliberate cleanup signals are recorded separately in
  `roles.<role>.cleanupSignals` with signal/forced/stopped state.

Strict completeness rules (repair, same diagnostic version `1`):

* `captureComplete` and `confirmed` require **every attached stream** to have
  `completed=true` and `eof=true`, with no read `error`, no `writeError`, no
  `truncated`, and exact persisted byte/digest metadata matching the file read
  back from disk;
* every attached role must have a known integer `postCleanupReturncode`.
  Negative signal codes are valid; a still-unknown code remains JSON `null`.
  Never-started/unattached roles are never fabricated as empty streams or
  code `0`, so they remain conservative/incomplete;
* a drain deadline that expires before EOF records an explicit
  `drain-deadline:<role>.<stream>` capture error (or `drain-incomplete` when
  the drain itself failed). A bounded prefix is not silent completion;
* `process-diagnostics.json` and the returned in-memory summary are computed
  from the same strict predicate. Its `outcome.confirmed`,
  `outcome.captureComplete` and `outcome.incompleteReasons` are the persisted
  form of that predicate.

Readiness rules:

* `ready` requires an actual `BEGIN ` prefix read from the observer stdout.
* `early-exit` requires an actual `Popen.poll()` returncode before `BEGIN`.
* `stream-error` records a drain error or stdout EOF before `BEGIN` while the
  process is still alive. EOF alone is **not** an exit-code proof.
* `timeout` means the bounded arm deadline expired while the process was still
  alive.
* `unknown` means no observer handle/observation existed (for example the
  observer was never spawned).

## 5. Fail-closed persistence

For this new code:

* a missing, truncated or failed diagnostic file write cannot produce an
  accepted receipt or a confirmed cleanup;
* if diagnostics are not confirmed, the stage is retained and cleanup is
  unresolved (`persistence-failed`);
* the original failure reason stays the failure reason; the diagnostic capture
  error is a separate field;
* finalization is idempotent. Repeated finalization returns the first result and
  performs no duplicate writes;
* files are created with `O_EXCL`/`O_NOFOLLOW`. A stale or cross-ID
  `process-diagnostics.json` is never overwritten or adopted; it causes the new
  diagnostic persistence to fail closed;
* `PreflightFailure(reason, detail=None, cleanup=None)` may carry the cleanup
  evidence already observed by the raising site. The outer failure handler
  preserves it under `cleanup.raised` (and top-level `cleanupEvidence`) along
  with the original failure reason. In particular,
  `preflight-cleanup-unconfirmed` remains a failed exit `79` run with
  `cleanup.confirmed=false` and a retained stage; it is never a `TypeError`,
  accepted receipt or success.

New receipt/failure records add:

* `diagnosticVersion` (1);
* `processDiagnosticsPath`;
* `processDiagnosticsSha256` (digest of the exact
  `process-diagnostics.json` bytes);
* `diagnostics` (read-only summary);
* on receipts, `diagnosticEvidenceDigests` for the four stream files.

Historical receipts/failures without these fields remain readable and are not
rewritten. The independent preflight verifier only requires its existing named
journals, so the additive fields do not relax any existing check.

## 6. Status and recover

`status --preflight-id` may expose an additive, read-only `diagnostics` summary.
It validates the file's kind/version, `preflightId`, claim digest, manifest and
resource-plan digest before calling it `present`. A cross-ID file is reported as
`cross-id` and is not used as this run's evidence. In addition, status
recomputes the same strict stream/returncode predicate from the document's
primitives and re-reads the four persisted stream files; the stored
`outcome.confirmed=true` flag alone is never sufficient. An older document that
only recorded successful writes is therefore reported `incomplete`, not
present. Status keeps its legacy `completed` / `unknown-outcome` semantics and
exit codes; diagnostics do not create a completed state.

`recover --preflight-id` is unchanged: it handles only the original resource
records, never replays a selfcheck, never invents process exit records and never
reads historical diagnostics to fill a new run. Recovery does not rewrite
diagnostic files.

## 7. Unsupported loss windows

The following are explicitly not recoverable by version 1 and must remain
disclosed:

* a controller hard crash/kernel kill/OOM before `finalize` runs cannot flush
  the already-read bytes; only files written before the crash survive;
* loss of the evidence filesystem, a full disk, or an OS-level I/O error can
  lose or partially retain diagnostics; fail-closed confirmation cannot be
  issued from the lost bytes;
* a child that double-forks, escapes its process group or is reparented outside
  the owned group keeps the existing conservative group safeguards and may
  remain `unknown`;
* the controller deliberately does not spawn `bpftrace --version`, so the
  observed binary version is not re-probed; only the resolved path and the
  sealed declared version are recorded;
* failures before the claim creates the evidence directory have no writable
  location for diagnostics; they keep the existing conservative
  `unknown-outcome` behavior and produce no diagnostic artifact;
* diagnostics are not evidence of a successful observer arm, a valid
  observation, a formal target, an admission or R3 readiness.

## 8. Test coverage summary

The version-1 suite uses harmless local Python child processes for real
exit-code/drain behavior and recorded Docker/bpftrace shims for controller
integration. It covers compile-error stderr plus exit `2` before `BEGIN`,
identity-journal failure after spawn, EOF while alive, readiness timeout then
deliberate cleanup, cancellation, successful stdout/raw separation, >256 KiB
truncation, stream read failure, diagnostic write/fsync failure, stale/cross-ID
files, repeated finalization, unknown returncodes, pre-cleanup poll vs deliberate
signal, zero forbidden signal/resource/spawn calls during finalization,
read-only status, recover non-replay and stage retention with the original
reason preserved. A separate focused repair suite adds unfinished stdout/stderr,
EOF with an alive child, known-vs-unknown codes, a negative signal, normal
complete capture, read/truncation/write failure with exact reasons and artifact
state, repeated finalization, the constructor plus a controller
cleanup-unconfirmed failure path, and parser/simulation coverage of the scalar
`@events` counter and END grammar for `0`, `1`, `4` and an over-budget stream
(which remains invalid under the unchanged `MAX_EVENTS=4`). No real Docker,
bpftrace, fixture, target, preflight, tqdm, NLTK or admission is used.
