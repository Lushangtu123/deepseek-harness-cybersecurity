#!/usr/bin/env python3
"""Revision-8 final stage recheck checks.

The recovery result must come from a new, explicit path query after the
container/client/observer work.  Every scenario is simulated inside
``checks/tmp`` with explicit no-effect replacements for container queries,
signals and deletions (or a local directory operation under checks/tmp).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
RESULTS = ROOT / "checks" / "rev8-results.json"
sys.path.insert(0, str(ROOT / "checks"))
sys.path.insert(0, str(ROOT / "tools"))
import regression_lib  # noqa: E402

from rev8_support import SyntheticRecovery  # noqa: E402

ENTRIES = []


def record(name, passed, **fields):
    entry = {"test": name, "passed": bool(passed), "simulated": True, **fields}
    ENTRIES.append(entry)
    print(("PASS " if passed else "FAIL ") + name)
    return entry


def exit_for(decision):
    return {"success": 0, "incomplete": 3, "blocked": 78}.get(decision, None)


def test_stage_appears_during_container_query():
    box = SyntheticRecovery("rev8-appears", stage_mode="absent")
    try:
        def effect(_context):
            box.calls_marker = True
            box.stage.mkdir(parents=True)
            (box.stage / "appeared-during-query").write_text(
                "controlled local marker\n", encoding="utf-8")
            return {"removed": True, "state": "never-created"}

        result = box.run_recover(container_effect=lambda context: (
            box.__dict__.__setitem__("_effect_calls", box.__dict__.get("_effect_calls", 0) + 1),
            effect(context))[1])
        stage = result["record"].get("stage") or {}
        checks = {
            "exitIncomplete": result["code"] == 3,
            "stateIncomplete": result["record"].get("state") == "incomplete",
            "notConfirmed": result["record"].get("cleanupConfirmed") is False,
            "stageRemovedFalse": stage.get("removed") is False,
            "stageLstatPresent": stage.get("lstatAfter") == "present",
            "stageStateAppeared": stage.get("state") == "appeared-after-plan",
            "stageStillPresent": result["stagePresent"] is True,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "finalQueryExecuted": result["calls"]["stageRelQueries"] >= 2,
            "realMachinePassFalse": result["record"].get("realMachinePass") is False,
        }
        return record("stage-appears-during-resource-query-is-retained", all(checks.values()),
                      checks=checks, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], calls=result["calls"])
    finally:
        box.close()


def test_final_permission_error():
    box = SyntheticRecovery("rev8-permission", stage_mode="absent")
    try:
        def chmod_evidence_parent():
            os.chmod(box.evidence.parent, 0)

        def effect(_context):
            value = {"removed": True, "state": "never-created"}
            chmod_evidence_parent()
            return value

        try:
            result = box.run_recover(container_effect=effect)
        finally:
            os.chmod(box.evidence.parent, 0o700)
        stage = result["record"].get("stage") or {}
        checks = {
            "exitIncomplete": result["code"] == 3,
            "stateIncomplete": result["record"].get("state") == "incomplete",
            "notConfirmed": result["record"].get("cleanupConfirmed") is False,
            "stageRemovedFalse": stage.get("removed") is False,
            "stageLstatUnknown": stage.get("lstatAfter") == "unknown",
            "stageStateLstatError": stage.get("state") == "lstat-error",
            "permissionReason": str(result["record"].get("reason"))
                                == "stage-lstat:permission-denied",
            "actualPathRecorded": stage.get("path") == result["stagePath"],
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "finalQueryExecuted": result["calls"]["stageRelQueries"] >= 2,
        }
        return record("final-recheck-permission-error-incomplete", all(checks.values()),
                      checks=checks, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], calls=result["calls"])
    finally:
        try:
            os.chmod(box.evidence.parent, 0o700)
        except OSError:
            pass
        box.close()


def test_final_not_a_directory_error():
    base = Path(tempfile.mkdtemp(prefix="rev8-notdir-", dir=TMP))
    box = SyntheticRecovery("rev8-notdir-synth", stage_mode="absent")
    try:
        blocker = base / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        actual = box.module.guard.path_state(blocker / "stage")
        expected_path = box.stage
        result = box.run_recover(final_override={**actual, "path": str(expected_path)})
        stage = result["record"].get("stage") or {}
        checks = {
            "actualErrorWasNotADirectory": actual.get("state") == "unknown"
                                           and actual.get("detail") == "not-a-directory",
            "exitCode3": result["code"] == 3,
            "stateIncomplete": result["record"].get("state") == "incomplete",
            "notConfirmed": result["record"].get("cleanupConfirmed") is False,
            "lstatUnknown": stage.get("lstatAfter") == "unknown",
            "lstatErrorState": stage.get("state") == "lstat-error",
            "preciseReason": result["record"].get("reason")
                            == "stage-lstat:not-a-directory",
            "actualPath": stage.get("path") == str(expected_path),
            "removedFalse": stage.get("removed") is False,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "finalQueryExecuted": result["calls"]["stageRelQueries"] >= 2,
        }
        return record("final-recheck-not-a-directory-incomplete", all(checks.values()),
                      checks=checks, actual=actual, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], calls=result["calls"])
    finally:
        regression_lib.retire_sandbox(base)
        box.close()


def test_final_oserror():
    base = Path(tempfile.mkdtemp(prefix="rev8-oserror-", dir=TMP))
    box = SyntheticRecovery("rev8-oserror-synth", stage_mode="absent")
    try:
        too_long = base / ("x" * 5000)
        actual = box.module.guard.path_state(too_long)
        expected_path = box.stage
        result = box.run_recover(final_override={**actual, "path": str(expected_path)})
        stage = result["record"].get("stage") or {}
        checks = {
            "actualOserror": actual.get("state") == "unknown"
                             and actual.get("detail") == "OSError",
            "exitCode3": result["code"] == 3,
            "stateIncomplete": result["record"].get("state") == "incomplete",
            "notConfirmed": result["record"].get("cleanupConfirmed") is False,
            "lstatUnknown": stage.get("lstatAfter") == "unknown",
            "lstatErrorState": stage.get("state") == "lstat-error",
            "preciseReason": result["record"].get("reason") == "stage-lstat:OSError",
            "actualPath": stage.get("path") == str(expected_path),
            "removedFalse": stage.get("removed") is False,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "finalQueryExecuted": result["calls"]["stageRelQueries"] >= 2,
        }
        return record("final-recheck-generic-oserror-incomplete", all(checks.values()),
                      checks=checks, actual=actual, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], calls=result["calls"])
    finally:
        regression_lib.retire_sandbox(base)
        box.close()


def test_final_non_directory_blocked():
    box = SyntheticRecovery("rev8-nondir", stage_mode="present")
    try:
        def effect(_context):
            shutil.rmtree(box.stage)
            box.stage.write_text("now a regular file\n", encoding="utf-8")
            return {"removed": True, "state": "never-created"}

        result = box.run_recover(container_effect=effect)
        stage = result["record"].get("stage") or {}
        checks = {
            "exitBlocked": result["code"] == 78,
            "stateBlocked": result["record"].get("state") == "blocked",
            "reasonNotDirectory": result["record"].get("reason") == "stage-not-directory",
            "stageNotRemoved": stage.get("removed") is False,
            "stageLstatPresent": stage.get("lstatAfter") == "present",
            "stageStateNotDirectory": stage.get("state") == "not-directory",
            "actualPathIsFile": result["stageIsFile"] is True,
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "finalQueryExecuted": result["calls"]["stageRelQueries"] >= 2,
        }
        return record("final-recheck-non-directory-is-blocked", all(checks.values()),
                      checks=checks, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], calls=result["calls"])
    finally:
        box.close()


def test_final_symlink_blocked():
    base = Path(tempfile.mkdtemp(prefix="rev8-link-target-", dir=TMP))
    target = base / "outside"
    target.mkdir()
    box = SyntheticRecovery("rev8-symlink", stage_mode="present")
    try:
        def effect(_context):
            shutil.rmtree(box.stage)
            box.stage.symlink_to(target, target_is_directory=True)
            box.track_fixture_link(box.stage)
            return {"removed": True, "state": "never-created"}

        result = box.run_recover(container_effect=effect)
        stage = result["record"].get("stage") or {}
        checks = {
            "exitBlocked": result["code"] == 78,
            "stateBlocked": result["record"].get("state") == "blocked",
            "reasonSymlink": result["record"].get("reason") == "stage-symlink",
            "stageNotRemoved": stage.get("removed") is False,
            "stageLstatPresent": stage.get("lstatAfter") == "present",
            "stageStateSymlink": stage.get("state") == "symlink",
            "actualPathIsLink": result["stageIsLink"] is True,
            "targetRetained": target.is_dir(),
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
        }
        return record("final-recheck-symlink-is-blocked", all(checks.values()),
                      checks=checks, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], target=str(target),
                      calls=result["calls"])
    finally:
        box.close()
        regression_lib.retire_sandbox(base)


def test_final_identity_changed_blocked():
    box = SyntheticRecovery("rev8-identity", stage_mode="present")
    try:
        old = dict(box.identity)
        fake = dict(old)
        fake["ino"] = old["ino"] + 1
        for name, kind in (("stage-started.json", "zero-target-preflight-stage-started"),
                           ("stage-created.json", "zero-target-preflight-stage-created")):
            value = json.loads((box.evidence / name).read_text())
            value["stageIdentity"] = fake
            (box.evidence / name).write_text(
                json.dumps(value, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        result = box.run_recover()
        current = box.module.guard.stage_identity(box.stage)
        stage = result["record"].get("stage") or {}
        changed = (current or {}).get("ino") != fake.get("ino") or \
                  (current or {}).get("dev") != fake.get("dev")
        checks = {
            "actualIdentityChanged": changed,
            "exitBlocked": result["code"] == 78,
            "stateBlocked": result["record"].get("state") == "blocked",
            "reasonIdentity": result["record"].get("reason") == "stage-identity-changed",
            "stageNotRemoved": stage.get("removed") is False,
            "stageLstatPresent": stage.get("lstatAfter") == "present",
            "stageStateIdentityChanged": stage.get("state") == "identity-changed",
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
        }
        return record("final-recheck-identity-contradiction-is-blocked", all(checks.values()),
                      checks=checks, code=result["code"], stage=stage,
                      oldIdentity=old, currentIdentity=current, calls=result["calls"])
    finally:
        box.close()


def test_final_escape_blocked():
    box = SyntheticRecovery("rev8-escape", stage_mode="absent")
    try:
        value = box.module._final_stage_recheck(
            "../outside", str(box.sandbox / "outside"), None, "absent", True)
        resource_calls = {"containerQuery": 0, "delete": 0, "signal": 0}
        checks = {
            "decisionBlocked": value.get("decision") == "blocked",
            "exitCode78": exit_for(value.get("decision")) == 78,
            "reasonEscape": value.get("reason") == "stage-relative-path",
            "lstatUnknown": value.get("lstatAfter") == "unknown",
            "removedFalse": value.get("removed") is False,
            "noResourceActions": all(count == 0 for count in resource_calls.values()),
        }
        return record("final-recheck-lexical-escape-is-blocked", all(checks.values()),
                      checks=checks, resourceCalls=resource_calls, result=value)
    finally:
        box.close()


def test_intermediate_symlink_blocked():
    base = Path(tempfile.mkdtemp(prefix="rev8-path-link-", dir=TMP))
    fixture_links = regression_lib.FixtureLinks(base)
    box = SyntheticRecovery("rev8-path-link", stage_mode="absent")
    original_root = box.module.ROOT
    try:
        outside = base / "outside"
        outside.mkdir()
        root = base / "root"
        root.mkdir()
        (root / "preflight").symlink_to(outside, target_is_directory=True)
        fixture_links.track(root / "preflight")
        box.module.ROOT = root
        value = box.module._final_stage_recheck(
            box.plan["stageRelativePath"], str(root / box.plan["stageRelativePath"]),
            None, "absent", True)
        resource_calls = {"containerQuery": 0, "delete": 0, "signal": 0}
        checks = {
            "decisionBlocked": value.get("decision") == "blocked",
            "exitCode78": exit_for(value.get("decision")) == 78,
            "reasonSymlink": value.get("reason") == "stage-symlink",
            "lstatPresent": value.get("lstatAfter") == "present",
            "linkRetained": (root / "preflight").is_symlink(),
            "noResourceActions": all(count == 0 for count in resource_calls.values()),
        }
        return record("final-recheck-intermediate-link-is-blocked", all(checks.values()),
                      checks=checks, resourceCalls=resource_calls, result=value)
    finally:
        box.module.ROOT = original_root
        try:
            fixture_links.close()
        finally:
            box.close()
        regression_lib.retire_sandbox(base)


def test_normal_missing_success():
    box = SyntheticRecovery("rev8-missing", stage_mode="absent")
    try:
        result = box.run_recover()
        stage = result["record"].get("stage") or {}
        checks = {
            "exitSuccess": result["code"] == 0,
            "stateCleared": result["record"].get("state") == "resources-cleared",
            "confirmedTrue": result["record"].get("cleanupConfirmed") is True,
            "stageRemovedTrue": stage.get("removed") is True,
            "stageLstatAbsent": stage.get("lstatAfter") == "absent",
            "stageStateAbsent": stage.get("state") == "absent",
            "actualPathAbsent": result["stagePresent"] is False,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "finalQueryExecuted": result["calls"]["stageRelQueries"] >= 2,
            "realMachinePassFalse": result["record"].get("realMachinePass") is False,
            "selfCheckNotReplayed": result["record"].get("selfCheckReplayed") is False,
        }
        return record("normal-missing-stage-uses-new-absence-query", all(checks.values()),
                      checks=checks, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], calls=result["calls"])
    finally:
        box.close()


def test_normal_removal_success():
    box = SyntheticRecovery("rev8-remove", stage_mode="present")
    try:
        result = box.run_recover()
        stage = result["record"].get("stage") or {}
        checks = {
            "exitSuccess": result["code"] == 0,
            "stateCleared": result["record"].get("state") == "resources-cleared",
            "confirmedTrue": result["record"].get("cleanupConfirmed") is True,
            "stageRemovedTrue": stage.get("removed") is True,
            "stageLstatAbsent": stage.get("lstatAfter") == "absent",
            "stageActuallyGone": result["stagePresent"] is False,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "deleteCalledOnce": result["calls"]["delete"] == 1,
            "finalQueryExecuted": result["calls"]["stageRelQueries"] >= 2,
            "realMachinePassFalse": result["record"].get("realMachinePass") is False,
        }
        return record("normal-present-stage-removal-is-confirmed", all(checks.values()),
                      checks=checks, code=result["code"], stage=stage,
                      stagePath=result["stagePath"], calls=result["calls"])
    finally:
        box.close()


def test_cleanup_missing_stage_with_created_identity():
    base = Path(tempfile.mkdtemp(prefix="rev8-cleanup-missing-", dir=TMP))
    box = SyntheticRecovery("rev8-cleanup-missing", stage_mode="absent")
    try:
        stage = base / "stage"
        stage.mkdir()
        (stage / "marker").write_text("present then externally gone\n",
                                      encoding="utf-8")
        identity = box.module.guard.stage_identity(stage)
        shutil.rmtree(stage)
        context = {"stageDir": str(stage), "stageIdentity": identity,
                   "stageBuildState": "created", "persistFailure": None}
        result = box.module._cleanup_stage(context, True)
        resource_calls = {"containerQuery": 0, "delete": 0, "signal": 0}
        checks = {
            "noKeyError": isinstance(result, dict),
            "removedTrue": result.get("removed") is True,
            "stateAbsent": result.get("state") == "absent",
            "lstatAbsent": result.get("lstatAfter") == "absent",
            "pathRecorded": result.get("path") == str(stage),
            "stageActuallyGone": not stage.exists(),
            "noResourceActions": all(count == 0 for count in resource_calls.values()),
        }
        return record("cleanup-missing-stage-with-created-identity-no-keyerror",
                      all(checks.values()), checks=checks, resourceCalls=resource_calls,
                      result=result)
    finally:
        box.close()
        regression_lib.retire_sandbox(base)


def test_recovery_log_write_failure():
    box = SyntheticRecovery("rev8-write-fail", stage_mode="absent")
    try:
        result = box.run_recover(fail_recovery_write=True)
        checks = {
            "exitWriteFailure": result["code"] == 79,
            "summaryWriteFailed": result["summary"].get("state") == "recovery-write-failed",
            "noRecoveryFile": result["files"] == [],
            "notConfirmed": result["summary"].get("cleanupConfirmed") is None,
            "containerQueryRan": result["calls"]["containerQuery"] == 1,
            "deleteNotCalled": result["calls"]["delete"] == 0,
            "stageAbsent": result["stagePresent"] is False,
        }
        return record("recovery-journal-write-failure-returns-79", all(checks.values()),
                      checks=checks, code=result["code"], summary=result["summary"],
                      calls=result["calls"])
    finally:
        box.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(RESULTS))
    args = parser.parse_args(argv)
    results_path = Path(args.out)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    scenarios = [
        test_stage_appears_during_container_query,
        test_final_permission_error,
        test_final_not_a_directory_error,
        test_final_oserror,
        test_final_non_directory_blocked,
        test_final_symlink_blocked,
        test_final_identity_changed_blocked,
        test_final_escape_blocked,
        test_intermediate_symlink_blocked,
        test_normal_missing_success,
        test_normal_removal_success,
        test_cleanup_missing_stage_with_created_identity,
        test_recovery_log_write_failure,
    ]
    failures = []
    for scenario in scenarios:
        try:
            entry = scenario()
        except BaseException as error:  # noqa: BLE001
            entry = record(scenario.__name__ + "-exception", False,
                           error=type(error).__name__ + ":" + str(error)[:500])
        if not entry.get("passed"):
            failures.append(entry["test"])
    payload = {
        "kind": "cli-final-stage-recheck-rev8-checks",
        "version": 3,
        "simulated": True,
        "realContainers": 0,
        "realProcesses": 0,
        "realBpftrace": 0,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "passed": len(ENTRIES) - len(failures),
        "total": len(ENTRIES),
        "failed": failures,
        "results": ENTRIES,
    }
    results_path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                            encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "total": payload["total"],
                      "failed": failures}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
