#!/usr/bin/env python3
"""SIMULATED behavioural checks for formal runner/judge offline admission.

No real Docker, bpftrace, preflight, selfcheck, fixture or target is invoked.
The sandbox suite executes only ``checks/shims`` and the in-process cases
monkeypatch resource calls.
"""
import argparse
import fcntl
import json
import os
import sys
import traceback
from pathlib import Path

CHECKS = Path(__file__).resolve().parents[1]
ROOT = CHECKS.parent
sys.path.insert(0, str(CHECKS))
sys.path.insert(0, str(CHECKS / "formal_admission"))
sys.path.insert(0, str(ROOT / "tools"))

import formal_support as support  # noqa: E402
import regression_lib  # noqa: E402
from formal_support import (  # noqa: E402
    attempt_path, docker_count, judge, plans, read_json, ready_box,
    resign_observation, run_dir, sha, sha_bytes, target_plan, write_json,
)

RESULTS = []


def record(name, passed, **fields):
    entry = {"test": name, "passed": bool(passed), **fields}
    RESULTS.append(entry)
    print(("PASS " if passed else "FAIL ") + name)
    return entry


def scenario(name):
    def wrapper(function):
        try:
            value = function()
            value.setdefault("test", name)
            value["passed"] = bool(value.get("passed"))
            value["error"] = None
        except Exception as error:  # noqa: BLE001
            value = {"test": name, "passed": False,
                     "error": type(error).__name__ + ":" + str(error),
                     "trace": traceback.format_exc()[-2500:]}
        print(("PASS " if value["passed"] else "FAIL ") + name)
        RESULTS.append(value)
        return function
    return wrapper


# --------------------------------------------------------------- sandbox flow
@scenario("normal-preparation-target-v2")
def normal_flow():
    box = ready_box("fa-normal", allowed=(1,))
    result = box.run_attempt(1)
    attempt = box.attempt(1)
    verdict = box.verdict(1) or {}
    observation = box.observation(1) or {}
    observer = (run_dir(box, 1) / "observer.bt").read_text(encoding="utf-8")
    plan_path, plan = target_plan(box, 1)
    checks = {
        "return0": result.returncode == 0,
        "verdictConfirmed": verdict.get("decision") == "confirmed",
        "observerV2": "BUFFER-PROTOCOL buffer-v2" in observer,
        "observationProtocol": observation.get("protocol") == "buffer-v2",
        "observationFraming": observation.get("framingPolicy") == "end-lf-padding-v1",
        "attemptProtocol": attempt.get("observationProtocol") == "buffer-v2",
        "attemptFraming": attempt.get("framingPolicy") == "end-lf-padding-v1",
        "attemptParserSha": attempt.get("bufferParserSha256") == sha(ROOT / "tools" / "buffer_protocol_v2.py"),
        "attemptTemplateSha": attempt.get("bufferTemplateSha256") == sha(ROOT / "tools" / "observer_template_buffer_v2.bt"),
        "planExists": plan is not None,
        "planCreated": (plan or {}).get("containerState") == "created",
        "planId": (plan or {}).get("prepareId") == attempt.get("prepareId"),
        "stageFinalAbsent": not (run_dir(box, 1) / str((plan or {}).get("stageDir", "missing")).split("/")[-1]).exists(),
        "cleanupConfirmed": (attempt.get("cleanup") or {}).get("confirmed") is True,
        "reservationReleased": attempt.get("reservationHeld") is False,
        "targetExecutions": attempt.get("targetExecutions") == 1,
        "counter": read_json(box.path / "state" / "attempt-counter.json").get("used") == [1],
    }
    return {"passed": all(checks.values()), "checks": checks,
            "verificationReason": verdict.get("reason")}


@scenario("admission-identity-mismatch-rejected-before-resources")
def admission_identity_mismatch():
    box = ready_box("fa-admission-id", allowed=(1,))
    admission_path = box.path / "codex-review" / "experiment-admission.json"
    admission = read_json(admission_path)
    admission["framingPolicy"] = "legacy"
    write_json(admission_path, admission)
    creates_before = docker_count(box, "create ")
    result = box.run_attempt(1)
    checks = {
        "rejected78": result.returncode == 78,
        "reason": "admission-framingPolicy" in result.stderr,
        "noAttempt": not attempt_path(box, 1).exists(),
        "noCreate": docker_count(box, "create ") == creates_before,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "stderr": result.stderr[-250:]}


@scenario("plan-write-failure-prevents-stage-creation")
def plan_write_failure():
    import red_checks  # noqa: PLC0415
    import resource_guard as guard  # noqa: PLC0415
    runner = red_checks.load_runner(str(ROOT / "tools"))
    base = Path(CHECKS / "tmp") / ("fa-plan-fail-" + os.urandom(4).hex())
    red_checks.inprocess_paths(runner, base)
    plan = read_json(ROOT / "experiment-plan.json")
    plan_sha = sha(ROOT / "experiment-plan.json")
    runner.verify_prepare_inputs = lambda _result: red_checks.fake_preflight_inputs(runner)
    runner.preflight_context = lambda: {
        "preflightId": "a" * 32, "receiptSha256": "b" * 64,
        "profileSha256": "c" * 64, "profile": {},
    }
    original_write = guard.write_new_json_document
    calls = {"plan": 0}

    def failing_write(path, value):
        if "plans" in str(path):
            calls["plan"] += 1
            raise OSError("simulated-plan-fsync-failure")
        return original_write(path, value)

    guard.write_new_json_document = failing_write
    raised = None
    try:
        runner.prepare_container_bind(plan, plan_sha)
    except BaseException as error:  # noqa: BLE001
        raised = type(error).__name__
    finally:
        guard.write_new_json_document = original_write
    stages = list(Path(runner.PREPARE).glob("stage-bind-*"))
    checks = {
        "writeAttempted": calls["plan"] == 1,
        "raised": raised is not None,
        "noStage": stages == [],
    }
    return {"passed": all(checks.values()), "checks": checks, "raised": raised}


@scenario("prepare-id-query-status-and-recover-no-replay")
def selectors():
    box = ready_box("fa-selectors", allowed=(1,))
    result = box.run_attempt(1)
    plan_path, plan = target_plan(box, 1)
    prepare_bind = next((value for value in (read_json(path) for path in plans(box))
                         if value.get("operationRole", "").startswith("bind-")), None)
    status = box.run(["status"])
    query_attempt = box.run(["query", "--attempt", "1"])
    query_plan = box.run(["query", "--prepare-id", plan["prepareId"]])
    starts_before = docker_count(box, "start ")
    recover = box.run(["recover", "--prepare-id", plan["prepareId"]])
    starts_after = docker_count(box, "start ")
    status_value = json.loads(status.stdout) if status.returncode == 0 else {}
    query_value = json.loads(query_plan.stdout) if query_plan.returncode == 0 else {}
    checks = {
        "normal": result.returncode == 0,
        "bindPlanExists": prepare_bind is not None,
        "statusReturn0": status.returncode == 0,
        "statusHasPlans": len(status_value.get("preparations") or []) >= 2,
        "queryAttempt0": query_attempt.returncode == 0,
        "queryPlan0": query_plan.returncode == 0,
        "queryPlanId": (query_value.get("plan") or {}).get("prepareId") == plan["prepareId"],
        "recover0": recover.returncode == 0,
        "replayedFalse": '"replayed": false' in recover.stdout,
        "noNewStart": starts_after == starts_before,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "recoverStdout": recover.stdout[-250:]}


@scenario("cli-exclusivity-and-preserved-attempt-selector")
def cli_exclusivity():
    box = ready_box("fa-cli", allowed=(1,))
    box.run_attempt(1)
    plan_path, plan = target_plan(box, 1)
    both_query = box.run(["query", "--attempt", "1", "--prepare-id", plan["prepareId"]])
    neither_query = box.run(["query"])
    both_cleanup = box.run(["cleanup", "--attempt", "1", "--prepare-id", plan["prepareId"]])
    neither_recover = box.run(["recover"])
    old_attempt = box.run(["query", "--attempt", "1"])
    new_id = box.run(["query", "--prepare-id", plan["prepareId"]])
    checks = {
        "bothQueryRejected": both_query.returncode == 2,
        "neitherQueryRejected": neither_query.returncode == 2,
        "bothCleanupRejected": both_cleanup.returncode == 2,
        "neitherRecoverRejected": neither_recover.returncode == 2,
        "oldAttemptWorks": old_attempt.returncode == 0,
        "newPrepareIdWorks": new_id.returncode == 0,
    }
    return {"passed": all(checks.values()), "checks": checks}


@scenario("plan-written-before-stage-config-and-create")
def plan_before_stage():
    import red_checks  # noqa: PLC0415
    bind = red_checks.stage_plan_before_creation(str(ROOT / "tools"))
    target = red_checks.target_plan_before_stage(str(ROOT / "tools"))
    identity = red_checks.identity_write_failure_unknown(str(ROOT / "tools"))
    checks = {
        "bindPlanBeforeStage": bind.get("passed") is True,
        "targetPlanBeforeStage": target.get("passed") is True,
        "identityWriteUnknown": identity.get("passed") is True,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "bind": bind.get("observed"), "target": target.get("observed"),
            "identity": identity.get("planned")}


# ------------------------------------------------------------- cleanup probes
def cleanup_harness(name, *, stage_present=True, remove_result=None,
                    cleanup_override=None, journal_failure=False):
    import red_checks  # noqa: PLC0415
    import resource_guard as guard  # noqa: PLC0415

    runner = red_checks.load_runner(str(ROOT / "tools"))
    base = Path(CHECKS / "tmp") / ("fa-cleanup-" + name + "-" + os.urandom(4).hex())
    red_checks.inprocess_paths(runner, base)
    stage = Path(runner.PREPARE) / "stage-probe"
    identity = None
    if stage_present:
        stage.mkdir(parents=True)
        (stage / "input").mkdir()
        identity = guard.stage_identity(stage)
    tag = "1" * 16
    record = {
        "version": 1, "attempt": 1,
        "resourceIntent": {
            "tag": tag,
            "containerName": "stdlib-cli-run-0001-" + tag,
            "stageDir": str(stage),
            "stageIdentity": identity,
            "containerCreated": False,
        },
        "stageDir": str(stage),
        "stageIdentity": identity,
        "containerCreated": False,
        "processes": {"client": {"spawnState": "not-started"},
                      "observer": {"spawnState": "not-started"}},
        "reservationHeld": True,
        "checkpoints": [],
    }
    (Path(runner.STATE) / "attempt-0001.json").write_text(
        json.dumps(record, sort_keys=True, indent=1) + "\n")
    original_remove = guard.remove_container_verified
    original_cleanup = guard.cleanup_stage
    original_update = runner.update_attempt
    remove_result = remove_result or {"removed": True, "state": "never-created"}
    guard.remove_container_verified = lambda _record: dict(remove_result)
    if cleanup_override is not None:
        guard.cleanup_stage = cleanup_override
    if journal_failure:
        def failing_update(number, **fields):
            if "cleanup" in fields:
                raise OSError("simulated-final-journal-failure")
            return original_update(number, **fields)
        runner.update_attempt = failing_update
    raised = None
    confirmed = None
    try:
        confirmed = runner.cleanup_attempt(record)
    except BaseException as error:  # noqa: BLE001
        raised = type(error).__name__ + ":" + str(error)
    finally:
        guard.remove_container_verified = original_remove
        guard.cleanup_stage = original_cleanup
        runner.update_attempt = original_update
    stored = json.loads((Path(runner.STATE) / "attempt-0001.json").read_text())
    return {
        "confirmed": confirmed,
        "raised": raised,
        "stageExists": stage.exists() or stage.is_symlink(),
        "stageOutcome": (stored.get("cleanup") or {}).get("stage"),
        "reservationHeld": stored.get("reservationHeld"),
        "storedCleanup": stored.get("cleanup"),
    }


@scenario("final-stage-absent-present-permission-link-reappearance")
def final_stage_cases():
    absent = cleanup_harness("absent", stage_present=False)
    present = cleanup_harness("present", stage_present=True)
    identity_changed = cleanup_harness(
        "identity", stage_present=True,
        cleanup_override=lambda path, identity: {
            "removed": False, "state": "identity-changed", "lstatAfter": "present"},
    )
    deletion_failure = cleanup_harness(
        "delete", stage_present=True,
        cleanup_override=lambda path, identity: {
            "removed": False, "state": "rmtree", "lstatAfter": "present"},
    )

    def permission(path, identity):
        return {"removed": False, "state": "lstat-error", "lstatAfter": "unknown",
                "detail": "permission-denied"}

    permission_case = cleanup_harness("permission", stage_present=True,
                                      cleanup_override=permission)

    def reappear(path, identity):
        import resource_guard as guard  # noqa: PLC0415
        result = {"removed": False, "state": "still-present", "lstatAfter": "present"}
        Path(path).mkdir(parents=True, exist_ok=True)
        return result

    reappeared = cleanup_harness("reappear", stage_present=True,
                                 cleanup_override=reappear)
    journal = cleanup_harness("journal", stage_present=True, journal_failure=True)
    checks = {
        "absentConfirmed": absent["confirmed"] is True and absent["stageExists"] is False,
        "presentRemoved": present["confirmed"] is True and present["stageExists"] is False,
        "identityChangedRetained": identity_changed["confirmed"] is False
        and identity_changed["stageExists"] is True,
        "deletionFailureRetained": deletion_failure["confirmed"] is False
        and deletion_failure["stageExists"] is True,
        "permissionUnknownRetained": permission_case["confirmed"] is False
        and permission_case["stageExists"] is True
        and (permission_case["stageOutcome"] or {}).get("lstatAfter") == "unknown",
        "reappearanceRetained": reappeared["confirmed"] is False
        and reappeared["stageExists"] is True,
        "journalFailureRaised": journal["raised"] is not None
        and journal["reservationHeld"] is True,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "cases": {"absent": absent, "present": present,
                      "identity": identity_changed, "delete": deletion_failure,
                      "permission": permission_case, "reappear": reappeared,
                      "journal": journal}}


@scenario("cleanup-unconfirmed-retains-reservation")
def cleanup_unconfirmed():
    case = cleanup_harness(
        "unconfirmed", stage_present=True,
        remove_result={"removed": False, "state": "unknown", "detail": "query-failed"},
    )
    stored = case["storedCleanup"] or {}
    checks = {
        "notConfirmed": case["confirmed"] is False,
        "reservationHeld": case["reservationHeld"] is True,
        "finalCheckAfterResources": stored.get("finalStageCheck") == "after-resources",
        "containerUnknown": (stored.get("container") or {}).get("removed") is not True,
        "stageFilesRetained": case["stageExists"] is True,
    }
    return {"passed": all(checks.values()), "checks": checks, "case": case}


@scenario("different-resource-evidence-rejected-zero-destruction")
def different_resource():
    box = ready_box("fa-different", allowed=(1,))
    box.run_attempt(1)
    plan_path, plan = target_plan(box, 1)
    forged = dict(plan)
    forged["prepareId"] = "2" * 32
    old_tag = forged["tag"]
    new_tag = "3" * 16
    forged["tag"] = new_tag
    forged["containerName"] = forged["containerName"].replace(old_tag, new_tag)
    write_json(box.path / "prepare" / "plans" / ("2" * 32 + ".json"), forged)
    rm_before = docker_count(box, "rm ")
    start_before = docker_count(box, "start ")
    result = box.run(["recover", "--prepare-id", "2" * 32])
    checks = {
        "rejected78": result.returncode == 78,
        # The repaired reader rejects a forged plan at the exact plan-identity
        # guard before the cross-record comparison; both are the same approved
        # ownership rejection.  The old message remains accepted here.
        "identityReason": ("resource-identity-mismatch" in result.stderr
                           or "prepare-plan-identity" in result.stderr
                           or "prepare-plan-selector-mismatch" in result.stderr),
        "noRm": docker_count(box, "rm ") == rm_before,
        "noStart": docker_count(box, "start ") == start_before,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "stderr": result.stderr[-300:]}


@scenario("repeat-recover-no-replay-and-busy-lock")
def repeat_and_lock():
    box = ready_box("fa-repeat", allowed=(1,))
    box.run_attempt(1)
    starts_before = docker_count(box, "start ")
    first = box.run(["recover", "--attempt", "1"])
    second = box.run(["recover", "--attempt", "1"])
    starts_after = docker_count(box, "start ")
    lock_path = box.path / "state" / "batch.lock"
    handle = open(lock_path, "a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        busy = box.run(["recover", "--attempt", "1"])
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
    checks = {
        "first0": first.returncode == 0,
        "second0": second.returncode == 0,
        "replayedFalse": '"replayed": false' in first.stdout
        and '"replayed": false' in second.stdout,
        "noStart": starts_after == starts_before,
        "busy79": busy.returncode == 79 and "batch-locked" in busy.stderr,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "busyStderr": busy.stderr[-200:]}


@scenario("attempt-budget-spent-and-no-refund")
def budget():
    box = ready_box("fa-budget", allowed=(8,))
    result = box.run_attempt(8, exit_code=0, mode="zero")
    attempt = box.attempt(8)
    counter = read_json(box.path / "state" / "attempt-counter.json")
    checks = {
        "unknownExit3": result.returncode == 3,
        "used": counter.get("used") == [8],
        "spent": attempt.get("targetExecutions") == 1,
        "settledCleanup": attempt.get("settled") is True
        and attempt.get("reservationHeld") is False,
        "syntaxUnknown": (box.verdict(8) or {}).get("reason")
        == "syntax-reject-target-exit",
    }
    return {"passed": all(checks.values()), "checks": checks}


# ------------------------------------------------------------------- judge
def judge_outcomes_scenario():
    box = ready_box("fa-judge", allowed=(1, 5, 9, 13, 8))
    outcomes = {}
    runs = {
        1: dict(),
        5: dict(),
        9: dict(),
        13: dict(mode="wrong-caller"),
        8: dict(exit_code=3, mode="zero"),
    }
    for number, kwargs in runs.items():
        result = box.run_attempt(number, **kwargs)
        outcomes[number] = {
            "return": result.returncode,
            "attempt": box.attempt(number),
            "verdict": box.verdict(number) or {},
            "observation": box.observation(number) or {},
        }
    checks = {
        "confirmed1": outcomes[1]["verdict"].get("decision") == "confirmed",
        "dataOnly5": outcomes[5]["verdict"].get("decision") == "excluded"
        and outcomes[5]["verdict"].get("reason") == "data-only-structure",
        "echo9": outcomes[9]["verdict"].get("decision") == "excluded"
        and outcomes[9]["verdict"].get("reason") == "no-dynamic-event",
        "wrongFn13": outcomes[13]["verdict"].get("decision") == "excluded"
        and outcomes[13]["verdict"].get("reason") == "caller-identity-mismatch",
        "q4Correct": outcomes[8]["verdict"].get("decision") == "excluded"
        and outcomes[8]["verdict"].get("reason") == "syntax-reject"
        and outcomes[8]["return"] == 0,
        "allV2": all((value["observation"].get("protocol") == "buffer-v2")
                     for value in outcomes.values()),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "decisions": {number: value["verdict"].get("decision")
                          for number, value in outcomes.items()}}, box


@scenario("judge-valid-data-echo-wrong-function-q4")
def judge_outcomes():
    result, _box = judge_outcomes_scenario()
    return result


@scenario("judge-corruptions-clear-unknown-not-exception")
def judge_corruptions():
    box = ready_box("fa-corrupt", allowed=(1,))
    box.run_attempt(1)
    run = run_dir(box, 1)
    observation_path = run / "observation.json"
    raw_path = run / "observer.raw"
    attempt_path_value = attempt_path(box, 1)
    original_observation = observation_path.read_bytes()
    original_attempt = attempt_path_value.read_bytes()
    original_raw = raw_path.read_bytes()
    cases = {}

    def run_case(name, **kwargs):
        observation_path.write_bytes(original_observation)
        attempt_path_value.write_bytes(original_attempt)
        raw_path.write_bytes(original_raw)
        result, verdict = judge(box, 1, out=run / ("verification-" + name + ".json"),
                                **kwargs)
        cases[name] = {"return": result.returncode,
                       "decision": verdict.get("decision"),
                       "reason": verdict.get("reason")}
        return verdict

    # 1. stored events replaced by another valid event set, then re-signed.
    import structure  # noqa: PLC0415
    observation = read_json(observation_path)
    forged = json.loads(json.dumps(observation))
    event = forged["events"][0]
    event["dynamicStructure"]["firstlineno"] = int(
        event["dynamicStructure"].get("firstlineno") or 0) + 1
    event["dynamicStructureSha256"] = structure.structure_digest(
        event["dynamicStructure"])
    event["dynamicCodeSha256"] = structure.code_digest_from_structure(
        event["dynamicStructure"])
    write_json(observation_path, forged)
    resign_observation(box, 1)
    result, verdict = judge(box, 1, out=run / "verification-stale-events.json")
    cases["stale-events"] = {"return": result.returncode,
                             "decision": verdict.get("decision"),
                             "reason": verdict.get("reason")}
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)

    # 2. bytes appended inside the raw stream (not the END-LF trailer)
    raw_path.write_bytes(original_raw + b"tamper\n")
    resign_observation(box, 1, raw_path=raw_path)
    result, verdict = judge(box, 1, out=run / "verification-raw-tamper.json")
    cases["raw-tamper"] = {"return": result.returncode,
                           "decision": verdict.get("decision"),
                           "reason": verdict.get("reason")}

    # 2b. missing END
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    raw_path.write_bytes(original_raw.rsplit(b"END ", 1)[0])
    resign_observation(box, 1, raw_path=raw_path)
    result, verdict = judge(box, 1, out=run / "verification-missing-end.json")
    cases["missing-end"] = {"return": result.returncode,
                            "decision": verdict.get("decision"),
                            "reason": verdict.get("reason")}

    # 2c. truncated raw
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    raw_path.write_bytes(original_raw[: max(1, len(original_raw) // 2)])
    resign_observation(box, 1, raw_path=raw_path)
    result, verdict = judge(box, 1, out=run / "verification-truncated.json")
    cases["truncated"] = {"return": result.returncode,
                          "decision": verdict.get("decision"),
                          "reason": verdict.get("reason")}

    # 2d. unsupported structure record
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    lines = original_raw.splitlines(keepends=True)
    end_index = next(index for index, line in enumerate(lines)
                     if line.startswith(b"END "))
    lines.insert(end_index, b"UNSUPPORTED probe\n")
    raw_path.write_bytes(b"".join(lines))
    resign_observation(box, 1, raw_path=raw_path)
    result, verdict = judge(box, 1, out=run / "verification-unsupported.json")
    cases["unsupported"] = {"return": result.returncode,
                            "decision": verdict.get("decision"),
                            "reason": verdict.get("reason")}

    # 3. legacy template instead of pinned buffer-v2
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    raw_path.write_bytes(original_raw)
    legacy = box.path / "tools" / "observer_template.bt"
    result, verdict = judge(box, 1, template=legacy,
                            out=run / "verification-legacy-template.json")
    cases["legacy-template"] = {"return": result.returncode,
                                "decision": verdict.get("decision"),
                                "reason": verdict.get("reason")}

    # 4. payload=None must be a clear unknown, not AttributeError crash
    expected_path = box.path / "prepare" / "compile-0001" / "expected.json"
    expected = read_json(expected_path)
    original_expected = expected_path.read_bytes()
    expected["payload"] = None
    write_json(expected_path, expected)
    attempt = read_json(attempt_path_value)
    attempt["expectedSha256"] = sha(expected_path)
    write_json(attempt_path_value, attempt)
    result, verdict = judge(box, 1, out=run / "verification-payload-none.json")
    cases["payload-none"] = {"return": result.returncode,
                             "decision": verdict.get("decision"),
                             "reason": verdict.get("reason")}
    expected_path.write_bytes(original_expected)

    # 5. wrong policy
    result, verdict = judge(box, 1, extra=["--framing-policy", "legacy"],
                            out=run / "verification-bad-policy.json")
    cases["bad-policy"] = {"return": result.returncode,
                           "decision": verdict.get("decision"),
                           "reason": verdict.get("reason")}

    # 6. wrong caller offset in stored observation, re-signed
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    raw_path.write_bytes(original_raw)
    observation = read_json(observation_path)
    observation["callOffset"] = observation["callOffset"] + 1
    write_json(observation_path, observation)
    resign_observation(box, 1)
    result, verdict = judge(box, 1, out=run / "verification-wrong-offset.json")
    cases["wrong-offset"] = {"return": result.returncode,
                             "decision": verdict.get("decision"),
                             "reason": verdict.get("reason")}

    # 7. a forged confirmed flag cannot turn a zero-event raw into confirmation
    import buffer_protocol_v2  # noqa: PLC0415
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    raw_path.write_bytes(original_raw)
    attempt = read_json(attempt_path_value)
    bind = read_json(box.path / "prepare" / "bind" / "bind.json")
    result_bind = next(item for item in bind["results"]
                       if item["classId"] == attempt["classId"])
    run_id = attempt["runId"]
    tag = attempt["challenge"][:12]
    caller_path = "/review/runroot/" + result_bind["stagedPath"]
    zero_raw = ("BEGIN run=%s tag=%s\n" % (run_id, tag)).encode("ascii")
    zero_raw += buffer_protocol_v2.MARKER.encode("ascii") + b"\n"
    zero_raw += ("END run=%s tag=%s events=0\n" % (run_id, tag)).encode("ascii")
    forged_observation = buffer_protocol_v2.parse_receipt(
        zero_raw, run_id, tag, caller_path, result_bind["callOffset"],
        attempt["targetPid"], attempt["targetUid"], max_events=4,
    )
    forged_observation["confirmed"] = True
    forged_observation["decision"] = "confirmed"
    raw_path.write_bytes(zero_raw)
    write_json(observation_path, forged_observation)
    resign_observation(box, 1, raw_path=raw_path)
    result, verdict = judge(box, 1, out=run / "verification-forged-confirmed.json")
    cases["forged-confirmed"] = {"return": result.returncode,
                                 "decision": verdict.get("decision"),
                                 "reason": verdict.get("reason")}

    # 8. wrong point id
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    raw_path.write_bytes(original_raw)
    attempt = read_json(attempt_path_value)
    attempt["pointId"] = "f" * 64
    write_json(attempt_path_value, attempt)
    result, verdict = judge(box, 1, out=run / "verification-wrong-point.json")
    cases["wrong-point"] = {"return": result.returncode,
                            "decision": verdict.get("decision"),
                            "reason": verdict.get("reason")}

    # 9. missing raw evidence
    result, verdict = judge(box, 1, raw=run / "missing.raw",
                            out=run / "verification-missing-raw.json")
    cases["missing-raw"] = {"return": result.returncode,
                            "decision": verdict.get("decision"),
                            "reason": verdict.get("reason")}

    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)
    raw_path.write_bytes(original_raw)
    checks = {
        "allUnknown": all(value["decision"] == "unknown" for name, value in cases.items()
                          if name != "forged-confirmed"),
        "forgedNotConfirmed": cases["forged-confirmed"]["decision"] != "confirmed",
        "allExit3": all(value["return"] == 3 for name, value in cases.items()
                        if name != "forged-confirmed"),
        "staleReason": "observation-canonical" in (cases["stale-events"]["reason"] or ""),
        "payloadReason": "expected-payload-type" in (cases["payload-none"]["reason"] or ""),
        "policyReason": "framing-policy" in (cases["bad-policy"]["reason"] or ""),
    }
    return {"passed": all(checks.values()), "checks": checks, "cases": cases}


@scenario("judge-end-lf-trailer-boundary-and-strict-types")
def trailer_and_types():
    box = ready_box("fa-trailer", allowed=(1,))
    box.run_attempt(1)
    run = run_dir(box, 1)
    raw_path = run / "observer.raw"
    observation_path = run / "observation.json"
    attempt_path_value = attempt_path(box, 1)
    original_raw = raw_path.read_bytes()
    original_observation = observation_path.read_bytes()
    original_attempt = attempt_path_value.read_bytes()
    cases = {}
    for count in (0, 1, 8, 9):
        raw_path.write_bytes(original_raw + b"\n" * count)
        observation = read_json(observation_path)
        observation["trailingBlankLines"] = count
        write_json(observation_path, observation)
        resign_observation(box, 1, raw_path=raw_path)
        result, verdict = judge(box, 1, out=run / ("verification-lf-%d.json" % count))
        cases["lf-%d" % count] = {"return": result.returncode,
                                  "decision": verdict.get("decision"),
                                  "reason": verdict.get("reason")}
    raw_path.write_bytes(original_raw)
    observation_path.write_bytes(original_observation)
    attempt_path_value.write_bytes(original_attempt)

    # bool is not an int exit code
    attempt = read_json(attempt_path_value)
    attempt["targetExit"] = True
    write_json(attempt_path_value, attempt)
    result, verdict = judge(box, 1, out=run / "verification-bool-exit.json")
    cases["bool-exit"] = {"return": result.returncode,
                          "decision": verdict.get("decision"),
                          "reason": verdict.get("reason")}
    attempt_path_value.write_bytes(original_attempt)
    checks = {
        "lf0": cases["lf-0"]["decision"] == "confirmed",
        "lf1": cases["lf-1"]["decision"] == "confirmed",
        "lf8": cases["lf-8"]["decision"] == "confirmed",
        "lf9Unknown": cases["lf-9"]["decision"] == "unknown",
        "boolUnknown": cases["bool-exit"]["decision"] == "unknown"
        and "invalid-returncode-type" in (cases["bool-exit"]["reason"] or ""),
    }
    return {"passed": all(checks.values()), "checks": checks, "cases": cases}


@scenario("preparation-does-not-consume-target-attempt")
def preparation_budget():
    box = ready_box("fa-prep-budget", allowed=(1,))
    counter_path = box.path / "state" / "attempt-counter.json"
    counter_before = read_json(counter_path) if counter_path.is_file() else {"used": []}
    bind_plans = [read_json(path) for path in plans(box)]
    checks = {
        "noAttemptFiles": not list((box.path / "state").glob("attempt-*.json")),
        "counterUnchanged": counter_before.get("used") == [],
        "bindPlanRecorded": any(value.get("operationRole", "").startswith("bind-")
                                for value in bind_plans),
        "noTargetPlan": not any(value.get("attempt") == 1 for value in bind_plans),
    }
    return {"passed": all(checks.values()), "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(CHECKS / "formal-admission-results.json"))
    parser.add_argument("--evidence", default=str(CHECKS / "evidence-runs" / "formal-admission"))
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(CHECKS / "tmp").mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "formal-admission-simulated-results",
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "realTargets": 0,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "formalTargets": "0/16",
        "r3": "blocked",
        "shimResolution": dict(regression_lib.SHIM_RESOLUTIONS),
        "results": RESULTS,
        "total": len(RESULTS),
        "passed": sum(1 for item in RESULTS if item["passed"]),
        "failed": [item["test"] for item in RESULTS if not item["passed"]],
        "note": "Docker and bpftrace are controlled shims. In-process cases "
                "monkeypatch resource calls. Not a real-machine result.",
    }
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    Path(args.evidence).mkdir(parents=True, exist_ok=True)
    (Path(args.evidence) / "formal-admission-results.json").write_text(
        out.read_text(encoding="utf-8"), encoding="utf-8")
    (Path(args.evidence) / "SIMULATED.txt").write_text(
        "SIMULATED recorded-shim evidence only. No real container, bpftrace, "
        "preflight, selfcheck or target execution. Not product approval.\n",
        encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not payload["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
