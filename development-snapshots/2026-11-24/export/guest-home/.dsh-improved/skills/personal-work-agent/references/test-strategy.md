# Contract-driven test strategy

Read when choosing regression coverage or when an affected parser, serializer, normalizer, transformation, or state machine has many meaningful inputs and a stable property. Skip property machinery for wording, wiring, or a narrow example-only contract. Keep the existing test runner and conventions.

## Check test value before adding machinery

For the affected behavior, identify the observable contract, a credible regression the assertion would catch, and the gap in existing coverage. Prefer extending an existing test when it can express the same failure clearly; a new test file, framework, or helper is not itself progress. Keep this judgment lightweight for an obvious bug regression.

Test through a real public boundary or a stable domain interface where practical. Do not expose production internals, add public exports, or introduce an otherwise unused abstraction solely to make a test convenient. Necessary design changes should have a production justification independent of the test.

Keep assertions that protect meaningful protocol fields, security boundaries, public API compatibility, or reviewed golden/snapshot contracts. Low-level or exact-output assertions are not inherently low-value; judge their contract, not their shape. Do not replace them with a weaker broad assertion just to reduce test count.

An explicit request to audit tests starts with read-only findings: contract protected, credible failure, coverage overlap, and evidence for any proposed change. Do not turn an ordinary fix into a whole-suite cleanup, or automatically delete tests because they appear redundant. Changes to existing tests must preserve the behavior they protect and remain within the user's requested scope.

## Reuse the contract in test-first work

For an authorized test-first change, reuse the confirmed brief/spec and existing public interfaces. Resolve material interface ambiguity, but do not ask the user to reconfirm every test or an already-approved boundary. Use the available `tdd` workflow or the native maintenance feedback loop, not both instruction chains.

Work in vertical slices: one meaningful behavioral test fails for the intended reason, the smallest implementation makes it pass, then choose the next slice from what was learned. Do not prewrite a speculative suite before implementing any behavior. Derive expected values independently from the confirmed contract or worked examples, not a copy of production logic. Keep any behavior-preserving refactoring scoped and green, then rerun affected checks; a passing slice is not evidence that all acceptance criteria are complete.

Keep exact requirements and links to executed checks in the existing task record. Handoff preserves which acceptance items passed, failed, were blocked or remain untested; it must not collapse them into an unsupported "tests pass" summary. See [work-coordination.md](work-coordination.md).

## Choose an observable contract

Use the specification or callers to identify the property before choosing a generator. Useful candidates include:

- Round trip: decoding an encoded supported value preserves its documented meaning, including escaping and empty values.
- Idempotence: applying a documented canonicalization twice gives the same result as once.
- Invariant: a permitted state transition preserves the defined conservation, ordering, or boundary rule.
- Differential check: an independent trusted implementation agrees over the same supported domain.

Do not assume these properties automatically hold. Lossy conversions, timestamps, randomization, and intentionally noncanonical outputs can invalidate them. Resolve material contract ambiguity rather than silently changing public behavior to fit a test.

## Use the smallest useful test mechanism

1. Retain an example that reproduces the reported defect and nearby legitimate behavior.
2. If properties add meaningful coverage, use the repository's existing property framework. Otherwise prefer bounded table-driven or exhaustive tests using current dependencies. A new framework requires the normal dependency-approval boundary.
3. Define the input domain explicitly. Include meaningful edge classes such as empty values, delimiters, Unicode, limits, and equivalent representations only where the contract supports them. Avoid filters that discard nearly every generated input; check that the tested domain is nonempty and representative.
4. Make failures replayable: record the minimized counterexample, seed or replay identifier when applicable, and command. Preserve a deterministic regression for an important discovered defect; a seed alone can change meaning across library versions.
5. Demonstrate that the check detects the defect on the original implementation in an isolated copy when practical, then run it and neighboring tests on the final code.

An identity assertion, a second copy of the production algorithm, or comparing two values produced by the same broken path is not an independent oracle. A round trip can also hide matching encoder/decoder mistakes, so retain specification-derived examples. When a property fails, distinguish an implementation bug, a false property, an invalid generator, and an environment failure before editing production code.

Report the actual domain and checks run. Passing finite generated cases is evidence, not proof over every input. No automatic dependency install, fuzzing service, long-running campaign, or unrelated test rewrite is implied.

Further reading: [Trail of Bits property-based testing skill](https://github.com/trailofbits/skills/blob/main/plugins/property-based-testing/skills/property-based-testing/SKILL.md). This reference is a locally written workflow; it does not install or require that plugin.

The test-value criteria are locally written guidance informed by [gstack's test-value bar](https://github.com/garrytan/gstack/blob/main/docs/test-value-bar.md); no gstack runner, telemetry, or dependency is required.
