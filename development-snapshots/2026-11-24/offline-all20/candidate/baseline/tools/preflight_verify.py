#!/usr/bin/env python3
"""Independent preflight-evidence verifier.

This module is the single verifier used by the formal runner and the judge.  It
does not trust any ``complete``/``accepted`` boolean stored in JSON: it reads
the one-time claim, the license, the source-review receipt, the frozen manifest,
the sealed observer profile, the measured layout, the rendered observer and the
raw stream, then recomputes the observation with the frozen
:mod:`buffer_protocol_v2` parser from the current raw bytes.

The module is pure with respect to execution: it never starts Docker or
bpftrace, never reads a fixture, never imports a target and never writes a file.
"""
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

import buffer_protocol_v2
import observation_pure
import observer_render
import resource_guard as resource_guard
import structure

FIXED_IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
PYTHON_VERSION = "3.12.15"
INTERPRETER = "/usr/bin/python3.12"
LIBRARY = "/usr/lib/libpython3.12.so.1.0"
TARGET_UID = 65534
RUN_ID = "preflight"
CALLER_PATH = "/review/preflight/preflight_selfcheck.py"
PROFILE_NAME = "zero-target-preflight"
PROTOCOL_REVISION = 3
OBSERVATION_PROTOCOL = "buffer-v2"
FRAMING_POLICY = buffer_protocol_v2.FRAMING_POLICY
LEGACY_OBSERVATION_PROTOCOL = "legacy"
BUFFER_PARSER_NAME = "buffer_protocol_v2.py"
BUFFER_TEMPLATE_NAME = "observer_template_buffer_v2.bt"
LEGACY_TEMPLATE_NAME = "observer_template.bt"
HASH_RE = re.compile(r"[a-f0-9]{64}")
ID_RE = re.compile(r"[a-f0-9]{32,64}")
TAG_RE = re.compile(r"[a-f0-9]{16}")
TOOL_NAMES = (
    "preflight_selfcheck.py",
    "layout_probe.py",
    "structure.py",
    "observer_template.bt",
    "observer_template_buffer.bt",
    "buffer_protocol.py",
    "buffer_protocol_v2.py",
    "observer_template_buffer_v2.bt",
    "observer-profile.lock.json",
)
LAYOUT_KEYS = {
    "codeConstsOffset",
    "codeNamesOffset",
    "codeFilenameOffset",
    "codeFlagsOffset",
    "codeFirstlinenoOffset",
    "codeQualnameOffset",
    "codeSizeOffset",
    "codeAdaptiveOffset",
    "tupleSizeOffset",
    "tupleItemsOffset",
    "strLengthOffset",
    "strStateOffset",
    "strDataOffset",
    "typeNameOffset",
    "intTagOffset",
    "intDigitOffset",
}
FRAME_KEYS = {"tstateCframeOffset", "framePrevInstrOffset"}
CONTAINER_NAME_PREFIX = "stdlib-cli-preflight-"
RESOURCE_PLAN_FIELDS = (
    "preflightId",
    "tag",
    "containerName",
    "imageId",
    "stageRelativePath",
)


class PreflightError(Exception):
    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def sha_bytes(data):
    return observation_pure.sha256_bytes(data)


def buffer_binding_digests(root):
    """Actual candidate parser/template digests, never caller-supplied ones."""
    root = Path(root)
    return {
        BUFFER_PARSER_NAME: sha_bytes(read_regular_bytes(root / "tools" / BUFFER_PARSER_NAME)),
        BUFFER_TEMPLATE_NAME: sha_bytes(
            read_regular_bytes(root / "tools" / BUFFER_TEMPLATE_NAME)
        ),
    }


def require_exitcode(value, what, allow_unknown=False):
    """Accept only an actual integer exit status; bool/float are not integers."""
    if value is None and allow_unknown:
        return None
    if type(value) is not int:
        raise PreflightError("exitcode-type:" + what)
    return value


def require_success_exitcode(value, what):
    """Accept exactly integer 0.  ``False``/``0.0`` are not success codes."""
    if type(value) is not int or value != 0:
        raise PreflightError("exitcode-not-zero:" + what)
    return value


def read_regular_bytes(path, limit=1 << 22):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise PreflightError("missing:" + str(path)) from None
    except OSError as error:
        raise PreflightError("lstat:" + type(error).__name__) from None
    if stat.S_ISLNK(info.st_mode):
        raise PreflightError("symlink:" + str(path))
    if not stat.S_ISREG(info.st_mode):
        raise PreflightError("not-regular:" + str(path))
    if info.st_size > limit:
        raise PreflightError("too-large:" + str(path))
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError as error:
        raise PreflightError("read:" + type(error).__name__) from None
    if len(data) != info.st_size:
        raise PreflightError("short-read:" + str(path))
    return data


def read_json_regular(path, limit=1 << 22):
    raw = read_regular_bytes(path, limit=limit)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise PreflightError("json:" + type(error).__name__) from None
    if type(value) is not dict:
        raise PreflightError("shape:" + str(path))
    return value, raw, sha_bytes(raw)


def resolve_under(root, relative):
    root = Path(root).resolve()
    if type(relative) is not str or not relative or relative.startswith("/"):
        raise PreflightError("relative-path")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise PreflightError("path-escape:" + relative) from None
    if candidate == root:
        raise PreflightError("path-root")
    return candidate


def fixed_container_name(tag):
    return CONTAINER_NAME_PREFIX + tag


def expected_stage_relative(preflight_id, tag):
    return "preflight/evidence/%s/stage-%s" % (preflight_id, tag)


def resource_plan(preflight_id, tag):
    """The only resource plan a preflight claim may bind.

    The five fields are fixed.  There is no project path, arbitrary name,
    command, environment or executable field in the plan.
    """
    return {
        "preflightId": preflight_id,
        "tag": tag,
        "containerName": fixed_container_name(tag),
        "imageId": FIXED_IMAGE,
        "stageRelativePath": expected_stage_relative(preflight_id, tag),
    }


def resource_plan_digest(plan):
    """Canonical digest using the existing guard normalisation."""
    return resource_guard.digest(plan)


def resource_plan_reason(plan, preflight_id=None, stage_relative=None):
    """Return a precise contract reason, or ``None`` when the plan is exact."""
    if type(plan) is not dict:
        return "resource-plan-shape"
    if set(plan) != set(RESOURCE_PLAN_FIELDS):
        return "resource-plan-fields"
    plan_id = plan.get("preflightId")
    if type(plan_id) is not str or not ID_RE.fullmatch(plan_id):
        return "resource-plan-id"
    if preflight_id is not None and plan_id != preflight_id:
        return "resource-plan-id-mismatch"
    tag = plan.get("tag")
    if type(tag) is not str or not TAG_RE.fullmatch(tag):
        return "resource-plan-tag"
    if plan.get("containerName") != fixed_container_name(tag):
        return "resource-plan-container-name"
    if plan.get("imageId") != FIXED_IMAGE:
        return "resource-plan-image"
    expected = stage_relative or expected_stage_relative(plan_id, tag)
    if plan.get("stageRelativePath") != expected:
        return "resource-plan-stage-path"
    return None


def verify_manifest(root, manifest_path):
    manifest, raw, manifest_sha = read_json_regular(manifest_path, limit=1 << 24)
    if manifest.get("state") != "pending-codex-review":
        raise PreflightError("manifest-state")
    if manifest.get("selfExcluded") is not True:
        raise PreflightError("manifest-self-excluded")
    files = manifest.get("files")
    if type(files) is not dict or not files:
        raise PreflightError("manifest-files")
    for relative, expected in files.items():
        if type(relative) is not str or not HASH_RE.fullmatch(expected or ""):
            raise PreflightError("manifest-entry")
        candidate = resolve_under(root, relative)
        try:
            info = os.lstat(candidate)
        except OSError:
            raise PreflightError("manifest-path:" + relative) from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise PreflightError("manifest-path:" + relative)
        with open(candidate, "rb") as handle:
            actual = sha_bytes(handle.read())
        if actual != expected:
            raise PreflightError("manifest-file-mismatch:" + relative)
    return manifest, manifest_sha


def load_profile(profile_path):
    profile, raw, profile_sha = read_json_regular(profile_path)
    if profile.get("kind") != "controlled-script-observer-profile":
        raise PreflightError("profile-kind")
    if profile.get("version") != 1:
        raise PreflightError("profile-version")
    for key, expected_type in (
        ("imageId", str),
        ("pythonVersion", str),
        ("interpreterPath", str),
        ("libraryPath", str),
        ("interpreterSha256", str),
        ("librarySha256", str),
        ("bpftraceVersion", str),
        ("mechanism", str),
    ):
        if type(profile.get(key)) is not expected_type:
            raise PreflightError("profile-field:" + key)
    for key in ("interpreterSha256", "librarySha256"):
        if not HASH_RE.fullmatch(profile[key]):
            raise PreflightError("profile-digest:" + key)
    if profile["imageId"] != FIXED_IMAGE:
        raise PreflightError("profile-image")
    if profile["pythonVersion"] != PYTHON_VERSION:
        raise PreflightError("profile-python")
    if profile["interpreterPath"] != INTERPRETER or profile["libraryPath"] != LIBRARY:
        raise PreflightError("profile-paths")
    return profile, profile_sha


def profile_identity(profile):
    return {
        "imageId": profile["imageId"],
        "pythonVersion": profile["pythonVersion"],
        "interpreterPath": profile["interpreterPath"],
        "libraryPath": profile["libraryPath"],
        "interpreterSha256": profile["interpreterSha256"],
        "librarySha256": profile["librarySha256"],
        "bpftraceVersion": profile["bpftraceVersion"],
        "mechanism": profile["mechanism"],
    }


def verify_license(license_path, review_path, manifest_sha, expected_id=None,
                   parser_sha=None, template_sha=None,
                   require_buffer_protocol=False):
    license_value, license_raw, license_sha = read_json_regular(license_path)
    if license_value.get("kind") != "zero-target-preflight-admission":
        raise PreflightError("license-kind")
    if license_value.get("protocolRevision") != PROTOCOL_REVISION:
        raise PreflightError("license-revision")
    if require_buffer_protocol:
        if license_value.get("observationProtocol") != OBSERVATION_PROTOCOL:
            raise PreflightError("license-observation-protocol")
        if license_value.get("framingPolicy") != FRAMING_POLICY:
            raise PreflightError("license-framing-policy")
        if type(parser_sha) is not str or not HASH_RE.fullmatch(parser_sha):
            raise PreflightError("license-buffer-parser-missing")
        if license_value.get("bufferParserSha256") != parser_sha:
            raise PreflightError("license-buffer-parser")
        if type(template_sha) is not str or not HASH_RE.fullmatch(template_sha):
            raise PreflightError("license-buffer-template-missing")
        if license_value.get("bufferTemplateSha256") != template_sha:
            raise PreflightError("license-buffer-template")
    if license_value.get("state") != "approved":
        raise PreflightError("license-state")
    if license_value.get("allowedCommand") != "preflight":
        raise PreflightError("license-command")
    if license_value.get("maxTargetExecutions") != 0 or license_value.get("fixturesImported") != 0:
        raise PreflightError("license-budget")
    if license_value.get("protocolManifestSha256") != manifest_sha:
        raise PreflightError("license-manifest")
    if license_value.get("candidateManifestSha256") != manifest_sha:
        raise PreflightError("license-candidate-manifest")
    preflight_id = license_value.get("preflightId")
    if type(preflight_id) is not str or not ID_RE.fullmatch(preflight_id):
        raise PreflightError("license-preflight-id")
    if expected_id is not None and preflight_id != expected_id:
        raise PreflightError("license-id-mismatch")
    review, review_raw, review_sha = read_json_regular(review_path)
    if license_value.get("sourceReviewReceiptSha256") != review_sha:
        raise PreflightError("license-review")
    if review.get("state") != "completed":
        raise PreflightError("review-state")
    if review.get("protocolManifestSha256") != manifest_sha:
        raise PreflightError("review-manifest")
    if review.get("blockers"):
        raise PreflightError("review-blockers")
    return license_value, license_sha, review, review_sha, preflight_id


def claim_paths(root, preflight_id):
    base = Path(root) / "preflight" / "claims"
    return base / (preflight_id + ".json"), base / (preflight_id + ".completed.json")


def evidence_dir(root, preflight_id):
    return Path(root) / "preflight" / "evidence" / preflight_id


def verify_claim(root, preflight_id, license_sha, receipt_sha=None,
                 parser_sha=None, template_sha=None,
                 require_buffer_protocol=False):
    claim_file, completed_file = claim_paths(root, preflight_id)
    claim, claim_raw, claim_sha = read_json_regular(claim_file)
    if claim.get("kind") != "zero-target-preflight-claim":
        raise PreflightError("claim-kind")
    if claim.get("protocolRevision") != PROTOCOL_REVISION:
        raise PreflightError("claim-revision")
    if require_buffer_protocol:
        if claim.get("observationProtocol") != OBSERVATION_PROTOCOL:
            raise PreflightError("claim-observation-protocol")
        if claim.get("framingPolicy") != FRAMING_POLICY:
            raise PreflightError("claim-framing-policy")
        if claim.get("bufferParserSha256") != parser_sha:
            raise PreflightError("claim-buffer-parser")
        if claim.get("bufferTemplateSha256") != template_sha:
            raise PreflightError("claim-buffer-template")
    if claim.get("preflightId") != preflight_id:
        raise PreflightError("claim-id")
    if claim.get("preflightLicenseSha256") != license_sha:
        raise PreflightError("claim-license")
    if claim.get("state") != "consumed":
        raise PreflightError("claim-state")
    if claim.get("evidenceDir") != "preflight/evidence/" + preflight_id:
        raise PreflightError("claim-evidence-dir")
    plan = claim.get("resourcePlan")
    plan_sha = claim.get("resourcePlanSha256")
    if plan is None or plan_sha is None:
        raise PreflightError("claim-resource-plan-missing")
    reason = resource_plan_reason(plan, preflight_id)
    if reason:
        raise PreflightError("claim-" + reason)
    if type(plan_sha) is not str or not HASH_RE.fullmatch(plan_sha):
        raise PreflightError("claim-resource-plan-sha")
    if resource_plan_digest(plan) != plan_sha:
        raise PreflightError("claim-resource-plan-digest")
    if receipt_sha is not None:
        if not completed_file.is_file() or completed_file.is_symlink():
            raise PreflightError("claim-not-completed")
        completed, completed_raw, completed_sha = read_json_regular(completed_file)
        if completed.get("kind") != "zero-target-preflight-claim-completed":
            raise PreflightError("claim-completed-kind")
        if completed.get("preflightId") != preflight_id:
            raise PreflightError("claim-completed-id")
        if completed.get("state") != "completed":
            raise PreflightError("claim-completed-state")
        if completed.get("preflightReceiptSha256") != receipt_sha:
            raise PreflightError("claim-completed-receipt")
        if completed.get("claimSha256") != claim_sha:
            raise PreflightError("claim-completed-claim")
        if require_buffer_protocol:
            if completed.get("observationProtocol") != OBSERVATION_PROTOCOL:
                raise PreflightError("claim-completed-observation-protocol")
            if completed.get("framingPolicy") != FRAMING_POLICY:
                raise PreflightError("claim-completed-framing-policy")
            if completed.get("bufferParserSha256") != parser_sha:
                raise PreflightError("claim-completed-buffer-parser")
            if completed.get("bufferTemplateSha256") != template_sha:
                raise PreflightError("claim-completed-buffer-template")
    return claim, claim_sha


def verify_layout_bytes(layout_raw, profile, manifest_sha, preflight_id):
    try:
        layout = json.loads(layout_raw)
    except (ValueError, UnicodeDecodeError):
        raise PreflightError("layout-json") from None
    if type(layout) is not dict:
        raise PreflightError("layout-shape")
    if layout.get("kind") != "zero-target-preflight-layout" or layout.get("version") not in (2, 3):
        raise PreflightError("layout-kind")
    if layout.get("protocolRevision") != PROTOCOL_REVISION:
        raise PreflightError("layout-revision")
    if layout.get("preflightId") != preflight_id:
        raise PreflightError("layout-preflight-id")
    if layout.get("protocolManifestSha256") != manifest_sha:
        raise PreflightError("layout-manifest")
    if layout.get("candidateManifestSha256") != manifest_sha:
        raise PreflightError("layout-candidate-manifest")
    if layout.get("profileSha256") != profile.get("profileFileSha256"):
        raise PreflightError("layout-profile")
    identity = profile_identity(profile)
    if layout.get("runtime") != identity:
        raise PreflightError("layout-runtime")
    if layout.get("imageId") != identity["imageId"]:
        raise PreflightError("layout-image")
    if layout.get("pythonVersion") != identity["pythonVersion"]:
        raise PreflightError("layout-python")
    offsets = layout.get("offsets")
    frame = layout.get("frameOffsets")
    if type(offsets) is not dict or set(offsets) != LAYOUT_KEYS:
        raise PreflightError("layout-offsets")
    for key, value in offsets.items():
        if type(value) is not int or value < 0 or value > 4096:
            raise PreflightError("layout-offset:" + key)
    if type(frame) is not dict or not FRAME_KEYS.issubset(frame):
        raise PreflightError("layout-frame")
    for key in FRAME_KEYS:
        if type(frame.get(key)) is not int or frame[key] < 0 or frame[key] > 4096:
            raise PreflightError("layout-frame:" + key)
    if layout.get("intZeroTag") != 1:
        raise PreflightError("layout-int-zero")
    return layout, sha_bytes(layout_raw), structure.structure_digest(layout)


def verify_config_bytes(config_raw, profile, preflight_id, layout):
    try:
        config = json.loads(config_raw)
    except (ValueError, UnicodeDecodeError):
        raise PreflightError("config-json") from None
    if type(config) is not dict:
        raise PreflightError("config-shape")
    if config.get("kind") != "zero-target-preflight-config":
        raise PreflightError("config-kind")
    if config.get("protocolRevision") != PROTOCOL_REVISION:
        raise PreflightError("config-revision")
    if config.get("preflightId") != preflight_id:
        raise PreflightError("config-preflight-id")
    if config.get("callerPath") != CALLER_PATH:
        raise PreflightError("config-caller")
    if type(config.get("callOffset")) is not int or config["callOffset"] < 0:
        raise PreflightError("config-call-offset")
    if not HASH_RE.fullmatch(config.get("callerSha256") or ""):
        raise PreflightError("config-caller-sha")
    if config.get("intZeroTag") != 1:
        raise PreflightError("config-int-zero")
    if config.get("pythonVersion") != profile["pythonVersion"]:
        raise PreflightError("config-python")
    if config.get("interpreterSha256") != profile["interpreterSha256"]:
        raise PreflightError("config-interpreter")
    if config.get("librarySha256") != profile["librarySha256"]:
        raise PreflightError("config-library")
    if config.get("profileSha256") != profile.get("profileFileSha256"):
        raise PreflightError("config-profile")
    expected_structure = config.get("expectedStructure")
    if type(expected_structure) is not dict:
        raise PreflightError("config-expected-structure")
    try:
        structure_sha = structure.structure_digest(expected_structure)
        code_sha = structure.code_digest_from_structure(expected_structure)
    except (KeyError, TypeError, ValueError, AttributeError,
            structure.StructureUnsupported) as error:
        raise PreflightError(
            "config-expected-structure:" + type(error).__name__
        ) from None
    if structure_sha != config.get("expectedStructureSha256"):
        raise PreflightError("config-expected-digest")
    if code_sha != config.get("expectedCodeSha256"):
        raise PreflightError("config-expected-code")
    config_layout = config.get("layout")
    if type(config_layout) is not dict:
        raise PreflightError("config-layout")
    if type(config_layout.get("offsets")) is not dict or type(layout.get("offsets")) is not dict:
        raise PreflightError("config-layout-offsets")
    if config_layout.get("offsets") != layout.get("offsets"):
        raise PreflightError("config-layout-offsets")
    config_frame = config_layout.get("frameOffsets")
    layout_frame = layout.get("frameOffsets")
    if type(config_frame) is not dict or type(layout_frame) is not dict:
        raise PreflightError("config-layout-frame")
    for key in FRAME_KEYS:
        if config_frame.get(key) != layout_frame.get(key):
            raise PreflightError("config-layout-frame:" + key)
    return config


def _evidence_journal(evidence, name, expected):
    if not isinstance(expected, str) or not HASH_RE.fullmatch(expected):
        raise PreflightError("evidence-digest:" + name)
    try:
        raw = read_regular_bytes(evidence / name)
    except PreflightError as error:
        raise PreflightError("evidence:" + name + ":" + error.reason) from None
    digest = sha_bytes(raw)
    if digest != expected:
        raise PreflightError("evidence-mismatch:" + name)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise PreflightError("evidence-json:" + name) from None
    if type(value) is not dict:
        raise PreflightError("evidence-shape:" + name)
    return value, digest


def _time(value, what):
    if type(value) is not str:
        raise PreflightError("timestamp:" + what)
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise PreflightError("timestamp:" + what) from None


def _require_int(value, what, minimum=0):
    if type(value) is not int or value < minimum:
        raise PreflightError("value:" + what)
    return value


def _require_identity(value, what):
    if type(value) is not dict:
        raise PreflightError("identity:" + what)
    pid = _require_int(value.get("pid"), what + ":pid", 1)
    pgid = _require_int(value.get("pgid"), what + ":pgid", 1)
    starttime = _require_int(value.get("starttime"), what + ":starttime")
    boot = value.get("bootId")
    if type(boot) is not str or not boot or value.get("groupLeader") is not True:
        raise PreflightError("identity:" + what)
    return {"pid": pid, "pgid": pgid, "starttime": starttime,
            "bootId": boot, "groupLeader": True}


def _mount_tuples(value, what):
    if type(value) is not list:
        raise PreflightError("mounts:" + what)
    rows = set()
    for item in value:
        if type(item) is not dict or item.get("readonly") is not True:
            raise PreflightError("mounts:" + what)
        source = item.get("source")
        destination = item.get("destination")
        if type(source) is not str or not source or type(destination) is not str or not destination:
            raise PreflightError("mounts:" + what)
        rows.add((source, destination))
    if not rows:
        raise PreflightError("mounts:" + what)
    return rows


def _absent_triple(queries):
    if type(queries) is not dict:
        return False
    return all((queries.get(key) or {}).get("state") == "absent"
               for key in ("id", "name", "tag"))


def verify_resource_evidence(evidence, receipt, config, profile, preflight_id, manifest_sha,
                             plan=None):
    """Bind and re-derive cleanup from the journals, not stored booleans."""
    if plan is None:
        plan = receipt.get("resourcePlan")
    plan_reason = resource_plan_reason(plan, preflight_id)
    if plan_reason:
        raise PreflightError("receipt-" + plan_reason)
    plan_sha = receipt.get("resourcePlanSha256")
    if plan_sha != resource_plan_digest(plan):
        raise PreflightError("receipt-resource-plan-digest")
    named = {
        "preflight-intent.json": receipt.get("preflightIntentSha256"),
        "stage-intent.json": receipt.get("stageIntentSha256"),
        "stage-started.json": receipt.get("stageStartedSha256"),
        "stage-created.json": receipt.get("stageCreatedSha256"),
        "container-intent.json": receipt.get("containerIntentSha256"),
        "container-created.json": receipt.get("containerCreatedSha256"),
        "container-pid.json": receipt.get("containerPidSha256"),
        "process-client-intent.json": receipt.get("processClientIntentSha256"),
        "process-client-identity.json": receipt.get("processClientIdentitySha256"),
        "process-observer-intent.json": receipt.get("processObserverIntentSha256"),
        "process-observer-identity.json": receipt.get("processObserverIdentitySha256"),
        "cleanup.json": receipt.get("cleanupSha256"),
    }
    digests = receipt.get("evidenceDigests")
    if type(digests) is not dict:
        raise PreflightError("receipt-evidence-digests")
    values = {}
    actual = {}
    for name, expected in named.items():
        if digests.get(name) != expected:
            raise PreflightError("receipt-evidence-map:" + name)
        value, digest = _evidence_journal(evidence, name, expected)
        if value.get("protocolRevision") != PROTOCOL_REVISION:
            raise PreflightError("evidence-revision:" + name)
        values[name] = value
        actual[name] = digest

    intent = values["preflight-intent.json"]
    if (intent.get("kind") != "zero-target-preflight-intent"
            or intent.get("protocolRevision") != PROTOCOL_REVISION
            or intent.get("preflightId") != preflight_id):
        raise PreflightError("intent-shape")
    tag = receipt.get("tag")
    if type(tag) is not str or not TAG_RE.fullmatch(tag) or intent.get("tag") != tag:
        raise PreflightError("intent-tag")
    name = intent.get("containerName")
    if type(name) is not str or not name or receipt.get("containerName") != name:
        raise PreflightError("intent-container-name")
    if intent.get("imageId") != FIXED_IMAGE:
        raise PreflightError("intent-image")
    if intent.get("resourcePlan") != plan:
        raise PreflightError("intent-resource-plan")
    if intent.get("resourcePlanSha256") != plan_sha:
        raise PreflightError("intent-resource-plan-sha")
    stage_dir = intent.get("stageDir")
    if stage_dir != str(evidence / ("stage-" + tag)):
        raise PreflightError("intent-stage-dir")
    if plan.get("stageRelativePath") != expected_stage_relative(preflight_id, tag):
        raise PreflightError("intent-stage-plan")
    intent_mounts = _mount_tuples(intent.get("mounts"), "intent")

    stage_intent = values["stage-intent.json"]
    if (stage_intent.get("kind") != "zero-target-preflight-stage-intent"
            or stage_intent.get("preflightId") != preflight_id
            or stage_intent.get("stageDir") != stage_dir
            or stage_intent.get("resourcePlan") != plan
            or stage_intent.get("resourcePlanSha256") != plan_sha
            or set(stage_intent.get("plannedTools") or []) != set(TOOL_NAMES)):
        raise PreflightError("stage-intent-shape")

    stage_started = values["stage-started.json"]
    started_identity = stage_started.get("stageIdentity")
    if (stage_started.get("kind") != "zero-target-preflight-stage-started"
            or stage_started.get("preflightId") != preflight_id
            or stage_started.get("stageDir") != stage_dir
            or type(started_identity) is not dict
            or type(started_identity.get("dev")) is not int
            or type(started_identity.get("ino")) is not int
            or started_identity.get("path") != stage_dir):
        raise PreflightError("stage-started-shape")

    stage_created = values["stage-created.json"]
    stage_identity = stage_created.get("stageIdentity")
    if type(stage_identity) is not dict:
        raise PreflightError("stage-created-identity")
    if (stage_identity.get("dev"), stage_identity.get("ino"), stage_identity.get("path")) != (
            started_identity.get("dev"), started_identity.get("ino"), started_identity.get("path")):
        raise PreflightError("stage-created-identity")
    if (stage_created.get("kind") != "zero-target-preflight-stage-created"
            or stage_created.get("preflightId") != preflight_id
            or stage_created.get("tag") != tag
            or stage_created.get("stageDir") != stage_dir
            or _mount_tuples(stage_created.get("mounts"), "stage") != intent_mounts):
        raise PreflightError("stage-created-shape")

    container_intent = values["container-intent.json"]
    if (container_intent.get("kind") != "zero-target-preflight-container-intent"
            or container_intent.get("preflightId") != preflight_id
            or container_intent.get("tag") != tag
            or container_intent.get("containerName") != name
            or container_intent.get("imageId") != FIXED_IMAGE
            or container_intent.get("entrypoint") != INTERPRETER
            or container_intent.get("interactive") is not True
            or container_intent.get("resourcePlan") != plan
            or container_intent.get("resourcePlanSha256") != plan_sha
            or _mount_tuples(container_intent.get("mounts"), "container-intent") != intent_mounts):
        raise PreflightError("container-intent-shape")

    container_created = values["container-created.json"]
    container_id = container_created.get("containerId")
    if (container_created.get("kind") != "zero-target-preflight-container-created"
            or container_created.get("preflightId") != preflight_id
            or type(container_id) is not str or not HASH_RE.fullmatch(container_id)
            or container_created.get("containerName") != name
            or container_created.get("tag") != tag
            or container_created.get("imageId") != FIXED_IMAGE
            or container_created.get("entrypoint") != INTERPRETER
            or container_created.get("interactive") is not True
            or container_created.get("resourcePlan") != plan
            or container_created.get("resourcePlanSha256") != plan_sha
            or _mount_tuples(container_created.get("mounts"), "container-created") != intent_mounts):
        raise PreflightError("container-created-shape")
    create_query = container_created.get("createQuery")
    if type(create_query) is not dict:
        raise PreflightError("container-create-query")
    require_success_exitcode(create_query.get("returncode"), "container-create-query")
    create_lines = [line.strip() for line in str(create_query.get("stdout") or "").splitlines()
                    if line.strip()]
    if not create_lines or create_lines[-1] != container_id:
        raise PreflightError("container-create-identity")

    container_pid = values["container-pid.json"]
    if (container_pid.get("kind") != "zero-target-preflight-container-pid"
            or container_pid.get("preflightId") != preflight_id
            or container_pid.get("containerId") != container_id
            or container_pid.get("containerName") != name
            or container_pid.get("tag") != tag):
        raise PreflightError("container-pid-shape")
    pid_query = container_pid.get("query")
    if type(pid_query) is not dict:
        raise PreflightError("container-pid-query")
    require_success_exitcode(pid_query.get("returncode"), "container-pid-query")
    pid_text = str(pid_query.get("stdout") or "").strip()
    if not pid_text.isdigit() or int(pid_text) <= 0:
        raise PreflightError("container-pid-output")
    target_pid = receipt.get("targetPid")
    if type(target_pid) is not int or target_pid <= 0 or int(pid_text) != target_pid:
        raise PreflightError("container-pid-binding")
    if container_pid.get("targetPid") != target_pid:
        raise PreflightError("container-pid-record")
    if receipt.get("targetUid") != TARGET_UID:
        raise PreflightError("target-uid")

    client_intent = values["process-client-intent.json"]
    if (client_intent.get("kind") != "zero-target-preflight-process-intent"
            or client_intent.get("preflightId") != preflight_id
            or client_intent.get("role") != "client"
            or client_intent.get("spawnState") != "spawn-attempted"
            or client_intent.get("argv") != ["docker", "start", "-a", "-i", container_id]):
        raise PreflightError("client-intent-shape")
    client_record = values["process-client-identity.json"]
    client_identity = _require_identity(client_record.get("identity"), "client")
    if (client_record.get("kind") != "zero-target-preflight-process-state"
            or client_record.get("preflightId") != preflight_id
            or client_record.get("role") != "client"
            or client_record.get("spawnState") != "started"
            or client_record.get("pid") != client_identity["pid"]):
        raise PreflightError("client-identity-shape")

    observer_intent = values["process-observer-intent.json"]
    expected_observer = ["bpftrace", "-q", str(evidence / "observer.bt")]
    if (observer_intent.get("kind") != "zero-target-preflight-process-intent"
            or observer_intent.get("preflightId") != preflight_id
            or observer_intent.get("role") != "observer"
            or observer_intent.get("spawnState") != "spawn-attempted"
            or observer_intent.get("argv") != expected_observer):
        raise PreflightError("observer-intent-shape")
    observer_record = values["process-observer-identity.json"]
    observer_identity = _require_identity(observer_record.get("identity"), "observer")
    if (observer_record.get("kind") != "zero-target-preflight-process-state"
            or observer_record.get("preflightId") != preflight_id
            or observer_record.get("role") != "observer"
            or observer_record.get("spawnState") != "started"
            or observer_record.get("pid") != observer_identity["pid"]):
        raise PreflightError("observer-identity-shape")

    cleanup_file = values["cleanup.json"]
    if (cleanup_file.get("kind") != "zero-target-preflight-cleanup"
            or cleanup_file.get("preflightId") != preflight_id
            or cleanup_file.get("tag") != tag
            or cleanup_file.get("containerName") != name
            or cleanup_file.get("containerId") != container_id):
        raise PreflightError("cleanup-shape")
    cleanup = cleanup_file.get("cleanup")
    if type(cleanup) is not dict:
        raise PreflightError("cleanup-value")
    if cleanup.get("persistFailure") is not None:
        raise PreflightError("cleanup-persist-failure")
    container_clean = cleanup.get("container")
    if type(container_clean) is not dict or container_clean.get("removed") is not True:
        raise PreflightError("cleanup-container")
    if container_clean.get("state") not in {"removed", "absent"}:
        raise PreflightError("cleanup-container-state")
    if not _absent_triple(container_clean.get("queries")):
        raise PreflightError("cleanup-container-queries")
    before = container_clean.get("beforeRemoval")
    if type(before) is not dict or before.get("state") not in {"present", "absent"}:
        raise PreflightError("cleanup-container-before")
    if before.get("state") == "present":
        observed = before.get("observed")
        if type(observed) is not dict:
            raise PreflightError("cleanup-container-observed")
        if (observed.get("id") != container_id or observed.get("name") != name
                or (observed.get("labels") or {}).get("sce.tag") != tag
                or observed.get("image") != FIXED_IMAGE):
            raise PreflightError("cleanup-container-ownership")
    for role, record, identity in (
        ("client", client_record, client_identity),
        ("observer", observer_record, observer_identity),
    ):
        row = cleanup.get(role)
        if type(row) is not dict or row.get("state") != "exited":
            raise PreflightError("cleanup-" + role + "-state")
        if row.get("identity") != identity:
            raise PreflightError("cleanup-" + role + "-identity")
        if row.get("proof") not in {"group-query", "empty-group-query"}:
            raise PreflightError("cleanup-" + role + "-proof")
    stage_clean = cleanup.get("stage")
    if type(stage_clean) is not dict or stage_clean.get("removed") is not True:
        raise PreflightError("cleanup-stage")
    if stage_clean.get("state") not in {"removed", "absent"}:
        raise PreflightError("cleanup-stage-state")
    if stage_clean.get("lstatAfter") != "absent":
        raise PreflightError("cleanup-stage-lstat")
    if stage_clean.get("stageIdentity") != stage_identity:
        raise PreflightError("cleanup-stage-identity")
    if stage_clean.get("path") != stage_dir:
        raise PreflightError("cleanup-stage-path")

    order = [
        ("preflight-intent.json", "createdAt"),
        ("stage-intent.json", "createdAt"),
        ("stage-started.json", "createdAt"),
        ("stage-created.json", "createdAt"),
        ("container-intent.json", "createdAt"),
        ("container-created.json", "createdAt"),
        ("process-client-intent.json", "recordedAt"),
        ("process-client-identity.json", "recordedAt"),
        ("container-pid.json", "recordedAt"),
        ("process-observer-intent.json", "recordedAt"),
        ("process-observer-identity.json", "recordedAt"),
        ("cleanup.json", "recordedAt"),
    ]
    previous = None
    for file_name, field in order:
        moment = _time(values[file_name].get(field), file_name + ":" + field)
        if previous is not None and moment < previous:
            raise PreflightError("evidence-order:" + file_name)
        previous = moment
    generated = _time(receipt.get("generatedAt"), "receipt:generatedAt")
    if previous is not None and generated < previous:
        raise PreflightError("evidence-order:receipt")
    if receipt.get("cleanup") != cleanup:
        raise PreflightError("cleanup-receipt-mismatch")
    return {"files": actual, "cleanup": cleanup, "values": values}


def verify_preflight_evidence(root, receipt_path, license_path, review_path, manifest_path,
                              profile_path, expected_id=None):
    """Return a fully recomputed evidence bundle or raise ``PreflightError``."""
    root = Path(root).resolve()
    receipt_raw = read_regular_bytes(receipt_path)
    receipt_sha = sha_bytes(receipt_raw)
    try:
        receipt = json.loads(receipt_raw)
    except (ValueError, UnicodeDecodeError):
        raise PreflightError("receipt-json") from None
    if type(receipt) is not dict:
        raise PreflightError("receipt-shape")
    if receipt.get("kind") != "zero-target-preflight-receipt":
        raise PreflightError("receipt-kind")
    if receipt.get("protocolRevision") != PROTOCOL_REVISION:
        raise PreflightError("receipt-revision")
    if receipt.get("state") != "accepted":
        raise PreflightError("receipt-state")
    preflight_id = receipt.get("preflightId")
    if type(preflight_id) is not str or not ID_RE.fullmatch(preflight_id):
        raise PreflightError("receipt-preflight-id")
    if expected_id is not None and preflight_id != expected_id:
        raise PreflightError("receipt-id-mismatch")
    expected_receipt = evidence_dir(root, preflight_id) / "preflight-receipt.json"
    if Path(receipt_path).resolve() != expected_receipt.resolve():
        raise PreflightError("receipt-path")
    if receipt.get("runId") != RUN_ID or receipt.get("tag") is None:
        raise PreflightError("receipt-run")

    manifest, manifest_sha = verify_manifest(root, manifest_path)
    actual_buffer = buffer_binding_digests(root)
    parser_sha = actual_buffer[BUFFER_PARSER_NAME]
    buffer_template_sha = actual_buffer[BUFFER_TEMPLATE_NAME]
    license_value, license_sha, review, review_sha, license_id = verify_license(
        license_path, review_path, manifest_sha, expected_id=preflight_id,
        parser_sha=parser_sha, template_sha=buffer_template_sha,
        require_buffer_protocol=True,
    )
    if license_id != preflight_id:
        raise PreflightError("license-id-mismatch")
    claim, claim_sha = verify_claim(
        root, preflight_id, license_sha, receipt_sha=receipt_sha,
        parser_sha=parser_sha, template_sha=buffer_template_sha,
        require_buffer_protocol=True,
    )
    claim_plan = claim.get("resourcePlan")
    claim_plan_sha = claim.get("resourcePlanSha256")
    if receipt.get("resourcePlan") != claim_plan:
        raise PreflightError("receipt-resource-plan")
    if receipt.get("resourcePlanSha256") != claim_plan_sha:
        raise PreflightError("receipt-resource-plan-sha")

    if receipt.get("protocolManifestSha256") != manifest_sha:
        raise PreflightError("receipt-manifest")
    if receipt.get("candidateManifestSha256") != manifest_sha:
        raise PreflightError("receipt-candidate-manifest")
    if receipt.get("preflightLicenseSha256") != license_sha:
        raise PreflightError("receipt-license")
    if receipt.get("sourceReviewReceiptSha256") != review_sha:
        raise PreflightError("receipt-review")
    if receipt.get("claimSha256") != claim_sha:
        raise PreflightError("receipt-claim")
    if receipt.get("observationProtocol") != OBSERVATION_PROTOCOL:
        raise PreflightError("receipt-observation-protocol")
    if receipt.get("framingPolicy") != FRAMING_POLICY:
        raise PreflightError("receipt-framing-policy")
    if receipt.get("bufferParserSha256") != parser_sha:
        raise PreflightError("receipt-buffer-parser")
    if receipt.get("bufferTemplateSha256") != buffer_template_sha:
        raise PreflightError("receipt-buffer-template")

    profile, profile_sha = load_profile(profile_path)
    profile["profileFileSha256"] = profile_sha
    if receipt.get("profileSha256") != profile_sha:
        raise PreflightError("receipt-profile")
    if receipt.get("profile") != profile_identity(profile):
        raise PreflightError("receipt-profile-identity")
    if receipt.get("imageId") != profile["imageId"]:
        raise PreflightError("receipt-image")
    if receipt.get("pythonVersion") != profile["pythonVersion"]:
        raise PreflightError("receipt-python")
    runtime = receipt.get("runtime") or {}
    if runtime.get("interpreterSha256") != profile["interpreterSha256"]:
        raise PreflightError("receipt-interpreter")
    if runtime.get("librarySha256") != profile["librarySha256"]:
        raise PreflightError("receipt-library")

    tools = receipt.get("toolDigests")
    if type(tools) is not dict:
        raise PreflightError("receipt-tools")
    for name in TOOL_NAMES:
        tool_path = root / "tools" / name
        if sha_bytes(read_regular_bytes(tool_path)) != tools.get(name):
            raise PreflightError("receipt-tool:" + name)
    if tools.get("observer-profile.lock.json") != profile_sha:
        raise PreflightError("receipt-profile-tool")

    evidence = expected_receipt.parent
    layout_file = receipt.get("layoutFile")
    if layout_file != "preflight/evidence/%s/layout.json" % preflight_id:
        raise PreflightError("receipt-layout-path")
    layout_path = resolve_under(root, layout_file)
    layout_raw = read_regular_bytes(layout_path)
    layout_sha = sha_bytes(layout_raw)
    if receipt.get("layoutSha256") != layout_sha:
        raise PreflightError("receipt-layout-sha")
    layout, computed_layout_sha, layout_structure_sha = verify_layout_bytes(
        layout_raw, profile, manifest_sha, preflight_id
    )
    if receipt.get("layoutStructureSha256") != layout_structure_sha:
        raise PreflightError("receipt-layout-structure")

    config_raw = read_regular_bytes(evidence / "preflight-config.json")
    if receipt.get("preflightConfigSha256") != sha_bytes(config_raw):
        raise PreflightError("receipt-config-sha")
    config = verify_config_bytes(config_raw, profile, preflight_id, layout)
    if receipt.get("callerPath") != CALLER_PATH or receipt.get("callOffset") != config["callOffset"]:
        raise PreflightError("receipt-caller")
    if receipt.get("callerSha256") != config["callerSha256"]:
        raise PreflightError("receipt-caller-sha")

    if receipt.get("frozenTemplateName") != BUFFER_TEMPLATE_NAME:
        raise PreflightError("receipt-frozen-template-name")
    frozen_template_raw = read_regular_bytes(root / "tools" / BUFFER_TEMPLATE_NAME)
    frozen_template_sha = sha_bytes(frozen_template_raw)
    if frozen_template_sha != buffer_template_sha:
        raise PreflightError("receipt-buffer-template-file")
    if tools.get(BUFFER_TEMPLATE_NAME) != frozen_template_sha:
        raise PreflightError("receipt-frozen-template")
    if receipt.get("frozenTemplateSha256") != frozen_template_sha:
        raise PreflightError("receipt-frozen-template-sha")
    template_raw = read_regular_bytes(evidence / "observer.bt")
    template_sha = sha_bytes(template_raw)
    if receipt.get("observerTemplateSha256") != template_sha:
        raise PreflightError("receipt-template-sha")
    raw_raw = read_regular_bytes(evidence / "observer.raw", limit=1 << 22)
    raw_sha = sha_bytes(raw_raw)
    observation_raw = read_regular_bytes(evidence / "observation.json")
    observation_sha = sha_bytes(observation_raw)
    try:
        stored_observation = json.loads(observation_raw)
    except (ValueError, UnicodeDecodeError):
        raise PreflightError("observation-json") from None
    if type(stored_observation) is not dict:
        raise PreflightError("observation-shape")

    target_pid = receipt.get("targetPid")
    target_uid = receipt.get("targetUid")
    if type(target_pid) is not int or target_pid <= 0:
        raise PreflightError("receipt-target-pid")
    if target_uid != TARGET_UID:
        raise PreflightError("receipt-target-uid")
    require_success_exitcode(receipt.get("collectorExitCode"), "collector-exit")
    if receipt.get("collectorOutputFresh") is not True:
        raise PreflightError("receipt-collector-fresh")
    if receipt.get("evidenceCreatedNew") is not True:
        raise PreflightError("receipt-evidence-new")
    if receipt.get("drainComplete") is not True:
        raise PreflightError("receipt-drain")
    if receipt.get("rawTruncated") is not False:
        raise PreflightError("receipt-raw-truncated")
    stop = receipt.get("observerStop") or {}
    if stop.get("stopped") is not True or stop.get("forced") is not False:
        raise PreflightError("receipt-observer-stop")
    if stop.get("state") != "exited" or stop.get("signal") != "SIGINT":
        raise PreflightError("receipt-observer-stop-graceful")

    try:
        rebuilt_observer = observer_render.render(
            frozen_template_raw, layout, layout_sha, profile_sha, RUN_ID,
            receipt["tag"], CALLER_PATH, config["callOffset"], target_pid,
            TARGET_UID, PROFILE_NAME,
        )
    except observer_render.RenderError as error:
        raise PreflightError("observer-render:" + str(error)) from None
    if rebuilt_observer != template_raw:
        raise PreflightError("observer-rebuild-mismatch")

    resource_evidence = verify_resource_evidence(
        evidence, receipt, config, profile, preflight_id, manifest_sha,
        plan=claim_plan,
    )

    recomputed = buffer_protocol_v2.parse_receipt(
        raw_raw, RUN_ID, receipt["tag"], CALLER_PATH, config["callOffset"],
        target_pid, TARGET_UID, max_events=4, raw_truncated=False, require_events=1,
    )
    if stored_observation != recomputed:
        raise PreflightError("observation-mismatch")
    if recomputed.get("protocol") != OBSERVATION_PROTOCOL:
        raise PreflightError("observation-protocol")
    if recomputed.get("framingPolicy") != FRAMING_POLICY:
        raise PreflightError("observation-framing-policy")
    if type(recomputed.get("trailingBlankLines")) is not int or not (
            0 <= recomputed["trailingBlankLines"] <= 8):
        raise PreflightError("observation-trailing-blank-lines")
    if recomputed.get("targetExecuted") is not False:
        raise PreflightError("observation-target-executed")
    if recomputed.get("marker") != buffer_protocol_v2.MARKER:
        raise PreflightError("observation-buffer-marker")
    if recomputed.get("markerCount") != 1:
        raise PreflightError("observation-buffer-marker-count")
    observation = receipt.get("observation") or {}
    if observation.get("complete") is not True:
        raise PreflightError("observation-complete")
    if observation.get("events") != 1:
        raise PreflightError("observation-events")
    if observation.get("observationProtocol") != OBSERVATION_PROTOCOL:
        raise PreflightError("observation-capture-protocol")
    if observation.get("framingPolicy") != FRAMING_POLICY:
        raise PreflightError("observation-capture-framing-policy")
    if observation.get("trailingBlankLines") != recomputed.get("trailingBlankLines"):
        raise PreflightError("observation-capture-trailing-blank-lines")
    if observation.get("bufferParserSha256") != parser_sha:
        raise PreflightError("observation-capture-buffer-parser")
    if observation.get("bufferTemplateSha256") != buffer_template_sha:
        raise PreflightError("observation-capture-buffer-template")
    if observation.get("observerRebuildVerified") is not True:
        raise PreflightError("observation-capture-rebuild")
    if observation.get("rawSha256") != raw_sha:
        raise PreflightError("observation-raw")
    if observation.get("rawBytes") != len(raw_raw):
        raise PreflightError("observation-raw-bytes")
    if observation.get("observerSha256") != template_sha:
        raise PreflightError("observation-template")
    if observation.get("observationSha256") != observation_sha:
        raise PreflightError("observation-file")
    if observation.get("intZero") is not True:
        raise PreflightError("observation-int-zero")
    if observation.get("callerOffsetVerified") is not True:
        raise PreflightError("observation-caller")
    if observation.get("structureVerified") is not True:
        raise PreflightError("observation-structure")
    if observation.get("endComplete") is not True:
        raise PreflightError("observation-end")
    if observation.get("errors"):
        raise PreflightError("observation-errors")
    if recomputed.get("state") != "complete":
        raise PreflightError("observation-recomputed-state")
    if len(recomputed.get("events") or []) != 1:
        raise PreflightError("observation-recomputed-events")
    event = recomputed["events"][0]
    if event.get("callerOffset") != config["callOffset"]:
        raise PreflightError("observation-recomputed-offset")
    if event.get("callerSha256") != config["callerSha256"]:
        raise PreflightError("observation-recomputed-caller")
    if structure.structure_digest(event.get("dynamicStructure")) != event.get(
            "dynamicStructureSha256"):
        raise PreflightError("observation-structure-self-digest")
    if structure.code_digest_from_structure(event.get("dynamicStructure")) != event.get(
            "dynamicCodeSha256"):
        raise PreflightError("observation-code-self-digest")
    if structure.structure_digest(event.get("callerDescriptor")) != event.get(
            "callerSha256"):
        raise PreflightError("observation-caller-self-digest")
    if event.get("dynamicStructureSha256") != config["expectedStructureSha256"]:
        raise PreflightError("observation-recomputed-structure")
    if event.get("dynamicCodeSha256") != config["expectedCodeSha256"]:
        raise PreflightError("observation-recomputed-code")
    consts = (event.get("dynamicStructure") or {}).get("consts") or []
    if {"t": "int", "v": 0} not in consts:
        raise PreflightError("observation-recomputed-int-zero")
    if recomputed.get("beginCount") != 1 or recomputed.get("endCount") != 1:
        raise PreflightError("observation-markers")
    if recomputed.get("begin") != "run=%s tag=%s" % (RUN_ID, receipt["tag"]):
        raise PreflightError("observation-begin")
    if recomputed.get("end") != "run=%s tag=%s events=1" % (RUN_ID, receipt["tag"]):
        raise PreflightError("observation-end-record")

    cleanup = receipt.get("cleanup") or {}
    derived_cleanup = resource_evidence["cleanup"]
    if cleanup.get("confirmed") is not True:
        raise PreflightError("receipt-cleanup")
    if (cleanup.get("container") or {}).get("removed") is not True:
        raise PreflightError("receipt-cleanup-container")
    for key in ("client", "observer", "stage"):
        row = cleanup.get(key) or {}
        if row.get("stopped") is not True and row.get("removed") is not True:
            raise PreflightError("receipt-cleanup-" + key)
    if (derived_cleanup.get("container") or {}).get("removed") is not True:
        raise PreflightError("derived-cleanup-container")
    for key in ("client", "observer"):
        if (derived_cleanup.get(key) or {}).get("state") != "exited":
            raise PreflightError("derived-cleanup-" + key)
    if (derived_cleanup.get("stage") or {}).get("removed") is not True:
        raise PreflightError("derived-cleanup-stage")
    if receipt.get("targetExecutions") != 0 or receipt.get("fixturesImported") != 0:
        raise PreflightError("receipt-budget")
    if receipt.get("realContainers") != 1:
        raise PreflightError("receipt-real-containers")

    return {
        "receipt": receipt,
        "receiptSha256": receipt_sha,
        "receiptPath": str(Path(receipt_path).resolve()),
        "preflightId": preflight_id,
        "license": license_value,
        "licenseSha256": license_sha,
        "review": review,
        "reviewSha256": review_sha,
        "manifest": manifest,
        "manifestSha256": manifest_sha,
        "profile": profile,
        "profileSha256": profile_sha,
        "layout": layout,
        "layoutSha256": layout_sha,
        "layoutStructureSha256": layout_structure_sha,
        "layoutBytes": layout_raw,
        "config": config,
        "configSha256": sha_bytes(config_raw),
        "templateBytes": template_raw,
        "templateSha256": template_sha,
        "frozenTemplateBytes": frozen_template_raw,
        "frozenTemplateSha256": frozen_template_sha,
        "observationProtocol": OBSERVATION_PROTOCOL,
        "framingPolicy": FRAMING_POLICY,
        "trailingBlankLines": recomputed.get("trailingBlankLines"),
        "bufferParserSha256": parser_sha,
        "bufferTemplateSha256": buffer_template_sha,
        "rawBytes": raw_raw,
        "rawSha256": raw_sha,
        "observation": recomputed,
        "observationSha256": observation_sha,
        "claim": claim,
        "claimSha256": claim_sha,
        "resourceEvidence": resource_evidence,
        "cleanup": derived_cleanup,
    }
