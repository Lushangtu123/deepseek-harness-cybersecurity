# Strict buffer-v2 zero-target preflight contract

Status: **prepared-not-executed / pending Codex source and external review**.
`protocolRevision` remains **3**. `R3` remains **blocked**. Formal targets remain
**0 / 16**. Selfcheck executions are **0 / 1**. The implementer ran no real
Docker container, bpftrace attachment, observer, target, selfcheck, compiler,
sudo, fixture, deployment or git push. All controller tests use the controlled
`checks/shims` or in-process fakes, and every sandbox is under `checks/`.

This document is a source/contract file and is included in
`protocol-manifest.json`. It makes no admission, selfcheck-success or
runtime-observation claim.

## 1. Frozen boundary and actual baseline

| item | requirement |
| --- | --- |
| `baseline/` | frozen 54-file buffer-v1 preflight candidate, exact original bytes |
| baseline manifest | `1c0a196fbacddd91fc3a42429090c47ac4003999550c738fa69c910d9abd9f8e` |
| baseline file count | 54 |
| `baseline/proof/` and `proof/` | read-only source-gap/counterexample records, excluded from the runtime closure |
| `source-evidence/` | pinned upstream source data only, never loaded at runtime |
| `tools/buffer_protocol.py` | unchanged v1 parser, raw-v1 tests retained |
| `tools/observer_template_buffer.bt` | unchanged v1 template |
| `tools/observation_pure.py` | unchanged |
| `tools/structure.py` | unchanged |
| `tools/observer_render.py` | unchanged |
| `tools/observer_template.bt` | unchanged, still the historical/formal legacy template |
| `tools/preflight_selfcheck.py` | unchanged, exactly one `eval("0")` |
| `tools/judge.py` | unchanged |
| `experiment-plan.json` | unchanged |
| four fixtures | unchanged |

The actual 54-file baseline manifest is recomputed by
`checks/verify_baseline.py`; it is the comparison tree in this root. No claim is
made that any baseline test execution preceded the old v1 development. The old
candidate's historical documents and proof are preserved, not relabelled.

The new source files are `tools/buffer_protocol_v2.py` and
`tools/observer_template_buffer_v2.bt`. The new template is derived from
`tools/observer_template_buffer.bt` with only:

1. the explicit `BUFFER-PROTOCOL buffer-v1` marker changed to
   `BUFFER-PROTOCOL buffer-v2` in the single `BEGIN` printf;
2. documented comments naming the variant changed from v1 to v2, plus a short
   derivation comment near the header.

The `%rh` body, all five bounded buffer reads, bytes/count/string bounds, four
mandatory count records, integer-zero branches, `None` handling, pid/uid/
path/offset filters, unsupported reasons, `DCODE`, `EVENT`, and the graceful
`END` map clear are unchanged. There is no source-specific hardcoding and no
runtime PID/path pasted from a previous candidate.

## 2. Upstream formatter call chain

Pinned upstream data (not runtime-loaded):

* `source-evidence/bpftrace-v0.20.2-utils.cpp`
  SHA-256 `19aa0d15c911b1aa78ae3a363a021f6f5aca0243d7401f8a1d689a85e5f0c778`,
  commit `b0f7f14abfa83ec08d68e0558391f7529d9d84a5`, tag `v0.20.2`;
* `source-evidence/format_string.cpp` and `source-evidence/printf.cpp`.

`format_string.cpp` handles `%rh` by setting
`PrintableBuffer::keep_ascii(false)` and
`PrintableBuffer::escape_hex(false)`. `printf.cpp` passes both flags to
`hex_format_buffer(value_.data(), value_.size(), keep_ascii_, escape_hex_)`.
The pinned loop emits `%02x` for each byte and `"%02x "` for every byte except
the last. Therefore `%rh` output is lower-case byte pairs separated by exactly
one ASCII space, with no trailing space:

```text
QUALB 4 5f 72 75 6e          # "_run" golden, manually checked
QUALB 4 65 76 61 6c          # "eval"
QUALB 0 -                    # empty record token, no memory read
QUALB 1 00                   # one NUL byte
```

The tests port that loop independently and assert both flags: `%rh` emits
`5f 72 75 6e`; `%rx` emits `\x5f\x72\x75\x6e`; `%r` keeps printable ASCII.
The controlled shim has its own `format_rh()` implementation and never queries
the parser under test.

## 3. buffer-v2 parser

`tools/buffer_protocol_v2.py` imports only the fixed trusted siblings:

```text
import observation_pure as _legacy
import structure
```

It has the public `parse_receipt(...)` interface and the canonical
`dynstruct-v1` event/hash shape of the legacy/v1 parsers. `PROTOCOL` is
`buffer-v2`; `MARKER` is `BUFFER-PROTOCOL buffer-v2`; `targetExecuted` is always
`False` and `targetSelfReportUsed` is always `False`. `rawSha256` and
`rawBytes` always describe the actual supplied v2 stream; no v1 stream is
translated and presented as a v2 observation.

Grammar:

```text
BEGIN run=<id> tag=<tag>
BUFFER-PROTOCOL buffer-v2
EVENT <7 integers>
DCONSTN <count> / DNAMEN <count> / KCONSTN <count> / KNAMEN <count>
DCODE <i> <bytehex>
DCONST <i> n|?|i <negative> <digit>
DCONSTB <i> <length> <payload>
DNAMEB <i> <length> <payload>
QUALB <length> <payload>
KCONST <i> n|?|i <negative> <digit>
KCONSTB <i> <length> <payload>
KNAMEB <i> <length> <payload>
UNSUPPORTED <reason>
END run=<id> tag=<tag> events=<count>
```

For a non-empty payload there are exactly `<length>` tokens, each matching
`[0-9a-f]{2}`, joined by exactly one ASCII space. The parser rejects, without
stripping, coercion, sniffing or fallback:

* leading/trailing/doubled payload spaces, tabs, CR/LF controls, blank lines;
* contiguous multi-byte hex, odd/partial pairs, uppercase, `0x`, non-pair text;
* missing or extra tokens and a token count that differs from `<length>`;
* `-` for non-zero length and any non-`-` zero-length token (empty is exactly
  one `-`);
* missing/duplicate/out-of-range `*N` counts, missing/duplicate/gapped/
  out-of-range map indexes and count/index coverage mismatch;
* wrong/missing/duplicate/misplaced marker; wrong/missing/duplicate/misplaced
  `BEGIN`/`END`; trailing data after `END`; event count mismatch/overflow;
* legacy `*W` records, legacy string headers, unknown opcodes and any
  legacy/v1/v2 mix;
* non-ASCII payload as an invalid receipt, never a `UnicodeDecodeError` leak.

`0..64` bytes are preserved, including ASCII controls, NUL, quotes and
backslash. Integer `0` stays `{"t": "int", "v": 0}` and `None` stays
`{"t": "none"}`. A one-byte payload is wire-compatible with v1, but the required
v2 marker keeps the protocols distinct. The parser also rejects the v1 marker
and the unmodified v1 parser still rejects spaced multi-byte v2 records.

## 4. Explicit collector choice

`tools/collect_observer.py` requires an explicit choice:

```text
--observation-protocol legacy|buffer-v1|buffer-v2
```

* `legacy` selects frozen `observation_pure.py`;
* `buffer-v1` selects the retained `buffer_protocol.py` (diagnostic reading
  only; it is not selected by the new preflight);
* `buffer-v2` selects `buffer_protocol_v2.py`;
* an omitted or unknown choice is an argparse usage error;
* a wrong choice produces an invalid receipt and non-zero exit; there is no
  content sniffing or fallback.

The formal/historical runner keeps passing `legacy` explicitly and rendering
the unchanged legacy template. The new zero-target preflight passes
`buffer-v2` explicitly and renders `observer_template_buffer_v2.bt`.

## 5. Preflight binding

New licenses, claims, resource contexts, intents, completed markers, observation
captures and receipts bind:

```text
observationProtocol  = "buffer-v2"
bufferParserSha256   = actual tools/buffer_protocol_v2.py digest
bufferTemplateSha256 = actual tools/observer_template_buffer_v2.bt digest
frozenTemplateName   = "observer_template_buffer_v2.bt"
frozenTemplateSha256 = actual frozen v2 template digest
```

The producer verifies the manifest and computes actual parser/template digests,
then verifies the license **before** acquiring the lock, consuming the claim,
creating evidence, a stage, a container or a process. A license/receipt with
`observationProtocol=buffer-v1`, or with the v1 parser/template digests, is
rejected with exit 78 even if the payload is a single byte. The new verifier
also refuses an old v1 receipt/claim.

Claim-before-evidence, exclusive lock, resource journals, intent-before-create,
identity persistence, unknown identity/exit/drain -> no acceptance, the triple
container-absence query, final stage `lstat` success conditions, graceful
SIGINT/complete END and query/recover-original-only are preserved. There are no
unrelated exitcode, ledger or recovery changes.

## 6. Independent verification and GO

Both the producer and `preflight_verify.py`:

1. read the original `preflight/evidence/<id>/observer.raw` bytes;
2. invoke the actual frozen `buffer_protocol_v2.parse_receipt` (never a stored
   `complete`/`accepted` boolean);
3. require one event, the bound tag/caller offset, integer zero, the v2
   protocol and exactly one v1-free marker, `BEGIN` and `END`;
4. recompute `dynamicStructureSha256`, `dynamicCodeSha256` and `callerSha256`
   from the normalized event objects and compare them with the frozen config;
5. render the actual `observer.bt` from the exact frozen v2 template, layout
   bytes, profile digest, run/tag/caller/offset and target pid/uid, then require
   exact byte equality.

A modified raw stream, a modified stored `observation.json`, a modified
`observer.bt` with an updated stored observer digest, a changed parser/template
file, or a changed receipt digest is not accepted. A simultaneous observer-byte
and stored-hash change is caught by the deterministic rebuild.

`status --preflight-id` and `recover --preflight-id` query the original ID only,
do not replay the selfcheck or target, do not rewrite old evidence and never
report a real-machine pass. A historical v1/legacy record may be read but is not
promoted or relabelled as v2 acceptance.

## 7. TDD / RED and changed-test record

The first focused RED run was executed on the real old interfaces before
implementation: the unmodified v1 parser rejected spaced `QUALB` with
`qualb-shape`, the old collector rejected `--observation-protocol buffer-v2`
(argparse rc 2, valid choices `legacy`, `buffer-v1`), and the old verifier
selected `buffer-v1`. The initial RED directory is preserved as-is. It also
contained two test-harness mistakes (an incorrect `%r` nonprintable expectation
and a v1 stream builder that spaced every payload); the corrected RED run was
executed before implementation and is preserved separately. Neither RED run
was overwritten.

Changed original focused entries (all edit bytes are in the final manifest):

| original entry | change |
| --- | --- |
| `candidate-sibling-imports-and-frozen-legacy-bytes` | now loads v2, additionally asserts v1 parser and v1 buffer-template bytes equal baseline |
| `five-string-classes-lengths-0-1-63-64-accepted` | streams use v2 spaced pairs; entry expects `buffer-v2` |
| `five-string-classes-length-65-refused` | streams use v2 spaced pairs |
| `nonascii-payload-invalid-not-exception` | streams use v2 spaced pairs |
| `ascii-specials-and-zero-vs-none-preserved` | streams use v2 spaced pairs |
| `count-records-are-mandatory-and-cover-indexes` | streams use v2 spaced pairs |
| `malformed-lengths-hex-dash-and-duplicates-refused` | v2 spaced baseline and duplicate lookup; old compact-malformed cases retained as rejects |
| `truncation-markers-and-begin-end-attribution` | v2 marker; `buffer-v1` marker is the explicit invalid-marker control |
| `legacy-buffer-mix-and-legacy-parser-boundary` | v2 spaced stream; v1 parser still rejects it |
| `collector-explicit-protocol-no-sniff-or-fallback` | v2 is the selected candidate; legacy remains explicit |
| `parameterized-buffer-template-preserves-old-bytes-and-fields` | compares v2 template body; asserts v1 template bytes are unchanged |
| `preflight-refuses-missing-wrong-protocol-or-digests-before-resources` | adds v1 protocol, v1 parser digest and v1 template digest rejects |
| `preflight-synthetic-buffer-v1-accepted-and-verifier-recomputes` | renamed `...-buffer-v2-...`; expects v2 capture/receipt/rebuild |
| `verifier-rejects-modified-raw-observation-and-observer-rebuild` | unchanged logic, v2 preflight |
| `verifier-rejects-receipt-parser-and-template-digest-mismatch` | unchanged logic with v2 actual digests |
| `legacy-and-downgraded-records-are-not-admitted-as-buffer-preflight` | restores v2 after rejecting `legacy` and `buffer-v1` |
| `strict-exitcode-types-rejected-unknown-null-preserved` | unchanged logic, v2 preflight |
| `recovery-and-status-query-original-id-without-replay` | expects v2 claim/status |
| `go-waits-for-buffer-marker-and-does-not-run-on-early-begin` | withholds the v2 marker |

New focused entries cover the independent formatter/flags, strict spacing for
all five records, count/index gaps and duplicates, ASCII controls/NUL/quotes/
backslash, v1/v2 single-byte marker separation, equivalent legacy/v1/v2
canonical hashes with truthful distinct raw hashes, frozen-helper normalization,
unsupported/trailing/duplicate BEGIN rules, explicit v1 collector diagnostics,
and actual parser/template file tampering. The final focused suite has 29
entries and is recorded in the evidence index.

Explicit v1 raw parser tests are retained: contiguous v1 records still complete
under `buffer_protocol.py`; spaced v1 records still fail with `qualb-shape` (or
the earlier record-specific shape when another class is spaced first). The v1
parser/template bytes are checked against `baseline/tools/` in the focused suite.

One post-implementation diagnostics run was executed in parallel with four other
suites and observed a scheduling-delayed SIGINT in a fixed 3-second wait; that
raw failure is preserved and was followed by a sequential 20/20 pass. It is not
a product-state change.

## 8. Manifest, evidence and pending gates

The final manifest contains the new parser, template, tests, this contract and
the fixed source references by hash. `baseline/`, `proof/`, `source-evidence/`,
`REPORT.md`, `phase-result.json`, evidence runs and this evidence index are not
runtime closure entries; source-evidence is data-only and never imported.
`observer_render.py`, `observation_pure.py`, `structure.py`,
`preflight_selfcheck.py`, `judge.py`, both old templates and the v1 parser remain
byte-identical to their baseline copies.

The following remain **not claimed**:

* real buffer-v2 runtime observation support;
* a successful selfcheck execution (**0 / 1**);
* any formal target (**0 / 16**);
* `R3` acceptance (**blocked**);
* an approval, admission, license, completed claim or real-machine pass.

Codex may later admit exactly one fixed `eval("0")` selfcheck and zero formal
fixtures after independent source review and external review. The implementer
minted no approval, admission or license and did not run the selfcheck.
