# Proportionate clarification

Use when implementation intent, design, or scope needs discussion. Decide from what is unknown and what could go wrong, not from file count alone.

| Situation | Next step |
|---|---|
| Localized change with clear behavior, constraints, and acceptance | Inspect the affected context, implement within authorization, and verify; no separate design approval or document |
| Bounded change with a material unanswered choice | Ask the smallest question that changes the result, state the chosen behavior in chat, then follow the normal implementation workflow |
| Broad change with competing product, architecture, privacy, compatibility, or operating choices | Agree the boundary and important decisions before implementation; use an existing plan or a short written design when a durable contract is useful |

An exact request can be high risk: payment retries, authorization, migrations, or data loss still require relevant safeguards and action-time permission. Conversely, several mechanical edits can remain a clear bounded task.

Reuse answers and approved plans already in the conversation. "Continue" or "implement the recommendation" authorizes the described in-scope work, not a materially different product, remote mutation, or unmentioned installation. Ask again only if new evidence creates a consequential choice or expands the approved boundary.

For a requested design stress-test, use the available `grill-me` skill only within that scope. Investigate facts the code/tools can answer; reserve questions for decisions or inaccessible facts. Resolve prerequisite choices before dependent ones, give a recommendation with its tradeoff, and stop when the task's consequential uncertainties are settled. Do not turn an already-approved issue brief into another exhaustive interview. When lasting terminology or decisions need recording, reuse [project-knowledge.md](project-knowledge.md), not a second requirements document; specialist invocation never expands writing permissions.

Use `brainstorming` when available and genuinely useful, preserving its host instruction priority. Do not silently rewrite another installed skill to resolve a conflict; disclose incompatible mandatory steps and update that skill only when authorized. If no applicable specialist is available, use the table above as the native workflow.

No size classification waives regression checks, safety guards, or permissions. A throwaway prototype must be explicitly requested or accepted, isolated from production, and labeled with unverified behavior; retaining it requires normal review. Do not automatically create a spec, commit it, launch a visual companion, or spawn reviewers for routine work.

This locally written workflow is informed by [Superpowers v7.0.0 brainstorming](https://github.com/obra/superpowers/blob/v7.0.0/skills/brainstorming/SKILL.md), without its automatic commit or prototype-testing defaults.
