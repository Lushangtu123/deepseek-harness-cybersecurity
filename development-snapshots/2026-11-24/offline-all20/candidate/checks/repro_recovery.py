#!/usr/bin/env python3
"""Reproduce the three independent recovery counterexamples.

The script is deliberately source-parameterised: the *same* protocol can be run
against the frozen ``baseline/tools`` candidate and against the current
``tools`` candidate.  All temporary files live under ``checks/tmp``; no real
Docker, bpftrace, sudo, target or fixture import is used.

    python3 checks/repro_recovery.py --phase before \
        --source baseline/tools/zero_target_preflight.py \
        --out checks/repro-before-v7.json

The output file is never silently overwritten.  Each result records the actual
source SHA-256, the command line and the observation time.
"""
import argparse
import ast
import contextlib
import hashlib
import io
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
FULL_ID = re.compile(r"[a-f0-9]{64}")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def canonical_digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("ascii")
    return sha_bytes(payload)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=1) + "\n",
                          encoding="utf-8")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_guard(source):
    return load_module("repro_guard_" + os.urandom(4).hex(),
                       source.parent / "resource_guard.py")


def extract(source, names, environment):
    tree = ast.parse(source.read_bytes(), filename=str(source))
    nodes = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    module = ast.Module(body=[nodes[name] for name in names if name in nodes],
                        type_ignores=[])
    exec(compile(module, str(source), "exec"), environment)
    return environment


def case_lookup_error(source):
    """A PermissionError on the parent must not be used as absence proof."""
    guard = load_guard(source)
    environment = {"os": os, "guard": guard}
    extract(source, ["_recover_stage"], environment)
    recover_stage = environment["_recover_stage"]
    base = Path(tempfile.mkdtemp(prefix="repro-lstat-", dir=TMP))
    barrier = base / "unreadable"
    stage = barrier / "stage"
    stage.mkdir(parents=True)
    barrier.chmod(0)
    error = None
    try:
        try:
            os.lstat(stage)
        except OSError as raised:
            error = type(raised).__name__
        if error is None:
            raise AssertionError("the host permission control did not reproduce")
        result = recover_stage(str(stage), {"dev": 1, "ino": 1}, True, None)
    finally:
        barrier.chmod(0o700)
    stage_present = stage.exists()
    shutil.rmtree(base, ignore_errors=True)
    return {
        "id": "recovery-lookup-error-treated-as-absent",
        "method": "actual local inaccessible parent; no container or target",
        "lstatError": error,
        "reported": result,
        "stageActuallyCreated": True,
        "stageObservedPresentDuringCall": stage_present,
        "defectReproduced": result.get("removed") is True and result.get("lstatAfter") == "absent",
        "fixed": (result.get("removed") is False
                  and result.get("lstatAfter") != "absent"
                  and stage_present),
    }


def case_present_recheck(source):
    """A helper's removed=True cannot override the final lstat recheck."""
    guard = load_guard(source)
    base = Path(tempfile.mkdtemp(prefix="repro-present-", dir=TMP))
    stage_dir = base / "stage"
    stage_dir.mkdir()
    (stage_dir / "marker").write_text("present\n", encoding="utf-8")
    identity = guard.stage_identity(stage_dir)
    original_cleanup = guard.cleanup_stage

    def fake_cleanup(path, value):
        return {"removed": True, "state": "removed"}

    guard.cleanup_stage = fake_cleanup
    context = {
        "stageDir": str(stage_dir),
        "stageIdentity": identity,
        "stageBuildState": "created",
        "persistFailure": None,
        "client": {"spawnState": "not-started"},
        "observer": {"spawnState": "not-started"},
        "container": {"containerName": "simulated", "tag": "0123456789abcdef"},
    }
    environment = {
        "os": os,
        "guard": guard,
        "_process_cleanup": lambda record: {"state": "exited", "proof": "not-started"},
        "_cleanup_container": lambda value: {"removed": True, "state": "never-created"},
        "now": lambda: "synthetic",
    }
    try:
        extract(source, ["_stage_lstat", "_cleanup_stage", "cleanup_resources"], environment)
        result = environment["cleanup_resources"](context)
    finally:
        guard.cleanup_stage = original_cleanup
    present = stage_dir.is_dir()
    shutil.rmtree(base, ignore_errors=True)
    return {
        "id": "cleanup-present-recheck-ignored",
        "method": "synthetic removal summary; actual lstat recheck",
        "reported": result,
        "stageActuallyPresent": present,
        "expectedConfirmed": False,
        "defectReproduced": (result.get("confirmed") is True
                             and (result.get("stage") or {}).get("lstatAfter") == "present"),
        "fixed": (result.get("confirmed") is False
                  and (result.get("stage") or {}).get("lstatAfter") in
                  {"present", "unknown", "lstat-error"}),
    }


def foreign_journals(root, identity_id, tag):
    tag = tag * 16 if len(tag) == 1 else tag
    name = "stdlib-cli-preflight-" + tag
    stage = root / "preflight" / "evidence" / identity_id / ("stage-" + tag)
    observer = root / "preflight" / "evidence" / identity_id / "observer.bt"
    container_id = identity_id * 2
    if not FULL_ID.fullmatch(container_id):
        container_id = (identity_id * 4)[:64]
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "tools").mkdir(exist_ok=True)
    observer.parent.mkdir(parents=True, exist_ok=True)
    observer.write_bytes(b"// simulated observer\n")
    info = os.lstat(stage)
    stage_identity = {"dev": info.st_dev, "ino": info.st_ino,
                      "mode": info.st_mode & 0o777, "path": str(stage)}
    plan = {
        "preflightId": identity_id,
        "tag": tag,
        "containerName": name,
        "imageId": IMAGE,
        "stageRelativePath": "preflight/evidence/%s/stage-%s" % (identity_id, tag),
    }
    plan_sha = canonical_digest(plan)
    mounts = [{"source": str(stage / "tools"), "destination": "/review/preflight",
               "readonly": True}]
    stamp = "2026-11-13T00:00:00+00:00"
    journals = {
        "preflight-intent.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-intent",
            "preflightId": identity_id, "tag": tag, "containerName": name,
            "imageId": IMAGE, "stageDir": str(stage), "stageIdentity": None,
            "mounts": mounts, "processes": {"client": "not-started",
                                             "observer": "not-started"},
            "resourcePlan": plan, "resourcePlanSha256": plan_sha,
            "targetExecutions": 0, "fixturesImported": 0, "createdAt": stamp,
        },
        "stage-intent.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-stage-intent",
            "preflightId": identity_id, "tag": tag, "stageDir": str(stage),
            "toolsDir": str(stage / "tools"),
            "plannedTools": ["preflight_selfcheck.py", "layout_probe.py",
                             "structure.py", "observer_template.bt",
                             "observer-profile.lock.json"],
            "resourcePlan": plan, "resourcePlanSha256": plan_sha,
            "createdAt": stamp,
        },
        "stage-started.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-stage-started",
            "preflightId": identity_id, "stageDir": str(stage),
            "stageIdentity": stage_identity, "createdAt": stamp,
        },
        "stage-created.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-stage-created",
            "preflightId": identity_id, "tag": tag, "stageDir": str(stage),
            "stageIdentity": stage_identity, "mounts": mounts,
            "createdAt": stamp,
        },
        "container-intent.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-container-intent",
            "preflightId": identity_id, "tag": tag, "containerName": name,
            "imageId": IMAGE, "entrypoint": "/usr/bin/python3.12",
            "interactive": True, "mounts": mounts,
            "resourcePlan": plan, "resourcePlanSha256": plan_sha,
            "createdAt": stamp,
        },
        "container-created.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-container-created",
            "preflightId": identity_id, "containerId": container_id,
            "containerName": name, "tag": tag, "imageId": IMAGE,
            "entrypoint": "/usr/bin/python3.12", "interactive": True,
            "mounts": mounts,
            "createQuery": {"returncode": 0,
                            "stdout": container_id + "\n", "stderr": ""},
            "createdAt": stamp,
        },
        "process-client-intent.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-process-intent",
            "preflightId": identity_id, "role": "client",
            "spawnState": "spawn-attempted",
            "argv": ["docker", "start", "-a", "-i", container_id],
            "recordedAt": stamp,
        },
        "process-client-identity.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-process-state",
            "preflightId": identity_id, "role": "client", "pid": 4242,
            "spawnState": "started",
            "identity": {"pid": 4242, "pgid": 4242, "starttime": 1,
                         "bootId": "repro-boot", "groupLeader": True},
            "recordedAt": stamp,
        },
        "process-observer-intent.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-process-intent",
            "preflightId": identity_id, "role": "observer",
            "spawnState": "spawn-attempted",
            "argv": ["bpftrace", "-q", str(observer)],
            "recordedAt": stamp,
        },
        "process-observer-identity.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-process-state",
            "preflightId": identity_id, "role": "observer", "pid": 4243,
            "spawnState": "started",
            "identity": {"pid": 4243, "pgid": 4243, "starttime": 2,
                         "bootId": "repro-boot", "groupLeader": True},
            "recordedAt": stamp,
        },
        "container-pid.json": {
            "version": 3, "protocolRevision": 3,
            "kind": "zero-target-preflight-container-pid",
            "preflightId": identity_id, "containerId": container_id,
            "containerName": name, "tag": tag,
            "argv": ["docker", "inspect", "--type", "container", "-f",
                     "{{.State.Pid}}", container_id],
            "query": {"returncode": 0, "stdout": "4244\n", "stderr": ""},
            "targetPid": 4244, "recordedAt": stamp,
        },
    }
    evidence = root / "preflight" / "evidence" / identity_id
    for filename, value in journals.items():
        write_json(evidence / filename, value)
    return {"stage": stage, "containerId": container_id, "name": name,
            "tag": tag, "observer": observer, "plan": plan, "planSha": plan_sha}


def case_foreign_journals(source):
    """ID A's evidence containing ID B's journals must be rejected as a whole."""
    sandbox = Path(tempfile.mkdtemp(prefix="repro-foreign-", dir=TMP))
    shutil.copytree(source.parent, sandbox / "tools", dirs_exist_ok=True)
    tools = sorted((sandbox / "tools").glob("*"))
    files = {str(path.relative_to(sandbox)): sha_file(path) for path in tools if path.is_file()}
    write_json(sandbox / "protocol-manifest.json", {
        "kind": "stdlib-cli-admission-protocol-manifest", "version": 3,
        "phase": "repro", "state": "pending-codex-review", "selfExcluded": True,
        "files": files, "fileCount": len(files), "targetExecutions": 0,
    })
    manifest_sha = sha_file(sandbox / "protocol-manifest.json")
    (sandbox / "codex-review").mkdir()
    write_json(sandbox / "codex-review" / "source-review-receipt.json", {
        "state": "completed", "protocolManifestSha256": manifest_sha,
        "blockers": [], "reviewer": "repro-recorded-review",
    })
    review_sha = sha_file(sandbox / "codex-review" / "source-review-receipt.json")
    original_id = "a" * 32
    foreign_id = "b" * 32
    foreign_tag = "b" * 16
    foreign = foreign_journals(sandbox, foreign_id, foreign_tag)
    (sandbox / "preflight" / "claims").mkdir(parents=True)
    tag = "a" * 16
    name = "stdlib-cli-preflight-" + tag
    plan = {
        "preflightId": original_id, "tag": tag, "containerName": name,
        "imageId": IMAGE,
        "stageRelativePath": "preflight/evidence/%s/stage-%s" % (original_id, tag),
    }
    write_json(sandbox / "codex-review" / "preflight-admission.json", {
        "kind": "zero-target-preflight-admission", "protocolRevision": 3,
        "state": "approved", "allowedCommand": "preflight",
        "maxTargetExecutions": 0, "fixturesImported": 0,
        "protocolManifestSha256": manifest_sha,
        "candidateManifestSha256": manifest_sha,
        "sourceReviewReceiptSha256": review_sha, "preflightId": original_id,
    })
    license_sha = sha_file(sandbox / "codex-review" / "preflight-admission.json")
    write_json(sandbox / "preflight" / "claims" / (original_id + ".json"), {
        "version": 3, "protocolRevision": 3,
        "kind": "zero-target-preflight-claim", "state": "consumed",
        "preflightId": original_id, "preflightLicenseSha256": license_sha,
        "protocolManifestSha256": manifest_sha,
        "sourceReviewReceiptSha256": review_sha,
        "evidenceDir": "preflight/evidence/" + original_id,
        "evidencePath": str(sandbox / "preflight" / "evidence" / original_id),
        "resourcePlan": plan, "resourcePlanSha256": canonical_digest(plan),
        "consumedAt": "2026-11-13T00:00:00+00:00",
        "targetExecutions": 0, "fixturesImported": 0,
    })
    original_evidence = sandbox / "preflight" / "evidence" / original_id
    original_evidence.mkdir(parents=True)
    # The defect is exactly this: ID A's evidence directory contains valid
    # journals that belong to ID B.  Keep the journal bytes identical.
    foreign_evidence = foreign["stage"].parents[0]
    for path in sorted(foreign_evidence.glob("*.json")):
        shutil.copyfile(path, original_evidence / path.name)
    module = load_module("repro_preflight_" + os.urandom(4).hex(),
                         sandbox / "tools" / "zero_target_preflight.py")
    calls = {"container": 0, "process": 0, "stage": 0, "stopGroup": 0,
             "removeContainer": 0, "cleanupStage": 0, "docker": 0}
    handoffs = []
    captured = {}

    def recorder_container(*args, **kwargs):
        calls["container"] += 1
        handoffs.append({"kind": "container", "args": [repr(value) for value in args]})
        return {"removed": True, "state": "recorder-no-effect"}

    def recorder_process(*args, **kwargs):
        calls["process"] += 1
        handoffs.append({"kind": "process", "args": [repr(value) for value in args]})
        return {"state": "exited", "proof": "recorder-no-effect"}

    def recorder_stage(*args, **kwargs):
        calls["stage"] += 1
        handoffs.append({"kind": "stage", "args": [repr(value) for value in args]})
        return {"removed": True, "lstatAfter": "absent", "state": "recorder-no-effect"}

    def recorder_write(recovery, evidence, code):
        captured["recovery"] = recovery
        captured["code"] = code
        return code

    module._recover_container = recorder_container
    module._recover_process = recorder_process
    module._recover_stage = recorder_stage
    module._write_recovery = recorder_write
    guard = module.guard
    guard.stop_group = lambda *args, **kwargs: calls.__setitem__(
        "stopGroup", calls["stopGroup"] + 1) or {"stopped": True, "state": "exited"}
    guard.remove_container_verified = lambda *args, **kwargs: calls.__setitem__(
        "removeContainer", calls["removeContainer"] + 1) or {
            "removed": True, "state": "recorder-no-effect"}
    guard.cleanup_stage = lambda *args, **kwargs: calls.__setitem__(
        "cleanupStage", calls["cleanupStage"] + 1) or {
            "removed": True, "state": "recorder-no-effect"}
    guard.docker = lambda *args, **kwargs: calls.__setitem__(
        "docker", calls["docker"] + 1) or None
    code = module.recover(original_id)
    recovery = captured.get("recovery") or {}
    foreign_stage_handed = next((row for row in handoffs
                                 if row["kind"] == "stage"
                                 and str(foreign["stage"]) in " ".join(row["args"])), None)
    shutil.rmtree(sandbox, ignore_errors=True)
    result = {
        "id": "recovery-foreign-journals-not-rejected",
        "method": "effect-free control-flow handoff with real claim/licence reads",
        "requestedPreflightId": original_id,
        "journalPreflightId": foreign_id,
        "code": code,
        "state": recovery.get("state"),
        "reason": recovery.get("reason"),
        "cleanupConfirmed": recovery.get("cleanupConfirmed"),
        "cleanupHandoffs": calls,
        "handoffCount": len(handoffs),
        "foreignStageHanded": foreign_stage_handed is not None,
        "handoffs": handoffs,
        "defectReproduced": (code == 0 and recovery.get("state") == "resources-cleared"
                             and len(handoffs) > 0 and foreign_stage_handed is not None),
        "fixed": (code == 78 and recovery.get("state") == "blocked"
                  and sum(calls.values()) == 0 and len(handoffs) == 0),
    }
    return result



def function_summaries(source, names):
    """Record the actual source spans/digests used by this reproduction."""
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source))
    found = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    result = {}
    for name in names:
        node = found.get(name)
        if node is None:
            result[name] = None
            continue
        segment = ast.get_source_segment(text, node) or ""
        result[name] = {
            "lineno": node.lineno,
            "endLineno": node.end_lineno,
            "sha256": sha_bytes(segment.encode("utf-8")),
        }
    return result


def case_cached_absence(source):
    """A stage appearing during the resource query must be rechecked.

    The recovery plan lstat sees an absent stage.  While the container query is
    running, a harmless local directory appears at the planned path.  A cached
    absence result returns success; the fixed code must take a new path query
    and retain the directory as incomplete.
    """
    module = load_module("repro_cached_" + os.urandom(4).hex(), source)
    sandbox = Path(tempfile.mkdtemp(prefix="repro-cached-", dir=TMP))
    identifier = "c" * 32
    tag = "d" * 16
    manifest_sha, license_sha, review_sha = "1" * 64, "2" * 64, "3" * 64
    module.ROOT = sandbox
    module.PREFLIGHT_ROOT = sandbox / "preflight"
    module.CLAIMS_ROOT = module.PREFLIGHT_ROOT / "claims"
    module.EVIDENCE_ROOT = module.PREFLIGHT_ROOT / "evidence"
    module.RECOVERIES_ROOT = module.PREFLIGHT_ROOT / "recoveries"
    module.LOCK_PATH = module.PREFLIGHT_ROOT / ".preflight.lock"
    module.MANIFEST = sandbox / "protocol-manifest.json"
    module.LICENSE = sandbox / "license.json"
    module.REVIEW = sandbox / "review.json"
    module.PROFILE = source.parent / "observer-profile.lock.json"
    verify = module.preflight_verify
    originals = (verify.verify_manifest, verify.verify_license, verify.load_profile)
    verify.verify_manifest = lambda *args: ({}, manifest_sha)
    verify.verify_license = lambda *args, **kwargs: (
        {}, license_sha, {}, review_sha, identifier)
    verify.load_profile = lambda *args: ({}, "4" * 64)
    calls = {"containerQuery": 0, "delete": 0, "stageQueries": 0}
    try:
        plan = verify.resource_plan(identifier, tag)
        plan_sha = verify.resource_plan_digest(plan)
        evidence = verify.evidence_dir(sandbox, identifier)
        evidence.mkdir(parents=True)
        planned_stage = sandbox / plan["stageRelativePath"]
        claim = module.claim_record(
            identifier, license_sha, evidence, manifest_sha, review_sha, plan)
        claim_path = module.CLAIMS_ROOT / (identifier + ".json")
        claim_path.parent.mkdir(parents=True)
        write_json(claim_path, claim)
        write_json(evidence / "preflight-intent.json", {
            "version": 3,
            "protocolRevision": 3,
            "kind": "zero-target-preflight-intent",
            "preflightId": identifier,
            "tag": tag,
            "containerName": plan["containerName"],
            "imageId": plan["imageId"],
            "stageDir": str(planned_stage),
            "resourcePlan": plan,
            "resourcePlanSha256": plan_sha,
        })
        before = module._recovery_plan(evidence, identifier, plan, plan_sha)

        original_cleanup_container = module._cleanup_container

        def container_effect(context):
            calls["containerQuery"] += 1
            planned_stage.mkdir()
            (planned_stage / "appeared-during-query").write_text(
                "local no-effect marker\n", encoding="utf-8")
            return {"removed": True, "state": "synthetic-absent"}

        original_recover_stage = module._recover_stage

        def counted_recover_stage(*args, **kwargs):
            calls["delete"] += 1
            return original_recover_stage(*args, **kwargs)

        module._cleanup_container = container_effect
        module._recover_stage = counted_recover_stage
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = module.recover(identifier)
        summary = json.loads(stream.getvalue().splitlines()[-1])
        recovery = json.loads(Path(summary["recoveryFile"]).read_bytes())
        stage_present = planned_stage.is_dir()
        stage_state = recovery.get("stage") or {}
        result = {
            "id": "cached-absence-not-rechecked-at-success",
            "method": "real local claim and journal parsing; a harmless local "
                      "directory appears during the mocked container query",
            "frozenMaterialChecks": "synthetic valid controls; no real admission "
                                    "or selfcheck",
            "validatedPlanBefore": {
                "status": before.get("status"),
                "stage": before.get("stage"),
            },
            "resourceCalls": [
                {"action": "container-query", "count": calls["containerQuery"],
                 "stageCreatedDuringQuery": True},
                {"action": "stage-delete", "count": calls["delete"]},
            ],
            "exitCode": code,
            "reported": summary,
            "stageReport": stage_state,
            "stageActuallyPresentAtReturn": stage_present,
            "stageActualPath": str(planned_stage),
            "expectedCleanupConfirmed": False,
            "defectReproduced": (
                code == 0
                and recovery.get("state") == "resources-cleared"
                and recovery.get("cleanupConfirmed") is True
                and stage_state.get("lstatAfter") == "absent"
                and stage_present
            ),
            "fixed": (
                code == 3
                and recovery.get("state") == "incomplete"
                and recovery.get("cleanupConfirmed") is False
                and stage_state.get("lstatAfter") == "present"
                and stage_state.get("removed") is False
                and stage_present
                and calls["delete"] == 0
            ),
            "limit": "No real container, process or deletion; one local "
                     "directory was created and retained.",
        }
        return result
    finally:
        verify.verify_manifest, verify.verify_license, verify.load_profile = originals
        shutil.rmtree(sandbox, ignore_errors=True)



def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-overwrite", action="store_true")
    args = parser.parse_args(argv)
    source = Path(args.source)
    if not source.is_file():
        raise SystemExit("source missing: " + str(source))
    out = Path(args.out)
    if out.exists() and not args.allow_overwrite:
        raise SystemExit("output already exists (first failure is immutable): " + str(out))
    TMP.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    results = [case_lookup_error(source), case_present_recheck(source),
               case_foreign_journals(source), case_cached_absence(source)]
    key = "defectReproduced" if args.phase == "before" else "fixed"
    if args.phase == "before":
        # The frozen baseline already contains the three earlier fixes.  This
        # phase exists to reproduce the *new* success-path counterexample on
        # those exact baseline bytes; the earlier cases are recorded for
        # context and are not required to fail again.
        required = [item for item in results
                    if item.get("id") == "cached-absence-not-rechecked-at-success"]
        all_expected = all(item.get(key) is True for item in required)
    else:
        all_expected = all(item.get(key) is True for item in results)
    payload = {
        "kind": "recovery-counterexample-reproduction",
        "phase": args.phase,
        "source": str(source),
        "sourceSha256": sha_file(source),
        "command": list(sys.argv),
        "startedAt": started,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "realProcesses": 0,
        "fixturesImported": 0,
        "sourceFunctions": function_summaries(
            source, ("recover", "_final_stage_recheck", "_recovery_plan",
                     "_recover_stage", "_cleanup_stage", "_safe_lstat")),
        "allExpected": all_expected,
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"phase": args.phase, "allExpected": all_expected,
                      "sourceSha256": payload["sourceSha256"],
                      "results": [(item["id"], item[key]) for item in results]},
                     sort_keys=True))
    return 0 if all_expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
