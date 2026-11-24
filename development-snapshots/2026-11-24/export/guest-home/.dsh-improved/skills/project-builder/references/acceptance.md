# First-release acceptance

Use before claiming the agreed release works. Choose checks from actual requirements and risk, not a universal framework checklist.

## Observable contract

For each essential journey identify initial state, user input/action, expected result, and durable final state when persistence is promised. Cover important invalid input, failure, and recovery behavior. Use isolated owned fixtures; never send test messages, charge real money, or modify live data without explicit authorization.

| Boundary in this project | Evidence that matters |
|---|---|
| CLI or library | Actual public command/API, outputs and exit/error behavior; avoid tests that only import internal helpers |
| UI | Exercise the core interaction and inspect the resulting state; check relevant keyboard, labeling, loading/error and layout behavior with available tools |
| Service and storage | Exercise the real local request path and observe resulting state; verify persistence across a fresh process when promised |
| Background work | Observe the promised completed outcome, not only a queued/accepted response; bound waits and retain diagnostic evidence |
| External integration | Distinguish fixture/contract checks from authorized live verification; unavailable live access remains an explicit limitation |

Do not impose irrelevant rows. A local utility need not gain a database or browser suite. Conversely, do not drop auth/access boundaries, validation, data integrity, or other agreed requirements to obtain an early green result.

## Fresh evidence

- For multi-command verification, retries or precise runtime versions, use the bundled [command evidence helper](../../personal-work-agent/references/command-evidence.md) before running and reporting checks. If used standalone without the helper, retain original conclusive tool outputs and disclose the unavailable structured gate; do not install PWA, forge receipts or rerun an uncertain external action.
- Generate and check the helper's verification block for those reports; keep missing command history, native image/interaction checks and final acceptance as explicit unverified gaps until separately observed. Checking a block never certifies the host's surrounding final prose.
- Run the appropriate focused tests and available static/build checks after the final edit. Observe conclusive results and relevant warnings, not just command submission.
- Make critical checks capable of failing: include a meaningful negative control or demonstrate the target regression. Do not weaken acceptance or assertions to fit the implementation.
- Verify setup/run instructions against the actual paths, entrypoints, environment and resolved dependencies. If a clean-environment check is not possible, say so; do not claim reproducibility from an already-warm machine.
- Inspect integrated artifacts and changed paths, including unexpected generated files and secrets. Confirm unrelated user content remains intact.
- Record acceptance as passed, failed, or blocked, with evidence and scope. Deferred work counts as excluded only when the user's agreed release boundary excludes it; blockers cannot silently become non-goals.

## Readiness is scoped

A generated scaffold is not a working MVP. A locally verified first release is not a deployed, load-tested, security-certified, backed-up production service. Name the highest state actually demonstrated and report unresolved checks. Deployment planning may be delivered without performing deployment.
