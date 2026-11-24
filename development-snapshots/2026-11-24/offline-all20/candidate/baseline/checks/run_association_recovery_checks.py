#!/usr/bin/env python3
"""Desired-behaviour checks for B5-B7 association recovery.

This file is source-parameterised: it can be pointed at ``baseline/tools`` to
record RED desired-behaviour failures and at the repaired ``tools`` directory
for GREEN.  Every resource operation is an in-process double with a call
counter.  No Docker, bpftrace, signal, target, fixture, selfcheck or admission
file is ever created or executed.

The checks encode the approved B5-B7 contract:

* B5: historical monotonic resource creation proof is separate from the
  *current* cleanup status; every cleanup durably records checking/held before
  any resource query; reappeared resources keep parent and child held and never
  regress the historical creation proof.
* B6: association is a three-write protocol (parent intent + child id, child
  parentAttempt, parent completion) and recovery reconciles the original
  association from the parent list, pending intent and reverse child links.
* B7: direct ``recover/cleanup --prepare-id`` read failures are incomplete (3),
  ownership contradictions are blocked (78), a genuine lock is 79 and CLI
  ambiguity stays 2.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
RESULTS = []
NOT_CREATED = {"stage": True, "container": True, "client": True, "observer": True}


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_runner(tools):
    tools = Path(tools).resolve()
    name = "association_recovery_runner_" + sha_file(
        tools / "experiment_runner.py")[:12] + "_" + uuid.uuid4().hex[:6]
    spec = importlib.util.spec_from_file_location(name, tools / "experiment_runner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(tools))
    spec.loader.exec_module(module)
    return module


def check(identifier, description):
    def decorate(function):
        RESULTS.append((identifier, description, function))
        return function
    return decorate


class Workspace:
    """A private state/prepare/runs tree with the runner globals redirected."""

    def __init__(self, runner, prefix="association-recovery-"):
        self.runner = runner
        self.root = Path(tempfile.mkdtemp(prefix=prefix, dir=TMP))
        self.prepare = self.root / "prepare"
        self.state = self.root / "state"
        self.runs = self.root / "runs"
        for path in (self.prepare, self.state, self.runs):
            path.mkdir()
        self.saved = (runner.ROOT, runner.PREPARE, runner.RUNS, runner.STATE,
                      runner._PREFLIGHT_RESULT)
        runner.ROOT = self.root
        runner.PREPARE = self.prepare
        runner.RUNS = self.runs
        runner.STATE = self.state
        runner._PREFLIGHT_RESULT = None
        runner.release_batch_lock()

    def close(self):
        try:
            self.runner.release_batch_lock()
        finally:
            (self.runner.ROOT, self.runner.PREPARE, self.runner.RUNS,
             self.runner.STATE, self.runner._PREFLIGHT_RESULT) = self.saved
            shutil.rmtree(self.root, ignore_errors=True)


def write_json(runner, path, value):
    runner.write_json_document(Path(path), value)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fake_preflight(runner):
    return {
        "preflightId": "a" * 32,
        "receiptSha256": "b" * 64,
        "profileSha256": "c" * 64,
        "profile": {},
        "layoutSha256": "d" * 64,
        "layoutStructureSha256": "e" * 64,
        "bufferParserSha256": "f" * 64,
        "bufferTemplateSha256": "0" * 64,
        "frozenTemplateSha256": "0" * 64,
    }


def fake_prepare_inputs(runner):
    import structure  # noqa: PLC0415

    layout = {"preflightId": "a" * 32, "runtime": {}}
    layout_bytes = (json.dumps(layout, sort_keys=True, indent=1) + "\n").encode()
    return {
        "layout": layout,
        "layoutBytes": layout_bytes,
        "layoutSha256": hashlib.sha256(layout_bytes).hexdigest(),
        "layoutStructureSha256": structure.digest(layout),
        "templateBytes": b"template",
        "templateSha256": hashlib.sha256(b"template").hexdigest(),
        "profile": {},
        "profileSha256": "c" * 64,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "bufferParserSha256": "f" * 64,
        "bufferTemplateSha256": "e" * 64,
        "frozenTemplateSha256": "e" * 64,
    }


def reserve_one(runner, workspace, number=1):
    plan = json.loads((ROOT / "experiment-plan.json").read_text())
    with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)):
        record = runner.reserve_attempt(
            plan, "a" * 64, number,
            {"allowedAttempts": [number], "reviewer": "simulated"},
        )
    return record


def lifecycle_plan(runner, guard, prepare_id, role, stage, tag, attempt=None,
                   stage_state="created", processes=None, parent_attempt=None,
                   extra=None):
    """Write one exact lifecycle plan, optionally with a real stage directory."""
    stage = Path(stage)
    if stage_state == "created":
        stage.mkdir(parents=True, exist_ok=True)
        identity = guard.stage_identity(stage)
    else:
        identity = None
    plan = {
        "version": 3,
        "protocolRevision": 3,
        "kind": "resource-lifecycle-plan",
        "prepareId": prepare_id,
        "operationRole": role,
        "role": role,
        "attempt": attempt,
        "state": "planned",
        "stageDir": str(stage),
        "stageState": stage_state,
        "stageIdentity": identity,
        "tag": tag,
        "containerName": runner.container_name(role, tag),
        "imageId": runner.IMAGE,
        "image": runner.IMAGE,
        "mounts": [],
        "processes": processes or {"client": {"spawnState": "not-started"}},
        "containerState": "not-created",
        "containerId": None,
        "reservationHeld": True,
        "createdAt": "1970-01-01T00:00:00+00:00",
    }
    if parent_attempt is not None:
        plan["parentAttempt"] = parent_attempt
    if extra:
        plan.update(extra)
    runner.write_json_document(runner.lifecycle_plan_path(prepare_id), plan)
    return prepare_id, plan


def proof(phase="reserved", not_created=None, number=1):
    return {
        "protocol": "resource-phase-v1",
        "phase": phase,
        "sequence": [{"phase": phase, "at": "1970-01-01T00:00:00+00:00"}],
        "notCreated": dict(not_created or NOT_CREATED),
        "targetAttempt": number,
    }


def target_record(runner, number, prepare_id, plan, **extra):
    record = {
        "version": 1,
        "attempt": number,
        "state": "planned",
        "prepareId": prepare_id,
        "resourceIntent": dict(plan),
        "stageDir": plan.get("stageDir"),
        "stageIdentity": plan.get("stageIdentity"),
        "processes": dict(plan.get("processes") or {}),
        "reservationHeld": True,
        "settled": False,
        "targetExecutions": 0,
        "executionState": "not-started",
        "resourceProof": proof("stage-created" if plan.get("stageState") == "created"
                               else "reserved",
                               {"stage": plan.get("stageState") != "created",
                                "container": True, "client": True, "observer": True},
                               number),
        "checkpoints": [],
    }
    record.update(extra)
    runner.write_json_document(runner.attempt_path(number), record)
    return record


def clean_target(runner, guard, workspace, number=1, tag="9" * 16,
                 prep_id=None):
    """A valid target plan whose stage/container/processes were never created."""
    prepare_id = prep_id or os.urandom(16).hex()
    stage = workspace.runs / ("%04d" % number) / ("stage-" + tag)
    prepare_id, plan = lifecycle_plan(
        runner, guard, prepare_id, "run-%04d" % number, stage, tag,
        attempt=number, stage_state="not-created",
        processes={"client": {"spawnState": "not-started"},
                   "observer": {"spawnState": "not-started"}},
    )
    record = target_record(runner, number, prepare_id, plan)
    return prepare_id, plan, record


@contextlib.contextmanager
def resource_doubles(runner, guard, *, on_remove=None, on_lookup=None,
                     remove_result=None, spawn_state=None, stage="real",
                     docker_forbidden=True):
    """Replace every real/destructive resource operation with a counter."""
    calls = {"remove": 0, "stop": 0, "stage": 0, "docker": 0,
             "lookup": 0, "tagLookup": 0, "spawn": 0}

    def remove(record):
        calls["remove"] += 1
        if on_remove is not None:
            on_remove()
        if remove_result is not None:
            return dict(remove_result)
        return {"removed": True, "state": "never-created"}

    def stop(identity, graceful=0, term=0):
        calls["stop"] += 1
        return {"stopped": True, "state": "exited", "forced": False}

    def docker(*args, **kwargs):
        calls["docker"] += 1
        if docker_forbidden:
            raise AssertionError("real Docker forbidden in pure test: %r" % (args,))
        return subprocess.CompletedProcess(args, 0, "", "")

    def lookup(identifier):
        calls["lookup"] += 1
        if on_lookup is not None:
            on_lookup()
        return {"state": "absent"}

    def tag_lookup(tag):
        calls["tagLookup"] += 1
        return {"state": "absent"}

    def spawn(record):
        calls["spawn"] += 1
        if spawn_state is not None:
            return spawn_state(record)
        if isinstance(record, dict) and record.get("spawnState") == "unknown":
            return {"state": "unknown", "detail": "synthetic-unknown"}
        return {"state": "exited", "proof": "not-started"}

    original_stage = runner.cleanup_stage

    def cleanup_stage(path, identity):
        calls["stage"] += 1
        if stage == "stub":
            return {"removed": True, "state": "removed", "lstatAfter": "absent"}
        return original_stage(path, identity)

    with patch.object(guard, "remove_container_verified", remove), \
            patch.object(guard, "stop_group", stop), \
            patch.object(guard, "docker", docker), \
            patch.object(guard, "container_lookup", lookup), \
            patch.object(guard, "container_tag_lookup", tag_lookup), \
            patch.object(guard, "spawn_group_state", spawn), \
            patch.object(runner, "cleanup_stage", cleanup_stage):
        yield calls


def no_destructive(calls):
    return calls["remove"] == 0 and calls["stop"] == 0 and calls["stage"] == 0


def exit_code(function, *args, **kwargs):
    try:
        value = function(*args, **kwargs)
        return "return", value
    except SystemExit as error:
        return "exit", error.code
    except BaseException as error:  # noqa: BLE001 - traceback is not a 78
        return "raised", type(error).__name__ + ":" + str(error)[:200]


def recover(runner, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as out, \
            contextlib.redirect_stderr(io.StringIO()) as err:
        kind, value = exit_code(runner.command_recover, **kwargs)
    runner.release_batch_lock()
    return kind, value, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------- B5
@check("B5-current-cleanup-after-previous-success",
       "a reappeared associated stage makes the current cleanup incomplete, not a stale success")
def b5_current_after_success(runner, guard):
    workspace = Workspace(runner, "b5-reappear-")
    try:
        target_tag = "a" * 16
        target_stage = workspace.runs / "0001" / ("stage-" + target_tag)
        write_json(runner, runner.counter_path(),
                   {"version": 1, "used": [1], "max": 16})
        target_id, target_plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(), "run-0001", target_stage,
            target_tag, attempt=1,
            processes={"client": {"spawnState": "not-started"},
                       "observer": {"spawnState": "not-started"}},
        )
        compile_tag = "b" * 16
        compile_stage = workspace.prepare / ("stage-compile-0001-" + compile_tag)
        compile_id, compile_plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "compile-0001-" + compile_tag[:8], compile_stage, compile_tag,
            attempt=1, parent_attempt=1,
        )
        record = target_record(runner, 1, target_id, target_plan)
        record["associatedPrepareIds"] = [compile_id]
        write_json(runner, runner.attempt_path(1), record)

        with resource_doubles(runner, guard) as calls:
            first = recover(runner, number=1)
            before_second = read_json(runner.attempt_path(1))
            creation_before = json.dumps(before_second.get("resourceProof"),
                                         sort_keys=True)
            # A reappeared directory must not accidentally reuse the deleted
            # directory's inode: cleanup correctly retains a different identity.
            old_identity = compile_plan.get("stageIdentity") or {}
            for attempt in range(12):
                decoys = [workspace.prepare / (
                    "decoy-%d-%d" % (attempt, index)) for index in range(attempt + 1)]
                for decoy in decoys:
                    decoy.mkdir()
                compile_stage.mkdir(parents=True, exist_ok=True)
                for decoy in decoys:
                    shutil.rmtree(decoy)
                new_identity = guard.stage_identity(compile_stage) or {}
                if (new_identity.get("dev"), new_identity.get("ino")) != (
                        old_identity.get("dev"), old_identity.get("ino")):
                    break
                shutil.rmtree(compile_stage)
            else:
                raise AssertionError("could not create a distinct reappeared stage")
            second = recover(runner, number=1)
            after_second = read_json(runner.attempt_path(1))
            child_after = read_json(runner.lifecycle_plan_path(compile_id))
            second_stage_retained = compile_stage.is_dir()
            creation_after = json.dumps(after_second.get("resourceProof"), sort_keys=True)
            # Restoration: a fresh full check after the reappeared directory is
            # really gone must be able to clear success again.
            shutil.rmtree(compile_stage)
            third = recover(runner, number=1)
            after_third = read_json(runner.attempt_path(1))
            child_third = read_json(runner.lifecycle_plan_path(compile_id))
            counter = read_json(runner.counter_path())
        checks = {
            "firstSuccess": first[0] == "return" and first[1] == 0,
            "firstSettled": before_second.get("settled") is True
            and before_second.get("reservationHeld") is False,
            "secondIncomplete3": second[0] == "return" and second[1] == 3,
            "secondNotPhaseRegression78": not (second[0] == "exit" and second[1] == 78),
            "secondParentHeld": after_second.get("reservationHeld") is True,
            "secondParentNotSettled": after_second.get("settled") is False,
            "secondCleanupUnconfirmed": (after_second.get("cleanup") or {}).get(
                "confirmed") is False,
            "secondChildHeld": child_after.get("reservationHeld") is True,
            "secondChildStageRetained": second_stage_retained,
            "historicalCreationUnchanged": creation_before == creation_after,
            "historicalHasNoCleanupRegression":
                json.dumps(after_second.get("resourceProof"), sort_keys=True) ==
                creation_before,
            "thirdSuccess": third[0] == "return" and third[1] == 0,
            "thirdSettled": after_third.get("settled") is True
            and after_third.get("reservationHeld") is False,
            "thirdCleanupConfirmed": (after_third.get("cleanup") or {}).get(
                "confirmed") is True,
            "thirdChildReleased": child_third.get("reservationHeld") is False,
            "counterSpent": counter.get("used") == [1],
            "noReplay": after_third.get("targetExecutions") == 0,
            "historicalReceiptsPreserved": any(
                item.get("state") == "confirmed"
                for item in (after_third.get("cleanupReceipts") or []))
            and any(item.get("state") == "incomplete"
                    for item in (after_third.get("cleanupReceipts") or [])),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {
            "checks": checks,
            "first": first,
            "second": second,
            "third": third,
            "calls": calls,
            "secondCleanup": after_second.get("cleanup"),
            "secondCheck": after_second.get("cleanupCheck"),
            "thirdReceipts": after_third.get("cleanupReceipts"),
        }
    finally:
        workspace.close()


@check("B5-durable-checking-before-query",
       "cleanup writes checking/held/unsettled durably before the first resource query")
def b5_durable_checking(runner, guard):
    workspace = Workspace(runner, "b5-checking-")
    try:
        prepare_id, plan, record = clean_target(runner, guard, workspace)
        # Simulate a previously successful cleanup: the next check must first
        # clear the stale success durably.
        record.update({"settled": True, "reservationHeld": False,
                       "cleanup": {"confirmed": True, "checkedAt":
                                   "1970-01-01T00:00:00+00:00"}})
        plan.update({"containerState": "created", "containerId": "1" * 64})
        write_json(runner, runner.lifecycle_plan_path(prepare_id), plan)
        record["resourceIntent"] = dict(plan)
        write_json(runner, runner.attempt_path(1), record)
        captured = {}

        def observe():
            if "record" not in captured:
                captured["record"] = read_json(runner.attempt_path(1))

        with resource_doubles(runner, guard, on_remove=observe) as calls:
            kind, value = exit_code(runner.cleanup_attempt, record)
        observed = captured.get("record") or {}
        checks = {
            "cleanupReturned": kind == "return" and value is True,
            "checkingDurableBeforeQuery":
                (observed.get("cleanupCheck") or {}).get("state") == "checking",
            "settledFalseBeforeQuery": observed.get("settled") is False,
            "reservationHeldBeforeQuery": observed.get("reservationHeld") is True,
            "currentCleanupChecking":
                (observed.get("cleanup") or {}).get("state") == "checking",
            "resourceQueryRan": calls["remove"] == 1,
            "noOtherRealCalls": calls["docker"] == 0 and calls["stop"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "observed": observed}
    finally:
        workspace.close()


@check("B5-begin-check-journal-failure",
       "an unpersisted cleanup-check start is incomplete and performs no resource query")
def b5_begin_journal_failure(runner, guard):
    workspace = Workspace(runner, "b5-begin-fail-")
    try:
        prepare_id, plan, record = clean_target(runner, guard, workspace)
        original_update = runner.update_attempt

        def failing(number, **fields):
            check = fields.get("cleanupCheck") or {}
            if check.get("state") == "checking":
                raise OSError("simulated-cleanup-check-start-failure")
            return original_update(number, **fields)

        with patch.object(runner, "update_attempt", failing), \
                resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "incomplete3": kind == "return" and value == 3,
            "diagnostic": "incomplete-cleanup" in err,
            "noResourceQuery": all(calls[key] == 0 for key in
                                   ("remove", "stop", "stage", "docker",
                                    "lookup", "tagLookup", "spawn")),
            "parentHeld": stored.get("reservationHeld") is True,
            "notSettled": stored.get("settled") is not True,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stored": stored, "stderr": err[-300:]}
    finally:
        workspace.close()


@check("B5-final-journal-failure",
       "final attempt or plan journal failure is incomplete, never success")
def b5_final_journal_failure(runner, guard):
    results = {}
    cases = []
    # Attempt final journal failure after a clean full check.
    workspace = Workspace(runner, "b5-final-attempt-")
    try:
        prepare_id, plan, record = clean_target(runner, guard, workspace,
                                                tag="c" * 16)
        original_update = runner.update_attempt

        def failing_attempt(number, **fields):
            check = fields.get("cleanupCheck") or {}
            if check.get("state") in {"confirmed", "incomplete"}:
                raise OSError("simulated-final-attempt-journal-failure")
            return original_update(number, **fields)

        with patch.object(runner, "update_attempt", failing_attempt), \
                resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        results["attempt"] = {
            "kind": kind, "value": value, "calls": calls,
            "reservationHeld": stored.get("reservationHeld"),
            "settled": stored.get("settled"),
            "check": stored.get("cleanupCheck"), "stderr": err[-300:],
        }
        cases.append(kind == "return" and value == 3
                     and stored.get("reservationHeld") is True
                     and stored.get("settled") is not True)
    finally:
        workspace.close()
    # Plan final journal failure for an associated child.
    workspace = Workspace(runner, "b5-final-plan-")
    try:
        target_tag = "d" * 16
        target_stage = workspace.runs / "0001" / ("stage-" + target_tag)
        write_json(runner, runner.counter_path(),
                   {"version": 1, "used": [1], "max": 16})
        target_id, target_plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(), "run-0001", target_stage,
            target_tag, attempt=1,
            processes={"client": {"spawnState": "not-started"},
                       "observer": {"spawnState": "not-started"}},
        )
        compile_tag = "e" * 16
        compile_stage = workspace.prepare / ("stage-compile-0001-" + compile_tag)
        compile_id, compile_plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "compile-0001-" + compile_tag[:8], compile_stage, compile_tag,
            attempt=1, parent_attempt=1,
        )
        record = target_record(runner, 1, target_id, target_plan)
        record["associatedPrepareIds"] = [compile_id]
        write_json(runner, runner.attempt_path(1), record)
        original_plan_update = runner.update_lifecycle_plan

        def failing_plan(identifier, **fields):
            if (fields.get("state") in {"cleanup-confirmed", "cleanup-unconfirmed"}
                    and "cleanup" in fields):
                raise OSError("simulated-final-plan-journal-failure")
            return original_plan_update(identifier, **fields)

        with patch.object(runner, "update_lifecycle_plan", failing_plan), \
                resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        child = read_json(runner.lifecycle_plan_path(compile_id))
        results["plan"] = {
            "kind": kind, "value": value, "calls": calls,
            "reservationHeld": stored.get("reservationHeld"),
            "settled": stored.get("settled"),
            "childHeld": child.get("reservationHeld"),
            "stderr": err[-300:],
        }
        cases.append(kind == "return" and value == 3
                     and stored.get("reservationHeld") is True
                     and stored.get("settled") is not True)
    finally:
        workspace.close()
    return all(cases), {"cases": results, "allIncomplete": all(cases)}


# --------------------------------------------------------------------- B6
@check("B6-association-order",
       "parent intent + child id, child parentAttempt, parent completion write order")
def b6_association_order(runner, guard):
    workspace = Workspace(runner, "b6-order-")
    try:
        workspace.runner.ROOT = ROOT
        reserve_one(runner, workspace)
        plan = json.loads((ROOT / "experiment-plan.json").read_text())
        writes = []
        original_attempt = runner.update_attempt
        original_plan = runner.update_lifecycle_plan

        def watched_attempt(number, **fields):
            writes.append({"kind": "attempt", "fields": fields})
            return original_attempt(number, **fields)

        def watched_plan(prepare_id, **fields):
            writes.append({"kind": "plan", "prepareId": prepare_id,
                           "fields": fields})
            return original_plan(prepare_id, **fields)

        class StopProbe(Exception):
            pass

        def stop_stage(path):
            raise StopProbe()

        with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)), \
                patch.object(runner, "verify_prepare_inputs",
                             lambda _r: fake_prepare_inputs(runner)), \
                patch.object(runner, "update_attempt", watched_attempt), \
                patch.object(runner, "update_lifecycle_plan", watched_plan), \
                patch.object(runner, "_safe_mkdir", stop_stage), \
                resource_doubles(runner, guard) as calls:
            try:
                runner.compile_attempt(plan, "a" * 64, 1, "a" * 32)
            except StopProbe:
                pass
        runner.release_batch_lock()
        plans = [value for value in (workspace.prepare / "plans").glob("*.json")]
        child = read_json(plans[0]) if plans else {}
        child_id = child.get("prepareId")
        first_attempt = next((item for item in writes if item["kind"] == "attempt"), {})
        first_plan = next((item for item in writes if item["kind"] == "plan"), {})
        third = [item for item in writes if item["kind"] == "attempt"]
        final_attempt = third[-1] if third else {}
        intents = (first_attempt.get("fields") or {}).get("associationIntents") or []
        final_intents = (final_attempt.get("fields") or {}).get("associationIntents") or []
        checks = {
            "threeWrites": len(writes) == 3,
            "attemptIntentFirst": writes and writes[0]["kind"] == "attempt"
            and any(item.get("prepareId") == child_id and item.get("state") == "pending"
                    for item in intents),
            "childParentAttemptSecond": len(writes) > 1
            and writes[1]["kind"] == "plan"
            and writes[1].get("prepareId") == child_id
            and writes[1]["fields"].get("parentAttempt") == 1,
            "parentCompletionThird": len(writes) > 2
            and writes[2]["kind"] == "attempt"
            and child_id in (writes[2]["fields"].get("associatedPrepareIds") or [])
            and any(item.get("prepareId") == child_id and item.get("state") == "complete"
                    for item in final_intents),
            "noResourceCalls": all(calls[key] == 0 for key in ("docker", "remove",
                                                               "stop", "stage")),
        }
        return all(checks.values()), {"checks": checks, "writes": writes,
                                      "childId": child_id, "calls": calls}
    finally:
        workspace.close()


def _association_failure_case(runner, guard, name, fail_kind):
    workspace = Workspace(runner, name)
    try:
        workspace.runner.ROOT = ROOT
        reserve_one(runner, workspace)
        plan = json.loads((ROOT / "experiment-plan.json").read_text())
        original_attempt = runner.update_attempt
        original_plan = runner.update_lifecycle_plan
        tool_calls = {"runTool": 0}

        def failing_attempt(number, **fields):
            intents = fields.get("associationIntents")
            if fail_kind == "intent" and intents:
                raise OSError("simulated-intent-write-failure")
            if fail_kind == "complete" and "associatedPrepareIds" in fields:
                raise OSError("simulated-completion-write-failure")
            return original_attempt(number, **fields)

        def failing_plan(prepare_id, **fields):
            if fail_kind == "child" and "parentAttempt" in fields:
                raise OSError("simulated-child-write-failure")
            return original_plan(prepare_id, **fields)

        def unexpected_tool(*args, **kwargs):
            tool_calls["runTool"] += 1
            raise AssertionError("stage/tool must not run with incomplete association")

        raised = None
        with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)), \
                patch.object(runner, "verify_prepare_inputs",
                             lambda _r: fake_prepare_inputs(runner)), \
                patch.object(runner, "update_attempt", failing_attempt), \
                patch.object(runner, "update_lifecycle_plan", failing_plan), \
                patch.object(runner, "run_tool_container", unexpected_tool), \
                resource_doubles(runner, guard) as calls:
            try:
                runner.compile_attempt(plan, "a" * 64, 1, "a" * 32)
            except BaseException as error:  # noqa: BLE001
                raised = type(error).__name__ + ":" + str(error)[:160]
        runner.release_batch_lock()
        stored = read_json(runner.attempt_path(1))
        plans = [read_json(item) for item in
                 (workspace.prepare / "plans").glob("*.json")]
        intents = stored.get("associationIntents") or []
        stage_dirs = list(workspace.prepare.glob("stage-compile-*"))
        checks = {
            "raised": raised is not None,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "noStage": stage_dirs == [],
            "noTool": tool_calls["runTool"] == 0,
            "noResourceCalls": all(calls[key] == 0 for key in
                                   ("docker", "remove", "stop", "stage")),
        }
        if fail_kind in {"child", "complete"}:
            checks["intentDurable"] = any(
                (item.get("state") == "pending"
                 and item.get("prepareId") in [value.get("prepareId") for value in plans])
                for item in intents)
        if fail_kind == "child":
            checks["childNotLinked"] = all(
                value.get("parentAttempt") is None for value in plans)
        if fail_kind == "complete":
            checks["childParentAttempt"] = any(
                value.get("parentAttempt") == 1 for value in plans)
            checks["parentListEmpty"] = not stored.get("associatedPrepareIds")
        return all(checks.values()), {
            "checks": checks, "raised": raised, "calls": calls,
            "stored": {key: stored.get(key) for key in
                       ("reservationHeld", "settled", "associatedPrepareIds",
                        "associationIntents")},
            "plans": [{"prepareId": value.get("prepareId"),
                       "parentAttempt": value.get("parentAttempt"),
                       "stageState": value.get("stageState")} for value in plans],
            "stageDirs": [str(path) for path in stage_dirs],
        }
    finally:
        workspace.close()


@check("B6-interrupt-at-parent-intent",
       "failure before the first association write holds the parent and creates nothing")
def b6_interrupt_intent(runner, guard):
    return _association_failure_case(runner, guard, "b6-intent-", "intent")


@check("B6-interrupt-at-child-parent",
       "failure writing child parentAttempt holds the parent and creates nothing")
def b6_interrupt_child(runner, guard):
    return _association_failure_case(runner, guard, "b6-child-", "child")


@check("B6-interrupt-at-completion",
       "failure of the final association-complete write holds parent and child")
def b6_interrupt_complete(runner, guard):
    passed, detail = _association_failure_case(runner, guard, "b6-complete-", "complete")
    # The recovery for this interrupted association must stay incomplete and
    # must not settle the parent merely because the associated list is empty.
    workspace = Workspace(runner, "b6-complete-recover-")
    try:
        workspace.runner.ROOT = ROOT
        reserve_one(runner, workspace)
        plan = json.loads((ROOT / "experiment-plan.json").read_text())
        original_attempt = runner.update_attempt

        def failing_attempt(number, **fields):
            if "associatedPrepareIds" in fields:
                raise OSError("simulated-completion-write-failure")
            return original_attempt(number, **fields)

        with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)), \
                patch.object(runner, "verify_prepare_inputs",
                             lambda _r: fake_prepare_inputs(runner)), \
                patch.object(runner, "update_attempt", failing_attempt):
            try:
                runner.compile_attempt(plan, "a" * 64, 1, "a" * 32)
            except BaseException:  # noqa: BLE001 - expected interruption
                pass
        runner.release_batch_lock()
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "incomplete3": kind == "return" and value == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "noDestructive": no_destructive(calls),
            "pendingIntentPreserved": any(
                item.get("state") == "pending"
                for item in (stored.get("associationIntents") or [])),
        }
        return passed and all(checks.values()), {
            "interruption": detail, "recoveryChecks": checks,
            "recovery": [kind, value, err[-200:]], "calls": calls,
            "stored": stored,
        }
    finally:
        workspace.close()


@check("B6-reverse-only-child-held",
       "a reverse child-parent relation is reconciled even with an empty parent list")
def b6_reverse_only(runner, guard):
    workspace = Workspace(runner, "b6-reverse-")
    try:
        target_id, target_plan, record = clean_target(runner, guard, workspace,
                                                      tag="f" * 16)
        compile_tag = "1" * 16
        compile_stage = workspace.prepare / ("stage-compile-0001-" + compile_tag)
        compile_id, _plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "compile-0001-" + compile_tag[:8], compile_stage, compile_tag,
            attempt=1, parent_attempt=1,
            processes={"client": {"spawnState": "unknown"}},
        )
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        child = read_json(runner.lifecycle_plan_path(compile_id))
        checks = {
            "incomplete3": kind == "return" and value == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "parentCleanupUnconfirmed": (stored.get("cleanup") or {}).get(
                "confirmed") is False,
            "childHeld": child.get("reservationHeld") is True,
            "childStageRetained": compile_stage.is_dir(),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stored": stored, "stderr": err[-200:]}
    finally:
        workspace.close()


@check("B6-preexisting-standalone-compile-accounted",
       "a standalone compile plan for the attempt is included in parent settlement")
def b6_standalone_compile(runner, guard):
    workspace = Workspace(runner, "b6-standalone-")
    try:
        target_id, target_plan, record = clean_target(runner, guard, workspace,
                                                      tag="2" * 16)
        compile_tag = "3" * 16
        compile_stage = workspace.prepare / ("stage-compile-0001-" + compile_tag)
        compile_id, _plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "compile-0001-" + compile_tag[:8], compile_stage, compile_tag,
            attempt=1, processes={"client": {"spawnState": "unknown"}},
        )
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        child = read_json(runner.lifecycle_plan_path(compile_id))
        checks = {
            "incomplete3": kind == "return" and value == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "childHeld": child.get("reservationHeld") is True,
            "childStageRetained": compile_stage.is_dir(),
            "scanRecorded": (stored.get("cleanup") or {}).get(
                "associationCandidates", 0) >= 1,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "cleanup": stored.get("cleanup")}
    finally:
        workspace.close()


@check("B6-unreadable-related-plan-held",
       "unreadable or malformed potentially relevant plans keep parent held with no destruction")
def b6_unreadable_plan(runner, guard):
    variants = {}
    cases = []
    for variant in ("malformed", "permission", "io"):
        workspace = Workspace(runner, "b6-unreadable-" + variant + "-")
        try:
            target_id, target_plan, record = clean_target(
                runner, guard, workspace, tag=("4" if variant == "malformed" else
                                               "5" if variant == "permission" else
                                               "6") * 16)
            bad_id = ("7" if variant == "malformed" else
                      "8" if variant == "permission" else "9") * 32
            bad_path = runner.lifecycle_plan_path(bad_id)
            bad_path.parent.mkdir(parents=True, exist_ok=True)
            if variant == "malformed":
                bad_path.write_bytes(b"{malformed-not-json\n")
                patcher = contextlib.nullcontext()
            else:
                runner.write_json_document(bad_path, {
                    "version": 3, "protocolRevision": 3,
                    "kind": "resource-lifecycle-plan", "prepareId": bad_id,
                })
                original_read = runner.read_json

                def failing(path, _original=original_read, _bad=bad_path,
                            _kind=variant):
                    if Path(path) == Path(_bad):
                        if _kind == "permission":
                            raise PermissionError("simulated-permission")
                        raise OSError("simulated-io")
                    return _original(path)

                patcher = patch.object(runner, "read_json", failing)
            with patcher, resource_doubles(runner, guard) as calls:
                kind, value, out, err = recover(runner, number=1)
            stored = read_json(runner.attempt_path(1))
            checks = {
                "incomplete3": kind == "return" and value == 3,
                "parentHeld": stored.get("reservationHeld") is True,
                "parentNotSettled": stored.get("settled") is False,
                "noDestructive": no_destructive(calls),
                "noDocker": calls["docker"] == 0,
            }
            variants[variant] = {"checks": checks, "calls": calls,
                                 "stderr": err[-200:]}
            cases.append(all(checks.values()))
        finally:
            workspace.close()
    return all(cases), {"variants": variants, "allIncomplete": all(cases)}


@check("B6-ownership-contradiction-before-destruction",
       "ownership contradictions block 78 before any signal or delete")
def b6_contradiction_before_destruction(runner, guard):
    workspace = Workspace(runner, "b6-contradiction-")
    try:
        target_id, target_plan, record = clean_target(runner, guard, workspace,
                                                      tag="a1" * 8)
        first_id = "1" * 32
        second_id = "2" * 32
        first_tag = "a" * 16
        first_stage = workspace.prepare / ("stage-compile-0001-" + first_tag)
        first_id, first_plan = lifecycle_plan(
            runner, guard, first_id, "compile-0001-" + first_tag[:8],
            first_stage, first_tag, attempt=1, parent_attempt=1,
        )
        second_tag = "b" * 16
        second_stage = workspace.prepare / ("stage-compile-0001-" + second_tag)
        second_id, second_plan = lifecycle_plan(
            runner, guard, second_id, "compile-0001-" + second_tag[:8],
            second_stage, second_tag, attempt=1, parent_attempt=1,
            extra={"prepareId": "3" * 32},
        )
        record["associatedPrepareIds"] = [first_id, second_id]
        write_json(runner, runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        checks = {
            "blocked78": kind == "exit" and value == 78,
            "noDestructiveBeforeBlock": no_destructive(calls),
            "firstStageRetained": first_stage.is_dir(),
            "secondStageRetained": second_stage.is_dir(),
            "noDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stderr": err[-300:]}
    finally:
        workspace.close()


@check("B6-intent-identifies-original-child",
       "pending intent for a missing original child is never substituted by another child")
def b6_intent_original_child(runner, guard):
    workspace = Workspace(runner, "b6-original-")
    try:
        target_id, target_plan, record = clean_target(runner, guard, workspace,
                                                      tag="c1" * 8)
        missing_id = "c" * 32
        record["associationIntents"] = [{
            "protocol": "association-intent-v1",
            "attempt": 1,
            "prepareId": missing_id,
            "state": "pending",
            "startedAt": "1970-01-01T00:00:00+00:00",
        }]
        other_id = "d" * 32
        other_tag = "d" * 16
        other_stage = workspace.prepare / ("stage-compile-0001-" + other_tag)
        other_id, other_plan = lifecycle_plan(
            runner, guard, other_id, "compile-0001-" + other_tag[:8],
            other_stage, other_tag, attempt=1, parent_attempt=1,
        )
        write_json(runner, runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "incomplete3": kind == "return" and value == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "noDestructive": no_destructive(calls),
            "noSubstitution": stored.get("associatedPrepareIds") in (None, []),
            "noAutoLink": other_plan.get("parentAttempt") == 1,
            "originalIntentPreserved": any(
                item.get("prepareId") == missing_id and item.get("state") == "pending"
                for item in (stored.get("associationIntents") or [])),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stored": stored, "stderr": err[-200:]}
    finally:
        workspace.close()


@check("B6-incomplete-association-blocks-creation",
       "a pending association prevents subsequent stage/container/process creation")
def b6_incomplete_blocks_creation(runner, guard):
    workspace = Workspace(runner, "b6-blocks-")
    try:
        record = reserve_one(runner, workspace)
        tag = "e" * 16
        stage = workspace.prepare / ("stage-compile-0001-" + tag)
        compile_id, _plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "compile-0001-" + tag[:8], stage, tag, attempt=1,
            stage_state="not-created", parent_attempt=1,
        )
        record["associationIntents"] = [{
            "protocol": "association-intent-v1", "attempt": 1,
            "prepareId": compile_id, "state": "pending",
            "startedAt": "1970-01-01T00:00:00+00:00",
        }]
        write_json(runner, runner.attempt_path(1), record)
        raised = None
        with resource_doubles(runner, guard) as calls:
            try:
                runner.associate_existing_preparations(1)
            except BaseException as error:  # noqa: BLE001
                raised = type(error).__name__ + ":" + str(error)[:160]
        runner.release_batch_lock()
        stored = read_json(runner.attempt_path(1))
        checks = {
            "raised": raised is not None,
            "noStage": not stage.exists(),
            "parentHeld": stored.get("reservationHeld") is True,
            "parentListNotCompleted": not stored.get("associatedPrepareIds"),
            "noResourceCalls": no_destructive(calls) and calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "raised": raised,
                                      "calls": calls, "stored": stored}
    finally:
        workspace.close()


@check("B6-reverse-only-bind-held",
       "a bind plan reverse-linked to the attempt is reconciled and retained")
def b6_reverse_only_bind(runner, guard):
    workspace = Workspace(runner, "b6-bind-")
    try:
        target_id, target_plan, record = clean_target(runner, guard, workspace,
                                                      tag="e1" * 8)
        bind_tag = "f2" * 8
        bind_stage = workspace.prepare / ("stage-bind-" + bind_tag)
        bind_id, _plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "bind-" + bind_tag[:8], bind_stage, bind_tag,
            attempt=None, parent_attempt=1,
            processes={"client": {"spawnState": "unknown"}},
        )
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        child = read_json(runner.lifecycle_plan_path(bind_id))
        checks = {
            "incomplete3": kind == "return" and value == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "childHeld": child.get("reservationHeld") is True,
            "childStageRetained": bind_stage.is_dir(),
            "candidateScanned": (stored.get("cleanup") or {}).get(
                "associationCandidates", 0) >= 1,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "cleanup": stored.get("cleanup")}
    finally:
        workspace.close()


@check("B6-unrelated-plan-not-cleaned",
       "an unrelated attempt plan is neither destructive evidence nor a blocker")
def b6_unrelated_plan(runner, guard):
    workspace = Workspace(runner, "b6-unrelated-")
    try:
        target_id, target_plan, record = clean_target(runner, guard, workspace,
                                                      tag="a2" * 8)
        other_tag = "b3" * 8
        other_stage = workspace.prepare / ("stage-compile-0002-" + other_tag)
        other_id, _plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "compile-0002-" + other_tag[:8], other_stage, other_tag,
            attempt=2, processes={"client": {"spawnState": "unknown"}},
        )
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "targetSuccess": kind == "return" and value == 0,
            "targetSettled": stored.get("settled") is True,
            "unrelatedStageRetained": other_stage.is_dir(),
            "unrelatedCandidateExcluded": (stored.get("cleanup") or {}).get(
                "associationCandidates", 0) == 0,
            "noRealDocker": calls["docker"] == 0 and calls["stop"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "cleanup": stored.get("cleanup")}
    finally:
        workspace.close()


@check("B6-unlinked-existing-association-blocks-creation",
       "a parent-list child without parentAttempt holds instead of auto-repairing")
def b6_unlinked_existing_blocks(runner, guard):
    workspace = Workspace(runner, "b6-unlinked-")
    try:
        record = reserve_one(runner, workspace)
        tag = "c4" * 8
        stage = workspace.prepare / ("stage-compile-0001-" + tag)
        compile_id, _plan = lifecycle_plan(
            runner, guard, os.urandom(16).hex(),
            "compile-0001-" + tag[:8], stage, tag, attempt=1,
            stage_state="not-created",
        )
        record["associatedPrepareIds"] = [compile_id]
        write_json(runner, runner.attempt_path(1), record)
        raised = None
        with resource_doubles(runner, guard) as calls:
            try:
                runner.associate_existing_preparations(1)
            except BaseException as error:  # noqa: BLE001
                raised = type(error).__name__ + ":" + str(error)[:160]
        runner.release_batch_lock()
        stored = read_json(runner.attempt_path(1))
        checks = {
            "raised": raised is not None,
            "noStage": not stage.exists(),
            "parentHeld": stored.get("reservationHeld") is True,
            "parentListUnchanged": stored.get("associatedPrepareIds") == [compile_id],
            "noIntentInvented": not stored.get("associationIntents"),
            "noResourceCalls": no_destructive(calls) and calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "raised": raised,
                                      "calls": calls, "stored": stored}
    finally:
        workspace.close()


# --------------------------------------------------------------------- B7
def _direct_plan(runner, guard, workspace, prepare_id, tag="f1" * 8,
                 attempt=1):
    stage = workspace.prepare / ("stage-compile-0001-" + tag)
    prepare_id, plan = lifecycle_plan(
        runner, guard, prepare_id, "compile-0001-" + tag[:8], stage, tag,
        attempt=attempt, stage_state="not-created",
    )
    reserve_one(runner, workspace)
    runner.release_batch_lock()
    runner.update_attempt(1, prepareId=prepare_id)
    return plan


@check("B7-direct-prepare-read-classification",
       "missing/malformed/permission/IO direct prepare reads are incomplete 3")
def b7_direct_reads(runner, guard):
    variants = {}
    cases = []
    for variant in ("missing", "malformed", "permission", "io"):
        workspace = Workspace(runner, "b7-direct-" + variant + "-")
        try:
            prepare_id = ("a" if variant == "missing" else
                          "b" if variant == "malformed" else
                          "c" if variant == "permission" else "d") * 32
            plan_path = runner.lifecycle_plan_path(prepare_id)
            if variant != "missing":
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                if variant == "malformed":
                    reserve_one(runner, workspace)
                    runner.release_batch_lock()
                    runner.update_attempt(1, prepareId=prepare_id)
                    plan_path.write_bytes(b"{not-json\n")
                    patcher = contextlib.nullcontext()
                else:
                    _direct_plan(runner, guard, workspace, prepare_id)
                    original_read = runner.read_json

                    def failing(path, _original=original_read, _plan=plan_path,
                                _kind=variant):
                        if Path(path) == Path(_plan):
                            if _kind == "permission":
                                raise PermissionError("simulated-permission")
                            raise OSError("simulated-io")
                        return _original(path)

                    patcher = patch.object(runner, "read_json", failing)
            else:
                reserve_one(runner, workspace)
                runner.release_batch_lock()
                runner.update_attempt(1, prepareId=prepare_id)
                patcher = contextlib.nullcontext()
            with patcher, resource_doubles(runner, guard) as calls:
                kind, value, out, err = recover(runner, prepare_id=prepare_id)
            attempt = read_json(runner.attempt_path(1))
            checks = {
                "incomplete3": kind == "return" and value == 3,
                "not79": not (kind == "exit" and value == 79),
                "parentHeld": attempt.get("reservationHeld") is True,
                "parentNotSettled": attempt.get("settled") is not True,
                "noDestructive": no_destructive(calls),
                "noDocker": calls["docker"] == 0,
                "diagnosticNamesIncomplete": "incomplete" in err,
            }
            variants[variant] = {"checks": checks, "calls": calls,
                                 "stderr": err[-300:],
                                 "result": [kind, value]}
            cases.append(all(checks.values()))
        finally:
            workspace.close()
    return all(cases), {"variants": variants, "allIncomplete": all(cases)}


@check("B7-direct-ownership-contradiction",
       "direct prepare ownership contradiction is blocked 78 with no destruction")
def b7_direct_contradiction(runner, guard):
    workspace = Workspace(runner, "b7-contradiction-")
    try:
        prepare_id = "e" * 32
        other = "f" * 32
        write_plan = {
            "version": 3, "protocolRevision": 3,
            "kind": "resource-lifecycle-plan", "prepareId": other,
            "operationRole": "compile-0001-aaaaaaaa", "role": "compile-0001-aaaaaaaa",
            "attempt": 1, "state": "planned",
            "stageDir": str(workspace.prepare / ("stage-compile-0001-" + "a" * 16)),
            "stageState": "not-created", "stageIdentity": None,
            "tag": "a" * 16,
            "containerName": runner.container_name("compile-0001-aaaaaaaa", "a" * 16),
            "imageId": runner.IMAGE, "image": runner.IMAGE, "mounts": [],
            "processes": {"client": {"spawnState": "not-started"}},
            "containerState": "not-created", "containerId": None,
            "reservationHeld": True,
            "createdAt": "1970-01-01T00:00:00+00:00",
        }
        runner.write_json_document(runner.lifecycle_plan_path(prepare_id), write_plan)
        reserve_one(runner, workspace)
        runner.release_batch_lock()
        runner.update_attempt(1, prepareId=prepare_id)
        with resource_doubles(runner, guard) as calls:
            kind, value, out, err = recover(runner, prepare_id=prepare_id)
        attempt = read_json(runner.attempt_path(1))
        checks = {
            "blocked78": kind == "exit" and value == 78,
            "noDestructive": no_destructive(calls),
            "parentHeld": attempt.get("reservationHeld") is True,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stderr": err[-300:]}
    finally:
        workspace.close()


@check("B7-direct-cleanup-alias-classification",
       "cleanup --prepare-id uses the same incomplete classification as recover")
def b7_cleanup_alias(runner, guard):
    workspace = Workspace(runner, "b7-alias-")
    try:
        prepare_id = "1" * 32
        reserve_one(runner, workspace)
        runner.release_batch_lock()
        runner.update_attempt(1, prepareId=prepare_id)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.main, ["cleanup", "--prepare-id",
                                                  prepare_id])
        runner.release_batch_lock()
        attempt = read_json(runner.attempt_path(1))
        checks = {
            "incomplete3": kind == "return" and value == 3,
            "noDestructive": no_destructive(calls),
            "parentHeld": attempt.get("reservationHeld") is True,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": [kind, value]}
    finally:
        workspace.close()


@check("B7-genuine-lockbusy-and-cli-ambiguity",
       "a genuine held batch lock stays 79 and CLI ambiguity stays 2")
def b7_lock_and_cli(runner, guard):
    import fcntl  # noqa: PLC0415

    sandbox = Path(tempfile.mkdtemp(prefix="b7-lock-", dir=TMP))
    result = None
    handle = None
    try:
        shutil.copytree(Path(runner.__file__).resolve().parent, sandbox / "tools")
        (sandbox / "state").mkdir()
        lock_path = sandbox / "state" / "batch.lock"
        handle = open(lock_path, "a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = [sys.executable, str(sandbox / "tools" / "experiment_runner.py"),
                   "recover", "--prepare-id", "a" * 32]
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=60, cwd=str(sandbox))
    finally:
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        shutil.rmtree(sandbox, ignore_errors=True)
    with contextlib.redirect_stderr(io.StringIO()):
        both = exit_code(runner.main, ["recover", "--attempt", "1",
                                       "--prepare-id", "a" * 32])
        neither = exit_code(runner.main, ["cleanup"])
        both_cleanup = exit_code(runner.main, ["cleanup", "--attempt", "1",
                                               "--prepare-id", "a" * 32])
    checks = {
        "lockbusy79": result is not None and result.returncode == 79,
        "lockDiagnostic": result is not None and "batch-locked" in result.stderr,
        "ambiguous2": all(kind == "exit" and value == 2 for kind, value in
                          (both, neither, both_cleanup)),
    }
    return all(checks.values()), {
        "checks": checks,
        "lockReturn": None if result is None else result.returncode,
        "lockStderr": None if result is None else result.stderr[-160:],
        "ambiguity": [both, neither, both_cleanup],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    tools = Path(args.tools).resolve()
    out = Path(args.out).resolve()
    if out.exists():
        raise SystemExit("refusing to overwrite results: " + str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    runner = load_runner(tools)
    import resource_guard as guard  # noqa: PLC0415 - source-parameterised

    results = []
    for identifier, description, function in RESULTS:
        try:
            passed, detail = function(runner, guard)
            error = None
        except BaseException as exc:  # noqa: BLE001 - classify, never hide
            passed = False
            detail = {}
            error = {"type": type(exc).__name__,
                     "message": str(exc)[:400],
                     "traceback": traceback.format_exc()[-1600:]}
        results.append({"id": identifier, "description": description,
                        "passed": bool(passed), "detail": detail,
                        "error": error})
        print(("PASS " if passed else "FAIL ") + identifier)

    payload = {
        "kind": "association-recovery-b5-b7-checks",
        "sourceTools": str(tools),
        "runnerSha256": sha_file(tools / "experiment_runner.py"),
        "guardSha256": sha_file(tools / "resource_guard.py"),
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "realTargets": 0,
        "fixturesImported": 0,
        "selfcheckExecutions": 0,
        "formalTargets": "0/16",
        "r3": "blocked",
        "results": results,
        "passed": sum(1 for item in results if item["passed"]),
        "failed": [item["id"] for item in results if not item["passed"]],
        "total": len(results),
    }
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                   encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not payload["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
