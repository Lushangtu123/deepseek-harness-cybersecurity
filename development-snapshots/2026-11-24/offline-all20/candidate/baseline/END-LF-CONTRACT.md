# Bounded END-LF framing contract (`end-lf-padding-v1`)

Status: **prepared-not-executed / pending Codex source and external review**.
`protocolRevision` remains **3**.  `observationProtocol` remains **buffer-v2**.
The framing policy is the single tool-fixed value **`end-lf-padding-v1`**.
`R3` remains **blocked**; formal targets remain **0 / 16**; new selfcheck
executions remain **0 / 1**.  This document and its manifest are source only.

## 1. Fixed baseline, historical failure and raw diagnostic

| item | value |
| --- | --- |
| `baseline/` | exact original 58-file candidate, read-only |
| baseline manifest | `68471bf7e3d75ca4668870365e3833179620757ac0481742c4b16a5fe307f1e4` |
| baseline file count / bytes | 58 / 1,136,311 |
| historical raw | `proof/observer.raw` |
| historical raw bytes | **306** |
| historical raw SHA-256 | `5e61c6b689cf4e31905fb6e2863648a0c1d0376446d8dc237189b9cc8627806b` |
| historical preflight | `c58ce185e8804901b0abae8510f8d081`, failed, slot consumed |
| historical failure | collector exit 3 / preflight exit 79, `ParseError:blank-line` at one-based line 18 |

The 306-byte file is the real original stream, not a cleaned copy.  It ends
with `END ... events=1\n\n\n\n`: the normal END LF plus **three** additional
LF bytes.  It remains bound to its original caller, tag, PID/UID and expected
canonical hashes in `proof/`.  This contract uses it **only as historical
diagnostic data**.  Parsing it under the new policy does not create a new
post-freeze execution receipt, does not complete the old preflight, and does
not relabel the old run as successful.  The old preflight and its consumed slot
remain failed.  The prior 303-byte in-memory diagnosis copy is not used as a
fixture and was never accepted evidence.

## 2. Policy

The one valid `END` record must have its normal LF terminator.  After that
terminator the stream may contain **0 through 8 additional LF bytes** and
nothing else.  `trailingBlankLines` is exactly the number of additional LF
bytes beyond the normal END terminator (`0..8`).

Accepted:

```text
END run=... tag=... events=1\n            # trailingBlankLines = 0
END run=... tag=... events=1\n\n           # 1
END run=... tag=... events=1\n\n\n\n       # 3 (historical original)
END run=... tag=... events=1\n  ... 8 LF   # 8
```

Rejected:

* 9 or more additional LF bytes (`trailing-lf-overflow`);
* no final LF after END (`end-unterminated`);
* a blank line before BEGIN, between BEGIN/marker/records, or before END
  (`ParseError:blank-line`);
* spaces, TAB or CR in the trailer or on a line (`line-spacing` /
  `line-control`);
* a non-LF nonempty trailer, records after END (`trailing-after-end`), or a
  duplicate END (`end-duplicate`);
* missing END (`end-missing`) and a truncated stream (`raw-truncated`);
* any legacy/mixed record, malformed payload token or spacing, missing/
  duplicate/gapped counts or indexes, identity/tag mismatch, event-count
  mismatch, or non-ASCII payload, with the existing rejection reasons.

The rule is bounded framing, not content sanitation.  The implementation does
not call `.strip()` or `.rstrip()` on the whole evidence.  It does not drop
arbitrary empty lines.  The trailer is classified only after the unique END and
declared event count are checked.

## 3. Parser metadata and truthfulness

`tools/buffer_protocol_v2.py` exposes:

```text
FRAMING_POLICY = "end-lf-padding-v1"
MAX_TRAILING_BLANK_LINES = 8
```

`parse_output`/`parse_receipt` report `framingPolicy` and `trailingBlankLines`.
`rawBytes` and `rawSha256` always cover the **entire original supplied stream**,
including permitted LF padding.  Semantic event objects and their
`dynamicStructureSha256`, `dynamicCodeSha256` and `callerSha256` are unchanged
by padding.  `targetExecuted` and `targetSelfReportUsed` remain `False`.
Passing any other `framing_policy` value returns invalid with
`["framing-policy"]`.  There is no sniffing, fallback or project-selected rule.

Historical 306-byte diagnostic comparison under the new policy:

| property | result |
| --- | --- |
| state | `complete` |
| errors | `[]` |
| `rawBytes` / `rawSha256` | `306` / `5e61c6b689cf4e31905fb6e2863648a0c1d0376446d8dc237189b9cc8627806b` |
| `trailingBlankLines` | `3` |
| `dynamicStructureSha256` | `daa75692969ee231c422d100d6e347d01b8543ab75fff5d08322ff1d8943fc5c` |
| `dynamicCodeSha256` | `59fbf27117957f3b933508fb2670f31f9c6b2bc56f93e1b71367abb7e31df898` |
| `callerSha256` | `24484cc8305b002a8fcb007e769b717cb6cd622b07e46991611b208b87ed3b65` |
| `targetExecuted` | `False` |

These values are recomputed from the unchanged original bytes in the tests.
They are diagnostic evidence, not a new execution receipt.

## 4. Collector interface

The collector keeps the required explicit protocol choice and adds
`--framing-policy end-lf-padding-v1` for the buffer-v2 path only.

* `buffer-v2` without the flag: invalid, exit 2,
  `framing-policy-missing`, no output written;
* unknown flag value: argparse choice rejection, exit 2, no output written;
* `buffer-v2` with the exact flag: explicit v2 parse, exit 0 only when complete;
* legacy and buffer-v1 keep their old command shape and bytes; supplying the new
  flag to them is rejected as `framing-policy-not-applicable` rather than
  silently ignored.  Omitting it remains the unchanged legacy/v1 path.

The new zero-target preflight passes the policy explicitly.  The formal runner
continues to pass `legacy` explicitly and is unchanged.

## 5. Preflight binding and resource order

New licenses, claims, resource context/intents, completed markers, observation
captures and receipts bind:

```text
observationProtocol = "buffer-v2"
framingPolicy       = "end-lf-padding-v1"   (exact required value)
bufferParserSha256  = actual tools/buffer_protocol_v2.py digest
bufferTemplateSha256= actual tools/observer_template_buffer_v2.bt digest
```

The producer verifies the manifest, computes the actual parser/template
digests, and verifies the license **before** the lock, claim, evidence
directory, stage, container or process.  Missing or wrong `framingPolicy` in
the license is exit 78 and creates no claim/evidence and makes no Docker call.
Claims, completed markers, captures and receipts are also checked for the exact
policy.  Status/recover keep historical read-only semantics: a saved record
without the new field is displayed/queried as historical data, is never
promoted to acceptance, and is never replayed.  Recovery does not require the
new policy because it does not admit an observation.

## 6. Independent reparse

Both `tools/zero_target_preflight.py` and `tools/preflight_verify.py` read the
actual `observer.raw`, invoke the actual frozen `buffer_protocol_v2` parser,
and compare:

* `framingPolicy` and a validated integer `trailingBlankLines` in `0..8`;
* the full raw digest/byte count, including padding;
* the stored observation object (never a stored `complete` boolean);
* the deterministic observer rebuild and all existing caller/structure/code/
  identity/resource/cleanup bindings.

Synthetic tests change receipt policy, padded byte count, raw digest, observer
bytes plus stored observer hash, and frozen-template binding separately.  Each
mutation is rejected; restoring the exact bytes verifies again.  Appending
three LF bytes to an accepted synthetic raw and updating every stored raw
digest is accepted only because the verifier reparses the new actual raw and
recomputes `trailingBlankLines=3`.

## 7. TDD record and changed tests

Before product edits, two unique RED directories were retained and never
overwritten:

* `checks/evidence-runs/20261115T173709Z-23d7795b-end-lf-red/` — first RED.
  It reproduced the old parser rejection of all 306 original bytes
  (`ParseError:blank-line`, unchanged raw hash), and behaviourally failed the
  requested policy/padding/license cases.  It also contained one test-harness
  mistake: the collector case recorded results without asserting them.
* `checks/evidence-runs/20261115T173734Z-4e3d76bc-end-lf-red-corrected/` —
  corrected RED before any product edit.  The collector case now asserts the
  old interface wrongly admitted v2 without a policy and rejected the explicit
  flag.  Real commands, raw stdout/stderr, return codes, source hashes before
  and after, and the fixed proof/baseline hashes are preserved.

No initial environment or timing failure was observed in the final focused
runs.  The earlier buffer-v2 round's parallel 3-second SIGINT timeout is outside
this change and is not claimed as localized here.

Changed test surfaces:

| file | change |
| --- | --- |
| `checks/run_end_lf_checks.py` | new focused framing/admission/reparse suite (13 entries) |
| `checks/run_buffer_preflight_checks.py` | v2 collector helper sends the explicit policy; license fixtures and preflight acceptance bind `framingPolicy`; missing/wrong policy cases added |
| `checks/run_buffer_v2_red.py` | closure license and collector command bind the explicit policy |
| `checks/regression_lib.py` | synthetic license helper binds `framingPolicy` |
| `checks/static_check.py` | actual 58-file baseline constants; framing/collector/preflight/manifest guards |

Existing buffer-v2 payload, spacing, count/index, mixed-protocol, identity,
digest, exit-code, lifecycle and resource behaviour remains asserted.  The only
tail-LF expectation that changed is the newly permitted 0..8 extra LF after the
normal END terminator; arbitrary empty lines elsewhere still fail.

## 8. Manifest, exclusions and remaining limits

`protocol-manifest.json` includes all changed trusted code, `END-LF-CONTRACT.md`
and every changed/new test listed above.  It excludes `baseline/`, `proof/`,
`source-evidence/`, delivery documents, evidence runs, temporary sandboxes and
the manifest itself.  `proof/` and `baseline/` stay read-only.  The historical
raw hash is bound in this contract and in the test constant.

Not claimed:

* a new live selfcheck, preflight acceptance or post-freeze execution receipt;
* any formal target (**0 / 16**), deployment, push or host privilege change;
* that the old failed preflight `c58ce185e8804901b0abae8510f8d081` passed;
* full runtime coverage of every string class/length or detector effect;
* provider-independent or completed external review.

This is offline preparation only.  Codex and external source review remain
pending.  After independent checks, Codex may issue at most one new license for
the same tool-owned `eval("0")` selfcheck; the old 1 / 1 remains spent.  Any
failed or unknown live attempt closes with a gap and no second attempt.
