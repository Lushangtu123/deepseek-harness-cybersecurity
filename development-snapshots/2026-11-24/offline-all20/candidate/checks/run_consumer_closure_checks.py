#!/usr/bin/env python3
"""Desired-behaviour checks for the consumer-closure round.

The same module is source-parameterised: ``--tools baseline`` records the
pre-implementation RED facts and ``--tools tools`` records the repaired GREEN
facts.  All resources are pure in-process doubles or recorded shims.  No real
Docker, BPF/bpftrace, compiler, selfcheck, fixture, target or admission runs.

Covered here:

* settlement recomputes the parent and every known related lifecycle record;
* recovery-success settlement applies the same recomputation;
* a damaged/unreadable/unknown preparation record blocks every new task or
  preparation start in this exact batch, before any counter or journal write;
* known read/association failures map to diagnostic incomplete (3) at the
  public command boundary, while ownership contradictions stay 78;
* the public CLI compile path is exercised through a controlled sandbox.
"""
import argparse
import contextlib
import fcntl
import importlib
import io
import json
import os
import stat
import subprocess
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TMP = ROOT / "checks" / "tmp"
sys.path.insert(0, str(HERE))

import run_unified_recovery_checks as U  # noqa: E402
import regression_lib  # noqa: E402

RESULTS = []
RETAINED_SANDBOXES = []





def check(identifier, description):
    def decorate(function):
        RESULTS.append((identifier, description, function))
        return function
    return decorate


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(runner, path, value):
    runner.write_json_document(Path(path), value)
    return value


def mark_attempt_confirmed(runner, number, held=True):
    record = read_json(runner.attempt_path(number))
    checked = "1970-01-01T00:00:00+00:00"
    record.update({
        "cleanup": {"confirmed": True, "state": "confirmed",
                    "checkedAt": checked, "finalStageCheck": "after-resources"},
        "cleanupCheck": {
            "protocol": "cleanup-check-v1", "state": "confirmed",
            "attempt": number, "startedAt": checked, "startedCount": 1,
            "finishedAt": checked,
        },
        "reservationHeld": bool(held),
        "settled": not held,
    })
    write_json(runner, runner.attempt_path(number), record)
    return record


def seed_historical_receipt(runner, number):
    """Preserve one already-recorded historical cleanup receipt before a fault."""
    record = read_json(runner.attempt_path(number))
    row = {
        "state": "confirmed",
        "confirmed": True,
        "checkedAt": "1969-12-31T23:59:59+00:00",
        "resourceCreationPhase": "reserved",
    }
    record["cleanupReceipts"] = list(record.get("cleanupReceipts") or []) + [row]
    write_json(runner, runner.attempt_path(number), record)
    return row


def read_query_and_status(runner, number):
    """Read the public query/status views without mutating the journal."""
    with contextlib.redirect_stdout(io.StringIO()) as status_out, \
            contextlib.redirect_stderr(io.StringIO()):
        status_code = U.exit_code(runner.command_status)
    status_payload = json.loads(status_out.getvalue())
    with contextlib.redirect_stdout(io.StringIO()) as query_out, \
            contextlib.redirect_stderr(io.StringIO()):
        query_code = U.exit_code(runner.command_query, number)
    query_payload = json.loads(query_out.getvalue())
    status_row = next(
        (row for row in status_payload.get("attempts") or []
         if row.get("attempt") == number), {})
    return {
        "statusCode": status_code,
        "queryCode": query_code,
        "statusRow": status_row,
        "query": query_payload,
    }


def damage_plan(runner, prepare_id, mode="fields", workspace=None):
    path = runner.lifecycle_plan_path(prepare_id)
    if mode == "malformed":
        path.write_bytes(b"{not-json\n")
    elif mode == "unicode":
        path.write_bytes(b"\xff\xfe\x00broken\n")
    elif mode == "symlink":
        if workspace is None:
            raise ValueError('symlink damage requires its owning workspace')
        path.unlink()
        os.symlink(str(path) + ".missing-target", path)
        workspace.track_fixture_link(path)
        return None
    else:
        plan = read_json(path)
        plan["cleanup"] = {"confirmed": True, "state": "confirmed",
                           "checkedAt": 17}
        write_json(runner, path, plan)
    return path.read_bytes()


def try_reserve(runner, number, plan=None):
    plan = plan or json.loads((ROOT / "experiment-plan.json").read_text())
    admission = {"allowedAttempts": [1, 2, 3], "reviewer": "synthetic-closure"}
    with patch.object(runner, "preflight_context", U.fake_preflight):
        try:
            result = runner.reserve_attempt(plan, "a" * 64, number, admission)
            return "return", result
        except SystemExit as error:
            return "exit", error.code
        except BaseException as error:  # noqa: BLE001 - never hide a traceback
            return "raised", type(error).__name__ + ":" + str(error)[:200]
        finally:
            runner.release_batch_lock()


def plan_names(runner):
    directory = runner.plans_dir()
    return sorted(path.name for path in directory.iterdir()) \
        if directory.is_dir() else []


# --------------------------------------------------------------- settlement
@check("settlement-parent-and-damaged-child-refused",
       "a good parent with a damaged known child never settles completed")
def settlement_bad_child(runner, guard):
    workspace = U.Workspace(runner, "closure-settle-child-")
    failed_workspace = None
    try:
        setup = U.parent_child(workspace, runner, guard, child_tag="b1" * 8,
                               parent_success=False, child_success=False)
        mark_attempt_confirmed(runner, 1)
        history = seed_historical_receipt(runner, 1)
        damaged = damage_plan(runner, setup["childId"], "fields")
        child_path = runner.lifecycle_plan_path(setup["childId"])
        counter_before = read_json(runner.counter_path())
        with U.resource_doubles(runner, guard) as calls:
            state = runner.settle(1, True, "confirmed", True)
        parent = read_json(runner.attempt_path(1))
        journal_after = runner.attempt_path(1).read_bytes()
        views = read_query_and_status(runner, 1)
        status = views["statusRow"]
        query = views["query"]
        checks = {
            "stateUnknown": state == "unknown",
            "notCompleted": parent.get("state") != "completed",
            "notSettled": parent.get("settled") is False,
            "held": parent.get("reservationHeld") is True,
            "childBytesExact": child_path.read_bytes() == damaged,
            "counterUnchanged": read_json(runner.counter_path()) == counter_before,
            "noResourceOperation": U.no_destructive(calls) and calls["docker"] == 0,
            # A related failure must durably invalidate the parent's *current*
            # cleanup success while keeping its historical receipts.
            "cleanupConfirmedFalse": (parent.get("cleanup") or {}).get(
                "confirmed") is False,
            "cleanupStateIncomplete": (parent.get("cleanup") or {}).get(
                "state") == "incomplete",
            "settlementRefusalReason": (parent.get("cleanup") or {}).get(
                "reason") == "settlement-refused-scope",
            "historyPreserved": history in (parent.get("cleanupReceipts") or []),
            "historyNonEmpty": bool(parent.get("cleanupReceipts")),
            "statusEffectiveFalse": status.get(
                "effectiveCleanupConfirmed") is False,
            "statusHeld": status.get("effectiveReservationHeld") is True,
            "statusQueryExit0": views["statusCode"][0] == "return"
            and views["statusCode"][1] in {None, 0}
            and views["queryCode"] == ("return", 0),
            "queryEffectiveFalse": query.get(
                "effectiveCleanupConfirmed") is False,
            "queryHeld": query.get("reservationHeld") is True,
            "queryNotSettled": query.get("settled") is False,
            "viewsReadOnly": runner.attempt_path(1).read_bytes() == journal_after,
        }
        # A failed hold write may never be presented as a successful settlement.
        failed_workspace = U.Workspace(runner, "closure-settle-holdfail-")
        setup2 = U.parent_child(failed_workspace, runner, guard,
                                child_tag="b2" * 8, parent_success=False,
                                child_success=False)
        mark_attempt_confirmed(runner, 1)
        damage_plan(runner, setup2["childId"], "malformed")
        counter2 = read_json(runner.counter_path())
        original_write = runner.write_json_document

        def failing_write(path, value, _original=original_write):
            if Path(path) == Path(runner.attempt_path(1)):
                raise OSError("simulated-settlement-hold-write")
            return _original(path, value)

        with patch.object(runner, "write_json_document", failing_write), \
                U.resource_doubles(runner, guard) as calls2:
            state2 = runner.settle(1, True, "confirmed", True)
        checks.update({
            "holdWriteNotCompleted": state2 != "completed",
            "holdWriteUnknown": state2 == "unknown",
            "holdWriteCounterUnchanged":
            read_json(runner.counter_path()) == counter2,
            "holdWriteNoResource": U.no_destructive(calls2)
            and calls2["docker"] == 0,
        })
        return all(checks.values()), {"checks": checks, "state": state,
                                      "parent": parent, "calls": calls,
                                      "views": views,
                                      "holdWriteState": state2,
                                      "calls2": calls2}
    finally:
        if failed_workspace is not None:
            failed_workspace.close()
        workspace.close()


@check("settlement-linked-child-unavailable-variants",
       "missing/malformed/unreadable linked children refuse completion and keep bytes")
def settlement_child_variants(runner, guard):
    variants = {}
    cases = []
    for mode in ("missing", "malformed", "unicode", "permission", "symlink"):
        workspace = U.Workspace(runner, "closure-settle-" + mode + "-")
        try:
            setup = U.parent_child(workspace, runner, guard,
                                   child_tag=("c2" if mode == "missing" else
                                              "c3" if mode == "malformed" else
                                              "c4" if mode == "unicode" else
                                              "c5" if mode == "permission" else
                                              "c6") * 8,
                                   parent_success=False, child_success=False)
            mark_attempt_confirmed(runner, 1)
            history = seed_historical_receipt(runner, 1)
            path = runner.lifecycle_plan_path(setup["childId"])
            patcher = contextlib.nullcontext()
            if mode == "missing":
                path.unlink()
                damaged = None
            elif mode == "permission":
                damaged = path.read_bytes()
                original = runner.read_json

                def failing(target, _original=original, _path=path):
                    if Path(target) == Path(_path):
                        raise PermissionError("synthetic-child-permission")
                    return _original(target)

                patcher = patch.object(runner, "read_json", failing)
            else:
                damaged = damage_plan(runner, setup["childId"], mode, workspace=workspace)
            with patcher, U.resource_doubles(runner, guard) as calls:
                state = runner.settle(1, True, "confirmed", True)
            parent = read_json(runner.attempt_path(1))
            after = path.read_bytes() if path.is_file() and not path.is_symlink() else None
            checks = {
                "stateUnknown": state == "unknown",
                "notSettled": parent.get("settled") is False,
                "held": parent.get("reservationHeld") is True,
                "bytesRetained": after == damaged,
                "noResourceOperation": U.no_destructive(calls),
                "cleanupConfirmedFalse": (parent.get("cleanup") or {}).get(
                    "confirmed") is False,
                "historyPreserved": history in (
                    parent.get("cleanupReceipts") or []),
            }
            cases.append(all(checks.values()))
            variants[mode] = {"checks": checks, "state": state}
        finally:
            workspace.close()
    return all(cases), {"variants": variants}


@check("settlement-complete-scope-releases",
       "a complete, currently confirmed parent/child scope still settles completed")
def settlement_complete_scope(runner, guard):
    workspace = U.Workspace(runner, "closure-settle-good-")
    try:
        setup = U.parent_child(workspace, runner, guard, child_tag="c7" * 8,
                               parent_success=False, child_success=False)
        U.previous_success_plan(runner, setup["parentId"])
        U.previous_success_plan(runner, setup["childId"])
        mark_attempt_confirmed(runner, 1)
        state = runner.settle(1, True, "confirmed", True)
        parent = read_json(runner.attempt_path(1))
        checks = {
            "completed": state == "completed",
            "settled": parent.get("settled") is True,
            "released": parent.get("reservationHeld") is False,
        }
        return all(checks.values()), {"checks": checks, "parent": parent}
    finally:
        workspace.close()


@check("settlement-semantic-unknown-with-confirmed-cleanup-can-settle",
       "semantic unknown records settle when actual resources are clean")
def settlement_semantic_unknown(runner, guard):
    workspace = U.Workspace(runner, "closure-settle-unknown-")
    try:
        setup = U.parent_child(workspace, runner, guard, child_tag="c8" * 8,
                               parent_success=False, child_success=False)
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        U.previous_success_plan(runner, setup["parentId"])
        U.previous_success_plan(runner, setup["childId"])
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        child["state"] = "unknown"
        child["processes"] = {"client": {"spawnState": "unknown"}}
        write_json(runner, runner.lifecycle_plan_path(setup["childId"]), child)
        mark_attempt_confirmed(runner, 1)
        state = runner.settle(1, True, "confirmed", True)
        parent = read_json(runner.attempt_path(1))
        checks = {
            "completed": state == "completed",
            "settled": parent.get("settled") is True,
            "released": parent.get("reservationHeld") is False,
            "childStillValid": U.read_json(
                runner.lifecycle_plan_path(setup["childId"])).get("state") == "unknown",
        }
        return all(checks.values()), {"checks": checks, "parent": parent}
    finally:
        workspace.close()


@check("settlement-recompute-after-child-change",
       "settlement truth is recomputed after a prior good scope and child change")
def settlement_recompute(runner, guard):
    workspace = U.Workspace(runner, "closure-settle-recompute-")
    try:
        setup = U.parent_child(workspace, runner, guard, child_tag="c9" * 8,
                               parent_success=False, child_success=True)
        U.previous_success_plan(runner, setup["parentId"])
        mark_attempt_confirmed(runner, 1)
        first_ok, first = runner._settlement_validation_ok(1)
        child = read_json(runner.lifecycle_plan_path(setup["childId"]))
        child["cleanup"] = {"confirmed": False, "state": "incomplete",
                            "checkedAt": "1970-01-01T00:00:00+00:00"}
        write_json(runner, runner.lifecycle_plan_path(setup["childId"]), child)
        second_ok, second = runner._settlement_validation_ok(1)
        checks = {
            "firstReleasable": first_ok is True,
            "secondRefused": second_ok is False,
            "secondDiagnostic": bool(second.get("settlementProblems")),
        }
        return all(checks.values()), {"checks": checks, "first": first,
                                      "second": second}
    finally:
        workspace.close()


@check("recovery-settlement-refuses-stale-parent-success",
       "recovery settlement recomputes related children instead of trusting a boolean")
def recovery_settlement_recompute(runner, guard):
    workspace = U.Workspace(runner, "closure-recovery-settle-")
    try:
        setup = U.parent_child(workspace, runner, guard, child_tag="ca" * 8,
                               parent_success=False, child_success=False)
        U.previous_success_plan(runner, setup["parentId"])
        mark_attempt_confirmed(runner, 1)
        history = seed_historical_receipt(runner, 1)
        U.previous_success_plan(runner, setup["childId"])
        damaged = damage_plan(runner, setup["childId"], "fields")
        counter_before = read_json(runner.counter_path())
        with patch.object(runner, "cleanup_attempt", lambda record: True), \
                U.resource_doubles(runner, guard) as calls:
            result = U.recover(runner, number=1)
        parent = read_json(runner.attempt_path(1))
        journal_after = runner.attempt_path(1).read_bytes()
        views = read_query_and_status(runner, 1)
        status = views["statusRow"]
        query = views["query"]
        checks = {
            "incomplete3": result[0] == "return" and result[1] == 3,
            "notReleased": parent.get("settled") is False,
            "held": parent.get("reservationHeld") is True,
            "noDestructive": U.no_destructive(calls),
            "diagnostic": "settlement-refused" in result[3],
            "childBytesExact": runner.lifecycle_plan_path(
                setup["childId"]).read_bytes() == damaged,
            "counterUnchanged": read_json(runner.counter_path()) == counter_before,
            "cleanupConfirmedFalse": (parent.get("cleanup") or {}).get(
                "confirmed") is False,
            "historyPreserved": history in (parent.get("cleanupReceipts") or []),
            "statusEffectiveFalse": status.get(
                "effectiveCleanupConfirmed") is False,
            "statusHeld": status.get("effectiveReservationHeld") is True,
            "queryEffectiveFalse": query.get(
                "effectiveCleanupConfirmed") is False,
            "queryHeld": query.get("reservationHeld") is True,
            "queryNotSettled": query.get("settled") is False,
            "viewsReadOnly": runner.attempt_path(1).read_bytes() == journal_after,
        }
        return all(checks.values()), {"checks": checks, "result": result[:2],
                                      "stderr": result[3][-240:],
                                      "parent": parent, "views": views}
    finally:
        workspace.close()


# --------------------------------------------------- same-batch new starts
def _damaged_plan_cases():
    return ("fields", "malformed", "unicode", "symlink", "standalone")


@check("new-reservation-blocked-by-damaged-preparation",
       "a damaged/unknown plan record blocks attempt 2 before counter or journal writes")
def reservation_blocked(runner, guard):
    variants = {}
    cases = []
    for mode in _damaged_plan_cases():
        workspace = U.Workspace(runner, "closure-reserve-" + mode + "-")
        try:
            U.reserve_one(runner)
            if mode == "standalone":
                tag = "d1" * 8
                stage = workspace.prepare / ("stage-bind-" + tag)
                prepare_id, _plan = runner.write_lifecycle_plan(
                    "bind-" + tag[:8], stage, tag,
                    runner.container_name("bind-" + tag[:8], tag))
            else:
                prepare_id, _plan, _stage = U.make_plan(
                    runner, guard, workspace, "compile", "d2" * 8, attempt=2,
                    stage_state="not-created")
            damage_plan(runner, prepare_id, mode if mode != "standalone" else "fields",
                         workspace=workspace)
            counter_before = read_json(runner.counter_path())
            attempts_before = sorted(path.name for path in workspace.state.iterdir())
            with U.resource_doubles(runner, guard) as calls:
                kind, value = try_reserve(runner, 2)
            counter_after = read_json(runner.counter_path())
            attempts_after = sorted(path.name for path in workspace.state.iterdir())
            checks = {
                "incomplete3": kind == "exit" and value == 3,
                "notRaised": kind != "raised",
                "counterUnchanged": counter_after == counter_before,
                "noAttempt2": not runner.attempt_path(2).exists(),
                "stateUnchanged": attempts_before == attempts_after,
                "noResourceOperation": U.no_destructive(calls),
            }
            cases.append(all(checks.values()))
            variants[mode] = {"checks": checks, "kind": kind, "value": value}
        finally:
            workspace.close()
    return all(cases), {"variants": variants}


@check("new-reservation-blocked-by-unknown-plans-directory",
       "an unreadable whole plans directory blocks a new reservation")
def reservation_unknown_directory(runner, guard):
    workspace = U.Workspace(runner, "closure-reserve-unknown-dir-")
    try:
        U.reserve_one(runner)
        directory = runner.plans_dir()
        directory.mkdir()
        counter_before = read_json(runner.counter_path())
        with regression_lib.sampling_fault_window():
            directory.chmod(0)
            try:
                kind, value = try_reserve(runner, 2)
            finally:
                directory.chmod(0o700)
        checks = {
            "incomplete3": kind == "exit" and value == 3,
            "counterUnchanged": read_json(runner.counter_path()) == counter_before,
            "noAttempt2": not runner.attempt_path(2).exists(),
        }
        return all(checks.values()), {"checks": checks, "kind": kind, "value": value}
    finally:
        workspace.close()


@check("new-reservation-empty-directory-and-separate-batch",
       "an empty/missing plans directory is allowed and another batch root is unaffected")
def reservation_allowed_and_separate(runner, guard):
    first = U.Workspace(runner, "closure-reserve-a-")
    second = None
    try:
        U.reserve_one(runner)
        prepare_id, _plan, _stage = U.make_plan(
            runner, guard, first, "compile", "d3" * 8, attempt=2,
            stage_state="not-created")
        damage_plan(runner, prepare_id, "fields")
        bad = try_reserve(runner, 2)
        # A separate root is its own batch and still reserves normally.
        second = U.Workspace(runner, "closure-reserve-b-")
        kind, value = try_reserve(runner, 2)
        checks = {
            "damagedRootBlocked": bad[0] == "exit" and bad[1] == 3,
            "otherRootReserved": kind == "return" and runner.attempt_path(2).is_file(),
            "otherCounterAdvanced": 2 in read_json(
                runner.counter_path()).get("used", []),
        }
        return all(checks.values()), {"checks": checks, "bad": bad,
                                      "good": kind, "value": value}
    finally:
        if second is not None:
            second.close()
        first.close()


@check("compile-and-bind-preparation-blocked-before-writes",
       "compile/bind preparation refuses before a new plan, stage or tool call")
def preparation_blocked(runner, guard):
    variants = {}
    cases = []
    for step in ("compile-per-attempt", "bind-all"):
        workspace = U.Workspace(runner, "closure-prepare-" + step + "-")
        try:
            prepare_id, _plan, _stage = U.make_plan(
                runner, guard, workspace, "compile", "d4" * 8, attempt=2,
                stage_state="not-created")
            damage_plan(runner, prepare_id, "fields")
            names_before = plan_names(runner)
            counter_before = read_json(runner.counter_path()) \
                if runner.counter_path().is_file() else None
            called = {"count": 0}

            def stub(*args, **kwargs):
                called["count"] += 1
                return {"state": "synthetic"}, "0" * 64

            admission = (None, None, "0" * 64, "0" * 64, {})
            with patch.object(runner, "require_admission",
                              lambda *a, **k: admission), \
                    patch.object(runner, "verify_prepare_inputs",
                                 lambda *a, **k: {}), \
                    patch.object(runner, "load_plan",
                                 lambda: (json.loads((ROOT / "experiment-plan.json").read_text()), "a" * 64)), \
                    patch.object(runner, "compile_attempt", stub), \
                    patch.object(runner, "prepare_container_bind", stub), \
                    patch.object(runner, "prepare_container_layout", stub), \
                    U.resource_doubles(runner, guard) as calls:
                kind, value = U.exit_code(runner.command_prepare, step, 2)
            counter_after = read_json(runner.counter_path()) \
                if runner.counter_path().is_file() else None
            checks = {
                "incomplete3": kind in {"exit", "return"} and value == 3,
                "noToolCall": called["count"] == 0,
                "noNewPlan": plan_names(runner) == names_before,
                "counterUnchanged": counter_after == counter_before,
                "noResourceOperation": U.no_destructive(calls),
            }
            cases.append(all(checks.values()))
            variants[step] = {"checks": checks, "kind": kind, "value": value}
        finally:
            workspace.close()
    return all(cases), {"variants": variants}


@check("query-status-available-with-damaged-batch",
       "query/status remain available while a damaged plan blocks new starts")
def query_status_available(runner, guard):
    workspace = U.Workspace(runner, "closure-query-available-")
    try:
        U.reserve_one(runner)
        prepare_id, _plan, _stage = U.make_plan(
            runner, guard, workspace, "compile", "d5" * 8, attempt=2,
            stage_state="not-created")
        damage_plan(runner, prepare_id, "fields")
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            status = U.exit_code(runner.main, ["status"])
            query = U.exit_code(runner.main, ["query", "--attempt", "1"])
            recover = U.exit_code(runner.main, ["recover", "--attempt", "1"])
        checks = {
            "status0": status == ("return", 0),
            "query0": query == ("return", 0),
            "recoverNotCrash": recover[0] == "return" and recover[1] in {0, 3},
            "statusOutput": "preparations" in out.getvalue(),
        }
        return all(checks.values()), {"checks": checks, "status": status,
                                      "query": query, "recover": recover}
    finally:
        workspace.close()


# ----------------------------------------------------------- public CLI (shims)
@check("public-compile-known-failure-is-diagnostic-3",
       "public compile maps a known damaged associated plan to exit 3, not a traceback")
def public_compile_diagnostic(runner, guard):
    box = regression_lib.Sandbox("closure-public-compile")
    RETAINED_SANDBOXES.append({
        "caseId": "public-compile-known-failure-is-diagnostic-3",
        "relativePath": box.path.relative_to(ROOT).as_posix(),
    })
    try:
        box.write_preflight_license()
        preflight = box.preflight()
        if preflight.returncode != 0:
            raise AssertionError("controlled preflight failed: " + preflight.stderr[-500:])
        box.write_formal_admission(allowed=[1])
        box.prepare()
        plans = box.path / "prepare" / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        damaged_id = "ab" * 16
        (plans / (damaged_id + ".json")).write_bytes(b"{damaged-child\n")
        record = {
            "version": 1, "attempt": 1, "state": "reserved",
            "prepareId": None, "resourceIntent": None, "resourceIdentity": None,
            "stageDir": None, "stageIdentity": None,
            "processes": {"client": {"spawnState": "not-started"}},
            "reservationHeld": True, "settled": False,
            "targetExecutions": 0, "executionState": "not-started",
            "associatedPrepareIds": [damaged_id],
            "associationIntents": [{
                "protocol": "association-intent-v1", "attempt": 1,
                "prepareId": damaged_id, "state": "complete",
                "startedAt": "1970-01-01T00:00:00+00:00",
            }],
            "resourceProof": {
                "protocol": "resource-phase-v1", "phase": "reserved",
                "sequence": [{"phase": "reserved",
                              "at": "1970-01-01T00:00:00+00:00"}],
                "notCreated": {"stage": True, "container": True,
                               "client": True, "observer": True},
                "targetAttempt": 1,
            },
            "cleanup": {"confirmed": False},
        }
        box.write_json(box.path / "state" / "attempt-0001.json", record)
        names_before = sorted(path.name for path in plans.iterdir())
        counter_before = (box.path / "state" / "attempt-counter.json").read_bytes() \
            if (box.path / "state" / "attempt-counter.json").is_file() else None
        result = box.run(["compile", "--attempt", "1"])
        names_after = sorted(path.name for path in plans.iterdir())
        counter_after = (box.path / "state" / "attempt-counter.json").read_bytes() \
            if (box.path / "state" / "attempt-counter.json").is_file() else None
        traceback_present = "Traceback (most recent call last)" in result.stderr
        checks = {
            "exit3": result.returncode == 3,
            "noTraceback": not traceback_present,
            "diagnostic": ("known-record-state" in result.stderr
                           or "incomplete" in result.stderr),
            "noNewPlan": names_after == names_before,
            "counterUnchanged": counter_after == counter_before,
            "damagedBytesRetained": (plans / (damaged_id + ".json")).read_bytes()
            == b"{damaged-child\n",
        }
        return all(checks.values()), {
            "checks": checks, "returncode": result.returncode,
            "stderr": result.stderr[-400:], "plansBefore": names_before,
            "plansAfter": names_after,
        }
    except BaseException:
        raise


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
    runner = U.load_runner(tools)
    import resource_guard as guard  # noqa: PLC0415 - source-parameterised

    RETAINED_SANDBOXES.clear()
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
        "kind": "consumer-closure-settlement-and-batch-checks",
        "sourceTools": str(tools),
        "runnerSha256": U.sha_file(tools / "experiment_runner.py"),
        "guardSha256": U.sha_file(tools / "resource_guard.py"),
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
        "retainedSandboxes": list(RETAINED_SANDBOXES),
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
