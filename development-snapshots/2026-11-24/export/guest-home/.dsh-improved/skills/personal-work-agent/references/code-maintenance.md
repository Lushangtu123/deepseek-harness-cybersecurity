# Existing-codebase maintenance

Use this mode for diagnosis, implementation, refactoring, review, test work, CI failures, and repository documentation tied to an existing project.

## 1. Inspect before editing

- Locate the repository root and read applicable `AGENTS.md` files.
- Inspect the working tree and preserve unrelated staged, unstaged, and untracked work.
- Read the smallest relevant set of README, contribution, architecture, and feature documentation.
- Identify the actual language, framework, package manager, workspaces, entry points, build files, lockfiles, CI definitions, containers, migrations, and environment examples.
- Derive runnable commands from configuration. Treat README commands as claims until they agree with the repository.
- Capture a compact working snapshot: task class, branch and HEAD when applicable, dirty paths, affected boundary, repository-native commands, and unknowns. Keep it in working memory unless a long-task ledger is warranted.
- Capture the baseline diff for any dirty path that may overlap the task. Use patch-scoped edits and limit formatters or generators to intended paths. If task changes cannot be separated safely from existing hunks, pause or isolate the work without discarding the user's changes.

For a remote-only repository, read [github-remote-inspection.md](github-remote-inspection.md). If inspection is blocked, continue only with work that does not depend on the missing evidence and label resulting assumptions.

For dependency upgrades, framework/API migrations, version-sensitive guidance, or Python environment and service checks, read [version-aware-maintenance.md](version-aware-maintenance.md). Read it only when that branch is relevant; ordinary language-level fixes do not require dependency research.

## 2. Classify the request

- Explain or report: inspect and answer; do not edit.
- Diagnose: establish the cause and evidence; do not implement unless the request includes a fix.
- Implement or fix: make the smallest sufficient change and verify it.
- Refactor: preserve behavior and establish regression coverage before structural changes.
- Review: report actionable findings ordered by impact; do not modify unless asked.

For existing PR comments or review threads, read [pr-maintenance.md](pr-maintenance.md). Reviewing feedback, implementing selected fixes, and replying to or resolving remote threads are separate actions with separate scope checks.

For issue/backlog triage or a report that needs an execution brief, read [issue-intake.md](issue-intake.md). For requested architecture opportunities or concrete structural friction, read [architecture-assessment.md](architecture-assessment.md). These are conditional assessment branches, not automatic steps or authorization to implement their recommendations.

## 3. Analyze impact

Trace the affected entry point, call path, data contract, persistence, tests, and user-visible behavior. Check for implications to authentication, authorization, migrations, caching, queues, environment variables, API compatibility, accessibility, and deployment.

When cross-file navigation or impact discovery is substantial, read [codegraph-navigation.md](codegraph-navigation.md) for optional use of an already-available CodeGraph capability. Skip it for a localized task with known source and tests. Missing graph tools do not block native search, and graph output does not establish runtime behavior or replace verification.

For risky or broad changes, state the proposed boundary before implementation. Avoid unrelated cleanup.

When intent or scope needs discussion, use [task-sizing.md](task-sizing.md). Reuse the user's approved description; do not create a separate design document or repeat approval for a clear localized fix.

When terminology or an important design decision is disputed or needs to survive the change, use [project-knowledge.md](project-knowledge.md). Separate the code's current behavior from the agreed requirement; preserve existing documentation conventions and exact acceptance constraints.

## 4. Establish the feedback loop

Before the first relevant execution, establish its entry command and prerequisites from the actual repository. When the invoked chain, lifecycle hooks, or execution environment are unresolved, read [execution-preflight.md](execution-preflight.md). A missing tool is a setup limitation, not a product defect or permission to install; a known safe native check need not repeat a whole-environment audit.

For a multi-command verification, retry/recovery, or a report needing exact runtime versions, read [command-evidence.md](command-evidence.md) before execution. Capture the relevant commands directly and derive their report facts before sending; do not reconstruct missing receipts afterward.

For a defect fix or observable behavior change that includes implementation, use this loop proportionately. A diagnosis-only request completes the evidence and root-cause steps, proposes the smallest fix, and stops before mutation.

1. Define the user-visible or operational acceptance signal.
2. Reproduce the symptom or establish a check that can fail for the target behavior. Confirm a new regression test fails for the intended reason before relying on it.
3. Form a falsifiable root-cause hypothesis from the call path and evidence; do not patch symptoms first.
4. When implementation is authorized, change one relevant variable and make the smallest sufficient implementation change.
5. Run the focused check to green, then rerun the original unminimized symptom and relevant neighboring checks.
6. Inspect the final diff and run fresh final verification after the last change.

A command exit code, HTTP success status, process start, or rendered page is only evidence for what it directly observes. Add a positive or negative control when necessary to show that the check can detect the defect. If the same fix strategy fails three times, stop adding patches and reassess the hypothesis, test seam, dependencies, or architecture.

If no honest automated seam exists, report that limitation and use the strongest available reproducible check; do not create a shallow test that cannot detect the requested behavior.

When choosing or reviewing regression coverage, read [test-strategy.md](test-strategy.md). Check the value of the affected tests without a whole-suite audit. Its property-testing branch applies only to a meaningful invariant and broad input space; a narrow defect can use a focused native example.

## 5. Implement safely

- Follow local naming, structure, formatting, and dependency conventions.
- Prefer modifying an existing abstraction over adding a parallel one when the existing abstraction is appropriate.
- Add a dependency only when its concrete benefit outweighs maintenance and security cost.
- Do not edit generated or vendored files unless the repository workflow requires it.
- Update existing documentation when behavior, configuration, migration, or operating procedures change.

When implementation size or over-engineering is a material concern, apply the minimal-correct-change ladder in [token-efficiency.md](token-efficiency.md). Shorter code is not a completion signal: preserve explicit requirements, readable control flow, safety guards, compatibility, and meaningful verification.

Use [capability-routing.md](capability-routing.md) to avoid overlapping TDD, diagnosis, CI, review, and framework workflows. For Java, Python, notebooks, or other stacks, route by detected evidence rather than forcing the personal default stack.

## 6. Validate by risk

Choose the relevant layers in order:

1. Formatting or linting for changed files.
2. Static analysis or type checking.
3. Focused unit tests that cover the changed behavior.
4. Integration or end-to-end tests for cross-boundary behavior.
5. Production build for build-time or bundling risk.
6. Security checks for trust-boundary, dependency, authentication, or data changes.
7. Performance or accessibility checks when the change affects those requirements.

If a check fails, determine whether it is caused by the change or was already present when practical. Never delete or weaken a meaningful test to make the suite pass.

When fixing or validating an identified security defect, read [security-patch-validation.md](security-patch-validation.md). Check the original defect, relevant same-root variants, and legitimate behavior at the affected boundary. This is not an automatic whole-repository security audit.

When acceptance depends on an API, CLI, background job, webhook, or browser flow beyond the observed unit boundary, read [functional-qa.md](functional-qa.md). Verify the promised final state, not only request acceptance; isolated changes do not require this branch.

## 7. Protect operational compatibility

For dependency upgrades, migrations, deprecations, public API changes, or production-facing behavior, inspect compatibility requirements, data and rollback paths, observability, staged-release controls, and failure recovery. Apply [version-aware-maintenance.md](version-aware-maintenance.md) to version-sensitive work. Do not execute a migration, release, or deployment unless the concrete action is authorized.

## 8. Deliver

Summarize:

- Outcome and changed behavior.
- Important files or modules changed.
- Validation commands and results.
- Remaining risks or unverified items.
- Required environment variables, migrations, or operational steps.
- Suggested commit message and PR summary when useful.

Keep the report compact, but retain exact verification results, material risks, and unverified items. Apply the reporting boundary in [token-efficiency.md](token-efficiency.md) when token efficiency is in scope.

Do not create a new summary Markdown file unless the user requests it or the repository has an established practice that requires one.

When a reusable report is requested, adapt the optional [change-report template](../assets/templates/change-report.md) and remove sections that do not apply.
