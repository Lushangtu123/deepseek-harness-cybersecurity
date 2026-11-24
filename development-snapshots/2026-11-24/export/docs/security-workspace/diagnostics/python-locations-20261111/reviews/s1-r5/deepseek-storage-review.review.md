Confirmed scoped defects:

1. **Guard/plain finding `pointId` is not enforced.** In the v2 `guardEvidence` / `plainStringEvidence` loops, validation checks `validPoint(f.executionPoint, files[f.file])` but not `f.pointId === f.executionPoint.id`. `locationFields()` later drops location fields on mismatch, but the artifact is still pushed and the result is `completed`. Repro: valid `executionPoint`, matching result, correct observation/lines, forged `f.pointId='f'.repeat(64)` → completed artifact without location identity. This should degrade to `unavailable`. Tests cover forged `findingLocations` IDs only, not guard/plain finding IDs.

2. **`findingLocations` bound path is not tied to the indexed result.** Validation checks `m.index === i` and `validPoint(m.point, files[m.path])`, but never `m.path === results[i].path`. With two inventory files, index 0 for a `sample.py` finding can return a valid bound point for `other.py` and still complete. Cross-check `m.path` against `results[i].path` and require an own inventory key.

3. **`validPoint()` can accept a missing source binding.** If `files[f.file]` is `undefined` (finding path absent from inventory), `p.sourceSha256 === undefined` passes when `executionPoint` omits `sourceSha256`; the digest can be recomputed without that field. This permits source-unbound points in `findingLocations`, guard, and plain-string evidence. Require `typeof sourceSha === 'string'` and an own-key check before calling `validPoint`.

4. **Test gap:** the four synthetic tests cover null/malformed findings, no-Python unmatched retention, import missing/forged point IDs, and forged `findingLocations` point ID. They do not cover guard/plain forged `pointId`, `findingLocations` path/result mismatch, or missing `sourceSha256`.

Conservative limitations, not confirmation defects: 2 MiB output overflow → `unavailable`; >64 Python files → `unavailable`; no-Python supported findings → unmatched retention. These are acceptable conservative degradation, not evidence confirmation.

Additional gap: import evidence validates caller/sink point IDs but not `sinkLocation.callee === e.sink`; if sink identity part of inventory is required, add that check. No R3 or live acceptance claim.
