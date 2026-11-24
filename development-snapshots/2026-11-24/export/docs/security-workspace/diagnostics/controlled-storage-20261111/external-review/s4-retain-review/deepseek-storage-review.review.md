No remaining blocker in the added result-digest/source-rehash guard itself. The ordering is correct: local `vm-result-final.json` is bound to `poll['resultSha256']`; remote `status.resultSha256` and raw `result.json` bytes are checked against the same `RESULT` before `json.loads`; only then are `sourceSha256` entries rehashed. Mismatch, missing source, or drift fails closed. That closes the prior “trust source map without rehash” defect.

Conservative limitations, not new blockers under the stated assumptions: host-side `meta`/`poll`/local result files are trusted as pinned; no external anchor or arbitrary same-UID immutability; source-map path confinement/coverage is not asserted; no R3, physical-power-loss, or full-product claim.

Two scoped non-digest issues in the exact script:
1. `vm-finish-script-final.txt` is written before `if (root/'vm-retained-r2.json').exists()`, so a rerun after reconciliation overwrites that artifact before raising “Already reconciled.” Move the existence check before the write to keep rerun read-only. This is an evidence-mutation/idempotency defect, not a bypass of the digest guard.
2. The displayed summary is not literal output of either print: the remote print includes `record` state inside `attemptRecords`; the host final print omits `attemptRecords` entirely. If the shown JSON is a redacted summary, fine; otherwise confirm `vm-retained-r2.json` retains the full `record` object.

So: digest guard = no remaining blocker for the prior defect; rerun write-order = concrete adjacent evidence-integrity defect.
