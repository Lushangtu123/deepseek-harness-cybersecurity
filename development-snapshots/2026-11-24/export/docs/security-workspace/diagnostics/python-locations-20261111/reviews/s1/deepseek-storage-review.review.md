Read-only review; no tools/execution. No R3 or live acceptance.

**Confirmed blockers (robustness/contract/coverage, not false-acceptance safety)**

1. **Unhashable `check_id` crashes `map_findings`.**  
   `rule = hit.get('check_id')` is used in `if rule not in GUARD_RULES` before type validation. A JSON hit such as `{"check_id": [], "path": "sample.py", "start": {...}}` raises `TypeError: unhashable type: 'list'` instead of being retained as `invalid-finding`. The CLI catches only `OSError, ValueError, RecursionError`, so this escapes; managed Node degrades to `unavailable`. This contradicts per-rawhit unmatched retention.

2. **The supplied `snapshot-green.txt` is not green.**  
   It reports 87 tests with **4 failures**, all `assertEqual(json.loads(run.stdout)['version'], 1)` receiving `2`. The code emits `version: 2` in `review_batch`; the reviewer snapshot tests still freeze version 1. This is a reproducible test/launcher-contract regression, not a runtime safety issue. It must be resolved before claiming the 87 launcher/source-position checks are green.

3. **Managed Node output-buffer regression.**  
   `personal-python-evidence.mjs` sets `maxBuffer: 128*1024`, while the Python batch permits `MAX_FILES=64`, `MAX_CHECKS=64` per file, and up to 2000 hits. The report includes full `locations` and `findingLocations`, each bound point carrying hashes/spans. A valid report with only a few files × 64 points will exceed 128 KiB; `execFileSync` throws `ENOBUFS` and the catch returns `{state:'unavailable'}`. This is a reproducible coverage/availability blocker, not a false-positive safety flaw.

**Conservative limitations / false negatives**

- `request_assignment` matches only `request.args.get('')` exactly: `ast.Constant(value=str())` is the empty string. Normal non-empty query keys never produce eval-guard evidence. This is a coverage limitation, not false acceptance.
- `review_eval_guard` only scans top-level synchronous `FunctionDef` bodies; async/nested/module-level guards are missed.
- `review_plain_string_guard` requires the exact guard AST and only inspects the first statement of a following `Try` body; other valid shapes are missed.
- `unique_dynamic_execution` rejects any overlapping dynamic call, including unrelated `compile`/attribute calls; this is conservative.
- Name resolution does not model `global`/`nonlocal`. I did **not** confirm a static false-positive path from this alone because actual `Store`/`Del`/arg/def/alias/`except`/`match` bindings are rejected; dynamic `globals()`/`setattr` remains out of syntactic scope.

**Safety assessment**

I did not confirm a static false-acceptance path in the reviewed guard association: `canonical_flask_request` plus `has_unambiguous_bindings` reject ordinary rebinding forms, `builtins.*` guard evidence is skipped, and precise guard checks pass the call span into both `review_eval_guard` and `review_plain_string_guard`, preventing line-level borrowing. Legacy hits remain unmapped and unbound as intended.

One additional defense-in-depth gap: managed import artifacts attach `callerLocation`/`sinkLocation` without the `sourceSha256`/`pointId` cross-check that `locationFields` applies to guard/plain artifacts. Since the worker output is local/trusted this is not a confirmed false-evidence path, but it is weaker validation than the other artifact families.

The blockers above are concrete and scoped; none support an R3/live-acceptance claim.
