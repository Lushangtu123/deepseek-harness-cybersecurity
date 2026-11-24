**Corrections verified.** `validate_locations` checks staged-source SHA/byte length/state/points, point IDs, duplicate IDs, nondecreasing call offsets, argument containment, and exact byte line/column. The UTF-8 boundary check is sound because source bytes have already passed `raw.decode('utf-8')`; any non-continuation offset is a code-point boundary. `reviewArtifact` is populated from `payload` bytes, not re-parsed JSON, and `reportJson` matches the receipt hash. No production/live claim.

**Confirmed scoped defects / regressions**

1. **Point ID does not bind `argument`.** The canonical ID digest covers only `sourceSha256`, `callee`, and `call`. A VM report can change `argument.start`/`argument.end` inside the call span and keep the same ID; `validate_locations` accepts it. Repro: alter argument offsets within `call`, leave `id` unchanged. If `argument` is part of the location point identity, this contradicts “canonical point IDs.” Within the stated VM trust boundary this is an **integrity/evidence defect, not a VM-boundary safety blocker**; fix by including the argument span in the digest or explicitly documenting ID as call-site-only.

2. **`reviewArtifact.manifestJson` is not always exact original manifest bytes.** When `scan_path is None`, `inputs()` reconstructs `manifest_raw` as `{files, scanSha256, locationBinding?}`, dropping other fields and formatting. A v3 review invoked without a scan file would expose that normalized manifest as `reviewArtifact.manifestJson`, not the original supplied manifest. The test only covers supplied `scan_path`, so the “exact original manifestJson” claim is overbroad. This is a **scope regression**; require `scan_path` for v3 review artifact capture or narrow the claim.

3. **Test gap: named “mid-utf8” case is not a UTF-8 endpoint test.** It sets `col=999`, i.e. wrong coordinate. No test exercises a continuation-byte offset or argument-ID mutation. The endpoint logic appears correct, so this is **coverage limitation**, not a confirmed code defect.

4. **Test-scope regression:** `reviewer_locations.test.py` imports `eval_evidence_batch` from `work/harness-purge-improved/package/scripts`, a mutable workspace path, not the pinned snapshot. Tests can pass against different `location_inventory` behavior. Test-only limitation.

Minor permissive behavior—equal call-start offsets and extra row/reason keys—is conservative/acceptable unless strict canonical inventory is required.

**Conclusion:** No confirmed safety blocker in the reviewed corrections. Items 1–2 are concrete scoped integrity/evidence defects; 3–4 are test limitations.
