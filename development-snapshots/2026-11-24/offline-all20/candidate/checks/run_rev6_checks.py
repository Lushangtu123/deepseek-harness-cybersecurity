#!/usr/bin/env python3
"""Revision-6 resource-journal and independent-evidence checks.

Every scenario runs inside an isolated ``checks/tmp`` sandbox with recorded
Docker/bpftrace shims.  Nothing here imports a fixture, executes a target,
starts a real container, issues a real license or calls an external service.
Results are written to ``checks/rev6-results.json`` with ``simulated: true``.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
RESULTS = ROOT / "checks" / "rev6-results.json"
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
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def receipt_and_claim(box):
    receipt_path = box.preflight_receipt_path()
    _claim, completed = preflight_verify.claim_paths(box.path, box.preflight_id)
    return receipt_path, completed


def resign_receipt(box, mutate):
    """Rewrite a receipt and keep the completed-claim link consistent."""
    receipt_path, completed_path = receipt_and_claim(box)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mutate(receipt, box.preflight_evidence())
    payload = (json.dumps(receipt, sort_keys=True, indent=1) + "\n").encode("utf-8")
    receipt_path.write_bytes(payload)
    receipt_sha = hashlib.sha256(payload).hexdigest()
    completed = json.loads(completed_path.read_text(encoding="utf-8"))
    completed["preflightReceiptSha256"] = receipt_sha
    write_json(completed_path, completed)
    return receipt, receipt_sha


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


def expect_preflight_error(box, allowed_prefixes, mutate):
    try:
        resign_receipt(box, mutate)
        verify(box)
    except preflight_verify.PreflightError as error:
        return True, error.reason, list(allowed_prefixes)
    except BaseException as error:  # noqa: BLE001
        return False, type(error).__name__ + ":" + str(error), list(allowed_prefixes)
    return False, "accepted", list(allowed_prefixes)


def ready_box(name):
    box = Sandbox(name)
    box.write_preflight_license()
    result = box.preflight()
    if result.returncode != 0:
        raise AssertionError("preflight failed: %s %s" % (result.returncode, result.stderr[-800:]))
    return box


def activate_box_env(box):
    values = box.env()
    keys = ("PATH", "SCE_ROOT", "SCE_SHIM_STATE", "SCE_DOCKER_LOG",
            "SCE_OBSERVER_MODE", "SCE_OBSERVER_END", "SCE_TARGET_EXIT")
    originals = {key: os.environ.get(key) for key in keys}
    for key in keys:
        if key in values:
            os.environ[key] = values[key]
    return originals


def restore_box_env(originals):
    for key, value in originals.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ---------------------------------------------------------------- resource flow
def test_claim_order_and_untracked_evidence():
    box = Sandbox("rev6-claim-order")
    box.write_preflight_license()
    evidence = box.preflight_evidence()
    evidence.mkdir(parents=True)
    (evidence / "stale-observation.json").write_text('{"complete": true}\n', encoding="utf-8")
    before = sha(evidence / "stale-observation.json")
    result = box.preflight()
    claim, _completed = preflight_verify.claim_paths(box.path, box.preflight_id)
    passed = (
        result.returncode == 79
        and "preflight-evidence-untracked" in result.stderr
        and not claim.exists()
        and sha(evidence / "stale-observation.json") == before
    )
    # Direct order check in the sandbox module: a claim write failure must not
    # create the evidence directory.
    box2 = Sandbox("rev6-claim-order-2")
    box2.write_preflight_license()
    helper = box2.path / "claim_order.py"
    helper.write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import zero_target_preflight as p\n"
        "import resource_guard as g\n"
        "manifest, manifest_sha = p.verify_manifest()\n"
        "license_value, license_sha, review, review_sha, preflight_id = p.verify_license(manifest_sha)\n"
        "evidence = p.preflight_verify.evidence_dir(p.ROOT, preflight_id)\n"
        "original = g.write_new_json_document\n"
        "def fail(path, value):\n"
        "    raise OSError('synthetic-claim-write')\n"
        "g.write_new_json_document = fail\n"
        "raised = None\n"
        "try:\n"
        "    plan = p.preflight_verify.resource_plan(preflight_id, '0123456789abcdef')\n"
        "    p.consume_claim(preflight_id, license_sha, evidence, manifest_sha, review_sha, plan)\n"
        "except BaseException as error:\n"
        "    raised = type(error).__name__\n"
        "finally:\n"
        "    g.write_new_json_document = original\n"
        "print(raised, evidence.exists())\n" % str(box2.path / "tools"),
        encoding="utf-8",
    )
    run = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True,
                         env=box2.env(), timeout=60)
    raised, evidence_exists = (run.stdout.strip().split() + ["", ""])[:2]
    passed = passed and run.returncode == 0 and raised == "OSError" and evidence_exists == "False"
    return record("claim-before-evidence-and-untracked-evidence", passed,
                  untrackedReturn=result.returncode, untrackedStderr=result.stderr[-200:],
                  claimAbsent=not claim.exists(), staleUnchanged=sha(
                      evidence / "stale-observation.json") == before,
                  claimWriteFailure=raised, evidenceAbsentAfterClaimFailure=(evidence_exists == "False"))


def test_post_spawn_identity_failure():
    from checks_repro_support import fake_popen, fake_identity  # noqa: E402

    box = Sandbox("rev6-post-spawn")
    evidence = box.path / "evidence"
    evidence.mkdir()
    tag = "0123456789abcdef"
    context = preflight.new_context(
        evidence, tag, "stdlib-cli-preflight-" + tag, "a" * 32,
        "b" * 64, "c" * 64, "d" * 64, "e" * 64,
    )
    stage = evidence / ("stage-" + tag)
    (stage / "tools").mkdir(parents=True)
    context["stageBuildState"] = "created"
    context["stageIdentity"] = guard.stage_identity(stage)
    original_write = guard.write_new_json_document
    original_identity = guard.process_identity
    original_popen = preflight.subprocess.Popen
    try:
        guard.process_identity = lambda pid: fake_identity()
        preflight.subprocess.Popen = lambda *args, **kwargs: fake_popen()

        def write(path, value):
            if str(path).endswith("process-observer-identity.json"):
                raise OSError("synthetic identity journal write")
            return original_write(path, value)

        guard.write_new_json_document = write
        try:
            preflight.spawn_process(context, "observer", ["mock-bpftrace"])
            error = None
        except BaseException as raised:  # noqa: BLE001
            error = type(raised).__name__
    finally:
        guard.write_new_json_document = original_write
        guard.process_identity = original_identity
        preflight.subprocess.Popen = original_popen
    originals = activate_box_env(box)
    try:
        cleanup = preflight.cleanup_resources(context)
    finally:
        restore_box_env(originals)
    passed = (
        error == "PreflightFailure"
        and context["observer"]["pid"] == os.getpid()
        and context["observer"]["identityPersisted"] is False
        and cleanup["confirmed"] is False
        and cleanup["observer"]["state"] == "unknown"
        and cleanup["stage"]["state"] == "persistence-failed"
        and stage.exists()
    )
    return record("post-spawn-identity-journal-failure", passed, error=error,
                  contextPid=context["observer"]["pid"],
                  identityPersisted=context["observer"]["identityPersisted"],
                  cleanupConfirmed=cleanup["confirmed"],
                  observerState=cleanup["observer"]["state"],
                  stageState=cleanup["stage"]["state"], stageExists=stage.exists())


def test_post_create_container_failure():
    box = Sandbox("rev6-post-create")
    (box.path / "state").mkdir(exist_ok=True)
    evidence = box.path / "evidence"
    evidence.mkdir()
    tag = "fedcba9876543210"
    context = preflight.new_context(
        evidence, tag, "stdlib-cli-preflight-" + tag, "a" * 32,
        "b" * 64, "c" * 64, "d" * 64, "e" * 64,
    )
    stage = evidence / ("stage-" + tag)
    (stage / "tools").mkdir(parents=True)
    context["stageBuildState"] = "created"
    context["stageIdentity"] = guard.stage_identity(stage)
    mounts = {str(stage / "tools"): "/review/preflight"}
    original_write = guard.write_new_json_document
    originals = activate_box_env(box)
    try:
        def write(path, value):
            if str(path).endswith("container-created.json"):
                raise OSError("synthetic container-created write")
            return original_write(path, value)

        guard.write_new_json_document = write
        try:
            preflight.create_container(context, mounts)
            error = None
        except BaseException as raised:  # noqa: BLE001
            error = type(raised).__name__
        cleanup = preflight.cleanup_resources(context)
    finally:
        guard.write_new_json_document = original_write
        restore_box_env(originals)
    container_files = list((box.path / "state" / "containers").glob("*.json"))
    still_present = any(not json.loads(path.read_text()).get("removed")
                        for path in container_files)
    passed = (
        error == "OSError"
        and isinstance(context["container"]["containerId"], str)
        and cleanup["confirmed"] is False
        and cleanup["container"]["removed"] is True
        and not still_present
        and cleanup["stage"]["state"] == "persistence-failed"
        and stage.exists()
    )
    return record("post-create-container-journal-failure", passed, error=error,
                  containerId=context["container"]["containerId"],
                  cleanupConfirmed=cleanup["confirmed"],
                  containerState=cleanup["container"]["state"],
                  stillPresent=still_present, stageState=cleanup["stage"]["state"],
                  stageExists=stage.exists())


def test_partial_stage_failure():
    box = Sandbox("rev6-partial-stage")
    tools = box.path / "tools"
    (tools / "structure.py").unlink()
    evidence = box.path / "evidence"
    evidence.mkdir()
    context = preflight.new_context(
        evidence, "0011223344556677", "stdlib-cli-preflight-0011223344556677",
        "a" * 32, "b" * 64, "c" * 64, "d" * 64, "e" * 64,
    )
    original_tools = preflight.TOOLS
    preflight.TOOLS = tools
    try:
        try:
            preflight.build_stage(context)
            error = None
        except BaseException as raised:  # noqa: BLE001
            error = type(raised).__name__
    finally:
        preflight.TOOLS = original_tools
    stage = Path(context["stageDir"])
    originals = activate_box_env(box)
    try:
        cleanup = preflight.cleanup_resources(context)
    finally:
        restore_box_env(originals)
    passed = (
        error == "PreflightFailure"
        and context["stageBuildState"] == "partial"
        and isinstance(context["stageIdentity"], dict)
        and stage.exists()
        and cleanup["confirmed"] is False
        and cleanup["stage"]["state"] == "partial-build-retained"
    )
    return record("partial-stage-build-failure-traceable", passed, error=error,
                  buildState=context["stageBuildState"], stageExists=stage.exists(),
                  cleanupConfirmed=cleanup["confirmed"],
                  stageState=cleanup["stage"]["state"])


def test_directory_sync_failure():
    box = Sandbox("rev6-fsync")
    evidence = box.path / "evidence"
    evidence.mkdir()
    tag = "8899aabbccddeeff"
    context = preflight.new_context(
        evidence, tag, "stdlib-cli-preflight-" + tag, "a" * 32,
        "b" * 64, "c" * 64, "d" * 64, "e" * 64,
    )
    stage = evidence / ("stage-" + tag)
    (stage / "tools").mkdir(parents=True)
    context["stageBuildState"] = "created"
    context["stageIdentity"] = guard.stage_identity(stage)
    original_fsync = guard._fsync_directory
    try:
        def fail(path):
            raise OSError("synthetic directory fsync")

        guard._fsync_directory = fail
        try:
            preflight.persist_json(context, "synthetic.json", {"kind": "synthetic"})
            error = None
        except BaseException as raised:  # noqa: BLE001
            error = type(raised).__name__
    finally:
        guard._fsync_directory = original_fsync
    originals = activate_box_env(box)
    try:
        cleanup = preflight.cleanup_resources(context)
    finally:
        restore_box_env(originals)
    passed = (
        error == "OSError"
        and context["persistFailure"] is not None
        and cleanup["confirmed"] is False
        and cleanup["stage"]["state"] == "persistence-failed"
        and stage.exists()
    )
    return record("directory-sync-failure-unconfirmed", passed, error=error,
                  persistFailure=context["persistFailure"],
                  cleanupConfirmed=cleanup["confirmed"],
                  stageState=cleanup["stage"]["state"], stageExists=stage.exists())


def test_consumed_interruption_status_and_recover():
    box = Sandbox("rev6-consumed")
    box.write_preflight_license()
    helper = box.path / "interrupt.py"
    helper.write_text(
        "import json,sys\n"
        "sys.path.insert(0, %r)\n"
        "import zero_target_preflight as p\n"
        "manifest, manifest_sha = p.verify_manifest()\n"
        "license_value, license_sha, review, review_sha, preflight_id = p.verify_license(manifest_sha)\n"
        "profile, profile_sha = p.load_profile()\n"
        "evidence = p.preflight_verify.evidence_dir(p.ROOT, preflight_id)\n"
        "tag = '0123456789abcdef'\n"
        "plan = p.preflight_verify.resource_plan(preflight_id, tag)\n"
        "claim, claim_sha = p.consume_claim(preflight_id, license_sha, evidence, manifest_sha, review_sha, plan)\n"
        "context = p.new_context(evidence, tag, p.preflight_verify.fixed_container_name(tag), preflight_id, manifest_sha, license_sha, review_sha, claim_sha, plan)\n"
        "p.persist_json(context, 'preflight-intent.json', {'version': 3, 'protocolRevision': 3, 'kind': 'zero-target-preflight-intent', 'preflightId': preflight_id, 'tag': context['tag'], 'containerName': context['containerName'], 'imageId': p.IMAGE, 'stageDir': context['stageDir'], 'stageIdentity': None, 'mounts': [{'source': str(p.Path(context['stageDir']) / 'tools'), 'destination': '/review/preflight', 'readonly': True}], 'processes': {'client': 'not-started', 'observer': 'not-started'}, 'resourcePlan': plan, 'resourcePlanSha256': context['resourcePlanSha256'], 'targetExecutions': 0, 'fixturesImported': 0, 'createdAt': p.now()})\n"
        "print(json.dumps({'claim': claim_sha, 'preflightId': preflight_id}))\n"
        % str(box.path / "tools")
        , encoding="utf-8")
    run = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True,
                         env=box.env(), timeout=60)
    status = box.status(box.preflight_id)
    recover = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "recover", "--preflight-id", box.preflight_id],
        capture_output=True, text=True, env=box.env(), timeout=60,
    )
    recovery_files = sorted(box.preflight_evidence().glob("recovery-*.json"))
    passed = (
        run.returncode == 0
        and status.returncode == 3
        and "unknown-outcome" in status.stdout
        and recover.returncode == 0
        and recovery_files
        and json.loads(recovery_files[-1].read_text()).get("state") == "resources-cleared"
        and not (box.path / "preflight" / "claims" / (box.preflight_id + ".completed.json")).exists()
    )
    return record("consumed-interruption-status-and-recover", passed,
                  interrupt=run.returncode, status=status.stdout.strip(),
                  recover=recover.returncode, recoverStdout=recover.stdout.strip(),
                  recoveryFiles=[path.name for path in recovery_files])


def test_recovery_normal_and_repeat():
    box = ready_box("rev6-recover-normal")
    receipt = box.preflight_receipt_path()
    receipt_sha = sha(receipt)
    claim_path = box.path / "preflight" / "claims" / (box.preflight_id + ".json")
    claim_sha = sha(claim_path)
    docker_before = box.docker_lines()
    evidence_before = sorted(path.name for path in box.preflight_evidence().iterdir())
    attempts = []
    for _index in range(2):
        before_files = set(box.preflight_evidence().glob("recovery-*.json"))
        result = subprocess.run(
            [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
             "recover", "--preflight-id", box.preflight_id],
            capture_output=True, text=True, env=box.env(), timeout=60,
        )
        new_files = sorted(set(box.preflight_evidence().glob("recovery-*.json"))
                           - before_files)
        value = json.loads(new_files[-1].read_text()) if new_files else {}
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        summary = json.loads(lines[-1]) if lines else {}
        attempts.append({
            "returncode": result.returncode,
            "record": value,
            "summary": summary,
            "newFile": new_files[-1].name if new_files else None,
            "newFileCount": len(new_files),
        })
    recovery_files = sorted(box.preflight_evidence().glob("recovery-*.json"))
    docker_after = box.docker_lines()
    evidence_after = sorted(path.name for path in box.preflight_evidence().iterdir())
    new_creates = sum(1 for line in docker_after[len(docker_before):]
                      if line.startswith("create "))
    new_starts = sum(1 for line in docker_after[len(docker_before):]
                     if line.startswith("start "))
    first, second = attempts
    first_record = first["record"]
    second_record = second["record"]
    first_stage = first_record.get("stage") or {}
    second_stage = second_record.get("stage") or {}
    checks = {
        "firstExitZero": first["returncode"] == 0,
        "secondExitZero": second["returncode"] == 0,
        "firstOneNewFile": first["newFileCount"] == 1,
        "secondOneNewFile": second["newFileCount"] == 1,
        "twoRecoveryRecords": len(recovery_files) == 2,
        "firstState": first_record.get("state") == "resources-cleared",
        "secondState": second_record.get("state") == "resources-cleared",
        "firstCleanupConfirmedTrue": first_record.get("cleanupConfirmed") is True,
        "secondCleanupConfirmedTrue": second_record.get("cleanupConfirmed") is True,
        "firstSelfCheckNotReplayed": first_record.get("selfCheckReplayed") is False,
        "secondSelfCheckNotReplayed": second_record.get("selfCheckReplayed") is False,
        "firstRealMachinePassFalse": first_record.get("realMachinePass") is False,
        "secondRealMachinePassFalse": second_record.get("realMachinePass") is False,
        "firstSummaryState": first["summary"].get("state") == "resources-cleared",
        "secondSummaryState": second["summary"].get("state") == "resources-cleared",
        "firstSummaryCleanupTrue": first["summary"].get("cleanupConfirmed") is True,
        "secondSummaryCleanupTrue": second["summary"].get("cleanupConfirmed") is True,
        "firstSummaryRealMachineFalse": first["summary"].get("realMachinePass") is False,
        "secondSummaryRealMachineFalse": second["summary"].get("realMachinePass") is False,
        "firstStageRemoved": first_stage.get("removed") is True,
        "secondStageRemoved": second_stage.get("removed") is True,
        "firstStageAbsent": first_stage.get("lstatAfter") == "absent",
        "secondStageAbsent": second_stage.get("lstatAfter") == "absent",
        "noNewCreates": new_creates == 0,
        "noNewStarts": new_starts == 0,
        "receiptUnchanged": sha(receipt) == receipt_sha,
        "claimUnchanged": sha(claim_path) == claim_sha,
        "onlyRecoveryFilesAdded": (
            set(evidence_after) - set(evidence_before)
            == {path.name for path in recovery_files}
        ),
    }
    passed = all(checks.values())
    regression_lib.retire_sandbox(box.path)
    return record("recovery-normal-repeated-no-selfcheck", passed,
                  checks=checks, attempts=[
                      {"returncode": item["returncode"],
                       "newFile": item["newFile"],
                       "state": item["record"].get("state"),
                       "cleanupConfirmed": item["record"].get("cleanupConfirmed"),
                       "selfCheckReplayed": item["record"].get("selfCheckReplayed"),
                       "realMachinePass": item["record"].get("realMachinePass"),
                       "stage": item["record"].get("stage"),
                       "summary": item["summary"]}
                      for item in attempts],
                  recoveryFiles=[path.name for path in recovery_files],
                  newCreates=new_creates, newStarts=new_starts,
                  receiptUnchanged=checks["receiptUnchanged"],
                  claimUnchanged=checks["claimUnchanged"])


def test_recovery_lock_busy():
    box = ready_box("rev6-recover-lock")
    lock_path = box.path / "preflight" / ".preflight.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,sys,time\n"
         "handle=open(sys.argv[1],'a+')\n"
         "fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
         "print('locked',flush=True)\n"
         "time.sleep(30)\n",
         str(lock_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        line = holder.stdout.readline()
        result = subprocess.run(
            [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
             "recover", "--preflight-id", box.preflight_id],
            capture_output=True, text=True, env=box.env(), timeout=30,
        )
    finally:
        holder.terminate()
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait()
    recovery_files = list(box.preflight_evidence().glob("recovery-*.json"))
    passed = (
        line.strip() == "locked"
        and result.returncode == 79
        and '"state": "locked"' in result.stdout
        and not recovery_files
    )
    return record("recovery-lock-busy", passed, holder=line.strip(),
                  recover=result.returncode, stdout=result.stdout.strip(),
                  recoveryFiles=[path.name for path in recovery_files])


def test_recover_unknown_process_no_signal():
    calls = []
    original_stop = guard.stop_group
    original_stat = guard.proc_stat
    try:
        guard.stop_group = lambda identity, graceful=5.0, term=2.0: calls.append(identity) or {
            "stopped": True}
        missing = preflight._recover_process(
            {"spawnState": "spawn-attempted", "identity": None}, None)
        no_identity = preflight._recover_process(
            {"spawnState": "started", "identity": None}, None)

        def unreadable(pid):
            raise PermissionError("synthetic")

        guard.proc_stat = unreadable
        unknown = preflight._recover_process(
            {"spawnState": "started",
             "identity": {"pid": 1, "pgid": 1, "starttime": 1,
                          "bootId": guard.boot_id() or "x", "groupLeader": True}}, None)
    finally:
        guard.stop_group = original_stop
        guard.proc_stat = original_stat
    passed = (
        missing["state"] == "unknown"
        and no_identity["state"] == "unknown"
        and unknown["state"] == "unknown"
        and calls == []
    )
    return record("recover-unknown-process-no-signal", passed,
                  missing=missing, noIdentity=no_identity, unreadable=unknown,
                  signals=calls)


def test_recover_corrupt_stat_and_pid_change():
    original_stat = guard.proc_stat
    original_members = guard.group_members
    outcomes = {}
    try:
        guard.proc_stat = lambda pid: {"pid": pid, "unknown": True, "reason": "proc-stat-malformed"}
        outcomes["corrupt"] = preflight._recover_process(
            {"spawnState": "started",
             "identity": {"pid": 1, "pgid": 1, "starttime": 1,
                          "bootId": guard.boot_id() or "x", "groupLeader": True}}, None)
        guard.proc_stat = original_stat
        guard.group_members = lambda pgid: ([{
            "pid": 1, "pidState": "R", "starttime": 999, "session": 1}], None)
        outcomes["changed"] = preflight._recover_process(
            {"spawnState": "started",
             "identity": {"pid": 1, "pgid": 1, "starttime": 1,
                          "bootId": guard.boot_id() or "x", "groupLeader": True}}, None)
    finally:
        guard.proc_stat = original_stat
        guard.group_members = original_members
    passed = (
        outcomes["corrupt"]["state"] == "unknown"
        and outcomes["changed"]["state"] == "unknown"
    )
    return record("recover-corrupt-stat-and-pid-identity-change", passed,
                  corrupt=outcomes["corrupt"], changed=outcomes["changed"])


def test_recover_container_ownership():
    original_lookup = guard.container_lookup
    original_tag = guard.container_tag_lookup
    original_docker = guard.docker
    calls = []
    try:
        def lookup(identifier):
            if identifier == "a" * 64:
                return {"state": "absent", "detail": "no-such-object"}
            return {"state": "present", "container": {
                "Id": "b" * 64, "Name": "/" + str(identifier),
                "Config": {"Image": preflight.IMAGE, "User": "65534:65534",
                           "Entrypoint": ["/usr/bin/python3.12"],
                           "Labels": {"sce.tag": "ffffffffffffffff"}},
                "State": {"Status": "running", "Pid": 1},
                "Mounts": [], "HostConfig": {},
            }}

        guard.container_lookup = lookup
        guard.container_tag_lookup = lambda tag: {"state": "present",
                                                  "rows": ["b" * 64 + " name"]}
        guard.docker = lambda *args, **kwargs: calls.append(args) or subprocess.CompletedProcess(
            args, 0, "", "")
        replacement = preflight._recover_container(
            None,
            {"containerId": "a" * 64, "containerName": "name",
             "tag": "0123456789abcdef", "imageId": preflight.IMAGE},
            None,
        )
        attempted = preflight._recover_container(
            {"containerName": "name", "tag": "0123456789abcdef"},
            None,
            "create-result-unknown",
        )
    finally:
        guard.container_lookup = original_lookup
        guard.container_tag_lookup = original_tag
        guard.docker = original_docker
    passed = (
        replacement.get("removed") is False
        and replacement.get("state") == "unknown"
        and "name-replacement" in str(replacement.get("detail"))
        and attempted.get("removed") is False
        and attempted.get("state") == "unknown"
        and not any(args and args[0] == "rm" for args in calls)
    )
    return record("recover-container-ownership-and-name-replacement", passed,
                  replacement=replacement, attempted=attempted,
                  rmCalls=sum(1 for args in calls if args and args[0] == "rm"))


def test_recover_stage_link_and_identity():
    base = TMP / ("rev6-stage-recover-" + os.urandom(4).hex())
    base.mkdir(parents=True)
    links = regression_lib.FixtureLinks(base)
    try:
        real = base / "real"
        real.mkdir()
        identity = guard.stage_identity(real)
        link = base / "link"
        link.symlink_to(real, target_is_directory=True)
        links.track(link)
        link_result = preflight._recover_stage(str(link), identity, True, None)
        dangling = base / "dangling"
        dangling.symlink_to(base / "does-not-exist", target_is_directory=True)
        links.track(dangling)
        dangling_result = preflight._recover_stage(str(dangling), identity, True, None)
        replaced = base / "replaced"
        replaced.mkdir()
        replacement_identity = guard.stage_identity(replaced)
        (replaced / "marker").write_text("new\n", encoding="utf-8")
        changed = preflight._recover_stage(str(replaced), identity, True, None)
        absent = preflight._recover_stage(str(base / "absent"), identity, True, None)
        passed = (
            link_result.get("removed") is False and link_result.get("state") == "symlink"
            and dangling_result.get("removed") is False and dangling_result.get("state") == "symlink"
            and changed.get("removed") is False and changed.get("state") == "identity-changed"
            and absent.get("removed") is True and absent.get("state") == "absent"
            and real.is_dir() and link.is_symlink()
            and guard.stage_identity(replaced) == replacement_identity
        )
    finally:
        links.close()
        regression_lib.retire_sandbox(base)
    return record("recover-stage-symlink-identity-change-and-absent", passed,
                  link=link_result, dangling=dangling_result,
                  changed=changed, absent=absent)


def test_receipt_write_failure():
    box = Sandbox("rev6-receipt-write")
    box.write_preflight_license()
    helper = box.path / "receipt_write.py"
    helper.write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import zero_target_preflight as p\n"
        "import resource_guard as g\n"
        "original = g.write_new_json_document\n"
        "def fail(path, value):\n"
        "    if str(path).endswith('preflight-receipt.json'):\n"
        "        raise OSError('synthetic receipt write failure')\n"
        "    return original(path, value)\n"
        "g.write_new_json_document = fail\n"
        "raise SystemExit(p.main(['preflight']))\n" % str(box.path / "tools"),
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True,
                            env=box.env(), timeout=180)
    receipt = box.preflight_receipt_path()
    failure_path = box.preflight_evidence() / "failure.json"
    failure = json.loads(failure_path.read_text()) if failure_path.is_file() else {}
    status = box.status(box.preflight_id)
    recover = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "recover", "--preflight-id", box.preflight_id],
        capture_output=True, text=True, env=box.env(), timeout=60,
    )
    passed = (
        result.returncode == 79
        and not receipt.exists()
        and failure.get("cleanup", {}).get("confirmed") is False
        and status.returncode == 3 and "unknown-outcome" in status.stdout
        and recover.returncode == 0
    )
    return record("receipt-write-failure-no-confirmation", passed,
                  preflight=result.returncode, receiptExists=receipt.exists(),
                  failureCleanup=failure.get("cleanup", {}).get("confirmed"),
                  status=status.stdout.strip(), recover=recover.returncode,
                  recoverStdout=recover.stdout.strip())


def test_completion_marker_failure():
    box = Sandbox("rev6-completion-marker")
    box.write_preflight_license()
    helper = box.path / "completion.py"
    helper.write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import zero_target_preflight as p\n"
        "def fail(*args, **kwargs):\n"
        "    raise OSError('synthetic completion marker failure')\n"
        "p.mark_claim_completed = fail\n"
        "raise SystemExit(p.main(['preflight']))\n" % str(box.path / "tools"),
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True,
                            env=box.env(), timeout=180)
    receipt = box.preflight_receipt_path()
    claim, completed = preflight_verify.claim_paths(box.path, box.preflight_id)
    status = box.status(box.preflight_id)
    receipt_sha = sha(receipt) if receipt.is_file() else None
    recover = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "recover", "--preflight-id", box.preflight_id],
        capture_output=True, text=True, env=box.env(), timeout=60,
    )
    passed = (
        result.returncode == 79
        and receipt.is_file() and not completed.exists()
        and status.returncode == 3 and "unknown-outcome" in status.stdout
        and recover.returncode == 0
        and sha(receipt) == receipt_sha
        and '"realMachinePass": false' in recover.stdout
    )
    return record("completion-marker-failure-conservative-unknown", passed,
                  preflight=result.returncode, receiptExists=receipt.is_file(),
                  completedExists=completed.exists(), status=status.stdout.strip(),
                  recover=recover.returncode, recoverStdout=recover.stdout.strip(),
                  receiptUnchanged=sha(receipt) == receipt_sha)


def test_recover_attempted_spawn_without_identity():
    box = ready_box("rev6-spawn-no-identity")
    identity = box.preflight_evidence() / "process-observer-identity.json"
    identity.unlink()
    before = len(box.docker_lines())
    result = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "recover", "--preflight-id", box.preflight_id],
        capture_output=True, text=True, env=box.env(), timeout=60,
    )
    after = box.docker_lines()
    recovery_files = sorted(box.preflight_evidence().glob("recovery-*.json"))
    value = json.loads(recovery_files[-1].read_text()) if recovery_files else {}
    new_starts = sum(1 for line in after[before:] if line.startswith("start "))
    new_creates = sum(1 for line in after[before:] if line.startswith("create "))
    passed = (
        result.returncode == 3
        and value.get("state") == "incomplete"
        and value.get("cleanupConfirmed") is False
        and (value.get("observer") or {}).get("state") == "unknown"
        and new_starts == 0 and new_creates == 0
    )
    return record("recover-attempted-spawn-without-identity", passed,
                  recover=result.returncode, state=value.get("state"),
                  observer=value.get("observer"), newStarts=new_starts,
                  newCreates=new_creates)


def test_recovery_cannot_bypass_frozen_materials():
    box = ready_box("rev6-recover-frozen")
    review = box.path / "codex-review" / "source-review-receipt.json"
    review.write_text('{"state": "broken"}\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "recover", "--preflight-id", box.preflight_id],
        capture_output=True, text=True, env=box.env(), timeout=60,
    )
    recovery_files = sorted(box.preflight_evidence().glob("recovery-*.json"))
    value = json.loads(recovery_files[-1].read_text()) if recovery_files else {}
    state = value.get("state")
    reason = value.get("reason")
    passed = (result.returncode == 78 and state == "blocked"
              and reason == "frozen:license-review")
    return record("recovery-cannot-bypass-frozen-materials", passed,
                  recover=result.returncode, state=state, reason=reason,
                  stderr=result.stderr[-200:])


# ------------------------------------------------------------- evidence binding
def test_observer_tamper_synced_digest():
    box = ready_box("rev6-observer-tamper")

    def mutate(receipt, evidence):
        tampered = (evidence / "observer.bt").read_bytes() + b"\n// tampered\n"
        (evidence / "observer.bt").write_bytes(tampered)
        digest = hashlib.sha256(tampered).hexdigest()
        receipt["observerTemplateSha256"] = digest
        receipt["observation"]["observerSha256"] = digest
        receipt["evidenceDigests"]["observer.bt"] = digest

    passed, reason, allowed = expect_preflight_error(
        box, ("observer-rebuild-mismatch",), mutate)
    return record("observer-tamper-with-synced-receipt-digest", passed,
                  reason=reason, allowed=allowed)


def test_layout_tamper():
    box = ready_box("rev6-layout-tamper")

    def mutate(receipt, evidence):
        layout = json.loads((evidence / "layout.json").read_text(encoding="utf-8"))
        layout["offsets"]["intTagOffset"] += 1
        payload = (json.dumps(layout, sort_keys=True, indent=1) + "\n").encode("utf-8")
        (evidence / "layout.json").write_bytes(payload)
        receipt["layoutSha256"] = hashlib.sha256(payload).hexdigest()
        receipt["layoutStructureSha256"] = preflight_verify.structure.structure_digest(layout)
        receipt["evidenceDigests"]["layout.json"] = receipt["layoutSha256"]
        config_path = evidence / "preflight-config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["layout"]["offsets"]["intTagOffset"] += 1
        config_payload = (json.dumps(config, sort_keys=True, indent=1) + "\n").encode("utf-8")
        config_path.write_bytes(config_payload)
        config_sha = hashlib.sha256(config_payload).hexdigest()
        receipt["preflightConfigSha256"] = config_sha
        receipt["evidenceDigests"]["preflight-config.json"] = config_sha

    passed, reason, allowed = expect_preflight_error(
        box, ("observer-rebuild-mismatch", "config-layout-offsets",
              "config-layout-frame", "layout-"), mutate)
    return record("layout-tamper-rejected", passed, reason=reason, allowed=allowed)


def test_target_pid_tamper():
    box = ready_box("rev6-pid-tamper")

    def mutate(receipt, evidence):
        path = evidence / "container-pid.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["targetPid"] += 1
        value["query"]["stdout"] = str(value["targetPid"]) + "\n"
        payload = (json.dumps(value, sort_keys=True, indent=1) + "\n").encode("utf-8")
        path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        receipt["containerPidSha256"] = digest
        receipt["evidenceDigests"]["container-pid.json"] = digest
        receipt["targetPid"] = value["targetPid"]

    passed, reason, allowed = expect_preflight_error(
        box, ("observer-rebuild-mismatch", "container-pid-binding"), mutate)
    return record("target-pid-tamper-rejected", passed, reason=reason, allowed=allowed)


def test_caller_offset_tamper():
    box = ready_box("rev6-offset-tamper")

    def mutate(receipt, evidence):
        path = evidence / "preflight-config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["callOffset"] += 2
        payload = (json.dumps(config, sort_keys=True, indent=1) + "\n").encode("utf-8")
        path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        receipt["preflightConfigSha256"] = digest
        receipt["evidenceDigests"]["preflight-config.json"] = digest
        receipt["callOffset"] = config["callOffset"]

    passed, reason, allowed = expect_preflight_error(
        box, ("observer-rebuild-mismatch", "observation-recomputed-offset",
              "observation-mismatch"), mutate)
    return record("caller-offset-tamper-rejected", passed, reason=reason, allowed=allowed)


def test_resource_journal_missing_and_owner():
    missing_box = ready_box("rev6-journal-missing")
    (missing_box.preflight_evidence() / "stage-created.json").unlink()
    try:
        verify(missing_box)
        missing_reason = "accepted"
    except preflight_verify.PreflightError as error:
        missing_reason = error.reason
    owner_box = ready_box("rev6-journal-owner")

    def mutate(receipt, evidence):
        path = evidence / "container-created.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["containerName"] = "foreign-owner"
        payload = (json.dumps(value, sort_keys=True, indent=1) + "\n").encode("utf-8")
        path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        receipt["containerCreatedSha256"] = digest
        receipt["evidenceDigests"]["container-created.json"] = digest

    passed_owner, owner_reason, allowed = expect_preflight_error(
        owner_box, ("container-created", "intent-container-name"), mutate)
    passed = (
        missing_reason.startswith("evidence:stage-created.json")
        and passed_owner
    )
    return record("resource-journal-missing-tampered-owner", passed,
                  missingReason=missing_reason, ownerReason=owner_reason,
                  allowed=allowed)


def test_raw_receipt_swap():
    box = ready_box("rev6-raw-swap")
    receipt = box.preflight_receipt_path()
    raw = box.preflight_evidence() / "observer.raw"
    receipt_bytes = receipt.read_bytes()
    raw_bytes = raw.read_bytes()
    receipt.write_bytes(raw_bytes)
    raw.write_bytes(receipt_bytes)
    try:
        verify(box)
        reason = "accepted"
    except preflight_verify.PreflightError as error:
        reason = error.reason
    passed = reason in {"receipt-json", "receipt-shape"} or reason.startswith("receipt-json")
    return record("raw-and-receipt-swap-rejected", passed, reason=reason)


def test_malformed_nested_config():
    box = ready_box("rev6-malformed")
    evidence = box.preflight_evidence()
    config = json.loads((evidence / "preflight-config.json").read_text(encoding="utf-8"))
    layout = json.loads((evidence / "layout.json").read_text(encoding="utf-8"))
    profile, profile_sha = preflight_verify.load_profile(
        box.path / "tools" / "observer-profile.lock.json")
    profile["profileFileSha256"] = profile_sha
    outcomes = {}
    for name, badge in (
        ("expected_structure", {"bad": 1}),
        ("frame_offsets", []),
    ):
        changed = json.loads(json.dumps(config))
        if name == "expected_structure":
            changed["expectedStructure"] = badge
            changed["expectedStructureSha256"] = preflight_verify.structure.structure_digest(badge)
        else:
            changed["layout"]["frameOffsets"] = badge
        raw = (json.dumps(changed, sort_keys=True, indent=1) + "\n").encode("utf-8")
        try:
            preflight_verify.verify_config_bytes(raw, profile, box.preflight_id, layout)
            outcomes[name] = "accepted"
        except preflight_verify.PreflightError as error:
            outcomes[name] = "PreflightError:" + error.reason
        except BaseException as error:  # noqa: BLE001
            outcomes[name] = type(error).__name__
        try:
            preflight.verify_config(changed, profile, profile_sha, box.preflight_id)
            outcomes[name + "_preflight"] = "accepted"
        except preflight.PreflightFailure as error:
            outcomes[name + "_preflight"] = "PreflightFailure:" + error.reason
        except BaseException as error:  # noqa: BLE001
            outcomes[name + "_preflight"] = type(error).__name__
    expected = {
        "expected_structure": "PreflightError:config-expected-structure:KeyError",
        "expected_structure_preflight":
            "PreflightFailure:preflight-expected-structure:KeyError",
        "frame_offsets": "PreflightError:config-layout-frame",
        "frame_offsets_preflight": "PreflightFailure:preflight-layout-frame",
    }
    passed = outcomes == expected
    return record("malformed-expected-structure-and-frame-offsets", passed,
                  outcomes=outcomes, expected=expected)


def test_observation_integrity():
    box = ready_box("rev6-observation")
    receipt, _sha = verify(box), sha(box.preflight_receipt_path())
    raw = box.preflight_evidence() / "observer.raw"
    original = raw.read_bytes()
    observation = receipt["observation"]
    healthy = (
        observation.get("state") == "complete"
        and len(observation.get("events") or []) == 1
        and observation.get("beginCount") == 1
        and observation.get("endCount") == 1
        and any(item.get("t") == "int" and item.get("v") == 0
                for event in observation.get("events") or []
                for item in ((event.get("dynamicStructure") or {}).get("consts") or []))
    )
    raw.write_bytes(original + b"END run=preflight tag=" + receipt["receipt"]["tag"].encode() + b" events=1\n")
    try:
        verify(box)
        tampered = "accepted"
    except preflight_verify.PreflightError as error:
        tampered = error.reason
    raw.write_bytes(original)
    passed = healthy and tampered in {
        "observation-mismatch", "observation-recomputed-state", "observation-raw"
    }
    return record("observation-integer-zero-unique-begin-end-and-tamper", passed,
                  healthy=healthy, tampered=tampered)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(RESULTS))
    args = parser.parse_args(argv)
    results_path = Path(args.out)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    scenarios = [
        test_claim_order_and_untracked_evidence,
        test_post_spawn_identity_failure,
        test_post_create_container_failure,
        test_partial_stage_failure,
        test_directory_sync_failure,
        test_consumed_interruption_status_and_recover,
        test_recovery_normal_and_repeat,
        test_recovery_lock_busy,
        test_recover_unknown_process_no_signal,
        test_recover_corrupt_stat_and_pid_change,
        test_recover_container_ownership,
        test_recover_stage_link_and_identity,
        test_completion_marker_failure,
        test_recover_attempted_spawn_without_identity,
        test_receipt_write_failure,
        test_recovery_cannot_bypass_frozen_materials,
        test_observer_tamper_synced_digest,
        test_layout_tamper,
        test_target_pid_tamper,
        test_caller_offset_tamper,
        test_resource_journal_missing_and_owner,
        test_raw_receipt_swap,
        test_malformed_nested_config,
        test_observation_integrity,
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
        "kind": "cli-resource-journal-rev6-checks",
        "version": 3,
        "simulated": True,
        "realContainers": 0,
        "realProcesses": 0,
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
