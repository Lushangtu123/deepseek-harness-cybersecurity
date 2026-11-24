# Repository execution preflight

Use for an unresolved repository command chain, lifecycle hook, missing tool or
environment mismatch. This is a conditional preparation step, not a new runner
or a requirement to audit every file before an already-understood local check.
Use [permissions.md](permissions.md) as the authorization authority.

## Ground the command and its effects

Before claiming a precise side effect, confirm that a returned inspection result
contains its source. An intended read, remembered pattern or script name is not
that result. If it is missing, retrieve the source or leave the effect unknown.

Read the actual entry definition and reachable local code/configuration needed
to classify the command, including any alternative command you intend to run
instead. Depending on the tool this includes pre/post lifecycle
hooks, Make includes/prerequisites, shell or Python wrappers, imported helpers,
container entrypoints, test collection and application startup. Follow only the
relevant chain; do not scan the entire repository or execute code to discover
whether its execution is safe.

Keep a compact internal map when there is more than one boundary:

| Entry / hook | Definition actually read | Invoked local target | Effect or unresolved boundary |
|---|---|---|---|
| | | | |

For a local hook or wrapper, retrieve its implementation and the relevant test
body before calling either safe or unsafe or executing a bypass. Inspect file
contents, not only names. Record which definitions were observed
and which remain unknown. An imported helper may perform work at import time;
`test` and `build` labels do not establish safety. Inspect hooks of the exact
package-manager operation, not a guessed lifecycle for a different command.

If a forbidden or unauthorized effect is already clear, do not execute the
command. Read further only if necessary and within scope to answer the user;
an early refusal is allowed, but is not a completed whole-chain inspection.
If dynamic dispatch or unavailable code leaves effects unbounded, use an
adequately isolated supported environment or report the block. Do not execute
an unsafe entry merely because its harmless first stage would probably pass.

Ground final claims in what was actually retrieved. For example, a manifest can
establish the name and arguments of an invoked script; it cannot establish that
unread script's HTTP method, payload, destination or source line. State an
inference as such or omit it. Recheck citations if the file changed afterward.

## Check the smallest execution environment

Identify the repository's selected runtime, package manager, environment and
lock/configuration files, then check the prerequisites for the intended check.
Distinguish declared, locked and installed versions. Prefer an existing project
environment or suitable already-installed native tool. Query nonsecret metadata
without importing service startup code, dumping environment variables, reading
credentials or contacting private services.

When a prerequisite is missing:

1. Name the blocked command and missing prerequisite precisely. Keep setup
   failure separate from an observed product failure.
2. Use a repository-supported available alternative only when it checks the
   same contract. Explain narrower coverage; syntax checks are not backend or
   browser acceptance, and supplied historical logs are not fresh execution.
3. If setup is needed, propose the smallest concrete action: target environment,
   pinned source/lockfile where available, dependency set, side effects, and the
   checks it would unblock. Reuse exact current authorization when applicable;
   otherwise obtain it before installing or changing the environment.
4. Prefer a task-owned isolated copy/environment when setup could disturb user
   work. Preserve source/lockfiles and unrelated resolutions. Do not silently
   disable lifecycle hooks that setup requires; when supported and appropriate,
   explain any intentionally omitted hooks and the resulting limitation.
5. After authorized setup, verify the selected environment and rerun the
   original blocked check against the final code. A successful install is not
   a passing test. Keep before/after evidence and any remaining gaps.

A plan-only request stops at the plan. No fallback may install tools, fetch
models/data, weaken tests, fabricate a lockfile or replace a production path
with synthetic data merely to obtain green output. If setup is not authorized,
preserve useful work and hand off the exact prerequisite and next safe check.

## Report the state honestly

Use the relevant distinction: not run, setup blocked, executed and failed,
executed and passed, or independently supplemented. Include command, environment,
result, covered outcome and remaining limitation. Preserve exact output/byte
contracts without adding Markdown escaping inside code literals. Link existing
evidence when useful; do not create a new repository report for every preflight.
