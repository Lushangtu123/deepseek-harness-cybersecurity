Reviewed the new scan-required guard and five controller tests. No confirmed safety blocker or reproducible scope regression in the changed area.

Confirmed:
- `execute(..., _operation='review', scan_path=None)` rejects before `verify`, `inputs`, storage reservation, or attempt creation.
- `locations()` is the remaining `None` path; `inputs` constructs the empty scan/narrowed manifest and preserves any supplied `locationBinding`.
- Formal review recomputes the location binding, fails on drift without committing `result`, and emits v3 `reviewArtifact` from payload bytes.
- Tests cover the guard, locations sandbox flags/receipt/recover-no-replay, binding drift, invalid inventory mutations, stale supplied binding, UTF-8 continuation rejection, and digest failure before task creation.

Conservative limitations / test-quality gaps, not blockers:
- The scan guard is exercised at API level only; CLI `run` already requires `scan_path`.
- The exact-byte reviewArtifact assertion uses `Path.read_text()`, which applies universal-newline translation. It does not strictly prove byte preservation for CRLF input; comparing `read_bytes().decode('utf-8')` would. The code path itself preserves raw bytes.
- The UTF-8 test mutates only `call.start`; `call.end` continuation handling is not directly covered.
- These are synthetic controller tests with the acknowledged mutable helper/synthetic backend; VM/Docker/live acceptance remains pending.

Call-ID semantics not reopened. No R3 or live acceptance claimed.
