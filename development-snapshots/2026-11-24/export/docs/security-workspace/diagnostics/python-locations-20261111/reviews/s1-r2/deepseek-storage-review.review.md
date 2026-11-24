Scoped read-only review. No execution, no R3/live-acceptance claim.

**Confirmed fixes**
- `map_findings` now type-checks `check_id` before `GUARD_RULES` membership. Non-dict hits and unhashable `check_id` values produce `unmatched` rows (`invalid-finding`) instead of crashing.
- Missing, zero-width, mid-UTF-8, wrong-rule, and non-inventory spans are retained as `unmatched` (`missing-or-invalid-span`, `source-not-in-inventory`, etc.). `review_batch` continues and emits `findingLocations`; it no longer rejects the batch for those scan-position cases.
- Report v2 is consistent between worker and regression assertion; Node accepts v1/v2. The 2 MiB `maxBuffer` is at least no longer the old 128 KiB failure.
- The new cross-file test exercises import discovery, caller call selection, callee sink selection, and checks the callee `sinkLocation.id` against the `b.py` inventory point.

**Remaining scoped issues**
1. **End-to-end retention gap (not a false-evidence blocker).** The Node adapter still drops supported findings before the worker when `f.location` fails `^(.+):(\d+)$` or names a path absent from the Python `files` map:
   `if(!match||!Object.hasOwn(files,match[1]))return[];`
   Those findings never reach `map_findings`, so no `unmatched` row is produced for them. The Python retention is real, but it is not end-to-end for malformed/absent `f.location`. Consequence is silent omission/coverage loss, not batch rejection. This is the clearest follow-up gap.
2. **The integrated point-binding test is weaker than its name.** It asserts `sinkLocation.id` equals the `b.py` inventory point, but for the caller it only asserts `callerLocation.call.start.line == 5`. It does not assert `callerLocation.id` equals the `a.py` inventory point, nor that `callerLocation.sourceSha256` equals `a.py`’s pinned digest. Thus source-side point binding is not actually verified; a wrong caller point on the same line would not be caught. Test-only gap, not a product defect.
3. **2 MiB is a cap, not a proven bound.** The worker accepts up to 2000 hits, 64 files, and 64 points per file; `findingLocations` duplicates the full point object for each bound hit. A valid maximum-shaped report can approach or exceed 2 MiB. Overflow degrades to `unavailable` via the catch, so it should not create false evidence, but it can suppress valid evidence. I cannot confirm “aligned launcher bound” from the supplied constants alone; this remains a conservative availability limitation unless the launcher independently bounds report size.
4. **Snapshot evidence is contaminated.** `snapshot.txt` interleaves repeated `storage-settlement-pending; query status and storage-reconcile before retrying` lines with unittest dots. The final `Ran 87 tests ... OK` is present, but the transcript is not clean reproducible evidence. Treat the 87-test result as synthetic/preserved evidence, not runtime acceptance.

**Safety assessment**
No confirmed safety blocker in the follow-up changes: the unhashable-`check_id` crash and missing-span batch rejection are fixed in the Python worker. The remaining items are visibility/test-coverage and buffer-bound limitations. The adapter prefilter is the one scoped regression relative to the stated “retain as unmatched” requirement, because it still silently omits a class of malformed positions before the retention logic runs.
