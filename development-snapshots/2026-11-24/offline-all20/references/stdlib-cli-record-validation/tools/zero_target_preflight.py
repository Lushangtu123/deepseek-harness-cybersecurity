#!/usr/bin/env python3
"""Executable zero-target preflight for the CLI experiment (revision 6).

The preflight has its **own** license (``codex-review/preflight-admission.json``)
bound to a unique ``preflightId``, the frozen candidate manifest and a completed
source-review receipt.  It does not require, read or write the formal experiment
admission, so the permission path is not circular.

Fail-closed lifecycle (revision 6):

1. verify the manifest, license, review and sealed observer profile;
2. take one stable exclusive lock and consume the license exactly once in a
   persistent claim registry **before** creating an evidence directory, stage,
   container or process;
3. keep one outer *resource context* that contains the stage/container/client/
   observer records before anything is created.  Every intent is persisted
   before its create/spawn call, and every obtained identity is put into the
   shared context immediately after the call returns -- before any further
   journal I/O can fail;
4. create every evidence file with ``O_EXCL`` (never overwrite an old file);
5. run only the fixed preflight tools, require the collector to exit 0 and
   recompute the observation from this invocation's raw bytes with the same
   pure parser the runner and judge use;
6. require a graceful observer stop (SIGINT, no TERM/KILL), complete drains,
   unique BEGIN/END, the bound preflight identity/tag/caller offset, integer
   zero, exact structure and exactly one event;
7. prove the container absent with three successful queries, prove the client
   and observer groups exited, and only then remove the identity-checked stage;
8. write bounded query/cleanup evidence and the accepted receipt only after all
   of the above, then mark the claim completed.  A journal-write or fsync
   failure keeps the outcome unknown and never produces a cleanup confirmation.

Unknown outcomes are queried by the original ID with the read-only
``status --preflight-id`` command and cleaned by ``recover --preflight-id``.
Recovery never replays the self-check, never rewrites an old receipt and never
invents a real-machine pass.

There is deliberately no argument for a script, target, fixture, attempt or
arbitrary mount.
"""
import argparse
import copy
import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import buffer_protocol_v2  # noqa: E402
import observation_pure  # noqa: E402
import observer_render  # noqa: E402
import preflight_diagnostics as diagnostics  # noqa: E402
import preflight_verify  # noqa: E402
import resource_guard as guard  # noqa: E402
import structure  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_ROOT = ROOT / "preflight"
EVIDENCE_ROOT = PREFLIGHT_ROOT / "evidence"
CLAIMS_ROOT = PREFLIGHT_ROOT / "claims"
RECOVERIES_ROOT = PREFLIGHT_ROOT / "recoveries"
LOCK_PATH = PREFLIGHT_ROOT / ".preflight.lock"
MANIFEST = ROOT / "protocol-manifest.json"
LICENSE = ROOT / "codex-review" / "preflight-admission.json"
REVIEW = ROOT / "codex-review" / "source-review-receipt.json"
TOOLS = ROOT / "tools"
PROFILE = TOOLS / "observer-profile.lock.json"

IMAGE = preflight_verify.FIXED_IMAGE
PYTHON_VERSION = preflight_verify.PYTHON_VERSION
INTERPRETER = preflight_verify.INTERPRETER
TARGET_UID = str(preflight_verify.TARGET_UID)
TARGET_GID = str(preflight_verify.TARGET_UID)
RUN_ID = preflight_verify.RUN_ID
CALLER_PATH = preflight_verify.CALLER_PATH
PROFILE_NAME = preflight_verify.PROFILE_NAME
FIXED_TOOLS = preflight_verify.TOOL_NAMES
PROTOCOL_REVISION = preflight_verify.PROTOCOL_REVISION
OBSERVATION_PROTOCOL = preflight_verify.OBSERVATION_PROTOCOL
FRAMING_POLICY = preflight_verify.FRAMING_POLICY
BUFFER_PARSER_NAME = preflight_verify.BUFFER_PARSER_NAME
BUFFER_TEMPLATE_NAME = preflight_verify.BUFFER_TEMPLATE_NAME
CONTEXT_VERSION = 3
LIMITS = {
    "memoryMiB": 512,
    "cpus": 1,
    "pids": 64,
    "tmpMiB": 32,
    "outputBytes": 262144,
    "configTimeoutSeconds": 120,
    "observerArmTimeoutSeconds": 15,
    "targetTimeoutSeconds": 30,
    "observerStopGraceSeconds": 8,
}
HASH_RE = re.compile(r"[a-f0-9]{64}")
TAG_RE = re.compile(r"[a-f0-9]{16}")
FULL_ID_RE = re.compile(r"[a-f0-9]{64}")
ALLOWED_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "HOSTNAME": "stdlib-cli-experiment",
}


class PreflightFailure(Exception):
    def __init__(self, reason, detail=None, cleanup=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail
        # Optional cleanup evidence already observed by the raising site.  The
        # outer failure handler preserves it with the original reason; it does
        # not turn an unconfirmed cleanup into success.
        self.cleanup = copy.deepcopy(cleanup) if isinstance(cleanup, dict) else None


def now():
    return datetime.now(timezone.utc).isoformat()


def die(code, message):
    sys.stderr.write("preflight: %s\n" % message)
    raise SystemExit(code)


def check_regular(path):
    if not path.is_file() or os.path.islink(path):
        die(78, "license-path")
    return path


def verify_manifest():
    try:
        return preflight_verify.verify_manifest(ROOT, MANIFEST)
    except preflight_verify.PreflightError as error:
        die(78, error.reason)


def buffer_binding():
    """Actual frozen buffer parser/template digests, before any resource."""
    binding = {}
    for name in (BUFFER_PARSER_NAME, BUFFER_TEMPLATE_NAME):
        path = TOOLS / name
        if not path.is_file() or os.path.islink(path):
            die(78, "buffer-material-missing:" + name)
        binding[name] = guard.sha_file(path)
    return binding


def verify_license(manifest_sha, expected_id=None, require_buffer_protocol=True,
                   binding=None):
    try:
        if require_buffer_protocol and binding is None:
            binding = buffer_binding()
        parser_sha = (binding or {}).get(BUFFER_PARSER_NAME)
        template_sha = (binding or {}).get(BUFFER_TEMPLATE_NAME)
        license_value, license_sha, review, review_sha, preflight_id = (
            preflight_verify.verify_license(
                LICENSE, REVIEW, manifest_sha, expected_id=expected_id,
                parser_sha=parser_sha, template_sha=template_sha,
                require_buffer_protocol=require_buffer_protocol,
            )
        )
    except preflight_verify.PreflightError as error:
        die(78, error.reason)
    return license_value, license_sha, review, review_sha, preflight_id


def load_profile():
    try:
        profile, profile_sha = preflight_verify.load_profile(PROFILE)
    except preflight_verify.PreflightError as error:
        die(78, "profile:" + error.reason)
    profile["profileFileSha256"] = profile_sha
    return profile, profile_sha


# --------------------------------------------------------------- resource context
def new_context(evidence, tag, name, preflight_id, manifest_sha, license_sha,
                review_sha, claim_sha, plan=None, binding=None):
    """One outer record for every resource that may exist after this point.

    The caller keeps this object for the whole invocation.  It exists *before*
    the first create/spawn call and is updated immediately when a handle or an
    identity is obtained.  The resource plan is fixed here, before any create.
    """
    if plan is None:
        plan = preflight_verify.resource_plan(preflight_id, tag)
    reason = preflight_verify.resource_plan_reason(plan, preflight_id)
    if reason:
        raise PreflightFailure("preflight-" + reason)
    if plan.get("containerName") != name:
        raise PreflightFailure("preflight-resource-plan-container-name")
    evidence_relative = "preflight/evidence/" + preflight_id
    if plan.get("stageRelativePath") != evidence_relative + "/stage-" + tag:
        raise PreflightFailure("preflight-resource-plan-stage-path")
    context = {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-resource-context",
        "preflightId": preflight_id,
        "tag": tag,
        "containerName": name,
        "evidence": evidence,
        "protocolManifestSha256": manifest_sha,
        "preflightLicenseSha256": license_sha,
        "sourceReviewReceiptSha256": review_sha,
        "claimSha256": claim_sha,
        "resourcePlan": plan,
        "resourcePlanSha256": preflight_verify.resource_plan_digest(plan),
        "stageRelativePath": plan["stageRelativePath"],
        "stageDir": str(evidence / ("stage-" + tag)),
        "stageIdentity": None,
        "stageBuildState": "not-created",
        "container": {
            "containerId": None,
            "containerName": name,
            "tag": tag,
            "image": IMAGE,
            "containerCreated": False,
            "createState": "not-attempted",
        },
        "client": {
            "role": "client", "spawnState": "not-started", "pid": None,
            "identity": None, "identityPersisted": False,
        },
        "observer": {
            "role": "observer", "spawnState": "not-started", "pid": None,
            "identity": None, "identityPersisted": False,
        },
        "journals": {},
        "timestamps": {},
        "persistFailure": None,
    }
    if binding is not None:
        context.update({
            "observationProtocol": OBSERVATION_PROTOCOL,
            "framingPolicy": FRAMING_POLICY,
            "bufferParserSha256": binding.get(BUFFER_PARSER_NAME),
            "bufferTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
            "frozenTemplateName": BUFFER_TEMPLATE_NAME,
            "frozenTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
        })
    return context


def persist_json(context, relative, value):
    """Create one evidence file and record its bytes digest in the context."""
    path = context["evidence"] / relative
    try:
        stored, digest = guard.write_new_json_document(path, value)
    except BaseException as error:
        context["persistFailure"] = {
            "file": relative,
            "error": type(error).__name__,
            "at": now(),
        }
        raise
    context["journals"][relative] = digest
    context["timestamps"][relative] = now()
    return stored, digest


def persist_bytes(context, relative, payload):
    path = context["evidence"] / relative
    try:
        digest = guard.write_new_bytes(path, payload)
    except BaseException as error:
        context["persistFailure"] = {
            "file": relative,
            "error": type(error).__name__,
            "at": now(),
        }
        raise
    context["journals"][relative] = digest
    context["timestamps"][relative] = now()
    return digest


def bounded_result(result, limit=4096):
    return {
        "returncode": result.returncode,
        "stdout": (result.stdout or "")[:limit],
        "stderr": (result.stderr or "")[:limit],
    }


def context_summary(context):
    if not isinstance(context, dict):
        return None
    return {
        "preflightId": context.get("preflightId"),
        "tag": context.get("tag"),
        "containerName": context.get("containerName"),
        "resourcePlan": context.get("resourcePlan"),
        "resourcePlanSha256": context.get("resourcePlanSha256"),
        "stageRelativePath": context.get("stageRelativePath"),
        "stageDir": context.get("stageDir"),
        "stageIdentity": context.get("stageIdentity"),
        "stageBuildState": context.get("stageBuildState"),
        "container": dict(context.get("container") or {}),
        "client": dict(context.get("client") or {}),
        "observer": dict(context.get("observer") or {}),
        "persistFailure": context.get("persistFailure"),
        "journals": dict(context.get("journals") or {}),
    }


# ------------------------------------------------------------------ claim / lock
def claim_record(preflight_id, license_sha, evidence, manifest_sha, review_sha, plan,
                 binding=None):
    record = {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-claim",
        "state": "consumed",
        "preflightId": preflight_id,
        "preflightLicenseSha256": license_sha,
        "protocolManifestSha256": manifest_sha,
        "sourceReviewReceiptSha256": review_sha,
        "evidenceDir": "preflight/evidence/" + preflight_id,
        "evidencePath": str(evidence),
        "resourcePlan": plan,
        "resourcePlanSha256": preflight_verify.resource_plan_digest(plan),
        "consumedAt": now(),
        "targetExecutions": 0,
        "fixturesImported": 0,
    }
    if binding is not None:
        record.update({
            "observationProtocol": OBSERVATION_PROTOCOL,
            "framingPolicy": FRAMING_POLICY,
            "bufferParserSha256": binding.get(BUFFER_PARSER_NAME),
            "bufferTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
            "frozenTemplateName": BUFFER_TEMPLATE_NAME,
            "frozenTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
        })
    return record


def consume_claim(preflight_id, license_sha, evidence, manifest_sha, review_sha, plan,
                  binding=None):
    """Consume first, create the evidence directory second.

    The claim is the durable one-use registration and binds the original
    resource plan before any stage, container or process exists.  A crash after
    this write but before the directory exists is ``unknown-outcome`` and never
    a pass.
    """
    reason = preflight_verify.resource_plan_reason(plan, preflight_id)
    if reason:
        raise PreflightFailure("preflight-" + reason)
    claim_path, _completed_path = preflight_verify.claim_paths(ROOT, preflight_id)
    claim_state = guard.path_state(claim_path)
    if claim_state["state"] == "present":
        raise PreflightFailure("preflight-license-consumed", str(claim_path))
    if claim_state["state"] == "unknown":
        raise PreflightFailure("preflight-claim-query", str(claim_path))
    evidence_state = guard.path_state(evidence)
    if evidence_state["state"] == "present":
        # An old evidence directory without a consumed claim must not be
        # adopted or auto-completed.
        raise PreflightFailure("preflight-evidence-untracked", str(evidence))
    if evidence_state["state"] == "unknown":
        raise PreflightFailure("preflight-evidence-query", str(evidence))
    try:
        claim, claim_sha = guard.write_new_json_document(
            claim_path,
            claim_record(preflight_id, license_sha, evidence, manifest_sha, review_sha,
                         plan, binding=binding),
        )
    except FileExistsError:
        raise PreflightFailure("preflight-license-consumed", str(claim_path)) from None
    try:
        evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    except BaseException:
        raise PreflightFailure("preflight-evidence-create", str(evidence)) from None
    return claim, claim_sha


def mark_claim_completed(preflight_id, claim_sha, receipt_sha, binding=None):
    _claim_path, completed_path = preflight_verify.claim_paths(ROOT, preflight_id)
    record = {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-claim-completed",
        "state": "completed",
        "preflightId": preflight_id,
        "claimSha256": claim_sha,
        "preflightReceiptSha256": receipt_sha,
        "completedAt": now(),
        "targetExecutions": 0,
        "fixturesImported": 0,
    }
    if binding is not None:
        record.update({
            "observationProtocol": OBSERVATION_PROTOCOL,
            "framingPolicy": FRAMING_POLICY,
            "bufferParserSha256": binding.get(BUFFER_PARSER_NAME),
            "bufferTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
            "frozenTemplateName": BUFFER_TEMPLATE_NAME,
            "frozenTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
        })
    guard.write_new_json_document(completed_path, record)


# ------------------------------------------------------------------------ stage
def build_stage(context):
    """Build the fixed tool tree; every partial step is traceable.

    ``stage-intent.json`` is persisted before the directory exists.
    ``stage-started.json`` records the lstat identity immediately after the
    directory is created.  A failure after that point leaves a partial stage
    that cleanup/recover must retain (not silently delete) until it is proven.
    """
    evidence = context["evidence"]
    tag = context["tag"]
    stage = evidence / ("stage-" + tag)
    tools = stage / "tools"
    context["stageDir"] = str(stage)
    state = guard.path_state(stage)
    if state["state"] == "present":
        raise PreflightFailure("preflight-stage-exists", str(stage))
    if state["state"] == "unknown":
        raise PreflightFailure("preflight-stage-query", str(stage))
    persist_json(context, "stage-intent.json", {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-stage-intent",
        "preflightId": context["preflightId"],
        "tag": tag,
        "stageDir": str(stage),
        "toolsDir": str(tools),
        "plannedTools": list(FIXED_TOOLS),
        "resourcePlan": context["resourcePlan"],
        "resourcePlanSha256": context["resourcePlanSha256"],
        "createdAt": now(),
    })
    tools.mkdir(parents=True, mode=0o755)
    stage.chmod(0o755)
    identity = guard.stage_identity(stage)
    if identity is None or identity.get("error"):
        raise PreflightFailure("preflight-stage-identity")
    context["stageIdentity"] = identity
    context["stageBuildState"] = "partial"
    persist_json(context, "stage-started.json", {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-stage-started",
        "preflightId": context["preflightId"],
        "stageDir": str(stage),
        "stageIdentity": identity,
        "createdAt": now(),
    })
    for name in FIXED_TOOLS:
        source = TOOLS / name
        if not source.is_file() or os.path.islink(source):
            raise PreflightFailure("preflight-tool:" + name)
        (tools / name).write_bytes(source.read_bytes())
        (tools / name).chmod(0o444)
    tools.chmod(0o555)
    stage.chmod(0o555)
    identity = guard.stage_identity(stage)
    if identity is None or identity.get("error"):
        raise PreflightFailure("preflight-stage-identity")
    names = {path.name for path in tools.iterdir()}
    if names != set(FIXED_TOOLS):
        raise PreflightFailure("preflight-mount-set")
    for forbidden in ("experiment-plan.json", "target_launcher.py", "experiment_compile.py",
                      "sce_echo_sink.py", "sce_quoted_sink.py", "sce_raw_sink.py", "sce_two_sites.py"):
        if any(forbidden in str(path) for path in stage.rglob("*")):
            raise PreflightFailure("preflight-forbidden-input:" + forbidden)
    context["stageIdentity"] = identity
    context["stageBuildState"] = "created"
    mounts = {str(tools): "/review/preflight"}
    persist_json(context, "stage-created.json", {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-stage-created",
        "preflightId": context["preflightId"],
        "tag": tag,
        "stageDir": str(stage),
        "stageIdentity": identity,
        "mounts": [{"source": source, "destination": destination, "readonly": True}
                   for source, destination in sorted(mounts.items())],
        "createdAt": now(),
    })
    return mounts


# -------------------------------------------------------------------- container
def verify_container_config(container):
    if container is None:
        return "container-shape"
    if container.get("image") != IMAGE:
        return "container-image"
    if container.get("user") != "%s:%s" % (TARGET_UID, TARGET_GID):
        return "container-user"
    if container.get("entrypoint") != [INTERPRETER]:
        return "container-entrypoint"
    host = container.get("hostConfig") or {}
    if host.get("NetworkMode") != "none":
        return "container-network"
    if host.get("ReadonlyRootfs") is not True:
        return "container-readonly"
    if "ALL" not in (host.get("CapDrop") or []):
        return "container-caps"
    if not any(str(item).startswith("no-new-privileges") for item in host.get("SecurityOpt") or []):
        return "container-privileges"
    if host.get("Memory") != LIMITS["memoryMiB"] * 1024 * 1024:
        return "container-memory"
    if host.get("PidsLimit") != LIMITS["pids"]:
        return "container-pids"
    tmp = str((host.get("Tmpfs") or {}).get("/tmp", ""))
    if "size=%dm" % LIMITS["tmpMiB"] not in tmp or "nosuid" not in tmp or "nodev" not in tmp:
        return "container-tmpfs"
    return None


def verify_mounts(container, expected):
    observed = {}
    for entry in container.get("mounts") or []:
        if type(entry) is not dict:
            return "mount-shape"
        if entry.get("Type") == "tmpfs" or entry.get("Destination") == "/tmp":
            continue
        destination = entry.get("Destination")
        if entry.get("Type") != "bind" or entry.get("RW") is not False:
            return "mount-not-readonly:" + str(destination)
        observed[destination] = entry.get("Source")
    expected_by_destination = {destination: source for source, destination in expected.items()}
    if set(observed) != set(expected_by_destination):
        return "mount-set"
    for destination, source in expected_by_destination.items():
        if observed[destination] != str(source):
            return "mount-source:" + destination
    return None


def create_container(context, mounts):
    """Create the one preflight container, registering presence immediately."""
    name = context["containerName"]
    tag = context["tag"]
    evidence = context["evidence"]
    preflight_id = context["preflightId"]
    lookup = guard.container_lookup(name)
    if lookup["state"] == "present":
        context["container"]["createState"] = "name-conflict-unknown"
        raise PreflightFailure("preflight-container-name-conflict")
    if lookup["state"] != "absent":
        context["container"]["createState"] = "name-query-unknown"
        raise PreflightFailure("preflight-container-name-query")
    args = [
        "create",
        "--name", name,
        "--interactive",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", "%dm" % LIMITS["memoryMiB"],
        "--memory-swap", "%dm" % LIMITS["memoryMiB"],
        "--cpus", str(LIMITS["cpus"]),
        "--pids-limit", str(LIMITS["pids"]),
        "--user", "%s:%s" % (TARGET_UID, TARGET_GID),
        "--tmpfs", "/tmp:rw,size=%dm,nosuid,nodev,noexec" % LIMITS["tmpMiB"],
        "--hostname", "stdlib-cli-experiment",
        "--label", "sce.tag=" + tag,
        "--label", "sce.role=preflight",
    ]
    for source, destination in sorted(mounts.items()):
        args.extend(["--mount", "type=bind,src=%s,dst=%s,readonly" % (source, destination)])
    for key, value in ALLOWED_ENV.items():
        args.extend(["--env", "%s=%s" % (key, value)])
    args.extend(["--entrypoint", INTERPRETER, IMAGE,
                 "-I", "-B", "-S", "/review/preflight/preflight_selfcheck.py",
                 "--preflight-id", preflight_id])
    persist_json(context, "container-intent.json", {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-container-intent",
        "preflightId": preflight_id,
        "tag": tag,
        "containerName": name,
        "imageId": IMAGE,
        "entrypoint": INTERPRETER,
        "interactive": True,
        "mounts": [{"source": source, "destination": destination, "readonly": True}
                   for source, destination in sorted(mounts.items())],
        "resourcePlan": context["resourcePlan"],
        "resourcePlanSha256": context["resourcePlanSha256"],
        "argv": list(args),
        "createdAt": now(),
    })
    result = guard.docker(*args)
    stdout_lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    created_id = stdout_lines[-1] if stdout_lines else None
    if created_id is not None and not FULL_ID_RE.fullmatch(created_id):
        created_id = None
    # Put the handle into the shared context immediately, before any inspect or
    # journal I/O can fail.  A non-zero result is never "never-created".
    if created_id is not None:
        context["container"]["containerId"] = created_id
        context["container"]["createState"] = "created-identity-pending"
    else:
        context["container"]["createState"] = "create-result-unknown"
    if result.returncode != 0:
        after = guard.container_lookup(name)
        tag_lookup = guard.container_tag_lookup(tag)
        context["container"]["createState"] = (
            "create-conflict-unknown" if after["state"] == "present"
            else "create-result-unknown"
        )
        try:
            persist_json(context, "container-create-failure.json", {
                "version": CONTEXT_VERSION,
                "protocolRevision": PROTOCOL_REVISION,
                "kind": "zero-target-preflight-container-create-failure",
                "preflightId": preflight_id,
                "tag": tag,
                "containerName": name,
                "createQuery": bounded_result(result),
                "nameQuery": after,
                "tagQuery": tag_lookup,
                "recordedAt": now(),
            })
        except BaseException:
            pass
        if after["state"] == "present":
            raise PreflightFailure("preflight-container-name-conflict")
        if after["state"] == "absent" and tag_lookup["state"] == "absent":
            context["container"]["createState"] = "not-created"
        raise PreflightFailure("preflight-create:" + (result.stderr or "")[-200:])
    if created_id is None:
        try:
            persist_json(context, "container-create-failure.json", {
                "version": CONTEXT_VERSION,
                "protocolRevision": PROTOCOL_REVISION,
                "kind": "zero-target-preflight-container-create-failure",
                "preflightId": preflight_id,
                "tag": tag,
                "containerName": name,
                "createQuery": bounded_result(result),
                "recordedAt": now(),
            })
        except BaseException:
            pass
        raise PreflightFailure("preflight-container-id")
    lookup = guard.container_lookup(created_id)
    if lookup["state"] != "present":
        raise PreflightFailure("preflight-create-unconfirmed")
    container = guard.parse_container(lookup["container"])
    if container is None or container.get("id") != created_id:
        raise PreflightFailure("preflight-container-id")
    reason = guard.container_identity_matches(container, created_id, name, tag, IMAGE)
    if reason:
        context["container"]["createState"] = "identity-mismatch"
        raise PreflightFailure("preflight-container-identity:" + reason)
    reason = verify_container_config(container)
    if reason:
        context["container"]["createState"] = "config-mismatch"
        raise PreflightFailure(reason)
    reason = verify_mounts(container, mounts)
    if reason:
        context["container"]["createState"] = "mount-mismatch"
        raise PreflightFailure(reason)
    context["container"].update({
        "containerId": container["id"],
        "containerCreated": True,
        "createState": "created",
    })
    persist_json(context, "container-created.json", {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-container-created",
        "preflightId": preflight_id,
        "containerId": container["id"],
        "containerName": name,
        "tag": tag,
        "imageId": IMAGE,
        "entrypoint": INTERPRETER,
        "interactive": True,
        "mounts": [{"source": source, "destination": destination, "readonly": True}
                   for source, destination in sorted(mounts.items())],
        "resourcePlan": context["resourcePlan"],
        "resourcePlanSha256": context["resourcePlanSha256"],
        "createQuery": bounded_result(result),
        "createdAt": now(),
    })
    return container


def config_target_pid(context, identifier):
    argv = ["inspect", "--type", "container", "-f", "{{.State.Pid}}", identifier]
    result = guard.docker(*argv)
    text = (result.stdout or "").strip()
    pid = int(text) if result.returncode == 0 and text.isdigit() and int(text) > 0 else None
    record = {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-container-pid",
        "preflightId": context["preflightId"],
        "containerId": context["container"].get("containerId"),
        "containerName": context["containerName"],
        "tag": context["tag"],
        "argv": ["docker"] + argv,
        "query": bounded_result(result),
        "targetPid": pid,
        "recordedAt": now(),
    }
    persist_json(context, "container-pid.json", record)
    if pid is None:
        raise PreflightFailure("preflight-container-pid")
    return pid


# --------------------------------------------------------------------- process
def spawn_process(context, role, argv):
    """Persist intent, spawn, retain the handle immediately, then journal identity."""
    evidence = context["evidence"]
    runtime = context.get("_diagnostics")
    if not isinstance(runtime, diagnostics.InvocationRuntime):
        runtime = diagnostics.runtime_from_context(context)
        context["_diagnostics"] = runtime
    persist_json(context, "process-" + role + "-intent.json", {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-process-intent",
        "preflightId": context["preflightId"],
        "role": role,
        "spawnState": "spawn-attempted",
        "argv": list(argv),
        "recordedAt": now(),
    })
    try:
        process = subprocess.Popen(
            list(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
        )
    except BaseException as error:
        runtime.attach_failure(role, error)
        context[role].update({"spawnState": "not-started", "pid": None,
                              "identity": None, "identityPersisted": False})
        try:
            persist_json(context, "process-" + role + "-failed.json", {
                "version": CONTEXT_VERSION,
                "protocolRevision": PROTOCOL_REVISION,
                "kind": "zero-target-preflight-process-state",
                "preflightId": context["preflightId"],
                "role": role,
                "spawnState": "not-started",
                "reason": type(error).__name__,
                "recordedAt": now(),
            })
        except BaseException:
            pass
        raise PreflightFailure("preflight-spawn:" + role + ":" + type(error).__name__)
    # Retain the already-owned handle and both bounded drains *before* any
    # identity-journal write can fail.  Python objects stay in runtime, never
    # in the JSON context.
    runtime.attach_process(role, process, argv)
    # The outer context learns about the process handle *now*.
    context[role].update({
        "pid": process.pid,
        "spawnState": "started",
        "identity": None,
        "identityPersisted": False,
        "reason": None,
    })
    identity = guard.process_identity(process.pid)
    context[role]["identity"] = identity
    if identity is None:
        context[role].update({"spawnState": "unknown", "reason": "identity-unreadable"})
    record = {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-process-state",
        "preflightId": context["preflightId"],
        "role": role,
        "pid": process.pid,
        "spawnState": context[role]["spawnState"],
        "identity": identity,
        "reason": context[role].get("reason"),
        "recordedAt": now(),
    }
    try:
        persist_json(context, "process-" + role + "-identity.json", record)
    except BaseException:
        context[role]["identityPersisted"] = False
        raise PreflightFailure("preflight-identity-journal:" + role) from None
    context[role]["identityPersisted"] = True
    if identity is None:
        raise PreflightFailure("preflight-" + role + "-identity")
    return process


# ---------------------------------------------------------------------- config
def parse_config_line(data):
    prefix = b"PREFLIGHT-CONFIG "
    for line in data.splitlines():
        if line.startswith(prefix):
            try:
                return json.loads(line[len(prefix):])
            except ValueError:
                return None
    return None


def verify_config(config, profile, profile_sha, preflight_id):
    if type(config) is not dict:
        raise PreflightFailure("preflight-config-missing")
    if config.get("kind") != "zero-target-preflight-config":
        raise PreflightFailure("preflight-config-kind")
    if config.get("protocolRevision") != PROTOCOL_REVISION:
        raise PreflightFailure("preflight-config-revision")
    if config.get("preflightId") != preflight_id:
        raise PreflightFailure("preflight-config-id")
    if config.get("callerPath") != CALLER_PATH:
        raise PreflightFailure("preflight-config-path")
    source = TOOLS / "preflight_selfcheck.py"
    if config.get("sourceSha256") != guard.sha_file(source):
        raise PreflightFailure("preflight-config-source")
    if type(config.get("callOffset")) is not int or config["callOffset"] < 0:
        raise PreflightFailure("preflight-config-offset")
    if config.get("intZeroTag") != 1:
        raise PreflightFailure("preflight-int-zero-tag")
    if not HASH_RE.fullmatch(config.get("callerSha256") or ""):
        raise PreflightFailure("preflight-caller-digest")
    if config.get("profileSha256") != profile_sha:
        raise PreflightFailure("preflight-config-profile")
    if config.get("profile") != preflight_verify.profile_identity(profile):
        raise PreflightFailure("preflight-config-profile-identity")
    if config.get("pythonVersion") != profile["pythonVersion"]:
        raise PreflightFailure("preflight-python")
    if config.get("interpreterSha256") != profile["interpreterSha256"]:
        raise PreflightFailure("preflight-interpreter")
    if config.get("librarySha256") != profile["librarySha256"]:
        raise PreflightFailure("preflight-library")
    expected_structure = config.get("expectedStructure")
    if not isinstance(expected_structure, dict):
        raise PreflightFailure("preflight-expected")
    try:
        structure_sha = structure.structure_digest(expected_structure)
        code_sha = structure.code_digest_from_structure(expected_structure)
    except (KeyError, TypeError, ValueError, structure.StructureUnsupported) as error:
        raise PreflightFailure("preflight-expected-structure:" + type(error).__name__) from None
    if structure_sha != config.get("expectedStructureSha256"):
        raise PreflightFailure("preflight-expected-digest")
    if code_sha != config.get("expectedCodeSha256"):
        raise PreflightFailure("preflight-expected-code")
    config_layout = config.get("layout")
    if type(config_layout) is not dict:
        raise PreflightFailure("preflight-layout")
    if type(config_layout.get("offsets")) is not dict:
        raise PreflightFailure("preflight-layout-offsets")
    if type(config_layout.get("frameOffsets")) is not dict:
        raise PreflightFailure("preflight-layout-frame")
    return config


def build_layout(config, profile, profile_sha, manifest_sha, preflight_id):
    return {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-layout",
        "state": "measured",
        "preflightId": preflight_id,
        "protocolManifestSha256": manifest_sha,
        "candidateManifestSha256": manifest_sha,
        "profileSha256": profile_sha,
        "runtime": preflight_verify.profile_identity(profile),
        "imageId": profile["imageId"],
        "pythonVersion": profile["pythonVersion"],
        "offsets": config["layout"]["offsets"],
        "frameOffsets": config["layout"]["frameOffsets"],
        "intZeroTag": config["intZeroTag"],
        "source": "preflight-selfcheck",
        "createdAt": now(),
    }


# --------------------------------------------------------------------- collect
def collect(evidence, raw_path, config, tag, target_pid):
    observation_path = evidence / "observation.json"
    state = guard.path_state(observation_path)
    if state["state"] == "present":
        raise PreflightFailure("preflight-observation-exists")
    if state["state"] == "unknown":
        raise PreflightFailure("preflight-observation-query")
    result = subprocess.run(
        [
            sys.executable, str(TOOLS / "collect_observer.py"),
            "--observation-protocol", OBSERVATION_PROTOCOL,
            "--framing-policy", FRAMING_POLICY,
            "--raw", str(raw_path),
            "--run-id", RUN_ID,
            "--tag", tag,
            "--caller-path", CALLER_PATH,
            "--call-offset", str(config["callOffset"]),
            "--target-pid", str(target_pid),
            "--target-uid", TARGET_UID,
            "--max-events", "4",
            "--out", str(observation_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise PreflightFailure("preflight-collector-exit:%d" % result.returncode,
                               (result.stderr or result.stdout or "")[-200:])
    if not observation_path.is_file() or os.path.islink(observation_path):
        raise PreflightFailure("preflight-collector-product-missing")
    observation, observation_sha = guard.read_json(observation_path)
    return observation, observation_sha, result.returncode


def verify_observation(stored, observation_sha, raw_bytes, raw_sha, config, tag,
                       target_pid, template_sha, binding, observer_bytes,
                       template_bytes, layout, layout_sha, profile_sha):
    """Recompute from the original raw bytes and rebuild the actual observer.

    A stored ``state``/``complete`` value is never accepted as proof.  This is
    the producer-side independent check; ``preflight_verify`` repeats it from
    the frozen files later.
    """
    parser_sha = binding.get(BUFFER_PARSER_NAME)
    buffer_template_sha = binding.get(BUFFER_TEMPLATE_NAME)
    recomputed = buffer_protocol_v2.parse_receipt(
        raw_bytes, RUN_ID, tag, CALLER_PATH, config["callOffset"],
        target_pid, preflight_verify.TARGET_UID, max_events=4,
        raw_truncated=False, require_events=1,
    )
    if stored != recomputed:
        raise PreflightFailure("preflight-observation-mismatch")
    if recomputed.get("protocol") != OBSERVATION_PROTOCOL:
        raise PreflightFailure("preflight-observation-protocol")
    if recomputed.get("framingPolicy") != FRAMING_POLICY:
        raise PreflightFailure("preflight-observation-framing-policy")
    if type(recomputed.get("trailingBlankLines")) is not int or not (
            0 <= recomputed["trailingBlankLines"] <= 8):
        raise PreflightFailure("preflight-observation-trailing-blank-lines")
    if recomputed.get("targetExecuted") is not False:
        raise PreflightFailure("preflight-target-executed")
    if recomputed.get("state") != "complete":
        raise PreflightFailure("preflight-observation-state")
    if len(recomputed.get("events") or []) != 1:
        raise PreflightFailure("preflight-observation-events")
    event = recomputed["events"][0]
    if event.get("callerOffset") != config["callOffset"]:
        raise PreflightFailure("preflight-caller-offset")
    if event.get("callerSha256") != config["callerSha256"]:
        raise PreflightFailure("preflight-caller-sha")
    try:
        structure_sha = structure.structure_digest(event.get("dynamicStructure"))
        code_sha = structure.code_digest_from_structure(event.get("dynamicStructure"))
        caller_sha = structure.structure_digest(event.get("callerDescriptor"))
    except (KeyError, TypeError, ValueError, AttributeError,
            structure.StructureUnsupported) as error:
        raise PreflightFailure(
            "preflight-structure-recompute:" + type(error).__name__
        ) from None
    if structure_sha != event.get("dynamicStructureSha256"):
        raise PreflightFailure("preflight-structure-self-digest")
    if code_sha != event.get("dynamicCodeSha256"):
        raise PreflightFailure("preflight-code-self-digest")
    if caller_sha != event.get("callerSha256"):
        raise PreflightFailure("preflight-caller-self-digest")
    if event.get("dynamicStructureSha256") != config.get("expectedStructureSha256"):
        raise PreflightFailure("preflight-structure")
    if event.get("dynamicCodeSha256") != config.get("expectedCodeSha256"):
        raise PreflightFailure("preflight-code")
    consts = (event.get("dynamicStructure") or {}).get("consts") or []
    if {"t": "int", "v": 0} not in consts:
        raise PreflightFailure("preflight-int-zero")
    if recomputed.get("beginCount") != 1 or recomputed.get("endCount") != 1:
        raise PreflightFailure("preflight-markers")
    if recomputed.get("markerCount") != 1 or recomputed.get("marker") != buffer_protocol_v2.MARKER:
        raise PreflightFailure("preflight-buffer-marker")
    if recomputed.get("begin") != "run=%s tag=%s" % (RUN_ID, tag):
        raise PreflightFailure("preflight-begin")
    if recomputed.get("end") != "run=%s tag=%s events=1" % (RUN_ID, tag):
        raise PreflightFailure("preflight-end")
    if recomputed.get("rawSha256") != raw_sha:
        raise PreflightFailure("preflight-raw")
    if sha_file_bytes(observer_bytes) != template_sha:
        raise PreflightFailure("preflight-observer-digest")
    try:
        rebuilt = observer_render.render(
            template_bytes, layout, layout_sha, profile_sha, RUN_ID, tag,
            CALLER_PATH, config["callOffset"], target_pid,
            preflight_verify.TARGET_UID, PROFILE_NAME,
        )
    except observer_render.RenderError as error:
        raise PreflightFailure("preflight-observer-render:" + str(error)) from None
    if rebuilt != observer_bytes:
        raise PreflightFailure("preflight-observer-rebuild")
    return {
        "complete": True,
        "events": 1,
        "observationProtocol": OBSERVATION_PROTOCOL,
        "framingPolicy": FRAMING_POLICY,
        "trailingBlankLines": recomputed.get("trailingBlankLines"),
        "bufferParserSha256": parser_sha,
        "bufferTemplateSha256": buffer_template_sha,
        "frozenTemplateName": BUFFER_TEMPLATE_NAME,
        "frozenTemplateSha256": buffer_template_sha,
        "observerRebuildVerified": True,
        "rawSha256": raw_sha,
        "rawBytes": len(raw_bytes),
        "observerSha256": template_sha,
        "observationSha256": observation_sha,
        "intZero": True,
        "callerOffsetVerified": True,
        "structureVerified": True,
        "structureSha256": structure_sha,
        "codeSha256": code_sha,
        "callerSha256": caller_sha,
        "endComplete": True,
        "begin": recomputed.get("begin"),
        "end": recomputed.get("end"),
        "marker": recomputed.get("marker"),
        "beginCount": 1,
        "endCount": 1,
        "markerCount": 1,
        "errors": [],
    }


def sha_file_bytes(payload):
    return guard.sha_bytes(payload)


# --------------------------------------------------------------------- cleanup
def _process_cleanup(record):
    if not isinstance(record, dict):
        return {"state": "unknown", "detail": "record-missing", "identity": None}
    spawn_state = record.get("spawnState")
    if spawn_state == "not-started":
        return {"state": "exited", "proof": "not-started", "identity": record.get("identity")}
    identity = record.get("identity")
    if record.get("identityPersisted") is not True or not isinstance(identity, dict):
        return {
            "state": "unknown",
            "detail": "identity-journal-unpersisted" if spawn_state == "started"
            else "spawn-state:" + str(spawn_state),
            "identity": identity,
        }
    state = guard.spawn_group_state(record)
    if state.get("state") == "alive":
        stop = guard.stop_group(identity, graceful=3, term=2)
        state = guard.spawn_group_state(record)
        return {**state, "stop": stop, "identity": identity}
    return {**state, "identity": identity}


def _cleanup_container(context):
    record = dict(context.get("container") or {})
    create_state = record.get("createState")
    full_id = record.get("containerId")
    name = record.get("containerName")
    tag = record.get("tag")
    if create_state == "not-attempted":
        by_name = guard.container_lookup(name) if name else {"state": "unknown", "detail": "no-name"}
        by_tag = guard.container_tag_lookup(tag) if tag else {"state": "unknown", "detail": "no-tag"}
        queries = {"name": by_name, "tag": by_tag}
        if by_name.get("state") == "absent" and by_tag.get("state") == "absent":
            return {"removed": True, "state": "never-created", "queries": queries}
        return {"removed": False, "state": "unknown", "detail": "unexpected-container",
                "queries": queries}
    if isinstance(full_id, str) and FULL_ID_RE.fullmatch(full_id):
        before = guard.verify_own_container_present(record)
        removal = guard.remove_container_verified({**record, "containerCreated": True})
        return {**removal, "beforeRemoval": before}
    by_name = guard.container_lookup(name) if name else {"state": "unknown", "detail": "no-name"}
    by_tag = guard.container_tag_lookup(tag) if tag else {"state": "unknown", "detail": "no-tag"}
    queries = {"name": by_name, "tag": by_tag}
    if by_name.get("state") == "absent" and by_tag.get("state") == "absent":
        return {"removed": True, "state": "never-created", "queries": queries}
    return {"removed": False,
            "state": "unknown" if (by_name.get("state") != "absent"
                                   or by_tag.get("state") != "absent") else "present",
            "detail": "create-attempt-without-identity", "queries": queries}


def _stage_lstat(stage_dir):
    if not stage_dir:
        return {"state": "absent", "detail": "no-path"}
    return guard.path_state(str(stage_dir))


def _cleanup_stage(context, resources_clear):
    """One tri-state stage decision shared with recovery.

    A stage is successfully removed only when the *final* lstat is ``absent``.
    ``removed=True`` with a present/unknown recheck is never a success.
    """
    stage_dir = context.get("stageDir")
    identity = context.get("stageIdentity")
    build_state = context.get("stageBuildState")
    state = _stage_lstat(stage_dir)
    lstat_after = state["state"] if state["state"] in ("absent", "present") else "unknown"
    base = {"path": stage_dir, "lstatAfter": lstat_after}
    if context.get("persistFailure"):
        return {**base, "removed": False, "state": "persistence-failed"}
    if build_state in ("not-created", "not-attempted"):
        if state["state"] == "present":
            return {**base, "removed": False, "state": "unexpected-stage"}
        if state["state"] == "unknown":
            return {**base, "removed": False, "state": "unknown-stage-query",
                    "detail": state["detail"]}
        return {**base, "removed": True, "state": "never-created"}
    if build_state == "partial":
        return {**base, "removed": False, "state": "partial-build-retained",
                "stageIdentity": identity}
    if not resources_clear:
        return {**base, "removed": False, "state": "retained-resources-unresolved",
                "stageIdentity": identity}
    if (not isinstance(identity, dict) or identity.get("error")
            or "dev" not in identity or "ino" not in identity):
        if state["state"] == "absent":
            return {**base, "removed": True, "state": "absent"}
        return {**base, "removed": False, "state": "identity-missing"}
    if state["state"] == "absent":
        # A stage path that is already gone is an explicit absence result, not
        # a missing key.  This is the normal second-cleanup case.
        return {**base, "removed": True, "state": "absent"}
    if state["state"] == "unknown":
        return {**base, "removed": False, "state": "lstat-error",
                "detail": state["detail"]}
    if state["state"] != "present":
        return {**base, "removed": False, "state": "unknown-stage-query",
                "detail": state["detail"]}
    if state["symlink"]:
        return {**base, "removed": False, "state": "symlink"}
    if not state["isDir"]:
        return {**base, "removed": False, "state": "not-directory"}
    result = guard.cleanup_stage(str(stage_dir), identity)
    final = _stage_lstat(stage_dir)
    result["path"] = stage_dir
    result["stageIdentity"] = identity
    if final["state"] == "absent":
        result["lstatAfter"] = "absent"
        if result.get("removed") is not True:
            result["removed"] = False
    elif final["state"] == "present":
        result["lstatAfter"] = "present"
        result["removed"] = False
        result["state"] = "still-present"
    else:
        result["lstatAfter"] = "unknown"
        result["removed"] = False
        result["state"] = "lstat-error"
        result["detail"] = final["detail"]
    return result


def cleanup_resources(context):
    """Clean only resources whose identity and exit are independently proved."""
    if not isinstance(context, dict):
        return {"confirmed": False, "state": "context-missing", "at": now()}
    runtime = context.get("_diagnostics")
    if not isinstance(runtime, diagnostics.InvocationRuntime):
        runtime = None
    if runtime is not None:
        # Poll before any deliberate cleanup is requested.  This snapshot is
        # evidence only; it never replaces group-identity checks or authorizes
        # a signal.
        runtime.snapshot_polls("before-cleanup")
    client_state = _process_cleanup(context.get("client"))
    observer_state = _process_cleanup(context.get("observer"))
    if runtime is not None:
        for role, state in (("client", client_state), ("observer", observer_state)):
            runtime.note_cleanup_signal(role, state.get("stop"))
    container_result = _cleanup_container(context)
    container_clear = container_result.get("removed") is True
    client_clear = client_state.get("state") == "exited"
    observer_clear = observer_state.get("state") == "exited"
    diagnostics_result = None
    if runtime is not None:
        diagnostics_result = runtime.finalize(
            phase=runtime.phase or "cleanup",
            context=context,
            cleanup={"container": container_result, "client": client_state,
                     "observer": observer_state},
        )
        context["diagnostics"] = diagnostics_result
        if diagnostics_result.get("confirmed") is not True and context.get(
                "persistFailure") is None:
            context["persistFailure"] = {
                "file": "process-diagnostics.json",
                "error": diagnostics_result.get("captureError") or "diagnostics-incomplete",
                "source": "observer-diagnostics",
                "at": now(),
            }
    diagnostics_clear = diagnostics_result is None or diagnostics_result.get(
        "confirmed") is True
    resources_clear = (container_clear and client_clear and observer_clear
                       and diagnostics_clear)
    stage_clean = _cleanup_stage(context, resources_clear)
    confirmed = (
        resources_clear
        and diagnostics_clear
        and stage_clean.get("removed") is True
        and stage_clean.get("lstatAfter") == "absent"
        and context.get("persistFailure") is None
    )
    return {
        "confirmed": confirmed,
        "container": container_result,
        "client": {**client_state, "stopped": client_state.get("state") == "exited"},
        "observer": {**observer_state, "stopped": observer_state.get("state") == "exited"},
        "stage": stage_clean,
        "diagnostics": diagnostics_result,
        "persistFailure": context.get("persistFailure"),
        "at": now(),
    }


# ------------------------------------------------------------------- lifecycle
def _finalize_diagnostics(runtime, context, phase):
    """Best-effort idempotent diagnostic finalization; never masks a failure."""
    if runtime is None or getattr(runtime, "finalized", False):
        return
    try:
        result = runtime.finalize(phase=phase, context=context)
        if isinstance(context, dict):
            context["diagnostics"] = result
    except BaseException:
        pass


def write_blocked(context, reason, cleanup=None, extra=None):
    if not isinstance(context, dict):
        return
    evidence = context.get("evidence")
    if evidence is None:
        return
    state = guard.path_state(evidence)
    if state["state"] != "present" or state["symlink"] or not state["isDir"]:
        return
    try:
        diagnostic_fields = diagnostics.additive_fields(context.get("diagnostics"))
        persist_json(context, "failure.json", {
            "version": CONTEXT_VERSION,
            "protocolRevision": PROTOCOL_REVISION,
            "kind": "zero-target-preflight-failure",
            "state": "blocked",
            "preflightId": context.get("preflightId"),
            "protocolManifestSha256": context.get("protocolManifestSha256"),
            "preflightLicenseSha256": context.get("preflightLicenseSha256"),
            "sourceReviewReceiptSha256": context.get("sourceReviewReceiptSha256"),
            "claimSha256": context.get("claimSha256"),
            "reason": reason,
            "cleanup": cleanup or {},
            "resourceContext": context_summary(context),
            "targetExecutions": 0,
            "fixturesImported": 0,
            "generatedAt": now(),
            **(diagnostic_fields or {}),
            **(extra or {}),
        })
    except BaseException:
        pass


def preflight():
    manifest, manifest_sha = verify_manifest()
    binding = buffer_binding()
    license_value, license_sha, review, review_sha, preflight_id = verify_license(
        manifest_sha, binding=binding, require_buffer_protocol=True
    )
    profile, profile_sha = load_profile()

    tag = os.urandom(8).hex()
    if not TAG_RE.fullmatch(tag):
        die(79, "tag")
    name = preflight_verify.fixed_container_name(tag)
    lock = guard.ExclusiveLock(LOCK_PATH)
    if not lock.acquire():
        die(79, "preflight-locked")
    evidence = preflight_verify.evidence_dir(ROOT, preflight_id)
    plan = preflight_verify.resource_plan(preflight_id, tag)
    claim_sha = None
    context = None
    client = None
    observer = None
    runtime = None
    try:
        claim, claim_sha = consume_claim(
            preflight_id, license_sha, evidence, manifest_sha, review_sha, plan,
            binding=binding,
        )
        runtime = diagnostics.InvocationRuntime(
            evidence=evidence,
            preflight_id=preflight_id,
            tag=tag,
            protocol_manifest_sha=manifest_sha,
            candidate_manifest_sha=manifest_sha,
            license_sha=license_sha,
            review_sha=review_sha,
            claim_sha=claim_sha,
            resource_plan=plan,
            resource_plan_sha=preflight_verify.resource_plan_digest(plan),
            limit=LIMITS["outputBytes"],
            profile=profile,
        )
        context = new_context(
            evidence, tag, name, preflight_id, manifest_sha, license_sha,
            review_sha, claim_sha, plan, binding=binding,
        )
        context["_diagnostics"] = runtime
        runtime.bind_context(context)
        persist_json(context, "preflight-intent.json", {
            "version": CONTEXT_VERSION,
            "protocolRevision": PROTOCOL_REVISION,
            "kind": "zero-target-preflight-intent",
            "preflightId": preflight_id,
            "tag": tag,
            "containerName": name,
            "imageId": IMAGE,
            "stageDir": context["stageDir"],
            "stageIdentity": None,
            "mounts": [{"source": str(Path(context["stageDir"]) / "tools"),
                        "destination": "/review/preflight", "readonly": True}],
            "processes": {"client": "not-started", "observer": "not-started"},
            "resourcePlan": context["resourcePlan"],
            "resourcePlanSha256": context["resourcePlanSha256"],
            "observationProtocol": OBSERVATION_PROTOCOL,
            "framingPolicy": FRAMING_POLICY,
            "bufferParserSha256": binding.get(BUFFER_PARSER_NAME),
            "bufferTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
            "frozenTemplateName": BUFFER_TEMPLATE_NAME,
            "frozenTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
            "targetExecutions": 0,
            "fixturesImported": 0,
            "createdAt": now(),
        })
        mounts = build_stage(context)
        container = create_container(context, mounts)
        identifier = container["id"]
        client = spawn_process(context, "client", ["docker", "start", "-a", "-i", identifier])
        if (context["client"].get("spawnState") != "started"
                or context["client"].get("identityPersisted") is not True):
            raise PreflightFailure("preflight-client-identity")
        client_out = runtime.drain("client", "stdout")
        client_err = runtime.drain("client", "stderr")
        config = None
        deadline = time.monotonic() + LIMITS["configTimeoutSeconds"]
        while time.monotonic() < deadline:
            config = parse_config_line(client_out.data())
            if config is not None:
                runtime.milestone("configAcquired", {"source": "client.stdout"})
                break
            if client.poll() is not None:
                runtime.snapshot_poll("client", "config-wait")
                break
            time.sleep(0.05)
        if config is None:
            raise PreflightFailure("preflight-config-missing")
        verify_config(config, profile, profile_sha, preflight_id)
        persist_json(context, "preflight-config.json", config)
        layout = build_layout(config, profile, profile_sha, manifest_sha, preflight_id)
        layout_raw = guard.json_bytes(layout)
        persist_bytes(context, "layout.json", layout_raw)
        layout_sha = context["journals"]["layout.json"]
        layout_structure_sha = structure.structure_digest(layout)
        target_pid = config_target_pid(context, identifier)
        template_path = TOOLS / BUFFER_TEMPLATE_NAME
        if not template_path.is_file() or os.path.islink(template_path):
            raise PreflightFailure("preflight-buffer-template")
        template_bytes = template_path.read_bytes()
        if guard.sha_bytes(template_bytes) != binding.get(BUFFER_TEMPLATE_NAME):
            raise PreflightFailure("preflight-buffer-template-digest")
        rendered = observer_render.render(
            template_bytes, layout, layout_sha, profile_sha, RUN_ID, tag,
            CALLER_PATH, config["callOffset"], target_pid,
            preflight_verify.TARGET_UID, PROFILE_NAME,
        )
        observer_sha = persist_bytes(context, "observer.bt", rendered)
        observer = spawn_process(context, "observer", ["bpftrace", "-q", str(evidence / "observer.bt")])
        if (context["observer"].get("spawnState") != "started"
                or context["observer"].get("identityPersisted") is not True):
            raise PreflightFailure("preflight-observer-identity")
        observer_out = runtime.drain("observer", "stdout")
        observer_err = runtime.drain("observer", "stderr")
        if runtime.observer_ready(
                b"BEGIN ", LIMITS["observerArmTimeoutSeconds"],
                required_lines=(buffer_protocol_v2.MARKER.encode("ascii"),),
        ) is None:
            raise PreflightFailure("preflight-observer-not-armed")
        runtime.milestone("goSendAttempted", {"target": "client.stdin"})
        try:
            client.stdin.write(b"GO\n")
            client.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise PreflightFailure("preflight-go:" + type(error).__name__) from None
        runtime.milestone("goFlushCompleted", {"target": "client.stdin"})
        try:
            client_code = client.wait(timeout=LIMITS["targetTimeoutSeconds"])
        except subprocess.TimeoutExpired:
            raise PreflightFailure("preflight-selfcheck-timeout") from None
        runtime.milestone("clientExited", {"returncode": client_code})
        client_out.finish(5)
        client_err.finish(5)
        if client_code != 0:
            raise PreflightFailure("preflight-selfcheck-exit:%s" % client_code)
        runtime.snapshot_poll("observer", "before-graceful-stop")
        stop_info = guard.stop_group(
            context["observer"]["identity"], graceful=LIMITS["observerStopGraceSeconds"], term=2
        )
        runtime.note_cleanup_signal("observer", stop_info)
        observer_out.finish(5)
        observer_err.finish(5)
        raw = observer_out.data()
        raw_sha = persist_bytes(context, "observer.raw", raw)
        drain_complete = (
            observer_out.drain_complete() and observer_err.drain_complete()
            and client_out.drain_complete() and client_err.drain_complete()
        )
        if observer_out.truncated or observer_err.truncated:
            raise PreflightFailure("preflight-observer-truncated")
        if not drain_complete:
            raise PreflightFailure("preflight-drain-incomplete")
        if stop_info.get("stopped") is not True:
            raise PreflightFailure("preflight-observer-stop:" + str(stop_info.get("state")))
        if stop_info.get("forced") is not False:
            raise PreflightFailure("preflight-observer-forced-stop")
        if stop_info.get("signal") != "SIGINT" or stop_info.get("state") != "exited":
            raise PreflightFailure("preflight-observer-not-graceful")
        observation, observation_sha, collector_code = collect(
            evidence, evidence / "observer.raw", config, tag, target_pid
        )
        persisted_raw = (evidence / "observer.raw").read_bytes()
        if persisted_raw != raw or guard.sha_bytes(persisted_raw) != raw_sha:
            raise PreflightFailure("preflight-raw-persist")
        observer_bytes = (evidence / "observer.bt").read_bytes()
        observation_receipt = verify_observation(
            observation, observation_sha, persisted_raw, raw_sha, config, tag,
            target_pid, observer_sha, binding, observer_bytes, template_bytes,
            layout, layout_sha, profile_sha,
        )
        runtime.set_phase("success")
        cleanup = cleanup_resources(context)
        diagnostic_summary = context.get("diagnostics") or {}
        persist_json(context, "cleanup.json", {
            "version": CONTEXT_VERSION,
            "protocolRevision": PROTOCOL_REVISION,
            "kind": "zero-target-preflight-cleanup",
            "preflightId": preflight_id,
            "tag": tag,
            "containerName": name,
            "containerId": context["container"].get("containerId"),
            "resourcePlan": context["resourcePlan"],
            "resourcePlanSha256": context["resourcePlanSha256"],
            "cleanup": cleanup,
            "recordedAt": now(),
        })
        if diagnostic_summary.get("confirmed") is not True:
            raise PreflightFailure(
                "preflight-diagnostics-unconfirmed",
                detail=diagnostic_summary.get("captureError"),
            )
        if cleanup.get("confirmed") is not True:
            raise PreflightFailure("preflight-cleanup-unconfirmed", cleanup=cleanup)
        receipt = {
            "version": CONTEXT_VERSION,
            "protocolRevision": PROTOCOL_REVISION,
            "kind": "zero-target-preflight-receipt",
            "state": "accepted",
            "preflightId": preflight_id,
            "protocolManifestSha256": manifest_sha,
            "candidateManifestSha256": manifest_sha,
            "claimSha256": claim_sha,
            "resourcePlan": context["resourcePlan"],
            "resourcePlanSha256": context["resourcePlanSha256"],
            "observationProtocol": OBSERVATION_PROTOCOL,
            "framingPolicy": FRAMING_POLICY,
            "bufferParserSha256": binding.get(BUFFER_PARSER_NAME),
            "bufferTemplateSha256": binding.get(BUFFER_TEMPLATE_NAME),
            "preflightLicenseSha256": license_sha,
            "sourceReviewReceiptSha256": review_sha,
            "profileSha256": profile_sha,
            "profile": preflight_verify.profile_identity(profile),
            "imageId": IMAGE,
            "pythonVersion": PYTHON_VERSION,
            "entrypoint": INTERPRETER,
            "interactive": True,
            "network": "none",
            "nonRoot": True,
            "containerName": name,
            "limits": {"memoryMiB": LIMITS["memoryMiB"], "cpus": LIMITS["cpus"],
                       "pids": LIMITS["pids"], "tmpMiB": LIMITS["tmpMiB"],
                       "outputBytes": LIMITS["outputBytes"]},
            "toolDigests": {name_: guard.sha_file(TOOLS / name_) for name_ in FIXED_TOOLS},
            "runtime": {
                "interpreterSha256": profile["interpreterSha256"],
                "librarySha256": profile["librarySha256"],
            },
            "layoutFile": "preflight/evidence/%s/layout.json" % preflight_id,
            "layoutSha256": layout_sha,
            "layoutStructureSha256": layout_structure_sha,
            "preflightConfigSha256": context["journals"].get("preflight-config.json"),
            "frozenTemplateName": BUFFER_TEMPLATE_NAME,
            "frozenTemplateSha256": guard.sha_bytes(template_bytes),
            "observerTemplateSha256": observer_sha,
            "targetPid": target_pid,
            "targetUid": preflight_verify.TARGET_UID,
            "runId": RUN_ID,
            "tag": tag,
            "callerPath": CALLER_PATH,
            "callOffset": config["callOffset"],
            "callerSha256": config["callerSha256"],
            "observation": observation_receipt,
            "collectorExitCode": collector_code,
            "collectorOutputFresh": True,
            "evidenceCreatedNew": True,
            "drainComplete": True,
            "rawTruncated": False,
            "observerStop": stop_info,
            "cleanup": cleanup,
            "evidenceDigests": dict(context["journals"]),
            "preflightIntentSha256": context["journals"].get("preflight-intent.json"),
            "stageIntentSha256": context["journals"].get("stage-intent.json"),
            "stageStartedSha256": context["journals"].get("stage-started.json"),
            "stageCreatedSha256": context["journals"].get("stage-created.json"),
            "containerIntentSha256": context["journals"].get("container-intent.json"),
            "containerCreatedSha256": context["journals"].get("container-created.json"),
            "containerPidSha256": context["journals"].get("container-pid.json"),
            "processClientIntentSha256": context["journals"].get("process-client-intent.json"),
            "processClientIdentitySha256": context["journals"].get("process-client-identity.json"),
            "processObserverIntentSha256": context["journals"].get("process-observer-intent.json"),
            "processObserverIdentitySha256": context["journals"].get("process-observer-identity.json"),
            "cleanupSha256": context["journals"].get("cleanup.json"),
            "diagnosticEvidenceDigests": {
                name: row.get("sha256")
                for name, row in (diagnostic_summary.get("files") or {}).items()
                if isinstance(row, dict) and row.get("written")
            },
            **(diagnostics.additive_fields(diagnostic_summary) or {}),
            "targetExecutions": 0,
            "fixturesImported": 0,
            "realContainers": 1,
            "generatedAt": now(),
        }
        try:
            receipt, receipt_sha = guard.write_new_json_document(
                evidence / "preflight-receipt.json", receipt
            )
        except BaseException as error:
            # A receipt that could not be persisted must not leave a cleanup
            # confirmation behind; the outer handler re-queries the resources.
            context["persistFailure"] = {
                "file": "preflight-receipt.json",
                "error": type(error).__name__,
                "at": now(),
            }
            raise
        try:
            mark_claim_completed(preflight_id, claim_sha, receipt_sha, binding=binding)
        except BaseException as error:
            # The receipt exists but the completed marker does not: status is
            # unknown-outcome and recover may record cleanup only.
            try:
                guard.write_new_json_document(evidence / "completion-failure.json", {
                    "version": CONTEXT_VERSION,
                    "protocolRevision": PROTOCOL_REVISION,
                    "kind": "zero-target-preflight-completion-failure",
                    "preflightId": preflight_id,
                    "claimSha256": claim_sha,
                    "preflightReceiptSha256": receipt_sha,
                    "reason": type(error).__name__,
                    "state": "unknown-outcome",
                    "recordedAt": now(),
                })
            except BaseException:
                pass
            sys.stderr.write("preflight: completion-marker-write-failed\n")
            return 79
        print(json.dumps({"state": "accepted", "preflightId": preflight_id,
                          "receiptSha256": receipt_sha}, sort_keys=True))
        return 0
    except PreflightFailure as error:
        raised_cleanup = error.cleanup if isinstance(error.cleanup, dict) else None
        cleanup = {"confirmed": False, "at": now()}
        if runtime is not None:
            runtime.set_phase("preflight-failure")
            runtime.set_error(error.reason)
        if isinstance(context, dict):
            try:
                cleanup = cleanup_resources(context)
            except Exception as cleanup_error:  # noqa: BLE001 - fail closed
                cleanup["error"] = type(cleanup_error).__name__
            if raised_cleanup is not None:
                # Preserve the cleanup evidence observed by the raising site.
                # A cleanup-unconfirmed failure remains failed and conservative
                # even if a second cleanup trips into a different state.
                cleanup["raised"] = copy.deepcopy(raised_cleanup)
                if error.reason == "preflight-cleanup-unconfirmed":
                    cleanup["confirmed"] = False
            _finalize_diagnostics(runtime, context, "preflight-failure")
            extra = {"detail": error.detail}
            if raised_cleanup is not None:
                extra["cleanupEvidence"] = copy.deepcopy(raised_cleanup)
            write_blocked(context, error.reason, cleanup=cleanup, extra=extra)
        sys.stderr.write("preflight: %s\n" % error.reason)
        return 79
    except BaseException as error:
        cleanup = {"confirmed": False, "at": now()}
        cancelled = isinstance(error, (KeyboardInterrupt, SystemExit))
        if runtime is not None:
            runtime.set_phase("cancelled" if cancelled else "exception")
            runtime.set_error(type(error).__name__ + ":" + str(error)[:160])
        if isinstance(context, dict):
            try:
                cleanup = cleanup_resources(context)
            except Exception as cleanup_error:  # noqa: BLE001
                cleanup["error"] = type(cleanup_error).__name__
            _finalize_diagnostics(runtime, context, runtime.phase or "exception")
            write_blocked(context, type(error).__name__ + ":" + str(error)[:160],
                          cleanup=cleanup)
        if cancelled:
            raise
        sys.stderr.write("preflight: %s:%s\n" % (type(error).__name__, str(error)[:160]))
        return 79
    finally:
        _finalize_diagnostics(runtime, context, runtime.phase or "finally" if runtime else "finally")
        for process in (client, observer):
            if process is not None:
                try:
                    process.stdin.close()
                except (OSError, AttributeError):
                    pass
        lock.release()


# ---------------------------------------------------------------------- status
def status(preflight_id):
    """Read-only lookup of the original ID; never creates or cleans anything."""
    if type(preflight_id) is not str or not preflight_verify.ID_RE.fullmatch(preflight_id):
        die(79, "status-id")
    claim_file, completed_file = preflight_verify.claim_paths(ROOT, preflight_id)
    if not claim_file.is_file() or claim_file.is_symlink():
        print(json.dumps({"preflightId": preflight_id, "state": "unknown-id"}, sort_keys=True))
        return 3
    claim, claim_sha = guard.read_json(claim_file)
    result = {
        "preflightId": preflight_id,
        "state": claim.get("state"),
        "claimSha256": claim_sha,
        "evidenceDir": claim.get("evidenceDir"),
        "observationProtocol": claim.get("observationProtocol"),
        "framingPolicy": claim.get("framingPolicy"),
        "bufferParserSha256": claim.get("bufferParserSha256"),
        "bufferTemplateSha256": claim.get("bufferTemplateSha256"),
    }
    if completed_file.is_file() and not completed_file.is_symlink():
        completed, completed_sha = guard.read_json(completed_file)
        result.update(state="completed", completedSha256=completed_sha,
                      preflightReceiptSha256=completed.get("preflightReceiptSha256"))
    else:
        result["state"] = "unknown-outcome"
    evidence = preflight_verify.evidence_dir(ROOT, preflight_id)
    recoveries = []
    evidence_state = guard.path_state(evidence)
    if (evidence_state["state"] == "present" and evidence_state.get("isDir") is True
            and evidence_state.get("symlink") is False):
        for path in sorted(evidence.glob("recovery-*.json")):
            if path.is_symlink():
                recoveries.append({"file": path.name, "state": "symlink"})
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                recoveries.append({"file": path.name, "state": "unreadable"})
                continue
            recoveries.append({"file": path.name, "state": value.get("state"),
                               "cleanupConfirmed": value.get("cleanupConfirmed")})
    result["recoveries"] = recoveries
    try:
        diagnostic_summary = diagnostics.read_status_summary(
            evidence, preflight_id, claim=claim, claim_sha=claim_sha
        )
    except BaseException as error:  # noqa: BLE001 - read-only status must not fail
        diagnostic_summary = {"state": "unreadable",
                              "detail": type(error).__name__}
    if diagnostic_summary is not None:
        result["diagnostics"] = diagnostic_summary
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "completed" else 3


# --------------------------------------------------------------------- recover
def read_journal(path, limit=1 << 22):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, None, "missing"
    except OSError as error:
        return None, None, "lstat:" + type(error).__name__
    if stat.S_ISLNK(info.st_mode):
        return None, None, "symlink"
    if not stat.S_ISREG(info.st_mode):
        return None, None, "not-regular"
    if info.st_size > limit:
        return None, None, "too-large"
    try:
        raw = path.read_bytes()
    except OSError as error:
        return None, None, "read:" + type(error).__name__
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, None, "json"
    if type(value) is not dict:
        return None, None, "shape"
    return value, guard.sha_bytes(raw), None


def _recover_process(record, error):
    if error == "missing":
        return {"state": "exited", "proof": "not-started", "identity": None}
    if error:
        return {"state": "unknown", "detail": "journal-" + error, "identity": None}
    if not isinstance(record, dict):
        return {"state": "unknown", "detail": "record-missing", "identity": None}
    spawn_state = record.get("spawnState")
    identity = record.get("identity")
    if spawn_state == "not-started":
        return {"state": "exited", "proof": "not-started", "identity": identity}
    if spawn_state != "started" or not isinstance(identity, dict):
        return {"state": "unknown", "detail": "spawn-state:" + str(spawn_state),
                "identity": identity}
    state = guard.group_state(identity)
    if state.get("state") == "alive":
        stop = guard.stop_group(identity, graceful=3, term=2)
        state = guard.group_state(identity)
        return {**state, "stop": stop, "identity": identity}
    return {**state, "identity": identity}


def _recover_container(intent, created, error):
    if error:
        return {"removed": False, "state": "unknown", "detail": "container-journal-" + error}
    name = None
    tag = None
    image = IMAGE
    created_value = created if isinstance(created, dict) else {}
    intent_value = intent if isinstance(intent, dict) else {}
    name = created_value.get("containerName") or intent_value.get("containerName")
    tag = created_value.get("tag") or intent_value.get("tag")
    identifier = created_value.get("containerId")
    if isinstance(identifier, str) and FULL_ID_RE.fullmatch(identifier):
        record = {
            "containerId": identifier,
            "containerName": name,
            "tag": tag,
            "containerCreated": True,
            "image": created_value.get("imageId") or image,
        }
        before = guard.verify_own_container_present(record)
        removal = guard.remove_container_verified(record)
        return {**removal, "beforeRemoval": before}
    if not name or not tag:
        return {"removed": False, "state": "unknown",
                "detail": "incomplete-container-identity"}
    record = {"containerId": None, "containerName": name, "tag": tag,
              "containerCreated": False, "image": image}
    return guard.remove_container_verified(record)


def _split_relative(relative):
    if type(relative) is not str or not relative or relative.startswith("/"):
        return None
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return parts


def _safe_lstat(root, relative, kind=None):
    """Walk fixed root + relative with lstat only.

    No resolve()/exists()/is_dir() is used before the trust decision.  Every
    component is checked with lstat; a symlink at any level is rejected.  A
    missing component is ``absent`` and an unreadable component is ``unknown``.
    """
    parts = _split_relative(relative)
    if parts is None:
        return {"state": "escape", "path": None, "detail": "relative-path"}
    current = Path(root)
    state = {"state": "present", "detail": None, "isDir": False, "isFile": False}
    for index, part in enumerate(parts):
        current = current / part
        state = guard.path_state(current)
        if state["state"] == "absent":
            return {"state": "absent", "path": str(current), "detail": "missing",
                    "isDir": False, "isFile": False}
        if state["state"] == "unknown":
            return {"state": "unknown", "path": str(current), "detail": state["detail"],
                    "isDir": False, "isFile": False}
        if state["symlink"]:
            return {"state": "symlink", "path": str(current), "detail": "symlink",
                    "isDir": False, "isFile": False}
        if index < len(parts) - 1 and not state["isDir"]:
            return {"state": "not-directory", "path": str(current),
                    "detail": state["detail"], "isDir": False, "isFile": False}
    if kind == "dir" and not state["isDir"]:
        return {"state": "not-directory", "path": str(current),
                "detail": state["detail"], "isDir": False, "isFile": False}
    if kind == "file" and not state["isFile"]:
        return {"state": "not-regular", "path": str(current),
                "detail": state["detail"], "isDir": False, "isFile": False}
    return state


def _identity_reason(value):
    if type(value) is not dict:
        return "identity-shape"
    for key, minimum in (("pid", 1), ("pgid", 1), ("starttime", 0)):
        if type(value.get(key)) is not int or value[key] < minimum:
            return "identity-" + key
    if type(value.get("bootId")) is not str or not value["bootId"]:
        return "identity-boot"
    if value.get("groupLeader") is not True:
        return "identity-group"
    return None


def _recover_stage(stage_dir, identity, resources_clear, error):
    if error:
        return {"removed": False, "state": "stage-journal-" + error,
                "path": stage_dir, "lstatAfter": "unknown"}
    if not stage_dir:
        return {"removed": False, "state": "unknown", "detail": "stage-path-missing",
                "lstatAfter": "unknown"}
    state = guard.path_state(stage_dir)
    if state["state"] == "absent":
        return {"removed": True, "state": "absent", "path": stage_dir,
                "lstatAfter": "absent"}
    if state["state"] == "unknown":
        return {"removed": False, "state": "lstat-error", "path": stage_dir,
                "lstatAfter": "unknown", "detail": state["detail"]}
    if state["symlink"]:
        return {"removed": False, "state": "symlink", "path": stage_dir,
                "lstatAfter": "present"}
    if not resources_clear:
        return {"removed": False, "state": "retained-resources-unresolved",
                "path": stage_dir, "lstatAfter": "present"}
    if (not isinstance(identity, dict) or identity.get("error")
            or "dev" not in identity or "ino" not in identity):
        return {"removed": False, "state": "identity-missing", "path": stage_dir,
                "lstatAfter": "present"}
    match = guard.stage_matches(stage_dir, identity)
    if match == "absent":
        return {"removed": True, "state": "absent", "path": stage_dir,
                "lstatAfter": "absent"}
    if match:
        return {"removed": False, "state": match, "path": stage_dir,
                "lstatAfter": "unknown" if match == "lstat-error" else "present"}
    result = guard.cleanup_stage(stage_dir, identity)
    result["path"] = stage_dir
    result["stageIdentity"] = identity
    final = guard.path_state(stage_dir)
    if final["state"] == "absent":
        result["lstatAfter"] = "absent"
        if result.get("removed") is not True:
            result["removed"] = False
    elif final["state"] == "present":
        result["lstatAfter"] = "present"
        result["removed"] = False
        result["state"] = "still-present"
    else:
        result["lstatAfter"] = "unknown"
        result["removed"] = False
        result["state"] = "lstat-error"
        result["detail"] = final["detail"]
    return result


def _recovery_plan(evidence, preflight_id, plan, plan_sha):
    """Read and bind every journal before any resource action.

    Returns ``ready`` only when the complete ownership graph is consistent.
    An existing journal that contradicts the plan is ``blocked``.  A missing
    journal that is needed for attribution is ``incomplete`` (unknown), which
    never triggers a cleanup, signal or deletion.
    """
    stage_rel = plan.get("stageRelativePath")
    if _split_relative(stage_rel) is None:
        return {"status": "blocked", "reason": "stage-relative-path"}
    expected_stage = str(ROOT / stage_rel)
    evidence_rel = "preflight/evidence/" + preflight_id
    evidence_state = _safe_lstat(ROOT, evidence_rel, kind="dir")
    if evidence_state["state"] == "symlink":
        return {"status": "blocked", "reason": "evidence-symlink"}
    if evidence_state["state"] in ("not-directory", "escape", "not-regular"):
        return {"status": "blocked", "reason": "evidence-path:" + evidence_state["state"]}
    if evidence_state["state"] == "absent":
        return {"status": "incomplete", "reason": "evidence-missing"}
    if evidence_state["state"] == "unknown":
        return {"status": "incomplete",
                "reason": "evidence-lstat:" + str(evidence_state.get("detail"))}
    stage_state = _safe_lstat(ROOT, stage_rel)
    if stage_state["state"] == "symlink":
        return {"status": "blocked", "reason": "stage-symlink"}
    if stage_state["state"] == "unknown":
        return {"status": "incomplete",
                "reason": "stage-lstat:" + str(stage_state.get("detail"))}
    if stage_state["state"] == "escape":
        return {"status": "blocked", "reason": "stage-relative-path"}
    if stage_state["state"] == "not-directory":
        # A planned directory component that is now a non-directory is a
        # contradiction, never an absence proof.
        return {"status": "blocked", "reason": "stage-not-directory"}
    if stage_state["state"] == "present" and not stage_state.get("isDir"):
        return {"status": "blocked", "reason": "stage-not-directory"}
    if stage_state["state"] not in ("present", "absent"):
        return {"status": "blocked",
                "reason": "stage-path:" + str(stage_state["state"])}

    names = (
        "preflight-intent.json",
        "stage-intent.json",
        "stage-started.json",
        "stage-created.json",
        "container-intent.json",
        "container-created.json",
        "container-pid.json",
        "process-client-intent.json",
        "process-client-identity.json",
        "process-client-failed.json",
        "process-observer-intent.json",
        "process-observer-identity.json",
        "process-observer-failed.json",
        "cleanup.json",
    )
    values = {}
    digests = {}
    for name in names:
        value, digest, error = read_journal(evidence / name)
        if error not in (None, "missing"):
            return {"status": "incomplete",
                    "reason": "journal-read:%s:%s" % (name, error), "digests": digests}
        values[name] = value
        digests[name] = digest

    def value(name):
        item = values.get(name)
        return item if isinstance(item, dict) else None

    intent = value("preflight-intent.json")
    if intent is None:
        return {"status": "incomplete", "reason": "intent-missing", "digests": digests}
    for key, expected, reason in (
        ("kind", "zero-target-preflight-intent", "intent-kind"),
        ("protocolRevision", PROTOCOL_REVISION, "intent-revision"),
        ("preflightId", preflight_id, "intent-preflight-id"),
        ("tag", plan["tag"], "intent-tag"),
        ("containerName", plan["containerName"], "intent-container-name"),
        ("imageId", plan["imageId"], "intent-image"),
        ("stageDir", expected_stage, "intent-stage-dir"),
    ):
        if key not in intent:
            return {"status": "incomplete", "reason": reason + "-missing",
                    "digests": digests}
        if intent.get(key) != expected:
            return {"status": "blocked", "reason": reason, "digests": digests}
    if intent.get("resourcePlan") is not None and intent.get("resourcePlan") != plan:
        return {"status": "blocked", "reason": "intent-resource-plan", "digests": digests}
    if (intent.get("resourcePlanSha256") is not None
            and intent.get("resourcePlanSha256") != plan_sha):
        return {"status": "blocked", "reason": "intent-resource-plan-sha",
                "digests": digests}

    stage_intent = value("stage-intent.json")
    stage_started = value("stage-started.json")
    stage_created = value("stage-created.json")
    started_identity = None
    stage_identity = None

    if stage_intent is not None:
        for key, expected, reason in (
            ("kind", "zero-target-preflight-stage-intent", "stage-intent-kind"),
            ("preflightId", preflight_id, "stage-intent-preflight-id"),
            ("tag", plan["tag"], "stage-intent-tag"),
            ("stageDir", expected_stage, "stage-intent-stage-dir"),
        ):
            if key not in stage_intent:
                return {"status": "incomplete", "reason": reason + "-missing",
                        "digests": digests}
            if stage_intent.get(key) != expected:
                return {"status": "blocked", "reason": reason, "digests": digests}
        tools = stage_intent.get("plannedTools")
        if tools is None:
            return {"status": "incomplete", "reason": "stage-intent-tools-missing",
                    "digests": digests}
        if set(tools) != set(FIXED_TOOLS):
            return {"status": "blocked", "reason": "stage-intent-tools",
                    "digests": digests}
        if (stage_intent.get("resourcePlan") is not None
                and stage_intent.get("resourcePlan") != plan):
            return {"status": "blocked", "reason": "stage-intent-resource-plan",
                    "digests": digests}

    if stage_started is not None:
        for key, expected, reason in (
            ("kind", "zero-target-preflight-stage-started", "stage-started-kind"),
            ("preflightId", preflight_id, "stage-started-preflight-id"),
            ("stageDir", expected_stage, "stage-started-stage-dir"),
        ):
            if key not in stage_started:
                return {"status": "incomplete", "reason": reason + "-missing",
                        "digests": digests}
            if stage_started.get(key) != expected:
                return {"status": "blocked", "reason": reason, "digests": digests}
        started_identity = stage_started.get("stageIdentity")
        if (type(started_identity) is not dict or started_identity.get("error")
                or type(started_identity.get("dev")) is not int
                or type(started_identity.get("ino")) is not int):
            return {"status": "incomplete", "reason": "stage-started-identity",
                    "digests": digests}
        if started_identity.get("path") != expected_stage:
            return {"status": "blocked", "reason": "stage-started-path",
                    "digests": digests}
        if stage_intent is None:
            return {"status": "incomplete", "reason": "stage-intent-missing",
                    "digests": digests}

    if stage_created is not None:
        for key, expected, reason in (
            ("kind", "zero-target-preflight-stage-created", "stage-created-kind"),
            ("preflightId", preflight_id, "stage-created-preflight-id"),
            ("tag", plan["tag"], "stage-created-tag"),
            ("stageDir", expected_stage, "stage-created-stage-dir"),
        ):
            if key not in stage_created:
                return {"status": "incomplete", "reason": reason + "-missing",
                        "digests": digests}
            if stage_created.get(key) != expected:
                return {"status": "blocked", "reason": reason, "digests": digests}
        stage_identity = stage_created.get("stageIdentity")
        if (type(stage_identity) is not dict or stage_identity.get("error")
                or type(stage_identity.get("dev")) is not int
                or type(stage_identity.get("ino")) is not int):
            return {"status": "incomplete", "reason": "stage-created-identity",
                    "digests": digests}
        if stage_identity.get("path") != expected_stage:
            return {"status": "blocked", "reason": "stage-created-path",
                    "digests": digests}
        if stage_started is None:
            return {"status": "incomplete", "reason": "stage-started-missing",
                    "digests": digests}
        if (started_identity is not None
                and (stage_identity.get("dev"), stage_identity.get("ino"),
                     stage_identity.get("path")) !=
                (started_identity.get("dev"), started_identity.get("ino"),
                 started_identity.get("path"))):
            return {"status": "blocked", "reason": "stage-created-identity",
                    "digests": digests}

    if stage_started is not None or stage_created is not None:
        identity = stage_identity or started_identity
        if identity is None:
            return {"status": "incomplete", "reason": "stage-identity-missing",
                    "digests": digests}
        if stage_state["state"] == "present" and not stage_state.get("isDir"):
            return {"status": "blocked", "reason": "stage-not-directory",
                    "digests": digests}
        stage_mode = "present" if stage_state["state"] == "present" else "absent"
    else:
        identity = None
        if stage_state["state"] == "present":
            return {"status": "incomplete",
                    "reason": "stage-unexpected-without-identity", "digests": digests}
        stage_mode = "absent"

    container_intent = value("container-intent.json")
    container_created = value("container-created.json")
    container_pid = value("container-pid.json")
    container_id = None
    if container_intent is None and container_created is None:
        container_mode = "none"
    elif container_intent is not None and container_created is None:
        return {"status": "incomplete", "reason": "create-result-unknown",
                "digests": digests}
    elif container_created is not None and container_intent is None:
        return {"status": "incomplete", "reason": "container-intent-missing",
                "digests": digests}
    else:
        for key, expected, reason in (
            ("kind", "zero-target-preflight-container-intent", "container-intent-kind"),
            ("preflightId", preflight_id, "container-intent-preflight-id"),
            ("tag", plan["tag"], "container-intent-tag"),
            ("containerName", plan["containerName"], "container-intent-name"),
            ("imageId", plan["imageId"], "container-intent-image"),
        ):
            if key not in container_intent:
                return {"status": "incomplete", "reason": reason + "-missing",
                        "digests": digests}
            if container_intent.get(key) != expected:
                return {"status": "blocked", "reason": reason, "digests": digests}
        if container_intent.get("entrypoint") != INTERPRETER:
            return {"status": "blocked", "reason": "container-intent-entrypoint",
                    "digests": digests}
        if container_intent.get("interactive") is not True:
            return {"status": "blocked", "reason": "container-intent-interactive",
                    "digests": digests}
        if (container_intent.get("resourcePlan") is not None
                and container_intent.get("resourcePlan") != plan):
            return {"status": "blocked", "reason": "container-intent-resource-plan",
                    "digests": digests}
        for key, expected, reason in (
            ("kind", "zero-target-preflight-container-created", "container-created-kind"),
            ("preflightId", preflight_id, "container-created-preflight-id"),
            ("containerName", plan["containerName"], "container-created-name"),
            ("tag", plan["tag"], "container-created-tag"),
            ("imageId", plan["imageId"], "container-created-image"),
        ):
            if key not in container_created:
                return {"status": "incomplete", "reason": reason + "-missing",
                        "digests": digests}
            if container_created.get(key) != expected:
                return {"status": "blocked", "reason": reason, "digests": digests}
        if container_created.get("entrypoint") != INTERPRETER:
            return {"status": "blocked", "reason": "container-created-entrypoint",
                    "digests": digests}
        if container_created.get("interactive") is not True:
            return {"status": "blocked", "reason": "container-created-interactive",
                    "digests": digests}
        container_id = container_created.get("containerId")
        if type(container_id) is not str or not FULL_ID_RE.fullmatch(container_id):
            return {"status": "blocked", "reason": "container-created-id",
                    "digests": digests}
        create_query = container_created.get("createQuery")
        if create_query is None:
            return {"status": "incomplete", "reason": "container-create-query-missing",
                    "digests": digests}
        if type(create_query) is not dict or create_query.get("returncode") != 0:
            return {"status": "blocked", "reason": "container-create-query",
                    "digests": digests}
        lines = [line.strip() for line in str(create_query.get("stdout") or "").splitlines()
                 if line.strip()]
        if not lines or lines[-1] != container_id:
            return {"status": "blocked", "reason": "container-create-id",
                    "digests": digests}
        if (container_created.get("resourcePlan") is not None
                and container_created.get("resourcePlan") != plan):
            return {"status": "blocked", "reason": "container-created-resource-plan",
                    "digests": digests}
        if container_pid is not None:
            for key, expected, reason in (
                ("kind", "zero-target-preflight-container-pid", "container-pid-kind"),
                ("preflightId", preflight_id, "container-pid-preflight-id"),
                ("containerId", container_id, "container-pid-container-id"),
                ("containerName", plan["containerName"], "container-pid-name"),
                ("tag", plan["tag"], "container-pid-tag"),
            ):
                if key not in container_pid:
                    return {"status": "incomplete", "reason": reason + "-missing",
                            "digests": digests}
                if container_pid.get(key) != expected:
                    return {"status": "blocked", "reason": reason, "digests": digests}
            query = container_pid.get("query")
            if query is None:
                return {"status": "incomplete", "reason": "container-pid-query-missing",
                        "digests": digests}
            if type(query) is not dict or query.get("returncode") != 0:
                return {"status": "blocked", "reason": "container-pid-query",
                        "digests": digests}
            text = str(query.get("stdout") or "").strip()
            if not text.isdigit() or int(text) <= 0:
                return {"status": "blocked", "reason": "container-pid-output",
                        "digests": digests}
            if container_pid.get("targetPid") != int(text):
                return {"status": "blocked", "reason": "container-pid-record",
                        "digests": digests}
        container_mode = "created"

    observer_path = str(evidence / "observer.bt")

    def process_plan(role, intent_name, identity_name, failed_name):
        intent_value = value(intent_name)
        identity_value = value(identity_name)
        failed_value = value(failed_name)
        if intent_value is None and identity_value is None and failed_value is None:
            return {"mode": "none"}, None
        if intent_value is not None:
            for key, expected, reason in (
                ("kind", "zero-target-preflight-process-intent",
                 "process-" + role + "-intent-kind"),
                ("preflightId", preflight_id, "process-" + role + "-intent-preflight-id"),
                ("role", role, "process-" + role + "-intent-role"),
                ("spawnState", "spawn-attempted",
                 "process-" + role + "-intent-spawn-state"),
            ):
                if key not in intent_value:
                    return None, {"status": "incomplete",
                                  "reason": reason + "-missing"}
                if intent_value.get(key) != expected:
                    return None, {"status": "blocked", "reason": reason}
            argv = intent_value.get("argv")
            if role == "client":
                if container_mode != "created":
                    return None, {"status": "incomplete",
                                  "reason": "client-without-container"}
                if argv != ["docker", "start", "-a", "-i", container_id]:
                    return None, {"status": "blocked", "reason": "client-intent-argv"}
            elif argv != ["bpftrace", "-q", observer_path]:
                return None, {"status": "blocked", "reason": "observer-intent-argv"}
        if identity_value is not None:
            if intent_value is None:
                return None, {"status": "incomplete",
                              "reason": "process-" + role + "-intent-missing"}
            for key, expected, reason in (
                ("kind", "zero-target-preflight-process-state",
                 "process-" + role + "-identity-kind"),
                ("preflightId", preflight_id,
                 "process-" + role + "-identity-preflight-id"),
                ("role", role, "process-" + role + "-identity-role"),
                ("spawnState", "started", "process-" + role + "-identity-spawn-state"),
            ):
                if key not in identity_value:
                    return None, {"status": "incomplete",
                                  "reason": reason + "-missing"}
                if identity_value.get(key) != expected:
                    return None, {"status": "blocked", "reason": reason}
            identity = identity_value.get("identity")
            identity_reason = _identity_reason(identity)
            if identity_reason:
                return None, {"status": "blocked",
                              "reason": "process-" + role + "-" + identity_reason}
            if identity_value.get("pid") != identity.get("pid"):
                return None, {"status": "blocked",
                              "reason": "process-" + role + "-identity-pid"}
            return {"mode": "started", "record": identity_value,
                    "identity": identity}, None
        if failed_value is not None:
            if intent_value is None:
                return None, {"status": "incomplete",
                              "reason": "process-" + role + "-intent-missing"}
            for key, expected, reason in (
                ("kind", "zero-target-preflight-process-state",
                 "process-" + role + "-failed-kind"),
                ("preflightId", preflight_id,
                 "process-" + role + "-failed-preflight-id"),
                ("role", role, "process-" + role + "-failed-role"),
                ("spawnState", "not-started", "process-" + role + "-failed-spawn-state"),
            ):
                if key not in failed_value:
                    return None, {"status": "incomplete",
                                  "reason": reason + "-missing"}
                if failed_value.get(key) != expected:
                    return None, {"status": "blocked", "reason": reason}
            return {"mode": "not-started"}, None
        return None, {"status": "incomplete",
                      "reason": "process-" + role + "-identity-missing"}

    client, failure = process_plan(
        "client", "process-client-intent.json", "process-client-identity.json",
        "process-client-failed.json")
    if failure:
        failure["digests"] = digests
        return failure
    observer, failure = process_plan(
        "observer", "process-observer-intent.json", "process-observer-identity.json",
        "process-observer-failed.json")
    if failure:
        failure["digests"] = digests
        return failure

    if observer["mode"] != "none":
        observer_state = _safe_lstat(
            ROOT, "preflight/evidence/%s/observer.bt" % preflight_id, kind="file")
        if observer_state["state"] == "symlink":
            return {"status": "blocked", "reason": "observer-symlink",
                    "digests": digests}
        if observer_state["state"] in ("not-regular", "not-directory", "escape"):
            return {"status": "blocked", "reason": "observer-path", "digests": digests}
        if observer_state["state"] == "absent":
            return {"status": "incomplete", "reason": "observer-artifact-missing",
                    "digests": digests}
        if observer_state["state"] == "unknown":
            return {"status": "incomplete", "reason": "observer-lstat",
                    "digests": digests}

    return {
        "status": "ready",
        "stage": {"mode": stage_mode, "path": expected_stage,
                  "identity": identity, "lstat": stage_state["state"]},
        "container": {"mode": container_mode, "intent": container_intent,
                      "created": container_created, "id": container_id},
        "client": client,
        "observer": observer,
        "digests": digests,
        "values": values,
    }


def _final_stage_recheck(stage_rel, expected_stage, identity, mode, resources_clear):
    """Take a new, explicit path query after every resource action.

    The lstat in ``_recovery_plan`` only schedules an operation.  This query is
    the authoritative result for the recovery record and is composed from the
    fixed root through the original ID's evidence directory with one lstat per
    component.  A non-directory is a contradiction, not an absence result.
    """
    state = _safe_lstat(ROOT, stage_rel, kind="dir")
    path = expected_stage

    def outcome(decision, reason, state_name, lstat_after, removed=False, detail=None):
        value = {
            "removed": removed,
            "state": state_name,
            "path": path,
            "lstatAfter": lstat_after,
            "decision": decision,
            "reason": reason,
        }
        if detail is not None:
            value["detail"] = detail
        return value

    if state["state"] == "escape":
        return outcome("blocked", "stage-relative-path", "escape", "unknown")
    if state["state"] == "symlink":
        return outcome("blocked", "stage-symlink", "symlink", "present")
    if state["state"] == "not-directory":
        return outcome("blocked", "stage-not-directory", "not-directory", "present")
    if state["state"] == "unknown":
        return outcome("incomplete", "stage-lstat:" + str(state.get("detail")),
                       "lstat-error", "unknown", detail=state.get("detail"))
    if state["state"] == "absent":
        if resources_clear:
            return outcome("success", None, "absent", "absent", removed=True)
        return outcome("incomplete", "resources-not-clear",
                       "retained-resources-unresolved", "absent")
    if state["state"] != "present":
        return outcome("blocked", "stage-path:" + str(state["state"]),
                       "unknown-path", "unknown")

    # A real directory now exists at the composed path.  If the plan saw an
    # absence, this directory appeared after the scheduling lstat and must be
    # retained, never silently reported as removed.
    if mode == "absent":
        return outcome("incomplete", "stage-appeared", "appeared-after-plan",
                       "present")
    if not resources_clear:
        return outcome("incomplete", "resources-not-clear",
                       "retained-resources-unresolved", "present")
    if (not isinstance(identity, dict) or identity.get("error")
            or "dev" not in identity or "ino" not in identity):
        return outcome("incomplete", "stage-identity-missing",
                       "identity-missing", "present")
    if (state.get("dev") != identity.get("dev")
            or state.get("ino") != identity.get("ino")):
        return outcome("blocked", "stage-identity-changed",
                       "identity-changed", "present")

    result = guard.cleanup_stage(str(expected_stage), identity)
    final = _safe_lstat(ROOT, stage_rel, kind="dir")
    base = {"path": path, "stageIdentity": identity}
    if final["state"] == "absent":
        removed = result.get("removed") is True
        value = {
            **base,
            "removed": removed,
            "state": result.get("state") or "absent",
            "lstatAfter": "absent",
            "decision": "success" if removed else "incomplete",
            "reason": None if removed else "cleanup-not-confirmed",
        }
        if not removed:
            value["detail"] = result.get("detail") or result.get("state")
        return value
    if final["state"] == "present":
        return {**base, "removed": False, "state": "still-present",
                "lstatAfter": "present", "decision": "incomplete",
                "reason": "stage-still-present",
                "detail": result.get("state")}
    if final["state"] == "unknown":
        return {**base, "removed": False, "state": "lstat-error",
                "lstatAfter": "unknown", "decision": "incomplete",
                "reason": "stage-lstat:" + str(final.get("detail")),
                "detail": final.get("detail")}
    if final["state"] == "symlink":
        return {**base, "removed": False, "state": "symlink",
                "lstatAfter": "present", "decision": "blocked",
                "reason": "stage-symlink"}
    if final["state"] == "not-directory":
        return {**base, "removed": False, "state": "not-directory",
                "lstatAfter": "present", "decision": "blocked",
                "reason": "stage-not-directory"}
    return {**base, "removed": False, "state": "escape",
            "lstatAfter": "unknown", "decision": "blocked",
            "reason": "stage-relative-path"}


def recover(preflight_id):
    """Query and clean only the original ID; never replay the self-check.

    All journals are read and bound before the first resource operation.  A
    confirmed ownership contradiction is ``blocked`` (exit 78); a missing new
    plan, a corrupt journal, or an unconfirmable state is ``incomplete``
    (exit 3).  Only a fully re-proved cleanup becomes ``resources-cleared``.
    """
    if type(preflight_id) is not str or not preflight_verify.ID_RE.fullmatch(preflight_id):
        die(79, "recover-id")
    lock = guard.ExclusiveLock(LOCK_PATH)
    if not lock.acquire():
        print(json.dumps({"preflightId": preflight_id, "state": "locked"}, sort_keys=True))
        return 79
    recovery = {
        "version": CONTEXT_VERSION,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "zero-target-preflight-recovery",
        "preflightId": preflight_id,
        "state": "incomplete",
        "cleanupConfirmed": False,
        "realMachinePass": False,
        "receiptAccepted": False,
        "selfCheckReplayed": False,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "recordedAt": now(),
    }
    evidence = preflight_verify.evidence_dir(ROOT, preflight_id)
    try:
        # Frozen materials are checked first.  A failure here is a confirmed
        # material contradiction, not a missing runtime journal.
        manifest, manifest_sha = preflight_verify.verify_manifest(ROOT, MANIFEST)
        # Recovery may inspect a historical record.  It deliberately does not
        # require the new buffer protocol binding and never claims acceptance.
        license_value, license_sha, review, review_sha, license_id = (
            preflight_verify.verify_license(
                LICENSE, REVIEW, manifest_sha, expected_id=preflight_id,
                require_buffer_protocol=False,
            )
        )
        profile, profile_sha = preflight_verify.load_profile(PROFILE)
        recovery.update({
            "protocolManifestSha256": manifest_sha,
            "preflightLicenseSha256": license_sha,
            "sourceReviewReceiptSha256": review_sha,
            "profileSha256": profile_sha,
        })

        claim_rel = "preflight/claims/" + preflight_id + ".json"
        claim_state = _safe_lstat(ROOT, claim_rel, kind="file")
        if claim_state["state"] == "symlink":
            recovery.update(state="blocked", reason="claim-symlink")
            return _write_recovery(recovery, evidence, 78)
        if claim_state["state"] in ("not-regular", "not-directory", "escape"):
            recovery.update(state="blocked", reason="claim-path:" + claim_state["state"])
            return _write_recovery(recovery, evidence, 78)
        if claim_state["state"] == "absent":
            recovery.update(state="incomplete", reason="claim-missing")
            return _write_recovery(recovery, evidence, 3)
        if claim_state["state"] == "unknown":
            recovery.update(state="incomplete",
                            reason="claim-lstat:" + str(claim_state.get("detail")))
            return _write_recovery(recovery, evidence, 3)
        claim, claim_sha, claim_error = read_journal(ROOT / claim_rel)
        if claim_error:
            recovery.update(state="incomplete", reason="claim-read:" + claim_error)
            return _write_recovery(recovery, evidence, 3)
        recovery["claimSha256"] = claim_sha
        for key, expected, reason in (
            ("kind", "zero-target-preflight-claim", "claim-kind"),
            ("protocolRevision", PROTOCOL_REVISION, "claim-revision"),
            ("preflightId", preflight_id, "claim-preflight-id"),
            ("state", "consumed", "claim-state"),
            ("evidenceDir", "preflight/evidence/" + preflight_id, "claim-evidence-dir"),
            ("preflightLicenseSha256", license_sha, "claim-license"),
            ("protocolManifestSha256", manifest_sha, "claim-manifest"),
            ("sourceReviewReceiptSha256", review_sha, "claim-review"),
        ):
            if key not in claim:
                recovery.update(state="incomplete", reason=reason + "-missing")
                return _write_recovery(recovery, evidence, 3)
            if claim.get(key) != expected:
                recovery.update(state="blocked", reason=reason)
                return _write_recovery(recovery, evidence, 78)

        plan = claim.get("resourcePlan")
        plan_sha = claim.get("resourcePlanSha256")
        if plan is None or plan_sha is None:
            recovery.update(state="incomplete", reason="claim-resource-plan-missing")
            return _write_recovery(recovery, evidence, 3)
        if type(plan) is not dict:
            recovery.update(state="incomplete", reason="claim-resource-plan-shape")
            return _write_recovery(recovery, evidence, 3)
        missing = set(preflight_verify.RESOURCE_PLAN_FIELDS) - set(plan)
        extra = set(plan) - set(preflight_verify.RESOURCE_PLAN_FIELDS)
        if missing:
            recovery.update(state="incomplete",
                            reason="claim-resource-plan-missing-fields")
            return _write_recovery(recovery, evidence, 3)
        if extra:
            recovery.update(state="blocked", reason="claim-resource-plan-extra-fields")
            return _write_recovery(recovery, evidence, 78)
        plan_reason = preflight_verify.resource_plan_reason(plan, preflight_id)
        if plan_reason:
            recovery.update(state="blocked", reason="claim-" + plan_reason)
            return _write_recovery(recovery, evidence, 78)
        if type(plan_sha) is not str or plan_sha != preflight_verify.resource_plan_digest(plan):
            recovery.update(state="blocked", reason="claim-resource-plan-digest")
            return _write_recovery(recovery, evidence, 78)
        recovery["resourcePlan"] = plan
        recovery["resourcePlanSha256"] = plan_sha
        recovery["observationProtocol"] = claim.get("observationProtocol")
        recovery["framingPolicy"] = claim.get("framingPolicy")
        recovery["bufferParserSha256"] = claim.get("bufferParserSha256")
        recovery["bufferTemplateSha256"] = claim.get("bufferTemplateSha256")
        recovery["stageRelativePath"] = plan["stageRelativePath"]
        recovery["tag"] = plan["tag"]
        recovery["containerName"] = plan["containerName"]

        outcome = _recovery_plan(evidence, preflight_id, plan, plan_sha)
        recovery["journals"] = outcome.get("digests") or {}
        recovery["preflightIntentSha256"] = recovery["journals"].get("preflight-intent.json")
        recovery["stageIntentSha256"] = recovery["journals"].get("stage-intent.json")
        recovery["stageStartedSha256"] = recovery["journals"].get("stage-started.json")
        recovery["stageCreatedSha256"] = recovery["journals"].get("stage-created.json")
        recovery["containerIntentSha256"] = recovery["journals"].get("container-intent.json")
        recovery["containerCreatedSha256"] = recovery["journals"].get("container-created.json")
        recovery["processClientIdentitySha256"] = recovery["journals"].get(
            "process-client-identity.json")
        recovery["processObserverIdentitySha256"] = recovery["journals"].get(
            "process-observer-identity.json")
        if outcome["status"] == "blocked":
            recovery.update(state="blocked", reason=outcome.get("reason"),
                            cleanupConfirmed=False)
            recovery["stage"] = {"removed": False, "state": "unknown",
                                 "lstatAfter": "unknown"}
            recovery["container"] = {"removed": False, "state": "unknown"}
            recovery["client"] = {"state": "unknown"}
            recovery["observer"] = {"state": "unknown"}
            return _write_recovery(recovery, evidence, 78)
        if outcome["status"] == "incomplete":
            recovery.update(state="incomplete", reason=outcome.get("reason"),
                            cleanupConfirmed=False)
            recovery["stage"] = {"removed": False, "state": "unknown",
                                 "lstatAfter": "unknown"}
            recovery["container"] = {"removed": False, "state": "unknown"}
            recovery["client"] = {"state": "unknown"}
            recovery["observer"] = {"state": "unknown"}
            return _write_recovery(recovery, evidence, 3)

        container_plan = outcome["container"]
        if container_plan["mode"] == "none":
            # No create intent was persisted, so this code did not create a
            # container.  Still query the fixed name/tag: only a successful
            # double-empty query proves the planned container is absent.
            container = _cleanup_container({"container": {
                "createState": "not-attempted",
                "containerName": plan["containerName"],
                "tag": plan["tag"],
                "image": plan["imageId"],
            }})
        else:
            container = _recover_container(
                container_plan["intent"], container_plan["created"], None)
        recovery["container"] = container

        def process_action(plan_value):
            if plan_value["mode"] == "none":
                return {"state": "exited", "proof": "not-started", "identity": None}
            if plan_value["mode"] == "not-started":
                return {"state": "exited", "proof": "not-started",
                        "identity": plan_value.get("identity")}
            return _recover_process(plan_value["record"], None)

        client = process_action(outcome["client"])
        observer = process_action(outcome["observer"])
        recovery["client"] = client
        recovery["observer"] = observer

        resources_clear = (
            container.get("removed") is True
            and client.get("state") == "exited"
            and observer.get("state") == "exited"
        )
        stage_plan = outcome["stage"]
        expected_stage = stage_plan["path"]
        recovery["stageDir"] = expected_stage
        # This is a new query, after the container, client and observer work.
        # The plan's earlier lstat is only a scheduling observation and is never
        # reused as the success proof.
        stage = _final_stage_recheck(
            plan["stageRelativePath"], expected_stage, stage_plan.get("identity"),
            stage_plan["mode"], resources_clear,
        )
        decision = stage.pop("decision", "incomplete")
        reason = stage.pop("reason", "stage-final-incomplete")
        recovery["stage"] = stage
        if decision == "blocked":
            recovery.update(state="blocked", reason=reason,
                            cleanupConfirmed=False)
            return _write_recovery(recovery, evidence, 78)
        confirmed = (
            decision == "success"
            and resources_clear
            and stage.get("removed") is True
            and stage.get("lstatAfter") == "absent"
        )
        recovery["cleanupConfirmed"] = bool(confirmed)
        recovery["state"] = "resources-cleared" if confirmed else "incomplete"
        if not confirmed:
            recovery["reason"] = reason if decision != "success" else "resources-not-clear"
            return _write_recovery(recovery, evidence, 3)
        return _write_recovery(recovery, evidence, 0)
    except preflight_verify.PreflightError as error:
        recovery.update(state="blocked", reason="frozen:" + error.reason,
                        cleanupConfirmed=False)
        return _write_recovery(recovery, evidence, 78)
    except BaseException as error:
        recovery.update(state="incomplete",
                        reason=type(error).__name__ + ":" + str(error)[:160],
                        cleanupConfirmed=False)
        return _write_recovery(recovery, evidence, 3)
    finally:
        lock.release()


def _write_recovery(recovery, evidence, code):
    target_ok = False
    if isinstance(evidence, Path):
        state = guard.path_state(evidence)
        target_ok = (state["state"] == "present" and state.get("isDir") is True
                     and state.get("symlink") is False)
    target_dir = evidence if target_ok else RECOVERIES_ROOT
    path = target_dir / ("recovery-" + os.urandom(8).hex() + ".json")
    try:
        guard.write_new_json_document(path, recovery)
    except BaseException as error:
        print(json.dumps({"preflightId": recovery.get("preflightId"),
                          "state": "recovery-write-failed",
                          "error": type(error).__name__}, sort_keys=True))
        return 79
    print(json.dumps({
        "preflightId": recovery.get("preflightId"),
        "state": recovery.get("state"),
        "cleanupConfirmed": recovery.get("cleanupConfirmed"),
        "recoveryFile": str(path),
        "realMachinePass": False,
    }, sort_keys=True))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description="Zero-target preflight (fixed inputs only)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--preflight-id", required=True)
    recover_parser = sub.add_parser("recover")
    recover_parser.add_argument("--preflight-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        return preflight()
    if args.command == "status":
        return status(args.preflight_id)
    if args.command == "recover":
        return recover(args.preflight_id)
    die(79, "unknown-command")


if __name__ == "__main__":
    raise SystemExit(main())
