# Capability routing

Use this reference when a request is ambiguous, spans modes, or could activate overlapping specialist skills. Match the requested input, operation, output, and success condition. Select one primary workflow; helpers should have narrow, non-overlapping responsibilities.

## Check availability before delegating

1. Use the current session's skill catalog and actual tool discovery. Match the advertised skill name, not a directory basename, old conversation, or remembered cache path. Resolve namespaces from the catalog; do not fabricate an alias or invocation tool.
2. Read the selected skill before using it. Check its required tools, authentication, platform, framework versions, and implicit side effects against this task. A skill is instructions for the agent, not a separately running worker or a grant of tool access.
3. When a prerequisite is missing, use a supported available alternative or the repository-native workflow below. Say what is unavailable when it affects the result. Do not install, authenticate, enable integrations, or expand permissions just to satisfy a skill's recipe.
4. A specialist's project-specific conventions do not become this repository's conventions. Do not carry Binder, Linear, Composio, automatic commits, messages, or deployment steps into a task that did not request them. If the specialist cannot be used within the authorized scope, use the native fallback and explain the limitation.
5. Load only the chosen workflow and useful helpers. Do not load every entry in this table. A user-named skill takes precedence over these defaults when available and applicable, subject to higher-priority instructions and action-time permissions.

## Route by task class

| Task class | Primary behavior | Optional specialist | Boundary |
|---|---|---|---|
| Read or explain | Inspect and answer | Domain specialist only when needed | Do not edit or create external state |
| Build a new project or resume its unfinished first release | Read [project-bootstrap.md](project-bootstrap.md), reuse the agreed contract, build verified vertical slices | `project-builder` when advertised in the current catalog | Preserve plan-only intent and existing files; no recursive orchestration, automatic install, commit, or deployment |
| Diagnose a bug or regression | Establish a red-capable feedback loop and root cause | Prefer `diagnose`; use `systematic-debugging` only if explicitly requested or the preferred skill is unavailable | Diagnosis alone does not authorize a fix |
| Implement a bounded change | Make the smallest observable change | Use `tdd` when test-first work is requested or a useful behavioral seam exists | Do not load a second TDD workflow |
| Clarify or size implementation work | Follow [task-sizing.md](task-sizing.md); reuse known requirements and prior approval | `brainstorming` for material design uncertainty | No automatic design artifacts, commits, or repeated approval for a clear small change |
| Review how a task/session went | Follow [task-retrospective.md](task-retrospective.md); cite the agreed record and propose only supported improvements | No additional skill required | Read-only until the user authorizes selected changes; no automatic hooks, global rules, or fabricated recurrence |
| Clarify or document project terminology/decisions | Follow [project-knowledge.md](project-knowledge.md); preserve source, context, status and exact requirements | Existing repository documentation workflow | No forced glossary/ADR, silent conflict resolution, code renaming, or publication |
| Review or extend tests | Check observable contract, credible failure, coverage gap, and production boundary | Existing test specialist only as needed | Read [test-strategy.md](test-strategy.md); audit-only requests do not authorize test deletion |
| Cross-boundary acceptance | Verify the affected flow and final state | Existing native API/CLI/job/browser tools | Read [functional-qa.md](functional-qa.md); no implicit live probes or installations |
| Audit or update skills | Inventory exact paths and review the selected change | `manage-skills` when its CLI and existing database work; `skill-creator` for authored changes | Read [skill-governance.md](skill-governance.md); no implicit library migration, bulk sync, or auto-approval |
| Assess architecture opportunities | Follow [architecture-assessment.md](architecture-assessment.md); ground candidates in current maintenance friction | `improve-codebase-architecture` only if available and compatible with scope | Assessment remains read-only; no mandatory report, dependency chain or refactor |
| Triage an issue or prepare an execution brief | Follow [issue-intake.md](issue-intake.md); separate report, reproduction and intended contract | `triage` only if available and compatible with scope | No automatic tracker writes, closure, label setup or implementation |
| Implement an architectural or broad change | Reuse the agreed acceptance contract and a short implementation plan | Framework or security specialist for the affected boundary | Reconfirm scope only when new evidence materially changes the approved architecture or migration boundary |
| Review a branch or PR | Review from a fixed base or merge-base | Use `review` for an explicitly requested diff review | Review is read-only unless fixes are requested |
| Handle existing PR review comments | Validate each finding against the current PR HEAD before deciding or fixing | Prefer `triage-review-comments`; use `gh-address-comments` for supported collection or authorized fixes | Read [pr-maintenance.md](pr-maintenance.md); replies, thread resolution, push, and merge are separate actions |
| GitHub Actions CI failure | Inspect checks and logs, then isolate the cause | Use `gh-fix-ci` | Do not generalize external CI providers as GitHub Actions |
| Upgrade dependencies or migrate APIs | Verify resolved versions, compatibility, and small reviewable batches | Use a migration specialist only if its prerequisites and side effects fit | Read [version-aware-maintenance.md](version-aware-maintenance.md); no implicit package install, live migration, or release |
| High-risk completion | Independently check requirements, diff, and fresh verification | Use `requesting-code-review` only for major or high-risk changes | Ordinary small changes receive focused self-review |
| Remote-only repository inspection | Read the pinned remote revision | Follow [github-remote-inspection.md](github-remote-inspection.md) | Do not imply local state or executed tests |
| Long-running or cross-session work | Maintain a compact evidence and next-action ledger | Use `handoff` when another session must continue | Do not create routine status artifacts |
| Context setup or degradation | Curate a focused context package before the primary workflow | Use `context-engineering` when its trigger conditions in `SKILL.md` apply | Skip it for isolated work with sufficient context; do not install it implicitly |

## Specialist boundaries

- Prefer repository-native tools and instructions over personal defaults.
- Resolve framework/runtime versions before applying version-specific advice; consult [version-aware-maintenance.md](version-aware-maintenance.md) when versions or compatibility affect the change.
- Use security specialists for trust-boundary, authentication, authorization, secret, dependency, or vulnerability work; ordinary code touching input data does not automatically require a security audit.
- Use document, presentation, spreadsheet, PDF, or investment specialists for their mechanics. This skill owns routing, source discipline, permissions, and the final evidence check.

When two skills prescribe the same method, choose one and record the alternative as unused rather than combining both instruction sets.

## Small capability registry

These are optional candidates, not installation requirements. Use only names present in the current catalog. Derive exact commands from the repository; the native fallback is not permission to create a new framework.

| Concern | Candidate skill | Prerequisite / applicability | Native fallback |
|---|---|---|---|
| Root cause | `diagnose`, otherwise `systematic-debugging` | Relevant logs, source, or a reproducible symptom | Reproduce, trace, test one hypothesis; diagnosis alone remains read-only |
| Test-first implementation | `tdd` | Authorized change and a meaningful test seam | Existing test runner with a red/green regression; disclose unavailable execution |
| Property-oriented testing | `property-based-testing` if present | A specified invariant, broad input space, and task-relevant defect risk; do not stack a second test workflow | Read [test-strategy.md](test-strategy.md); use native parameterized/exhaustive checks or an already-installed generator |
| Security repair validation | `post-patch-validation` if present | An identified security defect or explicit repair-validation request; prerequisites and side effects must fit | Read [security-patch-validation.md](security-patch-validation.md); scoped local original/variant/benign checks with honest evidence limits |
| PR comment decisions | `triage-review-comments` | Current PR revision and comments; no inherited project-specific mutations | Read-only connector or authenticated `gh`, then current-code evidence; see PR reference |
| PR comment collection / fixes | `gh-address-comments` | Its supported GitHub access mechanism; fixes explicitly in scope | Available GitHub connector or local patch; do not require `gh` when a connector suffices |
| GitHub Actions | `gh-fix-ci` | GitHub Actions evidence and its required GitHub access | Available check/log reader; report access limits instead of inventing a cause |
| React / Next.js performance | `vercel-react-best-practices` | Detected React/Next.js version and performance-related task | Existing profiler/tests and version-matched official docs |
| React component API design | `vercel-composition-patterns` | Component refactor; check React 19-only guidance before use | Existing component contracts and behavior-preserving tests |
| Vitest tests | `vitest` | Repository actually uses a compatible Vitest version | Existing configured test runner; do not introduce Vitest to unrelated stacks |
| Browser reproduction | `playwright` or `webapp-testing` | Supported browser tools, safe local target; choose one for the requested operation | Existing E2E suite or an explicit manual reproduction; do not install browsers silently |
| Accessibility / UI audit | `web-design-guidelines` | Requested or relevant UI audit, read-only unless changes authorized | Inspect affected UI against applicable requirements |
| Context setup or degradation | `context-engineering` | Available in the current catalog and the task matches a trigger in `SKILL.md` | Load only relevant rules, files, constraints, and live evidence; use the coordination ledger for cross-session continuity |
| Cross-file call paths or change impact | Existing CodeGraph MCP/CLI, following [codegraph-navigation.md](codegraph-navigation.md) | Actual callable capability and known target project; index freshness may remain unknown | Native search/current source is the fallback; setup uses `codegraph-bootstrap` only when authorized, with no implicit install, indexing or hooks |
| Token-efficient code | `ponytail` | Installed, applicable, and the task has genuine over-build choices or explicitly requests it | Read [token-efficiency.md](token-efficiency.md); use repository-native reuse, standard library, native platform, existing dependencies, then minimum new code |
| Concise reporting | `caveman` | Installed and explicitly requested, or terse reporting is the deliverable after facts are verified | Follow the compact-report boundary in [token-efficiency.md](token-efficiency.md); do not compress the engineering process |
| Semantic document extraction | Existing MarkItDown installation as an optional helper | Layout is not authoritative and the original remains available | Keep the original authoritative and use the format-specific office skill for visual, formula, comment, or editability requirements |
| Large repetitive tool output | Already-configured compression layer, including Caveman 2 | Input is recoverable and routing, privacy, fail-open behavior, and measured benefit are acceptable | Query, filter, or slice the original with repository-native tools; do not install or globally enable an interceptor implicitly |
| Python service / library | No mandatory specialist | Actual Python environment, lockfile and CI; notebooks alone are insufficient | Follow the Python adapter in the version-aware reference |
| Cross-session handoff | `handoff` | Another session must continue and the skill is currently available | Compact evidence ledger from [work-coordination.md](work-coordination.md) |

For an explicitly requested migration skill such as `codebase-migrate`, inspect its installation, issue-tracker, commit, push, and merge requirements first. Do not make it the default for a local version update. Plain explanation, pure logic edits, and narrow existing tests do not need a framework specialist solely because the repository uses that framework.
