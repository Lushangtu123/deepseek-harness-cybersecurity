# Scoped functional acceptance

Read when an affected API, CLI, background job, webhook, or browser flow crosses a boundary that unit tests do not observe. Use only the relevant flow; a local wording or isolated calculation change does not require an acceptance campaign. Reuse repository-native tests, fixtures, clients, and available browser tools; do not install a runner, enable telemetry, or contact a live service merely to perform QA.

## Define the outcome

Derive acceptance from the requested behavior and current contract, not from what the implementation happens to return. Distinguish a request being accepted from work completing: an HTTP success, queued job, or zero exit code alone may not establish the promised state change or output.

Keep a small case table for the affected flow:

| Case / initial state | Action | Expected observable outcome | Final-state evidence |
|---|---|---|---|
| Relevant successful path | Input or operation | Contracted result | Output plus state or downstream effect |

Add only contract-relevant boundaries: invalid input or denied access, dependency failure, retry/duplicate delivery, cancellation, or partial completion. Do not assume every operation is idempotent, cancellable, or synchronous. Resolve material ambiguity before labeling its behavior a defect; do not invent new product requirements from the case list.

## Execute within a safe boundary

- Use isolated, owned fixtures with known initial state. Inspect invoked scripts and configuration for side effects under [permissions.md](permissions.md) before executing them. Authorization to modify code does not authorize production data changes, messages, payments, or live dependency probes.
- Prefer local fakes or controlled dependencies for failures and retries. If the real boundary cannot be exercised safely, state which behavior the substitute cannot verify rather than claiming an end-to-end pass.
- Record enough to replay the case: command or interaction, nonsecret inputs, fixture identity, initial/final state, and relevant output. Capture browser evidence only where it establishes the claimed UI behavior; screenshots do not prove an unseen backend effect.
- Bound asynchronous waits and retry counts using the contract or task budget. After an uncertain external mutation, reconcile state according to [permissions.md](permissions.md); a timeout is not permission to repeat it. Clean up only fixtures created for this run, within their authorized scope.

## Report and retest

A successful request may follow an invisible retry or reconnect. Confirm event occurrence and recovery with the relevant same-run lifecycle evidence, not the lack of an error in the calling interface. Without that evidence, current success is observed while interruption/recovery remains unverified. When a failure is injected, first verify the fault fired; an unexercised control cannot pass a recovery case. Do not expand into credential, process-argument or unrelated log searches to fill an evidence gap.

Distinguish observed product defects from setup failures, blocked access, unavailable dependencies, and checks not run. A missing environment is not a failing product case; a stubbed check is not a live integration result. After a repair, replay the original case and the relevant neighboring case against the final code, and report outcomes with the evidence and remaining boundary gaps. A QA or review request alone does not authorize implementing discovered fixes.

This is a locally written, narrowly scoped adaptation of ideas in [gstack's system-functional QA guidance](https://github.com/garrytan/gstack/blob/main/qa/sections/system-functional.md). It does not require that plugin or adopt its external-action defaults.
