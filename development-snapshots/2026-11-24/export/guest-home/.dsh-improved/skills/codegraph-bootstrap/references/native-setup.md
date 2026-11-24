# Native CodeGraph setup

Applies to macOS, Linux and Windows using an existing upstream CLI. Inspect the
installed version's `--help` before execution. Select the actual host rather
than treating all MCP configuration formats as interchangeable. Upstream 1.6.2
and its documented
Codex local setup were reviewed on 2026-10-26; that is a review reference, not a
claim that any local version is installed or that it remains the latest.

## 1. Inventory before mutation

Resolve `codegraph` with the platform's executable lookup and query `--version`
and `--help` if present. Inspect the selected repository and existing host MCP
entry (see [host-adapters.md](host-adapters.md)). Do not install PowerShell on
macOS to run the old wrappers. No shell or
npm registry access is necessary when a working installation already exists.

## 2. Choose the minimum authorized operation

- **CLI absent:** establish the requested installation location and a reviewed
  exact version. Prefer the official registry/vendor source; do not use an
  unpinned `npx`, auto-upgrade, or pipe a remote script into a shell. A skill
  update does not by itself install the CodeGraph runtime. Verify the chosen
  version's runtime requirements and package lifecycle effects first.
- **Index absent or stale:** indexing writes local project state and consumes
  resources. For an authorized selected project, inspect `init --help` or
  `index --help`, choose exclusions for dependency trees, generated artifacts,
  task archives and private material outside the intended scope, then initialize
  or refresh only that project. Current upstream `init` already indexes; do not
  automatically follow it with a duplicate full `index`. Preserve user work.
- **MCP registration missing:** use [the selected host adapter](host-adapters.md).
  The following CLI recipe applies to Codex only. Inspect the upstream installer and
  affected files. With the target/scope authorized, current upstream supports
  `codegraph install --target codex --location local --yes` in the selected
  project. It may edit project Codex configuration and agent guidance; preserve
  unrelated entries. `--yes` removes prompts, not authorization requirements.
  Global registration is an explicit scope choice, not the default repair.
  Do not add hooks or configure unselected agents. Claude Desktop and Harness
  use their own configuration branches; never pass an invented target to the
  upstream installer or select `--target all` for convenience.

An interrupted registration may already have written files. Reconcile existing
state before retrying; do not run an installer just to test whether it works.
If the installed CLI lacks a required scope, retain native-search fallback and
report that limitation rather than silently expanding to a global install.

## 3. Keep local setup from enabling telemetry

Upstream's anonymous usage telemetry is default-on and its MCP server can check
for updates. For an authorized setup, pass `DO_NOT_TRACK=1`,
`CODEGRAPH_TELEMETRY=0` and `CODEGRAPH_NO_UPDATE_CHECK=1` to the setup/index
process and the selected MCP server environment. Environment fields belong
inside the actual MCP configuration generated/managed for that target; inspect
its format instead of appending a second conflicting table. Do not rewrite
shell profiles or change unrelated servers. Never upload source or graph data
as part of setup. These controls do not block the intentional package download.

`codegraph telemetry off` changes stored user-level consent; use it only when
that persistent choice is requested. Process-scoped controls are sufficient
for a bounded setup/pilot without changing the user's other installations.

## 4. Verify and retain rollback

Record the exact binary/version, changed configuration paths, chosen project,
index status/limits and actual query outcome. Compare a known caller and an
unrelated same-name negative control against source. An empty result cannot
establish graph completeness. Startup/reconnection may require a fresh host
session; do not claim that editing config makes tools callable in this one.
Keep config backups and report a scoped rollback; upstream uninstall can remove
more than one installation, so do not run it blindly.

## Official sources

- [CodeGraph quickstart](https://colbymchenry.github.io/codegraph/getting-started/quickstart/)
- [MCP tool surface](https://github.com/colbymchenry/codegraph#MCP-tools)
- [Telemetry controls](https://github.com/colbymchenry/codegraph/blob/main/TELEMETRY.md)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
