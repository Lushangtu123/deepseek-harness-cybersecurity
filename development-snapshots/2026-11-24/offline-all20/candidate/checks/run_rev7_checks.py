#!/usr/bin/env python3
"""Revision-7 recovery binding and tri-state path checks.

Every scenario is recorded/simulated.  Tests run only under ``checks/tmp`` and
use the recording Docker/bpftrace shims; no real container, bpftrace, target or
fixture import is performed.  Results are written with ``simulated: true``.
"""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
RESULTS = ROOT / "checks" / "rev7-results.json"
sys.path.insert(0, str(ROOT / "checks"))
sys.path.insert(0, str(ROOT / "tools"))

import regression_lib  # noqa: E402
from regression_lib import Sandbox, sha  # noqa: E402

import preflight_verify  # noqa: E402
import resource_guard as guard  # noqa: E402
import zero_target_preflight as preflight  # noqa: E402

ENTRIES = []


def record(name, passed, **fields):
    entry = {"test": name, "passed": bool(passed), "simulated": True, **fields}
    ENTRIES.append(entry)
    print(("PASS " if passed else "FAIL ") + name)
    return entry


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=1) + "\n",
                          encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ready_box(name):
    box = Sandbox(name)
    box.write_preflight_license()
    result = box.preflight()
    if result.returncode != 0:
        raise AssertionError("preflight failed: %s %s"
                             % (result.returncode, result.stderr[-800:]))
    return box


class ModuleSandbox:
    """Point the imported tool module at one checks/tmp sandbox."""

    NAMES = ("ROOT", "PREFLIGHT_ROOT", "EVIDENCE_ROOT", "CLAIMS_ROOT",
             "RECOVERIES_ROOT", "LOCK_PATH", "MANIFEST", "LICENSE", "REVIEW",
             "TOOLS", "PROFILE")

    def __init__(self, box):
        self.box = box
        self.originals = {}

    def __enter__(self):
        box = self.box
        values = {
            "ROOT": box.path,
            "PREFLIGHT_ROOT": box.path / "preflight",
            "EVIDENCE_ROOT": box.path / "preflight" / "evidence",
            "CLAIMS_ROOT": box.path / "preflight" / "claims",
            "RECOVERIES_ROOT": box.path / "preflight" / "recoveries",
            "LOCK_PATH": box.path / "preflight" / ".preflight.lock",
            "MANIFEST": box.path / "protocol-manifest.json",
            "LICENSE": box.path / "codex-review" / "preflight-admission.json",
            "REVIEW": box.path / "codex-review" / "source-review-receipt.json",
            "TOOLS": box.path / "tools",
            "PROFILE": box.path / "tools" / "observer-profile.lock.json",
        }
        for name in self.NAMES:
            self.originals[name] = getattr(preflight, name)
            setattr(preflight, name, values[name])
        return self

    def __exit__(self, *_exc):
        for name, value in self.originals.items():
            setattr(preflight, name, value)
        return False


class ActionCounters:
    """Record every cleanup/signal/delete entry point without performing it."""

    def __init__(self):
        self.calls = {"container": 0, "process": 0, "stage": 0,
                      "stopGroup": 0, "removeContainer": 0,
                      "cleanupStage": 0, "docker": 0}
        self.handoffs = []
        self.originals = {}

    def __enter__(self):
        for name in ("_recover_container", "_recover_process", "_recover_stage",
                     "_cleanup_container"):
            self.originals[("preflight", name)] = getattr(preflight, name)
        for name in ("stop_group", "remove_container_verified",
                     "cleanup_stage", "docker"):
            self.originals[("guard", name)] = getattr(guard, name)
        self._install()
        return self

    def _install(self):
        def container(*args, **kwargs):
            self.calls["container"] += 1
            self.handoffs.append({"kind": "container"})
            return {"removed": True, "state": "recorder-no-effect"}

        def process(*args, **kwargs):
            self.calls["process"] += 1
            self.handoffs.append({"kind": "process"})
            return {"state": "exited", "proof": "recorder-no-effect"}

        def stage(*args, **kwargs):
            self.calls["stage"] += 1
            self.handoffs.append({"kind": "stage"})
            return {"removed": True, "lstatAfter": "absent",
                    "state": "recorder-no-effect"}

        def cleanup_container(*args, **kwargs):
            self.calls["container"] += 1
            self.handoffs.append({"kind": "container-plan"})
            return {"removed": True, "state": "recorder-no-effect"}

        preflight._recover_container = container
        preflight._recover_process = process
        preflight._recover_stage = stage
        preflight._cleanup_container = cleanup_container
        guard.stop_group = lambda *args, **kwargs: self._bump("stopGroup") or {
            "stopped": True, "state": "exited"}
        guard.remove_container_verified = lambda *args, **kwargs: self._bump(
            "removeContainer") or {"removed": True, "state": "recorder-no-effect"}
        guard.cleanup_stage = lambda *args, **kwargs: self._bump(
            "cleanupStage") or {"removed": True, "state": "recorder-no-effect"}
        guard.docker = lambda *args, **kwargs: self._bump("docker") or None

    def _bump(self, name):
        self.calls[name] += 1
        return 0

    def __exit__(self, *_exc):
        for (owner, name), value in self.originals.items():
            if owner == "preflight":
                setattr(preflight, name, value)
            else:
                setattr(guard, name, value)
        return False

    def total(self):
        return sum(self.calls.values())


def run_recover_inprocess(box):
    """Run recover against the sandbox with effect-free cleanup recorders."""
    with ModuleSandbox(box), ActionCounters() as counters:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = preflight.recover(box.preflight_id)
    files = sorted(box.preflight_evidence().glob("recovery-*.json"))
    value = read_json(files[-1]) if files else {}
    return code, value, counters, files


def mutate_journal(path, mutate):
    value = read_json(path)
    mutate(value)
    write_json(path, value)


# ------------------------------------------------------------- tri-state paths
def test_permission_error_retained():
    base = Path(tempfile.mkdtemp(prefix="rev7-perm-", dir=TMP))
    barrier = base / "unreadable"
    stage = barrier / "stage"
    stage.mkdir(parents=True)
    (stage / "marker").write_text("present\n", encoding="utf-8")
    identity = guard.stage_identity(stage)
    with regression_lib.sampling_fault_window():
        barrier.chmod(0)
        context = {"stageDir": str(stage), "stageIdentity": identity,
                   "stageBuildState": "created", "persistFailure": None}
        error = None
        try:
            try:
                os.lstat(stage)
            except OSError as raised:
                error = type(raised).__name__
            result = preflight._cleanup_stage(context, True)
        finally:
            barrier.chmod(0o700)
    still_there = stage.is_dir()
    regression_lib.retire_sandbox(base)
    passed = (error == "PermissionError"
              and result.get("removed") is False
              and result.get("lstatAfter") == "unknown"
              and still_there)
    return record("stage-permission-error-is-unknown-and-retained", passed,
                  lstatError=error, result=result, stageStillPresent=still_there)


def test_not_a_directory_unknown():
    base = Path(tempfile.mkdtemp(prefix="rev7-notdir-", dir=TMP))
    blocker = base / "file"
    blocker.write_text("not a directory\n", encoding="utf-8")
    stage = blocker / "stage"
    context = {"stageDir": str(stage),
               "stageIdentity": {"dev": 1, "ino": 1, "path": str(stage)},
               "stageBuildState": "created", "persistFailure": None}
    error = None
    try:
        try:
            os.lstat(stage)
        except OSError as raised:
            error = type(raised).__name__
        result = preflight._cleanup_stage(context, True)
    finally:
        regression_lib.retire_sandbox(base)
    passed = (error == "NotADirectoryError"
              and result.get("removed") is False
              and result.get("lstatAfter") == "unknown")
    return record("stage-not-a-directory-is-unknown", passed,
                  lstatError=error, result=result)


def test_removed_but_present_not_confirmed():
    base = Path(tempfile.mkdtemp(prefix="rev7-present-", dir=TMP))
    stage = base / "stage"
    stage.mkdir()
    (stage / "marker").write_text("present\n", encoding="utf-8")
    context = {"stageDir": str(stage), "stageIdentity": guard.stage_identity(stage),
               "stageBuildState": "created", "persistFailure": None,
               "client": {"spawnState": "not-started"},
               "observer": {"spawnState": "not-started"},
               "container": {"createState": "not-attempted",
                             "containerName": "stdlib-cli-preflight-0123456789abcdef",
                             "tag": "0123456789abcdef"}}
    calls = {"nameQuery": 0, "tagQuery": 0, "delete": 0, "lstat": 0,
             "signal": 0, "realDocker": 0}
    original_lookup = guard.container_lookup
    original_tag = guard.container_tag_lookup
    original_cleanup = guard.cleanup_stage
    original_stage_lstat = preflight._stage_lstat
    original_stop = guard.stop_group
    original_docker = guard.docker

    def lookup(_identifier):
        calls["nameQuery"] += 1
        return {"state": "absent", "detail": "synthetic-name-absent"}

    def tag_lookup(_tag):
        calls["tagQuery"] += 1
        return {"state": "absent", "rows": []}

    def delete(_path, _identity):
        calls["delete"] += 1
        return {"removed": True, "state": "removed"}

    def stage_lstat(path):
        calls["lstat"] += 1
        return original_stage_lstat(path)

    def stop(*_args, **_kwargs):
        calls["signal"] += 1
        return {"stopped": True, "state": "exited"}

    def real_docker(*_args, **_kwargs):
        calls["realDocker"] += 1
        raise AssertionError("real Docker must not be queried")

    guard.container_lookup = lookup
    guard.container_tag_lookup = tag_lookup
    guard.cleanup_stage = delete
    guard.stop_group = stop
    guard.docker = real_docker
    preflight._stage_lstat = stage_lstat
    try:
        cleanup = preflight.cleanup_resources(context)
    finally:
        guard.container_lookup = original_lookup
        guard.container_tag_lookup = original_tag
        guard.cleanup_stage = original_cleanup
        guard.stop_group = original_stop
        guard.docker = original_docker
        preflight._stage_lstat = original_stage_lstat
    present = stage.is_dir()
    checks = {
        "containerAbsenceQueriesRan": calls["nameQuery"] == 1 and calls["tagQuery"] == 1,
        "deleteStubCalled": calls["delete"] == 1,
        "finalLstatExecuted": calls["lstat"] >= 2,
        "noSignal": calls["signal"] == 0,
        "noRealDocker": calls["realDocker"] == 0,
        "notConfirmed": cleanup.get("confirmed") is False,
        "stageNotRemoved": (cleanup.get("stage") or {}).get("removed") is False,
        "stageLstatPresent": (cleanup.get("stage") or {}).get("lstatAfter") == "present",
        "stageActuallyPresent": present,
    }
    passed = all(checks.values())
    regression_lib.retire_sandbox(base)
    return record("removed-true-but-final-lstat-present-is-not-confirmed", passed,
                  checks=checks, calls=calls, cleanup=cleanup,
                  stageActuallyPresent=present)


def test_final_recheck_unknown():
    base = Path(tempfile.mkdtemp(prefix="rev7-final-", dir=TMP))
    stage = base / "stage"
    stage.mkdir()
    context = {"stageDir": str(stage), "stageIdentity": guard.stage_identity(stage),
               "stageBuildState": "created", "persistFailure": None}
    original_lstat = preflight._stage_lstat
    original_cleanup = guard.cleanup_stage
    sequence = {"count": 0}

    def fake_lstat(path):
        sequence["count"] += 1
        if sequence["count"] == 1:
            return original_lstat(path)
        return {"state": "unknown", "detail": "synthetic-final-recheck"}

    guard.cleanup_stage = lambda *args, **kwargs: {"removed": True, "state": "removed"}
    preflight._stage_lstat = fake_lstat
    try:
        result = preflight._cleanup_stage(context, True)
    finally:
        preflight._stage_lstat = original_lstat
        guard.cleanup_stage = original_cleanup
    regression_lib.retire_sandbox(base)
    passed = (result.get("removed") is False
              and result.get("lstatAfter") == "unknown"
              and sequence["count"] >= 2)
    return record("final-lstat-unknown-is-not-confirmed", passed,
                  result=result, lstatCalls=sequence["count"])


def test_path_reappears_after_delete():
    base = Path(tempfile.mkdtemp(prefix="rev7-reappear-", dir=TMP))
    stage = base / "stage"
    stage.mkdir()
    (stage / "old").write_text("old\n", encoding="utf-8")
    identity = guard.stage_identity(stage)
    original = guard.cleanup_stage

    def remove_then_recreate(path, value):
        shutil.rmtree(path)
        os.makedirs(path)
        (Path(path) / "new").write_text("new\n", encoding="utf-8")
        return {"removed": True, "state": "removed"}

    guard.cleanup_stage = remove_then_recreate
    try:
        result = preflight._recover_stage(str(stage), identity, True, None)
    finally:
        guard.cleanup_stage = original
    reappeared = stage.is_dir() and (stage / "new").is_file()
    regression_lib.retire_sandbox(base)
    passed = (result.get("removed") is False
              and result.get("lstatAfter") == "present"
              and result.get("state") == "still-present"
              and reappeared)
    return record("stage-reappears-after-delete-not-confirmed", passed,
                  result=result, reappeared=reappeared)


def test_normal_absence():
    base = Path(tempfile.mkdtemp(prefix="rev7-absent-", dir=TMP))
    missing = base / "never-created"
    context = {"stageDir": str(missing), "stageIdentity": None,
               "stageBuildState": "not-created", "persistFailure": None}
    cleanup = preflight._cleanup_stage(context, True)
    recover = preflight._recover_stage(str(missing), None, True, None)
    regression_lib.retire_sandbox(base)
    passed = (cleanup.get("removed") is True
              and cleanup.get("lstatAfter") == "absent"
              and recover.get("removed") is True
              and recover.get("lstatAfter") == "absent")
    return record("explicit-lstat-absence-is-confirmed", passed,
                  cleanup=cleanup, recover=recover)


def test_normal_removal():
    base = Path(tempfile.mkdtemp(prefix="rev7-remove-", dir=TMP))
    stage = base / "stage"
    (stage / "tools").mkdir(parents=True)
    (stage / "tools" / "fixture.txt").write_text("simulated\n", encoding="utf-8")
    context = {"stageDir": str(stage), "stageIdentity": guard.stage_identity(stage),
               "stageBuildState": "created", "persistFailure": None}
    result = preflight._cleanup_stage(context, True)
    gone = not stage.exists()
    regression_lib.retire_sandbox(base)
    passed = (result.get("removed") is True
              and result.get("lstatAfter") == "absent"
              and gone)
    return record("normal-stage-removal-has-absent-recheck", passed,
                  result=result, stageGone=gone)


# ------------------------------------------------------------ ownership binding
MISMATCHES = (
    ("id", "preflight-intent.json",
     lambda value: value.__setitem__("preflightId", "b" * 32),
     "intent-preflight-id"),
    ("kind", "preflight-intent.json",
     lambda value: value.__setitem__("kind", "foreign-intent"),
     "intent-kind"),
    ("role", "process-client-identity.json",
     lambda value: value.__setitem__("role", "observer"),
     "process-client-identity-role"),
    ("tag", "container-created.json",
     lambda value: value.__setitem__("tag", "f" * 16),
     "container-created-tag"),
    ("name", "container-created.json",
     lambda value: value.__setitem__("containerName", "foreign-container"),
     "container-created-name"),
    ("image", "container-created.json",
     lambda value: value.__setitem__("imageId", "sha256:" + "0" * 64),
     "container-created-image"),
    ("stage-path", "stage-created.json",
     lambda value: value.__setitem__("stageDir", "/tmp/foreign-stage"),
     "stage-created-stage-dir"),
    ("observer-path", "process-observer-intent.json",
     lambda value: value["argv"].__setitem__(2, "/tmp/foreign-observer.bt"),
     "observer-intent-argv"),
    ("container-id", "container-created.json",
     lambda value: value.__setitem__("containerId", "c" * 64),
     "container-create-id"),
    ("identity", "process-client-identity.json",
     lambda value: value["identity"].__setitem__("pid", 9999),
     "process-client-identity-pid"),
)


def test_mismatch_matrix():
    outcomes = []
    for label, filename, mutate, expected in MISMATCHES:
        box = ready_box("rev7-mismatch-" + label)
        evidence = box.preflight_evidence()
        mutate_journal(evidence / filename, mutate)
        docker_before = len(box.docker_lines())
        code, value, counters, files = run_recover_inprocess(box)
        docker_after = len(box.docker_lines())
        passed = (code == 78
                  and value.get("state") == "blocked"
                  and str(value.get("reason")) == expected
                  and counters.total() == 0
                  and docker_after == docker_before)
        outcomes.append({"case": label, "expectedReason": expected,
                         "reason": value.get("reason"), "code": code,
                         "state": value.get("state"),
                         "calls": counters.calls, "passed": passed,
                         "recoveryFiles": [path.name for path in files]})
        regression_lib.retire_sandbox(box.path)
    passed = all(row["passed"] for row in outcomes)
    return record("ownership-mismatch-matrix-blocked-with-zero-actions", passed,
                  cases=outcomes)


def test_missing_corrupt_and_plan_absent():
    outcomes = {}

    box = ready_box("rev7-missing-log")
    (box.preflight_evidence() / "process-observer-identity.json").unlink()
    code, value, counters, _files = run_recover_inprocess(box)
    outcomes["missing"] = {"code": code, "state": value.get("state"),
                           "reason": value.get("reason"),
                           "calls": counters.calls}
    regression_lib.retire_sandbox(box.path)

    box = ready_box("rev7-corrupt-log")
    (box.preflight_evidence() / "container-created.json").write_text(
        "{not-json\n", encoding="utf-8")
    code, value, counters, _files = run_recover_inprocess(box)
    outcomes["corrupt"] = {"code": code, "state": value.get("state"),
                           "reason": value.get("reason"),
                           "calls": counters.calls}
    regression_lib.retire_sandbox(box.path)

    box = ready_box("rev7-no-plan")
    claim_path = box.path / "preflight" / "claims" / (box.preflight_id + ".json")
    claim = read_json(claim_path)
    claim.pop("resourcePlan", None)
    claim.pop("resourcePlanSha256", None)
    write_json(claim_path, claim)
    claim_before = sha(claim_path)
    code, value, counters, _files = run_recover_inprocess(box)
    outcomes["noPlan"] = {"code": code, "state": value.get("state"),
                          "reason": value.get("reason"),
                          "calls": counters.calls,
                          "claimUnchanged": sha(claim_path) == claim_before,
                          "claimHasPlan": "resourcePlan" in read_json(claim_path)}
    regression_lib.retire_sandbox(box.path)

    passed = (
        outcomes["missing"]["code"] == 3
        and outcomes["missing"]["state"] == "incomplete"
        and outcomes["missing"]["reason"] == "process-observer-identity-missing"
        and sum(outcomes["missing"]["calls"].values()) == 0
        and outcomes["corrupt"]["code"] == 3
        and outcomes["corrupt"]["state"] == "incomplete"
        and str(outcomes["corrupt"]["reason"]).startswith(
            "journal-read:container-created.json")
        and sum(outcomes["corrupt"]["calls"].values()) == 0
        and outcomes["noPlan"]["code"] == 3
        and outcomes["noPlan"]["state"] == "incomplete"
        and outcomes["noPlan"]["reason"] == "claim-resource-plan-missing"
        and sum(outcomes["noPlan"]["calls"].values()) == 0
        and outcomes["noPlan"]["claimUnchanged"]
        and outcomes["noPlan"]["claimHasPlan"] is False
    )
    return record("missing-corrupt-and-plan-absent-stay-unknown", passed,
                  outcomes=outcomes)


# --------------------------------------------------------------- plan binding
def verify(box):
    return preflight_verify.verify_preflight_evidence(
        box.path,
        box.preflight_receipt_path(),
        box.path / "codex-review" / "preflight-admission.json",
        box.path / "codex-review" / "source-review-receipt.json",
        box.path / "protocol-manifest.json",
        box.path / "tools" / "observer-profile.lock.json",
        expected_id=box.preflight_id,
    )


def test_claim_and_receipt_bind_plan():
    box = ready_box("rev7-plan-binding")
    claim_path = box.path / "preflight" / "claims" / (box.preflight_id + ".json")
    claim = read_json(claim_path)
    receipt = read_json(box.preflight_receipt_path())
    evidence = box.preflight_evidence()
    plan = claim.get("resourcePlan")
    plan_sha = claim.get("resourcePlanSha256")
    expected = preflight_verify.resource_plan(box.preflight_id, receipt["tag"])
    checks = {
        "claimPlan": plan == expected,
        "claimPlanSha": plan_sha == guard.digest(expected),
        "claimSha": claim.get("preflightId") == box.preflight_id
                    and receipt.get("claimSha256") == sha(claim_path),
        "receiptPlan": receipt.get("resourcePlan") == plan
                       and receipt.get("resourcePlanSha256") == plan_sha,
        "stageRelative": plan.get("stageRelativePath")
                         == "preflight/evidence/%s/stage-%s"
                         % (box.preflight_id, receipt["tag"]),
        "intentPlan": read_json(evidence / "preflight-intent.json").get(
            "resourcePlan") == plan,
        "stageIntentPlan": read_json(evidence / "stage-intent.json").get(
            "resourcePlan") == plan,
        "containerIntentPlan": read_json(evidence / "container-intent.json").get(
            "resourcePlan") == plan,
        "containerCreatedPlan": read_json(evidence / "container-created.json").get(
            "resourcePlan") == plan,
        "cleanupPlan": read_json(evidence / "cleanup.json").get(
            "resourcePlan") == plan,
    }
    box_result = verify(box)
    checks["verified"] = box_result["claim"]["resourcePlan"] == expected
    passed = all(checks.values())
    regression_lib.retire_sandbox(box.path)
    return record("claim-receipt-and-journals-bind-resource-plan", passed,
                  checks=checks, plan=plan, planSha256=plan_sha)


def test_recovery_record_plan_and_no_receipt_rewrite():
    box = ready_box("rev7-recover-plan")
    receipt_sha = sha(box.preflight_receipt_path())
    docker_before = box.docker_lines()
    result = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "recover", "--preflight-id", box.preflight_id],
        capture_output=True, text=True, env=box.env(), timeout=60,
    )
    files = sorted(box.preflight_evidence().glob("recovery-*.json"))
    value = read_json(files[-1]) if files else {}
    docker_after = box.docker_lines()
    new_creates = sum(1 for line in docker_after[len(docker_before):]
                      if line.startswith("create "))
    new_starts = sum(1 for line in docker_after[len(docker_before):]
                     if line.startswith("start "))
    plan = value.get("resourcePlan") or {}
    receipt_unchanged = sha(box.preflight_receipt_path()) == receipt_sha
    passed = (
        result.returncode == 0
        and value.get("state") == "resources-cleared"
        and value.get("cleanupConfirmed") is True
        and value.get("resourcePlanSha256")
        == preflight_verify.resource_plan_digest(plan)
        and plan.get("stageRelativePath")
        == "preflight/evidence/%s/stage-%s" % (box.preflight_id, value.get("tag"))
        and (value.get("stage") or {}).get("lstatAfter") == "absent"
        and receipt_unchanged
        and new_creates == 0 and new_starts == 0
        and len(files) == 1
    )
    regression_lib.retire_sandbox(box.path)
    return record("recovery-record-binds-plan-and-does-not-rewrite-receipt", passed,
                  recover=result.returncode, recovery=value,
                  recoveryFiles=[path.name for path in files],
                  receiptUnchanged=receipt_unchanged,
                  newCreates=new_creates, newStarts=new_starts)


def resign_receipt(box, mutate):
    receipt_path = box.preflight_receipt_path()
    _claim, completed_path = preflight_verify.claim_paths(box.path, box.preflight_id)
    receipt = read_json(receipt_path)
    mutate(receipt)
    payload = (json.dumps(receipt, sort_keys=True, indent=1) + "\n").encode("utf-8")
    receipt_path.write_bytes(payload)
    receipt_sha = sha(receipt_path)
    completed = read_json(completed_path)
    completed["preflightReceiptSha256"] = receipt_sha
    write_json(completed_path, completed)


def test_verifier_requires_plan():
    outcomes = {}
    box = ready_box("rev7-verify-no-plan")
    claim_path = box.path / "preflight" / "claims" / (box.preflight_id + ".json")
    claim = read_json(claim_path)
    claim.pop("resourcePlan", None)
    claim.pop("resourcePlanSha256", None)
    write_json(claim_path, claim)
    try:
        verify(box)
        outcomes["claimNoPlan"] = "accepted"
    except preflight_verify.PreflightError as error:
        outcomes["claimNoPlan"] = error.reason
    regression_lib.retire_sandbox(box.path)

    box = ready_box("rev7-verify-receipt-plan")
    receipt = read_json(box.preflight_receipt_path())
    expected_plan = receipt.get("resourcePlan")
    def mutate(value):
        value["resourcePlan"] = dict(expected_plan, tag="f" * 16)
    resign_receipt(box, mutate)
    try:
        verify(box)
        outcomes["receiptPlan"] = "accepted"
    except preflight_verify.PreflightError as error:
        outcomes["receiptPlan"] = error.reason
    regression_lib.retire_sandbox(box.path)

    passed = (outcomes["claimNoPlan"] == "claim-resource-plan-missing"
              and outcomes["receiptPlan"] == "receipt-resource-plan")
    return record("independent-verifier-requires-claim-and-receipt-plan", passed,
                  outcomes=outcomes)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(RESULTS))
    args = parser.parse_args(argv)
    results_path = Path(args.out)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    scenarios = [
        test_permission_error_retained,
        test_not_a_directory_unknown,
        test_removed_but_present_not_confirmed,
        test_final_recheck_unknown,
        test_path_reappears_after_delete,
        test_normal_absence,
        test_normal_removal,
        test_mismatch_matrix,
        test_missing_corrupt_and_plan_absent,
        test_claim_and_receipt_bind_plan,
        test_recovery_record_plan_and_no_receipt_rewrite,
        test_verifier_requires_plan,
    ]
    failures = []
    for scenario in scenarios:
        try:
            entry = scenario()
        except BaseException as error:  # noqa: BLE001
            entry = record(scenario.__name__ + "-exception", False,
                           error=type(error).__name__ + ":" + str(error)[:400])
        if not entry.get("passed"):
            failures.append(entry["test"])
    payload = {
        "kind": "cli-recovery-binding-rev7-checks",
        "version": 3,
        "simulated": True,
        "realContainers": 0,
        "realProcesses": 0,
        "realBpftrace": 0,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "shimResolution": dict(regression_lib.SHIM_RESOLUTIONS),
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
