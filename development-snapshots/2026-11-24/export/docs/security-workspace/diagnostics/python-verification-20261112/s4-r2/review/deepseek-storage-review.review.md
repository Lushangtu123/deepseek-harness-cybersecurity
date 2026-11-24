**Verdict: preflight pass with limitations.** Findings 1–4 are closed for the reviewed fail-closed paths; finding 5 is only partially closed. I found no new concrete source-level bypass in the supplied excerpts. This is not R3 or live/independent acceptance.

- **(1) Rehashed Node envelope substituting worker/controller: closed.** `validVerificationPlan()` directly compares `v.code['python_execution_verify.py']` and `v.verifierControllerSha256` to `shippedVerifierHash(...)`, and compares dependency metadata to the shipped lock. The regression test mutates worker hash, verifier-controller hash, dependency package version, and dependency file hash, then expects `verification-plan-missing-or-changed`. That defeats consistent rehashing. Residual: reviewer-launcher pin still relies on `staticSnapshot.launcherSha256` rather than a direct shipped-hash comparison in the excerpt.

- **(2) Missing planned receipts not explicit: closed.** The final loop emits `verification-request-unobserved:<caseId>` for every planned request not seen. The test removes a receipt/artifact and asserts that blocker plus reduced `supportedCases`. Good.

- **(3) SourceRoot/stage closure: closed for the inspected run.** The controller stages only the checked payload. `InspectEngine` asserts the bind mount source is the private `stage`, the staged source hash map exactly equals the manifest, files are not symlinks, and stage mode is private. The extra synthetic file outside the manifest was absent from stage. This is concrete stage evidence for that run, not a proof for unobserved runs.

- **(4) Candidate dependency metadata: closed.** Python rejects any lock unequal to the shipped lock, builds dependencies from the fixed lock, and rechecks lock/tree during verify. Node compares freeze dependencies and `dependencyPackages` against the shipped lock and checks dependency inputs in each receipt. No independent candidate-controlled policy comparison remains visible.

- **(5) Raw count and Mac/VM identity: partially closed.** The packet now supplies `rawMapping` (5), `inspected:15`, `dailyCounts:[169,42]`, unchanged `dailyProtection`, and matching VM/Mac raw score hashes with a distinct canonical hash. This closes basic artifact consistency, but the counts are not reconciled in the packet, and identical hashes under `vm-quality.json` and `mac-quality.json` labels do not attest host identity. That is a residual trust/attestation limitation, not a demonstrated safety blocker.

Current logs are green; historical red tests are not independently visible here. No R3 or live acceptance is claimed.
