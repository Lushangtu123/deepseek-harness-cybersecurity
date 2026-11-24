#!/usr/bin/env python3
"""Focused offline checks for damaged-record preservation and effective state.

Private synthetic records and in-process resource doubles only.  No Docker,
BPF/bpftrace, compiler, selfcheck, fixture, target or paid execution is used.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
sys.path.insert(0, str(ROOT / "checks"))
import regression_lib  # noqa: E402
RUNNER = ROOT / "tools" / "experiment_runner.py"
SPEC = importlib.util.spec_from_file_location("record_validation_runner", RUNNER)
m = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(ROOT / "tools"))
SPEC.loader.exec_module(m)

CHECKS = []
ABSENT = {"removed": True, "state": "absent",
          "queries": {"id": {"state": "absent"}, "name": {"state": "absent"},
                      "tag": {"state": "absent"}}}


def sha_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def record(name, passed, **fields):
    CHECKS.append({"id": name, "test": name, "passed": bool(passed), **fields})
    print(("PASS " if passed else "FAIL ") + name)
    return passed


def check(name, description=None):
    def wrapper(function):
        def invoke():
            try:
                detail = function()
                return record(name, True, description=description, detail=detail)
            except BaseException as error:  # noqa: BLE001 - preserve raw failure
                return record(
                    name, False, description=description,
                    error={"type": type(error).__name__, "message": str(error)[:2000],
                           "traceback": traceback.format_exc()[-4000:]})
        invoke.__name__ = function.__name__
        CHECKS.append({"deferred": name, "invoke": invoke})
        return invoke
    return wrapper


class Sandbox:
    def __init__(self):
        TMP.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix="record-validation-", dir=TMP))
        self.root = self.path
        for name in ("state", "prepare", "runs"):
            (self.root / name).mkdir()
        self._patches = None

    def __enter__(self):
        self._patches = [
            patch.multiple(m, ROOT=self.root, STATE=self.root / "state",
                           PREPARE=self.root / "prepare", RUNS=self.root / "runs"),
            patch.object(m.guard, "docker",
                         side_effect=AssertionError("real Docker forbidden")),
            patch.object(m.guard, "stop_group",
                         side_effect=AssertionError("real signals forbidden")),
        ]
        for item in self._patches:
            item.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        m.release_batch_lock()
        for item in reversed(self._patches):
            item.stop()
        regression_lib.retire_sandbox(self.path)


def reserve(number=1, allowed=None, challenge=None):
    hash_value = "a" * 64
    plan = read_json(ROOT / "experiment-plan.json")
    with patch.object(m, "preflight_context", return_value={
            "bufferParserSha256": hash_value,
            "bufferTemplateSha256": hash_value,
            "frozenTemplateSha256": hash_value}):
        return m.reserve_attempt(
            plan, hash_value, number,
            {"allowedAttempts": list(allowed or [1, 2, 3])}, challenge)


def make_plan(kind, tag, number=1):
    role = "run-%04d" % number if kind == "run" \
        else "compile-%04d-%s" % (number, tag[:8])
    if kind == "run":
        stage = m.RUNS / ("%04d" % number) / ("stage-" + tag)
    else:
        stage = m.PREPARE / ("stage-compile-%04d-%s" % (number, tag))
    prepare_id, plan = m.write_lifecycle_plan(
        role, stage, tag, m.container_name(role, tag), attempt=number)
    if kind == "run":
        plan = m.update_lifecycle_plan(
            prepare_id,
            processes={"client": {"spawnState": "not-started"},
                       "observer": {"spawnState": "not-started"}})
    return prepare_id, plan, stage


def recover(**kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    kind = "return"
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = m.command_recover(**kwargs)
            except SystemExit as error:
                kind = "exit"
                code = error.code
    finally:
        m.release_batch_lock()
    return kind, code, stdout.getvalue(), stderr.getvalue()


def query(**kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = m.command_query(**kwargs)
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def status():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = m.command_status()
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def setup_success(child_count=1):
    reserve()
    parent_id, parent, parent_stage = make_plan("run", "4" * 16, 1)
    tags = ["5" * 16, "6" * 16]
    children = []
    for index in range(child_count):
        child_id, child, child_stage = make_plan("compile", tags[index], 1)
        children.append((child_id, child, child_stage))
    m.update_attempt(1, prepareId=parent_id, resourceIntent=dict(parent),
                     stageDir=str(parent_stage), processes=parent["processes"])
    for child_id, _child, _stage in children:
        m.associate_preparation(1, child_id)
    with patch.object(m, "remove_plan_container", return_value=ABSENT):
        result = recover(number=1)
    assert result[0] == "return" and result[1] == 0, ("initial valid control", result)
    for _child_id, _child, child_stage in children:
        child_stage.mkdir()
        (child_stage / "SIMULATED.txt").write_text(
            "private reappeared stage", encoding="utf-8")
    return parent_id, parent_stage, children


def damage(path, field, value):
    data = read_json(path)
    data[field] = value
    m.write_json_document(path, data)
    return Path(path).read_bytes()


def assert_unchanged(path, raw):
    assert Path(path).read_bytes() == raw, ("damaged bytes changed", str(path))


def hold_state(path):
    data = read_json(path)
    return data.get("reservationHeld"), data.get("cleanup")


def all_effective_views(value):
    if isinstance(value, dict):
        if "effectiveReservationHeld" in value:
            yield value
        for item in value.values():
            yield from all_effective_views(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_effective_views(item)


@check("legacy-missing-null-and-empty-controls",
       "missing/null legacy fields and empty valid dictionaries/lists remain accepted")
def legacy_controls():
    with Sandbox():
        reserve()
        base = read_json(m.attempt_path(1))
        details = {}
        for field in ("resourceIntent", "cleanupReceipts", "cleanup", "cleanupCheck"):
            record_value = dict(base)
            record_value.pop(field, None)
            details[field + "-missing"] = m.classify_attempt_record(record_value)["recordState"]
            record_value = dict(base)
            record_value[field] = None
            details[field + "-null"] = m.classify_attempt_record(record_value)["recordState"]
        empty = dict(base)
        empty.update({"resourceIntent": {}, "resourceIdentity": {},
                      "cleanupReceipts": [], "cleanup": {}, "cleanupCheck": {}})
        details["empty-controls"] = m.classify_attempt_record(empty)["recordState"]
        assert details["resourceIntent-missing"] == "legacy"
        assert details["cleanupReceipts-null"] == "legacy"
        assert details["empty-controls"] == "valid", details
        return details


@check("invalid-intent-shapes-preserve-parent-and-hold-valid-child",
       "B11 list/string/empty-list intents are invalid before resource calls")
def invalid_intents():
    details = {}
    for label, value in (("nonempty-list", ["bad"]), ("string", "bad"),
                         ("empty-list", [])):
        with Sandbox():
            _parent_id, _parent_stage, children = setup_success()
            child_id, _child, child_stage = children[0]
            raw = damage(m.attempt_path(1), "resourceIntent", value)
            calls = []

            def fake_remove(plan):
                calls.append(plan)
                return ABSENT

            with patch.object(m, "remove_plan_container", side_effect=fake_remove):
                result = recover(number=1)
            assert result[0:2] == ("return", 3), (label, result)
            assert not calls, (label, "resource calls", len(calls))
            assert_unchanged(m.attempt_path(1), raw)
            child_raw = m.lifecycle_plan_path(child_id).read_bytes()
            child_held, child_cleanup = hold_state(m.lifecycle_plan_path(child_id))
            assert child_held is True and child_cleanup.get("confirmed") is False, (label, child_cleanup)
            assert m.lifecycle_plan_path(child_id).read_bytes() == child_raw
            _code, view, _err = query(number=1)
            assert view["recordState"] == "invalid", (label, view.get("recordState"))
            assert view["effectiveReservationHeld"] is True
            assert view["effectiveCleanupConfirmed"] is False
            assert view["recordIssues"] and all(isinstance(item, str) for item in view["recordIssues"])
            assert read_json(m.counter_path())["used"] == [1]
            assert child_stage.is_dir()
            details[label] = {"exit": 3, "calls": 0, "childHeld": True}
    return details


@check("malformed-history-parent-and-child-preserved",
       "B12 parent/child history variants are not converted to empty lists")
def malformed_history():
    details = {}
    for location in ("parent", "child"):
        for label, value in (("string", "damaged-history"),
                             ("object", {"bad": True}),
                             ("list-member", [7])):
            with Sandbox():
                parent_id, _parent_stage, children = setup_success()
                child_id, _child, child_stage = children[0]
                path = m.attempt_path(1) if location == "parent" \
                    else m.lifecycle_plan_path(child_id)
                if location == "parent":
                    m.lifecycle_plan_path(parent_id).unlink()
                raw = damage(path, "cleanupReceipts", value)
                calls = []
                with patch.object(m, "remove_plan_container",
                                  side_effect=lambda plan: calls.append(plan) or ABSENT):
                    result = recover(number=1)
                assert result[0:2] == ("return", 3), (location, label, result)
                assert not calls, (location, label, "resource calls")
                assert_unchanged(path, raw)
                _code, view, _err = query(number=1 if location == "parent" else None,
                                          prepare_id=None if location == "parent" else child_id)
                holder = next(all_effective_views(view), None)
                assert holder is not None, (location, label, "no effective view")
                assert holder["recordState"] == "invalid"
                assert holder["effectiveReservationHeld"] is True
                assert holder["effectiveCleanupConfirmed"] is False
                assert read_json(m.counter_path())["used"] == [1]
                assert child_stage.is_dir()
                details[location + ":" + label] = {"exit": 3, "preserved": True}
    return details


@check("recognized-cleanup-field-types-are-validated",
       "cleanup/cleanupCheck dicts reject wrong recognized types before writes")
def cleanup_fields():
    with Sandbox():
        reserve()
        base = read_json(m.attempt_path(1))
        cases = {
            "cleanup-string": ("cleanup", "bad"),
            "cleanup-confirmed-string": ("cleanup", {"confirmed": "yes"}),
            "cleanup-state-value": ("cleanup", {"state": "made-up"}),
            "check-string": ("cleanupCheck", "bad"),
            "check-protocol": ("cleanupCheck", {"protocol": "wrong"}),
            "check-count": ("cleanupCheck", {"startedCount": "1"}),
            "check-state": ("cleanupCheck", {"state": "bogus"}),
        }
        details = {}
        for label, (field, value) in cases.items():
            record_value = dict(base)
            record_value[field] = value
            classification = m.classify_attempt_record(record_value)
            assert classification["recordState"] == "invalid", (label, classification)
            assert classification["recordIssues"]
            details[label] = "invalid"
        # One actual recovery keeps exact bytes for both current-field cases.
        for field in ("cleanup", "cleanupCheck"):
            with Sandbox():
                _pid, _stage, children = setup_success()
                child_id, _child, child_stage = children[0]
                raw = damage(m.attempt_path(1), field, "bad")
                with patch.object(m, "remove_plan_container", return_value=ABSENT):
                    result = recover(number=1)
                assert result[0:2] == ("return", 3)
                assert_unchanged(m.attempt_path(1), raw)
                assert hold_state(m.lifecycle_plan_path(child_id))[0] is True
                assert child_stage.is_dir()
        return details


@check("valid-parent-invalid-child-holds-valid-sibling",
       "a damaged child is untouched while a readable sibling is held")
def valid_parent_invalid_child():
    with Sandbox():
        _parent, _parent_stage, children = setup_success(child_count=2)
        damaged_id, _damaged, _damaged_stage = children[0]
        sibling_id, _sibling, sibling_stage = children[1]
        raw = damage(m.lifecycle_plan_path(damaged_id), "cleanupReceipts", "bad")
        calls = []
        with patch.object(m, "remove_plan_container",
                          side_effect=lambda plan: calls.append(plan) or ABSENT):
            result = recover(number=1)
        assert result[0:2] == ("return", 3), result
        assert not calls
        assert_unchanged(m.lifecycle_plan_path(damaged_id), raw)
        assert hold_state(m.lifecycle_plan_path(sibling_id))[0] is True
        assert sibling_stage.is_dir()
        return {"exit": 3, "damagedPreserved": True, "siblingHeld": True, "calls": 0}


@check("multiple-children-one-contradiction-holds-read-sibling",
       "D2 reads the whole scope before 78 and holds a valid readable sibling")
def contradiction_scope():
    with Sandbox():
        _parent, parent_stage, children = setup_success(child_count=2)
        valid_id, _valid, valid_stage = children[0]
        conflict_id, _conflict, conflict_stage = children[1]
        plan = read_json(m.lifecycle_plan_path(conflict_id))
        plan["prepareId"] = "a" * 32
        m.write_json_document(m.lifecycle_plan_path(conflict_id), plan)
        raw = m.lifecycle_plan_path(conflict_id).read_bytes()
        calls = []
        with patch.object(m, "remove_plan_container",
                          side_effect=lambda plan: calls.append(plan) or ABSENT):
            result = recover(number=1)
        assert result[0:2] == ("exit", 78), result
        assert not calls
        assert_unchanged(m.lifecycle_plan_path(conflict_id), raw)
        assert hold_state(m.lifecycle_plan_path(valid_id))[0] is True
        assert valid_stage.is_dir() and conflict_stage.is_dir()
        return {"exit": 78, "validSiblingHeld": True,
                "contradictoryPreserved": True, "calls": 0}


@check("read-error-and-partial-enumeration-hold-known-child",
       "unreadable/partial plan discovery still holds a directly readable known child")
def read_and_enumeration():
    with Sandbox():
        _parent, _parent_stage, children = setup_success()
        child_id, _child, child_stage = children[0]
        # A direct read failure is unreadable, not an empty scope.
        with patch.object(m, "read_json", side_effect=PermissionError("denied")):
            opened = m.open_attempt_record(1)
        assert opened["state"] == "unreadable" and opened["detail"] == "permission-denied"
        # A directory enumeration failure retains the parent list and holds it.
        with patch.object(m.os, "scandir", side_effect=OSError("simulated-io")), \
                patch.object(m, "remove_plan_container", return_value=ABSENT):
            result = recover(number=1)
        assert result[0:2] == ("return", 3), result
        assert hold_state(m.lifecycle_plan_path(child_id))[0] is True
        assert child_stage.is_dir()
        return {"exit": 3, "childHeld": True, "readState": opened["state"]}


@check("write-failure-cannot-claim-durable-hold",
       "a hold-write failure is reported and damaged bytes remain exact")
def write_failure():
    with Sandbox():
        _parent, _parent_stage, children = setup_success()
        child_id, _child, child_stage = children[0]
        raw = damage(m.attempt_path(1), "resourceIntent", ["bad"])
        child_raw = m.lifecycle_plan_path(child_id).read_bytes()
        with patch.object(m, "write_json_document",
                          side_effect=OSError("simulated-log-failure")), \
                patch.object(m, "remove_plan_container", return_value=ABSENT):
            result = recover(number=1)
        assert result[0:2] == ("return", 3), result
        assert_unchanged(m.attempt_path(1), raw)
        assert_unchanged(m.lifecycle_plan_path(child_id), child_raw)
        assert hold_state(m.lifecycle_plan_path(child_id))[0] is False
        assert "holdFailures" in result[3] or "record-invalid" in result[3]
        assert child_stage.is_dir()
        return {"exit": 3, "falseDurableClaim": False, "stderr": result[3][-500:]}


@check("raw-success-is-not-effective-success",
       "query/status expose raw success separately from effective unknown hold")
def raw_versus_effective():
    with Sandbox():
        setup_success()
        # Create a raw-success-looking record whose nested history is damaged.
        record_value = read_json(m.attempt_path(1))
        record_value["cleanup"] = {"state": "confirmed", "confirmed": True,
                                   "checkedAt": "1970-01-01T00:00:00+00:00",
                                   "stage": {"removed": True, "state": "absent"}}
        record_value["cleanupReceipts"] = "damaged-history"
        record_value["reservationHeld"] = False
        record_value["settled"] = True
        m.write_json_document(m.attempt_path(1), record_value)
        raw = m.attempt_path(1).read_bytes()
        _code, view, _err = query(number=1)
        assert view["cleanup"]["confirmed"] is True
        assert view["reservationHeld"] is False
        assert view["recordState"] == "invalid"
        assert view["effectiveCleanupConfirmed"] is False
        assert view["effectiveReservationHeld"] is True
        assert view["recordIssues"]
        _code, state, _err = status()
        row = next(item for item in state["attempts"] if item.get("attempt") == 1)
        assert row["recordState"] == "invalid"
        assert row["effectiveCleanupConfirmed"] is False
        assert row["effectiveReservationHeld"] is True
        assert m.attempt_path(1).read_bytes() == raw
        return {"rawConfirmed": True, "effectiveConfirmed": False,
                "effectiveHeld": True, "readOnly": True}


@check("reservation-and-settlement-refuse-damaged-record",
       "new reservation and settlement consume shared effective validation")
def reservation_and_settlement():
    with Sandbox():
        reserve()
        raw = damage(m.attempt_path(1), "cleanupReceipts", "bad")
        counter_before = read_json(m.counter_path())
        hash_value = "a" * 64
        plan = read_json(ROOT / "experiment-plan.json")
        kind = "return"
        try:
            with patch.object(m, "preflight_context", return_value={
                    "bufferParserSha256": hash_value,
                    "bufferTemplateSha256": hash_value,
                    "frozenTemplateSha256": hash_value}):
                m.reserve_attempt(plan, hash_value, 2,
                                  {"allowedAttempts": [1, 2, 3]})
        except SystemExit as error:
            kind = "exit"
            code = error.code
        finally:
            m.release_batch_lock()
        assert kind == "exit" and code == 3, (kind, code)
        assert not m.attempt_path(2).exists()
        assert read_json(m.counter_path()) == counter_before
        assert_unchanged(m.attempt_path(1), raw)
        assert m.settle(1, True, "confirmed", True) == "unknown"
        assert_unchanged(m.attempt_path(1), raw)
        return {"reservationExit": 3, "counterUnchanged": True,
                "settlement": "unknown", "bytesPreserved": True}


@check("normal-cleanup-and-repeat-recovery-are-not-replayed",
       "valid cleanup works and a repeated recovery does not replay or refund")
def normal_repeat():
    with Sandbox():
        _parent, _stage, children = setup_success()
        # A clean repeat, not a new unexplained/recreated stage.
        shutil.rmtree(children[0][2])
        counter = read_json(m.counter_path())
        calls = []
        with patch.object(m, "remove_plan_container",
                          side_effect=lambda plan: calls.append(plan) or ABSENT):
            first = recover(number=1)
        assert first[0:2] == ("return", 0), first
        stored = read_json(m.attempt_path(1))
        assert stored["settled"] is True and stored["reservationHeld"] is False
        with patch.object(m, "remove_plan_container",
                          side_effect=lambda plan: calls.append(plan) or ABSENT):
            second = recover(number=1)
        assert second[1] in (0, 3), second
        assert read_json(m.counter_path()) == counter
        assert read_json(m.attempt_path(1)).get("targetExecutions") == 0
        assert calls, "normal control should query resources"
        return {"first": 0, "second": second[1], "counterUnchanged": True,
                "targetExecutions": 0}


@check("restored-correct-fixture-can-finish-normally",
       "after an external fixture correction, recovery completes without replay")
def restored_fixture():
    with Sandbox():
        _parent, _parent_stage, children = setup_success()
        child_id, _child, child_stage = children[0]
        child_original = m.lifecycle_plan_path(child_id).read_bytes()
        damage(m.lifecycle_plan_path(child_id), "cleanupReceipts", "bad")
        with patch.object(m, "remove_plan_container", return_value=ABSENT):
            broken = recover(number=1)
        assert broken[0:2] == ("return", 3), broken
        m.lifecycle_plan_path(child_id).write_bytes(child_original)
        shutil.rmtree(child_stage)
        with patch.object(m, "remove_plan_container", return_value=ABSENT):
            restored = recover(number=1)
        assert restored[0:2] == ("return", 0), restored
        stored = read_json(m.attempt_path(1))
        assert stored["settled"] is True and stored["reservationHeld"] is False
        assert child_stage.is_dir() is False
        return {"broken": 3, "restored": 0, "settled": True}


@check("broken-relationship-is-not-guessed",
       "a malformed parent list is not guessed; an explicit reverse link is still held")
def broken_relationship():
    with Sandbox():
        _parent, _parent_stage, children = setup_success()
        child_id, _child, _child_stage = children[0]
        raw = damage(m.attempt_path(1), "associatedPrepareIds", "not-a-list")
        calls = []
        with patch.object(m, "remove_plan_container",
                          side_effect=lambda plan: calls.append(plan) or ABSENT):
            result = recover(number=1)
        assert result[0:2] == ("return", 3), result
        assert not calls
        assert_unchanged(m.attempt_path(1), raw)
        assert hold_state(m.lifecycle_plan_path(child_id))[0] is True
        _code, view, _err = query(number=1)
        assert view["recordState"] == "invalid"
        assert view["effectiveReservationHeld"] is True
        assert view["recordIssues"]
        return {"exit": 3, "parentPreserved": True, "reverseLinkHeld": True, "calls": 0}


@check("receipt-append-never-coerces-or-overwrites-damage",
       "receipt history rejects strings/objects and preserves compatible rows")
def receipt_append():
    outcome = {"state": "confirmed", "confirmed": True,
               "checkedAt": "1970-01-01T00:00:00+00:00",
               "resourceCreationPhase": None}
    existing = [{"state": "incomplete", "confirmed": False,
                 "checkedAt": "1970-01-01T00:00:00+00:00",
                 "resourceCreationPhase": None, "extraCompatible": True}]
    rows = m._append_cleanup_receipt(existing, outcome)
    assert rows[0].get("extraCompatible") is True
    assert rows[-1]["state"] == "confirmed"
    for bad in ("damaged-history", {"bad": True}, [7]):
        try:
            m._append_cleanup_receipt(bad, outcome)
        except m.RecordValidationError:
            pass
        else:
            raise AssertionError(("history was coerced", type(bad).__name__))
    return {"rows": len(rows), "unknownKeysPreserved": True}


@check("record-state-and-issues-contract",
       "recordState values and recordIssues reason strings are explicit")
def state_contract():
    with Sandbox():
        reserve()
        base = read_json(m.attempt_path(1))
        missing = dict(base)
        missing.pop("resourceIntent", None)
        assert m.classify_attempt_record(missing)["recordState"] == "legacy"
        empty = dict(base)
        empty.update({"resourceIntent": {}, "resourceIdentity": {},
                      "cleanupReceipts": [], "cleanup": {}, "cleanupCheck": {}})
        assert m.classify_attempt_record(empty)["recordState"] == "valid"
        bad = dict(base)
        bad["resourceIntent"] = []
        classification = m.classify_attempt_record(bad)
        assert classification["recordState"] == "invalid"
        assert isinstance(classification["recordIssues"], list)
        assert classification["recordIssues"]
        assert all(type(item) is str for item in classification["recordIssues"])
        unreadable = m._unreadable_result("permission-denied")
        assert unreadable["recordState"] == "unreadable"
        assert unreadable["effectiveReservationHeld"] is True
        assert unreadable["effectiveCleanupConfirmed"] is False
        return {"states": ["valid", "legacy", "invalid", "unreadable"]}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "checks" /
                                             "record-validation-results.json"))
    args = parser.parse_args(argv)
    for item in list(CHECKS):
        if "deferred" in item:
            item["invoke"]()
    results = [item for item in CHECKS if "deferred" not in item]
    failed = [item["id"] for item in results if not item["passed"]]
    payload = {
        "kind": "stdlib-cli-record-validation-focused-checks",
        "version": 1,
        "protocolRevision": 3,
        "state": "pending-codex-review",
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "admissionIssued": False,
        "formalTargets": "0/16",
        "r3": "blocked",
        "results": results,
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": failed,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                   encoding="utf-8")
    print(json.dumps({"total": payload["total"], "passed": payload["passed"],
                      "failed": failed}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
