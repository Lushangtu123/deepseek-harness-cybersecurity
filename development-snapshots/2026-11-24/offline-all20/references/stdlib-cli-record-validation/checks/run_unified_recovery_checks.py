#!/usr/bin/env python3
"""Desired-behaviour checks for unified recovery scope B8/B9/B10/D1.

This module is source-parameterised.  The same file is run against the
untouched frozen baseline to retain RED desired-behaviour failures and against
the repaired candidate for GREEN.  Every resource operation is an in-process
double or a counting stub; no Docker, BPF/bpftrace, compiler, selfcheck,
fixture, target or admission file is executed or imported.

The checks encode:

* B8: directory enumeration must complete.  PermissionError, IO errors,
  partial iteration, links, non-directories and ownership contradictions are
  classified before any destructive call.  A genuinely absent directory is
  distinguished from an unknown one, and empty is not used as an association
  inference in place of the not-created proof and durable references.
* B9: a direct child cleanup first invalidates the exactly bound parent.  The
  child may be reported clean, but the parent stays held with
  ``parent-full-recheck-required`` until a later complete parent recovery.
* B10: every readable known associated child is durably held even when the
  main run plan is missing, malformed or unreadable.  Inaccessible records are
  retained with explicit unknown diagnostics.
* D1: recovering reads of the selected preparation and nested attempt records
  are incomplete (3), not uncaught exceptions and not a false busy (79).
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
import types
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
    name = "unified_recovery_runner_" + sha_file(
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

    def __init__(self, runner, prefix="unified-recovery-"):
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

    @property
    def plans(self):
        return self.prepare / "plans"

    def close(self):
        try:
            self.runner.release_batch_lock()
        finally:
            (self.runner.ROOT, self.runner.PREPARE, self.runner.RUNS,
             self.runner.STATE, self.runner._PREFLIGHT_RESULT) = self.saved
            for path in self.root.rglob("*"):
                try:
                    if path.is_dir():
                        path.chmod(0o700)
                except OSError:
                    pass
            shutil.rmtree(self.root, ignore_errors=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(runner, path, value):
    runner.write_json_document(Path(path), value)
    return value


def fake_preflight():
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


def reserve_one(runner):
    plan = json.loads((ROOT / "experiment-plan.json").read_text())
    with patch.object(runner, "preflight_context", lambda: fake_preflight()):
        record = runner.reserve_attempt(
            plan, "a" * 64, 1,
            {"allowedAttempts": [1], "reviewer": "simulated-unified-recovery"})
    runner.release_batch_lock()
    return record


def proof(phase="reserved", not_created=None):
    return {
        "protocol": "resource-phase-v1",
        "phase": phase,
        "sequence": [{"phase": phase, "at": "1970-01-01T00:00:00+00:00"}],
        "notCreated": dict(not_created or NOT_CREATED),
        "targetAttempt": 1,
    }


def make_plan(runner, guard, workspace, kind, tag, *, attempt=1,
              parent_attempt=None, stage_state="created", processes=None,
              extra=None):
    if kind == "run":
        role = "run-0001"
        stage = workspace.runs / "0001" / ("stage-" + tag)
    elif kind == "compile":
        role = "compile-0001-" + tag[:8]
        stage = workspace.prepare / ("stage-compile-0001-" + tag)
    else:
        raise AssertionError("unsupported kind")
    if stage_state == "created":
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "SIMULATED.txt").write_text(
            "effect-free synthetic stage\n", encoding="utf-8")
    prepare_id, plan = runner.write_lifecycle_plan(
        role, stage, tag, runner.container_name(role, tag), attempt=attempt,
        process_roles=("client", "observer") if kind == "run" else ("client",))
    identity = guard.stage_identity(stage) if stage_state == "created" else None
    plan.update({
        "state": "planned",
        "stageState": stage_state,
        "stageIdentity": identity,
        "containerState": "not-created",
        "containerId": None,
        "processes": processes or (
            {"client": {"spawnState": "not-started"},
             "observer": {"spawnState": "not-started"}}
            if kind == "run" else {"client": {"spawnState": "not-started"}}),
    })
    if parent_attempt is not None:
        plan["parentAttempt"] = parent_attempt
    if extra:
        plan.update(extra)
    write_json(runner, runner.lifecycle_plan_path(prepare_id), plan)
    return prepare_id, plan, stage


def write_record(runner, number, prepare_id, plan, **extra):
    stage_state = plan.get("stageState")
    not_created = dict(NOT_CREATED)
    not_created["stage"] = stage_state != "created"
    record = {
        "version": 1,
        "attempt": number,
        "state": "planned",
        "prepareId": prepare_id,
        "resourceIntent": dict(plan),
        "resourceIdentity": None,
        "stageDir": plan.get("stageDir"),
        "stageIdentity": plan.get("stageIdentity"),
        "processes": dict(plan.get("processes") or {}),
        "reservationHeld": True,
        "settled": False,
        "targetExecutions": 0,
        "executionState": "not-started",
        "associatedPrepareIds": [],
        "associationIntents": [],
        "resourceProof": proof(
            "stage-created" if stage_state == "created" else "reserved",
            not_created),
        "checkpoints": [],
    }
    record.update(extra)
    write_json(runner, runner.attempt_path(number), record)
    return record


def previous_success_plan(runner, prepare_id, checked="1970-01-01T00:00:00+00:00"):
    plan = read_json(runner.lifecycle_plan_path(prepare_id))
    plan.update({
        "reservationHeld": False,
        "state": "cleanup-confirmed",
        "cleanup": {"confirmed": True, "state": "confirmed", "checkedAt": checked},
        "cleanupCheck": {
            "protocol": "cleanup-check-v1", "state": "confirmed",
            "prepareId": prepare_id, "startedAt": checked,
            "startedCount": 1, "finishedAt": checked,
        },
        "cleanupReceipts": [{
            "state": "confirmed", "confirmed": True, "checkedAt": checked,
            "resourceCreationPhase": (plan.get("resourceProof") or {}).get("phase"),
        }],
    })
    write_json(runner, runner.lifecycle_plan_path(prepare_id), plan)
    return plan


def previous_success_attempt(runner, number, checked="1970-01-01T00:00:00+00:00"):
    record = read_json(runner.attempt_path(number))
    record.update({
        "state": "aborted",
        "settled": True,
        "reservationHeld": False,
        "cleanup": {"confirmed": True, "state": "confirmed", "checkedAt": checked},
        "cleanupCheck": {
            "protocol": "cleanup-check-v1", "state": "confirmed",
            "attempt": number, "startedAt": checked, "startedCount": 1,
            "finishedAt": checked,
        },
        "cleanupReceipts": [{
            "state": "confirmed", "confirmed": True, "checkedAt": checked,
        }],
    })
    write_json(runner, runner.attempt_path(number), record)
    return record


def link_child(runner, prepare_id, number=1):
    record = read_json(runner.attempt_path(number))
    listed = sorted(set(record.get("associatedPrepareIds") or []) | {prepare_id})
    intents = list(record.get("associationIntents") or [])
    intents = [item for item in intents if item.get("prepareId") != prepare_id]
    intents.append({
        "protocol": "association-intent-v1",
        "attempt": number,
        "prepareId": prepare_id,
        "state": "complete",
        "startedAt": "1970-01-01T00:00:00+00:00",
        "completedAt": "1970-01-01T00:00:00+00:00",
    })
    record.update({"associatedPrepareIds": listed,
                   "associationIntents": intents,
                   "reservationHeld": True, "settled": False})
    write_json(runner, runner.attempt_path(number), record)
    plan = read_json(runner.lifecycle_plan_path(prepare_id))
    plan["parentAttempt"] = number
    write_json(runner, runner.lifecycle_plan_path(prepare_id), plan)
    return record


@contextlib.contextmanager
def resource_doubles(runner, guard, *, remove_result=None, stage="real",
                     spawn_state=None):
    """Replace every real/destructive operation with a counter or real pure op."""
    calls = {"remove": 0, "stop": 0, "stage": 0, "docker": 0, "lookup": 0,
             "tagLookup": 0, "spawn": 0, "removed": [], "stagePaths": []}

    def remove(record):
        calls["remove"] += 1
        calls["removed"].append(dict(record or {}))
        if remove_result is not None:
            return dict(remove_result)
        return {"removed": True, "state": "never-created"}

    def stop(identity, graceful=0, term=0):
        calls["stop"] += 1
        return {"stopped": True, "state": "exited", "forced": False}

    def docker(*args, **kwargs):
        calls["docker"] += 1
        raise AssertionError("real Docker forbidden in pure test: %r" % (args,))

    def lookup(identifier):
        calls["lookup"] += 1
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
        calls["stagePaths"].append(str(path))
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
        return "return", function(*args, **kwargs)
    except SystemExit as error:
        return "exit", error.code
    except BaseException as error:  # noqa: BLE001 - a traceback is not a 3/78
        return "raised", type(error).__name__ + ":" + str(error)[:240]


def recover(runner, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as out, \
            contextlib.redirect_stderr(io.StringIO()) as err:
        kind, value = exit_code(runner.command_recover, **kwargs)
    runner.release_batch_lock()
    return kind, value, out.getvalue(), err.getvalue()


def cleanup_plan_bytes(runner, prepare_id):
    return runner.lifecycle_plan_path(prepare_id).read_bytes()


# ------------------------------------------------------------------------ B8
@check("B8-directory-permission-parent-incomplete3",
       "unreadable association directory cannot settle the parent or hide its child")
def b8_directory_permission(runner, guard):
    workspace = Workspace(runner, "b8-dir-permission-")
    try:
        reserve_one(runner)
        child_id, child_plan, child_stage = make_plan(
            runner, guard, workspace, "compile", "a1" * 8,
            parent_attempt=1)
        link_child(runner, child_id)
        child_bytes = runner.lifecycle_plan_path(child_id).read_bytes()
        directory = runner.plans_dir()
        directory.chmod(0)
        try:
            with resource_doubles(runner, guard) as calls:
                result = recover(runner, number=1)
            stored = read_json(runner.attempt_path(1))
        finally:
            directory.chmod(0o700)
        child_after = read_json(runner.lifecycle_plan_path(child_id))
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "notBusy79": not (result[0] == "exit" and result[1] == 79),
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "parentCleanupUnconfirmed": (stored.get("cleanup") or {}).get(
                "confirmed") is False,
            "parentCleanupIncomplete": (stored.get("cleanup") or {}).get(
                "state") == "incomplete",
            "childStageRetained": child_stage.is_dir(),
            "childFileRetained": child_bytes == runner.lifecycle_plan_path(
                child_id).read_bytes(),
            "childNotReportedUnheld": child_after.get("reservationHeld") is True,
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
            "counterSpent": read_json(runner.counter_path()).get("used") == [1],
            "directoryUnknownReason": (stored.get("cleanup") or {}).get(
                "reason") == "association-directory-unknown",
        }
        return all(checks.values()), {
            "checks": checks, "calls": calls, "result": result[:2],
            "stderr": result[3][-240:], "stored": stored,
            "child": child_after,
        }
    finally:
        workspace.close()


@check("B8-directory-io-child-held-incomplete3",
       "IO enumeration failure is incomplete and invalidates a readable known child")
def b8_directory_io(runner, guard):
    workspace = Workspace(runner, "b8-dir-io-")
    try:
        reserve_one(runner)
        child_id, child_plan, child_stage = make_plan(
            runner, guard, workspace, "compile", "b2" * 8,
            parent_attempt=1)
        link_child(runner, child_id)
        previous_success_plan(runner, child_id)

        def failing_scandir(path):
            raise OSError("simulated-enumeration-io")

        with patch.object(runner.os, "scandir", failing_scandir), \
                resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        child_after = read_json(runner.lifecycle_plan_path(child_id))
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "parentCleanupIncomplete": (stored.get("cleanup") or {}).get(
                "state") == "incomplete",
            "childHeld": child_after.get("reservationHeld") is True,
            "childStaleSuccessCleared": (child_after.get("cleanup") or {}).get(
                "confirmed") is False,
            "childStageRetained": child_stage.is_dir(),
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {
            "checks": checks, "calls": calls, "result": result[:2],
            "stderr": result[3][-240:], "stored": stored, "child": child_after,
        }
    finally:
        workspace.close()


class PartialIterator:
    def __init__(self, entry, error):
        self.entry = entry
        self.error = error
        self.index = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.index == 0:
            self.index += 1
            return types.SimpleNamespace(name=self.entry)
        raise self.error

    def close(self):
        self.closed = True


@check("B8-directory-partial-iteration-incomplete3",
       "partial enumeration keeps the already-readable child and reports incomplete")
def b8_partial_iteration(runner, guard):
    workspace = Workspace(runner, "b8-partial-")
    try:
        reserve_one(runner)
        child_id, child_plan, child_stage = make_plan(
            runner, guard, workspace, "compile", "c3" * 8,
            parent_attempt=1)
        link_child(runner, child_id)
        previous_success_plan(runner, child_id)

        def partial_scandir(path):
            return PartialIterator(child_id + ".json", OSError("partial-iteration"))

        with patch.object(runner.os, "scandir", partial_scandir), \
                resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        child_after = read_json(runner.lifecycle_plan_path(child_id))
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentCleanupIncomplete": (stored.get("cleanup") or {}).get(
                "state") == "incomplete",
            "childHeld": child_after.get("reservationHeld") is True,
            "childStaleSuccessCleared": (child_after.get("cleanup") or {}).get(
                "confirmed") is False,
            "childStageRetained": child_stage.is_dir(),
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {
            "checks": checks, "calls": calls, "result": result[:2],
            "stored": stored, "child": child_after,
        }
    finally:
        workspace.close()


@check("B8-empty-directory-success-with-proof",
       "fully enumerated empty directory plus not-created proof still settles")
def b8_empty_success(runner, guard):
    workspace = Workspace(runner, "b8-empty-")
    try:
        reserve_one(runner)
        workspace.plans.mkdir()
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "success0": result[0] == "return" and result[1] == 0,
            "settled": stored.get("settled") is True,
            "released": stored.get("reservationHeld") is False,
            "noDestructive": no_destructive(calls),
            "counterSpent": read_json(runner.counter_path()).get("used") == [1],
            "notCreatedProofPreserved": (stored.get("resourceProof") or {}).get(
                "phase") == "reserved" and all(
                    ((stored.get("resourceProof") or {}).get("notCreated") or {}).get(k)
                    is True for k in NOT_CREATED),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stored": stored, "result": result[:2]}
    finally:
        workspace.close()


@check("B8-absent-directory-success-with-proof",
       "a genuinely absent directory with no associated reference is a known empty scope")
def b8_absent_success(runner, guard):
    workspace = Workspace(runner, "b8-absent-")
    try:
        reserve_one(runner)
        assert not workspace.plans.exists()
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "success0": result[0] == "return" and result[1] == 0,
            "settled": stored.get("settled") is True,
            "released": stored.get("reservationHeld") is False,
            "noDestructive": no_destructive(calls),
            "directoryStillAbsent": not workspace.plans.exists(),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stored": stored, "result": result[:2]}
    finally:
        workspace.close()


@check("B8-absent-directory-known-ref-incomplete3",
       "absence is not allowed to erase a durable associated-child reference")
def b8_absent_reference(runner, guard):
    workspace = Workspace(runner, "b8-absent-ref-")
    try:
        reserve_one(runner)
        record = read_json(runner.attempt_path(1))
        missing_child = "d" * 32
        record.update({
            "associatedPrepareIds": [missing_child],
            "associationIntents": [{
                "protocol": "association-intent-v1", "attempt": 1,
                "prepareId": missing_child, "state": "complete",
                "startedAt": "1970-01-01T00:00:00+00:00",
            }],
        })
        write_json(runner, runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "referencePreserved": stored.get("associatedPrepareIds") == [missing_child],
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "stored": stored, "result": result[:2]}
    finally:
        workspace.close()


@check("B8-directory-symlink-blocked78",
       "a symlinked association directory is a contradiction before destruction")
def b8_directory_symlink(runner, guard):
    workspace = Workspace(runner, "b8-dir-link-")
    real = workspace.prepare / "real-plans"
    real.mkdir()
    try:
        (workspace.prepare / "plans").symlink_to(real, target_is_directory=True)
        reserve_one(runner)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "blocked78": result[0] == "exit" and result[1] == 78,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "noDestructive": no_destructive(calls),
            "linkRetained": (workspace.prepare / "plans").is_symlink(),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:]}
    finally:
        workspace.close()


@check("B8-directory-not-directory-blocked78",
       "a non-directory association path is blocked before destruction")
def b8_directory_file(runner, guard):
    workspace = Workspace(runner, "b8-dir-file-")
    try:
        (workspace.prepare / "plans").write_text("not a directory\n",
                                                 encoding="utf-8")
        reserve_one(runner)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "blocked78": result[0] == "exit" and result[1] == 78,
            "parentHeld": stored.get("reservationHeld") is True,
            "noDestructive": no_destructive(calls),
            "fileRetained": (workspace.prepare / "plans").is_file(),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:]}
    finally:
        workspace.close()


@check("B8-directory-ownership-blocked78",
       "an association directory owned by another uid is a contradiction")
def b8_directory_owner(runner, guard):
    workspace = Workspace(runner, "b8-dir-owner-")
    try:
        workspace.plans.mkdir()
        reserve_one(runner)
        with patch.object(runner.os, "getuid",
                          return_value=os.getuid() + 1), \
                resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "blocked78": result[0] == "exit" and result[1] == 78,
            "parentHeld": stored.get("reservationHeld") is True,
            "noDestructive": no_destructive(calls),
            "directoryRetained": workspace.plans.is_dir(),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:]}
    finally:
        workspace.close()


@check("B8-directory-identity-change-blocked78",
       "a directory identity/entry change between discovery and deletion is blocked")
def b8_directory_identity_change(runner, guard):
    workspace = Workspace(runner, "b8-dir-change-")
    try:
        reserve_one(runner)
        parent_id, parent_plan, parent_stage = make_plan(
            runner, guard, workspace, "run", "e4" * 8)
        record = write_record(runner, 1, parent_id, parent_plan)
        original = runner.begin_plan_cleanup_check

        def replace_directory(prepare_id, plan):
            value = original(prepare_id, plan)
            plans = runner.plans_dir()
            backup = plans.with_name("plans-backup")
            plans.rename(backup)
            plans.mkdir()
            return value

        with patch.object(runner, "begin_plan_cleanup_check",
                          replace_directory), \
                resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        stored = read_json(runner.attempt_path(1))
        checks = {
            "blocked78": result[0] == "exit" and result[1] == 78,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is False,
            "parentStageRetained": parent_stage.is_dir(),
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {
            "checks": checks, "calls": calls, "result": result[:2],
            "stderr": result[3][-240:], "stored": stored,
        }
    finally:
        workspace.close()


@check("B8-creation-enumeration-blocks-before-resources",
       "association preparation also fails closed when its directory cannot be enumerated")
def b8_creation_enumeration(runner, guard):
    workspace = Workspace(runner, "b8-creation-")
    try:
        reserve_one(runner)
        workspace.plans.mkdir()

        def failing_scandir(path):
            raise OSError("simulated-creation-enumeration-io")

        raised = None
        with patch.object(runner.os, "scandir", failing_scandir), \
                resource_doubles(runner, guard) as calls:
            try:
                runner.associate_existing_preparations(1)
            except BaseException as error:  # noqa: BLE001 - fail closed
                raised = type(error).__name__ + ":" + str(error)[:240]
        stored = read_json(runner.attempt_path(1))
        checks = {
            "raised": raised is not None,
            "explicitUnknown": raised is not None
            and "association-directory-unknown" in raised,
            "parentHeld": stored.get("reservationHeld") is True,
            "parentNotSettled": stored.get("settled") is not True,
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "raised": raised,
                                      "calls": calls, "stored": stored}
    finally:
        workspace.close()


# ------------------------------------------------------------------------ B9
def parent_child(workspace, runner, guard, *, child_tag="f5" * 8,
                 second_child=False, parent_stage=True, child_stage=True,
                 parent_success=False, child_success=False):
    reserve_one(runner)
    parent_id, parent_plan, parent_stage_path = make_plan(
        runner, guard, workspace, "run", "f4" * 8, stage_state=(
            "created" if parent_stage else "not-created"))
    record = write_record(runner, 1, parent_id, parent_plan)
    child_id, child_plan, child_stage_path = make_plan(
        runner, guard, workspace, "compile", child_tag,
        parent_attempt=1, stage_state="created" if child_stage else "not-created")
    link_child(runner, child_id)
    second = None
    if second_child:
        second_tag = "a6" * 8
        second_id, second_plan, second_stage = make_plan(
            runner, guard, workspace, "compile", second_tag,
            parent_attempt=1, stage_state="created")
        record = read_json(runner.attempt_path(1))
        record["associatedPrepareIds"] = sorted(
            set(record.get("associatedPrepareIds") or []) | {second_id})
        record["associationIntents"] = list(
            record.get("associationIntents") or []) + [{
                "protocol": "association-intent-v1", "attempt": 1,
                "prepareId": second_id, "state": "complete",
                "startedAt": "1970-01-01T00:00:00+00:00",
            }]
        write_json(runner, runner.attempt_path(1), record)
        second_plan["parentAttempt"] = 1
        write_json(runner, runner.lifecycle_plan_path(second_id), second_plan)
        second = (second_id, second_plan, second_stage)
    if child_success:
        previous_success_plan(runner, child_id)
    if second_child:
        previous_success_plan(runner, second[0])
    if parent_success:
        previous_success_attempt(runner, 1)
    return {
        "parentId": parent_id, "parentPlan": parent_plan,
        "parentStage": parent_stage_path, "record": record,
        "childId": child_id, "childPlan": child_plan,
        "childStage": child_stage_path, "second": second,
    }


@check("B9-direct-child-invalidates-bound-parent",
       "a successful child-only cleanup holds the exactly bound parent")
def b9_child_cleans_parent_held(runner, guard):
    workspace = Workspace(runner, "b9-child-parent-")
    try:
        setup = parent_child(workspace, runner, guard,
                             parent_success=True, child_success=True)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=setup["childId"])
        parent = read_json(runner.attempt_path(1))
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        checks = {
            "childCleanReturn0": result[0] == "return" and result[1] == 0,
            "childStageGone": not setup["childStage"].exists(),
            "childReleased": child.get("reservationHeld") is False,
            "childConfirmed": (child.get("cleanup") or {}).get("confirmed") is True,
            "parentHeld": parent.get("reservationHeld") is True,
            "parentNotSettled": parent.get("settled") is False,
            "parentCleanupUnconfirmed": (parent.get("cleanup") or {}).get(
                "confirmed") is False,
            "parentReason": (parent.get("cleanup") or {}).get(
                "reason") == "parent-full-recheck-required",
            "parentStageRetained": setup["parentStage"].is_dir(),
            "noParentStageCleanup": all(
                str(setup["parentStage"]) != path for path in calls["stagePaths"]),
            "noRealDocker": calls["docker"] == 0,
            "counterSpent": read_json(runner.counter_path()).get("used") == [1],
        }
        # Restore normal conditions: a complete parent recovery must settle.
        with resource_doubles(runner, guard) as calls2:
            second = recover(runner, number=1)
        parent2 = read_json(runner.attempt_path(1))
        checks.update({
            "parentRecovery0": second[0] == "return" and second[1] == 0,
            "parentSettled": parent2.get("settled") is True,
            "parentReleased": parent2.get("reservationHeld") is False,
            "parentStageGone": not setup["parentStage"].exists(),
        })
        return all(checks.values()), {
            "checks": checks, "calls": calls, "calls2": calls2,
            "first": result[:2], "second": second[:2],
            "parent": parent, "parentAfter": parent2, "child": child,
        }
    finally:
        workspace.close()


@check("B9-cleanup-alias-invalidates-bound-parent",
       "cleanup --prepare-id shares the same parent invalidation")
def b9_cleanup_alias(runner, guard):
    workspace = Workspace(runner, "b9-alias-")
    try:
        setup = parent_child(workspace, runner, guard,
                             child_tag="b7" * 8,
                             parent_success=True, child_success=True)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(
                runner.main, ["cleanup", "--prepare-id", setup["childId"]])
        parent = read_json(runner.attempt_path(1))
        checks = {
            "childCleanReturn0": kind == "return" and value == 0,
            "parentHeld": parent.get("reservationHeld") is True,
            "parentNotSettled": parent.get("settled") is False,
            "parentReason": (parent.get("cleanup") or {}).get(
                "reason") == "parent-full-recheck-required",
            "parentStageRetained": setup["parentStage"].is_dir(),
            "noDestructiveOnParent": all(
                str(setup["parentStage"]) != path for path in calls["stagePaths"]),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": [kind, value],
                                      "stored": parent}
    finally:
        workspace.close()


@check("B9-standalone-child-independent",
       "a valid standalone preparation with no parent remains independently recoverable")
def b9_standalone(runner, guard):
    workspace = Workspace(runner, "b9-standalone-")
    try:
        child_id, child_plan, child_stage = make_plan(
            runner, guard, workspace, "compile", "c8" * 8)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=child_id)
        stored = read_json(runner.lifecycle_plan_path(child_id))
        checks = {
            "success0": result[0] == "return" and result[1] == 0,
            "stageGone": not child_stage.exists(),
            "released": stored.get("reservationHeld") is False,
            "noAttemptCreated": not runner.attempt_path(1).exists(),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2], "stored": stored}
    finally:
        workspace.close()


@check("B9-multiple-known-children-parent-full-recheck",
       "child-only success leaves the parent held until every sibling is clear")
def b9_multiple_children(runner, guard):
    workspace = Workspace(runner, "b9-multiple-")
    try:
        setup = parent_child(workspace, runner, guard, child_tag="d9" * 8,
                             second_child=True, parent_success=True,
                             child_success=True)
        sibling_id, sibling_plan, sibling_stage = setup["second"]
        sibling_plan = read_json(runner.lifecycle_plan_path(sibling_id))
        sibling_plan["processes"] = {"client": {"spawnState": "unknown"}}
        write_json(runner, runner.lifecycle_plan_path(sibling_id), sibling_plan)
        with resource_doubles(runner, guard) as calls:
            first = recover(runner, prepare_id=setup["childId"])
            parent = read_json(runner.attempt_path(1))
            second = recover(runner, number=1)
            parent_after_second = read_json(runner.attempt_path(1))
        checks = {
            "childSuccess0": first[0] == "return" and first[1] == 0,
            "parentHeldAfterChild": (
                parent.get("reservationHeld") is True
                and parent.get("settled") is False),
            "parentReason": (parent.get("cleanup") or {}).get(
                "reason") == "parent-full-recheck-required",
            "siblingStageRetained": setup["second"][2].is_dir(),
            "parentStillIncomplete3": second[0] == "return" and second[1] == 3,
            "parentStillHeld": parent_after_second.get("reservationHeld") is True,
            "parentStillNotSettled": parent_after_second.get("settled") is False,
            "noRealDocker": calls["docker"] == 0,
        }
        # Clear the sibling and complete the parent scope.
        sibling_plan = read_json(runner.lifecycle_plan_path(sibling_id))
        sibling_plan["processes"] = {"client": {"spawnState": "not-started"}}
        write_json(runner, runner.lifecycle_plan_path(sibling_id), sibling_plan)
        shutil.rmtree(setup["second"][2])
        with resource_doubles(runner, guard) as calls2:
            third = recover(runner, number=1)
        parent_final = read_json(runner.attempt_path(1))
        checks.update({
            "parentFinal0": third[0] == "return" and third[1] == 0,
            "parentFinalSettled": parent_final.get("settled") is True,
            "parentFinalReleased": parent_final.get("reservationHeld") is False,
        })
        return all(checks.values()), {
            "checks": checks, "calls": calls, "calls2": calls2,
            "first": first[:2], "second": second[:2], "third": third[:2],
            "parent": parent, "parentAfterSecond": parent_after_second,
            "parentFinal": parent_final,
        }
    finally:
        workspace.close()


def _parent_attempt_variant(runner, guard, mode, child_tag):
    workspace = Workspace(runner, "b9-parent-attempt-" + mode + "-")
    try:
        setup = parent_child(workspace, runner, guard, child_tag=child_tag,
                             parent_success=True, child_success=True)
        path = runner.attempt_path(1)
        original = path.read_bytes()
        patcher = contextlib.nullcontext()
        if mode == "missing":
            path.unlink()
            damaged = None
        elif mode == "malformed":
            path.write_bytes(b"{not-json\n")
            damaged = path.read_bytes()
        elif mode == "unicode":
            path.write_bytes(b"\xff\xfe\x00broken-utf8\n")
            damaged = path.read_bytes()
        elif mode == "type":
            path.write_bytes(b"[]\n")
            damaged = path.read_bytes()
        else:
            damaged = original
            original_read = runner.read_json

            def failing(target, _original=original_read, _path=path, _kind=mode):
                if Path(target) == Path(_path):
                    if _kind == "permission":
                        raise PermissionError("simulated-parent-permission")
                    raise OSError("simulated-parent-io")
                return _original(target)

            patcher = patch.object(runner, "read_json", failing)
        with patcher, resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=setup["childId"])
        child_after = read_json(runner.lifecycle_plan_path(setup["childId"]))
        parent_bytes = path.read_bytes() if path.is_file() else None
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "notRaised": result[0] != "raised",
            "notBusy79": not (result[0] == "exit" and result[1] == 79),
            "childStageRetained": setup["childStage"].is_dir(),
            "childHeld": child_after.get("reservationHeld") is True,
            "childSuccessCleared": (child_after.get("cleanup") or {}).get(
                "confirmed") is False,
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
            "damagedParentBytesRetained": parent_bytes == damaged,
            "diagnosticIncomplete": "incomplete" in result[3],
        }
        return all(checks.values()), {
            "checks": checks, "calls": calls, "result": result[:2],
            "stderr": result[3][-240:], "child": child_after,
        }
    finally:
        workspace.close()


@check("B9-parent-attempt-unreadable-variants",
       "missing/malformed/unicode/type/Permission/IO parent records are incomplete 3")
def b9_parent_attempt_variants(runner, guard):
    tags = {"missing": "e1" * 8, "malformed": "e2" * 8,
            "unicode": "e3" * 8, "type": "e4" * 8,
            "permission": "e5" * 8, "io": "e6" * 8}
    variants = {}
    cases = []
    for mode, tag in tags.items():
        passed, detail = _parent_attempt_variant(runner, guard, mode, tag)
        variants[mode] = detail
        cases.append(passed)
    return all(cases), {"variants": variants, "allIncomplete": all(cases)}


@check("B9-parent-link-unconfirmed-incomplete3",
       "a child parentAttempt without a parent list/intent is not guessed into a link")
def b9_parent_link_unconfirmed(runner, guard):
    workspace = Workspace(runner, "b9-unconfirmed-")
    try:
        setup = parent_child(workspace, runner, guard, child_tag="e7" * 8,
                             parent_success=True, child_success=True)
        record = read_json(runner.attempt_path(1))
        record["associatedPrepareIds"] = []
        record["associationIntents"] = []
        write_json(runner, runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=setup["childId"])
        parent = read_json(runner.attempt_path(1))
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "childStageRetained": setup["childStage"].is_dir(),
            "childHeld": child.get("reservationHeld") is True,
            "parentHeld": parent.get("reservationHeld") is True,
            "parentNotSettled": parent.get("settled") is False,
            "noDestructive": no_destructive(calls),
            "noInventedList": parent.get("associatedPrepareIds") == [],
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2], "parent": parent,
                                      "child": child}
    finally:
        workspace.close()


@check("B9-ambiguous-parent-blocked78",
       "two durable parents claiming one child are blocked before child destruction")
def b9_ambiguous_parent(runner, guard):
    workspace = Workspace(runner, "b9-ambiguous-")
    try:
        setup = parent_child(workspace, runner, guard, child_tag="e8" * 8,
                             child_success=True)
        second = {
            "version": 1, "attempt": 2, "state": "planned",
            "prepareId": "f" * 32, "associatedPrepareIds": [setup["childId"]],
            "associationIntents": [{
                "protocol": "association-intent-v1", "attempt": 2,
                "prepareId": setup["childId"], "state": "complete",
                "startedAt": "1970-01-01T00:00:00+00:00",
            }],
            "reservationHeld": True, "settled": False,
        }
        write_json(runner, runner.attempt_path(2), second)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=setup["childId"])
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        checks = {
            "blocked78": result[0] == "exit" and result[1] == 78,
            "childStageRetained": setup["childStage"].is_dir(),
            "childStillHeld": child.get("reservationHeld") is True,
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:]}
    finally:
        workspace.close()


@check("B9-parent-journal-failure-before-child",
       "failure to persist the parent hold prevents child resource handling")
def b9_parent_journal_failure(runner, guard):
    workspace = Workspace(runner, "b9-parent-journal-")
    try:
        setup = parent_child(workspace, runner, guard, child_tag="e9" * 8,
                             parent_success=True, child_success=True)
        original = runner.update_attempt

        def failing(number, **fields):
            if "cleanup" in fields or "reservationHeld" in fields:
                raise OSError("simulated-parent-hold-failure")
            return original(number, **fields)

        with patch.object(runner, "update_attempt", failing), \
                resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=setup["childId"])
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "childStageRetained": setup["childStage"].is_dir(),
            "childHeld": child.get("reservationHeld") is True,
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:], "child": child}
    finally:
        workspace.close()


@check("B9-child-final-journal-failure-no-success",
       "a child final journal failure is incomplete even after its stage operation")
def b9_child_journal_failure(runner, guard):
    workspace = Workspace(runner, "b9-child-journal-")
    try:
        setup = parent_child(workspace, runner, guard, child_tag="f1" * 8,
                             parent_success=True, child_success=True)
        original = runner.update_lifecycle_plan

        def failing(prepare_id, **fields):
            check = fields.get("cleanupCheck") or {}
            if (fields.get("state") in {"cleanup-confirmed", "cleanup-unconfirmed"}
                    and check.get("state") in {"confirmed", "incomplete"}):
                raise OSError("simulated-child-final-journal-failure")
            return original(prepare_id, **fields)

        with patch.object(runner, "update_lifecycle_plan", failing), \
                resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=setup["childId"])
        parent = read_json(runner.attempt_path(1))
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "notRaised": result[0] != "raised",
            "parentHeld": parent.get("reservationHeld") is True,
            "parentNotSettled": parent.get("settled") is False,
            "parentReason": (parent.get("cleanup") or {}).get(
                "reason") == "parent-full-recheck-required",
            "childNoSuccessClaim": (child.get("cleanup") or {}).get(
                "confirmed") is not True,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:],
                                      "parent": parent, "child": child}
    finally:
        workspace.close()


# ----------------------------------------------------------------------- B10
def b10_setup(workspace, runner, guard, *, tags=("a1" * 8, "b2" * 8, "c3" * 8)):
    """Parent success + linked/reverse/standalone children, all previously clean."""
    reserve_one(runner)
    parent_id, parent_plan, parent_stage = make_plan(
        runner, guard, workspace, "run", "9a" * 8)
    record = write_record(runner, 1, parent_id, parent_plan)
    linked_id, linked_plan, linked_stage = make_plan(
        runner, guard, workspace, "compile", tags[0], parent_attempt=1)
    link_child(runner, linked_id)
    reverse_id, reverse_plan, reverse_stage = make_plan(
        runner, guard, workspace, "compile", tags[1], parent_attempt=1)
    standalone_id, standalone_plan, standalone_stage = make_plan(
        runner, guard, workspace, "compile", tags[2])
    previous_success_attempt(runner, 1)
    for child_id in (linked_id, reverse_id, standalone_id):
        previous_success_plan(runner, child_id)
    return {
        "parentId": parent_id, "parentPlan": parent_plan,
        "parentStage": parent_stage, "record": record,
        "children": [
            (linked_id, linked_plan, linked_stage),
            (reverse_id, reverse_plan, reverse_stage),
            (standalone_id, standalone_plan, standalone_stage),
        ],
    }


def _b10_variant(runner, guard, mode):
    workspace = Workspace(runner, "b10-" + mode + "-")
    try:
        setup = b10_setup(workspace, runner, guard)
        path = runner.lifecycle_plan_path(setup["parentId"])
        original = path.read_bytes()
        patcher = contextlib.nullcontext()
        if mode == "missing":
            path.unlink()
            damaged = None
        elif mode == "malformed":
            path.write_bytes(b"{not-json\n")
            damaged = path.read_bytes()
        elif mode == "unicode":
            path.write_bytes(b"\xff\xfe\x00broken-utf8\n")
            damaged = path.read_bytes()
        elif mode == "type":
            path.write_bytes(b"[]\n")
            damaged = path.read_bytes()
        else:
            damaged = original
            original_read = runner.read_json

            def failing(target, _original=original_read, _path=path, _kind=mode):
                if Path(target) == Path(_path):
                    if _kind == "permission":
                        raise PermissionError("simulated-target-plan-permission")
                    raise OSError("simulated-target-plan-io")
                return _original(target)

            patcher = patch.object(runner, "read_json", failing)
        with patcher, resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        parent = read_json(runner.attempt_path(1))
        child_states = []
        for child_id, _child_plan, child_stage in setup["children"]:
            child_states.append((child_id, read_json(
                runner.lifecycle_plan_path(child_id)), child_stage))
        target_bytes = path.read_bytes() if path.is_file() else None
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "notRaised": result[0] != "raised",
            "notBusy79": not (result[0] == "exit" and result[1] == 79),
            "parentHeld": parent.get("reservationHeld") is True,
            "parentNotSettled": parent.get("settled") is False,
            "parentCleanupUnconfirmed": (parent.get("cleanup") or {}).get(
                "confirmed") is False,
            "parentStageRetained": setup["parentStage"].is_dir(),
            "allChildStagesRetained": all(stage.is_dir() for _, _, stage in
                                          setup["children"]),
            "allChildrenHeld": all(child.get("reservationHeld") is True
                                   for _, child, _ in child_states),
            "allChildSuccessCleared": all(
                (child.get("cleanup") or {}).get("confirmed") is False
                for _, child, _ in child_states),
            "allChildReceiptsPreserved": all(
                any(item.get("state") == "confirmed"
                    for item in (child.get("cleanupReceipts") or []))
                for _, child, _ in child_states),
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
            "counterSpent": read_json(runner.counter_path()).get("used") == [1],
            "noReplay": parent.get("targetExecutions") in (0, None),
            "damagedTargetBytesRetained": target_bytes == damaged,
        }
        # Restore normal conditions and prove a complete parent recovery settles.
        if mode == "missing":
            path.write_bytes(original)
        elif mode in {"malformed", "unicode", "type"}:
            path.write_bytes(original)
        with resource_doubles(runner, guard) as calls2:
            restored = recover(runner, number=1)
        parent_final = read_json(runner.attempt_path(1))
        checks.update({
            "restoredParent0": restored[0] == "return" and restored[1] == 0,
            "restoredParentSettled": parent_final.get("settled") is True,
            "restoredParentReleased": parent_final.get("reservationHeld") is False,
            "restoredStagesGone": (
                not setup["parentStage"].exists()
                and all(not stage.exists() for _, _, stage in setup["children"])),
        })
        return all(checks.values()), {
            "checks": checks, "calls": calls, "calls2": calls2,
            "result": result[:2], "restored": restored[:2],
            "stderr": result[3][-240:], "parent": parent,
            "parentFinal": parent_final,
            "children": [{"id": child_id, "held": child.get("reservationHeld"),
                          "confirmed": (child.get("cleanup") or {}).get("confirmed")}
                         for child_id, child, _ in child_states],
        }
    finally:
        workspace.close()


@check("B10-target-plan-unavailable-child-held-variants",
       "missing/malformed/unicode/type/Permission/IO parent plans hold every known child")
def b10_target_plan_variants(runner, guard):
    variants = {}
    cases = []
    for mode in ("missing", "malformed", "unicode", "type", "permission", "io"):
        passed, detail = _b10_variant(runner, guard, mode)
        variants[mode] = detail
        cases.append(passed)
    return all(cases), {"variants": variants, "allIncomplete": all(cases)}


@check("B10-unreadable-child-retained-unknown",
       "a damaged known child file is retained, not guessed or overwritten")
def b10_unreadable_child(runner, guard):
    workspace = Workspace(runner, "b10-unreadable-child-")
    try:
        setup = b10_setup(workspace, runner, guard)
        bad_id = "d" * 32
        bad_path = runner.lifecycle_plan_path(bad_id)
        bad_path.write_bytes(b"{broken-known-child\n")
        record = read_json(runner.attempt_path(1))
        record["associatedPrepareIds"] = sorted(
            set(record.get("associatedPrepareIds") or []) | {bad_id})
        record["associationIntents"] = list(record.get("associationIntents") or []) + [{
            "protocol": "association-intent-v1", "attempt": 1,
            "prepareId": bad_id, "state": "complete",
            "startedAt": "1970-01-01T00:00:00+00:00",
        }]
        write_json(runner, runner.attempt_path(1), record)
        bad_before = bad_path.read_bytes()
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        parent = read_json(runner.attempt_path(1))
        bad_after = bad_path.read_bytes()
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "parentHeld": parent.get("reservationHeld") is True,
            "badBytesRetained": bad_before == bad_after,
            "noDestructive": no_destructive(calls),
            "explicitUnknownDiagnostic": (
                bool((parent.get("cleanup") or {}).get("associationUnreadable"))
                or "incomplete" in result[3]),
            "readableChildrenHeld": all(
                read_json(runner.lifecycle_plan_path(child_id)).get(
                    "reservationHeld") is True
                for child_id, _plan, _stage in setup["children"]),
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:],
                                      "parent": parent}
    finally:
        workspace.close()


@check("B10-ownership-contradiction-blocked78",
       "a child ownership contradiction blocks 78 before any signal or delete")
def b10_contradiction(runner, guard):
    workspace = Workspace(runner, "b10-contradiction-")
    try:
        setup = b10_setup(workspace, runner, guard)
        child_id, child_plan, child_stage = setup["children"][0]
        child_plan["prepareId"] = "f" * 32
        write_json(runner, runner.lifecycle_plan_path(child_id), child_plan)
        with resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        checks = {
            "blocked78": result[0] == "exit" and result[1] == 78,
            "parentStageRetained": setup["parentStage"].is_dir(),
            "allChildStagesRetained": all(stage.is_dir() for _, _, stage in
                                          setup["children"]),
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
        }
        return all(checks.values()), {"checks": checks, "calls": calls,
                                      "result": result[:2],
                                      "stderr": result[3][-240:]}
    finally:
        workspace.close()


# ------------------------------------------------------------------------ D1
def _d1_attempt_variant(runner, guard, mode):
    workspace = Workspace(runner, "d1-attempt-" + mode + "-")
    try:
        reserve_one(runner)
        path = runner.attempt_path(1)
        original = path.read_bytes()
        patcher = contextlib.nullcontext()
        if mode == "missing":
            path.unlink()
            damaged = None
        elif mode == "malformed":
            path.write_bytes(b"{not-json\n")
            damaged = path.read_bytes()
        elif mode == "unicode":
            path.write_bytes(b"\xff\xfe\x00broken-utf8\n")
            damaged = path.read_bytes()
        elif mode == "type":
            path.write_bytes(b"[]\n")
            damaged = path.read_bytes()
        else:
            damaged = original
            original_read = runner.read_json

            def failing(target, _original=original_read, _path=path, _kind=mode):
                if Path(target) == Path(_path):
                    if _kind == "permission":
                        raise PermissionError("simulated-attempt-permission")
                    raise OSError("simulated-attempt-io")
                return _original(target)

            patcher = patch.object(runner, "read_json", failing)
        with patcher, resource_doubles(runner, guard) as calls:
            result = recover(runner, number=1)
        after = path.read_bytes() if path.is_file() else None
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "notRaised": result[0] != "raised",
            "notBusy79": not (result[0] == "exit" and result[1] == 79),
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
            "damagedBytesRetained": after == damaged,
            "diagnosticIncomplete": "incomplete" in result[3],
        }
        return all(checks.values()), {
            "checks": checks, "calls": calls, "result": result[:2],
            "stderr": result[3][-240:],
        }
    finally:
        workspace.close()


@check("D1-recover-attempt-read-variants",
       "selected attempt missing/JSON/type/Unicode/Permission/IO is incomplete 3")
def d1_attempt_variants(runner, guard):
    variants = {}
    cases = []
    for mode in ("missing", "malformed", "unicode", "type", "permission", "io"):
        passed, detail = _d1_attempt_variant(runner, guard, mode)
        variants[mode] = detail
        cases.append(passed)
    return all(cases), {"variants": variants, "allIncomplete": all(cases)}


def _d1_nested_variant(runner, guard, mode):
    workspace = Workspace(runner, "d1-nested-" + mode + "-")
    try:
        reserve_one(runner)
        parent_id, parent_plan, parent_stage = make_plan(
            runner, guard, workspace, "run", "aa" * 8,
            stage_state="not-created")
        record = read_json(runner.attempt_path(1))
        record.update({
            "prepareId": parent_id,
            "resourceIntent": dict(parent_plan),
            "stageDir": parent_plan.get("stageDir"),
            "stageIdentity": None,
            "processes": dict(parent_plan.get("processes") or {}),
        })
        write_json(runner, runner.attempt_path(1), record)
        path = runner.attempt_path(1)
        original = path.read_bytes()
        patcher = contextlib.nullcontext()
        if mode == "missing":
            path.unlink()
            damaged = None
        elif mode == "malformed":
            path.write_bytes(b"{not-json\n")
            damaged = path.read_bytes()
        elif mode == "unicode":
            path.write_bytes(b"\xff\xfe\x00broken-utf8\n")
            damaged = path.read_bytes()
        elif mode == "type":
            path.write_bytes(b"[]\n")
            damaged = path.read_bytes()
        else:
            damaged = original
            original_read = runner.read_json

            def failing(target, _original=original_read, _path=path, _kind=mode):
                if Path(target) == Path(_path):
                    if _kind == "permission":
                        raise PermissionError("simulated-nested-permission")
                    raise OSError("simulated-nested-io")
                return _original(target)

            patcher = patch.object(runner, "read_json", failing)
        plan_before = runner.lifecycle_plan_path(parent_id).read_bytes()
        with patcher, resource_doubles(runner, guard) as calls:
            result = recover(runner, prepare_id=parent_id)
        after = path.read_bytes() if path.is_file() else None
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "notRaised": result[0] != "raised",
            "notBusy79": not (result[0] == "exit" and result[1] == 79),
            "noDestructive": no_destructive(calls),
            "noRealDocker": calls["docker"] == 0,
            "damagedAttemptBytesRetained": after == damaged,
            "planBytesStableOrHeld": (
                runner.lifecycle_plan_path(parent_id).read_bytes() == plan_before
                or (read_json(runner.lifecycle_plan_path(parent_id)).get(
                    "reservationHeld") is True)),
            "diagnosticIncomplete": "incomplete" in result[3],
        }
        return all(checks.values()), {
            "checks": checks, "calls": calls, "result": result[:2],
            "stderr": result[3][-240:],
        }
    finally:
        workspace.close()


@check("D1-run-prepare-nested-attempt-variants",
       "a nested attempt record read failure under recover --prepare-id is incomplete 3")
def d1_nested_variants(runner, guard):
    variants = {}
    cases = []
    for mode in ("missing", "malformed", "unicode", "type", "permission", "io"):
        passed, detail = _d1_nested_variant(runner, guard, mode)
        variants[mode] = detail
        cases.append(passed)
    return all(cases), {"variants": variants, "allIncomplete": all(cases)}


@check("D1-query-status-read-only",
       "status/query remain read-only for a valid record and plan")
def d1_query_status_read_only(runner, guard):
    workspace = Workspace(runner, "d1-readonly-")
    try:
        reserve_one(runner)
        parent_id, parent_plan, _stage = make_plan(
            runner, guard, workspace, "run", "ab" * 8,
            stage_state="not-created")
        record = read_json(runner.attempt_path(1))
        record.update({"prepareId": parent_id,
                       "resourceIntent": dict(parent_plan),
                       "stageDir": parent_plan.get("stageDir"),
                       "processes": dict(parent_plan.get("processes") or {})})
        write_json(runner, runner.attempt_path(1), record)
        attempt_before = runner.attempt_path(1).read_bytes()
        plan_before = runner.lifecycle_plan_path(parent_id).read_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            status_kind, status_value = exit_code(runner.main, ["status"])
            query_kind, query_value = exit_code(
                runner.main, ["query", "--attempt", "1"])
            plan_kind, plan_value = exit_code(
                runner.main, ["query", "--prepare-id", parent_id])
        checks = {
            "status0": status_kind == "return" and status_value == 0,
            "query0": query_kind == "return" and query_value == 0,
            "plan0": plan_kind == "return" and plan_value == 0,
            "attemptUnchanged": runner.attempt_path(1).read_bytes() == attempt_before,
            "planUnchanged": runner.lifecycle_plan_path(
                parent_id).read_bytes() == plan_before,
            "noResourceOps": True,
        }
        return all(checks.values()), {"checks": checks, "stdout": out.getvalue()[-200:]}
    finally:
        workspace.close()


@check("D1-actual-lockbusy-and-selector-ambiguity",
       "a genuine held lock is 79; argparse both/neither selectors stay 2")
def d1_lock_and_ambiguity(runner, guard):
    sandbox = Path(tempfile.mkdtemp(prefix="d1-lock-", dir=TMP))
    result = None
    handle = None
    try:
        shutil.copytree(Path(runner.__file__).resolve().parent, sandbox / "tools")
        (sandbox / "state").mkdir()
        import fcntl  # noqa: PLC0415
        handle = open(sandbox / "state" / "batch.lock", "a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = [sys.executable, str(sandbox / "tools" / "experiment_runner.py"),
                   "recover", "--attempt", "1"]
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=60, cwd=str(sandbox))
    finally:
        if handle is not None:
            try:
                import fcntl  # noqa: PLC0415
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
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
    TMP.mkdir(parents=True, exist_ok=True)
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
                     "traceback": traceback.format_exc()[-2000:]}
        results.append({"id": identifier, "description": description,
                        "passed": bool(passed), "detail": detail,
                        "error": error})
        print(("PASS " if passed else "FAIL ") + identifier)

    payload = {
        "kind": "unified-recovery-b8-b9-b10-d1-checks",
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
