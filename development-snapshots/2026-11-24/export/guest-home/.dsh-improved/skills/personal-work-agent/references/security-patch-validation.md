# Validate an identified security repair

Read for an identified vulnerability fix or an explicit request to validate a security patch. Scope checks to the affected trust boundary and realistic root cause. Ordinary code changes do not activate a broad security audit. Validation-only work stays read-only apart from authorized isolated test artifacts; fixing newly found issues requires fix authorization.

## Establish the boundary and comparison

Identify the affected entry point, untrusted input, intended security rule, vulnerable revision, patched revision, and legitimate behavior that must remain. Use existing local evidence first. If the vulnerable revision is unavailable, report that the red comparison was not verified; do not manufacture a baseline or claim a reproduction from an import error, timeout, or unrelated crash.

Inspect the patch before deciding what its proof of concept actually covers. Prefer safe local fixtures, temporary data, stubs, or an already authorized test environment. Never infer permission for live probing, email enumeration, external network scans, credential access, or production exploitation.

## Minimum evidence, scaled to the defect

| Check | What the evidence must show |
|---|---|
| Original defect | A safety assertion fails for the relevant reason on the vulnerable version and passes on the patch, where both can be tested safely |
| Same-root variant | A plausible distinct representation, entry point, or boundary condition is handled by the security rule, not merely a literal block of the original input |
| Legitimate control | Relevant authorized/benign behavior still succeeds; rejecting everything is not a repair |
| Neighboring regression | Affected callers and existing tests retain their contract |

Select variants from the actual defect: for example, canonicalization order for a path bug, ownership and role combinations for an authorization bug, or redirects/resolution behavior for an outbound-request bug. Do not turn examples into a universal payload checklist. If no meaningful variant applies, explain why instead of inventing one.

Keep the vulnerable comparison isolated from the user's working tree. Never revert their dirty edits to reproduce a defect. Preserve tests that expose an incomplete patch; do not weaken assertions to accept the current implementation.

## Interpret and report

Separate source-review evidence, successful build/import, and executed behavioral evidence. State exact revisions or content hashes, checks and outcomes, remaining untested conditions, and whether the observed patch is complete for the tested boundary. A dependency or environment blocker is an unverified check, not a security pass or a demonstrated exploit.

If a same-root variant still fails, report the incomplete repair with a minimal local reproduction. When fixes are authorized, repair the boundary and rerun original, variant, legitimate, and neighboring checks after the final edit. Wider threats, race conditions, or production assumptions beyond the available evidence remain explicit limitations.

Further reading: [Trail of Bits post-patch validation skill](https://github.com/trailofbits/skills/blob/main/plugins/post-patch-validation/skills/post-patch-validation/SKILL.md). This locally written scoped workflow does not require its standalone runtime or install external tools.
