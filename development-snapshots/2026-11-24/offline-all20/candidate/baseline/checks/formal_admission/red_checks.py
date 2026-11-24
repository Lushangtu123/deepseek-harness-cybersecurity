#!/usr/bin/env python3
"""Behavioural RED/PASS probes for the formal runner/judge admission change.

The same script is run against the sealed baseline tools (RED) and against the
candidate tools (PASS).  It never invokes a real Docker/bpftrace binary: the
sandbox flow uses ``checks/shims`` and the in-process cases monkeypatch every
resource operation before it can be reached.

Each case's ``passed`` field means "the desired post-fix behaviour was
observed".  On the sealed baseline the relevant cases are expected to be false;
that failure is the behavioural RED evidence, not an import/typo error.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

CHECKS = Path(__file__).resolve().parents[1]
ROOT = CHECKS.parent
sys.path.insert(0, str(CHECKS))
sys.path.insert(0, str(CHECKS / "formal_admission"))

import regression_lib  # noqa: E402
from regression_lib import Sandbox, sha  # noqa: E402


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def case(name, function):
    try:
        value = function()
        value.setdefault("case", name)
        value["passed"] = bool(value.get("passed"))
        value["error"] = None
    except Exception as error:  # noqa: BLE001
        value = {
            "case": name,
            "passed": False,
            "error": type(error).__name__ + ":" + str(error),
            "trace": traceback.format_exc()[-2000:],
        }
    print(("PASS " if value["passed"] else "RED  ") + name)
    return value


# --------------------------------------------------------------------- sandbox
def sandbox_flow(tools_source):
    box = Sandbox("red-formal", tools_source=tools_source)
    box.write_preflight_license()
    preflight = box.preflight()
    if preflight.returncode != 0:
        return box, {"error": "preflight-failed", "stderr": preflight.stderr[-500:]}
    box.write_formal_admission(allowed=[1])
    prepare = box.prepare()
    run = box.run_attempt(1)
    return box, {
        "preflightReturn": preflight.returncode,
        "runReturn": run.returncode,
        "runStderr": run.stderr[-500:],
        "prepare": [item.returncode for item in prepare],
    }


def legacy_formal_protocol(tools_source):
    box, info = sandbox_flow(tools_source)
    observer = box.path / "runs" / "0001" / "observer.bt"
    observation_path = box.path / "runs" / "0001" / "observation.json"
    attempt = box.attempt(1) if (box.path / "state" / "attempt-0001.json").is_file() else {}
    observation = box.observation(1) or {}
    observer_text = observer.read_text(encoding="utf-8") if observer.is_file() else ""
    desired = (
        info.get("runReturn") == 0
        and "BUFFER-PROTOCOL buffer-v2" in observer_text
        and observation.get("protocol") == "buffer-v2"
        and observation.get("framingPolicy") == "end-lf-padding-v1"
        and attempt.get("observationProtocol") == "buffer-v2"
        and attempt.get("framingPolicy") == "end-lf-padding-v1"
        and isinstance(attempt.get("bufferParserSha256"), str)
        and isinstance(attempt.get("bufferTemplateSha256"), str)
    )
    return {
        "passed": desired,
        "flow": info,
        "observerHasV2Marker": "BUFFER-PROTOCOL buffer-v2" in observer_text,
        "observerBytes": len(observer_text.encode("utf-8")),
        "observationProtocol": observation.get("protocol"),
        "observationFraming": observation.get("framingPolicy"),
        "attemptProtocol": attempt.get("observationProtocol"),
        "attemptFraming": attempt.get("framingPolicy"),
        "verdict": (box.verdict(1) or {}).get("decision"),
    }


def judge_recomputes_raw(tools_source):
    """Keep stored events but replace the raw stream with a complete zero-event one."""
    box, info = sandbox_flow(tools_source)
    run_dir = box.path / "runs" / "0001"
    raw_path = run_dir / "observer.raw"
    observation_path = run_dir / "observation.json"
    attempt_path = box.path / "state" / "attempt-0001.json"
    if not raw_path.is_file() or not observation_path.is_file():
        return {"passed": False, "flow": info, "error": "missing-run-evidence"}
    attempt = json.loads(attempt_path.read_text())
    observation = json.loads(observation_path.read_text())
    tag = attempt["challenge"][:12]
    forged_raw = ("BEGIN run=attempt-0001 tag=%s\n" % tag).encode("ascii")
    forged_raw += ("END run=attempt-0001 tag=%s events=0\n" % tag).encode("ascii")
    raw_path.write_bytes(forged_raw)
    observation["rawSha256"] = digest_bytes(forged_raw)
    observation["rawBytes"] = len(forged_raw)
    observation_path.write_text(json.dumps(observation, sort_keys=True, indent=1) + "\n")
    attempt["observationRawSha256"] = digest_bytes(forged_raw)
    attempt["observationSha256"] = sha(observation_path)
    attempt_path.write_text(json.dumps(attempt, sort_keys=True, indent=1) + "\n")
    # The probe selects the template matching the *stored* observer bytes so
    # the baseline is exercised through its event logic instead of failing
    # earlier on a template rebuild.  Production code never sniffs.
    observer_text = (run_dir / "observer.bt").read_text(encoding="utf-8")
    template_name = ("observer_template_buffer_v2.bt"
                     if "BUFFER-PROTOCOL buffer-v2" in observer_text
                     else "observer_template.bt")
    out = run_dir / "verification-forged.json"
    command = [
        sys.executable, str(box.path / "tools" / "judge.py"),
        "--binding", str(box.path / "prepare" / "bind" / "bind.json"),
        "--expected", str(box.path / "prepare" / "compile-0001" / "expected.json"),
        "--observation", str(observation_path),
        "--attempt", str(attempt_path),
        "--admission", str(box.path / "codex-review" / "experiment-admission.json"),
        "--manifest", str(box.path / "protocol-manifest.json"),
        "--preflight", str(box.preflight_receipt_path()),
        "--review-receipt", str(box.path / "codex-review" / "source-review-receipt.json"),
        "--observer", str(run_dir / "observer.bt"),
        "--raw", str(raw_path),
        "--layout", str(box.path / "prepare" / "layout" / "layout.json"),
        "--template", str(box.path / "tools" / template_name),
        "--profile", str(box.path / "tools" / "observer-profile.lock.json"),
        "--out", str(out),
    ]
    result = __import__("subprocess").run(command, capture_output=True, text=True,
                                          env=box.env(), timeout=60)
    verdict = json.loads(out.read_text()) if out.is_file() else {}
    return {
        "passed": verdict.get("decision") == "unknown",
        "flow": info,
        "judgeReturn": result.returncode,
        "decision": verdict.get("decision"),
        "reason": verdict.get("reason"),
        "rawSha": digest_bytes(forged_raw),
        "storedRawSha": observation.get("rawSha256"),
    }


# --------------------------------------------------------------- in-process
def load_runner(tools_source):
    tools_source = Path(tools_source).resolve()
    for name in ("experiment_runner",):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(tools_source))
    try:
        import experiment_runner as runner  # noqa: PLC0415
    finally:
        try:
            sys.path.remove(str(tools_source))
        except ValueError:
            pass
    return runner


class StopProbe(Exception):
    pass


def inprocess_paths(runner, base):
    base = Path(base)
    runner.STATE = base / "state"
    runner.RUNS = base / "runs"
    runner.PREPARE = base / "prepare"
    for directory in (runner.STATE, runner.RUNS, runner.PREPARE):
        Path(directory).mkdir(parents=True, exist_ok=True)
    return base


def fake_preflight_inputs(runner):
    import structure  # noqa: PLC0415

    layout = {"preflightId": "a" * 32, "runtime": {}}
    layout_bytes = (json.dumps(layout, sort_keys=True, indent=1) + "\n").encode()
    return {
        "layout": layout,
        "layoutBytes": layout_bytes,
        "layoutSha256": digest_bytes(layout_bytes),
        "layoutStructureSha256": structure.digest(layout),
        "templateBytes": b"template",
        "templateSha256": digest_bytes(b"template"),
        "profile": {},
        "profileSha256": "c" * 64,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "bufferParserSha256": "f" * 64,
        "bufferTemplateSha256": "e" * 64,
        "frozenTemplateSha256": "e" * 64,
    }


def stage_plan_before_creation(tools_source):
    runner = load_runner(tools_source)
    base = Path(tempfile.mkdtemp(dir=str(CHECKS / "tmp")))
    inprocess_paths(runner, base)
    plan = json.loads((ROOT / "experiment-plan.json").read_text())
    plan_sha = sha(ROOT / "experiment-plan.json")
    runner.verify_prepare_inputs = lambda _result: fake_preflight_inputs(runner)
    runner.preflight_context = lambda: {
        "preflightId": "a" * 32, "receiptSha256": "b" * 64,
        "profileSha256": "c" * 64, "profile": {},
    }
    observed = {"planAtStageCreation": False}

    real_safe = runner._safe_mkdir

    def safe(path):
        path = Path(path)
        if "stage-bind-" in str(path):
            plans = list((Path(runner.PREPARE) / "plans").glob("*.json")) if (
                Path(runner.PREPARE) / "plans").is_dir() else []
            for item in plans:
                try:
                    value = json.loads(item.read_text())
                except ValueError:
                    continue
                stage_dir = value.get("stageDir")
                if stage_dir and (str(path) == stage_dir or str(path).startswith(stage_dir + os.sep)):
                    observed["planAtStageCreation"] = True
                    observed["planPath"] = str(item)
                    observed["planKeys"] = sorted(value)
        return real_safe(path)

    runner._safe_mkdir = safe
    runner.run_tool_container = lambda *args, **kwargs: (_ for _ in ()).throw(StopProbe())
    try:
        runner.prepare_container_bind(plan, plan_sha)
    except StopProbe:
        pass
    except BaseException as error:  # noqa: BLE001
        observed["unexpected"] = type(error).__name__ + ":" + str(error)
    finally:
        runner._safe_mkdir = real_safe
    return {
        "passed": observed.get("planAtStageCreation") is True,
        "observed": observed,
        "stageDirs": [str(path) for path in (Path(runner.PREPARE)).glob("stage-bind-*")],
    }


def stage_config_for_run_target(runner, base):
    """Return (record, plan, bind result) with all on-disk prerequisites."""
    plan = json.loads((ROOT / "experiment-plan.json").read_text())
    item = next(entry for entry in plan["attempts"] if entry["attempt"] == 1)
    inputs = fake_preflight_inputs(runner)
    result = {
        "classId": "S",
        "stagedPath": "sce_raw_sink.py",
        "callOffset": 7,
        "closure": {},
        "module": "sce_raw_sink",
        "callable": "sink",
        "derivation": {
            "layoutSha256": inputs["layoutSha256"],
            "layoutStructureSha256": inputs["layoutStructureSha256"],
        },
    }
    (Path(runner.PREPARE) / "bind").mkdir(parents=True, exist_ok=True)
    (Path(runner.PREPARE) / "bind" / "bind.json").write_text(
        json.dumps({"results": [result]}, sort_keys=True, indent=1) + "\n")
    challenge = "a" * 32
    expected = {
        "challenge": challenge,
        "layoutSha256": inputs["layoutSha256"],
        "layoutStructureSha256": inputs["layoutStructureSha256"],
        "payload": "0",
        "expectedComputation": {"structureSha256": "d" * 64, "codeSha256": "e" * 64},
    }
    (Path(runner.PREPARE) / "compile-0001").mkdir(parents=True, exist_ok=True)
    (Path(runner.PREPARE) / "compile-0001" / "expected.json").write_text(
        json.dumps(expected, sort_keys=True, indent=1) + "\n")
    record = {
        "version": 1, "attempt": 1, "classId": "S", "challenge": challenge,
        "expectedSha256": None, "checkpoints": [], "processes": {},
    }
    (Path(runner.STATE) / "attempt-0001.json").write_text(
        json.dumps(record, sort_keys=True, indent=1) + "\n")
    runner.verify_prepare_inputs = lambda _result: inputs
    runner.preflight_context = lambda: {
        "preflightId": "a" * 32, "receiptSha256": "b" * 64,
        "profileSha256": "c" * 64, "profile": {},
    }
    runner.closure_sources_for = lambda _plan, _class_id: {}
    return record, plan, result, item


def target_plan_before_stage(tools_source):
    runner = load_runner(tools_source)
    base = Path(tempfile.mkdtemp(dir=str(CHECKS / "tmp")))
    inprocess_paths(runner, base)
    record, plan, _result, _item = stage_config_for_run_target(runner, base)
    observed = {"intentAtStageRunInputs": False, "prepareId": None, "planFiles": []}

    def stage_probe(*args, **kwargs):
        stored = json.loads((Path(runner.STATE) / "attempt-0001.json").read_text())
        observed["intentAtStageRunInputs"] = stored.get("resourceIntent") is not None
        observed["prepareId"] = stored.get("prepareId")
        observed["recordKeys"] = sorted(stored)
        plans = list((Path(runner.PREPARE) / "plans").glob("*.json")) if (
            Path(runner.PREPARE) / "plans").is_dir() else []
        observed["planFiles"] = [str(path) for path in plans]
        raise StopProbe()

    runner.stage_run_inputs = stage_probe
    try:
        runner.run_target(record, plan)
    except StopProbe:
        pass
    except BaseException as error:  # noqa: BLE001
        observed["unexpected"] = type(error).__name__ + ":" + str(error)
    return {"passed": observed.get("intentAtStageRunInputs") is True
            and observed.get("prepareId") is not None, "observed": observed}


def identity_write_failure_unknown(tools_source):
    runner = load_runner(tools_source)
    base = Path(tempfile.mkdtemp(dir=str(CHECKS / "tmp")))
    inprocess_paths(runner, base)
    record, plan, _result, _item = stage_config_for_run_target(runner, base)
    def fake_stage(*args, **kwargs):
        stored = json.loads((Path(runner.STATE) / "attempt-0001.json").read_text())
        intent = stored["resourceIntent"]
        stage_dir = Path(intent["stageDir"])
        for child in ("runroot", "config", "tools"):
            (stage_dir / child).mkdir(parents=True, exist_ok=True)
        return {
            "stageDir": str(stage_dir),
            "stageIdentity": {"dev": 1, "ino": 2, "mode": 0o755},
            "mounts": {row["source"]: row["destination"] for row in intent["mounts"]},
            "configSha256": "f" * 64,
            "launcherSha256": "0" * 64,
            "closure": {},
        }

    runner.stage_run_inputs = fake_stage
    runner.create_container = lambda *args, **kwargs: {"id": "1" * 64}
    runner.verify_config_inside = lambda *args, **kwargs: None
    runner.cleanup_attempt = lambda *args, **kwargs: False
    real_update = runner.update_attempt
    observed = {"identityWriteRaised": False}

    def update(number, **fields):
        if "resourceIdentity" in fields:
            observed["identityWriteRaised"] = True
            raise RuntimeError("simulated-identity-write-failure")
        return real_update(number, **fields)

    runner.update_attempt = update
    try:
        runner.run_target(record, plan)
    except BaseException as error:  # noqa: BLE001
        observed["raised"] = type(error).__name__ + ":" + str(error)
    stored = json.loads((Path(runner.STATE) / "attempt-0001.json").read_text())
    plans = []
    plans_dir = Path(runner.PREPARE) / "plans"
    if plans_dir.is_dir():
        for path in plans_dir.glob("*.json"):
            try:
                plans.append(json.loads(path.read_text()))
            except ValueError:
                plans.append({"path": str(path), "invalid": True})
    identity_evidence = [
        value for value in plans
        if value.get("containerState") in {"created", "create-unknown"}
        and value.get("containerId") == "1" * 64
    ]
    return {
        "passed": observed.get("identityWriteRaised") is True and bool(identity_evidence),
        "observed": observed,
        "storedContainerCreated": stored.get("containerCreated"),
        "storedResourceIdentity": stored.get("resourceIdentity"),
        "storedLifecycle": stored.get("lifecycle"),
        "planIdentityEvidence": [
            {"containerState": value.get("containerState"),
             "containerId": value.get("containerId")}
            for value in plans
        ],
    }


def early_cleanup_final_stage(tools_source):
    """A stage created before its attempt record is still recovered from plan."""
    runner = load_runner(tools_source)
    import resource_guard as guard  # noqa: PLC0415

    base = Path(tempfile.mkdtemp(dir=str(CHECKS / "tmp")))
    inprocess_paths(runner, base)
    tag = "1" * 16
    stage = Path(runner.RUNS) / "0001" / ("stage-" + tag)
    stage.mkdir(parents=True)
    (stage / "input").mkdir()
    identity = guard.stage_identity(stage)
    name = "stdlib-cli-run-0001-" + tag
    prepare_id = "a" * 32
    plans_dir = Path(runner.PREPARE) / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "version": 3, "protocolRevision": 3, "kind": "resource-lifecycle-plan",
        "prepareId": prepare_id, "operationRole": "run-0001", "role": "run-0001",
        "attempt": 1, "state": "planned", "stageDir": str(stage),
        "stageState": "created", "stageIdentity": identity, "tag": tag,
        "containerName": name, "imageId": runner.IMAGE, "image": runner.IMAGE,
        "mounts": [], "processes": {"client": {"spawnState": "not-started"},
                                    "observer": {"spawnState": "not-started"}},
        "containerState": "not-created", "containerId": None,
        "reservationHeld": True, "createdAt": "1970-01-01T00:00:00+00:00",
    }
    (plans_dir / (prepare_id + ".json")).write_text(
        json.dumps(plan, sort_keys=True, indent=1) + "\n")
    # Simulate the baseline bug: the stage exists but the attempt record was
    # never given a resource intent/stageDir.
    record = {
        "version": 1, "attempt": 1, "prepareId": prepare_id,
        "processes": {"client": {"spawnState": "not-started"},
                      "observer": {"spawnState": "not-started"}},
        "checkpoints": [],
    }
    (Path(runner.STATE) / "attempt-0001.json").write_text(
        json.dumps(record, sort_keys=True, indent=1) + "\n")
    original_remove = guard.remove_container_verified
    original_lookup = guard.container_lookup
    original_tag = guard.container_tag_lookup
    guard.remove_container_verified = lambda _record: {
        "removed": True, "state": "never-created"
    }
    guard.container_lookup = lambda _identifier: {"state": "absent"}
    guard.container_tag_lookup = lambda _tag: {"state": "absent"}
    try:
        confirmed = runner.cleanup_attempt(record)
    finally:
        guard.remove_container_verified = original_remove
        guard.container_lookup = original_lookup
        guard.container_tag_lookup = original_tag
    stored = json.loads((Path(runner.STATE) / "attempt-0001.json").read_text())
    stage_state = stored.get("cleanup", {}).get("stage") or {}
    return {
        "passed": stage_state.get("removed") is True and not stage.exists() and confirmed is True,
        "confirmed": confirmed,
        "stageStillExists": stage.exists(),
        "stageOutcome": stage_state,
        "reservationHeld": stored.get("reservationHeld"),
    }


CASES = {
    "legacy-formal-protocol": legacy_formal_protocol,
    "judge-recomputes-raw": judge_recomputes_raw,
    "stage-plan-before-creation": stage_plan_before_creation,
    "target-plan-before-stage": target_plan_before_stage,
    "identity-write-failure-unknown": identity_write_failure_unknown,
    "early-cleanup-final-stage": early_cleanup_final_stage,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="run")
    args = parser.parse_args(argv)
    tools = Path(args.tools).resolve()
    results = []
    for name, function in CASES.items():
        results.append(case(name, lambda function=function: function(tools)))
    payload = {
        "kind": "formal-admission-red-pass-probe",
        "label": args.label,
        "tools": str(tools),
        "toolsSha256": {
            "experiment_runner.py": sha(tools / "experiment_runner.py"),
            "judge.py": sha(tools / "judge.py"),
        },
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "results": results,
        "passed": sum(1 for item in results if item["passed"]),
        "failed": [item["case"] for item in results if not item["passed"]],
        "total": len(results),
        "note": "Simulated/recorded shims only. Not a real-machine result.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not payload["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
