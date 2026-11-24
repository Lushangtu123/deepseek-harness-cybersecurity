# buffer-v1 zero-target preflight contract

> Historical scope note: in this new root `baseline/` is the actual frozen
> 54-file buffer-v1 candidate, and the active protocol is buffer-v2 in
> `BUFFER-V2-CONTRACT.md`.  This file remains the historical v1 contract.

Status: **prepared-not-executed / pending Codex source and external review**.
`protocolRevision` remains **3**. `R3` remains **blocked**. Formal targets remain
**0 / 16**. The implementer ran no real Docker container, bpftrace attachment,
observer, target, selfcheck, compiler, sudo, fixture, deployment or git push.
All controller tests use controlled `checks/shims` or in-process fakes, and every
sandbox lives under `checks/`.

This document is a source/contract file and is included in
`protocol-manifest.json`. It makes no admission, selfcheck-success or
runtime-observation claim.

## 1. Frozen boundary

| item | requirement |
| --- | --- |
| `baseline/` | frozen 54-file buffer-v1 preflight candidate, exact original bytes (manifest `1c0a196...`) |
| `buffer-reference/` | previous 44-file compile-only candidate, exact original bytes |
| `tools/observation_pure.py` | unchanged |
| `tools/structure.py` | unchanged |
| `tools/observer_render.py` | unchanged |
| `tools/observer_template.bt` | unchanged, still the historical/formal legacy template |
| `tools/preflight_selfcheck.py` | unchanged, exactly one `eval("0")` |
| four fixtures | unchanged |
| `experiment-plan.json` | unchanged |

The reference trees and historical bootstrap evidence are not mounted, copied
into the stage, imported by the collector or rewritten. `protocol-manifest.json`
excludes both reference trees. Their actual digests and counts are recorded in
provenance documents, not duplicated raw bytes.

The new parameterized template is `tools/observer_template_buffer.bt`. It is
produced from the same parameterized placeholder vocabulary as the frozen legacy
template by exactly five whole-string record replacements and four mandatory
count records:

| legacy record | buffer-v1 record |
| --- | --- |
| `DCONSTW` | `DCONSTB` |
| `DNAMEW` | `DNAMEB` |
| `QUALW` | `QUALB` |
| `KCONSTW` | `KCONSTB` |
| `KNAMEW` | `KNAMEB` |

The four count records are `DCONSTN`, `DNAMEN`, `KCONSTN` and `KNAMEN`. The
zero-length branch emits the single `-` token and contains no `buf`/`uptr`
memory read. The non-zero branch emits exactly one
`buf(uptr(pointer), validated_length)` with `%rh`. All original unit/count/string
bounds, the pid/uid filters, caller path and call-offset filters, `DCODE`,
`EVENT`, integer-zero `DCONST/KCONST i 0 0`, `None`, unsupported reasons and
single `BEGIN`/`END` behavior remain.

Both templates use the same unchanged `observer_render.render` function and
placeholder set. Runtime PID/path/tag from the compile-only reference are never
pasted into the parameterized template.

## 2. Parser

`tools/buffer_protocol.py` is the frozen pure parser adapted only at its trusted
sibling imports:

```text
import observation_pure as _legacy
import structure
```

Those resolve to this candidate's frozen `tools/observation_pure.py` and
`tools/structure.py`. No project path, reference tree or `sys.path` insertion is
used.

The parser preserves the frozen grammar and every strict reject:

* missing/duplicate/misplaced/invalid `BEGIN`, `END` or
  `BUFFER-PROTOCOL buffer-v1` marker;
* trailing data after `END`, truncation, event-count mismatch/overflow;
* missing/duplicate/out-of-range count records and count/map index coverage
  mismatch;
* duplicate/missing/gap/out-of-range map indexes;
* wrong/odd/uppercase/non-hex/`0x`/whitespace/extra/truncated payloads;
* `-` for non-zero length or a non-`-` token for zero length;
* non-ASCII payload as an invalid receipt, never a `UnicodeDecodeError` leak;
* legacy `*W` records, legacy string headers, unknown opcodes and any
  buffer/legacy mix.

`parse_receipt` normalizes to the same canonical `dynstruct-v1` event shape and
structure/code/caller hashes as the legacy parser. Integer `0` stays
`{"t": "int", "v": 0}` and `None` stays `{"t": "none"}`. The pure parser sets
`targetExecuted: False` and `targetSelfReportUsed: False`; it never infers
execution from supplied bytes.

## 3. Explicit collector protocol

`tools/collect_observer.py` has a required choice:

```text
--observation-protocol legacy|buffer-v1
```

There is no default, content sniffing or fallback:

* `legacy` calls the frozen `observation_pure.parse_receipt`;
* `buffer-v1` calls the frozen `buffer_protocol.parse_receipt`;
* omitted protocol is an argparse usage error;
* a buffer stream under `legacy`, or a legacy stream under `buffer-v1`, produces
  an invalid receipt and a non-zero collector exit.

The formal/historical runner passes `legacy` explicitly and keeps rendering the
unchanged legacy template. The zero-target preflight passes `buffer-v1`
explicitly and renders `observer_template_buffer.bt`.

## 4. Preflight binding

New preflight licenses, claims, resource contexts, captures and receipts
explicitly bind:

```text
observationProtocol = "buffer-v1"
bufferParserSha256  = actual tools/buffer_protocol.py digest
bufferTemplateSha256= actual tools/observer_template_buffer.bt digest
frozenTemplateName  = "observer_template_buffer.bt"
frozenTemplateSha256= actual frozen buffer template digest
```

The receipt additionally binds the rendered `observerTemplateSha256`, raw
digest/bytes, layout/profile/manifest/review/license/claim digests and the
existing `toolDigests` closure. The `toolDigests` closure includes the buffer
parser, the buffer template, the legacy template, `structure.py`, the profile and
the other fixed tools.

The producer verifies the manifest, then computes the actual parser/template
digests and verifies the license **before** taking the lock, consuming the claim,
creating an evidence directory, stage, container or process. A missing/wrong
`observationProtocol` or a parser/template digest mismatch is rejected with exit
78 and no resource intent/create call.

The claim is still consumed first, the evidence directory second. Locks,
resource journals, identity validation, reservation semantics and the final
`lstat` stage check are unchanged. Recovery reads the original preflight ID only
and never replays the selfcheck or target.

## 5. Independent verification

Both the preflight producer and `preflight_verify`:

1. read the original `preflight/evidence/<id>/observer.raw` bytes;
2. parse them with the actual frozen `buffer_protocol.parse_receipt`, not a
   stored `complete`/`accepted` boolean;
3. require exactly one event, the bound tag/caller offset, integer `0`, the
   buffer protocol and exactly one marker, `BEGIN` and `END`;
4. recompute `dynamicStructureSha256`, `dynamicCodeSha256` and `callerSha256`
   from the normalized event objects and compare them with the frozen config;
5. render the actual `observer.bt` from the actual frozen buffer template,
   bound layout bytes, profile digest, run/tag/caller/offset and target
   pid/uid, then require exact byte equality.

Consequently a modified raw stream, a modified stored `observation.json`, a
modified `observer.bt` with an updated stored observer hash, or a mismatch
between stored and recomputed parser/template digests is not accepted. A
deterministic rebuild is the final observer-byte proof.

`preflight_verify` refuses an old/legacy receipt, a downgraded protocol, or a
claim/license without the new binding. Historical `status` and `recover` remain
readable under their old records without being promoted to a new buffer
acceptance; recovery records keep `receiptAccepted: False`,
`realMachinePass: False`, `selfCheckReplayed: False`, `targetExecutions: 0` and
`fixturesImported: 0`.

## 6. GO readiness

The zero-target preflight does not send `GO` on a bare `BEGIN`. The diagnostics
runtime must observe both:

```text
BEGIN ...
BUFFER-PROTOCOL buffer-v1
```

as exact lines before readiness is recorded and `GO` is sent. If the marker is
withheld, the preflight fails `preflight-observer-not-armed` without an accepted
receipt. Bounded drains and graceful `SIGINT`/complete `END` behavior are
retained; forced stop is never success.

## 7. Strict exit code and unknown state

Acceptance requires actual integer exit codes. Booleans and floats are not
integers even when Python compares them equal to `0` or `1`. This applies to the
collector exit, container create/pid query return codes, persisted target exit
type and diagnostics role codes. A genuinely unknown diagnostics code remains
`null` with `known: false`; it is never coerced to zero.

## 8. Resource behavior

The fixed preflight still owns exactly one container and the fixed tool mount.
It uses the sealed image/profile, no network, read-only root, dropped
capabilities, `no-new-privileges`, memory/pids/tmpfs limits and the target
uid/gid. It proves container absence with the existing triple query, proves the
client/observer groups exited, takes a new final `lstat` of the stage and removes
the identity-checked stage only after those resources are clear. A persist
failure, unknown resource query, unknown identity, forced stop or incomplete
drain cannot become accepted.

No lifecycle cleanup was broadened. Unknown resource/identity/exit/log states
remain unknown. Recovery queries only the original ID and writes a new recovery
record; it does not rewrite an old receipt or claim.

## 9. Pending external gates

The following are deliberately **not** claimed by this preparation:

* real buffer-v1 runtime observation support;
* a successful selfcheck execution;
* any formal target (`0 / 16`);
* `R3` acceptance (`blocked`);
* an admission license, claim completion or real-machine pass.

Codex may later admit exactly one fixed selfcheck and zero formal fixtures after
independent source review and external review. This implementer minted no
approval, license or admission and does not self-certify external review.
