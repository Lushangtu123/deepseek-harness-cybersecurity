Scoped review of the mapping delta and synthetic tests.

**Mapping logic:** `map_findings` now collects all contained supported eval/exec points before applying the expected callee check. `len(candidates) != 1` returns unmatched, so a span enclosing eval+exec or nested eval/exec is no longer guessed. A single contained call with the wrong callee reaches `rule-execution-point-mismatch`. This matches the stated S1 delta. I found no safety blocker or reproducible scope regression in this mapping change.

**Concrete test defect:** `test_ambiguous_nested_and_multiple_calls_are_not_guessed` asserts only `state == 'unmatched'`. It does not assert `reason == 'ambiguous-execution-points'`, nor that `pointId`/`point` are absent. A regression returning `rule-execution-point-mismatch` or `no-supported-execution-point` would still pass. This fails to lock the key delta distinction between ambiguous multi-point spans and single wrong-callee spans.

**Second test gap:** `test_missing_mid_character_wrong_digest_and_rule_mismatch` bundles missing-position, mid-character, and wrong-callee cases, then asserts only unmatched. The wrong-callee case is the only coverage for `rule-execution-point-mismatch`, but the test would pass if it returned ambiguous/no-supported. Split it and assert exact reasons.

**Conservative limitation:** direct eval/exec rules can bind a contained `builtins.eval`/`builtins.exec` point because only the final callee component is compared. The later guard loop skips `builtins.` points, so evidence is omitted. This is conservative given `builtinIdentity: unverified`, not a safety blocker, but it is untested in this delta.

**Test coverage note:** same-line mixed and nested cases are exercised for all three rules, but only by state. Adding reason/absence assertions would convert these from smoke coverage into regression locks. `exec(exec(x))` is not covered; that is a completeness limitation, not a blocker.
