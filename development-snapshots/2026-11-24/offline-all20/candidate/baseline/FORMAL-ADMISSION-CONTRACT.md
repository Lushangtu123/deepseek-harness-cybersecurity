# Formal Admission Contract (offline source candidate)

Status: `pending-codex-review`, `offline-only`.
Protocol revision: **3** (unchanged; no version bump is used as a fix).
Formal targets: **0/16**. Real containers/observers/selfchecks: **0**.
R3: **blocked**. No admission, license, claim or runtime receipt is authored by
this candidate.

This contract is additive to `BUFFER-V2-CONTRACT.md`, `END-LF-CONTRACT.md`,
`BUFFER-PREFLIGHT-CONTRACT.md`, `DIAGNOSTICS-CONTRACT.md` and
`REPAIR-CONTRACT.md`. Where the old formal runner/judge path selected legacy
observation, this document is authoritative.

## 1. Formal observation identity

Formal admission uses exactly:

| Item | Value |
| --- | --- |
| `observationProtocol` | `buffer-v2` |
| `framingPolicy` | `end-lf-padding-v1` |
| parser | existing frozen `tools/buffer_protocol_v2.py` |
| template | existing frozen `tools/observer_template_buffer_v2.bt` |

The identity carried through admission, preparation, layout, binding, compile,
attempt, capture and verification is derived from the **actual verified
preflight buffer template and its real bytes/hashes**:

- `bufferParserSha256` is the SHA-256 of the actual candidate
  `tools/buffer_protocol_v2.py`;
- `bufferTemplateSha256` / `frozenTemplateSha256` are the SHA-256 of the actual
  candidate `tools/observer_template_buffer_v2.bt` and of the verified preflight
  `frozenTemplateBytes` bundle entry;
- the rendered preflight `observer.bt` is diagnostic only; it is never used as
  the formal template link;
- `receipt.toolDigests["observer_template.bt"]` is never used as the formal
  template link.

`observer_render.render` renders the attempt observer from those pinned v2
template bytes and the verified preflight layout bytes. There is no content
sniffing and no legacy fallback. A missing marker, a legacy template, a parser
hash mismatch or a framing mismatch fails closed before any formal judgment.

Historical legacy artifacts remain readable as diagnostic data. They are not
promoted to a formal receipt and cannot satisfy a new-source verification.

## 2. Resource-plan ordering and journals

`prepareId` is tool-generated: exactly 32 lowercase hexadecimal characters.

A resource plan is written with `O_EXCL` semantics, flushed and `fsync`ed
**before** the stage directory, config file, container or process is created.
The plan journals at least:

- `prepareId`, `operationRole`/`role`, `attempt` (when applicable);
- the stage planned path and stage state/identity;
- the random 16-hex tag and derived container name;
- the fixed image id;
- mount destinations/sources and env keys;
- the per-process spawn state (`not-started`, `spawn-attempted`, `started`,
  `unknown`);
- the container state (`not-created`, `create-attempted`, `created`,
  `create-unknown`, `create-failed-cleaned`).

After creation the actual container identity is retained in the operation's
outer frame **before** any identity journal write. The same applies to the
spawned client/observer identity. A failed identity journal therefore leaves an
ambiguous state, not a claimed absence.

Ambiguous create or spawn is `unknown`. It is never recorded as `not-started`.
A create attempt is only converted to `never-created` after a fresh, successful
name and tag query proves it.

Preparation (layout/bind/compile) may record a resource reservation but does not
consume the target attempt counter. The target attempt counter is made durable
**before** target resource creation. Attempted and unknown target slots remain
spent; no path refunds a slot.

## 3. CLI selectors and locking

`query`, `recover` and `cleanup` accept exactly one of:

- the preserved `--attempt <n>` selector; or
- the new `--prepare-id <32 lowercase hex>` selector.

Both selectors together, or neither, are rejected by the CLI (exit 2).
Malformed/unsafe ids and cross-record role/tag/name/image/path/identity
mismatches are rejected with exit 78 **before** any signal or deletion.

`status` is read-only and includes preparation plan summaries. Mutations
(`run`, `prepare-*`, `compile`, `recover`, `cleanup`) use the same stable
exclusive batch lock; a busy lock is exit 79. Query/status do not take the
mutation lock.

Recovery queries and cleans the original recorded ids/resources. It never
reruns compile, bind, selfcheck or target. Repeating recovery is idempotent and
reports `replayed: false`.

## 4. Cleanup

Cleanup may delete only after:

1. validated ownership of the plan/attempt record;
2. a successful fresh container ID query, name query and tag query that prove
   absence or prove our exact recorded identity;
3. process-group exit proofs for the original client and observer identities,
   or a persisted `not-started` spawn proof.

A permission error, stat error, query failure, unreadable identity or identity
contradiction stays `unknown`. Only `FileNotFoundError` proves a path absent.

Stage handling happens **after** resource handling on every path, including
initially absent/never-created stages. A stage is deleted only after the
container/process proofs; the final `lstat` is still the last operation. A stage
that reappears, is a link, has a dev/ino mismatch, raises an lstat error, fails
deletion or is still present cannot produce success.

`cleanup-unconfirmed` retains the intent/journal/log evidence, retained stage
files where resource proofs are missing, and the reservation. No reservation is
released and no success is recorded unless resource exit + stage final absence +
a durable final journal all succeed. Target attempt counts are never refunded.

## 5. Judge

The judge is fail-closed and reads the **full actual raw bytes**. It never uses
stored events, a stored `confirmed`/`decision` value, target stdout or model
output as the semantic evidence.

It independently parses the raw stream with `buffer_protocol_v2.parse_receipt`
and requires:

- exactly one complete `BEGIN`, exactly one complete `END` and the v2 marker;
- the declared event count equals the parsed event count;
- exact run id, tag, caller path, call offset, target pid/uid;
- complete payload records and parser fields;
- the full raw SHA-256 and byte length, including the normal END LF and 0..8
  additional LF bytes; 9+ extra LF bytes are invalid;
- no truncation, forced stop, drain-incomplete marker or trailing record.

It strictly compares the canonical parser fields with the stored observation
(types included, so `bool` is never accepted as `int`). It may check
collector-added wrapper fields separately; it never requires arbitrary
dictionary equality of unrelated diagnostics.

The semantic verdict is derived from the **recomputed** events. A stale stored
event, re-signed stored hash, forged confirmed flag, wrong point/caller/offset,
missing evidence, digest mismatch, `payload=None`, bad protocol/framing policy,
unsupported/truncated raw or malformed nested input yields a clear
`unknown`/`invalid` result and exit 3 instead of an unhandled exception or a
false confirmation.

Q4 (`syntax-reject`) remains excluded only when the trusted compiler proves a
real `SyntaxError`, the target actually exited 3, the stream is complete and
zero events were observed. No ordinary zero-event trace becomes a syntax
rejection.

## 6. Exit-code conventions

| Condition | Code |
| --- | --- |
| semantic confirmed / excluded with confirmed cleanup | 0 |
| semantic unknown, or cleanup unconfirmed | 3 |
| invalid ownership / unsafe or contradictory identity | 78 |
| batch lock busy | 79 |
| malformed CLI selector | argparse / 2 |

## 7. Compatibility and known gaps

- The pure legacy parser/collector behavior is unchanged for explicitly chosen
  diagnostic protocols. The formal path no longer chooses that protocol.
- Historical shim fixtures that asserted a legacy formal protocol were migrated
  to explicit v2; their old results are preserved as history, not rewritten.
- This candidate contains source and SIMULATED/recorded-shim tests only. There
  is no real Docker/bpftrace/preflight/selfcheck execution and no runtime
  receipt. Source review and new-source selfcheck remain pending. The historical
  successful preflight `0398591de290462b8a6e3f4ec4ff2cbc` is not evidence for
  this manifest.
