# Scoped architecture assessment

Read when the user asks where an existing codebase's architecture should improve, or a requested change exposes concrete structural friction. This is an assessment branch of maintenance, not permission to refactor and not a whole-repository scan for every fix.

## Look where change hurts

Start with the named subsystem, maintenance pain or upcoming change. If none is supplied, use available recent history to identify repeatedly changed areas; history is a lead, not proof of a defect. With no history, inspect current call paths and state that change frequency is unknown. Respect existing domain language and relevant decisions using [project-knowledge.md](project-knowledge.md).

Trace a representative behavior from callers through implementation and tests. Look for a rule scattered across callers, duplicated invariants, leaking configuration/error contracts, or a change that requires coordinated edits in unrelated places. Cite inspected source at the relevant revision and explain the maintenance consequence; file size, function count and naming alone do not establish a problem.

Consider whether a smaller interface could hide real complexity and let callers and tests observe a coherent behavior. Ask what would happen if an abstraction disappeared: would complexity disappear, or spread into callers? This deletion test is a heuristic, not an instruction to delete. Thin compatibility adapters, authorization boundaries, protocols and independently deployed interfaces can earn their place without a large implementation. Do not collapse them merely to make a module look deeper, move all complexity into a monolith, or add hypothetical extensibility solely for tests.

## Compare useful candidates

For each supported candidate, explain:

- Observed friction and affected callers/contracts, with source pointers.
- A proposed boundary change and how it reduces coordinated maintenance or improves behavioral verification.
- Compatibility, security, persistence, deployment and migration costs where relevant.
- The smallest alternative, including leaving the structure alone; confidence and remaining unknowns.
- Existing regression protection, missing acceptance checks, and a staged/rollback approach if implementation is later requested.

Prioritize concrete current costs over speculative elegance. If no candidate has enough benefit, say so. Use a compact comparison in chat; diagrams or a saved report are optional when they help or were requested, not mandatory HTML, CDN use, new files, or extra agents.

## Reconnect only within authorization

An assessment ends with recommendations and unresolved choices. A selected candidate or an approved plan carries into the existing maintenance workflow; do not restart the interview. Reconfirm only consequential new choices. Approval to assess, discuss or record a decision does not authorize code edits, dependency installation, commits, or tracker changes.

For an authorized refactor, preserve the agreed behavior and exact negative/compatibility constraints. Reuse [test-strategy.md](test-strategy.md) and the repository's test interfaces before changing structure, then verify each bounded change and the original caller flow. Carry the same contract and evidence into [work-coordination.md](work-coordination.md) when a handoff is needed.

Method inspiration: [Matt Pocock's architecture assessment](https://github.com/mattpocock/skills/tree/main/skills/engineering/improve-codebase-architecture). This local adaptation does not depend on its skill chain, prescribed vocabulary, report format or parallel execution.
