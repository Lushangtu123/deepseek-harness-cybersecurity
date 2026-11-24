**Verdict:** The supplied evidence is internally consistent: 197 synthetic tests (87+29+27+45+9), current source hashes match for the listed overlapping files, the archive transaction/restore record is coherent, and the cleanup script checks owned containers/clients before deleting scratch. I found **no concrete code-execution safety blocker** in the supplied storage/archive path, and no evidence of container/client residue, file chown, or `_cleanup`/`rm` in archive. This is not R3 or live acceptance.

**Material acceptance-evidence limitations / claim-level defects:**

1. **`noNewAnalysisReceipt` is hardcoded, not tested.**
   `storage-live.py` prints `"noNewAnalysisReceipt": True` as a constant. It does not scan for or assert absence of a new analysis receipt. `api.recover()` returning `restore-required-no-analysis` is a recovery instruction, not proof that no receipt was created. This is safety-relevant, so the claim is not established by the 197-run as written.

2. **`rootCid.contentMatched` is hardcoded; mode 0644 is observed but not asserted.**
   The script asserts `container.cid` is uid 0, nlink 1, readable, and includes its hash in `original`; it does **not** assert `mode == 0o644` and does **not** compare CID bytes to the record’s `containerId`. The output prints `contentMatched: True` unconditionally. The final JSON shows mode `420` (0644), but a mode regression would not fail this acceptance script unless mode is asserted. Call this a concrete evidence gap, not a demonstrated unsafe artifact.

3. **Duplicate `archive_apply` is under-asserted.**
   `again=s.archive_apply(policy,plan,...)` only checks `again['entries'][0]['state']=='committed'` and that logs in the original `queryDirectory` are unchanged. It does not assert the duplicate returns the **same transaction id**, same archive/recycle paths, or that no new transaction/archive was created. A newly committed transaction could still pass this check while writing new query logs elsewhere. The duplicate-query idempotency claim is therefore weaker than stated.

4. **Daily config-pin/runtime preservation is partly hardcoded and depends on unmanifested identity code.**
   `worker.py` asserts `identity()==before` and reports `len(before['program'])` / `len(before['databases'])`, which supports the 169/42 stability claim. But it records `dailyConfigPinsRuntimeMatched: True` as a constant, not as an exposed compared field. The `identityCode` is extracted from `stage-guest.py`, which is not in the supplied current-source manifest. Its executed bytes are bound by `inputSha256`, but its semantics are not independently reviewed here. So the 169/42 result is supported; the config-pin/runtime part is not fully demonstrated by the supplied script evidence.

**Conservative limitations, not blockers:** the storage acceptance is synthetic, has zero independent R3 samples, and does not extend to daily deployment or full-product audit. The cleanup path uses elevation only for read-only Docker queries and no file-read chown/sudo; that matches the stated scope.
