---
name: codegraph-bootstrap
description: Set up or diagnose Colby McHenry CodeGraph for a selected project in Codex, Claude Desktop or DeepSeek Harness on supported platforms. Use for explicit CLI/index/MCP setup or repair; ordinary code navigation should reuse available tools without invoking an installer.
---

# CodeGraph setup for the selected host

Use the upstream `@colbymchenry/codegraph` CLI directly. This skill contains no
CodeGraph runtime. An installed skill is not evidence that its CLI, index or
MCP server is usable. Keep setup separate from ordinary repository work.

## Establish the requested scope

Task-specific tool restrictions apply before every preflight step. When shell
use is unavailable or prohibited, use native file reads and advertised MCP
tools; leave executable/version checks unverified. Do not run `bash`, `cat`
or a shell directory listing merely to inspect evidence. No preflight recipe
overrides the user's permitted tool set.

Inspect the platform, target repository, dirty files, executable availability,
installed version/help and the selected host's MCP registration before changing
anything. Read configuration only from explicitly selected host/profile files;
never recursively grep a home, config tree or filesystem for registration.
Do not read `.credentials.yaml`, `.env*`, sessions, storages or account files.
Exclusions must apply **before opening files**, not by filtering grep output.
Do not dump environment values or process argument lists; these can contain
credentials and unrelated task text. Start with current advertised tools and
one `command -v codegraph` / native executable lookup. If both are absent,
report that limit; do not exhaustively search other homes, package stores or
processes. Reaching a missing-runtime answer is a valid diagnostic endpoint.
A missing tool is a setup limitation, not a reason to bootstrap every agent.
Do not treat `status` as necessarily read-only: some versions repair indexes.

For DeepSeek configuration inspection, use the stdlib-only
[selected-file probe](scripts/inspect_dsh_config.py) with the actual `DSH_HOME`
and active profile, as described in
[host-adapters.md](references/host-adapters.md). It prints only paths, states
and a literal-mention boolean, never configuration values. A mention is not
registration and no mention is not proof about uninspected profiles. If Python
is unavailable, inspect only the same explicitly selected files using native
tools and disclose the missing probe. Never replace it with a recursive scan.

Preserve an existing working installation. If setup is authorized, read
[references/native-setup.md](references/native-setup.md), then choose only the
needed operations: reviewed version installation, selected-project indexing,
or registration for the explicitly selected host. Read
[references/host-adapters.md](references/host-adapters.md) for that host's schema
and skill-discovery boundary. Reuse current authorization; host approvals still
apply. Back up affected configuration/instruction files before changing them.
Prefer project-local registration when that host supports it; preserve the
scope of an existing registration when repairing it. Claude Desktop account
skills, Desktop Code skills and local MCP registration are separate targets.

Do not add global startup hooks, register unselected agents, change approval policy,
or auto-install missing software during session startup. Those effects require
an explicit request for that scope. Do not run the legacy PowerShell bootstrap
wrappers as the default path on any platform.

## Verify the actual connection

Check the executable version and the exact configured command/path. Resolve the
MCP tool advertised in the new/current session rather than guessing a tool
name. A config entry or host server-list entry alone does not prove a live
connection. On an authorized indexed project, ask a narrow structural question
and check a known relationship against current source. Keep unobserved runtime
behavior, freshness, dynamic edges and missing native events unverified.

Successful queries with no visible errors do not prove an uninterrupted
connection: the host can reconnect before the next call. Report current
callability separately from interruption and recovery. Confirm those events
with same-run lifecycle records; when unavailable, say **not observed;
occurrence/recovery unverified**, never **did not happen**. A missing fault
marker or `no-daemon` stop result does not establish that a failure control
fired. Do not widen configuration or log searches to manufacture certainty.

Different response content/order or a match with disk source does not establish
a cache miss or bypass. Report source agreement separately. Without same-run
cache telemetry or an observed bypass control for the relevant layer and
requests, leave cache behavior unknown; a miss is not a bypass.

If setup fails, preserve the first diagnostic and inspect the bounded cause;
do not repeatedly install, clear database locks or restart all clients. Normal
coding can continue with native search and source reads. Report installed,
registered, callable and functionally checked as separate states.

For Personal Work Agent integration, follow its optional CodeGraph navigation
reference when available: graph results assist discovery, and source/tests
remain authoritative. Do not promise token or quality gains before a matched
pilot including setup cost, complete usage, retries and resident context.

## Portable distribution

This package omits legacy PowerShell helpers. Use only the selected native host workflow; importing it does not install CodeGraph or connect MCP.
