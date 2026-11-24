Scope: changed S2 locations path, v3/dataset/freeze/run verifier, v7 report, and supplied synthetic tests. No tools or execution. No R3/live-acceptance claim.

**Confirmed scoped defects**

1. **Controller can commit a completed v2 locations receipt for a structurally invalid inventory.**  
   In `reviewer_snapshot.py` `execute()`’s version-2 branch, the controller checks only:
   - inventory version/protocol/runtime shape,
   - exact file-name set,
   - each file row is a dict with matching `sha256`.
   
   It does **not** validate/require `bytes`, `state`, `points`, point IDs, spans, or recompute the inventory from source bytes. A fake backend returning correct source digests with `files[path]={"sha256": ...}` gets through to cleanup and a completed receipt3. The gate later rejects it in `bindingValid()`/`freezeLocations()`.  
   Impact: a completed locations attempt can be unusable for freezing; receipt3 is not evidence of a valid location inventory. Because the gate rejects it, I do not classify this as a promotion bypass, but it is a real controller/receipt contract defect. Not covered by the supplied tests.

2. **Locations operation discards any supplied `manifest.locationBinding`.**  
   `inputs()` rewrites the manifest when `scan_path is None` to only `{"files":..., "scanSha256":...}`. Consequently `execute()` reads `locationBinding` from that rewritten manifest and never compares an existing binding during `locations`. Formal `run` with a scan path is unaffected.  
   If locations is generation-only, this is a conservative scope limitation; if it is meant to enforce “drift no completion receipt,” it is a scoped regression.

3. **V3 raw-artifact verification is not fed by the controller’s completed result.**  
   `execute()` returns `reportJson`, `inputFiles`, and hashes, but not `scanJson`, `manifestJson`, or `reviewArtifacts`. The gate’s `artifactBinding()`/`preciseArtifacts()` require raw `scanJson` and `manifestJson` inside `run.reviewArtifacts`; the supplied v3 test constructs those manually. Thus a completed harness attempt alone cannot enter v3 precise verification without external raw-artifact capture. The gate correctly blocks missing artifacts (`review-artifacts-missing`), so this is an integration gap rather than a safety bypass.

**Conservative limitations, not safety blockers**

- `rowBound()` and `preciseArtifacts()` require exactly one matching location batch or review batch per source. Independent overlapping batches with the same source are blocked even if mappings agree.
- V3 `pointId === null` negatives are file-level and require zero points in that file; a negative file cannot also contain any eval/exec point unless it gets a non-null point identity.
- Location inventory generation remains self-attested: the controller does not independently recompute points; the gate validates structure and binds raw artifacts, but this is not publisher authentication.
- The supplied evidence is synthetic. The passing tests do not establish Docker/VM behavior, live artifact capture, or that a production run can assemble the required v3 `reviewArtifacts`.

No confirmed path promotes R3; the gate still reports `r3Qualified:false`, and legacy v2 behavior remains diagnostic-only in the reviewed code.
