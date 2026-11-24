# Scoped review: all20 fixture-link lifecycle change

**Verdict: PASS-limited.** There are no actual blockers in the enclosed bytes.

The pass covers only the enclosed text: `regression_lib.py`, the unified, consumer and recovery-close check files, the two applied diffs, the two test files, and the evidence JSONs. The rev8 and operator diff is not enclosed, so this is not a full-scope pass.

**Method.** Tools, MCP and hooks were not used. Nothing was executed and nothing was hashed. Every hash, test result and RED/GREEN row below is a declared value read as text. None of it was independently computed or natively run.

## 1. What the enclosed bytes support

**Shared helper (`FixtureLinks`)**
- **Bounded registration.** `track` accepts only an absolute, normalized path strictly inside the root. It requires a symlink owned by the current uid. The parent chain must be owned directories, with no symlinked components.
- **Fail-closed ordering in `close()`:**
  1. Root identity is checked.
  2. The full no-follow walk rejects any unregistered link.
  3. Every record is validated.
  4. Only then are links unlinked.
  - `test_all_records_checked_before_any_unlink` and `test_unregistered_link_blocks_registered_unlink` cover this order, with zero unlinks.
- **Unlink path.** Unlink runs through a parent `dir_fd`. The parent is re-identified with `fstat`, and the name is checked again with `lstat` and `readlink` under that fd. `unlinkat` never follows a link. Link targets, whether file, directory, dangling or external, are never opened, chmod-ed or removed. The sentinel tests cover this.
- **Close failure skips retirement.** For the unified and recovery workspaces, `test_recovery_close_error_does_not_retire_unknown` covers this. For regressions and rev6, the source order shows the same thing: `links.close()` comes before `retire_sandbox` in `finally`.

**Call sites (enclosed)**
- Each site registers its link immediately after creating it:
  - unified B8
  - consumer `damage_plan` (2 callers, both pass `workspace`)
  - recovery B1 and B2
  - regressions
  - rev6 (×2)
- Every original negative assertion is computed before `finally`/`close()`:
  - `linkRetained`
  - `bytesRetained`
  - `link.is_symlink() and real.is_dir()`
  - the 78/3 outcome checks
- Check IDs and assertion expressions are unchanged. Only `track` calls were added, plus re-indentation into `try`.
- `retire_sandbox` and its helpers are byte-identical in the diff. They are only newly *called* for the rev6 and regressions `base` directories, whose entries contain no evidence tokens.
- `resource_guard.py` is identical in baseline and candidate (`704b9ce…`). Stage-symlink refusal is therefore the same in RED and GREEN runs.

**Arithmetic and consistency**
- New tests: 19 by name, matching the enclosed stderr list. 151 + 19 = 170.
- Header headroom: 1,612,639 + 484,513 = 2,097,152 = 2 MiB.
- Free-space floor: 536,870,912 = 512 MiB.
- Inventory: 10 active sites + 16 historical sites = 26 listed sites. The field `all20Entries: 20` names the suite, not the site count; the label is ambiguous but nothing is inconsistent.
- Inventory line moves match the diff hunks, for example unified 742 → 675 (net −67) and recovery 391/612 → 396/618.

## 2. Actual blockers

None found in the enclosed bytes.

## 3. Same-uid private-fixture races (disclosed class, not blockers)

- **R1.** A link can be swapped between the `lstat`/`readlink` under the fd and the `unlinkat`. The replacement link entry would then be removed. Because the unlink never follows, the replacement's target is never touched.
- **R2.** `_walk_links`, `_validate_root` and `_validate_record` are path-based. A tree swap during the walk could make it scan a different tree. The fd-parent `fstat` limits what the final unlink can act on, but does not close the window.
- **R3.** Unified `track_fixture_link` calls `readlink` a second time instead of reusing the recorded contents. That value only decides which directories `_restore_fixture_tree` skips.

## 4. Unchanged route gaps and residuals (non-blocking)

- **G1: New strictness in recovery close.** Recovery-close `Workspace.close()` now walks for links where it previously only retired. If product code ever created a symlink inside a recovery workspace, that check would now fail with a visible error. This is fail-closed. The recovery-close suite has not been run end to end with the new `Workspace` against real tools, only through fake-runner unit tests. Native20 is the real test of this.
- **G2: Walk now runs before restore in unified close.** A leftover directory that is readable but not searchable (mode r without x) now fails at the walk. Previously `_restore_fixture_tree` could `fchmod` it and continue. No current flow leaves such a mode, since B8 and consumer restore 0o700 in `finally`. This falls within the disclosed unreadable-directory limitation.
- **G3: Failure-path result shape.**
  - An exception from `close()` inside `finally` replaces the case's result.
  - In variant loops (consumer settlement and reservation, recovery B2, unified variants) it also aborts the remaining variants.
  - In `run_regressions` and `run_rev6`, a close failure now raises out of the scenario instead of returning `record(...)`.
  - Passing runs keep the same IDs and counts. Failing runs, including RED baseline runs, may show *error* instead of *passed: false*, and fewer variant details.
  - I cannot see whether those two runners' `main` catches per-scenario exceptions.
- **G4: Pre-existing gaps, unchanged by this round.**
  - The consumer `public-compile` Sandbox is intentionally retained and never retired. It is link-free.
  - The recovery `Workspace` has no mode-restore pass.
  - Conservative `retire_sandbox` keeps most workspaces, because names like `plans` and `attempt-*` contain evidence tokens. Only links are removed, which is the stated goal.

## 5. Not reviewed (bytes not enclosed)

- `implementation-rev8-operator/applied.diff`, which covers:
  - rev8 sites at lines 218 and 310 (`box.track_fixture_link` is called inside a resource-double effect, so whatever product code does next to that stage path matters)
  - `rev8_support.py`
  - the `operator/full20_batch.py` `linked-file` / `walk-entry:*` scan
- `run_evidence_gate_checks.py`, the `finally rmtree` site.
- Full `run_regressions.py` and `run_rev6_checks.py`, including:
  - the `regression_lib` import (not shown in the hunks; the GREEN probe declares the scenarios printed PASS)
  - `record()`
  - `main` exception handling
- `experiment_runner.py`.
- Referenced evidence files not enclosed:
  - `all20-links-final.stderr`
  - `initial-red.stderr`
  - `real-publication-roundtrip-qualified.json`
  - `applied.json`

**Gate note.** The consumer12 first smoke uses the enclosed unified and consumer paths, but it also depends on the unreviewed `full20_batch` scan. Clearing the Linux20 gate should rely on a separate review of that diff, not on this one.

## 6. Evidence caveats

- The RED rev6 row's `sourceSha256` is `5554aae…`. That is neither the baseline/reference value (`3f193e9a…`) nor the candidate value (`92eff5…`). Nothing enclosed binds `5554aae…` to the pre-change candidate bytes. It may be recorded in `applied.json`, which is not enclosed.
- Both legacy probes set `managedLockValidatorReplacedForUnitOnly`. That means managed-mode `retire_sandbox` was not actually exercised for the rev6 and regressions `base` directories.

## 7. Optional suggestions

- **S1.** Reject duplicate registration in `track`: raise if the path is already in `_links`. Today a double `track` would validate both records, unlink the first, then hit `FileNotFoundError` on the second, leaving a partial close. No current call site does this.
- **S2.** In unified `track_fixture_link`, reuse the contents `FixtureLinks` already recorded instead of calling `readlink` again (see R3).
- **S3.** `checks/test_fixture_return.py` has the same mistake you fixed in the new test:
  - In `test_changed_parent_retained`, the moved `old-prepare/plans` link stays behind. Close therefore fails on the *unregistered-link* branch, not the parent-identity branch, and the generic `assertRaises(Exception)` hides that.
  - `test_lstat_error_fails_close` fails in the walk, not in record validation.
  - Fix: tighten both to message regexes, and unlink the moved pointer in the first.
- **S4.** Branches that are only reachable through a race have no tests: the fd-parent mismatch, the name mismatch under the fd, and "still present after unlink". These could be covered by patching `os.fstat` or `os.lstat` with `dir_fd`.

**On the one allowed correction.** None is required. If you use it, S1 plus S2 is the smallest change and is test-only. S3 touches only host unit tests.
