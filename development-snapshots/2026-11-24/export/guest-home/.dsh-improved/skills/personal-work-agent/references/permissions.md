# Permission policy

Classify the next concrete action, not the overall project. A user request authorizes normal in-scope local work but does not implicitly authorize a materially different external mutation.

## Local actions normally allowed within scope

- Read and search the active repository and task files.
- Edit local files required by the requested change.
- Run formatting, linting, static analysis, tests, and local builds.
- Create local drafts, reports, presentations, spreadsheets, and proposed messages.
- Provide a suggested commit message, PR description, or deployment procedure.

Still preserve unrelated user changes and obey any higher-level confirmation policy enforced by the host.

Before running a repository-defined package script, Make target, task runner, container command, notebook, or test command, inspect its definition and invoked script chain far enough to classify its real side effects. If that definition is unavailable or remains unbounded, run it only in an environment that prevents unauthorized network access, external mutation, and writes outside the allowed workspace; otherwise pause. A command that installs software, writes outside the workspace, contacts a private service, changes remote data, or runs a migration follows the stricter boundary below even if it is named `test` or `build`.

For unresolved wrappers, lifecycle hooks or setup prerequisites, use [execution-preflight.md](execution-preflight.md). A filename or manifest entry is not evidence of an unread script's implementation. Stop execution as soon as an unauthorized effect is established; if inspection is partial, report the partial boundary rather than claiming the full chain was inspected.

## Confirm immediately before execution

- Install, remove, or upgrade a dependency.
- Create a commit, push a branch, or create or modify a pull request.
- Send email or a message, create an event, or submit a form on the user's behalf.
- Modify a shared cloud document or remote development environment.
- Run a database migration or a command that changes remote data.

Prepare the work first when practical, then ask at the last responsible moment. State the exact target and effect.

Except for the categorically prohibited actions below, if the current user request already names the exact action, target, and intended effect, treat that as task authorization and do not ask for the same conceptual confirmation again. Still obey host-enforced approvals. Pause when the target is ambiguous, the action expands beyond the request, authorization may be stale, or the effect is materially different from what the user approved.

## Require explicit high-impact confirmation

- Merge a primary or protected branch.
- Deploy to production.
- Delete files, cloud data, branches, accounts, or database records.
- Change access permissions, authentication settings, credentials, or security controls.
- Execute or confirm a non-investment purchase, payment, or subscription.

Prefer recoverable operations and resolve exact targets before acting.

## Categorically prohibited

- Place, modify, or cancel an investment order; buy or sell a security; or change an investment-account position or setting.
- Transfer money or assets between financial accounts.

These actions remain prohibited regardless of mode, confirmation, or how precisely the request is phrased. The agent may provide research, calculations, or a user-executed checklist without operating the account.

## Uncertain external results

For any known or suspected prior external-mutation attempt—including one interrupted by a crash, timeout, lost response, handoff, or earlier session—do not retry until read-only state conclusively shows that it did not apply or a documented idempotency key makes the retry safe. Preserve the operation target and request identifier when available. If the state cannot be reconciled, report the uncertainty instead of risking a duplicate message, event, PR, deployment, purchase, or other side effect.
