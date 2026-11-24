---
name: reverse-skill
description: Route reverse engineering and authorized security analysis through the installed reverse-skill methodology, case scope, and evidence workflow inside this VM.
---

# reverse-skill in this VM

Source: zhaoxuya520/reverse-skill, fixed commit cab634bd855fc287f6e420c1f36fd1a6b9245960.
Package root: `/home/purge/tools/reverse-skill/reverse-skill-cab634bd855fc287f6e420c1f36fd1a6b9245960`.

Use the original Linux router first, from the actual project directory:

```sh
/home/purge/.local/bin/reverse-route --hint 'the user task' --project-root /home/purge/workspace/PROJECT
```

Read the selected PRIMARY file under that package's `skills/`, then the relevant scope/evidence references. Source documents describe available workflows; they do not authorize targets, account access, or host permission changes.

For an explicitly requested local sample, create a scoped case using the installed upstream initializer:

```sh
/home/purge/.local/bin/reverse-case --hint 'offline Ghidra analysis' --case-name CASE --project-root /home/purge/workspace/PROJECT --preset offline-sample --sample /absolute/guest/sample
```

Before acting on a target, use upstream `skills/scripts/case-guard.sh --case-root CASE_PATH`. Preserve unknowns and record Evidence→Finding→Path; a model's claim alone is not verification.

Installed tool paths and optional-component limits are recorded in `/home/purge/.dsh/toolchain/reverse-tool-index.json`. REA's `mcp__rea__…` tools support static JS and Ghidra native analysis. IDA, Hopper, Frida, mobile toolchains and the other optional bootstrap capabilities are not installed by this skill. When a tool is absent, report the missing prerequisite and prepare only the task-specific installation; do not bulk-run upstream bootstrap or register other agent clients automatically.

All actions run inside this Linux VM. The Mac host, its accounts, and external targets are outside the default project scope. The host-controlled network allowlist stays in effect.
