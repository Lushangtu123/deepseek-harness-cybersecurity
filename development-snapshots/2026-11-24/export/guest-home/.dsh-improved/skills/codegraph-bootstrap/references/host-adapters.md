# Selected host adapters

Reviewed 2026-10-26. User target "Claude" here means the Desktop application.
Select only requested hosts and preserve their existing settings. Examples in
`assets/` are inert templates with required absolute-path placeholders; do not
apply them until a reviewed CodeGraph executable and target repository exist.
They do not install the runtime, build an index or grant filesystem access.

## Claude Desktop: skill and local server are separate

**Skills:** use Customize > Skills > Add skill > Upload for a ZIP containing
one `<skill-name>/SKILL.md` root and its references/assets. Confirm the account,
review the exact files before upload, preserve an existing same-name skill,
and keep sharing/publishing outside the import. `~/.claude/skills` alone does
not install an account skill in Desktop chat/Cowork. The Desktop Code surface
can use Claude Code discovery, but that is a separate observed execution path.

**Local CodeGraph:** use the Desktop local MCP/extension mechanism supported by
the installed app. It is not a cloud custom-connector URL. When the Developer
configuration UI exposes `claude_desktop_config.json`, merge only the selected
`mcpServers.codegraph` object from
[the JSON example](../assets/claude-desktop-codegraph.example.json), preserving
unrelated entries and backups. On macOS the documented configuration location
is `~/Library/Application Support/Claude/claude_desktop_config.json`; use the
actual application's UI to resolve it, not a guessed Claude Code settings file.
The alternative Desktop extension route needs a separately reviewed MCPB;
this skill does not ship one or claim the JSON template is an extension.

Use an existing absolute executable path and explicit `serve --mcp` arguments,
plus process environment controls. Do not enable auto-allow rules or change
approval policy. Reconnect only when it will not interrupt active user work,
then verify tool discovery and a known relationship in the actual Desktop
surface. Chat, Cowork and Code have different local-connector boundaries; a
skill upload does not make a local graph available to cloud execution. Check
the surface and native connection rather than promising universal access or
publicly exposing a local server.

## DeepSeek Harness

Resolve the active home/profile from the current host context, not by scanning
other homes. For an authorized read-only registration check, the only initial
files are `<dshHome>/cordis.patch.yml` and the selected
`<dshHome>/profiles/<profile>/cordis.yml` / `cordis.patch.yml`. Use the installed
skill's `scripts/inspect_dsh_config.py` with an available Python 3 interpreter:

```text
python3 /ACTUAL/SKILL/BASE/scripts/inspect_dsh_config.py --dsh-home /ACTUAL/DSH/HOME --profile ACTUAL_PROFILE
```

Omit `--profile` when unknown; do not enumerate profiles to fill the gap. The
probe rejects symlinked selected files/directories and reads at most 1 MiB per
file. It does not parse/evaluate YAML or `!!js`, print config values, traverse
subtrees or verify registration/connection. It is a diagnostic, not a sandbox
against hostile concurrent filesystem changes. A custom configuration source
needs a separately identified exact path and authorization; keep it unknown
until resolved. Never read credential/account files, dump process argv/env, or
use recursive grep followed by a filename filter as an exclusion boundary.

The local Desktop build 0.2.1-rc.3 bundles `dsh-skill-filesystem` and
`dsh-mcp-client`; its installed package documentation was checked in addition
to upstream docs. Respect configured homes/provider roots when they differ.

**Skills:** install selected direct directory bundles under `<dshHome>/skills`
(normally `~/.dsh/skills`) or the intended project's `.dsh/skills`. Do not copy
a nested Codex plugin root and assume recursive discovery. Preserve same-name
customizations and check the actual catalog/skill load afterward. Shared
`.agents/skills` affects other clients and is not the default install target.

**MCP:** use one `@deepseek-ai/dsh-mcp-client` entry in the intended Cordis
plugin scope, as in [the YAML example](../assets/deepseek-codegraph.example.yaml).
Merge through the app's supported configuration editor or the verified active
plugin list, not by replacing a profile or assuming a Claude `mcpServers`
object is accepted. Preserve unrelated providers, credentials and permission
rules. Use `serverName: codegraph`, `transport: stdio`, the existing absolute
binary path, `args: [serve, --mcp]`, the selected repository `cwd` and explicit
environment controls. Never invent an upstream `--target deepseek` flag.

The client discovers names such as `mcp__codegraph__codegraph_explore`; the
actual advertised list is authoritative. Startup failure can leave the app
running without that server's tools. Registration/config parsing alone is
therefore not a functional pass. Stdio negotiation can launch a temporary
probe before the serving process, so use the server invocation, not `init` or
an installer as the configured command. Keep unknown index freshness and
unresolved edges visible, and fall back to native source inspection.

## Codex

Keep the existing Codex branch in [native-setup.md](native-setup.md). A request
to adapt the instructions for Desktop/Harness does not authorize registering
MCP on all clients or altering the running session's permissions.

## Sources

- [Claude skill packaging](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)
- [Claude local MCP](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
- [Desktop connector boundaries](https://support.claude.com/en/articles/11725091-when-to-use-desktop-and-web-connectors)
- [Harness filesystem provider](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)
- [Harness MCP client](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)
