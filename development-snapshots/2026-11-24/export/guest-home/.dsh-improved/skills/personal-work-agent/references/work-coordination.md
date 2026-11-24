# Long-task coordination

Use this reference only for more than three dependent stages, impending context compaction, cross-session continuation, or work split among agents. Do not create a ledger for a routine one-step change.

## Compact working ledger

Keep the ledger in the operating environment's temporary directory or another user-approved non-repository location unless the repository already has an established planning artifact. Record only:

- Objective and observable completion condition.
- Authoritative issue, specification, repository, base revision, and current HEAD.
- Decisions and assumptions that affect implementation.
- Completed and next steps.
- Touched files or owned paths.
- Verification commands and current results.
- Blockers, unresolved risks, and authorization already granted or still required.

Update existing source-of-truth artifacts instead of duplicating them. Do not copy secrets, credentials, full logs, or unnecessary private data into the ledger. Use the installed `handoff` skill when another session or agent must continue.

Link relevant authoritative glossary, decision and spec anchors using [project-knowledge.md](project-knowledge.md); do not replace exact requirements with a vague summary. A continuation ledger is not a task retrospective or permission to change permanent rules. Use [task-retrospective.md](task-retrospective.md) only when that review is requested.

## Keep one contract across stages

Carry an approved issue brief or architecture choice into implementation/TDD and handoff by reference, retaining exact limits, units, errors, negative cases and non-goals. Add only changed decisions, completed acceptance items and open work; do not create competing specs or restart settled clarification. A brief or recommendation marked proposed stays proposed until actually accepted.

Before continuation, reconcile the recorded repository/revision and dirty paths with the current workspace; when Git is unavailable use actual file identities and disclose the limitation. Re-read the authoritative contract and check that referenced evidence belongs to the same code, configuration and relevant environment. Reuse valid evidence, but rerun affected checks after relevant changes and before a new completion claim. A previous agent's "green" summary, an old line number or a planned command is not fresh verification. Preserve user edits and changed requirements; surface material conflicts rather than choosing silently.

State the next concrete action and any authorization still needed. Prior permission applies only to its actual target/effect; a handoff does not authorize publication, installation or a new external action. Use the available `handoff` skill without requiring it as a new dependency; if unavailable, this compact ledger is the native fallback.

## Parallelism gate

- Parallelize independent read-only research or work on independent subsystems with no shared state.
- Give each worker a bounded scope, allowed mutations, owned paths, required evidence, and expected output.
- Do not let multiple workers edit overlapping files in one working tree. Use isolated worktrees or explicit non-overlapping ownership for parallel writes.
- The integrating agent resolves conflicts, inspects the combined diff, and reruns the checks that support the final claim. A worker's success report is not final verification.

## Failure states

Use a concrete state when work cannot continue safely: `NEEDS_CONTEXT`, `BLOCKED_DEPENDENCY`, `VERIFICATION_FAILED`, `SCOPE_CHANGED`, or `EXTERNAL_SIDE_EFFECT_UNCERTAIN`. Preserve useful partial work and evidence. Change the hypothesis, narrow the reproduction, or request the missing decision rather than repeating the same failed action.

For `EXTERNAL_SIDE_EFFECT_UNCERTAIN`, carry the exact target, known request or idempotency identifier, and last observed state into the handoff. Do not retry a known or suspected prior mutation until read-only reconciliation proves it absent or documented idempotency makes the retry safe.
