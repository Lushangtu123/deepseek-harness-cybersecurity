# Personal Work Agent integration

Use for PWA entry/return, interrupted builds, or another session continuing the work. This is a context contract, not an API, automatic worker invocation, or permission grant.

## Ownership and discovery

- PWA owns the user's overall outcome, cross-domain routing, shared permission policy, and final evidence check. Project Builder owns the scoped initial-build workflow. In one conversation the same agent can perform both roles.
- Resolve the advertised skill in the current catalog, including its namespace; do not hard-code a cache version, invent a tool call, or install a missing specialist. PWA retains a native bootstrap fallback if this skill is unavailable.
- Do not recursively invoke PWA to rediscover this skill or run a second requirements interview. Read only relevant PWA references when that orchestrator is actually in use; direct use does not require loading the whole PWA skill.
- PWA's existing permissions and quality gates remain applicable. A helper skill cannot broaden them. Passed stack defaults are preferences; confirmed product/platform constraints take priority.

## Entry context

Carry these facts in the current conversation or an existing brief, not a mandatory new JSON file:

| Field | Minimum useful information |
|---|---|
| Intent | Plan, build, review, or resume; desired first-release outcome and non-goals |
| Target | Exact workspace/project boundary, existing files, applicable instructions, relevant Git state if present |
| Decisions | Confirmed requirements and architecture, with relevant authoritative glossary/decision/spec paths or anchors; distinguish user choices from agent assumptions and personal preferences |
| Acceptance | Observable successful and important unsuccessful journeys; agreed prototype/production limits |
| Constraints | Data/privacy, platform, budget, external dependencies, authorized actions and pending approvals |
| Progress | Current slice, touched files, completed checks with evidence, known blockers, next step |

Omit irrelevant fields for a tiny project. Inspect recoverable local evidence before asking the user to repeat it. Ask only about an unresolved choice whose answer changes the work. Do not infer permission from an old ledger; recheck the next concrete action against the current request and host policy.

## Continue rather than reset

Reconcile recorded progress with actual files and tests. Resume the unfinished slice without regenerating or overwriting its scaffold. File existence does not mean the first release is finished. If the original acceptance contract is unavailable, recover it from the conversation or ask; do not invent a new product contract from a partial README.

For substantial, parallel, or cross-session work, update one compact existing ledger (or an approved temporary location) with decisions, owned paths, evidence, and the next action. Do not copy secrets, full private datasets, or bulky logs into it.

## Return context

Report one outcome appropriate to the current intent:

- `PLAN_READY`: the requested plan is delivered; no implied implementation or installation.
- `IN_PROGRESS`: useful slices exist; the requested first-release boundary is not complete.
- `NEEDS_DECISION`: a consequential product or authorization choice needs the user; name it precisely.
- `BLOCKED_ENVIRONMENT`: a dependency, tool, credential, or runtime prevents a named check or capability; distinguish implemented from verified.
- `VERIFIED_FIRST_RELEASE`: all agreed first-release acceptance criteria have fresh supporting evidence, with any agreed exclusions explicit. This is not automatically production readiness.

Include target path, actual changed files, current slice, commands/results and their scope, real versus substituted integrations, setup prerequisites, and unresolved items. Preserve known external-operation targets and uncertainty; do not retry an ambiguous mutation during handoff.

Carry exact constraints and acceptance checks as well as links to relevant vocabulary and decisions. Do not let a glossary or ADR replace the product contract, and do not mark an accepted design as implemented or verified without evidence.

On `VERIFIED_FIRST_RELEASE`, PWA can route later bug fixes, enhancements, and CI work to maintenance using this evidence. On other outcomes, continue the same build when appropriate instead of asking for requirements again. PWA should inspect artifacts and run the relevant integrated checks before its own completion claim; do not duplicate every check solely because the workflow name changed.
