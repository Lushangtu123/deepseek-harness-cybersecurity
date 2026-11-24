# Token-efficient work

Use this reference only when token, context, verbosity, or implementation size is a material concern. Optimize the complete task, not one message: fewer output tokens or lines of code do not count as a win if they cause retries, hide evidence, weaken verification, or leave incomplete work.

## Minimal correct implementation

For code changes, stop at the first option that fully satisfies the acceptance criteria and repository constraints:

1. No implementation change is needed; configuration, documentation, or an existing capability already provides the behavior.
2. Reuse or adjust an appropriate existing path, abstraction, test helper, or dependency.
3. Use the language standard library or native platform capability.
4. Use an already-resolved dependency consistent with repository conventions.
5. Add the smallest new logic, file, dependency, or abstraction that makes the verified behavior clear and maintainable.

Do not trade away trust-boundary validation, authorization, error handling that prevents data loss, accessibility, compatibility, observability, explicit requirements, or meaningful tests. Prefer a straightforward multi-line implementation over a clever one-liner when it is easier to review or safer to change. Avoid speculative extension points, wrappers, configuration, and cleanup outside the affected boundary.

If `ponytail` is installed and applicable, use it when the user requests it or when a bounded implementation has genuine room for over-building. Its output still passes the repository-native feedback loop and quality gates. Do not require or install it: the ladder above is the native fallback.

## Compact communication

Keep progress and final reporting concise by removing repetition, narrative about routine tool use, and unused alternatives. Preserve exact commands and outcomes, changed files, material assumptions, errors, risks, limitations, citations, and next actions that require the user. Do not compress an unresolved diagnosis, security finding, review rationale, or specification until the decision-relevant facts remain unambiguous.

If `caveman` is installed, use it only when the user explicitly requests that style or when concise reporting is the actual deliverable. Treat it as presentation guidance, not a replacement for investigation, verification, or reasoning. Do not claim net token savings without a same-task provider-level comparison.

## Document-to-text conversion

For semantic search, summarization, or extraction where layout is not authoritative, a Markdown or plain-text intermediate may reduce context and improve navigation. Keep the original file as the source of truth and retain page, slide, sheet, or section references when available.

Use an already-available MarkItDown installation only as an optional extraction helper. Do not install it implicitly. Prefer the format-specific document, presentation, spreadsheet, or PDF skill when the task depends on layout, tracked changes, comments, formulas, charts, images, pagination, accessibility, or editability. Sanitize untrusted inputs and use the narrowest local conversion surface available.

## Large-input compression

Compress only large, repetitive, recoverable input such as logs, test output, or machine-generated JSON/CSV when the original remains available on demand. Bypass compression for small inputs and when exact source text, code, ordering, formatting, or absence of a field is evidence. Recover the original immediately when the compressed view does not support a confident conclusion.

Do not install or globally enable Caveman 2, a proxy, hook, or another interception layer merely because compression could help. When such a layer is already configured and the task is eligible, keep it reversible and fail open to the original content. Never let it change the destination of credentials or data, and do not use it to obscure security, authentication, migration, or destructive-operation evidence.

## Verify the optimization

For substantial repository discovery, an already-available CodeGraph can be a
targeted retrieval helper; follow [codegraph-navigation.md](codegraph-navigation.md).
Reduced tool calls or processed tokens do not imply a smaller resident context
or equal answer quality. Include setup/index cost and verification in a matched
comparison; do not install the runtime merely to shorten an ordinary task.

Hold quality constant before evaluating savings:

- Run the same acceptance, regression, security, lint, type, build, and review gates that the uncompressed workflow requires.
- Compare complete provider-reported input, cached-input, and output totals on matched tasks when making a token-savings claim; response length alone is insufficient.
- Count retries, recovery calls, tool calls, and additional turns.
- Reject the optimization for any workload where correctness, completeness, maintainability, or total billed usage regresses.
