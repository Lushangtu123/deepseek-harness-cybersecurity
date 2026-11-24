#!/usr/bin/env python3
"""B1-B4 recovery-close behavioural checks.

The same file is run against the frozen ``baseline/tools`` source (to record RED
desired-behaviour failures) and against the repaired ``tools`` source.  Every
resource operation is an effect-free double or a counting stub; no Docker,
bpftrace, signal, target or fixture is ever executed.  Assertions count actual
branches and operations, not source strings.
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


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_runner(tools):
    tools = Path(tools).resolve()
    name = "recovery_close_runner_" + sha_file(tools / "experiment_runner.py")[:12] + "_" + uuid.uuid4().hex[:6]
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

    def __init__(self, runner, prefix="recovery-close-"):
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


def write_plan(runner, prepare_id, plan):
    runner.write_json_document(runner.lifecycle_plan_path(prepare_id), plan)


def created_plan(runner, guard, role, stage, tag, attempt=None,
                 process_roles=("client",), extra=None):
    stage = Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    prepare_id, plan = runner.write_lifecycle_plan(
        role, stage, tag, runner.container_name(role, tag), attempt=attempt,
        process_roles=process_roles,
    )
    identity = guard.stage_identity(stage)
    plan.update({
        "state": "planned",
        "stageState": "created",
        "stageIdentity": identity,
        "containerState": "not-created",
        "containerId": None,
    })
    if extra:
        plan.update(extra)
    write_plan(runner, prepare_id, plan)
    return prepare_id, plan, identity


def target_record(runner, number, prepare_id, plan, **extra):
    stage = plan.get("stageDir")
    record = {
        "version": 1,
        "attempt": number,
        "state": "planned",
        "prepareId": prepare_id,
        "resourceIntent": dict(plan),
        "resourceIdentity": None,
        "stageDir": stage,
        "stageIdentity": plan.get("stageIdentity"),
        "processes": dict(plan.get("processes") or {}),
        "reservationHeld": True,
        "settled": False,
        "targetExecutions": 0,
        "executionState": "not-started",
        "checkpoints": [],
    }
    record.update(extra)
    runner.write_json_document(runner.attempt_path(number), record)
    return record


def exit_code(function, *args, **kwargs):
    try:
        value = function(*args, **kwargs)
        return "return", value
    except SystemExit as error:
        return "exit", error.code
    except BaseException as error:  # noqa: BLE001 - a traceback is not a 78
        return "raised", type(error).__name__ + ":" + str(error)[:160]


@contextlib.contextmanager
def resource_doubles(runner, guard, *, remove_result=None, stage="real",
                     process_state=None, docker_forbidden=True):
    """Replace every destructive/real resource operation with a counter."""
    calls = {"remove": 0, "stop": 0, "stage": 0, "docker": 0,
             "lookup": 0, "tagLookup": 0}

    def remove(record):
        calls["remove"] += 1
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
        return {"state": "absent"}

    def tag_lookup(tag):
        calls["tagLookup"] += 1
        return {"state": "absent"}

    def spawn(record):
        if process_state is not None:
            return process_state(record)
        if isinstance(record, dict) and record.get("spawnState") == "unknown":
            return {"state": "unknown", "detail": "synthetic-unknown"}
        return {"state": "exited", "proof": "not-started"}

    original_stage = runner.cleanup_stage

    def cleanup_stage(path, identity):
        calls["stage"] += 1
        if stage == "stub":
            return {"removed": True, "state": "removed"}
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
    layout = {"preflightId": "a" * 32, "runtime": {}}
    import structure  # noqa: PLC0415
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


# ------------------------------------------------------------------ B1 checks
@check("B1-selector-filename-plan-id", "recover --prepare-id B never operates plan A / copy B")
def b1_selector_binding(runner, guard):
    workspace = Workspace(runner, "b1-selector-")
    try:
        tag = "1" * 16
        stage = workspace.prepare / ("stage-bind-" + tag)
        prepare_id, plan, _identity = created_plan(
            runner, guard, "bind-" + tag[:8], stage, tag)
        requested = "f" * 32
        shutil.copyfile(runner.lifecycle_plan_path(prepare_id),
                        runner.lifecycle_plan_path(requested))
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=requested)
            runner.release_batch_lock()
        stored_requested = json.loads(runner.lifecycle_plan_path(requested).read_bytes())
        stored_owned = json.loads(runner.lifecycle_plan_path(prepare_id).read_bytes())
        detail = {"kind": kind, "value": value, "calls": calls,
                  "stageExists": stage.is_dir(),
                  "requestedReservationHeld": stored_requested.get("reservationHeld"),
                  "ownedReservationHeld": stored_owned.get("reservationHeld")}
        passed = (kind == "exit" and value == 78 and stage.is_dir()
                  and no_destructive(calls)
                  and stored_requested.get("reservationHeld") is True)
        return passed, detail
    finally:
        workspace.close()


@check("B1-query-update-selector-binding", "query/update use the same exact selector guard")
def b1_query_update_binding(runner, guard):
    workspace = Workspace(runner, "b1-query-")
    try:
        tag = "2" * 16
        stage = workspace.prepare / ("stage-bind-" + tag)
        prepare_id, plan, _identity = created_plan(
            runner, guard, "bind-" + tag[:8], stage, tag)
        requested = "e" * 32
        shutil.copyfile(runner.lifecycle_plan_path(prepare_id),
                        runner.lifecycle_plan_path(requested))
        record_before = runner.lifecycle_plan_path(requested).read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            query_kind, query_value = exit_code(runner.command_query, prepare_id=requested)
            runner.release_batch_lock()
            update_kind, update_value = exit_code(
                runner.update_lifecycle_plan, requested, state="tampered")
        record_after = runner.lifecycle_plan_path(requested).read_bytes()
        passed = (query_kind == "exit" and query_value == 78
                  and update_kind == "exit" and update_value == 78
                  and record_before == record_after)
        return passed, {"query": [query_kind, query_value],
                        "update": [update_kind, update_value],
                        "fileUnchanged": record_before == record_after}
    finally:
        workspace.close()


@check("B1-plan-id-immutable", "update fields cannot change prepareId")
def b1_plan_id_immutable(runner, guard):
    workspace = Workspace(runner, "b1-id-immutable-")
    try:
        tag = "3" * 16
        stage = workspace.prepare / ("stage-bind-" + tag)
        prepare_id, plan, _identity = created_plan(
            runner, guard, "bind-" + tag[:8], stage, tag)
        before = runner.lifecycle_plan_path(prepare_id).read_bytes()
        kind, value = exit_code(runner.update_lifecycle_plan, prepare_id,
                                prepareId="d" * 32)
        after = runner.lifecycle_plan_path(prepare_id).read_bytes()
        passed = kind == "exit" and value == 78 and before == after
        return passed, {"kind": kind, "value": value, "unchanged": before == after}
    finally:
        workspace.close()


@check("B1-stage-root-link-traversal-nul", "stage path roots/links/traversal/NUL rejected before deletion")
def b1_stage_paths(runner, guard):
    results = {}
    cases = []

    def mutate_case(name, mutate):
        workspace = Workspace(runner, "b1-path-" + name + "-")
        try:
            tag = "5" * 16
            stage = workspace.prepare / ("stage-bind-" + tag)
            prepare_id, plan, identity = created_plan(
                runner, guard, "bind-" + tag[:8], stage, tag)
            plan.update(mutate(stage, identity))
            write_plan(runner, prepare_id, plan)
            with resource_doubles(runner, guard) as calls:
                kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
                runner.release_batch_lock()
            results[name] = {"kind": kind, "value": value, "calls": calls,
                             "stageExists": stage.exists()}
            cases.append(kind == "exit" and value == 78 and no_destructive(calls)
                         and stage.exists())
        finally:
            workspace.close()

    # PREPARE root case needs the workspace itself.
    workspace = Workspace(runner, "b1-path-prepare-root-")
    try:
        tag = "6" * 16
        prepare_id, plan, _identity = created_plan(
            runner, guard, "bind-" + tag[:8], workspace.prepare / "ignored", tag)
        plan.update({"stageDir": str(workspace.prepare), "stageState": "created",
                     "stageIdentity": guard.stage_identity(workspace.prepare)})
        write_plan(runner, prepare_id, plan)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        results["prepare-root"] = {"kind": kind, "value": value, "calls": calls,
                                   "rootExists": workspace.prepare.is_dir()}
        cases.append(kind == "exit" and value == 78 and no_destructive(calls)
                     and workspace.prepare.is_dir())
    finally:
        workspace.close()

    workspace = Workspace(runner, "b1-path-runs-root-")
    try:
        tag = "7" * 16
        prepare_id, plan, _identity = created_plan(
            runner, guard, "bind-" + tag[:8], workspace.prepare / "ignored", tag)
        plan.update({"stageDir": str(workspace.runs), "stageState": "created",
                     "stageIdentity": guard.stage_identity(workspace.runs)})
        write_plan(runner, prepare_id, plan)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        results["runs-root"] = {"kind": kind, "value": value, "calls": calls,
                                "rootExists": workspace.runs.is_dir()}
        cases.append(kind == "exit" and value == 78 and no_destructive(calls)
                     and workspace.runs.is_dir())
    finally:
        workspace.close()

    mutate_case("nul", lambda stage, identity: {
        "stageDir": str(stage) + "\x00suffix", "stageState": "created",
        "stageIdentity": identity})
    mutate_case("traversal", lambda stage, identity: {
        "stageDir": str(stage.parent / ".." / ("escape-" + stage.name)),
        "stageState": "created", "stageIdentity": identity})
    mutate_case("role-path", lambda stage, identity: {
        "stageDir": str(stage.parent / ".." / "runs" / "0001" / ("stage-" + stage.name[-16:])),
        "stageState": "created", "stageIdentity": identity})
    # A symlink stage is rejected even though resolve() lands under PREPARE.
    workspace = Workspace(runner, "b1-path-link-")
    try:
        tag = "8" * 16
        real = workspace.prepare / ("stage-bind-" + tag)
        real.mkdir()
        link = workspace.prepare / "link-stage"
        link.symlink_to(real, target_is_directory=True)
        prepare_id, plan, _identity = created_plan(
            runner, guard, "bind-" + tag[:8], real, tag)
        plan.update({"stageDir": str(link), "stageState": "created",
                     "stageIdentity": guard.stage_identity(real)})
        write_plan(runner, prepare_id, plan)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        results["symlink"] = {"kind": kind, "value": value, "calls": calls,
                              "linkExists": link.is_symlink(), "realExists": real.is_dir()}
        cases.append(kind == "exit" and value == 78 and no_destructive(calls)
                     and link.is_symlink() and real.is_dir())
    finally:
        workspace.close()
    return all(cases), results


@check("B1-role-attempt-name-tag-image-path-identity", "plan identity contradictions rejected before resource calls")
def b1_identity_fields(runner, guard):
    results = {}
    cases = []

    def identity_case(name, mutate):
        workspace = Workspace(runner, "b1-ident-" + name + "-")
        try:
            tag = "9" * 16
            stage = workspace.runs / "0001" / ("stage-" + tag)
            prepare_id, plan, identity = created_plan(
                runner, guard, "run-0001", stage, tag, attempt=1,
                process_roles=("client", "observer"))
            plan.update(mutate(stage, identity, tag))
            write_plan(runner, prepare_id, plan)
            record = target_record(runner, 1, prepare_id, plan)
            with resource_doubles(runner, guard) as calls:
                kind, value = exit_code(runner.cleanup_attempt, record)
                runner.release_batch_lock()
            results[name] = {"kind": kind, "value": value, "calls": calls}
            cases.append(kind == "exit" and value == 78 and no_destructive(calls))
        finally:
            workspace.close()

    identity_case("internal-role", lambda stage, identity, tag: {
        "role": "compile-0001-" + tag[:8]})
    identity_case("attempt-role", lambda stage, identity, tag: {"attempt": 2})
    identity_case("name", lambda stage, identity, tag: {
        "containerName": "stdlib-cli-foreign-" + tag})
    identity_case("tag", lambda stage, identity, tag: {"tag": "a" * 16})
    identity_case("image", lambda stage, identity, tag: {"imageId": "sha256:" + "1" * 64})
    identity_case("stage-relation", lambda stage, identity, tag: {
        "stageDir": str(Path(stage).parents[1] / "prepare" / ("stage-bind-" + tag))})
    identity_case("stage-identity-malformed", lambda stage, identity, tag: {
        "stageIdentity": {"error": "lstat"}})
    return all(cases), results


# ------------------------------------------------------------------ B2 checks
def target_plan_for_b2(runner, guard, workspace, number=1, tag="a" * 16):
    stage = workspace.runs / ("%04d" % number) / ("stage-" + tag)
    prepare_id, plan, identity = created_plan(
        runner, guard, "run-%04d" % number, stage, tag, attempt=number,
        process_roles=("client", "observer"))
    record = target_record(runner, number, prepare_id, plan)
    return prepare_id, plan, identity, record


@check("B2-missing-plan-no-fallback", "missing plan keeps intent/files/reservation and never deletes via intent")
def b2_missing_plan(runner, guard):
    workspace = Workspace(runner, "b2-missing-")
    try:
        tag = "b" * 16
        stage = workspace.runs / "0001" / ("stage-" + tag)
        stage.mkdir(parents=True)
        intent = {
            "prepareId": "a" * 32,
            "role": "run-0001", "operationRole": "run-0001", "attempt": 1,
            "tag": tag, "containerName": runner.container_name("run-0001", tag),
            "imageId": runner.IMAGE, "stageDir": str(stage),
            "stageIdentity": guard.stage_identity(stage),
            "containerState": "created", "containerId": "1" * 64,
            "processes": {"client": {"spawnState": "not-started"},
                          "observer": {"spawnState": "not-started"}},
        }
        record = {
            "version": 1, "attempt": 1, "state": "planned",
            "prepareId": "a" * 32, "resourceIntent": intent,
            "stageDir": str(stage), "stageIdentity": intent["stageIdentity"],
            "containerId": "1" * 64, "containerCreated": True,
            "processes": intent["processes"], "reservationHeld": True,
            "settled": False, "checkpoints": [],
        }
        runner.write_json_document(runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            try:
                confirmed = runner.cleanup_attempt(record)
                raised = None
            except BaseException as error:  # noqa: BLE001
                confirmed = None
                raised = type(error).__name__ + ":" + str(error)[:120]
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cli_kind, cli_value = exit_code(runner.command_recover, number=1)
            runner.release_batch_lock()
        stored = json.loads(runner.attempt_path(1).read_bytes())
        passed = (raised is None and confirmed is False and no_destructive(calls)
                  and cli_kind == "return" and cli_value == 3
                  and stored.get("reservationHeld") is True
                  and stored.get("resourceIntent") == intent
                  and stage.is_dir())
        return passed, {"confirmed": confirmed, "raised": raised, "calls": calls,
                        "cli": [cli_kind, cli_value],
                        "reservationHeld": stored.get("reservationHeld"),
                        "intentPreserved": stored.get("resourceIntent") == intent,
                        "stageExists": stage.is_dir()}
    finally:
        workspace.close()


@check("B2-unreadable-io-json-invalid-no-fallback", "PermissionError/IO/JSON/shape plans are incomplete, never fallback")
def b2_unreadable_plans(runner, guard):
    results = {}
    cases = []
    variants = ("permission", "io", "json", "shape")

    for variant in variants:
        workspace = Workspace(runner, "b2-invalid-" + variant + "-")
        try:
            prepare_id, plan, _identity, record = target_plan_for_b2(
                runner, guard, workspace, tag=("c" if variant == "permission" else
                                               "d" if variant == "io" else
                                               "e" if variant == "json" else "f") * 16)
            plan_path = runner.lifecycle_plan_path(prepare_id)
            original_read = runner.read_json

            if variant in {"permission", "io"}:
                def failing(path, _original=original_read, _planned=plan_path,
                            _kind=variant):
                    if Path(path) == Path(_planned):
                        if _kind == "permission":
                            raise PermissionError("simulated-permission")
                        raise OSError("simulated-io")
                    return _original(path)
                patcher = patch.object(runner, "read_json", failing)
            elif variant == "json":
                plan_path.write_bytes(b"{not-json\n")
                patcher = contextlib.nullcontext()
            else:
                plan_path.write_bytes(b"[]\n")
                patcher = contextlib.nullcontext()
            with patcher, resource_doubles(runner, guard) as calls:
                try:
                    confirmed = runner.cleanup_attempt(record)
                    raised = None
                except BaseException as error:  # noqa: BLE001
                    confirmed = None
                    raised = type(error).__name__ + ":" + str(error)[:120]
            stored = json.loads(runner.attempt_path(1).read_bytes())
            results[variant] = {"confirmed": confirmed, "raised": raised,
                                "calls": calls,
                                "reservationHeld": stored.get("reservationHeld"),
                                "intentPreserved": stored.get("resourceIntent") == plan}
            cases.append(raised is None and confirmed is False and no_destructive(calls)
                         and stored.get("reservationHeld") is True
                         and stored.get("resourceIntent") == plan)
        finally:
            workspace.close()
    return all(cases), results


@check("B2-ownership-contradiction-blocked78", "invalid identity plan is 78 and never falls through to deletion")
def b2_identity_contradiction(runner, guard):
    results = {}
    cases = []
    mutations = (
        ("image", {"imageId": "sha256:" + "1" * 64}),
        ("unknown-role", {"operationRole": "mystery-role", "role": "mystery-role"}),
        ("selector", {"prepareId": "2" * 32}),
    )
    for name, mutation in mutations:
        workspace = Workspace(runner, "b2-contradiction-" + name + "-")
        try:
            tag = ("1" if name == "image" else "2" if name == "unknown-role" else "3") * 16
            prepare_id, plan, _identity, record = target_plan_for_b2(
                runner, guard, workspace, tag=tag)
            plan.update(mutation)
            write_plan(runner, prepare_id, plan)
            with resource_doubles(runner, guard) as calls:
                kind, value = exit_code(runner.cleanup_attempt, record)
            results[name] = {"kind": kind, "value": value, "calls": calls}
            cases.append(kind == "exit" and value == 78 and no_destructive(calls))
        finally:
            workspace.close()
    return all(cases), results


@check("B2-identity-journal-validated", "existing identity journals are read and bound before destruction")
def b2_identity_journal(runner, guard):
    results = {}
    cases = []
    variants = ("contradiction", "json", "symlink")
    for variant in variants:
        workspace = Workspace(runner, "b2-identity-" + variant + "-")
        try:
            tag = ("1" if variant == "contradiction" else
                   "2" if variant == "json" else "3") * 16
            prepare_id, plan, _identity, record = target_plan_for_b2(
                runner, guard, workspace, tag=tag)
            identity_path = runner.lifecycle_identity_path(prepare_id)
            if variant == "contradiction":
                identity_path.write_text(json.dumps({
                    "prepareId": prepare_id,
                    "containerId": "f" * 64,
                    "containerName": plan.get("containerName"),
                    "tag": plan.get("tag"),
                    "image": plan.get("imageId"),
                }, sort_keys=True) + "\n", encoding="utf-8")
            elif variant == "json":
                identity_path.write_bytes(b"{broken\n")
            else:
                target = workspace.prepare / "identity-target.json"
                target.write_text("{}\n", encoding="utf-8")
                identity_path.symlink_to(target)
            with resource_doubles(runner, guard) as calls:
                kind, value = exit_code(runner.cleanup_attempt, record)
                runner.release_batch_lock()
            stored = json.loads(runner.attempt_path(1).read_bytes())
            results[variant] = {"kind": kind, "value": value, "calls": calls,
                                "reservationHeld": stored.get("reservationHeld")}
            if variant == "contradiction":
                cases.append(kind == "exit" and value == 78 and no_destructive(calls))
            elif variant == "json":
                cases.append(kind == "return" and value is False
                             and no_destructive(calls)
                             and stored.get("reservationHeld") is True)
            else:
                cases.append(kind == "exit" and value == 78 and no_destructive(calls))
        finally:
            workspace.close()
    return all(cases), results


@check("B2-lockbusy-and-cli-ambiguity", "lock busy is 79 and argparse ambiguity stays 2")
def b2_lock_and_cli(runner, guard):
    import fcntl
    sandbox = Path(tempfile.mkdtemp(prefix="b2-cli-", dir=TMP))
    result = None
    handle = None
    try:
        shutil.copytree(Path(runner.__file__).resolve().parent, sandbox / "tools")
        (sandbox / "state").mkdir()
        lock_path = sandbox / "state" / "batch.lock"
        handle = open(lock_path, "a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = [sys.executable, str(sandbox / "tools" / "experiment_runner.py"),
                   "recover", "--attempt", "1"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                                cwd=str(sandbox))
    finally:
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        shutil.rmtree(sandbox, ignore_errors=True)
    with contextlib.redirect_stderr(io.StringIO()):
        both = exit_code(runner.main, ["query", "--attempt", "1",
                                       "--prepare-id", "a" * 32])
        neither = exit_code(runner.main, ["query"])
        both_cleanup = exit_code(runner.main, ["cleanup", "--attempt", "1",
                                               "--prepare-id", "a" * 32])
        neither_recover = exit_code(runner.main, ["recover"])
    passed = (result is not None and result.returncode == 79
              and "batch-locked" in result.stderr
              and all(kind == "exit" and value == 2 for kind, value in
                      (both, neither, both_cleanup, neither_recover)))
    return passed, {"subprocessReturn": None if result is None else result.returncode,
                    "subprocessTail": None if result is None else result.stderr[-80:],
                    "both": both, "neither": neither,
                    "bothCleanup": both_cleanup, "neitherRecover": neither_recover}


# ------------------------------------------------------------------ B3 checks
@check("B3-standalone-compile-recovery", "compile preparation recovers with no target attempt record")
def b3_standalone_compile(runner, guard):
    workspace = Workspace(runner, "b3-compile-")
    try:
        tag = "4" * 16
        stage = workspace.prepare / ("stage-compile-0001-" + tag)
        prepare_id, plan, _identity = created_plan(
            runner, guard, "compile-0001-" + tag[:8], stage, tag, attempt=1)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        stored = json.loads(runner.lifecycle_plan_path(prepare_id).read_bytes())
        passed = (kind == "return" and value == 0 and calls["remove"] <= 1
                  and not stage.exists()
                  and stored.get("reservationHeld") is False
                  and not runner.attempt_path(1).exists())
        return passed, {"kind": kind, "value": value, "calls": calls,
                        "stageExists": stage.exists(),
                        "reservationHeld": stored.get("reservationHeld"),
                        "attemptRecordCreated": runner.attempt_path(1).exists()}
    finally:
        workspace.close()


@check("B3-standalone-bind-recovery", "bind preparation recovers without a target record")
def b3_standalone_bind(runner, guard):
    workspace = Workspace(runner, "b3-bind-")
    try:
        tag = "5" * 16
        stage = workspace.prepare / ("stage-bind-" + tag)
        prepare_id, plan, _identity = created_plan(
            runner, guard, "bind-" + tag[:8], stage, tag)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        stored = json.loads(runner.lifecycle_plan_path(prepare_id).read_bytes())
        passed = (kind == "return" and value == 0 and not stage.exists()
                  and stored.get("reservationHeld") is False)
        return passed, {"kind": kind, "value": value, "calls": calls,
                        "stageExists": stage.exists(),
                        "reservationHeld": stored.get("reservationHeld")}
    finally:
        workspace.close()


@check("B3-associated-compile-not-target", "compile selector never routes into the parent target cleanup")
def b3_associated_compile(runner, guard):
    workspace = Workspace(runner, "b3-associated-")
    try:
        target_tag = "6" * 16
        target_stage = workspace.runs / "0001" / ("stage-" + target_tag)
        target_id, target_plan, target_identity = created_plan(
            runner, guard, "run-0001", target_stage, target_tag, attempt=1,
            process_roles=("client", "observer"))
        record = target_record(runner, 1, target_id, target_plan)
        compile_tag = "7" * 16
        compile_stage = workspace.prepare / ("stage-compile-0001-" + compile_tag)
        compile_id, compile_plan, _identity = created_plan(
            runner, guard, "compile-0001-" + compile_tag[:8], compile_stage,
            compile_tag, attempt=1)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=compile_id)
            runner.release_batch_lock()
        stored_record = json.loads(runner.attempt_path(1).read_bytes())
        compiled = json.loads(runner.lifecycle_plan_path(compile_id).read_bytes())
        passed = (kind == "return" and value == 0 and not compile_stage.exists()
                  and target_stage.is_dir()
                  and stored_record.get("reservationHeld") is True
                  and compiled.get("reservationHeld") is False)
        return passed, {"kind": kind, "value": value, "calls": calls,
                        "compileStageExists": compile_stage.exists(),
                        "targetStageExists": target_stage.is_dir(),
                        "targetReservationHeld": stored_record.get("reservationHeld"),
                        "compileReservationHeld": compiled.get("reservationHeld")}
    finally:
        workspace.close()


@check("B3-run-role-link-and-mismatch", "run role routes only with selector==plan==record and attempt match")
def b3_run_routing(runner, guard):
    results = {}
    cases = []
    # Correct run routing.
    workspace = Workspace(runner, "b3-run-ok-")
    try:
        tag = "8" * 16
        stage = workspace.runs / "0001" / ("stage-" + tag)
        prepare_id, plan, _identity, record = target_plan_for_b2(
            runner, guard, workspace, tag=tag)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        stored = json.loads(runner.attempt_path(1).read_bytes())
        results["correct"] = {"kind": kind, "value": value, "calls": calls,
                              "reservationHeld": stored.get("reservationHeld")}
        cases.append(kind == "return" and value == 0 and not stage.exists()
                     and stored.get("reservationHeld") is False)
    finally:
        workspace.close()
    # Record prepareId contradicts the plan/selector.
    workspace = Workspace(runner, "b3-run-mismatch-")
    try:
        tag = "9" * 16
        prepare_id, plan, _identity, record = target_plan_for_b2(
            runner, guard, workspace, tag=tag)
        record["prepareId"] = "3" * 32
        runner.write_json_document(runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        results["prepare-link-mismatch"] = {"kind": kind, "value": value, "calls": calls}
        cases.append(kind == "exit" and value == 78 and no_destructive(calls))
    finally:
        workspace.close()
    # Record attempt contradicts plan.attempt.
    workspace = Workspace(runner, "b3-run-attempt-")
    try:
        tag = "a" * 16
        prepare_id, plan, _identity, record = target_plan_for_b2(
            runner, guard, workspace, tag=tag)
        record["attempt"] = 2
        runner.write_json_document(runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        results["attempt-mismatch"] = {"kind": kind, "value": value, "calls": calls}
        cases.append(kind == "exit" and value == 78 and no_destructive(calls))
    finally:
        workspace.close()
    return all(cases), results


@check("B3-unknown-role-rejected", "unknown operation role is rejected before resource calls")
def b3_unknown_role(runner, guard):
    workspace = Workspace(runner, "b3-unknown-")
    try:
        tag = "b" * 16
        stage = workspace.prepare / ("stage-mystery-" + tag)
        prepare_id, plan, _identity = created_plan(
            runner, guard, "mystery-role", stage, tag)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.command_recover, prepare_id=prepare_id)
            runner.release_batch_lock()
        passed = kind == "exit" and value == 78 and no_destructive(calls) and stage.is_dir()
        return passed, {"kind": kind, "value": value, "calls": calls,
                        "stageExists": stage.is_dir()}
    finally:
        workspace.close()


# ------------------------------------------------------------------ B4 checks
def reserve_one(runner, guard, workspace, number=1):
    plan = json.loads((ROOT / "experiment-plan.json").read_text())
    with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)):
        record = runner.reserve_attempt(plan, "a" * 64, number,
                                        {"allowedAttempts": [number], "reviewer": "sim"})
    return record


@check("B4-reserve-not-created-proof", "reserve-only target settles reservation, keeps slot spent, never claims success")
def b4_reserve_proof(runner, guard):
    workspace = Workspace(runner, "b4-reserve-")
    try:
        with resource_doubles(runner, guard) as calls:
            record = reserve_one(runner, guard, workspace)
            runner.release_batch_lock()
            codes = []
            for _ in range(2):
                with contextlib.redirect_stdout(io.StringIO()):
                    kind, value = exit_code(runner.command_recover, number=1)
                    runner.release_batch_lock()
                    codes.append((kind, value))
            counter = json.loads(runner.counter_path().read_bytes())
            stored = json.loads(runner.attempt_path(1).read_bytes())
        proof = stored.get("resourceProof") or {}
        initial_proof = record.get("resourceProof") or {}
        not_created = proof.get("notCreated") or {}
        passed = (codes == [("return", 0), ("return", 0)]
                  and stored.get("reservationHeld") is False
                  and stored.get("settled") is True
                  and stored.get("state") != "completed"
                  and stored.get("targetExecutions") == 0
                  and counter.get("used") == [1]
                  and calls["docker"] == 0 and calls["remove"] == 0
                  and calls["stop"] == 0 and calls["stage"] == 0
                  and initial_proof.get("protocol") == "resource-phase-v1"
                  and initial_proof.get("phase") == "reserved"
                  and all(not_created.get(key) is True for key in
                          ("stage", "container", "client", "observer")))
        return passed, {"codes": codes, "calls": calls,
                        "state": stored.get("state"),
                        "reservationHeld": stored.get("reservationHeld"),
                        "settled": stored.get("settled"),
                        "targetExecutions": stored.get("targetExecutions"),
                        "counter": counter, "resourceProof": proof}
    finally:
        workspace.close()


@check("B4-pre-plan-reserve-failure", "reserve crash after counter write consumes slot and creates no resources")
def b4_preplan_failure(runner, guard):
    workspace = Workspace(runner, "b4-preplan-")
    try:
        plan = json.loads((ROOT / "experiment-plan.json").read_text())
        original_write = runner.write_json_document

        def failing(path, value):
            if Path(path).name == "attempt-0001.json":
                raise OSError("simulated-reserve-record-failure")
            return original_write(path, value)

        raised = None
        with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)), \
                patch.object(runner, "write_json_document", failing), \
                resource_doubles(runner, guard) as calls:
            try:
                runner.reserve_attempt(plan, "a" * 64, 1,
                                       {"allowedAttempts": [1], "reviewer": "sim"})
            except BaseException as error:  # noqa: BLE001
                raised = type(error).__name__ + ":" + str(error)[:100]
            runner.release_batch_lock()
        counter = json.loads(runner.counter_path().read_bytes())
        plans = list((workspace.prepare / "plans").glob("*.json")) if (
            workspace.prepare / "plans").is_dir() else []
        passed = (raised is not None and counter.get("used") == [1]
                  and not runner.attempt_path(1).exists() and plans == []
                  and calls["docker"] == 0 and calls["remove"] == 0
                  and calls["stop"] == 0 and calls["stage"] == 0)
        return passed, {"raised": raised, "counter": counter,
                        "attemptExists": runner.attempt_path(1).exists(),
                        "planCount": len(plans), "calls": calls}
    finally:
        workspace.close()


@check("B4-association-before-stage", "compile plan is durably linked to the parent before stage creation")
def b4_association_before_stage(runner, guard):
    workspace = Workspace(runner, "b4-assoc-")
    try:
        runner.ROOT = ROOT
        tag = "c" * 16
        record = {"version": 1, "attempt": 1, "state": "reserved",
                  "prepareId": None, "processes": {}, "reservationHeld": True,
                  "checkpoints": []}
        runner.write_json_document(runner.attempt_path(1), record)
        plan = json.loads((ROOT / "experiment-plan.json").read_text())
        challenge = "a" * 32
        captured = {}

        class StopProbe(Exception):
            pass

        def stop_stage(path):
            captured["stageAtStop"] = str(path)
            stored = json.loads(runner.attempt_path(1).read_bytes())
            captured["associated"] = list(stored.get("associatedPrepareIds") or [])
            plans = [json.loads(item.read_bytes()) for item in
                     (workspace.prepare / "plans").glob("*.json")]
            captured["plans"] = plans
            raise StopProbe()

        with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)), \
                patch.object(runner, "verify_prepare_inputs", lambda _r: fake_prepare_inputs(runner)), \
                patch.object(runner, "_safe_mkdir", stop_stage):
            try:
                runner.compile_attempt(plan, "a" * 64, 1, challenge)
            except StopProbe:
                pass
        associated = captured.get("associated") or []
        plans = captured.get("plans") or []
        linked = [value for value in plans
                  if value.get("prepareId") in associated
                  and value.get("parentAttempt") == 1]
        passed = (len(associated) == 1 and len(linked) == 1
                  and linked[0].get("operationRole", "").startswith("compile-")
                  and captured.get("stageAtStop", "").find("stage-compile-0001-") >= 0)
        return passed, {"associated": associated,
                        "linkedPlans": [value.get("prepareId") for value in linked],
                        "planRoles": [value.get("operationRole") for value in plans],
                        "stageAtStop": captured.get("stageAtStop")}
    finally:
        workspace.close()


@check("B4-association-failure-no-resources", "failure between plan creation and parent link creates no stage/process")
def b4_association_failure(runner, guard):
    workspace = Workspace(runner, "b4-assoc-fail-")
    try:
        runner.ROOT = ROOT
        record = {"version": 1, "attempt": 1, "state": "reserved",
                  "prepareId": None, "processes": {}, "reservationHeld": True,
                  "checkpoints": []}
        runner.write_json_document(runner.attempt_path(1), record)
        plan = json.loads((ROOT / "experiment-plan.json").read_text())
        original_update = runner.update_attempt
        tool_calls = {"runTool": 0}

        def failing_update(number, **fields):
            if "associatedPrepareIds" in fields:
                raise OSError("simulated-association-failure")
            return original_update(number, **fields)

        def unexpected_tool(*args, **kwargs):
            tool_calls["runTool"] += 1
            raise AssertionError("stage/tool must not run before association")

        raised = None
        with patch.object(runner, "preflight_context", lambda: fake_preflight(runner)), \
                patch.object(runner, "verify_prepare_inputs", lambda _r: fake_prepare_inputs(runner)), \
                patch.object(runner, "update_attempt", failing_update), \
                patch.object(runner, "run_tool_container", unexpected_tool), \
                resource_doubles(runner, guard) as calls:
            try:
                runner.compile_attempt(plan, "a" * 64, 1, "a" * 32)
            except BaseException as error:  # noqa: BLE001
                raised = type(error).__name__ + ":" + str(error)[:100]
        stage_dirs = list(workspace.prepare.glob("stage-compile-*"))
        plans = [json.loads(item.read_bytes()) for item in
                 (workspace.prepare / "plans").glob("*.json")]
        passed = (raised is not None and stage_dirs == [] and tool_calls["runTool"] == 0
                  and all(value.get("stageState") == "not-created" for value in plans)
                  and calls["docker"] == 0 and calls["remove"] == 0
                  and calls["stop"] == 0 and calls["stage"] == 0)
        return passed, {"raised": raised, "stageDirs": [str(p) for p in stage_dirs],
                        "toolCalls": tool_calls["runTool"],
                        "planStates": [value.get("stageState") for value in plans],
                        "calls": calls}
    finally:
        workspace.close()


@check("B4-associated-prep-unknown-holds-parent", "unresolved associated preparation keeps the target reservation held")
def b4_assoc_unknown(runner, guard):
    workspace = Workspace(runner, "b4-assoc-unknown-")
    try:
        target_tag = "d" * 16
        target_stage = workspace.runs / "0001" / ("stage-" + target_tag)
        target_id, target_plan, _identity = created_plan(
            runner, guard, "run-0001", target_stage, target_tag, attempt=1,
            process_roles=("client", "observer"))
        target_plan.update({"containerState": "not-created", "containerId": None,
                            "processes": {"client": {"spawnState": "not-started"},
                                          "observer": {"spawnState": "not-started"}}})
        write_plan(runner, target_id, target_plan)
        compile_tag = "e" * 16
        compile_stage = workspace.prepare / ("stage-compile-0001-" + compile_tag)
        compile_id, compile_plan, _identity = created_plan(
            runner, guard, "compile-0001-" + compile_tag[:8], compile_stage,
            compile_tag, attempt=1)
        compile_plan["processes"] = {"client": {"spawnState": "unknown"}}
        compile_plan["parentAttempt"] = 1
        write_plan(runner, compile_id, compile_plan)
        record = target_record(runner, 1, target_id, target_plan)
        record["associatedPrepareIds"] = [compile_id]
        runner.write_json_document(runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.cleanup_attempt, record)
            runner.release_batch_lock()
        stored = json.loads(runner.attempt_path(1).read_bytes())
        passed = (kind == "return" and value is False
                  and stored.get("reservationHeld") is True
                  and target_stage.is_dir()
                  and compile_stage.is_dir())
        return passed, {"kind": kind, "value": value, "calls": calls,
                        "reservationHeld": stored.get("reservationHeld"),
                        "targetStageExists": target_stage.is_dir(),
                        "compileStageExists": compile_stage.is_dir()}
    finally:
        workspace.close()


@check("B4-old-empty-process-record-held", "legacy empty-process record with no proof is not promoted to success")
def b4_old_empty(runner, guard):
    workspace = Workspace(runner, "b4-old-empty-")
    try:
        record = {"version": 1, "attempt": 1, "state": "reserved",
                  "processes": {"client": {"spawnState": "not-started"},
                                "observer": {"spawnState": "not-started"}},
                  "reservationHeld": True, "settled": False, "checkpoints": []}
        runner.write_json_document(runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.cleanup_attempt, record)
        stored = json.loads(runner.attempt_path(1).read_bytes())
        passed = (kind == "return" and value is False
                  and stored.get("reservationHeld") is True
                  and no_destructive(calls))
        return passed, {"kind": kind, "value": value, "calls": calls,
                        "reservationHeld": stored.get("reservationHeld")}
    finally:
        workspace.close()


@check("B4-orphan-record-held", "orphan prepareId record with no plan is conservatively held")
def b4_orphan(runner, guard):
    workspace = Workspace(runner, "b4-orphan-")
    try:
        record = {"version": 1, "attempt": 1, "state": "planned",
                  "prepareId": "a" * 32,
                  "processes": {"client": {"spawnState": "not-started"},
                                "observer": {"spawnState": "not-started"}},
                  "reservationHeld": True, "settled": False, "checkpoints": []}
        runner.write_json_document(runner.attempt_path(1), record)
        with resource_doubles(runner, guard) as calls:
            kind, value = exit_code(runner.cleanup_attempt, record)
        stored = json.loads(runner.attempt_path(1).read_bytes())
        passed = (kind == "return" and value is False
                  and stored.get("reservationHeld") is True
                  and no_destructive(calls))
        return passed, {"kind": kind, "value": value, "calls": calls,
                        "reservationHeld": stored.get("reservationHeld")}
    finally:
        workspace.close()


@check("B4-final-log-fsync-failure", "plan/attempt journal failure is incomplete, never success")
def b4_final_log_failure(runner, guard):
    results = {}
    cases = []
    for variant in ("attempt", "plan"):
        workspace = Workspace(runner, "b4-log-" + variant + "-")
        try:
            tag = ("f" if variant == "attempt" else "1") * 16
            prepare_id, plan, _identity, record = target_plan_for_b2(
                runner, guard, workspace, tag=tag)
            original_attempt = runner.update_attempt
            original_plan = runner.update_lifecycle_plan

            if variant == "attempt":
                def failing_attempt(number, **fields):
                    if "cleanup" in fields:
                        raise OSError("simulated-final-attempt-journal-failure")
                    return original_attempt(number, **fields)
                patcher = patch.object(runner, "update_attempt", failing_attempt)
            else:
                def failing_plan(identifier, **fields):
                    if "cleanup" in fields:
                        raise OSError("simulated-final-plan-journal-failure")
                    return original_plan(identifier, **fields)
                patcher = patch.object(runner, "update_lifecycle_plan", failing_plan)
            with patcher, resource_doubles(runner, guard, stage="stub") as calls:
                raised = None
                confirmed = None
                try:
                    confirmed = runner.cleanup_attempt(record)
                except BaseException as error:  # noqa: BLE001
                    raised = type(error).__name__ + ":" + str(error)[:120]
            stored = json.loads(runner.attempt_path(1).read_bytes())
            results[variant] = {"confirmed": confirmed, "raised": raised,
                                "calls": calls,
                                "reservationHeld": stored.get("reservationHeld")}
            cases.append(raised is not None and stored.get("reservationHeld") is True)
        finally:
            workspace.close()
    return all(cases), results


@check("B4-resource-phase-monotonic", "new reservations persist explicit not-started records and a monotonic proof")
def b4_phase_monotonic(runner, guard):
    workspace = Workspace(runner, "b4-phase-")
    try:
        with resource_doubles(runner, guard):
            record = reserve_one(runner, guard, workspace)
            runner.release_batch_lock()
        proof = record.get("resourceProof") or {}
        sequence = proof.get("sequence") or []
        processes = record.get("processes") or {}
        passed = (proof.get("protocol") == "resource-phase-v1"
                  and proof.get("phase") == "reserved"
                  and len(sequence) >= 1 and sequence[-1].get("phase") == "reserved"
                  and all((proof.get("notCreated") or {}).get(key) is True for key in
                          ("stage", "container", "client", "observer"))
                  and processes.get("client", {}).get("spawnState") == "not-started"
                  and processes.get("observer", {}).get("spawnState") == "not-started")
        return passed, {"resourceProof": proof, "processes": processes}
    finally:
        workspace.close()


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
    import resource_guard as guard  # noqa: PLC0415 - source-parameterised import

    results = []
    for identifier, description, function in RESULTS:
        try:
            passed, detail = function(runner, guard)
            error = None
        except BaseException as exc:  # noqa: BLE001 - classify, never hide
            passed = False
            detail = {}
            error = {"type": type(exc).__name__,
                     "message": str(exc)[:300],
                     "traceback": traceback.format_exc()[-1200:]}
        results.append({"id": identifier, "description": description,
                        "passed": bool(passed), "detail": detail, "error": error})
        print(("PASS " if passed else "FAIL ") + identifier)

    payload = {
        "kind": "recovery-close-b1-b4-checks",
        "sourceTools": str(tools),
        "runnerSha256": sha_file(tools / "experiment_runner.py"),
        "guardSha256": sha_file(tools / "resource_guard.py"),
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "results": results,
        "passed": sum(1 for item in results if item["passed"]),
        "failed": [item["id"] for item in results if not item["passed"]],
        "total": len(results),
    }
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not payload["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
