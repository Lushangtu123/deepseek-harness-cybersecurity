**Verdict:** No confirmed code-execution safety blocker in the supplied VM/storage/archive evidence changes. The run is internally consistent: 197 tests, pinned source hashes, identity category hashes, rootCid mode/content checks, duplicate-transaction identity, and one retained attempt. This is still synthetic evidence only, not R3 or live acceptance.

**Confirmed fixes**
- **rootCid:** `storage-live.py` now asserts uid 0, nlink 1, readability, `mode == 0644`, and compares `container.cid` text to `attempt.json`’s `containerId`; output mode `420` matches. Previous gap fixed.
- **Duplicate apply:** now uses `probe=forbidden_engine` and asserts same transaction id, archive, recycle path, unchanged control-file hashes, and unchanged query logs. Previous gap fixed for the duplicate path.
- **Config/pins/runtime:** `worker.py` computes `dailyConfigPinsRuntimeMatched` from actual before/after identity dicts and exposes per-category before/after hashes. Identity code bytes are included in `sourceSha256`, SHA-pinned, and executed. The 169/42 counts are `len()`-derived, not constants, and actual output supports them.
- **`noNewAnalysisReceipt`:** no longer a constant. It is derived from managed-cache `review-*` IDs, unchanged `attempt.json` bytes, and status result SHA/equality; duplicate/recover use a forbidden engine. This supports “no new managed-cache attempt/receipt,” not a global VM absence.

**Material evidence defect**
`verify-retain.py` does **not** hash-bind `root/result.json`. It checks `vm-result-final.json` against `poll['resultSha256']`, checks `status['resultSha256'] == RESULT`, pins worker/input, then loads `root/result.json` and trusts its `sourceSha256` for the source-drift loop. It never asserts `sha256(result.json bytes) == status['resultSha256']` or equality with `vm-result-final.json`. An altered `result.json`—for example, dropping source entries—could pass this retention script. The earlier poll binding does not cure the standalone retention check. This is an evidence-integrity gap, not a code-execution safety blocker.

**Conservative/material limitations**
- `noNewAnalysisReceipt` is scoped to managed cache attempt IDs plus original record/result state; it does not scan the whole VM for new analysis receipts. The field name overstates scope unless read with that limitation.
- `identity()`’s `runtime` check hashes only `@deepseek-ai/dsh-tools/lib/index.js`, not the full runtime tree. “Runtime matched” is therefore narrow.
- In `storage-live.py`, `before_control` is captured **after** archive, so `sameControlArtifacts` proves duplicate-apply did not change control files; it does not prove archive/restore left all control artifacts unchanged.
- `verify-retain.py` scans `/proc` for the worker but ignores `PermissionError`; an inaccessible active worker would not be detected.
- Identity code is extracted from unmanifested `stage-guest.py`; executed bytes are pinned and supplied, so this is provenance opacity, not unmanifested executed code.

No file chown/removal blocker is shown in these paths. The old finish-vm deletion script was not executed; `verify-retain.py` preserves scratch and marks manual cleanup.
