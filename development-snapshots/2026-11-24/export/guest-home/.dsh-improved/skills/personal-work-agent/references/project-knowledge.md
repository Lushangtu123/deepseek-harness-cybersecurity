# Project vocabulary and lasting decisions

Use when ambiguous project terminology or important design choices affect the task, or when the user asks to document them. Ordinary small changes need no glossary, ADR, or documentation ceremony. This is shared guidance for PWA and the bundled Project Builder, not another requirements interview.

## Find the existing source of truth

Inspect relevant project instructions and the smallest useful set of domain/architecture/spec documents. Keep the repository's naming and locations: an existing README section, glossary, decision log, or ADR system takes priority over a new file convention. Do not install setup skills, rewrite `AGENTS.md`, or audit the whole repository merely to establish a place for notes.

Separate four things: observed implementation, user-confirmed requirement/decision, agent assumption/proposal, and unresolved conflict. A README claim or a symbol name alone does not prove intended domain meaning. If docs, code, and user statements disagree, cite the disagreement, distinguish current behavior from intended behavior, and ask only when the unresolved choice changes the task. Do not silently rename concepts in code, rewrite past decisions, or promote an inference into user approval.

## Record only useful knowledge

| Kind | When it earns a durable entry | Minimum content |
|---|---|---|
| Domain term | A project-specific word has ambiguous meanings, an important exclusion, or repeated use across sessions/components | Term, precise meaning in its named context, relevant contrast/example, authoritative source |
| Lasting decision | A consequential choice has plausible alternatives and losing its rationale would cause costly rework | Context, choice, status, rationale/alternatives, consequences, evidence/decision source, revisit condition |
| Requirement | Observable behavior or a constraint must survive handoff | Keep it in the existing brief/spec with exact values, units, error/ordering/negative requirements; link to implementation and acceptance evidence as they become available |
| Task state | Current slice, next action, checks or blockers | Keep in the existing task ledger or handoff, not the permanent glossary |

Use the existing document structure; these fields are content guidance, not a mandatory schema. Preserve distinctions when the same word means different things in different domains. Avoid universal vocabulary bans, code-to-term bulk renames, and duplicating a whole spec in a glossary.

Record a decision as accepted only when supported by user confirmation or an authoritative existing decision. Otherwise mark proposed or unresolved. Include the actual decision date when known; distinguish a later documentation date instead of inventing history. A documented accepted choice is not proof it has been implemented or tested.

An ADR is optional: use one for a lasting tradeoff that cannot be captured clearly in the existing decision record. Preserve superseded decisions and link their replacements rather than erasing the original rationale. Do not invent alternatives or reasons the user never considered; label newly supplied analysis as such.

## Respect the task's writing boundary

- Explanation, planning, review, and diagnosis stay read-only unless a saved deliverable was requested. Offer wording in chat if writing is not authorized.
- An authorized implementation can include a small, directly relevant documentation update. An explicit documentation request authorizes that scoped writing, not code changes, tracker publication, or global memory edits.
- Create a new glossary/decision file only when it solves an actual task need and no suitable existing home exists. Do not add empty templates or require a fixed file set. Confirm a materially broader documentation initiative first.
- Keep credentials, private session dumps, and unnecessary personal data out of durable project knowledge. Source pointers must not expose secret-bearing URLs or inaccessible material as if the next reader can verify it.

## Verify and reconnect

Review the edited passages against the confirmed facts and exact contract. Preserve unrelated sections and established terminology; resolve local links and check for contradictory duplicate definitions. Report conflicts that remain instead of silently choosing one. Run relevant behavior checks if behavior changed, but do not claim code tests validate a prose decision or run unrelated suites for a docs-only update.

Pass the authoritative document paths/anchors, acceptance constraints, unresolved choices, and changed decisions into the existing build/maintenance handoff. A glossary and ADR are not substitutes for the spec: retain exact limits, negative cases, and acceptance checks in the contract. Keep planned test coverage separate from executed results, and consume existing decisions on resume without asking the user to approve them again.

Method inspiration: [AI Hero's grill-with-docs](https://www.aihero.dev/skills-grill-with-docs), reviewed 2026-10-14. This local adaptation keeps shared vocabulary and decision rationale without requiring its upstream interview/dependency chain or prescribed file layout.
