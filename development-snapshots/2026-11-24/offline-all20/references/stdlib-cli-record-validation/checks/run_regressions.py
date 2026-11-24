#!/usr/bin/env python3
"""Offline regression suite for the CLI preflight-integrity revision.

The real controller is executed inside sandboxes under ``checks/tmp``.  Docker
and bpftrace are recorded shims: pure layout/bind/structure commands call the
real tool functions with the exact sealed-profile runtime values, while target
and observer runs are recorded scenarios.  No fixture is imported or executed,
no container is created and no target is run.

Every scenario records the exact rejection reason and the observed side effects
(created attempt files, docker create/start/rm lines, retained stages).
"""
import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
EVIDENCE = ROOT / "checks" / "regression-evidence"
RESULTS = ROOT / "checks" / "regression-results.json"
sys.path.insert(0, str(ROOT / "checks"))
sys.path.insert(0, str(ROOT / "tools"))

import regression_lib  # noqa: E402
from regression_lib import Sandbox, sha  # noqa: E402

IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
ENTRIES = []


def record(name, passed, **fields):
    entry = {"test": name, "passed": bool(passed), **fields}
    ENTRIES.append(entry)
    print(("PASS " if passed else "FAIL ") + name)
    return entry


def copy_evidence(box, name, files):
    destination = EVIDENCE / name
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in files:
        source = box.path / relative
        if source.is_file():
            target = destination / Path(relative).name
            shutil.copyfile(source, target)
    (destination / "RESULT.txt").write_text(
        json.dumps({"sandbox": str(box.path), "files": list(files), "simulated": True}, indent=1) + "\n",
        encoding="utf-8",
    )
    (destination / "SIMULATED.txt").write_text(
        "Recorded Docker/bpftrace shim evidence only. No real container, target "
        "execution, preflight or admission was performed. This is not a real-machine pass.\n",
        encoding="utf-8",
    )


def attempt_files(box):
    return sorted((box.path / "state").glob("attempt-*.json"))


def docker_count(box, prefix):
    return sum(1 for line in box.docker_lines() if line.startswith(prefix))


def preflight_ready(box, preflight_id=None):
    box.write_preflight_license(preflight_id=preflight_id)
    result = box.preflight()
    if result.returncode != 0:
        raise AssertionError("preflight failed: %s %s" % (result.returncode, result.stderr[-800:]))
    return result


# --------------------------------------------------------------------- scenarios
def scenario_fresh():
    box = Sandbox("fresh")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    expected = box.path / "prepare" / "compile-0001" / "expected.json"
    before = expected.is_file()
    result = box.run_attempt(1)
    attempt = box.attempt(1)
    verdict = box.verdict(1) or {}
    passed = (
        not before
        and result.returncode == 0
        and attempt["state"] == "completed"
        and verdict.get("decision") == "confirmed"
        and attempt["expectedSha256"] == sha(expected)
        and attempt["targetExecutions"] == 1
    )
    copy_evidence(box, "fresh", ["state/attempt-0001.json", "runs/0001/verification.json",
                                 "runs/0001/observation.json", "runs/0001/observer.raw",
                                 "prepare/compile-0001/expected.json"])
    return record("fresh-compile-confirmed", passed, returncode=result.returncode,
                  state=attempt.get("state"), decision=verdict.get("decision"),
                  expectedShaMatchesFile=attempt.get("expectedSha256") == sha(expected),
                  targetExecutions=attempt.get("targetExecutions"))


def scenario_reuse():
    box = Sandbox("reuse")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1, 2])
    box.prepare()
    first = box.run(["compile", "--attempt", "2"])
    second = box.run(["compile", "--attempt", "2"])
    result = box.run_attempt(2)
    attempt = box.attempt(2)
    verdict = box.verdict(2) or {}
    expected = box.path / "prepare" / "compile-0002" / "expected.json"
    passed = (
        first.returncode == 0 and '"reused": false' in first.stdout
        and second.returncode == 0 and '"reused": true' in second.stdout
        and result.returncode == 0
        and verdict.get("decision") == "confirmed"
        and attempt["expectedSha256"] == sha(expected)
    )
    copy_evidence(box, "reuse", ["state/attempt-0002.json", "runs/0002/verification.json",
                                 "prepare/compile-0002/expected.json"])
    return record("reuse-confirmed", passed, first=first.stdout.strip(),
                  second=second.stdout.strip(),
                  expectedShaMatchesFile=attempt.get("expectedSha256") == sha(expected))


def scenario_q4_correct():
    box = Sandbox("q4-correct")
    preflight_ready(box)
    box.write_formal_admission(allowed=[8])
    box.prepare()
    result = box.run_attempt(8, exit_code=3, mode="zero")
    attempt = box.attempt(8)
    verdict = box.verdict(8) or {}
    passed = (
        result.returncode == 0
        and verdict.get("decision") == "excluded"
        and verdict.get("reason") == "syntax-reject"
        and attempt.get("state") == "completed"
    )
    copy_evidence(box, "q4-correct", ["state/attempt-0008.json", "runs/0008/verification.json",
                                      "runs/0008/observation.json", "runs/0008/observer.raw"])
    return record("q4-correct-syntax-reject", passed, returncode=result.returncode,
                  decision=verdict.get("decision"), reason=verdict.get("reason"),
                  derived=verdict.get("derived"))


def scenario_q4_wrong_exit():
    box = Sandbox("q4-wrong-exit")
    preflight_ready(box)
    box.write_formal_admission(allowed=[8])
    box.prepare()
    result = box.run_attempt(8, exit_code=0, mode="zero")
    attempt = box.attempt(8)
    verdict = box.verdict(8) or {}
    passed = (
        result.returncode == 3
        and verdict.get("decision") == "unknown"
        and verdict.get("reason") == "syntax-reject-target-exit"
        and attempt.get("cleanup", {}).get("confirmed") is True
        and attempt.get("settled") is True
        and attempt.get("reservationHeld") is False
    )
    copy_evidence(box, "q4-wrong-exit", ["state/attempt-0008.json", "runs/0008/verification.json"])
    return record("q4-wrong-exit-settled-unknown", passed, returncode=result.returncode,
                  reason=verdict.get("reason"), settled=attempt.get("settled"),
                  reservationHeld=attempt.get("reservationHeld"))


def scenario_q4_missing_end():
    box = Sandbox("q4-missing-end")
    preflight_ready(box)
    box.write_formal_admission(allowed=[8])
    box.prepare()
    result = box.run_attempt(8, exit_code=3, mode="zero", end="missing")
    verdict = box.verdict(8) or {}
    observation = box.observation(8) or {}
    passed = (
        result.returncode == 3
        and verdict.get("decision") == "unknown"
        and "observation-state" in (verdict.get("reason") or "")
        and "end-missing" in (observation.get("errors") or [])
    )
    copy_evidence(box, "q4-missing-end", ["state/attempt-0008.json", "runs/0008/verification.json",
                                          "runs/0008/observation.json", "runs/0008/observer.raw"])
    return record("q4-missing-end", passed, returncode=result.returncode,
                  reason=verdict.get("reason"), observationErrors=observation.get("errors"))


def scenario_q4_non_syntax():
    def mutate(plan):
        entry = next(item for item in plan["attempts"] if item["attempt"] == 8)
        entry["payloadTemplate"] = "${challenge}"
    box = Sandbox("q4-non-syntax", plan_mutator=mutate)
    preflight_ready(box)
    box.write_formal_admission(allowed=[8])
    box.prepare()
    result = box.run_attempt(8, exit_code=3, mode="zero")
    verdict = box.verdict(8) or {}
    expected = box.read_json(box.path / "prepare" / "compile-0008" / "expected.json")
    passed = (
        expected.get("payloadSyntax") == "valid"
        and result.returncode == 3
        and verdict.get("decision") == "unknown"
        and verdict.get("reason") == "frozen-reason-mismatch"
    )
    copy_evidence(box, "q4-non-syntax", ["state/attempt-0008.json", "runs/0008/verification.json",
                                         "prepare/compile-0008/expected.json"])
    return record("q4-non-syntax-error", passed, returncode=result.returncode,
                  payloadSyntax=expected.get("payloadSyntax"), reason=verdict.get("reason"))


def scenario_syntax_claims():
    import judge
    def receipt(payload, claimed):
        return {
            "state": "prepared", "targetExecuted": False, "payloadRole": "data",
            "payload": payload,
            "payloadSha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "payloadSyntax": claimed, "syntaxRejectExpected": True,
            "dataBaseline": None, "expectedComputation": None,
            "computationVsBaselineDistinct": None,
        }
    valid_claim = judge.verify_expected(receipt("123", "syntax-error"))
    long_receipt = receipt("a" * 100, "valid")
    long_receipt["syntaxRejectExpected"] = False
    long_claim = judge.verify_expected(long_receipt)
    unsupported = judge.derive_verdict(
        [], {},
        {"payloadRole": "data", "payloadSyntax": "valid",
         "syntaxRejectExpected": False, "dataBaseline": None,
         "expectedComputation": None},
        {}, 3,
    )
    passed = (
        valid_claim == "expected-payload-syntax-mismatch"
        and long_claim is None
        and judge.payload_syntax("0", "data") == "valid"
        and judge.payload_syntax('probe"x', "data") == "syntax-error"
        and unsupported.get("reason") == "no-dynamic-event"
        and unsupported.get("syntaxReject") is False
    )
    return record("syntax-claim-and-structure-unsupported", passed,
                  validClaim=valid_claim, longClaim=long_claim,
                  unsupportedDerived=unsupported)


def scenario_cleanup_conflict():
    box = Sandbox("cleanup-conflict")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.run(["prepare-layout"])
    creates_before = docker_count(box, "create ")
    removes_before = docker_count(box, "rm ")
    result = box.run(["prepare-bind"], extra={"SCE_FORCE_NAME_CONFLICT": "1"})
    lines = box.docker_lines()
    stages = list((box.path / "prepare").glob("stage-bind-*"))
    passed = (
        result.returncode == 79
        and "container-name-conflict" in result.stderr
        and docker_count(box, "rm ") == removes_before
        and docker_count(box, "create ") == creates_before
        and stage_retained(stages)
    )
    copy_evidence(box, "cleanup-conflict", ["state/docker.log"])
    return record("cleanup-name-conflict-retains-stage", passed, returncode=result.returncode,
                  stderrTail=result.stderr[-200:],
                  removeCalls=docker_count(box, "rm ") - removes_before,
                  stageRetained=stage_retained(stages))


def stage_retained(stages):
    return bool(stages) and all(path.is_dir() for path in stages)


def scenario_stage_identity():
    import resource_guard as guard
    base = TMP / ("stage-identity-" + os.urandom(4).hex())
    base.mkdir()
    real = base / "real"
    real.mkdir()
    link = base / "stage-link"
    link.symlink_to(real, target_is_directory=True)
    link_identity = guard.stage_identity(link)
    link_clean = guard.cleanup_stage(str(link), link_identity)
    changed = base / "changed"
    changed.mkdir()
    identity = guard.stage_identity(changed)
    changed.rename(base / "moved")
    changed.mkdir()
    changed_clean = guard.cleanup_stage(str(changed), identity)
    passed = (
        link_identity and link_identity.get("error") == "symlink"
        and link_clean.get("removed") is False
        and link.is_symlink() and real.is_dir()
        and changed_clean.get("removed") is False
        and changed_clean.get("state") == "identity-changed"
        and changed.is_dir()
    )
    return record("stage-symlink-and-identity", passed, link=link_identity,
                  linkCleanup=link_clean, changedCleanup=changed_clean)


def scenario_early_recovery():
    box = Sandbox("early-recovery")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    box.run(["compile", "--attempt", "1"])
    starts_before = docker_count(box, "start ")
    result = box.run_attempt(1, extra={"SCE_FORCE_EXEC_FAIL": "1"})
    attempt = box.attempt(1)
    starts_after_run = docker_count(box, "start ")
    recover = box.run(["recover", "--attempt", "1"])
    after = box.attempt(1)
    starts_after_recover = docker_count(box, "start ")
    passed = (
        result.returncode != 0
        and attempt.get("state") == "unknown"
        and attempt.get("settled") is True
        and attempt.get("reservationHeld") is False
        and attempt.get("targetExecutions") == 0
        and attempt.get("cleanup", {}).get("confirmed") is True
        and recover.returncode == 0
        and '"replayed": false' in recover.stdout
        and after.get("settled") is True
        and (starts_after_run - starts_before) == 1
        and starts_after_recover == starts_after_run
    )
    copy_evidence(box, "early-recovery", ["state/attempt-0001.json", "state/docker.log"])
    return record("early-failure-recovery", passed, runReturn=result.returncode,
                  recoverReturn=recover.returncode, recoverStdout=recover.stdout.strip(),
                  runStarts=starts_after_run - starts_before,
                  replayStarts=starts_after_recover - starts_after_run,
                  targetExecutions=attempt.get("targetExecutions"),
                  cleanupConfirmed=attempt.get("cleanup", {}).get("confirmed"))


def scenario_duplicate():
    box = Sandbox("duplicate")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    first = box.run_attempt(1)
    second = box.run_attempt(1)
    counter = box.read_json(box.path / "state" / "attempt-counter.json")
    passed = (
        first.returncode == 0
        and second.returncode == 79
        and "attempt-already-reserved" in second.stderr
        and counter["used"] == [1]
    )
    return record("duplicate-reservation", passed, first=first.returncode,
                  second=second.returncode, used=counter["used"],
                  stderrTail=second.stderr[-200:])


def scenario_preflight_normal():
    box = Sandbox("preflight-normal")
    preflight_ready(box)
    receipt_path = box.preflight_receipt_path()
    receipt = box.read_json(receipt_path)
    observation = receipt.get("observation") or {}
    containers = []
    for path in (box.path / "state" / "containers").glob("*.json"):
        containers.append(json.loads(path.read_text()))
    preflight_containers = [
        item for item in containers if (item.get("labels") or {}).get("sce.role") == "preflight"
    ]
    command = " ".join(preflight_containers[0]["command"]) if preflight_containers else ""
    mounts = preflight_containers[0].get("mounts") if preflight_containers else []
    status = box.status(box.preflight_id)
    import preflight_verify
    verified = preflight_verify.verify_preflight_evidence(
        box.path,
        receipt_path,
        box.path / "codex-review" / "preflight-admission.json",
        box.path / "codex-review" / "source-review-receipt.json",
        box.path / "protocol-manifest.json",
        box.path / "tools" / "observer-profile.lock.json",
        expected_id=box.preflight_id,
    )
    evidence_files = sorted(
        str(path.relative_to(box.path)) for path in box.preflight_evidence().rglob("*") if path.is_file()
    )
    passed = (
        receipt.get("state") == "accepted"
        and receipt.get("targetExecutions") == 0
        and receipt.get("fixturesImported") == 0
        and (receipt.get("cleanup") or {}).get("confirmed") is True
        and observation.get("complete") is True
        and observation.get("events") == 1
        and observation.get("intZero") is True
        and observation.get("callerOffsetVerified") is True
        and observation.get("structureVerified") is True
        and observation.get("endComplete") is True
        and observation.get("rawSha256") == sha(box.preflight_evidence() / "observer.raw")
        and observation.get("observerSha256") == sha(box.preflight_evidence() / "observer.bt")
        and "preflight_selfcheck.py" in command
        and "target_launcher.py" not in command
        and "experiment_compile.py" not in command
        and {item["Destination"] for item in mounts} == {"/review/preflight"}
        and status.returncode == 0
        and verified["preflightId"] == box.preflight_id
        and any(name.endswith("preflight-receipt.json") for name in evidence_files)
        and not (box.path / "codex-review" / "experiment-admission.json").exists()
    )
    copy_evidence(box, "preflight-sim", ["preflight/evidence/%s/preflight-receipt.json" % box.preflight_id,
                                         "preflight/evidence/%s/observer.raw" % box.preflight_id,
                                         "preflight/evidence/%s/observer.bt" % box.preflight_id,
                                         "preflight/evidence/%s/observation.json" % box.preflight_id,
                                         "preflight/evidence/%s/layout.json" % box.preflight_id])
    return record("preflight-accepted-independent-recompute", passed,
                  returncode=None, state=receipt.get("state"),
                  observation=observation, command=command,
                  mountDestinations=sorted({item["Destination"] for item in mounts}),
                  evidenceFiles=evidence_files)


def scenario_preflight_cannot_target():
    box = Sandbox("preflight-guard")
    box.write_review()
    box.write_preflight_license()
    before = list(box.docker_lines())
    result = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "run", "--attempt", "1"],
        capture_output=True, text=True, env=box.env(), timeout=30,
    )
    after = list(box.docker_lines())
    passed = (
        result.returncode == 2
        and ("unrecognized arguments" in result.stderr or "invalid choice" in result.stderr)
        and before == after
    )
    return record("preflight-cannot-run-formal-target", passed, returncode=result.returncode,
                  stderrTail=result.stderr[-200:], dockerCalls=len(after))


def scenario_preflight_collector_failure():
    box = Sandbox("preflight-collector-failure")
    (box.path / "tools" / "collect_observer.py").write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n", encoding="utf-8"
    )
    box.write_manifest()
    box.write_review()
    box.write_preflight_license()
    legacy = box.path / "preflight" / "observation.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"state": "complete", "events": [{"stale": True}]}) + "\n")
    legacy_sha = sha(legacy)
    result = box.preflight()
    evidence = box.preflight_evidence()
    failure_path = evidence / "failure.json"
    failure = box.read_json(failure_path) if failure_path.is_file() else {}
    receipt_exists = (evidence / "preflight-receipt.json").exists()
    passed = (
        result.returncode == 79
        and str(failure.get("reason", "")).startswith("preflight-collector-exit:")
        and not receipt_exists
        and sha(legacy) == legacy_sha
        and not (evidence / "observation.json").exists()
    )
    copy_evidence(box, "preflight-collector-failure",
                  ["preflight/evidence/%s/failure.json" % box.preflight_id])
    return record("collector-failure-no-stale-observation", passed, returncode=result.returncode,
                  reason=failure.get("reason"), receiptExists=receipt_exists,
                  staleFileUnchanged=sha(legacy) == legacy_sha,
                  observationAbsent=not (evidence / "observation.json").exists())


def scenario_preflight_concurrency():
    box = Sandbox("preflight-concurrency")
    box.write_preflight_license()
    env = box.env({"SCE_PREFLIGHT_DELAY": "1.2"})
    command = [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"), "preflight"]
    first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=env)
    time.sleep(0.15)
    second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=env)
    first_out, first_err = first.communicate(timeout=120)
    second_out, second_err = second.communicate(timeout=120)
    retry = box.preflight()
    claim = box.read_json(box.path / "preflight" / "claims" / (box.preflight_id + ".json"))
    completed = box.path / "preflight" / "claims" / (box.preflight_id + ".completed.json")
    codes = sorted([first.returncode, second.returncode])
    passed = (
        codes == [0, 79]
        and retry.returncode == 79
        and "preflight-license-consumed" in retry.stderr
        and claim.get("state") == "consumed"
        and completed.is_file()
    )
    loser_stderr = first_err if first.returncode == 79 else second_err
    copy_evidence(box, "preflight-concurrency",
                  ["preflight/claims/%s.json" % box.preflight_id,
                   "preflight/claims/%s.completed.json" % box.preflight_id])
    return record("same-license-concurrency-and-retry-rejected", passed,
                  first=first.returncode, second=second.returncode,
                  retry=retry.returncode, loserStderr=loser_stderr[-200:],
                  claimState=claim.get("state"), completed=completed.is_file())


def scenario_preflight_replay():
    box = Sandbox("preflight-replay")
    preflight_ready(box)
    retry = box.preflight()
    status = box.status(box.preflight_id)
    unknown = box.status("f" * 32)
    passed = (
        retry.returncode == 79
        and "preflight-license-consumed" in retry.stderr
        and status.returncode == 0
        and '"state": "completed"' in status.stdout
        and unknown.returncode == 3
        and "unknown-id" in unknown.stdout
    )
    return record("preflight-replay-status-by-original-id", passed,
                  retry=retry.returncode, retryStderr=retry.stderr[-200:],
                  status=status.stdout.strip(), unknown=unknown.stdout.strip())


def scenario_cross_run():
    box = Sandbox("cross-run-a")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    other = Sandbox("cross-run-b")
    preflight_ready(other)
    attempts_before = attempt_files(box)
    # 1. raw from another preflight (different tag/run evidence)
    raw_path = box.preflight_evidence() / "observer.raw"
    original_raw = raw_path.read_bytes()
    raw_path.write_bytes((other.preflight_evidence() / "observer.raw").read_bytes())
    raw_result = box.run_attempt(1)
    raw_path.write_bytes(original_raw)
    # 2. observation from another preflight
    obs_path = box.preflight_evidence() / "observation.json"
    original_obs = obs_path.read_bytes()
    obs_path.write_bytes((other.preflight_evidence() / "observation.json").read_bytes())
    obs_result = box.run_attempt(1)
    obs_path.write_bytes(original_obs)
    # 3. receipt id/path from another preflight
    admission = box.read_json(box.path / "codex-review" / "experiment-admission.json")
    admission["preflightId"] = other.preflight_id
    admission["preflightReceiptPath"] = "preflight/evidence/%s/preflight-receipt.json" % other.preflight_id
    box.write_json(box.path / "codex-review" / "experiment-admission.json", admission)
    id_result = box.run_attempt(1)
    passed = (
        raw_result.returncode == 78 and "admission-preflight:" in raw_result.stderr
        and obs_result.returncode == 78 and "admission-preflight:" in obs_result.stderr
        and id_result.returncode == 78 and "admission-preflight:" in id_result.stderr
        and attempt_files(box) == attempts_before
    )
    return record("cross-run-raw-observation-receipt-mixing", passed,
                  rawReturn=raw_result.returncode, rawReason=raw_result.stderr[-200:],
                  observationReturn=obs_result.returncode,
                  observationReason=obs_result.stderr[-200:],
                  receiptReturn=id_result.returncode,
                  receiptReason=id_result.stderr[-200:],
                  newAttempts=len(attempt_files(box)) - len(attempts_before))


def scenario_layout_change():
    box = Sandbox("layout-change")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    success = box.run_attempt(1)
    attempt_before = box.attempt(1)
    creates_before = docker_count(box, "create ")
    starts_before = docker_count(box, "start ")
    layout_path = box.path / "prepare" / "layout" / "layout.json"
    original = layout_path.read_bytes()
    layout_path.write_bytes(original + b" ")
    result = box.run_attempt(1)
    attempt_after = box.attempt(1)
    # direct judge with the changed layout must not confirm
    judge_result = run_judge(box, 1, layout_path=layout_path)
    layout_path.write_bytes(original)
    passed = (
        success.returncode == 0
        and attempt_before.get("decision") == "confirmed"
        and result.returncode == 79
        and "layout-digest" in result.stderr
        and docker_count(box, "create ") == creates_before
        and docker_count(box, "start ") == starts_before
        and attempt_after.get("decision") == "confirmed"
        and judge_result.get("decision") == "unknown"
        and "layout" in (judge_result.get("reason") or "")
    )
    copy_evidence(box, "layout-change", ["state/attempt-0001.json", "runs/0001/verification.json"])
    return record("layout-change-after-bind-rejected", passed, runReturn=result.returncode,
                  runReason=result.stderr[-200:], judgeDecision=judge_result.get("decision"),
                  judgeReason=judge_result.get("reason"),
                  newCreates=docker_count(box, "create ") - creates_before,
                  newStarts=docker_count(box, "start ") - starts_before)


def run_judge(box, number, layout_path=None, template_path=None, observer_path=None, raw_path=None):
    run_dir = box.path / "runs" / ("%04d" % number)
    out = run_dir / "verification-manual.json"
    command = [
        sys.executable, str(box.path / "tools" / "judge.py"),
        "--binding", str(box.path / "prepare" / "bind" / "bind.json"),
        "--expected", str(box.path / "prepare" / ("compile-%04d" % number) / "expected.json"),
        "--observation", str(run_dir / "observation.json"),
        "--attempt", str(box.path / "state" / ("attempt-%04d.json" % number)),
        "--admission", str(box.path / "codex-review" / "experiment-admission.json"),
        "--manifest", str(box.path / "protocol-manifest.json"),
        "--preflight", str(box.preflight_receipt_path()),
        "--review-receipt", str(box.path / "codex-review" / "source-review-receipt.json"),
        "--observer", str(observer_path or (run_dir / "observer.bt")),
        "--raw", str(raw_path or (run_dir / "observer.raw")),
        "--layout", str(layout_path or (box.path / "prepare" / "layout" / "layout.json")),
        "--template", str(template_path or (box.path / "tools" / "observer_template_buffer_v2.bt")),
        "--profile", str(box.path / "tools" / "observer-profile.lock.json"),
        "--out", str(out),
    ]
    subprocess.run(command, capture_output=True, text=True, timeout=60)
    return json.loads(out.read_text()) if out.is_file() else {}


def scenario_template_change():
    box = Sandbox("template-change")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    template = box.path / "tools" / "observer_template_buffer_v2.bt"
    original = template.read_bytes()
    template.write_bytes(original + b"\n// changed\n")
    before = len(box.docker_lines())
    result = box.run_attempt(1)
    after = len(box.docker_lines())
    template.write_bytes(original)
    passed = (
        result.returncode == 78
        and ("manifest-file-mismatch:tools/observer_template_buffer_v2.bt" in result.stderr
             or "admission-preflight:" in result.stderr)
        and after == before
        and not (box.path / "state" / "attempt-0001.json").exists()
    )
    return record("template-change-before-use-rejected", passed, returncode=result.returncode,
                  reason=result.stderr[-300:], dockerCalls=after - before)


def scenario_process_states():
    import resource_guard as guard
    original_stat = guard.proc_stat
    original_members = guard.group_members
    outcomes = {}
    try:
        def raising(pid):
            raise PermissionError("simulated")
        guard.proc_stat = raising
        outcomes["permission"] = guard.group_state(
            {"pid": 1, "pgid": 1, "starttime": 1, "bootId": guard.boot_id(), "groupLeader": True}
        )["state"]
        guard.proc_stat = lambda pid: {"pid": pid, "unknown": True, "reason": "malformed"}
        outcomes["malformed"] = guard.group_state(
            {"pid": 1, "pgid": 1, "starttime": 1, "bootId": guard.boot_id(), "groupLeader": True}
        )["state"]
        guard.group_members = lambda pgid: ([], None)
        outcomes["empty"] = guard.group_state(
            {"pid": 1, "pgid": 1, "starttime": 1, "bootId": guard.boot_id(), "groupLeader": True}
        )["state"]
        outcomes["missing"] = guard.group_state(None)["state"]
        outcomes["spawn_missing"] = guard.spawn_group_state(
            {"spawnState": "started", "identity": None}
        )["state"]
        outcomes["not_started"] = guard.spawn_group_state({"spawnState": "not-started"})["state"]
    finally:
        guard.proc_stat = original_stat
        guard.group_members = original_members
    passed = (
        outcomes["permission"] == "unknown"
        and outcomes["malformed"] == "unknown"
        and outcomes["empty"] == "exited"
        and outcomes["missing"] == "unknown"
        and outcomes["spawn_missing"] == "unknown"
        and outcomes["not_started"] == "exited"
    )
    return record("process-three-state-and-missing-identity", passed, outcomes=outcomes)


def scenario_same_name():
    import resource_guard as guard
    original_lookup = guard.container_lookup
    original_tag = guard.container_tag_lookup
    original_docker = guard.docker
    calls = []
    try:
        def lookup(identifier):
            if identifier == "a" * 64:
                return {"state": "absent", "detail": "no-such-object"}
            return {"state": "present", "container": {
                "Id": "b" * 64, "Name": "/" + identifier,
                "Config": {"Image": IMAGE, "User": "65534:65534",
                           "Entrypoint": ["/usr/bin/python3.12"],
                           "Labels": {"sce.tag": "ffffffffffffffff"}},
                "State": {"Status": "running", "Pid": 1},
                "Mounts": [], "HostConfig": {},
            }}
        guard.container_lookup = lookup
        guard.container_tag_lookup = lambda tag: {"state": "present", "rows": ["b" * 64 + " name"]}
        guard.docker = lambda *args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, "", "")
        result = guard.remove_container_verified({
            "containerId": "a" * 64,
            "containerName": "name",
            "tag": "0123456789abcdef",
            "containerCreated": True,
            "image": IMAGE,
        })
        wrong_image_lookup = lambda identifier: {"state": "present", "container": {
            "Id": "a" * 64, "Name": "/name",
            "Config": {"Image": "sha256:" + "9" * 64, "User": "65534:65534",
                       "Entrypoint": ["/usr/bin/python3.12"],
                       "Labels": {"sce.tag": "0123456789abcdef"}},
            "State": {"Status": "running", "Pid": 1},
            "Mounts": [], "HostConfig": {},
        }}
        guard.container_lookup = wrong_image_lookup
        guard.container_tag_lookup = lambda tag: {"state": "present", "rows": ["a" * 64 + " name"]}
        wrong_image = guard.remove_container_verified({
            "containerId": "a" * 64, "containerName": "name",
            "tag": "0123456789abcdef", "containerCreated": True, "image": IMAGE,
        })
    finally:
        guard.container_lookup = original_lookup
        guard.container_tag_lookup = original_tag
        guard.docker = original_docker
    passed = (
        result.get("removed") is False
        and result.get("state") == "unknown"
        and "name-replacement" in str(result.get("detail"))
        and wrong_image.get("removed") is False
        and wrong_image.get("detail") == "container-image-mismatch"
        and not any(args and args[0] == "rm" for args in calls)
    )
    return record("same-name-replacement-and-image-mismatch", passed,
                  replacement=result, wrongImage=wrong_image,
                  rmCalls=sum(1 for args in calls if args and args[0] == "rm"))


def scenario_unknown_no_stage():
    import experiment_runner as runner
    import resource_guard as guard
    base = TMP / ("unknown-stage-" + os.urandom(4).hex())
    state = base / "state"
    prepare = base / "prepare"
    runs = base / "runs"
    for path in (state, prepare, runs):
        path.mkdir(parents=True)
    stage = prepare / "stage-test"
    stage.mkdir()
    stage_identity = guard.stage_identity(stage)
    attempt = {
        "version": 1, "attempt": 1, "state": "unknown", "containerId": "a" * 64,
        "containerCreated": True, "stageDir": str(stage), "stageIdentity": stage_identity,
        "resourceIntent": {"containerName": "name", "tag": "0123456789abcdef",
                           "stageDir": str(stage)},
        "processes": {"client": {"spawnState": "not-started"},
                      "observer": {"spawnState": "not-started"}},
        "reservationHeld": True,
    }
    runner.STATE = state
    runner.PREPARE = prepare
    runner.RUNS = runs
    runner.write_json_document(state / "attempt-0001.json", attempt)
    calls = []
    original_cleanup = runner.cleanup_stage
    original_remove = guard.remove_container_verified
    original_spawn = guard.spawn_group_state
    try:
        runner.cleanup_stage = lambda path, identity: calls.append(("stage", path)) or {
            "removed": True, "state": "removed"}
        # 1. unknown container, exited processes: no stage removal
        guard.remove_container_verified = lambda record: {
            "removed": False, "state": "unknown", "detail": "query-failure"}
        guard.spawn_group_state = lambda record: {"state": "exited", "proof": "not-started"}
        first = runner.cleanup_attempt(attempt)
        first_record = runner.read_json(state / "attempt-0001.json")[0]
        calls_first = list(calls)
        # 2. clear container, unknown client: no stage removal
        calls.clear()
        guard.remove_container_verified = lambda record: {
            "removed": True, "state": "removed"}
        guard.spawn_group_state = lambda record: {
            "state": "unknown", "detail": "identity-missing"}
        second = runner.cleanup_attempt(first_record)
        calls_second = list(calls)
        # 3. all clear: stage removal is now allowed
        calls.clear()
        guard.spawn_group_state = lambda record: {"state": "exited", "proof": "group-query"}
        third = runner.cleanup_attempt(runner.read_json(state / "attempt-0001.json")[0])
        calls_third = list(calls)
    finally:
        runner.cleanup_stage = original_cleanup
        guard.remove_container_verified = original_remove
        guard.spawn_group_state = original_spawn
    passed = (
        first is False and calls_first == []
        and second is False and calls_second == []
        and third is True and len(calls_third) == 1
    )
    return record("unknown-resource-retains-stage", passed,
                  firstConfirmed=first, firstStageCalls=calls_first,
                  secondConfirmed=second, secondStageCalls=calls_second,
                  thirdConfirmed=third, thirdStageCalls=calls_third)


def scenario_forced_stop():
    import resource_guard as guard
    original_group_state = guard.group_state
    original_wait = guard._wait_group
    original_killpg = guard.os.killpg
    signals = []
    try:
        guard.group_state = lambda identity: {"state": "alive"}
        guard._wait_group = lambda identity, timeout: {"state": "alive"}
        guard.os.killpg = lambda pgid, sig: signals.append(sig)
        result = guard.stop_group(
            {"pid": 1, "pgid": 1, "starttime": 1, "bootId": guard.boot_id(),
             "groupLeader": True},
            graceful=0, term=0,
        )
    finally:
        guard.group_state = original_group_state
        guard._wait_group = original_wait
        guard.os.killpg = original_killpg
    passed = (
        result.get("stopped") is False
        and result.get("forced") is True
        and signals[:3] == [guard.signal.SIGINT, guard.signal.SIGTERM, guard.signal.SIGKILL]
    )
    return record("forced-observer-stop-is-not-graceful", passed, result=result,
                  signals=[int(sig) for sig in signals])


def scenario_formal_forced_stop():
    box = Sandbox("formal-forced-stop")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    box.run(["compile", "--attempt", "1"])
    result = box.run_attempt(1, extra={"SCE_OBSERVER_IGNORE_INT": "1"})
    attempt = box.attempt(1)
    verdict = box.verdict(1) or {}
    observation = box.observation(1) or {}
    end_info = attempt.get("observerEnd") or {}
    passed = (
        result.returncode == 3
        and end_info.get("forcedStop") is True
        and end_info.get("gracefulStop") is False
        and observation.get("state") == "invalid"
        and "forced-stop" in (observation.get("errors") or [])
        and verdict.get("decision") == "unknown"
        and attempt.get("cleanup", {}).get("confirmed") is True
        and attempt.get("settled") is True
    )
    copy_evidence(box, "formal-forced-stop",
                  ["state/attempt-0001.json", "runs/0001/verification.json",
                   "runs/0001/observation.json", "runs/0001/observer.raw"])
    return record("formal-forced-observer-stop-blocks", passed,
                  returncode=result.returncode, endInfo=end_info,
                  observationState=observation.get("state"),
                  observationErrors=observation.get("errors"),
                  verdictReason=verdict.get("reason"))


def scenario_preflight_observation_failures():
    outcomes = {}
    cases = {
        "missing-end": {"SCE_OBSERVER_END": "missing"},
        "truncated": {"SCE_OBSERVER_TRUNCATE": "1"},
        "forced-stop": {"SCE_OBSERVER_IGNORE_INT": "1"},
    }
    for name, extra in cases.items():
        box = Sandbox("preflight-" + name)
        box.write_preflight_license()
        result = box.preflight(extra=extra)
        evidence = box.preflight_evidence()
        failure_path = evidence / "failure.json"
        failure = box.read_json(failure_path) if failure_path.is_file() else {}
        outcomes[name] = {
            "returncode": result.returncode,
            "reason": failure.get("reason"),
            "acceptedReceipt": (evidence / "preflight-receipt.json").exists(),
        }
    passed = all(
        item["returncode"] == 79
        and not item["acceptedReceipt"]
        and item["reason"]
        for item in outcomes.values()
    ) and outcomes["forced-stop"]["reason"] in {
        "preflight-observer-forced-stop", "preflight-observer-not-graceful",
        "preflight-observer-stop:unknown",
    } and outcomes["missing-end"]["reason"] in {
        "preflight-observation-mismatch", "preflight-end", "preflight-observation-state",
        "preflight-collector-exit:3",
    } and outcomes["truncated"]["reason"] in {
        "preflight-observer-truncated", "preflight-drain-incomplete",
    }
    return record("preflight-observer-failure-modes", passed, outcomes=outcomes)


def scenario_formal_admission():
    cases = {}

    def variant(name, mutate, expected_reason):
        box = Sandbox("formal-" + name)
        preflight_ready(box)
        box.write_formal_admission(allowed=[1])
        box.prepare()
        mutate(box)
        attempts_before = attempt_files(box)
        docker_before = len(box.docker_lines())
        result = box.run_attempt(1)
        attempts_after = attempt_files(box)
        cases[name] = {
            "returncode": result.returncode,
            "reason": result.stderr[-300:],
            "newAttempts": len(attempts_after) - len(attempts_before),
            "dockerCalls": len(box.docker_lines()) - docker_before,
            "expected": expected_reason,
        }

    def missing_preflight(box):
        box.preflight_receipt_path().unlink()

    def tamper_preflight(box):
        path = box.preflight_receipt_path()
        path.write_bytes(path.read_bytes() + b" ")

    def cross_run(box):
        admission = box.read_json(box.path / "codex-review" / "experiment-admission.json")
        admission["preflightId"] = "f" * 32
        admission["preflightReceiptPath"] = "preflight/evidence/%s/preflight-receipt.json" % ("f" * 32)
        box.write_json(box.path / "codex-review" / "experiment-admission.json", admission)

    def missing_review(box):
        (box.path / "codex-review" / "source-review-receipt.json").unlink()

    def blockers(box):
        path = box.path / "codex-review" / "source-review-receipt.json"
        review = box.read_json(path)
        review["blockers"] = ["test-blocker"]
        box.write_json(path, review)
        admission = box.read_json(box.path / "codex-review" / "experiment-admission.json")
        admission["sourceReviewReceiptSha256"] = sha(path)
        admission["reviewReceiptSha256"] = sha(path)
        box.write_json(box.path / "codex-review" / "experiment-admission.json", admission)

    def missing_license(box):
        (box.path / "codex-review" / "preflight-admission.json").unlink()

    def tamper_tool(box):
        path = box.preflight_receipt_path()
        receipt = box.read_json(path)
        receipt["toolDigests"]["structure.py"] = "0" * 64
        box.write_json(path, receipt)
        admission = box.read_json(box.path / "codex-review" / "experiment-admission.json")
        admission["preflightReceiptSha256"] = sha(path)
        box.write_json(box.path / "codex-review" / "experiment-admission.json", admission)
        completed_path = box.path / "preflight" / "claims" / (box.preflight_id + ".completed.json")
        completed = box.read_json(completed_path)
        completed["preflightReceiptSha256"] = sha(path)
        box.write_json(completed_path, completed)

    def wrong_runtime(box):
        path = box.preflight_receipt_path()
        receipt = box.read_json(path)
        receipt["runtime"]["interpreterSha256"] = "0" * 64
        receipt["profile"]["interpreterSha256"] = "0" * 64
        box.write_json(path, receipt)
        admission = box.read_json(box.path / "codex-review" / "experiment-admission.json")
        admission["preflightReceiptSha256"] = sha(path)
        box.write_json(box.path / "codex-review" / "experiment-admission.json", admission)
        completed_path = box.path / "preflight" / "claims" / (box.preflight_id + ".completed.json")
        completed = box.read_json(completed_path)
        completed["preflightReceiptSha256"] = sha(path)
        box.write_json(completed_path, completed)

    def change_profile(box):
        path = box.path / "tools" / "observer-profile.lock.json"
        path.write_bytes(path.read_bytes() + b" ")

    def missing_manifest(box):
        (box.path / "protocol-manifest.json").unlink()

    variant("missing-preflight", missing_preflight, "admission-preflight:missing")
    variant("tampered-preflight", tamper_preflight, "admission-preflight-tampered")
    variant("cross-run-preflight", cross_run, "admission-preflight:")
    variant("missing-review", missing_review, "admission-review-missing")
    variant("review-blockers", blockers, "admission-review-blockers")
    variant("missing-preflight-license", missing_license, "admission-preflight:missing")
    variant("tampered-preflight-tool", tamper_tool, "admission-preflight:receipt-tool")
    variant("wrong-runtime", wrong_runtime, "admission-preflight:receipt-profile-identity")
    variant("changed-profile", change_profile, "manifest-file-mismatch:tools/observer-profile.lock.json")
    variant("missing-manifest", missing_manifest, "manifest-missing")
    passed = all(
        item["returncode"] == 78
        and item["expected"] in item["reason"]
        and item["newAttempts"] == 0
        and item["dockerCalls"] == 0
        for item in cases.values()
    )
    return record("formal-admission-binds-actual-evidence", passed, cases=cases)


def scenario_settlement_recovery():
    box = Sandbox("settlement")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    result = box.run_attempt(1)
    attempt = box.attempt(1)
    starts_before = docker_count(box, "start ")
    recover = box.run(["recover", "--attempt", "1"])
    after = box.attempt(1)
    starts_after = docker_count(box, "start ")
    passed = (
        result.returncode == 0
        and attempt.get("state") == "completed"
        and attempt.get("cleanup", {}).get("confirmed") is True
        and attempt.get("settled") is True
        and attempt.get("reservationHeld") is False
        and recover.returncode == 0
        and '"replayed": false' in recover.stdout
        and starts_after == starts_before
        and after.get("settled") is True
    )
    copy_evidence(box, "settlement", ["state/attempt-0001.json", "state/docker.log"])
    return record("correct-settlement-and-recovery-no-replay", passed,
                  runReturn=result.returncode, recoverReturn=recover.returncode,
                  recoverStdout=recover.stdout.strip(),
                  replayStarts=starts_after - starts_before,
                  cleanupConfirmed=attempt.get("cleanup", {}).get("confirmed"))


def scenario_tamper():
    box = Sandbox("tamper")
    preflight_ready(box)
    box.write_formal_admission(allowed=[1])
    box.prepare()
    box.run_attempt(1)
    run_dir = box.path / "runs" / "0001"
    cases = {}
    for kind in ("observation", "raw", "template"):
        target = run_dir / ("tamper-" + kind)
        if kind == "observation":
            target.write_bytes((run_dir / "observation.json").read_bytes() + b" ")
            verdict = run_judge(box, 1, observer_path=run_dir / "observer.bt",
                                raw_path=run_dir / "observer.raw")
            # Use the tampered observation by direct judge invocation.
            out = run_dir / "verification-tamper.json"
            command = [
                sys.executable, str(box.path / "tools" / "judge.py"),
                "--binding", str(box.path / "prepare" / "bind" / "bind.json"),
                "--expected", str(box.path / "prepare" / "compile-0001" / "expected.json"),
                "--observation", str(target),
                "--attempt", str(box.path / "state" / "attempt-0001.json"),
                "--admission", str(box.path / "codex-review" / "experiment-admission.json"),
                "--manifest", str(box.path / "protocol-manifest.json"),
                "--preflight", str(box.preflight_receipt_path()),
                "--review-receipt", str(box.path / "codex-review" / "source-review-receipt.json"),
                "--observer", str(run_dir / "observer.bt"),
                "--raw", str(run_dir / "observer.raw"),
                "--layout", str(box.path / "prepare" / "layout" / "layout.json"),
                "--template", str(box.path / "tools" / "observer_template_buffer_v2.bt"),
                "--profile", str(box.path / "tools" / "observer-profile.lock.json"),
                "--out", str(out),
            ]
            subprocess.run(command, capture_output=True, text=True, timeout=60)
            cases[kind] = json.loads(out.read_text())
        elif kind == "raw":
            target.write_bytes((run_dir / "observer.raw").read_bytes() + b"tamper\n")
            cases[kind] = run_judge(box, 1, raw_path=target)
        else:
            target.write_bytes((run_dir / "observer.bt").read_bytes() + b"\n# tamper\n")
            cases[kind] = run_judge(box, 1, observer_path=target)
    passed = all(
        item.get("decision") == "unknown"
        and any(token in (item.get("reason") or "") for token in
                ("digest-chain", "observation-mismatch", "observer-rebuild", "observation-"))
        for item in cases.values()
    )
    return record("tamper-observation-raw-template", passed,
                  cases={key: {"decision": value.get("decision"), "reason": value.get("reason")}
                         for key, value in cases.items()})


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(RESULTS))
    parser.add_argument("--evidence", default=str(EVIDENCE))
    args = parser.parse_args(argv)
    results_path = Path(args.out)
    evidence_path = Path(args.evidence)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    globals()["EVIDENCE"] = evidence_path
    TMP.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    scenarios = [
        scenario_fresh,
        scenario_reuse,
        scenario_q4_correct,
        scenario_q4_wrong_exit,
        scenario_q4_missing_end,
        scenario_q4_non_syntax,
        scenario_syntax_claims,
        scenario_cleanup_conflict,
        scenario_stage_identity,
        scenario_early_recovery,
        scenario_duplicate,
        scenario_preflight_normal,
        scenario_preflight_cannot_target,
        scenario_preflight_collector_failure,
        scenario_preflight_concurrency,
        scenario_preflight_replay,
        scenario_cross_run,
        scenario_layout_change,
        scenario_template_change,
        scenario_process_states,
        scenario_same_name,
        scenario_unknown_no_stage,
        scenario_forced_stop,
        scenario_preflight_observation_failures,
        scenario_formal_forced_stop,
        scenario_formal_admission,
        scenario_settlement_recovery,
        scenario_tamper,
    ]
    failures = []
    for scenario in scenarios:
        try:
            entry = scenario()
            if not entry["passed"]:
                failures.append(entry["test"])
        except Exception as error:  # noqa: BLE001
            failures.append(scenario.__name__)
            record(scenario.__name__ + "-exception", False,
                   error=type(error).__name__ + ":" + str(error),
                   trace=traceback.format_exc()[-3000:])
    payload = {
        "kind": "cli-preflight-integrity-regression-results",
        "version": 2,
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "shimResolution": dict(regression_lib.SHIM_RESOLUTIONS),
        "results": ENTRIES,
        "passed": sum(1 for item in ENTRIES if item["passed"]),
        "failed": failures,
        "total": len(ENTRIES),
        "note": "Docker and bpftrace are recorded shims; these are not real-machine results.",
    }
    results_path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
