# Optional CodeGraph navigation

Use for an unfamiliar repository, cross-file call paths, or a change whose
dependents are costly to find manually. Skip graph setup for a localized edit
whose relevant source and tests are already known. CodeGraph is optional code
navigation, not a prerequisite for maintenance or a correctness certificate.

## Discover the actual capability

- Resolve the current MCP tools or an existing CodeGraph CLI. An installed
  `codegraph-bootstrap` skill, database file, or old conversation is not proof
  of a callable server or a current index. Do not invent tool names.
- If unavailable, use repository-native search and direct source reads. Normal
  maintenance does not authorize installing CodeGraph, registering MCP,
  indexing a repository, changing telemetry, or adding startup hooks. Use the
  bootstrap skill only for an authorized setup/repair request.
- Establish the exact project root, current working-tree changes and observable
  index state. Do not treat a recent index timestamp or an enabled watcher as
  proof that all changes were incorporated. Unknown freshness stays unknown.
  Refresh/rebuild only within authorized local-write scope; a nominal status
  command may itself repair state, so inspect its current behavior first.

## Ask a narrow structural question

Use the actual advertised tool schema. Current upstream commonly lists
`codegraph_explore`; other graph tools may be hidden unless configured. Name
the relevant file, symbol, entry point and intended question. Request the
source/call path needed for the task, rather than a whole-project dump. Stop
once the boundary is understood; use returned paths for targeted source reads
instead of repeating overlapping graph queries.

Treat graph output as evidence to reconcile with current code:

- Check the relevant declarations and call sites in current source before
  editing. Follow runtime wiring, configuration and tests when static edges
  cannot establish the requested behavior.
- Preserve unresolved dynamic dispatch, reflection, dependency injection,
  generated-code gaps, heuristic provenance and truncated results. A missing
  edge or empty caller list is not proof of dead code, no impact or safety.
- On stale, unavailable, inconsistent or insufficient output, return to native
  search and source inspection. Report the actual limitation; do not repeatedly
  restart services, clear locks or rebuild databases to obtain a successful
  query. A recovery action needs its own concrete scope.
- Graph results do not replace regression, integration, security or user-flow
  verification. Keep the normal maintenance and functional acceptance gates.
- Separate symbol absence from query coverage: a filename miss does not prove
  a function is absent. Inspect the relevant source when that distinction
  matters. Likewise, a displayed dependency/caller total may include imports
  or other references; confirm actual calls before reporting call counts.
- Successful graph calls prove current responses, not an uninterrupted MCP
  history. The client may reconnect before the next request. Use same-run
  lifecycle records for interruption/recovery claims; if unavailable, leave
  them unverified rather than inferring that no disconnect happened.
- Changed graph results or matching disk source do not prove a cache miss or
  bypass. State source agreement separately; leave cache behavior unknown
  without same-run telemetry for the relevant cache layer and requests.

## Measure before making efficiency claims

Fewer calls can still leave more source resident in a long conversation. Keep
queries narrow and retain references to recoverable originals. Do not remove
necessary source, uncertainty or verification to achieve a token target.

For an explicitly requested pilot, use a pinned copy of the user's repository
and representative call-chain, impact and maintenance tasks. Compare fresh
workspaces with and without graph access under the same model, tools,
permissions, task and acceptance checks. Prevent the control from accessing
the graph through another route. Run repeated trials (at least three per arm
for a version/efficiency comparison), retain failures, and count index/setup,
retries, elapsed time, tool calls, complete provider usage and residual context
separately. Require unchanged acceptance results and independently check known
critical relationships; any missed critical dependency or worse correctness
blocks adoption for that workload. Report unmeasured cost or quality as such.

## Sources and scope

Reviewed 2026-10-26 against upstream 1.6.2/main documentation; inspect the
installed version before executing setup or CLI commands. No upstream runtime
or installer is bundled by this reference.

- [Upstream project and tool surface](https://github.com/colbymchenry/codegraph)
- [Static graph boundaries](https://github.com/colbymchenry/codegraph/blob/main/src/mcp/dynamic-boundaries.ts)
- [Residual-context measurement](https://github.com/colbymchenry/codegraph/blob/main/docs/benchmarks/residual-context-occupancy.md)
- [Telemetry and update-check controls](https://github.com/colbymchenry/codegraph/blob/main/TELEMETRY.md)
