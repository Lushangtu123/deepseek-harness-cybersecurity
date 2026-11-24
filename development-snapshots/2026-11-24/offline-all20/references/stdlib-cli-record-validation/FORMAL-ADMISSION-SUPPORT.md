# Formal Admission Support and Compatibility Notes

This file explains how the offline formal admission change relates to the
sealed 70-file B1–B4 recovery-close baseline and to older artifacts. It is not product
approval and does not add a runtime receipt.

## Supported formal surface

- `tools/experiment_runner.py` formal `prepare-*`, `compile`, `run`, `query`,
  `status`, `recover` and `cleanup`.
- `tools/judge.py` formal verification of a buffer-v2 / end-lf-padding-v1 raw
  stream.
- The existing frozen `tools/buffer_protocol_v2.py`,
  `tools/observer_template_buffer_v2.bt`, `tools/observer_render.py`,
  `tools/preflight_verify.py`, `tools/resource_guard.py` and the preflight tools
  are used as-is. Their bytes are unchanged.
- `query/recover/cleanup --attempt <n>` remain supported exactly as before.
  `--prepare-id <32 lowercase hex>` is additive and mutually exclusive with
  `--attempt`.

## Compatibility

- **Legacy observer artifacts**: still readable as diagnostic data by the
  explicitly legacy collector/parser path. They are not admitted as formal
  evidence and are never promoted by the formal runner or judge.
- **Old formal shim fixtures**: the recorded-shim regression helper now selects
  the v2 template explicitly. Old result files and historical reference data
  are preserved, not rewritten into modern passes.
- **Pure legacy behavior**: `observation_pure`, `buffer_protocol`,
  `buffer_protocol_v2`, `observer_render`, `structure`, `target_launcher`,
  `experiment_compile`, `layout_probe`, `zero_target_preflight`,
  `preflight_verify`, `preflight_selfcheck` and the three observer templates are
  byte-identical to the sealed baseline.
- **Existing state/code conventions**: invalid ownership is blocked with 78,
  semantic unknown/incomplete with 3, lock busy with 79, CLI ambiguity with 2.
  The judge keeps its existing unknown exit 3 convention. B1–B4 additionally
  require exact selector/filename/plan-id binding, role-based recovery routing,
  and durable resource-phase/parent associations; see
  `RECOVERY-CLOSE-CONTRACT.md`.
- **Attempt budget**: the target counter is never refunded. Preparation plans
  may reserve resources but do not consume target attempts.
- **Historical incomplete records**: missing/ambiguous old identity remains
  conservatively unknown. It is not rewritten into a modern success receipt.

## Deliberately not supported

- No fallback from buffer-v2 to legacy or from legacy to buffer-v2.
- No content sniffing to choose a parser or framing policy.
- No judge confirmation from stored events, stored `confirmed` values, target
  stdout, model output or diagnostic wrappers.
- No real Docker/bpftrace/preflight/selfcheck/target execution in this phase.
- No new preflight license, formal batch or consumed claim.

## Verification status

Source-only. The new tests are SIMULATED/recorded-shim checks plus in-process
monkeypatched resource probes. They are not real-machine results. Codex
independent check and external source review remain pending; the new-source
selfcheck is pending. The B1–B4 support matrix and evidence limits are in
`RECOVERY-CLOSE-SUPPORT.md`.
