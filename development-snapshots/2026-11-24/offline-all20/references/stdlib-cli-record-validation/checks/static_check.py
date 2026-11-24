#!/usr/bin/env python3
"""Deterministic static and delivery checks for the revision-6 fix.

This script parses source, compares frozen bytes and verifies the final manifest
and result files.  It never executes a fixture, container, observer, preflight
or target.  Behavioural proof lives in ``checks/run_rev6_checks.py`` and the
recorded-shim regression suite; substring checks here are only a delivery guard.
"""
import argparse
import ast
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "baseline"
OUT = ROOT / "checks" / "static-checks.json"
IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
BASELINE_MANIFEST_SHA = "cbe9d12c03a2716adacd55331a9b38798627681cd0787b49e132978ddd5a13dd"
BASELINE_FILE_COUNT = 83
SEALED_PROFILE_SHA = "be4fac9697219f047d9d631006b10f3f0791ea0acec51ddc95b623412af295e8"

CHECKS = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(name, condition, detail=None):
    CHECKS.append({"check": name, "passed": bool(condition), "detail": detail})
    return bool(condition)


def read(path):
    return Path(path).read_text(encoding="utf-8")


def parse(path):
    return ast.parse(read(path), filename=str(path))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
    else:
        current = ROOT / "checks" / "current-run.json"
        run_dir = Path(json.loads(current.read_text())["runDir"]).resolve()
    output_path = Path(args.out) if args.out else run_dir / "static-checks.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # ---- baseline integrity and frozen inputs
    baseline_manifest = json.loads((BASE / "protocol-manifest.json").read_text())
    bad = []
    for relative, expected in baseline_manifest["files"].items():
        path = BASE / relative
        if not path.is_file() or sha(path) != expected:
            bad.append(relative)
    check("baseline-manifest-source-files-match",
          not bad and len(baseline_manifest["files"]) == BASELINE_FILE_COUNT
          and baseline_manifest["fileCount"] == BASELINE_FILE_COUNT, bad)
    check("baseline-manifest-sha", sha(BASE / "protocol-manifest.json") == BASELINE_MANIFEST_SHA)
    for relative in (
        "fixtures/echo/sce_echo_sink.py",
        "fixtures/safe-quoting/sce_quoted_sink.py",
        "fixtures/structure-controlled/sce_raw_sink.py",
        "fixtures/wrong-function/sce_two_sites.py",
        "experiment-plan.json",
    ):
        check("frozen-byte-identical:" + relative, sha(ROOT / relative) == sha(BASE / relative))
    protected_changes = []
    for path in sorted((ROOT / "tools").glob("*")):
        if not path.is_file() or path.name == "experiment_runner.py":
            continue
        if sha(path) != sha(BASE / "tools" / path.name):
            protected_changes.append("tools/" + path.name)
    check("protected-tools-baseline-identical", not protected_changes,
          protected_changes)
    check("only-intended-runner-changed",
          sha(ROOT / "tools" / "experiment_runner.py")
          != sha(BASE / "tools" / "experiment_runner.py"))
    check("sealed-observer-profile-bytes",
          sha(ROOT / "tools" / "observer-profile.lock.json") == SEALED_PROFILE_SHA)
    profile = json.loads((ROOT / "tools" / "observer-profile.lock.json").read_text())
    check("sealed-profile-fixed-image", profile.get("imageId") == IMAGE)
    check("sealed-profile-fixed-python", profile.get("pythonVersion") == "3.12.15")
    check("sealed-profile-fixed-interpreter",
          profile.get("interpreterSha256") == "7d1bf26e09ba6e5824f7f7587f2d37090def82ae83fe81485e3163a70bc8f7f5")
    check("sealed-profile-fixed-library",
          profile.get("librarySha256") == "73531f4f375bbd8d97bd55cce30f48900a7d9c9f597aa298d4f08d057a95b4c5")

    plan = json.loads((ROOT / "experiment-plan.json").read_text())
    check("plan-16-attempts", len(plan.get("attempts") or []) == 16)
    check("plan-4-fixtures", len(plan.get("fixtures") or []) == 4)
    check("plan-image", plan["profile"]["imageId"] == IMAGE)
    check("plan-python", plan["profile"]["pythonVersion"] == "3.12.15")

    # ---- source parses
    for path in sorted((ROOT / "tools").glob("*.py")):
        try:
            parse(path)
            ok = True
        except SyntaxError:
            ok = False
        check("ast-parse:" + path.name, ok)
    for path in sorted((ROOT / "checks").glob("*.py")):
        try:
            parse(path)
            ok = True
        except SyntaxError:
            ok = False
        check("ast-parse:checks/" + path.name, ok)

    # ---- no runtime/admission directories in the delivery root
    for forbidden in ("state", "runs", "prepare", "codex-review", "preflight"):
        check("no-root-runtime-dir:" + forbidden, not (ROOT / forbidden).exists())
    check("no-root-admission-file",
          not any(ROOT.glob("*/experiment-admission.json"))
          and not any(ROOT.glob("*/preflight-admission.json")))
    check("no-root-preflight-receipt", not (ROOT / "preflight" / "preflight-receipt.json").exists())
    check("no-root-lock", not (ROOT / "preflight" / ".preflight.lock").exists())

    # ---- protocol revision
    verifier = read(ROOT / "tools" / "preflight_verify.py")
    preflight = read(ROOT / "tools" / "zero_target_preflight.py")
    runner = read(ROOT / "tools" / "experiment_runner.py")
    judge = read(ROOT / "tools" / "judge.py")
    selfcheck = read(ROOT / "tools" / "preflight_selfcheck.py")
    shim_common = read(ROOT / "checks" / "shim_common.py")
    check("revision-verifier-3", "PROTOCOL_REVISION = 3" in verifier)
    check("revision-runner-3", "PROTOCOL_REVISION = 3" in runner)
    check("revision-selfcheck-3", '"protocolRevision": 3' in selfcheck)
    check("revision-shim-3", '"protocolRevision": 3' in shim_common)
    check("revision-claim-3", '"protocolRevision": PROTOCOL_REVISION' in preflight
          and '"version": CONTEXT_VERSION' in preflight)
    check("revision-receipt-3", '"version": CONTEXT_VERSION' in preflight
          and '"protocolRevision": PROTOCOL_REVISION' in preflight)
    check("revision-old-evidence-rejected", 'receipt.get("protocolRevision") != PROTOCOL_REVISION' in verifier)

    # ---- preflight: one-time license/lock/unique evidence
    check("preflight-stable-lock", "ExclusiveLock" in preflight
          and "flock" in read(ROOT / "tools" / "resource_guard.py"))
    check("preflight-one-time-claim", "consume_claim" in preflight
          and "preflight-license-consumed" in preflight
          and "O_EXCL" in read(ROOT / "tools" / "resource_guard.py"))
    claim_pos = preflight.find("guard.write_new_json_document(\n            claim_path")
    evidence_pos = preflight.find("evidence.mkdir", claim_pos)
    check("preflight-claim-before-evidence", 0 <= claim_pos < evidence_pos)
    check("preflight-untracked-evidence-refused", "preflight-evidence-untracked" in preflight)
    check("preflight-license-id", "preflightId" in preflight
          and "license-preflight-id" in verifier)
    check("preflight-candidate-manifest", "candidateManifestSha256" in preflight
          and "candidateManifestSha256" in verifier)
    check("preflight-review-binding", "sourceReviewReceiptSha256" in preflight
          and "review-blockers" in verifier)
    check("preflight-unique-evidence-dir", "EVIDENCE_ROOT" in preflight
          and "evidence_dir(ROOT" in preflight
          and 'RAW = OUT / "observer.raw"' not in preflight
          and 'OBSERVATION = OUT / "observation.json"' not in preflight)
    check("preflight-new-evidence-files", "persist_bytes" in preflight
          and "persist_json" in preflight and "evidenceCreatedNew" in preflight)
    check("preflight-collector-exit", "preflight-collector-exit" in preflight
          and "preflight-collector-product-missing" in preflight)
    check("preflight-no-stale-fallback", "preflight-observation-exists" in preflight
          and "if not OBSERVATION.is_file" not in preflight)
    collector_source = read(ROOT / "tools" / "collect_observer.py")
    buffer_source = read(ROOT / "tools" / "buffer_protocol.py")
    buffer_v2_source = read(ROOT / "tools" / "buffer_protocol_v2.py")
    check("preflight-shared-pure-parser",
          "buffer_protocol_v2.parse_receipt" in preflight
          and "observation_pure.parse_receipt" not in preflight
          and "buffer_protocol_v2.parse_receipt" in verifier
          and "parser_module.parse_receipt" in collector_source
          and 'args.observation_protocol == "buffer-v1"' in collector_source
          and "parser_module = buffer_protocol_v2" in collector_source
          and "buffer_protocol_v2" in read(ROOT / "tools" / "zero_target_preflight.py"))
    check("collector-explicit-protocol-no-sniff",
          'choices=("legacy", "buffer-v1", "buffer-v2")' in collector_source
          and 'required=True' in collector_source.split('"--observation-protocol"', 1)[1][:120]
          and 'if args.observation_protocol == "legacy"' in collector_source)
    check("preflight-buffer-binding-before-resources",
          "def buffer_binding()" in preflight
          and preflight.find("binding = buffer_binding()") < preflight.find("lock.acquire()")
          and "license-buffer-parser" in verifier
          and "license-buffer-template" in verifier)
    check("preflight-buffer-rebuild-producer",
          "preflight-observer-rebuild" in preflight
          and "buffer_protocol_v2.parse_receipt" in preflight)
    check("preflight-go-waits-for-buffer-marker",
          "required_lines=(buffer_protocol_v2.MARKER.encode" in preflight
          and "def observer_ready(self, prefix=b\"BEGIN \", timeout=15.0, required_lines=None)"
              in read(ROOT / "tools" / "preflight_diagnostics.py"))
    check("buffer-parser-frozen-siblings",
          "import observation_pure as _legacy" in buffer_source
          and "import structure" in buffer_source
          and "_LEGACY_DIR" not in buffer_source
          and "sys.path.insert" not in buffer_source
          and "from pathlib import Path" not in buffer_source
          and "import observation_pure as _legacy" in buffer_v2_source
          and "import structure" in buffer_v2_source
          and "sys.path.insert" not in buffer_v2_source
          and "from pathlib import Path" not in buffer_v2_source)
    check("buffer-v2-strict-grammar",
          'PROTOCOL = "buffer-v2"' in buffer_v2_source
          and 'MARKER = "BUFFER-PROTOCOL buffer-v2"' in buffer_v2_source
          and 'PAIR_RE = re.compile(r"[0-9a-f]{2}")' in buffer_v2_source
          and 'raise ParseError(what + ":spacing")' in buffer_v2_source
          and "if any(not item for item in tokens)" in buffer_v2_source)
    check("buffer-v2-end-lf-framing-policy",
          'FRAMING_POLICY = "end-lf-padding-v1"' in buffer_v2_source
          and "MAX_TRAILING_BLANK_LINES = 8" in buffer_v2_source
          and '"trailingBlankLines"' in buffer_v2_source
          and '"trailing-lf-overflow"' in buffer_v2_source
          and '"end-unterminated"' in buffer_v2_source
          and "framing_policy=FRAMING_POLICY" in buffer_v2_source)
    check("collector-explicit-framing-policy",
          '"--framing-policy"' in collector_source
          and "framing-policy-missing" in collector_source
          and "framing-policy-not-applicable" in collector_source
          and "parser_kwargs[\"framing_policy\"] = args.framing_policy" in collector_source)
    check("preflight-framing-binding",
          "FRAMING_POLICY = buffer_protocol_v2.FRAMING_POLICY" in verifier
          and "license-framing-policy" in verifier
          and "claim-framing-policy" in verifier
          and "claim-completed-framing-policy" in verifier
          and "receipt-framing-policy" in verifier
          and "observation-capture-framing-policy" in verifier
          and "framingPolicy" in preflight
          and '"--framing-policy", FRAMING_POLICY' in preflight)
    check("buffer-v1-bytes-retained",
          sha(ROOT / "tools" / "buffer_protocol.py")
          == sha(BASE / "tools" / "buffer_protocol.py")
          and sha(ROOT / "tools" / "observer_template_buffer.bt")
          == sha(BASE / "tools" / "observer_template_buffer.bt"))
    check("buffer-template-parameterized",
          (ROOT / "tools" / "observer_template_buffer.bt").is_file()
          and (ROOT / "tools" / "observer_template_buffer_v2.bt").is_file()
          and (ROOT / "tools" / "observer_template.bt").is_file()
          and sha(ROOT / "tools" / "observer_template.bt") ==
              sha(BASE / "tools" / "observer_template.bt")
          and sha(ROOT / "tools" / "observer_template_buffer.bt") ==
              sha(BASE / "tools" / "observer_template_buffer.bt")
          and (ROOT / "tools" / "observer_template_buffer_v2.bt").read_text().count("%rh") == 5
          and "BUFFER-PROTOCOL buffer-v2" in
              (ROOT / "tools" / "observer_template_buffer_v2.bt").read_text()
          and "BUFFER-PROTOCOL buffer-v1" not in
              (ROOT / "tools" / "observer_template_buffer_v2.bt").read_text())
    check("strict-exitcode-acceptance-types",
          "def require_exitcode(" in verifier
          and "def require_success_exitcode(" in verifier
          and "exitcode-type:" in verifier and "exitcode-not-zero:" in verifier
          and "invalid-returncode-type:" in judge)
    check("preflight-integer-zero", "preflight-int-zero" in preflight and "intZero" in preflight)
    check("preflight-caller-location", "preflight-caller-offset" in preflight
          and "preflight-caller-sha" in preflight)
    check("preflight-unique-end", "preflight-markers" in preflight and "preflight-end" in preflight)
    check("preflight-graceful-stop", "preflight-observer-forced-stop" in preflight
          and "preflight-observer-not-graceful" in preflight
          and 'stop_info.get("forced") is not False' in preflight)
    check("preflight-drain-complete", "preflight-drain-incomplete" in preflight
          and "drainComplete" in preflight)
    check("preflight-status-by-id", "def status" in preflight and "unknown-outcome" in preflight)
    check("preflight-no-target-surface", 'add_parser("recover")' in preflight
          and 'add_parser("preflight")' in preflight)
    check("preflight-fixed-tools", "FIXED_TOOLS" in preflight
          and "observer-profile.lock.json" in preflight
          and "/review/preflight/preflight_selfcheck.py" in preflight
          and "import target_launcher" not in preflight
          and "import experiment_compile" not in preflight)
    check("preflight-forbidden-fixtures", "preflight-forbidden-input" in preflight
          and all(name not in selfcheck for name in
                  ("sce_echo_sink", "sce_raw_sink", "sce_two_sites")))
    check("selfcheck-side-effect-free", 'eval("0")' in selfcheck
          and not any(token in selfcheck for token in
                      ("sce_echo_sink", "sce_quoted_sink", "sce_raw_sink",
                       "sce_two_sites", "fixtures/")))
    check("selfcheck-profile-exact", "profile-mismatch" in selfcheck
          and 'profile.get("interpreterSha256") != interpreter_sha' in selfcheck
          and 'profile.get("librarySha256") != library_sha' in selfcheck)

    # ---- shared resource context / journals
    check("context-before-create", "def new_context" in preflight
          and '"stageBuildState": "not-created"' in preflight
          and '"spawnState": "not-started"' in preflight)
    check("context-stage-intents", "stage-intent.json" in preflight
          and "stage-started.json" in preflight and "stage-created.json" in preflight)
    check("context-container-journal", "container-intent.json" in preflight
          and "container-created.json" in preflight and "container-pid.json" in preflight)
    check("context-process-identity-journal", "process-\" + role + \"-intent.json" in preflight
          and "process-\" + role + \"-identity.json" in preflight)
    check("context-handle-before-journal", preflight.find('context[role].update({\n        "pid": process.pid')
          < preflight.find('persist_json(context, "process-" + role + "-identity.json"'))
    check("context-container-handle-before-journal",
          preflight.find('context["container"]["containerId"] = created_id')
          < preflight.find('persist_json(context, "container-created.json"'))
    check("context-unknown-not-never-created", "create-result-unknown" in preflight
          and "identity-journal-unpersisted" in preflight)
    check("context-persist-failure-blocks", "persistFailure" in preflight
          and "persistence-failed" in preflight and "partial-build-retained" in preflight)
    check("context-cleanup-derives", "def cleanup_resources(context)" in preflight
          and "container_result.get(\"removed\") is True" in preflight)
    check("context-successful-query-proof", "container_absent_all" in read(ROOT / "tools" / "resource_guard.py")
          and "lstatAfter" in preflight)
    check("preflight-cleanup-file", "cleanup.json" in preflight and "cleanupSha256" in preflight)

    # ---- recover command
    check("recover-command", 'add_parser("recover")' in preflight
          and "def recover(preflight_id)" in preflight)
    check("recover-same-lock", "lock = guard.ExclusiveLock(LOCK_PATH)" in preflight
          and preflight.count("guard.ExclusiveLock(LOCK_PATH)") >= 2)
    check("recover-no-selfcheck", "selfCheckReplayed" in preflight
          and "subprocess.run" not in preflight.split("def recover(", 1)[1].split("def _write_recovery", 1)[0])
    check("recover-no-replay", "preflight_selfcheck.py" not in preflight.split(
        "def recover(", 1)[1].split("def _write_recovery", 1)[0])
    check("recover-original-id-only", 'claim_rel = "preflight/claims/" + preflight_id' in preflight
          and '"preflightId", preflight_id, "claim-preflight-id"' in preflight
          and "expected_id=preflight_id" in preflight)
    check("recover-unknown-no-signal", "identity-journal-unpersisted" in preflight
          and "if state.get(\"state\") == \"alive\":" in preflight)
    check("recover-new-record", "_write_recovery" in preflight
          and "recovery-\" + os.urandom" in preflight)
    check("recover-never-passes", '"receiptAccepted": False' in preflight
          and '"realMachinePass": False' in preflight)

    # ---- revision-7 tri-state, resource plan and pre-action recovery binding
    guard_source = read(ROOT / "tools" / "resource_guard.py")
    check("guard-path-tri-state", "def path_state(path):" in guard_source
          and "except PermissionError:" in guard_source
          and "except NotADirectoryError:" in guard_source
          and 'return {"state": "absent"' in guard_source)
    check("guard-no-lexists-in-cleanup", "os.path.lexists" not in guard_source)
    check("cleanup-final-lstat-condition",
          'stage_clean.get("lstatAfter") == "absent"' in preflight)
    check("claim-resource-plan", "resourcePlan" in preflight
          and "resourcePlanSha256" in preflight
          and "resource_plan_reason" in preflight)
    check("claim-plan-fixed-fields", "RESOURCE_PLAN_FIELDS" in verifier
          and "stageRelativePath" in verifier
          and "resource_plan_reason" in verifier)
    check("recover-preaction-binding", "def _recovery_plan(" in preflight
          and "def _safe_lstat(" in preflight
          and "def _split_relative(" in preflight)
    plan_pos = preflight.find("outcome = _recovery_plan(")
    action_pos = preflight.find("container = _recover_container(", plan_pos)
    check("recover-reads-all-before-actions", 0 <= plan_pos < action_pos)
    check("recover-blocked-exit-78",
          "return _write_recovery(recovery, evidence, 78)" in preflight)
    check("recover-incomplete-exit-3",
          "return _write_recovery(recovery, evidence, 3)" in preflight)
    check("recover-stage-absence", 'stage.get("lstatAfter") == "absent"' in preflight)
    check("recover-final-stage-recheck", "def _final_stage_recheck(" in preflight
          and "state = _safe_lstat(ROOT, stage_rel, kind=\"dir\")" in preflight
          and "stage = _final_stage_recheck(" in preflight)
    check("recover-no-cached-absent-success",
          'if stage_plan["mode"] == "absent":' not in preflight
          and "stage-appeared" in preflight
          and "appeared-after-plan" in preflight)
    check("recover-final-not-directory-not-absent",
          '"stage-not-directory"' in preflight
          and 'return outcome("blocked", "stage-not-directory"' in preflight)
    check("recover-final-identity-blocked",
          '"stage-identity-changed"' in preflight
          and 'return outcome("blocked", "stage-identity-changed"' in preflight)
    check("cleanup-absent-key-explicit",
          'if state["state"] == "absent":\n        # A stage path that is already gone' in preflight)
    check("verifier-requires-plan", "claim-resource-plan-missing" in verifier
          and "receipt-resource-plan" in verifier)
    check("test-isolation-shim-guard",
          "def verify_shims(env):" in read(ROOT / "checks" / "regression_lib.py")
          and "controlled shim mismatch" in read(ROOT / "checks" / "regression_lib.py"))
    check("test-isolation-no-real-docker-vacuous-pass",
          "containerAbsenceQueriesRan" in read(ROOT / "checks" / "run_rev7_checks.py")
          and "realDocker" in read(ROOT / "checks" / "run_rev7_checks.py"))
    check("repeat-recovery-field-checks",
          "firstSelfCheckNotReplayed" in read(ROOT / "checks" / "run_rev6_checks.py")
          and "secondRealMachinePassFalse" in read(ROOT / "checks" / "run_rev6_checks.py")
          and "onlyRecoveryFilesAdded" in read(ROOT / "checks" / "run_rev6_checks.py"))
    check("rev8-final-recheck-suite",
          (ROOT / "checks" / "run_rev8_checks.py").is_file()
          and (ROOT / "checks" / "rev8_support.py").is_file()
          and "test_stage_appears_during_container_query" in read(
              ROOT / "checks" / "run_rev8_checks.py"))

    # ---- independent verifier wired into runner and judge
    check("verifier-recomputes", "stored_observation != recomputed" in verifier)
    check("verifier-exact-runtime", 'layout.get("runtime") != identity' in verifier
          and 'receipt.get("profile") != profile_identity(profile)' in verifier)
    check("verifier-layout-bytes", 'receipt.get("layoutSha256") != layout_sha' in verifier
          and "layoutStructureSha256" in verifier)
    check("verifier-rebuilds-observer", "observer_render.render" in verifier
          and "observer-rebuild-mismatch" in verifier
          and "frozenTemplateSha256" in verifier)
    check("verifier-binds-target-pid", "container-pid-binding" in verifier
          and "container-pid-output" in verifier)
    check("verifier-reads-journals", "def verify_resource_evidence" in verifier
          and all(name in verifier for name in
                  ("preflight-intent.json", "stage-created.json",
                   "container-created.json", "process-client-identity.json",
                   "process-observer-identity.json", "cleanup.json")))
    check("verifier-derives-cleanup", "derived-cleanup-container" in verifier
          and "cleanup-receipt-mismatch" in verifier
          and "_absent_triple" in verifier)
    check("verifier-checks-order", "evidence-order:" in verifier)
    check("verifier-malformed-config", "config-expected-structure" in verifier
          and "except (KeyError, TypeError, ValueError, AttributeError" in verifier)
    check("runner-uses-independent-verifier", "preflight_verify.verify_preflight_evidence" in runner)
    check("judge-uses-independent-verifier", "preflight_verify.verify_preflight_evidence" in judge)
    check("runner-does-not-trust-preflight-booleans",
          'observation.get("complete") is True' not in runner
          and "preflightReceiptSha256" in runner)
    check("judge-does-not-trust-preflight-booleans",
          'preflight.get("observation")' not in judge and "verify_governance" in judge)
    check("judge-rebuilds-observer-exactly", "observer-rebuild-mismatch" in judge
          and "observer_render.render" in judge and "--layout" in judge)
    check("runner-rejects-layout-before-use", "verify_prepare_inputs(preflight_result)" in runner
          and "layout-digest" in runner and "template-digest" in runner)
    check("runner-layout-byte-not-structure",
          '"layoutSha256": layout_sha' in read(ROOT / "tools" / "experiment_compile.py")
          and '"layoutSha256": structure.digest(layout)' not in read(ROOT / "tools" / "experiment_compile.py"))
    check("compile-records-layout-structure",
          '"layoutStructureSha256": structure.digest(layout)' in read(ROOT / "tools" / "experiment_compile.py"))
    check("formal-layout-uses-preflight-bytes", "prepare_layout_from_preflight" in runner
          and "write_new_or_identical(layout_path, payload)" in runner)

    # ---- resource lifecycle
    guard = read(ROOT / "tools" / "resource_guard.py")
    check("guard-exact-full-id", 'observed["id"] != expected_id' in guard)
    check("guard-image-verified", "container-image-mismatch" in guard)
    check("guard-triple-absence-query", "container_absent_all" in guard
          and "tag-replacement" in guard and "name-replacement" in guard)
    check("guard-no-name-rm", 'docker("rm", "-f", identifier' in guard
          and 'docker("rm", "-f", name' not in guard)
    check("guard-tri-state-process", "proc-stat-malformed" in guard
          and "proc-unreadable" in guard and "identity-missing" in guard)
    check("guard-spawn-state", "spawn_group_state" in guard and "not-started" in guard)
    check("guard-forced-stop", "forced" in guard and "SIGKILL" in guard)
    check("cleanup-gated-stage", "associated_clear" in runner
          and "resources_clear = (" in runner
          and "container_clear and client_exited and observer_exited" in runner
          and "retained-resources-unresolved" in runner
          and "if resources_clear" in runner)
    check("cleanup-final-check-after-resources",
          '"finalStageCheck": "after-resources"' in runner
          and runner.count("cleanup_stage(") >= 2)
    check("resources-plan-before-stage",
          "def write_lifecycle_plan(" in runner
          and runner.find("write_lifecycle_plan(") < runner.find("stage_run_inputs(stage_dir")
          and 'prepareId=prepare_id' in runner
          and 'resourcePlanPath' in runner)
    check("create-spawn-ambiguous-unknown",
          'containerState="create-unknown"' in runner
          and 'spawnState": "unknown"' in runner
          and 'spawn-unknown' in runner)
    check("selector-exactly-one",
          'add_mutually_exclusive_group(required=True)' in runner
          and 'add_argument("--prepare-id")' in runner
          and 'def read_lifecycle_plan(' in runner
          and 'resource-identity-mismatch' in runner)
    check("formal-buffer-v2-identity",
          'OBSERVATION_PROTOCOL = buffer_protocol_v2.PROTOCOL' in runner
          and 'FRAMING_POLICY = buffer_protocol_v2.FRAMING_POLICY' in runner
          and 'buffer_protocol_v2.parse_output' in runner
          and '"--observation-protocol", OBSERVATION_PROTOCOL' in runner
          and '"--framing-policy", FRAMING_POLICY' in runner)
    check("judge-independent-raw-recompute",
          "buffer_protocol_v2.parse_receipt" in judge
          and "compare_canonical(observation, recomputed)" in judge
          and "derive_verdict(recomputed[\"events\"]" in judge
          and "recomputed-observation-state" in judge
          and "recomputed-trailing-blank-lines" in judge)
    check("judge-payload-none-fail-closed",
          "expected-payload-type" in judge
          and "except Exception as error:" in judge)
    run_block = runner.split("def run_target", 1)[1].split("def cleanup_attempt", 1)[0]
    check("cleanup-deferred-to-gated-cleanup", "resourceFinalize" in run_block
          and '"stage":' not in run_block.split("resourceFinalize", 1)[1][:600])
    check("recover-does-not-replay", "replayed" in runner
          and "start_attached" not in runner.split("def command_recover", 1)[1].split(
              "def command_prepare", 1)[0])

    # ---- observer / collector / Q4
    template = read(ROOT / "tools" / "observer_template.bt")
    end_block = template[template.rfind("END {"):]
    check("template-end-clears-map", "clear(@events)" in end_block and "printf" in end_block)
    check("template-scalar-counter",
          "@events = @events + 1;" in template
          and "@events = count();" not in template
          and "count()" not in template)
    check("template-scalar-compare",
          "if (@events > __MAX_EVENTS__)" in template)
    check("template-end-scalar",
          "$events = @events;" in end_block
          and end_block.count("printf") == 1
          and '"__TAG__", $events);' in end_block)
    check("template-int-zero", "DCONST %d i 0 0" in template and "KCONST %d i 0 0" in template)
    collector = read(ROOT / "tools" / "collect_observer.py")
    check("collector-new-output-only", "out-exists" in collector and "O_EXCL" in collector)
    check("collector-end-missing", '"end-missing"' in read(ROOT / "tools" / "observation_pure.py"))
    check("collector-end-duplicate", '"end-duplicate"' in read(ROOT / "tools" / "observation_pure.py"))
    check("collector-trailing-after-end", '"trailing-after-end"' in read(ROOT / "tools" / "observation_pure.py"))
    check("collector-truncated", "raw-truncated" in read(ROOT / "tools" / "observation_pure.py"))
    check("judge-real-syntax", "def payload_syntax(payload, role)" in judge and "except SyntaxError" in judge)
    check("judge-syntax-flag", "syntaxRejectExpected" in judge)
    check("judge-wrong-exit", "syntax-reject-target-exit" in judge)
    check("judge-no-ordinary-zero-as-syntax", "no-dynamic-event" in judge and '"syntax-reject"' in judge)

    # ---- observer early-exit diagnostics (additive version 1)
    diagnostic_source = ""
    diagnostic_path = ROOT / "tools" / "preflight_diagnostics.py"
    if diagnostic_path.is_file():
        diagnostic_source = read(diagnostic_path)
    check("diagnostics-module", bool(diagnostic_source)
          and "class InvocationRuntime" in diagnostic_source
          and "DIAGNOSTIC_VERSION = 1" in diagnostic_source)
    check("diagnostics-reuses-streamdrain", "from resource_guard import StreamDrain" in diagnostic_source)
    check("diagnostics-no-communicate", "communicate(" not in diagnostic_source)
    check("diagnostics-four-stream-files", all(name in diagnostic_source for name in (
        "diagnostic-client.stdout", "diagnostic-client.stderr",
        "diagnostic-observer.stdout", "diagnostic-observer.stderr")))
    check("diagnostics-document-kind", "zero-target-preflight-process-diagnostics" in diagnostic_source)
    check("diagnostics-readiness-values", all(value in diagnostic_source for value in (
        "ready", "early-exit", "stream-error", "timeout", "unknown")))
    check("diagnostics-controller-status", "/proc/self/status" in diagnostic_source)
    check("diagnostics-no-version-probe", '"probeSpawned": False' in diagnostic_source)
    attach_pos = preflight.find("runtime.attach_process(role, process, argv)")
    journal_pos = preflight.find('persist_json(context, "process-" + role + "-identity.json"')
    check("diagnostics-handle-before-identity-journal",
          0 <= attach_pos < journal_pos)
    check("diagnostics-drains-at-spawn", "runtime.drain(\"client\", \"stdout\")" in preflight
          and "runtime.drain(\"observer\", \"stdout\")" in preflight)
    check("diagnostics-no-second-drains",
          "guard.StreamDrain(client.stdout" not in preflight
          and "guard.StreamDrain(observer.stdout" not in preflight)
    check("diagnostics-cleanup-gate", "and diagnostics_clear" in preflight
          and "diagnostic_summary.get(\"confirmed\") is not True" in preflight)
    check("diagnostics-receipt-field",
          "processDiagnosticsSha256" in diagnostic_source
          and "diagnostics.additive_fields(diagnostic_summary)" in preflight
          and "diagnosticEvidenceDigests" in preflight)
    check("diagnostics-failure-field", "diagnostics.additive_fields" in preflight)
    check("diagnostics-status-readonly", "read_status_summary" in preflight)
    check("diagnostics-no-recover-replay",
          "read_status_summary" not in preflight.split("def recover(", 1)[1]
          .split("def _write_recovery", 1)[0])
    check("diagnostics-contract", (ROOT / "DIAGNOSTICS-CONTRACT.md").is_file())
    check("diagnostics-suite", (ROOT / "checks" / "run_diagnostics_checks.py").is_file())
    check("diagnostics-strict-stream-predicate",
          "def _strict_stream_problems(files, returncodes)" in diagnostic_source
          and '"stream-not-eof:"' in diagnostic_source
          and '"stream-not-completed:"' in diagnostic_source
          and '"returncode-unknown:"' in diagnostic_source)
    check("diagnostics-persisted-bytes-digests",
          "persistedBytes" in diagnostic_source
          and "persistedSha256" in diagnostic_source
          and "_verify_persisted" in diagnostic_source)
    check("diagnostics-drain-deadline-recorded",
          "drain-deadline:" in diagnostic_source
          and "drain-incomplete:" in diagnostic_source)
    check("diagnostics-shared-document-summary-predicate",
          "strict_complete" in diagnostic_source
          and "incompleteReasons" in diagnostic_source
          and "def _status_strict_problems(value, evidence)" in diagnostic_source)
    check("diagnostics-status-recomputes-strict",
          "strict_problems = _status_strict_problems(value, evidence)" in diagnostic_source
          and 'state = ("present" if outcome.get("confirmed") is True and not strict_problems'
              in diagnostic_source)
    check("preflight-cleanup-evidence-constructor",
          "def __init__(self, reason, detail=None, cleanup=None):" in preflight
          and 'cleanup["raised"]' in preflight
          and '"cleanupEvidence"' in preflight)
    check("repair-focused-suite", (ROOT / "checks" / "run_repair_checks.py").is_file())

    # ---- phase result
    phase_path = ROOT / "phase-result.json"
    if phase_path.is_file():
        phase = json.loads(phase_path.read_text())
        required = {
            "state": phase.get("state") in {"pending-codex-review", "blocked"},
            "protocolRevision": phase.get("protocolRevision") == 3,
            "diagnosticVersion": phase.get("diagnosticVersion") == 1,
            "targetExecutions": phase.get("targetExecutions") == 0,
            "fixturesImported": phase.get("fixturesImported") == 0,
            "realContainers": phase.get("realContainers") == 0,
            "admissionIssued": phase.get("admissionIssued") is False,
            "preflightExecuted": phase.get("preflightExecuted") is False,
            "r3": phase.get("r3") == "blocked",
            "gap": bool(phase.get("gaps") or phase.get("unresolved")),
        }
        for key, value in required.items():
            check("phase-result:" + key, value)
    else:
        check("phase-result-exists", False)

    # ---- current-run raw evidence (never old result files)
    run_files = {
        "baseline": "baseline-verification.json",
        "compile": "compile-results.json",
        "regression": "regression-results.json",
        "rev6": "rev6-results.json",
        "rev7": "rev7-results.json",
        "rev8": "rev8-results.json",
        "diagnostics": "diagnostics-results.json",
        "repair": "repair-results.json",
        "buffer": "buffer-preflight-results.json",
    }
    loaded = {}
    for key, name in run_files.items():
        path = run_dir / name
        check("current-run-file:" + key, path.is_file(), str(path))
        if path.is_file():
            loaded[key] = json.loads(path.read_text())

    if "baseline" in loaded:
        baseline = loaded["baseline"]
        check("current-baseline-source-files", baseline.get("fileCount") == BASELINE_FILE_COUNT
              and baseline.get("recomputed") == BASELINE_FILE_COUNT
              and baseline.get("mismatched") == [],
              baseline.get("mismatched"))
        check("current-baseline-manifest-sha",
              baseline.get("manifestSha256") == BASELINE_MANIFEST_SHA,
              baseline.get("manifestSha256"))
        check("current-baseline-fixtures", baseline.get("fixtures") == {
            "fixtures/echo/sce_echo_sink.py":
                "83b5e9cde7f5203571efb5cf8d5b24034d8816036140a1d23306c063ceb617b2",
            "fixtures/safe-quoting/sce_quoted_sink.py":
                "f03a1f1d698923b04e4b0a5a8709a8958c1cdc221d14c5969cde04c430afb47c",
            "fixtures/structure-controlled/sce_raw_sink.py":
                "fb799416a87ce896e747acd66618a98e3e349c6800a58843b196560399ca2dba",
            "fixtures/wrong-function/sce_two_sites.py":
                "260f904b0f72b002fbd9b6be57df9ee18e4b65c36e10cefd4723fb28de4bac6b",
        })
    if "compile" in loaded:
        compile_results = loaded["compile"]
        check("current-compile-all-pass", compile_results.get("failed") == []
              and compile_results.get("passed") == compile_results.get("total")
              and compile_results.get("total", 0) >= 24, compile_results.get("failed"))
    if "regression" in loaded:
        regression = loaded["regression"]
        check("current-regression-total", regression.get("total") == 28,
              regression.get("total"))
        check("current-regression-all-pass", regression.get("failed") == [],
              regression.get("failed"))
        check("current-regression-simulated", regression.get("simulated") is True
              and regression.get("targetExecutions") == 0
              and regression.get("realContainers") == 0)
        shims = regression.get("shimResolution") or {}
        check("current-regression-shims-controlled",
              all(name in shims for name in ("docker", "bpftrace"))
              and all(Path((shims.get(name) or {}).get("resolvedPath", "")).is_file()
                      and str((shims.get(name) or {}).get("resolvedPath", "")).startswith(
                          str((ROOT / "checks" / "shims").resolve()))
                      and sha((shims.get(name) or {}).get("resolvedPath"))
                      == (shims.get(name) or {}).get("sha256")
                      for name in ("docker", "bpftrace")),
              shims)
    if "rev6" in loaded:
        rev6 = loaded["rev6"]
        check("current-rev6-total", rev6.get("total") == 24, rev6.get("total"))
        check("current-rev6-all-pass", rev6.get("failed") == [], rev6.get("failed"))
        repeat = next((item for item in rev6.get("results") or []
                       if item.get("test") == "recovery-normal-repeated-no-selfcheck"), {})
        check("current-rev6-repeat-fields", repeat.get("passed") is True
              and all((repeat.get("checks") or {}).values())
              and len(repeat.get("checks") or {}) >= 20)
    if "rev7" in loaded:
        rev7 = loaded["rev7"]
        check("current-rev7-total", rev7.get("total") == 12, rev7.get("total"))
        check("current-rev7-all-pass", rev7.get("failed") == [], rev7.get("failed"))
        removed = next((item for item in rev7.get("results") or []
                        if item.get("test") ==
                        "removed-true-but-final-lstat-present-is-not-confirmed"), {})
        check("current-rev7-isolation", removed.get("passed") is True
              and all((removed.get("checks") or {}).values())
              and (removed.get("calls") or {}).get("delete") == 1
              and (removed.get("calls") or {}).get("lstat", 0) >= 2
              and (removed.get("calls") or {}).get("realDocker") == 0)
    if "rev8" in loaded:
        rev8 = loaded["rev8"]
        check("current-rev8-total", rev8.get("total") == 13, rev8.get("total"))
        check("current-rev8-all-pass", rev8.get("failed") == [], rev8.get("failed"))
        names = {item.get("test") for item in rev8.get("results") or []}
        required = {
            "stage-appears-during-resource-query-is-retained",
            "final-recheck-permission-error-incomplete",
            "final-recheck-not-a-directory-incomplete",
            "final-recheck-generic-oserror-incomplete",
            "final-recheck-non-directory-is-blocked",
            "final-recheck-symlink-is-blocked",
            "final-recheck-identity-contradiction-is-blocked",
            "normal-missing-stage-uses-new-absence-query",
            "normal-present-stage-removal-is-confirmed",
            "cleanup-missing-stage-with-created-identity-no-keyerror",
            "recovery-journal-write-failure-returns-79",
        }
        check("current-rev8-coverage", required <= names, sorted(required - names))
    if "diagnostics" in loaded:
        diagnostics = loaded["diagnostics"]
        check("current-diagnostics-total", diagnostics.get("total") == 20,
              diagnostics.get("total"))
        check("current-diagnostics-all-pass", diagnostics.get("failed") == [],
              diagnostics.get("failed"))
        check("current-diagnostics-simulated",
              diagnostics.get("simulated") is True
              and diagnostics.get("targetExecutions") == 0
              and diagnostics.get("realContainers") == 0
              and diagnostics.get("realBpftrace") == 0
              and diagnostics.get("realTargets") == 0)
        names = {item.get("test") for item in diagnostics.get("results") or []}
        required = {
            "observer-compile-error-stderr-exit2-before-begin",
            "identity-journal-failure-preserves-handle-and-streams",
            "eof-with-live-process-is-stream-error-not-exit",
            "readiness-timeout-then-deliberate-cleanup",
            "cancellation-finalizes-bounded-diagnostics",
            "success-path-separates-diagnostics-and-observer-raw",
            "output-over-256k-is-truncated-and-not-confirmed",
            "stream-read-failure-is-captured",
            "diagnostic-write-failure-is-incomplete",
            "diagnostic-fsync-failure-is-incomplete",
            "stale-cross-id-diagnostics-not-adopted",
            "finalization-twice-no-duplicate-writes",
            "cannot-determine-returncode-remains-null-not-zero",
            "pre-cleanup-poll-separate-from-cleanup-signal",
            "finalize-makes-no-signal-resource-or-spawn-calls",
            "status-exposes-diagnostics-read-only",
            "recover-does-not-replay-or-rewrite-diagnostics",
            "diagnostic-failure-keeps-stage-and-preserves-original-reason",
            "diagnostic-metadata-binds-manifest-claim-plan-and-digests",
            "cleanup-branch-visits-and-zero-real-boundaries",
        }
        check("current-diagnostics-coverage", required <= names,
              sorted(required - names))
    if "buffer" in loaded:
        buffer_results = loaded["buffer"]
        check("current-buffer-total", buffer_results.get("total") == 29,
              buffer_results.get("total"))
        check("current-buffer-all-pass", buffer_results.get("failed") == [],
              buffer_results.get("failed"))
        check("current-buffer-simulated",
              buffer_results.get("simulated") is True
              and buffer_results.get("targetExecutions") == 0
              and buffer_results.get("realContainers") == 0
              and buffer_results.get("realBpftrace") == 0
              and buffer_results.get("observationProtocol") == "buffer-v2"
              and buffer_results.get("formalTargets") == "0/16"
              and buffer_results.get("r3") == "blocked")
        names = {item.get("test") for item in buffer_results.get("results") or []}
        required = {
            "candidate-sibling-imports-and-frozen-legacy-bytes",
            "five-string-classes-lengths-0-1-63-64-accepted",
            "five-string-classes-length-65-refused",
            "nonascii-payload-invalid-not-exception",
            "ascii-specials-and-zero-vs-none-preserved",
            "count-records-are-mandatory-and-cover-indexes",
            "malformed-lengths-hex-dash-and-duplicates-refused",
            "truncation-markers-and-begin-end-attribution",
            "legacy-buffer-mix-and-legacy-parser-boundary",
            "collector-explicit-protocol-no-sniff-or-fallback",
            "parameterized-buffer-template-preserves-old-bytes-and-fields",
            "preflight-refuses-missing-wrong-protocol-or-digests-before-resources",
            "source-formatter-flags-golden-pairs-and-record-empty-token",
            "v2-all-five-records-strict-spacing-and-token-refusal",
            "v2-counts-index-gaps-and-map-duplicates-refused",
            "v2-ascii-controls-nul-quote-backslash-and-nonascii-boundary",
            "v1-v2-marker-and-single-byte-wire-payload-distinguish-protocols",
            "legacy-v1-v2-equivalent-capture-identical-canonical-hashes",
            "v2-normalizes-through-frozen-v1-helpers-not-a-translation",
            "v2-unsupported-and-trailing-after-end-rules-preserved",
            "collector-explicit-v1-diagnostic-and-v2-marker-boundary",
            "preflight-synthetic-buffer-v2-accepted-and-verifier-recomputes",
            "verifier-rejects-modified-raw-observation-and-observer-rebuild",
            "verifier-rejects-receipt-parser-and-template-digest-mismatch",
            "verifier-rejects-actual-parser-and-template-file-tamper",
            "legacy-and-downgraded-records-are-not-admitted-as-buffer-preflight",
            "strict-exitcode-types-rejected-unknown-null-preserved",
            "recovery-and-status-query-original-id-without-replay",
            "go-waits-for-buffer-marker-and-does-not-run-on-early-begin",
        }
        check("current-buffer-coverage", required <= names,
              sorted(required - names))
    if "repair" in loaded:
        repair = loaded["repair"]
        check("current-repair-total", repair.get("total") == 11,
              repair.get("total"))
        check("current-repair-all-pass", repair.get("failed") == [],
              repair.get("failed"))
        check("current-repair-simulated",
              repair.get("simulated") is True
              and repair.get("targetExecutions") == 0
              and repair.get("realContainers") == 0
              and repair.get("realBpftrace") == 0
              and repair.get("realTargets") == 0)
        names = {item.get("test") for item in repair.get("results") or []}
        required = {
            "unfinished-stdout-stderr-is-incomplete",
            "eof-with-alive-child-is-incomplete",
            "known-vs-unknown-returncode",
            "negative-signal-returncode-is-known",
            "normal-complete-capture-and-status",
            "stream-read-failure-is-incomplete",
            "truncation-is-incomplete",
            "diagnostic-write-failure-reason-and-status",
            "repeat-finalize-idempotent",
            "cleanup-unconfirmed-constructor-and-controller",
            "scalar-counter-and-end-grammar-zero-one-four-over-budget",
        }
        check("current-repair-coverage", required <= names,
              sorted(required - names))

    # ---- final source-only manifest (when present)
    manifest_path = ROOT / "protocol-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        files = manifest.get("files", {})
        check("manifest-state", manifest.get("state") == "pending-codex-review")
        check("manifest-self-excluded", "protocol-manifest.json" not in files)
        check("manifest-report-excluded", "REPORT.md" not in files)
        check("manifest-phase-excluded", "phase-result.json" not in files)
        check("manifest-evidence-index-excluded", "checks/evidence-index.json" not in files)
        check("manifest-current-run-excluded", "checks/current-run.json" not in files)
        check("manifest-results-excluded",
              not any(relative.startswith("checks/evidence-runs/") for relative in files))
        check("manifest-tmp-excluded",
              not any(relative.startswith("checks/tmp/") for relative in files))
        mismatched = []
        for relative, expected in files.items():
            path = ROOT / relative
            if not path.is_file() or os.path.islink(path) or sha(path) != expected:
                mismatched.append(relative)
        check("manifest-all-files-match", not mismatched, mismatched)
        check("manifest-file-count", manifest.get("fileCount") == len(files))
        check("manifest-source-only",
              "targetExecutions" in manifest and manifest.get("targetExecutions") == 0)
        check("manifest-includes-tools",
              all(any(relative == "tools/" + name for relative in files)
                  for name in ("experiment_runner.py", "resource_guard.py",
                               "preflight_verify.py", "observer_render.py",
                               "zero_target_preflight.py", "preflight_selfcheck.py",
                               "preflight_diagnostics.py", "observer-profile.lock.json",
                               "buffer_protocol.py", "buffer_protocol_v2.py",
                               "observer_template_buffer.bt",
                               "observer_template_buffer_v2.bt")))
        check("manifest-includes-contract",
              "DIAGNOSTICS-CONTRACT.md" in files
              and "REPAIR-CONTRACT.md" in files
              and "BUFFER-PREFLIGHT-CONTRACT.md" in files
              and "BUFFER-V2-CONTRACT.md" in files
              and "END-LF-CONTRACT.md" in files
              and "FORMAL-ADMISSION-CONTRACT.md" in files
              and "RECOVERY-CLOSE-CONTRACT.md" in files
              and "RECOVERY-CLOSE-SUPPORT.md" in files
              and "ASSOCIATION-RECOVERY-CONTRACT.md" in files
              and "ASSOCIATION-RECOVERY-SUPPORT.md" in files)
        check("manifest-includes-new-suite",
              "checks/run_diagnostics_checks.py" in files
              and "checks/run_repair_checks.py" in files
              and "checks/run_rev8_checks.py" in files
              and "checks/rev8_support.py" in files
              and "checks/run_buffer_preflight_checks.py" in files
              and "checks/run_buffer_v2_red.py" in files
              and "checks/run_end_lf_checks.py" in files
              and "checks/formal_admission/run_checks.py" in files
              and "checks/formal_admission/formal_support.py" in files
              and "checks/formal_admission/red_checks.py" in files
              and "checks/run_formal_admission_checks.py" in files
              and "checks/run_recovery_close_checks.py" in files
              and "checks/run_association_recovery_checks.py" in files
              and "checks/evidence_capture.py" in files
              and "checks/make_recovery_close_evidence_index.py" in files
              and "checks/make_association_evidence_index.py" in files
              and "checks/run_record_validation_checks.py" in files)
        check("manifest-end-lf-policy",
              manifest.get("observationProtocol") == "buffer-v2"
              and manifest.get("framingPolicy") == "end-lf-padding-v1"
              and manifest.get("selfcheckExecutions") == 0
              and manifest.get("formalTargets") == "0/16"
              and manifest.get("r3") == "blocked")
    else:
        check("manifest-exists", False)

    payload = {
        "kind": "cli-resource-journal-static-checks",
        "version": 3,
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "results": CHECKS,
        "passed": sum(1 for item in CHECKS if item["passed"]),
        "failed": [item["check"] for item in CHECKS if not item["passed"]],
        "total": len(CHECKS),
    }
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                           encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not payload["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
