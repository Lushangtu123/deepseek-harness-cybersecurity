# Host compatibility

Use when installing, importing or troubleshooting this skill on another host.
Ordinary tasks use the host's actual skill catalog and tools without a setup
audit. This is portable workflow guidance, not an adapter that adds tools,
filesystem access, background workers or account permissions.

## Shared behavior

- Read supporting files relative to the actually loaded skill, not a remembered
  Codex cache or another application's home. Resolve names/namespaces from the
  current host. A mention such as `$personal-work-agent` is a host-specific UI
  shorthand; natural-language requests can name the skill where supported.
- Use native read/edit/search, execution, questions and review capabilities.
  Do not fabricate Codex tool functions on Claude or Harness. A missing shell,
  browser, Python interpreter or specialist remains a capability gap.
- Run the bundled Python evidence helper only in an available authorized
  execution environment. If unavailable, retain native observations and mark
  structured verification unavailable; never invent receipts.
- Keep the same task scope, preservation, uncertainty, permission and outcome
  checks on every host. Tool/skill import, connection and a successful end-to-end
  task are separate observations. Never import credentials or approval settings
  from another host.

## Claude Desktop

Use the Desktop app's Customize > Skills import for account skills. Export one
ZIP per skill with one `<skill-name>/SKILL.md` root plus supporting resources.
Import Personal Work Agent and Project Builder separately if both are needed;
the Codex `.codex-plugin/plugin.json` is not a Desktop skill installer.
Review the files and destination before uploading; preserve existing same-name
skills and keep sharing/publishing separate. Enable the selected skill and
check actual invocation in the intended Desktop surface.

Claude Desktop contains different execution surfaces. Chat/account skills can
run in a hosted code environment; they cannot assume access to the user's Mac,
local repositories or a local CodeGraph database. Cowork and the Desktop Code
surface have their own filesystem/tool/connector boundaries. Detect the actual
surface and visible tools rather than promising that a local MCP works in all
of them. A repository supplied as an attachment is a separate snapshot.

`~/.claude/skills` is a Claude Code location, not a general account-skill import
for Desktop chat/Cowork. A Desktop Code session may use Claude Code discovery;
verify that actual session separately. Local CodeGraph access requires a local
MCP/desktop connector in a supporting surface; do not expose a local server
publicly to make cloud chat reach it. Use an authorized available snapshot or
native fallback when local access is absent.

## DeepSeek Harness

The local provider bundled with Desktop 0.2.1-rc.3 supports direct directory
bundles such as `<dshHome>/skills/personal-work-agent/SKILL.md`, normally under
`~/.dsh/skills`, and project roots under `.dsh/skills` / `.agents/skills`.
Respect actual `DSH_HOME`, provider settings and same-name precedence. It does
not recursively discover an arbitrary Codex plugin's nested `skills/` tree;
install each selected skill directory at the verified provider root.

Use the actual skill catalog and native `skill` operation when exposed; do not
assume Codex's colon namespace or tool APIs. Standard Markdown references and
local Python helpers remain conditional on available tools and permissions.
Harness MCP uses its own `@deepseek-ai/dsh-mcp-client` plugin configuration,
not a copied Codex TOML or Claude `mcpServers` object. For authorized setup,
use the selected host branch of `codegraph-bootstrap` if available.

## Verification limits

Directory/ZIP integrity and schema checks prove packaging only. Check visible
discovery, relevant reference loading and an actual permitted task on each
host before claiming behavioral compatibility. A task passed on Codex does not
qualify Claude or Harness, and different models/tool catalogs do not support a
controlled quality or token-savings comparison.

Sources reviewed 2026-10-26: [Claude custom skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills),
[Claude connector surfaces](https://support.claude.com/en/articles/11725091-when-to-use-desktop-and-web-connectors),
[Harness skills](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md),
and the matching local Harness 0.2.1-rc.3 provider/MCP documentation.
