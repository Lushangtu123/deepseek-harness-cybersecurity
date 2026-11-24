#!/usr/bin/env python3
"""Sole execution entry for the stdlib CLI structural-probe experiment.

Revision scope (round-4 blockers):

* every receipt link uses the **bytes written to disk**; canonical structure
  digests and ``bindingId`` keep their independent meaning;
* the fresh-compile branch is the normal branch and is read back from the
  expected file before the attempt is marked prepared;
* an interactive stdin is requested at ``docker create`` and the entrypoint is
  explicit; the target launcher still sees exactly one ``GO`` line;
* the observer is drained continuously, stopped with SIGINT first and only then
  TERM/KILL; END must be the last non-empty record and map noise is rejected;
* resource intent (random tag, stage identity, container name, mounts, env) is
  persisted before creation; a same-name container is refused, never removed;
* containers are addressed by full ID and verified by name/tag/image; process
  groups are verified by leader start time; stages by ``lstat`` dev/ino;
* early failures are recoverable: cleanup re-queries the original resources and
  does not reuse a stored boolean; no target is ever replayed;
* ``targetExecutions`` is set only when a GO write was confirmed and a client
  exit was observed; a container ID alone is never execution evidence.

The target execution entry is NOT run in this phase.  ``run`` refuses unless the
host wrote ``codex-review/experiment-admission.json`` binding the manifest, a
completed source review receipt and a successful zero-target preflight receipt.
This author cannot and did not create those files.
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import buffer_protocol_v2  # noqa: E402
import observation_pure  # noqa: E402
import observer_render  # noqa: E402
import preflight_verify  # noqa: E402
import resource_guard as guard  # noqa: E402
import structure  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
RUNS = ROOT / "runs"
PREPARE = ROOT / "prepare"
ADMISSION = ROOT / "codex-review" / "experiment-admission.json"
PREFLIGHT_ROOT = ROOT / "preflight"
PREFLIGHT_RECEIPT = PREFLIGHT_ROOT / "preflight-receipt.json"
PREFLIGHT_RAW = PREFLIGHT_ROOT / "observer.raw"
PREFLIGHT_TEMPLATE = PREFLIGHT_ROOT / "observer.bt"
SOURCE_REVIEW_RECEIPT = ROOT / "codex-review" / "source-review-receipt.json"
MANIFEST = ROOT / "protocol-manifest.json"
PLAN = ROOT / "experiment-plan.json"
TOOLS = ROOT / "tools"
PROFILE = TOOLS / "observer-profile.lock.json"
PROTOCOL_REVISION = 3
OBSERVATION_PROTOCOL = buffer_protocol_v2.PROTOCOL
FRAMING_POLICY = buffer_protocol_v2.FRAMING_POLICY
BUFFER_PARSER_NAME = preflight_verify.BUFFER_PARSER_NAME
BUFFER_TEMPLATE_NAME = preflight_verify.BUFFER_TEMPLATE_NAME
FIXED_TOOLS = preflight_verify.TOOL_NAMES
FIXTURES = ROOT / "fixtures"

IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
PYTHON_VERSION = "3.12.15"
INTERPRETER = "/usr/bin/python3.12"
TARGET_UID = "65534"
TARGET_GID = "65534"
LIMITS = {
    "memoryMiB": 512,
    "cpus": 1,
    "pids": 64,
    "tmpMiB": 32,
    "outputBytes": 262144,
    "targetTimeoutSeconds": 30,
    "observerArmTimeoutSeconds": 10,
    "observerStopGraceSeconds": 8,
    "maxAttempts": 16,
}
HASH_RE = re.compile(r"[a-f0-9]{64}")
CHALLENGE_RE = re.compile(r"[a-f0-9]{32}")
PREPARE_ID_RE = re.compile(r"[a-f0-9]{32}")
TAG_RE = re.compile(r"[a-f0-9]{16,64}")
ROLE_RUN_RE = re.compile(r"run-(\d{4})")
ROLE_BIND_RE = re.compile(r"bind-([a-f0-9]{8})")
ROLE_COMPILE_RE = re.compile(r"compile-(\d{4})-([a-f0-9]{8})")
RESOURCE_PROOF_PROTOCOL = "resource-phase-v1"
CLEANUP_CHECK_PROTOCOL = "cleanup-check-v1"
ASSOCIATION_INTENT_PROTOCOL = "association-intent-v1"
RECORD_STATES = ("valid", "legacy", "invalid", "unreadable")
CLEANUP_RECEIPT_STATES = ("incomplete", "confirmed")
CLEANUP_CHECK_STATES = ("checking", "incomplete", "confirmed")
RESOURCE_PHASES = (
    "reserved",
    "plan-created",
    "stage-creation",
    "stage-created",
    "container-creation",
    "container-created",
    "client-spawn",
    "observer-spawn",
    "running",
    "cleanup-unconfirmed",
    "cleanup-confirmed",
)
RESOURCE_NOT_CREATED_KEYS = ("stage", "container", "client", "observer")
ALLOWED_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "HOSTNAME": "stdlib-cli-experiment",
}
PREPARE_STEPS = ["layout-v1", "bind-all", "compile-per-attempt"]
ATTEMPT_RECORD_RE = re.compile(r"attempt-(\d{4})\.json")
LOCK_PATH = None  # resolved lazily so tests can relocate STATE
_LOCK_HANDLE = None
_PREFLIGHT_RESULT = None


class RecoveryIncomplete(RuntimeError):
    """A recovering read or scope hold could not be confirmed (exit 3)."""


class RecordValidationError(RuntimeError):
    """A damaged record must not be rewritten; callers map this to exit 3."""


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return guard.canonical(value)


def digest(value):
    return guard.digest(value)


def sha_bytes(data):
    return guard.sha_bytes(data)


def sha_file(path):
    return guard.sha_file(path)


def read_json(path):
    return guard.read_json(path)


def write_json_document(path, value):
    return guard.write_json_document(path, value)


def die(code, message):
    sys.stderr.write("runner: %s\n" % message)
    raise SystemExit(code)


# ------------------------------------------------------- record validation
# The recovery path consumes only a small, documented surface.  These helpers
# classify that surface without normalizing, repairing or writing any record.
# A malformed field is reported against its own name; it does not erase the
# other fields that may still identify a known related record.
def _issue(issues, field, detail):
    issues.append("%s:%s" % (field, detail))


def _is_sha256(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _is_prepare_id(value):
    return type(value) is str and PREPARE_ID_RE.fullmatch(value) is not None


def _is_tag(value):
    return type(value) is str and TAG_RE.fullmatch(value) is not None


def _valid_stage_path(value):
    if type(value) is not str or not value or "\x00" in value:
        return False
    try:
        path = Path(value)
    except (OSError, ValueError):
        return False
    return path.is_absolute() and ".." not in path.parts


def _validate_stage_identity(value, field, issues):
    if value is None:
        return
    if type(value) is not dict:
        _issue(issues, field, "not-object")
        return
    if value.get("error") is not None:
        if type(value.get("error")) is not str:
            _issue(issues, field + ".error", "not-string")
        return
    for key in ("dev", "ino"):
        if value.get(key) is not None and type(value.get(key)) is not int:
            _issue(issues, field + "." + key, "not-integer")


def _validate_processes(value, field, issues):
    if value is None:
        return
    if type(value) is not dict:
        _issue(issues, field, "not-object")
        return
    for role, process in value.items():
        if type(role) is not str:
            _issue(issues, field, "non-string-role")
            continue
        if type(process) is not dict:
            _issue(issues, field + "." + role, "not-object")
            continue
        state = process.get("spawnState")
        if state is not None and state not in {
                "not-started", "spawn-attempted", "started", "unknown"}:
            _issue(issues, field + "." + role + ".spawnState", "value")
        identity = process.get("identity")
        if identity is not None and type(identity) is not dict:
            _issue(issues, field + "." + role + ".identity", "not-object")
        if "pid" in process and process.get("pid") is not None \
                and type(process.get("pid")) is not int:
            _issue(issues, field + "." + role + ".pid", "not-integer")


def _validate_resource_proof(value, field, issues):
    if value is None:
        return
    if type(value) is not dict:
        _issue(issues, field, "not-object")
        return
    if value.get("protocol") != RESOURCE_PROOF_PROTOCOL:
        _issue(issues, field + ".protocol", "value")
    if value.get("phase") not in RESOURCE_PHASES:
        _issue(issues, field + ".phase", "value")
    flags = value.get("notCreated")
    if flags is not None:
        if type(flags) is not dict:
            _issue(issues, field + ".notCreated", "not-object")
        else:
            for key, flag in flags.items():
                if key not in RESOURCE_NOT_CREATED_KEYS or type(flag) is not bool:
                    _issue(issues, field + ".notCreated." + str(key), "value")


def _validate_intent_map(value, field, issues):
    if value is None:
        return
    if type(value) is not dict:
        _issue(issues, field, "not-object")
        return
    prepare_id = value.get("prepareId")
    if prepare_id is not None and not _is_prepare_id(prepare_id):
        _issue(issues, field + ".prepareId", "value")
    attempt = value.get("attempt")
    if attempt is not None and type(attempt) is not int:
        _issue(issues, field + ".attempt", "not-integer")
    role = value.get("operationRole")
    if role is not None and type(role) is not str:
        _issue(issues, field + ".operationRole", "not-string")
    alias = value.get("role")
    if alias is not None and type(alias) is not str:
        _issue(issues, field + ".role", "not-string")
    if (role is not None or alias is not None) and lifecycle_role(value) is None:
        _issue(issues, field + ".role", "value")
    tag = value.get("tag")
    if tag is not None and not _is_tag(tag):
        _issue(issues, field + ".tag", "value")
    name = value.get("containerName")
    if name is not None and (type(name) is not str or not name):
        _issue(issues, field + ".containerName", "value")
    identifier = value.get("containerId")
    if identifier is not None and not _is_sha256(identifier):
        _issue(issues, field + ".containerId", "value")
    created = value.get("containerCreated")
    if created is not None and type(created) is not bool:
        _issue(issues, field + ".containerCreated", "not-boolean")
    stage = value.get("stageDir")
    if stage is not None and not _valid_stage_path(stage):
        _issue(issues, field + ".stageDir", "value")
    _validate_stage_identity(value.get("stageIdentity"),
                             field + ".stageIdentity", issues)
    _validate_processes(value.get("processes"), field + ".processes", issues)
    _validate_resource_proof(value.get("resourceProof"),
                             field + ".resourceProof", issues)


def _validate_cleanup(value, field, issues):
    if value is None:
        return
    if type(value) is not dict:
        _issue(issues, field, "not-object")
        return
    state = value.get("state")
    if state is not None and state not in CLEANUP_CHECK_STATES:
        _issue(issues, field + ".state", "value")
    confirmed = value.get("confirmed")
    if confirmed is not None and type(confirmed) is not bool:
        _issue(issues, field + ".confirmed", "not-boolean")
    if state is not None:
        if type(confirmed) is not bool:
            _issue(issues, field + ".confirmed", "required-for-state")
        if (state == "confirmed") != (confirmed is True):
            _issue(issues, field + ".confirmed", "state-disagrees")
    checked_at = value.get("checkedAt")
    if checked_at is not None and (type(checked_at) is not str or not checked_at):
        _issue(issues, field + ".checkedAt", "value")
    if state is not None and (type(checked_at) is not str or not checked_at):
        _issue(issues, field + ".checkedAt", "required-for-state")
    for key in ("finalStageCheck", "reason"):
        item = value.get(key)
        if item is not None and type(item) is not str:
            _issue(issues, field + "." + key, "not-string")
    phase = value.get("resourceCreationPhase")
    if phase is not None and phase not in RESOURCE_PHASES:
        _issue(issues, field + ".resourceCreationPhase", "value")
    for key in ("container", "clientState", "clientStop", "observerState",
                "observerStop", "associated", "associationScan", "stage"):
        item = value.get(key)
        if item is not None and type(item) is not dict:
            _issue(issues, field + "." + key, "not-object")
    for key in ("associatedClear", "clientExited", "observerExited"):
        item = value.get(key)
        if item is not None and type(item) is not bool:
            _issue(issues, field + "." + key, "not-boolean")
    stage = value.get("stage")
    if type(stage) is dict:
        removed = stage.get("removed")
        if removed is not None and type(removed) is not bool:
            _issue(issues, field + ".stage.removed", "not-boolean")
        state_value = stage.get("state")
        if state_value is not None and type(state_value) is not str:
            _issue(issues, field + ".stage.state", "not-string")
    container = value.get("container")
    if type(container) is dict:
        removed = container.get("removed")
        if removed is not None and type(removed) is not bool:
            _issue(issues, field + ".container.removed", "not-boolean")


def _validate_cleanup_check(value, field, issues):
    if value is None:
        return
    if type(value) is not dict:
        _issue(issues, field, "not-object")
        return
    protocol = value.get("protocol")
    if protocol is not None and protocol != CLEANUP_CHECK_PROTOCOL:
        _issue(issues, field + ".protocol", "value")
    state = value.get("state")
    if state is not None and state not in CLEANUP_CHECK_STATES:
        _issue(issues, field + ".state", "value")
    attempt = value.get("attempt")
    if attempt is not None and type(attempt) is not int:
        _issue(issues, field + ".attempt", "not-integer")
    prepare_id = value.get("prepareId")
    if prepare_id is not None and not _is_prepare_id(prepare_id):
        _issue(issues, field + ".prepareId", "value")
    for key in ("startedAt", "finishedAt", "reason"):
        item = value.get(key)
        if item is not None and (type(item) is not str or not item):
            _issue(issues, field + "." + key, "value")
    started_count = value.get("startedCount")
    if started_count is not None and (
            type(started_count) is not int or started_count < 0):
        _issue(issues, field + ".startedCount", "value")
    previous = value.get("previousState")
    if previous is not None and type(previous) is not str:
        _issue(issues, field + ".previousState", "not-string")
    phase = value.get("resourceCreationPhase")
    if phase is not None and phase not in RESOURCE_PHASES:
        _issue(issues, field + ".resourceCreationPhase", "value")


def _validate_cleanup_receipts(value, field, issues):
    if value is None:
        return
    if type(value) is not list:
        _issue(issues, field, "not-list")
        return
    for index, receipt in enumerate(value):
        prefix = "%s[%d]" % (field, index)
        if type(receipt) is not dict:
            _issue(issues, prefix, "not-object")
            continue
        state = receipt.get("state")
        if state not in CLEANUP_RECEIPT_STATES:
            _issue(issues, prefix + ".state", "value")
        confirmed = receipt.get("confirmed")
        if type(confirmed) is not bool:
            _issue(issues, prefix + ".confirmed", "not-boolean")
        checked_at = receipt.get("checkedAt")
        if type(checked_at) is not str or not checked_at:
            _issue(issues, prefix + ".checkedAt", "value")
        phase = receipt.get("resourceCreationPhase")
        if phase is not None and phase not in RESOURCE_PHASES:
            _issue(issues, prefix + ".resourceCreationPhase", "value")


def _valid_associated_prepare_ids(value):
    """Return the valid known child ids plus issues; never invent an id."""
    if value is None:
        return [], []
    if type(value) is not list:
        return [], ["associatedPrepareIds:not-list"]
    rows = []
    issues = []
    for index, item in enumerate(value):
        if _is_prepare_id(item):
            rows.append(item)
        else:
            issues.append("associatedPrepareIds[%d]:value" % index)
    return rows, issues


def _valid_association_intents(value):
    """Return independently valid intent rows plus issues."""
    if value is None:
        return [], []
    if type(value) is not list:
        return [], ["associationIntents:not-list"]
    rows = []
    issues = []
    for index, item in enumerate(value):
        prefix = "associationIntents[%d]" % index
        if type(item) is not dict:
            issues.append(prefix + ":not-object")
            continue
        local = []
        if item.get("protocol") != ASSOCIATION_INTENT_PROTOCOL:
            local.append(prefix + ".protocol:value")
        prepare_id = item.get("prepareId")
        if not _is_prepare_id(prepare_id):
            local.append(prefix + ".prepareId:value")
        attempt = item.get("attempt")
        if attempt is not None and type(attempt) is not int:
            local.append(prefix + ".attempt:not-integer")
        if item.get("state") not in {"pending", "complete"}:
            local.append(prefix + ".state:value")
        if local:
            issues.extend(local)
        else:
            rows.append(dict(item))
    return rows, issues


def _validate_record_fields(record):
    """Validate only fields this recovery path reads, holds or settles."""
    issues = []
    if type(record) is not dict:
        return ["record:not-object"]
    if "attempt" in record and record.get("attempt") is not None \
            and type(record.get("attempt")) is not int:
        _issue(issues, "attempt", "not-integer")
    prepare_id = record.get("prepareId")
    if prepare_id is not None and not _is_prepare_id(prepare_id):
        _issue(issues, "prepareId", "value")
    stage = record.get("stageDir")
    if stage is not None and not _valid_stage_path(stage):
        _issue(issues, "stageDir", "value")
    _validate_stage_identity(record.get("stageIdentity"), "stageIdentity", issues)
    identifier = record.get("containerId")
    if identifier is not None and not _is_sha256(identifier):
        _issue(issues, "containerId", "value")
    name = record.get("containerName")
    if name is not None and (type(name) is not str or not name):
        _issue(issues, "containerName", "value")
    tag = record.get("tag")
    if tag is not None and not _is_tag(tag):
        _issue(issues, "tag", "value")
    _validate_processes(record.get("processes"), "processes", issues)
    _validate_resource_proof(record.get("resourceProof"), "resourceProof", issues)
    for field in ("resourceIntent", "resourceIdentity"):
        if field in record and record.get(field) is not None:
            _validate_intent_map(record.get(field), field, issues)
    _validate_cleanup_receipts(record.get("cleanupReceipts"),
                               "cleanupReceipts", issues)
    _validate_cleanup(record.get("cleanup"), "cleanup", issues)
    _validate_cleanup_check(record.get("cleanupCheck"), "cleanupCheck", issues)
    _, id_issues = _valid_associated_prepare_ids(record.get("associatedPrepareIds"))
    issues.extend(id_issues)
    _, intent_issues = _valid_association_intents(record.get("associationIntents"))
    issues.extend(intent_issues)
    for field in ("reservationHeld", "settled"):
        value = record.get(field)
        if value is not None and type(value) is not bool:
            _issue(issues, field, "not-boolean")
    return issues


def _legacy_fields(record):
    if type(record) is not dict:
        return []
    return [field for field in (
        "resourceIntent", "resourceIdentity", "cleanupReceipts",
        "cleanup", "cleanupCheck",
    ) if record.get(field) is None]


def _validation_result(state, issues, record):
    raw_cleanup = record.get("cleanup") if type(record) is dict \
        and type(record.get("cleanup")) is dict else {}
    raw_check = record.get("cleanupCheck") if type(record) is dict \
        and type(record.get("cleanupCheck")) is dict else {}
    raw_cleanup_confirmed = raw_cleanup.get("confirmed") is True
    raw_reservation_held = type(record) is dict \
        and record.get("reservationHeld") is True
    if state in {"invalid", "unreadable"}:
        cleanup_confirmed = False
        reservation_held = True
    else:
        cleanup_confirmed = raw_cleanup_confirmed
        reservation_held = raw_reservation_held
    return {
        "recordState": state,
        "recordIssues": list(issues),
        "effectiveCleanupConfirmed": cleanup_confirmed,
        "effectiveReservationHeld": reservation_held,
        "rawCleanupConfirmed": raw_cleanup_confirmed,
        "rawReservationHeld": raw_reservation_held,
        "rawCleanupCheckState": raw_check.get("state"),
        "legacyFields": _legacy_fields(record),
    }


def classify_attempt_record(record):
    """Pure field classification for one readable attempt record."""
    issues = _validate_record_fields(record)
    if issues:
        return _validation_result("invalid", issues, record)
    legacy = _legacy_fields(record)
    return _validation_result("legacy" if legacy else "valid", [], record)


def classify_lifecycle_plan(plan, identity_reason=None):
    """Pure field classification for one readable plan record."""
    issues = _validate_record_fields(plan)
    if identity_reason:
        issues.insert(0, "planIdentity:" + str(identity_reason))
    if issues:
        return _validation_result("invalid", issues, plan)
    legacy = _legacy_fields(plan)
    return _validation_result("legacy" if legacy else "valid", [], plan)


def _unreadable_result(detail):
    return _validation_result("unreadable", ["read:" + str(detail)], None)


def _open_failure_result(opened):
    state = "unreadable" if opened.get("state") == "unreadable" else "invalid"
    record = opened.get("record") or opened.get("plan")
    return _validation_result(
        state, ["read:" + str(opened.get("detail") or opened.get("state"))],
        record)


def _add_validation_fields(payload, validation):
    payload.update({
        "recordState": validation["recordState"],
        "recordIssues": list(validation["recordIssues"]),
        "effectiveCleanupConfirmed": validation["effectiveCleanupConfirmed"],
        "effectiveReservationHeld": validation["effectiveReservationHeld"],
        "rawCleanupConfirmed": validation.get("rawCleanupConfirmed"),
        "rawReservationHeld": validation.get("rawReservationHeld"),
        "rawCleanupCheckState": validation.get("rawCleanupCheckState"),
        "legacyFields": list(validation.get("legacyFields") or []),
    })
    return payload


def _attempt_validation(number):
    opened = open_attempt_record(number)
    if opened["state"] == "present":
        return opened, classify_attempt_record(opened["record"])
    if opened["state"] == "contradiction":
        return opened, _validation_result(
            "invalid", ["selector:" + str(opened.get("detail"))],
            opened.get("record"))
    return opened, _open_failure_result(opened)


def _plan_validation(prepare_id):
    opened = open_lifecycle_plan(prepare_id)
    if opened["state"] == "present":
        classification = opened.get("classification") \
            or classify_lifecycle_plan(opened["plan"])
        return opened, classification
    if opened["state"] == "invalid" and opened.get("classification"):
        return opened, opened["classification"]
    if opened["state"] == "contradiction":
        return opened, _validation_result(
            "invalid", ["selector:" + str(opened.get("detail"))],
            opened.get("plan"))
    return opened, _open_failure_result(opened)


def _current_cleanup_confirmed(record):
    """True only for a currently confirmed cleanup on a valid/legacy record."""
    if type(record) is not dict:
        return False
    cleanup = record.get("cleanup")
    if type(cleanup) is not dict or cleanup.get("confirmed") is not True:
        return False
    check = record.get("cleanupCheck")
    if check is None:
        # Old records may predate cleanupCheck; their current cleanup value is
        # still the only success signal they carry.
        return True
    if type(check) is not dict:
        return False
    return check.get("state") == "confirmed"


def settlement_scope(number):
    """Recompute the complete current settlement scope for one attempt.

    The caller boolean and a raw parent ``cleanup.confirmed`` are never enough.
    Every known related lifecycle record is re-read and classified: the
    selected target plan, the durable parent list, association intents, reverse
    child links and standalone compile plans for the attempt.  A completed
    directory enumeration and a currently confirmed cleanup are required for
    each readable record.  Missing, unreadable, malformed, unknown or
    contradictory relations refuse release.  Semantic ``unknown`` values on a
    readable record are not themselves a veto once the actual resource cleanup
    is confirmed.
    """
    opened, validation = _attempt_validation(number)
    problems = []
    if opened["state"] != "present" or validation["recordState"] in {
            "invalid", "unreadable"}:
        return {
            "number": number,
            "state": "refused",
            "problems": ["attempt-record-" + validation["recordState"]],
            "assessment": None,
            "mainPlan": None,
            "related": {},
        }
    record = opened["record"]
    if not _current_cleanup_confirmed(record):
        problems.append("parent-cleanup-unconfirmed")
    assessment = assess_associations(number, record)
    directory = assessment.get("directory") or {}
    if directory.get("state") not in {"present", "absent"}:
        problems.append("association-directory-" + str(directory.get("state")))
    for item in assessment.get("unreadable") or []:
        problems.append("related-unreadable:" + str(item.get("prepareId")))
    for item in assessment.get("damaged") or []:
        problems.append("related-invalid:" + str(item.get("prepareId")))
    for item in assessment.get("incomplete") or []:
        problems.append("association-incomplete:" + str(item))
    for detail in assessment.get("contradictions") or []:
        problems.append("association-contradiction:" + str(detail))
    related = {}
    for prepare_id in sorted(assessment.get("candidates") or {}):
        plan_opened = open_lifecycle_plan(prepare_id)
        if plan_opened["state"] != "present":
            problems.append("related-plan-%s:%s" % (
                prepare_id, plan_opened["state"]))
            related[prepare_id] = {"state": plan_opened["state"]}
            continue
        plan = plan_opened["plan"]
        classification = plan_opened.get("classification") \
            or classify_lifecycle_plan(plan)
        info = lifecycle_role(plan)
        parent = plan.get("parentAttempt")
        reasons = []
        if classification["recordState"] in {"invalid", "unreadable"}:
            reasons.append("record-" + classification["recordState"])
        if info is None or info["kind"] not in {"bind", "compile"}:
            reasons.append("role")
        if parent is not None and parent != number:
            reasons.append("parent")
        if info is not None and info["kind"] == "compile" \
                and info["number"] != number:
            reasons.append("attempt")
        if not _current_cleanup_confirmed(plan):
            reasons.append("cleanup-unconfirmed")
        related[prepare_id] = {
            "state": classification["recordState"],
            "reasons": reasons,
            "parentAttempt": parent,
        }
        for reason in reasons:
            problems.append("related-%s:%s" % (prepare_id, reason))
    main_plan = None
    prepare_id = record.get("prepareId")
    if prepare_id is not None:
        if not _is_prepare_id(prepare_id):
            problems.append("target-prepare-id")
        else:
            plan_opened = open_lifecycle_plan(prepare_id)
            if plan_opened["state"] != "present":
                problems.append("target-plan-" + plan_opened["state"])
            else:
                plan = plan_opened["plan"]
                classification = plan_opened.get("classification") \
                    or classify_lifecycle_plan(plan)
                info = lifecycle_role(plan)
                main_plan = {
                    "prepareId": prepare_id,
                    "state": classification["recordState"],
                }
                if classification["recordState"] in {"invalid", "unreadable"}:
                    problems.append("target-record-" + classification["recordState"])
                if info is None or info["kind"] != "run":
                    problems.append("target-role")
                elif info["number"] != number or plan.get("attempt") != number:
                    problems.append("target-attempt")
                if not _current_cleanup_confirmed(plan):
                    problems.append("target-cleanup-unconfirmed")
    return {
        "number": number,
        "state": "releasable" if not problems else "refused",
        "problems": problems,
        "assessment": assessment,
        "mainPlan": main_plan,
        "related": related,
    }


def _plan_scope_problems():
    """Damaged/unreadable/unknown preparation records in this exact batch."""
    problems = []
    directory = _explicit_directory_entries(plans_dir())
    if directory["state"] == "contradiction":
        return ["prepare-directory:" + str(directory.get("detail"))]
    if directory["state"] == "unknown":
        return ["prepare-directory-unknown:" + str(directory.get("detail"))]
    if directory["state"] == "absent":
        return problems
    names = set(directory["entries"])
    for name in directory["entries"]:
        if name.endswith(".identity.json"):
            prepare_id = name[:-len(".identity.json")]
            if PREPARE_ID_RE.fullmatch(prepare_id) \
                    and (prepare_id + ".json") not in names:
                problems.append("orphan-prepare-identity:" + prepare_id)
            continue
        prepare_id = name[:-5] if name.endswith(".json") else ""
        if not PREPARE_ID_RE.fullmatch(prepare_id):
            continue
        state, _raw = _plan_file_state(plans_dir() / name)
        if state == "missing":
            problems.append("prepare-plan-%s:missing" % prepare_id)
            continue
        if state in {"unreadable", "invalid"}:
            problems.append("prepare-plan-%s:%s" % (prepare_id, state))
            continue
        opened = open_lifecycle_plan(prepare_id)
        if opened["state"] == "contradiction":
            problems.append("prepare-plan-%s:contradiction:%s" % (
                prepare_id, opened.get("detail")))
            continue
        if opened["state"] != "present":
            problems.append("prepare-plan-%s:%s" % (
                prepare_id, opened["state"]))
            continue
        classification = opened.get("classification") \
            or classify_lifecycle_plan(opened["plan"])
        if classification["recordState"] in {"invalid", "unreadable"}:
            problems.append("prepare-plan-%s:%s" % (
                prepare_id, classification["recordState"]))
        identity_state, identity_detail = lifecycle_identity_state(
            prepare_id, opened["plan"])
        if identity_state in {"unreadable", "invalid"}:
            problems.append("prepare-identity-%s:%s" % (
                prepare_id, identity_state))
        elif identity_state == "contradiction":
            problems.append("prepare-identity-%s:contradiction:%s" % (
                prepare_id, identity_detail))
    return problems


def _known_scope_problems():
    """Return damaged/unreadable known records that must block a new task."""
    problems = []
    scan = _scan_attempt_records()
    directory = scan.get("directory") or {}
    if scan["state"] == "contradiction":
        return ["state-directory:" + str(directory.get("detail"))]
    if scan["state"] == "unknown":
        return ["state-directory-unknown:" + str(directory.get("detail"))]
    for item in scan.get("unreadable") or []:
        problems.append("attempt-%04d:%s" % (
            item.get("attempt"), item.get("state")))
    for item in scan.get("invalid") or []:
        problems.append("attempt-%04d:invalid" % item.get("attempt"))
    # The same-batch global rule: any damaged/unreadable/unknown or
    # contradictory preparation record pauses every new task/preparation start
    # in this exact batch, including cross-task reservations.  Other batch
    # roots have their own STATE/PREPARE globals and are unaffected.
    problems.extend(_plan_scope_problems())
    return problems


# ------------------------------------------------------------------ batch lock
def acquire_batch_lock():
    """Exclusive, non-blocking batch lock; one runner at a time."""
    global _LOCK_HANDLE
    if _LOCK_HANDLE is not None:
        return _LOCK_HANDLE
    STATE.mkdir(parents=True, exist_ok=True)
    handle = open(STATE / "batch.lock", "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        if error.errno in (errno.EACCES, errno.EAGAIN):
            die(79, "batch-locked")
        raise
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps({"pid": os.getpid(), "acquiredAt": now()}) + "\n")
    handle.flush()
    os.fsync(handle.fileno())
    _LOCK_HANDLE = handle
    return handle


def release_batch_lock():
    global _LOCK_HANDLE
    if _LOCK_HANDLE is None:
        return
    try:
        fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
    finally:
        _LOCK_HANDLE.close()
        _LOCK_HANDLE = None


# ------------------------------------------------------------------- manifest
def verify_manifest(manifest_path=MANIFEST):
    if not Path(manifest_path).is_file():
        die(78, "manifest-missing")
    if os.path.islink(manifest_path):
        die(78, "manifest-symlink")
    try:
        manifest, manifest_sha = read_json(manifest_path)
    except (OSError, ValueError, UnicodeDecodeError):
        die(78, "manifest-invalid")
    if type(manifest) is not dict or manifest.get("state") != "pending-codex-review":
        die(78, "manifest-state")
    files = manifest.get("files")
    if type(files) is not dict or not files:
        die(78, "manifest-files")
    for relative, expected in files.items():
        if type(relative) is not str or not HASH_RE.fullmatch(expected or ""):
            die(78, "manifest-entry")
        candidate = (ROOT / relative).resolve()
        if ROOT not in candidate.parents or not candidate.is_file():
            die(78, "manifest-path:" + relative)
        if os.path.islink(ROOT / relative):
            die(78, "manifest-symlink:" + relative)
        if sha_file(candidate) != expected:
            die(78, "manifest-file-mismatch:" + relative)
    return manifest, manifest_sha


def verify_preflight_receipt(admission, manifest_sha):
    """Verify the actual preflight evidence, not its stored pass booleans."""
    relative = admission.get("preflightReceiptPath")
    if relative is None:
        die(78, "admission-preflight-path")
    try:
        receipt_path = preflight_verify.resolve_under(ROOT, relative)
    except preflight_verify.PreflightError as error:
        die(78, "admission-preflight-path:" + error.reason)
    try:
        actual_receipt_sha = preflight_verify.sha_bytes(
            preflight_verify.read_regular_bytes(receipt_path)
        )
    except preflight_verify.PreflightError as error:
        die(78, "admission-preflight:" + error.reason)
    if admission.get("preflightReceiptSha256") != actual_receipt_sha:
        die(78, "admission-preflight-tampered")
    expected_id = admission.get("preflightId")
    try:
        result = preflight_verify.verify_preflight_evidence(
            ROOT,
            receipt_path,
            ROOT / "codex-review" / "preflight-admission.json",
            SOURCE_REVIEW_RECEIPT,
            MANIFEST,
            PROFILE,
            expected_id=expected_id,
        )
    except preflight_verify.PreflightError as error:
        die(78, "admission-preflight:" + error.reason)
    if admission.get("preflightReceiptSha256") != result["receiptSha256"]:
        die(78, "admission-preflight-tampered")
    if expected_id != result["preflightId"]:
        die(78, "admission-preflight-id")
    if result["receipt"].get("protocolManifestSha256") != manifest_sha:
        die(78, "admission-preflight-manifest")
    return result


def verify_source_review(admission, manifest_sha):
    path = SOURCE_REVIEW_RECEIPT
    if not path.is_file() or os.path.islink(path):
        die(78, "admission-review-missing")
    try:
        review, review_sha = read_json(path)
    except (OSError, ValueError, UnicodeDecodeError):
        die(78, "admission-review-invalid")
    if admission.get("sourceReviewReceiptSha256") != review_sha:
        die(78, "admission-review-tampered")
    if type(review) is not dict or review.get("state") != "completed":
        die(78, "admission-review-state")
    if review.get("protocolManifestSha256") != manifest_sha:
        die(78, "admission-review-manifest")
    if review.get("blockers"):
        die(78, "admission-review-blockers")
    return review, review_sha


# ------------------------------------------------------------------- admission
def require_admission(command, attempt=None, prepare_step=None):
    """Refuse before creating any target resource or writing state."""
    global _PREFLIGHT_RESULT
    if not ADMISSION.is_file():
        die(78, "admission-missing")
    try:
        admission, admission_sha = read_json(ADMISSION)
    except (OSError, ValueError, UnicodeDecodeError):
        die(78, "admission-invalid")
    if type(admission) is not dict or admission.get("kind") != "experiment-admission":
        die(78, "admission-shape")
    if admission.get("protocolRevision") != PROTOCOL_REVISION:
        die(78, "admission-revision")
    if admission.get("state") != "approved":
        die(78, "admission-state")
    if not isinstance(admission.get("reviewer"), str) or not admission["reviewer"].strip():
        die(78, "admission-reviewer")
    if not HASH_RE.fullmatch(admission.get("reviewReceiptSha256") or ""):
        die(78, "admission-receipt")
    manifest, manifest_sha = verify_manifest(MANIFEST)
    if admission.get("protocolManifestSha256") != manifest_sha:
        die(78, "admission-manifest-mismatch")
    verify_source_review(admission, manifest_sha)
    preflight_result = verify_preflight_receipt(admission, manifest_sha)
    allowed = admission.get("allowedAttempts")
    if type(allowed) is not list or not 1 <= len(allowed) <= LIMITS["maxAttempts"]:
        die(78, "admission-attempts")
    if any(type(number) is not int or not 1 <= number <= LIMITS["maxAttempts"] for number in allowed):
        die(78, "admission-attempt-range")
    if len(set(allowed)) != len(allowed):
        die(78, "admission-attempt-duplicate")
    if admission.get("maxTargetExecutions") != len(allowed):
        die(78, "admission-budget")
    if attempt is not None and attempt not in allowed:
        die(78, "attempt-not-admitted")
    steps = admission.get("allowedPrepareSteps")
    if type(steps) is not list or any(step not in PREPARE_STEPS for step in steps):
        die(78, "admission-prepare-steps")
    if prepare_step is not None and prepare_step not in steps:
        die(78, "prepare-step-not-admitted")
    for field in ("observationProtocol", "framingPolicy",
                  "bufferParserSha256", "bufferTemplateSha256"):
        if field in admission and admission.get(field) != preflight_result.get(field):
            die(78, "admission-" + field)
    _PREFLIGHT_RESULT = preflight_result
    return admission, manifest, manifest_sha, admission_sha, preflight_result


def load_plan():
    plan, plan_sha = read_json(PLAN)
    if type(plan) is not dict or plan.get("version") != 1:
        die(79, "plan-shape")
    attempts = plan.get("attempts")
    fixtures = plan.get("fixtures")
    if type(attempts) is not list or len(attempts) != 16:
        die(79, "plan-attempt-count")
    if type(fixtures) is not list or len(fixtures) != 4:
        die(79, "plan-fixture-count")
    if sorted(item.get("attempt") for item in attempts if type(item) is dict) != list(range(1, 17)):
        die(79, "plan-attempt-numbers")
    counts = {}
    for item in attempts:
        counts[item.get("classId")] = counts.get(item.get("classId"), 0) + 1
        fixture = (ROOT / item["fixture"]).resolve()
        if not fixture.is_file() or ROOT not in fixture.parents:
            die(79, "plan-fixture")
        if sha_file(fixture) != item.get("sourceSha256"):
            die(79, "plan-fixture-digest")
        if type(item.get("argvBase")) is not list or type(item.get("probeIndex")) is not int:
            die(79, "plan-argv")
        index = item["probeIndex"]
        if not 0 <= index < len(item["argvBase"]):
            die(79, "plan-probe-index")
        if item["argvBase"][index] != item["probePrefix"] + item["probeSuffix"]:
            die(79, "plan-probe-affixes")
    if sorted(counts.values()) != [4, 4, 4, 4]:
        die(79, "plan-class-counts")
    return plan, plan_sha


def closure_sources_for(plan, class_id):
    """Resolve the closure source map from the frozen fixture record."""
    entries = [item for item in plan.get("fixtures", []) if item.get("classId") == class_id]
    if len(entries) != 1:
        die(79, "fixture-record-selection:" + str(class_id))
    sources = entries[0].get("closureSources")
    if type(sources) is not dict or not sources:
        die(79, "fixture-closure-missing:" + str(class_id))
    for relative, source in sources.items():
        if type(relative) is not str or not relative.endswith(".py") or "/" in relative or ".." in relative:
            die(79, "fixture-closure-name:" + str(relative))
        if type(source) is not str:
            die(79, "fixture-closure-source")
        path = (ROOT / source).resolve()
        if ROOT not in path.parents or not path.is_file():
            die(79, "fixture-closure-path:" + source)
    return dict(sources)


# ------------------------------------------------------- verified preflight
def preflight_context():
    if _PREFLIGHT_RESULT is None:
        die(78, "preflight-context-missing")
    return _PREFLIGHT_RESULT


def prepare_layout_from_preflight(preflight_result):
    """Use the verified preflight layout bytes; never re-measure or replace."""
    payload = preflight_result["layoutBytes"]
    layout_path = PREPARE / "layout" / "layout.json"
    layout_sha, status = guard.write_new_or_identical(layout_path, payload)
    if layout_sha is None:
        die(79, "layout-write:" + str(status))
    if layout_sha != preflight_result["layoutSha256"]:
        die(79, "layout-digest")
    layout_receipt = {
        "version": 3,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "prepare-receipt",
        "step": "layout-v1",
        "state": "completed",
        "preflightId": preflight_result["preflightId"],
        "preflightReceiptSha256": preflight_result["receiptSha256"],
        "protocolManifestSha256": preflight_result["manifestSha256"],
        "profileSha256": preflight_result["profileSha256"],
        "imageId": preflight_result["profile"]["imageId"],
        "pythonVersion": preflight_result["profile"]["pythonVersion"],
        "interpreterSha256": preflight_result["profile"]["interpreterSha256"],
        "librarySha256": preflight_result["profile"]["librarySha256"],
        "layoutSha256": layout_sha,
        "layoutStructureSha256": preflight_result["layoutStructureSha256"],
        "observationProtocol": OBSERVATION_PROTOCOL,
        "framingPolicy": FRAMING_POLICY,
        "bufferParser": "tools/" + BUFFER_PARSER_NAME,
        "bufferParserSha256": preflight_result["bufferParserSha256"],
        "bufferTemplate": "tools/" + BUFFER_TEMPLATE_NAME,
        "bufferTemplateSha256": preflight_result["bufferTemplateSha256"],
        "frozenTemplate": BUFFER_TEMPLATE_NAME,
        "frozenTemplateSha256": preflight_result["frozenTemplateSha256"],
        "preflightObserverSha256": preflight_result["templateSha256"],
        "targetExecutions": 0,
        "createdAt": now(),
    }
    receipt_sha, status = guard.write_new_or_identical(
        PREPARE / "layout-receipt.json", guard.json_bytes(layout_receipt)
    )
    if receipt_sha is None:
        die(79, "layout-receipt-write:" + str(status))
    return preflight_result["layout"], layout_sha


def verify_prepare_inputs(preflight_result):
    """Recheck layout/profile/template bytes before every use."""
    layout_path = PREPARE / "layout" / "layout.json"
    if not layout_path.is_file() or os.path.islink(layout_path):
        die(79, "layout-missing")
    with open(layout_path, "rb") as handle:
        layout_raw = handle.read()
    layout_sha = sha_bytes(layout_raw)
    if layout_sha != preflight_result["layoutSha256"]:
        die(79, "layout-digest")
    try:
        layout = json.loads(layout_raw)
    except (ValueError, UnicodeDecodeError):
        die(79, "layout-json")
    if structure.digest(layout) != preflight_result["layoutStructureSha256"]:
        die(79, "layout-structure")
    if layout.get("preflightId") != preflight_result["preflightId"]:
        die(79, "layout-preflight-id")
    if layout.get("runtime") != preflight_verify.profile_identity(preflight_result["profile"]):
        die(79, "layout-profile")
    receipt_path = PREPARE / "layout-receipt.json"
    if not receipt_path.is_file() or os.path.islink(receipt_path):
        die(79, "layout-receipt-missing")
    try:
        layout_receipt, _ = read_json(receipt_path)
    except (OSError, ValueError, UnicodeDecodeError):
        die(79, "layout-receipt-invalid")
    if layout_receipt.get("preflightId") != preflight_result["preflightId"]:
        die(79, "layout-receipt-preflight-id")
    if layout_receipt.get("preflightReceiptSha256") != preflight_result["receiptSha256"]:
        die(79, "layout-receipt-cross-run")
    if layout_receipt.get("layoutSha256") != layout_sha:
        die(79, "layout-receipt-digest")
    if layout_receipt.get("layoutStructureSha256") != structure.digest(layout):
        die(79, "layout-receipt-structure")
    if layout_receipt.get("observationProtocol") != OBSERVATION_PROTOCOL:
        die(79, "layout-receipt-observation-protocol")
    if layout_receipt.get("framingPolicy") != FRAMING_POLICY:
        die(79, "layout-receipt-framing-policy")
    if layout_receipt.get("bufferParserSha256") != preflight_result.get("bufferParserSha256"):
        die(79, "layout-receipt-parser")
    if layout_receipt.get("bufferTemplateSha256") != preflight_result.get("bufferTemplateSha256"):
        die(79, "layout-receipt-template")
    if layout_receipt.get("frozenTemplateSha256") != preflight_result.get("frozenTemplateSha256"):
        die(79, "layout-receipt-frozen-template")
    # Formal observation identity comes from the actual verified preflight
    # buffer template and parser bytes.  The old toolDigests["observer_template.bt"]
    # entry and the rendered preflight observer.bt are diagnostic only and are
    # never used as the formal template link.
    if preflight_result.get("observationProtocol") != OBSERVATION_PROTOCOL:
        die(79, "observation-protocol")
    if preflight_result.get("framingPolicy") != FRAMING_POLICY:
        die(79, "framing-policy")
    expected_frozen_sha = preflight_result.get("frozenTemplateSha256")
    frozen_bytes = preflight_result.get("frozenTemplateBytes")
    if type(frozen_bytes) is not bytes or sha_bytes(frozen_bytes) != expected_frozen_sha:
        die(79, "frozen-template-bytes")
    expected_buffer_sha = preflight_result.get("bufferTemplateSha256")
    if expected_buffer_sha != expected_frozen_sha:
        die(79, "frozen-template-digest")
    template_path = TOOLS / BUFFER_TEMPLATE_NAME
    if not template_path.is_file() or os.path.islink(template_path):
        die(79, "template-missing")
    with open(template_path, "rb") as handle:
        template_bytes = handle.read()
    template_sha = sha_bytes(template_bytes)
    if template_sha != expected_buffer_sha:
        die(79, "template-digest")
    if template_bytes != frozen_bytes:
        die(79, "template-bytes")
    if buffer_protocol_v2.MARKER.encode("ascii") not in template_bytes:
        die(79, "template-marker")
    parser_path = TOOLS / BUFFER_PARSER_NAME
    if not parser_path.is_file() or os.path.islink(parser_path):
        die(79, "parser-missing")
    parser_sha = sha_file(parser_path)
    if parser_sha != preflight_result.get("bufferParserSha256"):
        die(79, "parser-digest")
    try:
        profile, profile_sha = preflight_verify.load_profile(PROFILE)
    except preflight_verify.PreflightError as error:
        die(79, "profile:" + error.reason)
    if profile_sha != preflight_result["profileSha256"]:
        die(79, "profile-digest")
    if preflight_verify.profile_identity(profile) != preflight_verify.profile_identity(preflight_result["profile"]):
        die(79, "profile-identity")
    return {
        "layout": layout,
        "layoutSha256": layout_sha,
        "layoutStructureSha256": structure.digest(layout),
        "layoutBytes": layout_raw,
        "templateBytes": template_bytes,
        "templateSha256": template_sha,
        "templateName": BUFFER_TEMPLATE_NAME,
        "frozenTemplateSha256": expected_frozen_sha,
        "bufferTemplateSha256": expected_buffer_sha,
        "bufferParserSha256": parser_sha,
        "bufferParserName": BUFFER_PARSER_NAME,
        "observationProtocol": OBSERVATION_PROTOCOL,
        "framingPolicy": FRAMING_POLICY,
        "profile": profile,
        "profileSha256": profile_sha,
    }


def observation_identity_fields(inputs):
    """The exact buffer-v2/framing/parser/template identity carried to disk."""
    return {
        "observationProtocol": OBSERVATION_PROTOCOL,
        "framingPolicy": FRAMING_POLICY,
        "bufferParser": "tools/" + BUFFER_PARSER_NAME,
        "bufferParserSha256": inputs["bufferParserSha256"],
        "bufferTemplate": "tools/" + BUFFER_TEMPLATE_NAME,
        "bufferTemplateSha256": inputs["bufferTemplateSha256"],
        "frozenTemplate": BUFFER_TEMPLATE_NAME,
        "frozenTemplateSha256": inputs["frozenTemplateSha256"],
    }


# ------------------------------------------------------------------- attempts
def attempt_path(number):
    return Path(STATE) / ("attempt-%04d.json" % number)


def counter_path():
    return Path(STATE) / "attempt-counter.json"


def load_counter():
    if not counter_path().is_file():
        return {"version": 1, "used": [], "max": LIMITS["maxAttempts"]}
    value, _ = read_json(counter_path())
    if type(value) is not dict or type(value.get("used")) is not list:
        die(79, "counter-corrupt")
    return value


def update_attempt(number, **fields):
    record, _ = read_json(attempt_path(number))
    current = classify_attempt_record(record)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecordValidationError(
            "attempt-journal-invalid:" + ",".join(current["recordIssues"][:4]))
    candidate = dict(record)
    candidate.update(fields)
    fresh = classify_attempt_record(candidate)
    if fresh["recordState"] == "invalid":
        raise RecordValidationError(
            "attempt-journal-update-invalid:" + ",".join(fresh["recordIssues"][:4]))
    write_json_document(attempt_path(number), candidate)
    return candidate


def durable_update_attempt(number, **fields):
    """Write and read back one attempt journal before treating it as durable.

    A write whose bytes cannot be read back is unknown persistence: callers
    must return incomplete (3) and must not claim cleanup success.
    """
    update_attempt(number, **fields)
    stored, _ = read_json(attempt_path(number))
    if type(stored) is not dict:
        raise RuntimeError("attempt-journal-shape")
    for key, value in fields.items():
        if stored.get(key) != value:
            raise RuntimeError("attempt-journal-unconfirmed:" + key)
    return stored


def checkpoint(number, step, **fields):
    record, _ = read_json(attempt_path(number))
    current = classify_attempt_record(record)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecordValidationError(
            "attempt-journal-invalid:" + ",".join(current["recordIssues"][:4]))
    trail = list(record.get("checkpoints") or [])
    trail.append({"step": step, "at": now(), **fields})
    candidate = dict(record)
    candidate["checkpoints"] = trail[-64:]
    candidate["checkpointStep"] = step
    fresh = classify_attempt_record(candidate)
    if fresh["recordState"] == "invalid":
        raise RecordValidationError(
            "attempt-journal-update-invalid:" + ",".join(fresh["recordIssues"][:4]))
    write_json_document(attempt_path(number), candidate)
    return candidate


def random_tag():
    return os.urandom(8).hex()


def container_name(role, tag):
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "-", role)[:30]
    return "stdlib-cli-%s-%s" % (cleaned, tag[:24])


def lifecycle_role(plan):
    """Return the exact role kind/number, or ``None`` for an unknown role.

    ``operationRole`` and ``role`` must agree.  Only the three tool-owned role
    shapes are accepted: ``run-NNNN``, ``bind-XXXXXXXX`` and
    ``compile-NNNN-XXXXXXXX``.  There is deliberately no project-chosen role.
    """
    if type(plan) is not dict:
        return None
    operation = plan.get("operationRole")
    role = plan.get("role")
    if operation is None:
        operation = role
    if role is None:
        role = operation
    if type(operation) is not str or operation != role:
        return None
    match = ROLE_RUN_RE.fullmatch(operation)
    if match:
        return {"kind": "run", "number": int(match.group(1)), "role": operation}
    match = ROLE_BIND_RE.fullmatch(operation)
    if match:
        return {"kind": "bind", "number": None, "suffix": match.group(1),
                "role": operation}
    match = ROLE_COMPILE_RE.fullmatch(operation)
    if match:
        return {"kind": "compile", "number": int(match.group(1)),
                "suffix": match.group(2), "role": operation}
    return None


def lifecycle_stage_expected(info, tag, attempt):
    if info["kind"] == "run":
        return Path(RUNS) / ("%04d" % info["number"]) / ("stage-" + tag)
    if info["kind"] == "bind":
        return Path(PREPARE) / ("stage-bind-" + tag)
    return Path(PREPARE) / ("stage-compile-%04d-%s" % (info["number"], tag))


def _path_has_link(path, stop):
    """True when a component from ``stop`` down to ``path`` is a symlink."""
    current = Path(path)
    stop = Path(stop)
    while True:
        state = guard.path_state(current)
        if state["state"] == "present" and state.get("symlink"):
            return True
        if current == stop or current == current.parent:
            return False
        current = current.parent


def lifecycle_stage_reason(plan, info):
    """Bind a plan's stage to its exact predetermined role path."""
    stage = plan.get("stageDir")
    if type(stage) is not str or not stage or "\x00" in stage:
        return "stage-path"
    try:
        candidate = Path(stage)
    except (OSError, ValueError):
        return "stage-path"
    if not candidate.is_absolute() or ".." in candidate.parts:
        return "stage-path"
    tag = plan.get("tag")
    if type(tag) is not str or not TAG_RE.fullmatch(tag):
        return "tag"
    expected = lifecycle_stage_expected(info, tag, plan.get("attempt"))
    if candidate != expected:
        return "stage-role-path"
    root = Path(RUNS) if info["kind"] == "run" else Path(PREPARE)
    if _path_has_link(expected, root):
        return "stage-path-link"
    return None


def lifecycle_not_created_default():
    return {key: True for key in RESOURCE_NOT_CREATED_KEYS}


def advance_resource_proof(record, phase, not_created=None, **detail):
    """Return a monotonic resource-phase proof; never move backward."""
    if phase not in RESOURCE_PHASES:
        die(78, "resource-phase-unknown")
    current = record.get("resourceProof") if type(record) is dict else None
    if current is None:
        current = {
            "protocol": RESOURCE_PROOF_PROTOCOL,
            "phase": "reserved",
            "sequence": [{"phase": "reserved", "at": now()}],
            "notCreated": lifecycle_not_created_default(),
            "targetAttempt": record.get("attempt") if type(record) is dict else None,
        }
    if type(current) is not dict or current.get("protocol") != RESOURCE_PROOF_PROTOCOL:
        die(78, "resource-proof-protocol")
    previous = current.get("phase")
    if previous in RESOURCE_PHASES and RESOURCE_PHASES.index(phase) < RESOURCE_PHASES.index(previous):
        die(78, "resource-phase-regression")
    sequence = list(current.get("sequence") or [])
    sequence.append({"phase": phase, "at": now(), **detail})
    flags = dict(current.get("notCreated") or lifecycle_not_created_default())
    for key, value in (not_created or {}).items():
        if key not in RESOURCE_NOT_CREATED_KEYS or type(value) is not bool:
            die(78, "resource-proof-flag")
        if flags.get(key) is True and value is False:
            flags[key] = False
        elif flags.get(key) is False and value is True:
            die(78, "resource-proof-flag-regression")
    return {
        "protocol": RESOURCE_PROOF_PROTOCOL,
        "phase": phase,
        "sequence": sequence[-64:],
        "notCreated": flags,
        "targetAttempt": current.get("targetAttempt"),
    }


def advance_attempt_proof(number, phase, not_created=None, **detail):
    record, _ = read_json(attempt_path(number))
    proof = advance_resource_proof(record, phase, not_created=not_created, **detail)
    return update_attempt(number, resourceProof=proof)


def has_not_created_proof(record):
    """Explicit new-protocol proof that no stage/container/process exists."""
    proof = record.get("resourceProof") if type(record) is dict else None
    if type(proof) is not dict or proof.get("protocol") != RESOURCE_PROOF_PROTOCOL:
        return False
    if proof.get("phase") not in {"reserved", "plan-created", "cleanup-confirmed"}:
        return False
    flags = proof.get("notCreated")
    if type(flags) is not dict:
        return False
    return all(flags.get(key) is True for key in RESOURCE_NOT_CREATED_KEYS)


def associated_prepare_ids(record):
    value = record.get("associatedPrepareIds") if type(record) is dict else None
    if value is None:
        return []
    if type(value) is not list or any(
            type(item) is not str or not PREPARE_ID_RE.fullmatch(item) for item in value):
        die(78, "associated-prepare-ids")
    return list(value)


def association_intents(record):
    """Read the durable association intent list without inventing entries."""
    value = record.get("associationIntents") if type(record) is dict else None
    if value is None:
        return []
    if type(value) is not list:
        die(78, "association-intents")
    rows = []
    for item in value:
        if type(item) is not dict:
            die(78, "association-intent-shape")
        if item.get("protocol") != ASSOCIATION_INTENT_PROTOCOL:
            die(78, "association-intent-protocol")
        prepare_id = item.get("prepareId")
        if type(prepare_id) is not str or not PREPARE_ID_RE.fullmatch(prepare_id):
            die(78, "association-intent-prepare-id")
        if item.get("attempt") is not None and type(item.get("attempt")) is not int:
            die(78, "association-intent-attempt")
        if item.get("state") not in {"pending", "complete"}:
            die(78, "association-intent-state")
        rows.append(dict(item))
    return rows


def association_complete(record, prepare_id):
    """True only when the parent list and a matching completed intent agree."""
    try:
        listed = associated_prepare_ids(record)
        intents = association_intents(record)
    except SystemExit:
        return False
    return prepare_id in listed and any(
        item.get("prepareId") == prepare_id and item.get("state") == "complete"
        for item in intents)


def require_association_complete(number, prepare_id):
    """A child may not create resources without a durably completed link."""
    record, _ = read_json(attempt_path(number))
    current = classify_attempt_record(record)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecoveryIncomplete("attempt-record-invalid")
    if not association_complete(record, prepare_id):
        raise RecoveryIncomplete("association-incomplete")
    plan, _path = read_lifecycle_plan(prepare_id)
    if plan.get("parentAttempt") != number:
        raise RecoveryIncomplete("association-child-link-missing")
    return record


def require_all_associations_complete(number):
    """Before target resources exist, every intent must be complete and linked."""
    record, _ = read_json(attempt_path(number))
    current = classify_attempt_record(record)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecoveryIncomplete("attempt-record-invalid")
    pending = [item for item in association_intents(record)
               if item.get("state") != "complete"]
    if pending:
        raise RecoveryIncomplete("association-incomplete")
    for prepare_id in associated_prepare_ids(record):
        plan, _path = read_lifecycle_plan(prepare_id)
        if plan.get("parentAttempt") != number:
            raise RecoveryIncomplete("association-child-link-missing")
    return record


def _plan_file_state(path):
    state = guard.path_state(path)
    if state["state"] == "absent":
        return "missing", None
    if state["state"] == "unknown":
        return "unreadable", None
    if state.get("symlink") or not state.get("isFile"):
        return "invalid", None
    try:
        raw, _ = read_json(path)
    except PermissionError:
        return "unreadable", None
    except (OSError, ValueError, UnicodeDecodeError):
        return "invalid", None
    if type(raw) is not dict:
        return "invalid", None
    return "present", raw


def _raw_plan_relevant(raw, prepare_id, number, listed, intent_ids, target_id):
    """Decide whether a readable raw plan claims this target attempt."""
    if prepare_id == target_id:
        return False, None
    raw_id = raw.get("prepareId")
    parent = raw.get("parentAttempt")
    attempt = raw.get("attempt")
    role = raw.get("operationRole")
    if role is None:
        role = raw.get("role")
    if type(raw_id) is not str:
        return False, "prepare-plan-selector-invalid:" + prepare_id
    if parent is not None and type(parent) is not int:
        return False, "prepare-plan-parent-invalid:" + prepare_id
    if attempt is not None and type(attempt) is not int:
        return False, "prepare-plan-attempt-invalid:" + prepare_id
    if role is not None and type(role) is not str:
        return False, "prepare-plan-role-invalid:" + prepare_id
    if raw_id != prepare_id:
        if prepare_id in listed or prepare_id in intent_ids:
            return False, "prepare-plan-selector-mismatch:" + prepare_id
        if parent == number:
            return False, "prepare-plan-selector-mismatch:" + prepare_id
        if type(role) is str and role.startswith("compile-") \
                and attempt == number:
            return False, "prepare-plan-selector-mismatch:" + prepare_id
        return False, None
    if prepare_id in listed or prepare_id in intent_ids:
        return True, None
    if parent == number:
        return True, None
    if type(role) is str and role.startswith("compile-") \
            and attempt == number:
        return True, None
    if parent is not None and parent != number:
        return False, None
    return False, None


def _directory_state(path):
    """Tri-state directory identity, including links and ownership."""
    state = guard.path_state(path)
    if state["state"] == "absent":
        return {"state": "absent", "detail": "file-not-found"}
    if state["state"] == "unknown":
        return {"state": "unknown", "detail": state.get("detail")}
    if state.get("symlink"):
        return {"state": "contradiction", "detail": "symlink"}
    if not state.get("isDir"):
        return {"state": "contradiction", "detail": "not-directory"}
    try:
        info = os.lstat(path)
    except PermissionError:
        return {"state": "unknown", "detail": "permission-denied"}
    except OSError as error:
        return {"state": "unknown", "detail": type(error).__name__}
    if info.st_uid != os.getuid():
        return {"state": "contradiction", "detail": "ownership"}
    return {
        "state": "present",
        "detail": "directory",
        "dev": info.st_dev,
        "ino": info.st_ino,
        "uid": info.st_uid,
        "mode": info.st_mode,
    }


def _explicit_directory_entries(path):
    """Enumerate a directory explicitly and prove that iteration completed.

    ``Path.glob`` suppresses lookup failures and cannot distinguish a complete
    empty directory from an unreadable one.  This helper keeps the entries read
    before a partial failure and returns ``unknown`` instead of an empty list.
    """
    before = _directory_state(path)
    if before["state"] != "present":
        return {**before, "entries": []}
    entries = []
    failure = None
    iterator = None
    try:
        iterator = os.scandir(path)
        while True:
            try:
                entry = next(iterator)
            except StopIteration:
                break
            except PermissionError:
                failure = "permission-denied"
                break
            except OSError as error:
                failure = type(error).__name__
                break
            entries.append(entry.name)
    except PermissionError:
        failure = "permission-denied"
    except OSError as error:
        failure = type(error).__name__
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            try:
                close()
            except OSError as error:
                if failure is None:
                    failure = type(error).__name__
    if failure is not None:
        return {"state": "unknown", "detail": failure,
                "entries": sorted(entries), "identity": before}
    after = _directory_state(path)
    if after["state"] == "absent":
        return {"state": "unknown", "detail": "directory-disappeared",
                "entries": sorted(entries), "identity": before}
    if after["state"] != "present":
        return {**after, "entries": sorted(entries), "identity": before}
    if (after["dev"], after["ino"], after["uid"]) != (
            before["dev"], before["ino"], before["uid"]):
        return {"state": "contradiction", "detail": "identity-changed",
                "entries": sorted(entries), "identity": before}
    return {"state": "present", "detail": "directory",
            "entries": sorted(entries), "identity": after,
            "dev": after["dev"], "ino": after["ino"], "uid": after["uid"]}


def _same_directory_scope(recorded, current):
    if recorded.get("state") == "absent":
        return current.get("state") == "absent"
    if recorded.get("state") != "present" or current.get("state") != "present":
        return False
    return (
        (recorded.get("dev"), recorded.get("ino"), recorded.get("uid"))
        == (current.get("dev"), current.get("ino"), current.get("uid"))
        and list(recorded.get("entries") or [])
        == list(current.get("entries") or [])
    )


def _revalidate_association_scope(assessment):
    """Re-prove the exact directory scope immediately before destruction."""
    recorded = assessment.get("directory") if type(assessment) is dict else None
    if type(recorded) is not dict:
        return
    current = _explicit_directory_entries(plans_dir())
    if current["state"] == "unknown":
        raise RecoveryIncomplete(
            "association-directory-unknown:" + str(current.get("detail")))
    if current["state"] == "contradiction":
        die(78, "association-directory-" + str(current.get("detail")))
    if not _same_directory_scope(recorded, current):
        die(78, "association-directory-changed")


def open_attempt_record(number):
    """Classify one recovering attempt-record read without inventing metadata."""
    path = attempt_path(number)
    state = guard.path_state(path)
    if state["state"] == "absent":
        return {"state": "missing", "detail": "file-not-found", "path": path}
    if state["state"] == "unknown":
        return {"state": "unreadable", "detail": state.get("detail"),
                "path": path}
    if state.get("symlink") or not state.get("isFile"):
        return {"state": "invalid", "detail": "not-regular-file", "path": path}
    try:
        record, _ = read_json(path)
    except PermissionError:
        return {"state": "unreadable", "detail": "permission-denied",
                "path": path}
    except UnicodeDecodeError:
        return {"state": "invalid", "detail": "unicode", "path": path}
    except ValueError:
        return {"state": "invalid", "detail": "json", "path": path}
    except OSError as error:
        return {"state": "unreadable", "detail": type(error).__name__,
                "path": path}
    if type(record) is not dict:
        return {"state": "invalid", "detail": "shape", "path": path}
    value = record.get("attempt")
    if type(value) is not int:
        return {"state": "invalid", "detail": "attempt-field", "path": path}
    if value != number:
        return {"state": "contradiction", "detail": "selector-mismatch",
                "record": record, "path": path}
    return {"state": "present", "record": record, "path": path}


def _scan_attempt_records():
    """Explicitly enumerate the attempt journals used for parent resolution."""
    directory = _explicit_directory_entries(Path(STATE))
    result = {
        "state": directory["state"],
        "directory": directory,
        "records": {},
        "unreadable": [],
        "invalid": [],
        "contradictions": [],
    }
    if directory["state"] != "present":
        return result
    for name in directory["entries"]:
        match = ATTEMPT_RECORD_RE.fullmatch(name)
        if not match:
            continue
        number = int(match.group(1))
        opened = open_attempt_record(number)
        if opened["state"] == "present":
            # Keep the raw record for relationship discovery, but never treat
            # an invalid field as writable or as a success signal.
            result["records"][number] = opened["record"]
            classification = classify_attempt_record(opened["record"])
            if classification["recordState"] == "invalid":
                result["invalid"].append({
                    "attempt": number,
                    "state": "invalid",
                    "issues": classification["recordIssues"],
                })
        elif opened["state"] == "contradiction":
            result["contradictions"].append(
                "attempt-record:" + str(opened.get("detail")))
        elif opened["state"] != "missing":
            result["unreadable"].append({
                "attempt": number,
                "state": opened["state"],
                "detail": opened.get("detail"),
            })
    return result


def attempt_references_prepare(record, prepare_id):
    """True only for an actually recorded parent list, intent or prepare link.

    Independently valid relationship fields are usable even when another field
    on the same record is damaged; no malformed field is guessed or repaired.
    """
    if type(record) is not dict:
        return False
    if record.get("prepareId") == prepare_id:
        return True
    ids, _ = _valid_associated_prepare_ids(record.get("associatedPrepareIds"))
    if prepare_id in ids:
        return True
    intents, _ = _valid_association_intents(record.get("associationIntents"))
    return any(item.get("prepareId") == prepare_id for item in intents)


def resolve_prepare_parent(plan, prepare_id):
    """Resolve an exact parent from durable links; never invent one."""
    scan = _scan_attempt_records()
    directory = scan.get("directory") or {}
    if scan["state"] == "contradiction":
        die(78, "state-directory-" + str(directory.get("detail")))
    if scan["state"] == "unknown":
        return {"state": "incomplete",
                "reason": "state-directory-unknown", "referencing": []}
    if scan["contradictions"]:
        die(78, scan["contradictions"][0])
    referencing = []
    for number, record in sorted(scan["records"].items()):
        if attempt_references_prepare(record, prepare_id):
            referencing.append(number)
    if scan["unreadable"]:
        return {"state": "incomplete", "reason": "attempt-record-unreadable",
                "referencing": referencing,
                "unreadable": scan["unreadable"]}
    if scan["invalid"]:
        return {"state": "incomplete", "reason": "attempt-record-invalid",
                "referencing": referencing,
                "invalid": scan["invalid"]}
    parent = plan.get("parentAttempt")
    if parent is not None:
        if type(parent) is not int:
            return {"state": "incomplete", "reason": "parent-attempt-invalid",
                    "referencing": referencing}
        if parent not in referencing:
            return {"state": "incomplete", "reason": "parent-link-unconfirmed",
                    "referencing": referencing, "parentAttempt": parent}
        if len(referencing) > 1:
            return {"state": "contradiction", "reason": "ambiguous-parent",
                    "referencing": referencing, "parentAttempt": parent}
        return {"state": "bound", "parentAttempt": parent,
                "referencing": referencing}
    if len(referencing) > 1:
        return {"state": "contradiction", "reason": "ambiguous-parent",
                "referencing": referencing}
    if len(referencing) == 1:
        return {"state": "incomplete", "reason": "child-unlinked",
                "referencing": referencing}
    return {"state": "standalone", "referencing": []}


def hold_attempt_scope(number, reason):
    """Durably hold one attempt before a child or sibling resource operation."""
    opened = open_attempt_record(number)
    if opened["state"] != "present":
        raise RecoveryIncomplete(
            "parent-attempt-%s:%s" % (opened["state"], opened.get("detail")))
    return _cleanup_unknown(
        number, reason,
        final_stage_check="not-attempted-parent-scope-held")


def hold_attempt_numbers(numbers, reason):
    held = []
    failures = []
    for number in sorted(set(numbers)):
        try:
            hold_attempt_scope(number, reason)
            held.append(number)
        except SystemExit:
            raise
        except BaseException as error:  # noqa: BLE001 - unconfirmed hold
            failures.append({"attempt": number,
                             "error": type(error).__name__,
                             "detail": str(error)[:160]})
    return held, failures


def _blocked_association_ids(assessment):
    """Ids that are known but must never be rewritten by this recovery pass."""
    blocked = set()
    for item in assessment.get("damaged") or []:
        prepare_id = item.get("prepareId")
        if _is_prepare_id(prepare_id):
            blocked.add(prepare_id)
    for item in assessment.get("unreadable") or []:
        prepare_id = item.get("prepareId")
        if _is_prepare_id(prepare_id):
            blocked.add(prepare_id)
    for detail in assessment.get("contradictions") or []:
        for token in re.findall(r"[a-f0-9]{32}", str(detail)):
            blocked.add(token)
    return blocked


def hold_association_candidates(assessment, reason, exclude=None):
    """Hold only individually validated, writable known children.

    Known listed/intent ids are re-read and independently validated, so a
    directory-enumeration failure cannot skip a readable child.  Contradictory
    or damaged objects are blocked before any write.
    """
    excluded = set(exclude or [])
    blocked = _blocked_association_ids(assessment)
    known = set(assessment.get("candidates") or {})
    known.update(assessment.get("listed") or [])
    for item in assessment.get("intents") or []:
        prepare_id = item.get("prepareId")
        if _is_prepare_id(prepare_id):
            known.add(prepare_id)
    outcomes = {}
    confirmed = True
    for prepare_id in sorted(known):
        if prepare_id in excluded:
            continue
        if prepare_id in blocked:
            confirmed = False
            outcomes[prepare_id] = {
                "held": False,
                "state": "blocked",
                "detail": "contradictory-or-damaged-record",
            }
            continue
        result = _hold_plan(prepare_id, reason)
        outcomes[prepare_id] = result
        if result.get("held") is not True:
            confirmed = False
    for item in assessment.get("damaged") or []:
        confirmed = False
        prepare_id = item.get("prepareId")
        if type(prepare_id) is str:
            outcomes.setdefault(prepare_id, {
                "held": False,
                "state": "invalid",
                "detail": "record-fields",
                "recordState": "invalid",
                "recordIssues": list(item.get("issues") or []),
            })
    for item in assessment.get("unreadable") or []:
        confirmed = False
        prepare_id = item.get("prepareId")
        if type(prepare_id) is str:
            outcomes.setdefault(prepare_id, {
                "held": False,
                "state": item.get("state"),
                "detail": "unreadable-discovery",
            })
    return confirmed, outcomes


def _plan_relationship_reason(plan, prepare_id, number):
    """Validate only the relationship fields used for association discovery."""
    if type(plan) is not dict:
        return "shape"
    if plan.get("prepareId") != prepare_id:
        return "prepareId"
    info = lifecycle_role(plan)
    if info is None or info["kind"] not in {"bind", "compile"}:
        return "role"
    if info["kind"] == "compile" and info["number"] != number:
        return "attempt"
    parent = plan.get("parentAttempt")
    if parent is not None and (type(parent) is not int or parent != number):
        return "parentAttempt"
    return None


def scan_association_candidates(number, record):
    """Explicitly enumerate every potentially relevant preparation plan.

    The returned ``directory`` proves whether enumeration completed.  A
    PermissionError, IO error or partial iteration is never converted into an
    empty list; entries read before the failure are retained so their readable
    known children can still be held.  Links, non-directories and ownership
    contradictions are blocked before any destructive call.
    """
    listed_rows, listed_issues = _valid_associated_prepare_ids(
        record.get("associatedPrepareIds"))
    intents, intent_issues = _valid_association_intents(
        record.get("associationIntents"))
    listed = set(listed_rows)
    intent_ids = {item.get("prepareId") for item in intents}
    target_id = record.get("prepareId")
    directory = _explicit_directory_entries(plans_dir())
    present = {}
    damaged = []
    unreadable = []
    contradictions = []
    relationship_issues = list(listed_issues) + list(intent_issues)
    scanned = 0
    if directory["state"] == "contradiction":
        contradictions.append(
            "association-directory:" + str(directory.get("detail")))
    elif directory["state"] in {"present", "unknown"}:
        for name in directory["entries"]:
            if name.endswith(".identity.json"):
                continue
            prepare_id = name[:-5] if name.endswith(".json") else ""
            if not PREPARE_ID_RE.fullmatch(prepare_id):
                continue
            scanned += 1
            state, raw = _plan_file_state(plans_dir() / name)
            if state in {"unreadable", "invalid"}:
                # The target plan itself is classified by the target read; every
                # other tool-owned plan file is potentially relevant.
                if prepare_id != target_id:
                    unreadable.append({"prepareId": prepare_id, "state": state})
                continue
            if state == "missing":
                continue
            relevant, contradiction = _raw_plan_relevant(
                raw, prepare_id, number, listed, intent_ids, target_id)
            if contradiction:
                contradictions.append(contradiction)
                continue
            if not relevant:
                continue
            opened = open_lifecycle_plan(prepare_id)
            if opened["state"] == "contradiction":
                contradictions.append(
                    "prepare-plan-identity:" + prepare_id + ":"
                    + str(opened.get("detail")))
                continue
            if opened["state"] == "invalid":
                relationship_reason = _plan_relationship_reason(
                    raw, prepare_id, number)
                if relationship_reason:
                    unreadable.append({
                        "prepareId": prepare_id,
                        "state": "invalid",
                        "detail": "relationship:" + relationship_reason,
                    })
                else:
                    classification = opened.get("classification") \
                        or classify_lifecycle_plan(raw)
                    damaged.append({
                        "prepareId": prepare_id,
                        "state": "invalid",
                        "issues": classification["recordIssues"],
                    })
                continue
            if opened["state"] != "present":
                unreadable.append({"prepareId": prepare_id,
                                   "state": opened["state"]})
                continue
            plan = opened["plan"]
            info = lifecycle_role(plan)
            if info is None or info["kind"] not in {"bind", "compile"}:
                contradictions.append("associated-role:" + prepare_id)
                continue
            if info["kind"] == "compile" and info["number"] != number:
                contradictions.append("associated-attempt:" + prepare_id)
                continue
            parent = plan.get("parentAttempt")
            if parent is not None and parent != number:
                contradictions.append("associated-parent:" + prepare_id)
                continue
            present[prepare_id] = plan
    incomplete = []
    for item in intents:
        prepare_id = item.get("prepareId")
        if item.get("state") != "complete":
            incomplete.append("pending-intent:" + prepare_id)
        elif prepare_id not in listed:
            incomplete.append("intent-not-in-parent-list:" + prepare_id)
        elif prepare_id not in present:
            incomplete.append("intent-child-unavailable:" + prepare_id)
        elif present[prepare_id].get("parentAttempt") != number:
            incomplete.append("intent-child-link-missing:" + prepare_id)
    for prepare_id in sorted(listed):
        if prepare_id not in present:
            incomplete.append("parent-list-child-unavailable:" + prepare_id)
        elif present[prepare_id].get("parentAttempt") is None:
            incomplete.append("parent-list-child-unlinked:" + prepare_id)
    for item in damaged:
        incomplete.append("damaged-child-unavailable:" + item["prepareId"])
    if directory["state"] == "unknown":
        incomplete.append("association-directory-unknown")
    # Reverse-only (parentAttempt) and standalone compile-N plans are already
    # in ``present``; neither is required to have a parent-list entry.
    if directory["state"] == "contradiction":
        reason = "association-directory-unsafe"
    elif directory["state"] == "unknown":
        reason = "association-directory-unknown"
    elif relationship_issues:
        reason = "association-record-invalid"
    elif unreadable:
        reason = "association-plan-unreadable"
    elif damaged:
        reason = "association-child-record-invalid"
    elif incomplete:
        reason = "association-incomplete"
    else:
        reason = None
    return {
        "listed": sorted(listed),
        "intents": intents,
        "pending": [item for item in intents if item.get("state") != "complete"],
        "candidates": present,
        "damaged": damaged,
        "unreadable": unreadable,
        "contradictions": contradictions,
        "incomplete": incomplete,
        "relationshipIssues": relationship_issues,
        "scanned": scanned,
        "directory": directory,
        "reason": reason,
    }


def _durable_update_plan(prepare_id, **fields):
    update_lifecycle_plan(prepare_id, **fields)
    plan, _ = read_json(lifecycle_plan_path(prepare_id))
    for key, value in fields.items():
        if plan.get(key) != value:
            raise RuntimeError("plan-journal-unconfirmed:" + key)
    return plan


def associate_preparation(number, prepare_id):
    """Link one original preparation using the three-write association order.

    1. parent association INTENT + child ID (and parent held);
    2. child ``parentAttempt``;
    3. parent association-complete (list + completed intent) last.

    Any interrupted write leaves a pending intent or a missing link and the
    parent reservation held.  A child may not create resources until the
    completion write is read back.
    """
    plan, _path = read_lifecycle_plan(prepare_id)
    info = lifecycle_role(plan)
    if info is None or info["kind"] not in {"bind", "compile"}:
        die(78, "associated-role")
    if info["kind"] == "compile" and info["number"] != number:
        die(78, "associated-attempt")
    parent = plan.get("parentAttempt")
    if parent is not None and parent != number:
        die(78, "associated-parent")
    record, _ = read_json(attempt_path(number))
    intents = association_intents(record)
    listed = associated_prepare_ids(record)
    for item in intents:
        item_id = item.get("prepareId")
        if item_id == prepare_id:
            if item.get("state") == "complete" and prepare_id in listed \
                    and parent == number:
                return record
            # A pending or incomplete existing intent is an interrupted
            # association: hold for recovery, never auto-complete it here.
            raise RecoveryIncomplete("association-incomplete")
        if item.get("state") != "complete" or item_id not in listed:
            raise RecoveryIncomplete("association-incomplete")
    for item_id in listed:
        if item_id == prepare_id:
            continue
        opened = open_lifecycle_plan(item_id)
        if opened["state"] == "contradiction":
            die(78, "associated-identity:" + str(opened.get("detail")))
        if opened["state"] != "present":
            raise RecoveryIncomplete("association-plan-unreadable")
        if opened["plan"].get("parentAttempt") != number:
            raise RecoveryIncomplete("association-incomplete")
    if prepare_id in listed and parent != number:
        raise RecoveryIncomplete("association-incomplete")
    if not any(item.get("prepareId") == prepare_id for item in intents):
        intents.append({
            "protocol": ASSOCIATION_INTENT_PROTOCOL,
            "attempt": number,
            "prepareId": prepare_id,
            "state": "pending",
            "startedAt": now(),
        })
    # 1. Parent intent + child ID first.  The parent is held from this write.
    durable_update_attempt(
        number,
        associationIntents=intents,
        reservationHeld=True,
        settled=False,
    )
    # 2. Child parentAttempt second.
    if parent != number:
        _durable_update_plan(
            prepare_id,
            parentAttempt=number,
            associationState="pending",
            associatedAt=now(),
        )
    # 3. Parent association-complete last: list and completed intent together.
    record, _ = read_json(attempt_path(number))
    intents = association_intents(record)
    listed = associated_prepare_ids(record)
    if prepare_id not in listed:
        listed = sorted(listed + [prepare_id])
    for item in intents:
        if item.get("prepareId") == prepare_id:
            item["state"] = "complete"
            item["completedAt"] = now()
    durable_update_attempt(
        number,
        associatedPrepareIds=listed,
        associationIntents=intents,
        associationCompleteAt=now(),
    )
    return require_association_complete(number, prepare_id)


def associate_existing_preparations(number):
    """Link valid standalone compile/bind plans for this attempt before use.

    A pending intent, an unreadable/malformed potentially relevant plan, or an
    identity contradiction blocks creation instead of being skipped.
    """
    record, _ = read_json(attempt_path(number))
    intents = association_intents(record)
    listed = set(associated_prepare_ids(record))
    for item in intents:
        if item.get("state") != "complete" or item.get("prepareId") not in listed:
            raise RecoveryIncomplete("association-incomplete")
    for item_id in sorted(listed):
        opened = open_lifecycle_plan(item_id)
        if opened["state"] == "contradiction":
            die(78, "associated-identity:" + str(opened.get("detail")))
        if opened["state"] != "present":
            raise RecoveryIncomplete("association-plan-unreadable")
        if opened["plan"].get("parentAttempt") != number:
            raise RecoveryIncomplete("association-incomplete")
    directory = _explicit_directory_entries(plans_dir())
    if directory["state"] == "absent":
        return []
    if directory["state"] == "contradiction":
        die(78, "association-directory-" + str(directory.get("detail")))
    if directory["state"] == "unknown":
        raise RecoveryIncomplete(
            "association-directory-unknown:" + str(directory.get("detail")))
    intent_ids = {item.get("prepareId") for item in intents}
    target_id = record.get("prepareId")
    linked = []
    for name in directory["entries"]:
        if name.endswith(".identity.json"):
            continue
        prepare_id = name[:-5] if name.endswith(".json") else ""
        if not PREPARE_ID_RE.fullmatch(prepare_id):
            continue
        state, raw = _plan_file_state(plans_dir() / name)
        if state in {"unreadable", "invalid"}:
            raise RecoveryIncomplete("association-plan-unreadable")
        if state == "missing":
            continue
        relevant, contradiction = _raw_plan_relevant(
            raw, prepare_id, number, listed, intent_ids, target_id)
        if contradiction:
            die(78, contradiction)
        if not relevant:
            continue
        plan, _path = read_lifecycle_plan(prepare_id)
        info = lifecycle_role(plan)
        if info is None or info["kind"] not in {"bind", "compile"}:
            die(78, "associated-role")
        if info["kind"] == "compile" and info["number"] != number:
            die(78, "associated-attempt")
        parent = plan.get("parentAttempt")
        if parent is not None and parent != number:
            die(78, "associated-parent")
        associate_preparation(number, prepare_id)
        linked = sorted(set(linked + [prepare_id]))
    return linked


def _remove_own_by_name_tag(name, tag):
    """Remove only a container that carries our exact name and tag."""
    lookup = guard.container_lookup(name)
    if lookup["state"] != "present":
        return {"removed": False, "state": lookup["state"]}
    observed = guard.parse_container(lookup["container"])
    if observed is None or observed.get("name") != name or observed.get("labels", {}).get("sce.tag") != tag:
        return {"removed": False, "state": "identity-mismatch"}
    return guard.remove_container_verified({
        "containerId": observed["id"], "containerName": name,
        "tag": tag, "containerCreated": True,
    })


def reserve_attempt(plan, plan_sha, number, admission, challenge=None):
    """Reserve one attempt slot under the exclusive batch lock."""
    handle = acquire_batch_lock()
    del handle  # held for the process lifetime
    if attempt_path(number).is_file():
        die(79, "attempt-already-reserved")
    counter = load_counter()
    if number in counter["used"] or len(counter["used"]) >= LIMITS["maxAttempts"]:
        die(79, "attempt-budget")
    # A new task may not start while a known record is damaged or unreadable.
    # Reading and classifying the whole known scope happens before the counter
    # write, so a refused reservation consumes nothing.
    known_problems = _known_scope_problems()
    if known_problems:
        die(3, "known-record-state:" + ";".join(known_problems[:6]))
    item = next(entry for entry in plan["attempts"] if entry["attempt"] == number)
    if challenge is None:
        challenge = os.urandom(16).hex()
    if not CHALLENGE_RE.fullmatch(challenge):
        die(79, "challenge")
    counter["used"] = sorted(counter["used"] + [number])
    # Count first: a crash between the two writes consumes the slot.
    write_json_document(counter_path(), counter)
    record = {
        "version": 1,
        "attempt": number,
        "classId": item["classId"],
        "fixture": item["fixture"],
        "sourceSha256": item["sourceSha256"],
        "expected": item.get("expected"),
        "argvBase": item.get("argvBase"),
        "probeIndex": item.get("probeIndex"),
        "probePrefix": item.get("probePrefix"),
        "probeSuffix": item.get("probeSuffix"),
        "challenge": challenge,
        "challengeSha256": sha_bytes(challenge.encode("ascii")),
        "planSha256": plan_sha,
        "state": "reserved",
        "reservedAt": now(),
        "budget": {
            "maxAttempts": LIMITS["maxAttempts"],
            "usedAfterReserve": len(counter["used"]),
            "admissionBudget": len(admission.get("allowedAttempts") or []),
        },
        "targetExecutions": 0,
        "executionState": "not-started",
        "goState": "not-attempted",
        "targetExit": None,
        "targetPid": None,
        "targetUid": int(TARGET_UID),
        "targetOutputDiagnosticOnly": True,
        **observation_identity_fields(preflight_context()),
        "prepareId": None,
        "resourcePlanPath": None,
        "bindingId": None,
        "pointId": None,
        "bindingSha256": None,
        "expectedSha256": None,
        "observationSha256": None,
        "observationRawSha256": None,
        "observerSha256": None,
        "verificationSha256": None,
        "resourceIdentity": None,
        "resourceIntent": None,
        "stageIdentity": None,
        "associatedPrepareIds": [],
        "resourceProof": {
            "protocol": RESOURCE_PROOF_PROTOCOL,
            "phase": "reserved",
            "sequence": [{"phase": "reserved", "at": now()}],
            "notCreated": lifecycle_not_created_default(),
            "targetAttempt": number,
        },
        "processes": {
            "client": {"spawnState": "not-started"},
            "observer": {"spawnState": "not-started"},
        },
        "observerStop": None,
        "observerEnd": None,
        "observerStopped": False,
        "clientExited": False,
        "stageDir": None,
        "prepare": {},
        "cleanup": {"confirmed": False},
        "reservationHeld": True,
        "settled": False,
        "checkpoints": [{"step": "reserved", "at": now()}],
    }
    write_json_document(attempt_path(number), record)
    return record


# --------------------------------------------------------------------- docker
def verify_mounts(container, expected):
    """Every declared bind mount must be present, read-only and exact."""
    observed = {}
    for entry in container.get("mounts") or []:
        if type(entry) is not dict:
            return "mount-shape"
        if entry.get("Type") == "tmpfs" or entry.get("Destination") == "/tmp":
            continue
        destination = entry.get("Destination")
        if not destination:
            return "mount-destination"
        if entry.get("Type") != "bind":
            return "mount-type:" + str(destination)
        if entry.get("RW") is not False:
            return "mount-writable:" + destination
        observed[destination] = entry.get("Source")
    expected_by_destination = {destination: source for source, destination in expected.items()}
    if set(observed) != set(expected_by_destination):
        return "mount-set"
    for destination, source in expected_by_destination.items():
        if observed[destination] != str(source):
            return "mount-source:" + destination
    return None


def verify_container_config(container):
    """Review the container configuration before any GO can be written."""
    if container is None:
        return "inspect-shape"
    if container.get("image") != IMAGE:
        return "container-image"
    if container.get("user") != "%s:%s" % (TARGET_UID, TARGET_GID):
        return "container-user"
    entrypoint = container.get("entrypoint")
    if entrypoint != [INTERPRETER]:
        return "container-entrypoint"
    host = container.get("hostConfig") or {}
    if host.get("NetworkMode") != "none":
        return "container-network"
    if host.get("ReadonlyRootfs") is not True:
        return "container-readonly"
    if "ALL" not in (host.get("CapDrop") or []):
        return "container-caps"
    security = host.get("SecurityOpt") or []
    if not any(str(item).startswith("no-new-privileges") for item in security):
        return "container-privileges"
    memory = host.get("Memory")
    if memory != LIMITS["memoryMiB"] * 1024 * 1024:
        return "container-memory"
    if host.get("PidsLimit") != LIMITS["pids"]:
        return "container-pids"
    tmpfs = host.get("Tmpfs") or {}
    tmp = str(tmpfs.get("/tmp", ""))
    if "size=%dm" % LIMITS["tmpMiB"] not in tmp or "nosuid" not in tmp or "nodev" not in tmp:
        return "container-tmpfs"
    return None


def create_container(name, tag, role, command, mounts, attempt=None):
    """Create with an explicit entrypoint and interactive stdin; never remove."""
    lookup = guard.container_lookup(name)
    if lookup["state"] == "present":
        die(79, "container-name-conflict")
    if lookup["state"] != "absent":
        die(79, "container-name-query")
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
        "--label", "sce.role=" + role,
    ]
    if attempt is not None:
        args.extend(["--label", "sce.attempt=%04d" % attempt])
    for source, destination in sorted(mounts.items()):
        args.extend(["--mount", "type=bind,src=%s,dst=%s,readonly" % (source, destination)])
    for key, value in ALLOWED_ENV.items():
        args.extend(["--env", "%s=%s" % (key, value)])
    args.extend(["--entrypoint", INTERPRETER, IMAGE])
    args.extend(command)
    result = guard.docker(*args)
    if result.returncode != 0:
        lookup = guard.container_lookup(name)
        if lookup["state"] == "present":
            die(79, "container-name-conflict")
        die(79, "container-create:" + (result.stderr or "")[-200:])
    lookup = guard.container_lookup(name)
    if lookup["state"] != "present":
        die(79, "container-create-unconfirmed")
    container = guard.parse_container(lookup["container"])
    if container is None or not container.get("id"):
        die(79, "container-id-missing")
    try:
        reason = guard.container_identity_matches(container, container["id"], name, tag)
        if reason:
            die(79, "container-identity:" + reason)
        reason = verify_container_config(container)
        if reason:
            die(79, reason)
        reason = verify_mounts(container, mounts)
        if reason:
            die(79, reason)
    except BaseException:
        _remove_own_by_name_tag(name, tag)
        raise
    return container


def start_attached(identifier):
    return subprocess.Popen(
        ["docker", "start", "-a", "-i", identifier],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def start_observer(observer_path):
    return subprocess.Popen(
        ["bpftrace", "-q", str(observer_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def verify_config_inside(identifier, expected_sha):
    result = guard.docker("exec", identifier, "/usr/bin/sha256sum", "/review/config/run.json", timeout=60)
    if result.returncode != 0:
        return "config-exec:" + (result.stderr or "").strip()[:120]
    fields = result.stdout.split()
    if not fields or fields[0] != expected_sha:
        return "config-digest"
    return None


def render_observer(record, target_pid):
    """Render from the frozen template and the verified preflight layout bytes."""
    preflight_result = preflight_context()
    inputs = verify_prepare_inputs(preflight_result)
    bind, _ = read_json(PREPARE / "bind" / "bind.json")
    result = next(
        entry for entry in bind["results"] if entry["classId"] == record["classId"]
    )
    if result.get("derivation", {}).get("layoutSha256") != inputs["layoutSha256"]:
        die(79, "binding-layout-digest")
    if result.get("derivation", {}).get("layoutStructureSha256") != inputs["layoutStructureSha256"]:
        die(79, "binding-layout-structure")
    try:
        return observer_render.render(
            inputs["templateBytes"],
            inputs["layout"],
            inputs["layoutSha256"],
            inputs["profileSha256"],
            "attempt-%04d" % record["attempt"],
            record["challenge"][:12],
            "/review/runroot/" + result["stagedPath"],
            result["callOffset"],
            target_pid,
            int(TARGET_UID),
            "stdlib-cli-v2-experiment",
        )
    except observer_render.RenderError as error:
        die(79, "observer-render:" + str(error))


# ---------------------------------------------------------------------- stage
def _safe_mkdir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        info = os.lstat(current)
        if os.path.islink(str(current)) or not os.path.isdir(str(current)):
            die(79, "stage-parent-not-directory")
    return path


def stage_run_inputs(stage, config_path, closure_sources):
    """Stage read-only input trees under an identity-checked directory."""
    stage = Path(stage)
    if os.path.lexists(stage):
        die(79, "stage-exists")
    _safe_mkdir(stage)
    runroot = stage / "runroot"
    config = stage / "config"
    tools = stage / "tools"
    for directory in (runroot, config, tools):
        directory.mkdir(parents=True, mode=0o755)
    resolved = {}
    for relative, source in closure_sources.items():
        payload = (ROOT / source).read_bytes()
        target = runroot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        resolved[relative] = sha_bytes(payload)
    config_payload = Path(config_path).read_bytes()
    (config / "run.json").write_bytes(config_payload)
    (tools / "target_launcher.py").write_bytes((TOOLS / "target_launcher.py").read_bytes())
    for path in list(runroot.rglob("*")) + list(config.rglob("*")) + list(tools.rglob("*")):
        if path.is_file():
            path.chmod(0o444)
        else:
            path.chmod(0o555)
    for directory in (runroot, config, tools):
        directory.chmod(0o555)
    stage.chmod(0o555)
    identity = guard.stage_identity(stage)
    if identity is None or identity.get("error"):
        die(79, "stage-identity")
    return {
        "stageDir": str(stage),
        "stageIdentity": identity,
        "mounts": {
            str(runroot): "/review/runroot",
            str(config): "/review/config",
            str(tools): "/review/tools",
        },
        "configSha256": sha_bytes(config_payload),
        "launcherSha256": sha_file(tools / "target_launcher.py"),
        "closure": resolved,
    }


def cleanup_stage(stage_dir, identity):
    return guard.cleanup_stage(stage_dir, identity)


# --------------------------------------------------------- lifecycle journals
def plans_dir():
    return Path(PREPARE) / "plans"


def lifecycle_plan_path(prepare_id):
    if type(prepare_id) is not str or not PREPARE_ID_RE.fullmatch(prepare_id):
        die(78, "prepare-id")
    return plans_dir() / (prepare_id + ".json")


def lifecycle_identity_path(prepare_id):
    return plans_dir() / (prepare_id + ".identity.json")


def lifecycle_identity_state(prepare_id, plan=None):
    """Read and bind the optional identity journal before any resource call.

    Returns ``(state, detail)`` where state is ``absent``, ``present``,
    ``unreadable``, ``invalid`` or ``contradiction``.  Missing is normal; a
    damaged or contradictory existing journal is never ignored.
    """
    path = lifecycle_identity_path(prepare_id)
    state = guard.path_state(path)
    if state["state"] == "absent":
        return "absent", None
    if state["state"] == "unknown":
        return "unreadable", state.get("detail")
    if state.get("symlink") or not state.get("isFile"):
        return "contradiction", "identity-path"
    try:
        value, _ = read_json(path)
    except (OSError, ValueError, UnicodeDecodeError):
        return "unreadable", "identity-json"
    if type(value) is not dict:
        return "invalid", "identity-shape"
    if value.get("prepareId") != prepare_id:
        return "contradiction", "identity-prepareId"
    if plan is not None:
        for field in ("containerName", "tag"):
            if value.get(field) is not None and value.get(field) != plan.get(field):
                return "contradiction", "identity-" + field
        identifier = value.get("containerId")
        if identifier is not None:
            if plan.get("containerId") is not None \
                    and identifier != plan.get("containerId"):
                return "contradiction", "identity-containerId"
            if plan.get("containerId") is None \
                    and plan.get("containerState") == "not-created":
                return "contradiction", "identity-containerId"
        if value.get("image") is not None \
                and value.get("image") not in (plan.get("image"), plan.get("imageId")):
            return "contradiction", "identity-image"
    return "present", value


def plan_with_identity_journal(plan, identity):
    """Use a durable post-create identity journal when the plan lost the id."""
    if type(identity) is not dict:
        return plan
    identifier = identity.get("containerId")
    if identifier is None or plan.get("containerId") is not None:
        return plan
    if plan.get("containerState") not in {"create-attempted", "create-unknown"}:
        return plan
    merged = dict(plan)
    merged.update({
        "containerId": identifier,
        "containerState": "created",
        "identityJournal": "used",
    })
    reason = plan_identity_reason(merged)
    if reason:
        die(78, "prepare-plan-identity-journal:" + reason)
    return merged


def write_lifecycle_plan(role, stage_dir, tag, name, attempt=None, mounts=None,
                         process_roles=("client",)):
    """Persist and fsync the resource plan before any stage/config/container."""
    prepare_id = os.urandom(16).hex()
    processes = {process_role: {"spawnState": "not-started"} for process_role in process_roles}
    plan = {
        "version": 3,
        "protocolRevision": PROTOCOL_REVISION,
        "kind": "resource-lifecycle-plan",
        "prepareId": prepare_id,
        "operationRole": role,
        "role": role,
        "attempt": attempt,
        "state": "planned",
        "stageDir": str(stage_dir),
        "stageState": "not-created",
        "stageIdentity": None,
        "tag": tag,
        "containerName": name,
        "imageId": IMAGE,
        "image": IMAGE,
        "mounts": [{"source": source, "destination": destination, "readonly": True}
                   for source, destination in sorted((mounts or {}).items())],
        "processes": processes,
        "containerState": "not-created",
        "containerId": None,
        "reservationHeld": True,
        "createdAt": now(),
    }
    guard.write_new_json_document(lifecycle_plan_path(prepare_id), plan)
    return prepare_id, plan


def open_lifecycle_plan(prepare_id):
    """Classify a plan read without performing any resource operation.

    ``present`` is the only state that carries a validated plan.  Missing,
    unreadable, malformed and non-regular inputs are unknown/incomplete;
    selector, filename and identity contradictions are blocked.
    """
    path = lifecycle_plan_path(prepare_id)
    state = guard.path_state(path)
    if state["state"] == "absent":
        return {"state": "missing", "detail": "file-not-found", "path": path}
    if state["state"] == "unknown":
        return {"state": "unreadable", "detail": state.get("detail"),
                "path": path}
    if state.get("symlink") or not state.get("isFile"):
        return {"state": "invalid", "detail": "not-regular-file", "path": path}
    try:
        plan, _ = read_json(path)
    except PermissionError:
        return {"state": "unreadable", "detail": "permission-denied",
                "path": path}
    except (OSError, ValueError, UnicodeDecodeError):
        return {"state": "invalid", "detail": "json-or-io", "path": path}
    if type(plan) is not dict:
        return {"state": "invalid", "detail": "shape", "path": path}
    if plan.get("prepareId") != prepare_id:
        return {"state": "contradiction", "detail": "selector-mismatch",
                "plan": plan, "path": path}
    reason = plan_identity_reason(plan)
    if reason:
        return {"state": "contradiction", "detail": "identity:" + reason,
                "plan": plan, "path": path}
    classification = classify_lifecycle_plan(plan)
    if classification["recordState"] == "invalid":
        return {
            "state": "invalid",
            "detail": "record-fields",
            "plan": plan,
            "classification": classification,
            "path": path,
        }
    return {"state": "present", "plan": plan, "path": path,
            "classification": classification}


def read_lifecycle_plan(prepare_id):
    """Read exactly ``prepare_id`` for non-recovering callers.

    Recovery uses :func:`open_lifecycle_plan` and classifies read failures as
    incomplete.  Query/status keep the historical 79 diagnostics.
    """
    opened = open_lifecycle_plan(prepare_id)
    if opened["state"] == "present":
        return opened["plan"], opened["path"]
    if opened["state"] == "contradiction":
        if opened.get("detail") == "selector-mismatch":
            die(78, "prepare-plan-selector-mismatch")
        die(78, "prepare-plan-identity:" + str(opened.get("detail")))
    if opened["state"] == "invalid":
        die(79, "prepare-plan-invalid")
    die(79, "prepare-plan-missing")


def plan_identity_reason(plan):
    """Validate every field used before a signal, deletion or settlement."""
    if type(plan) is not dict:
        return "shape"
    if plan.get("version") != 3 or plan.get("kind") != "resource-lifecycle-plan":
        return "kind"
    if plan.get("protocolRevision") != PROTOCOL_REVISION:
        return "protocol-revision"
    prepare_id = plan.get("prepareId")
    if type(prepare_id) is not str or not PREPARE_ID_RE.fullmatch(prepare_id):
        return "prepare-id"
    info = lifecycle_role(plan)
    if info is None:
        return "role"
    tag = plan.get("tag")
    if type(tag) is not str or not TAG_RE.fullmatch(tag):
        return "tag"
    if info["kind"] in {"bind", "compile"} and tag[:8] != info["suffix"]:
        return "role-tag"
    if info["kind"] == "bind":
        if plan.get("attempt") is not None:
            return "attempt"
    elif plan.get("attempt") != info["number"]:
        return "attempt"
    name = plan.get("containerName")
    if type(name) is not str or name != container_name(info["role"], tag):
        return "container-name"
    if plan.get("imageId") != IMAGE or plan.get("image") not in (None, IMAGE):
        return "image"
    stage_reason = lifecycle_stage_reason(plan, info)
    if stage_reason:
        return stage_reason
    if plan.get("stageState") not in {"not-created", "created", "unknown"}:
        return "stage-state"
    identity = plan.get("stageIdentity")
    if plan.get("stageState") == "created" and identity is not None:
        if type(identity) is not dict or identity.get("error") \
                or "dev" not in identity or "ino" not in identity:
            return "stage-identity"
    if plan.get("stageState") == "not-created" and identity is not None:
        if type(identity) is not dict or identity.get("error") \
                or "dev" not in identity or "ino" not in identity:
            return "stage-identity"
    if plan.get("containerState") not in {
            "not-created", "create-attempted", "created", "create-unknown",
            "create-failed-cleaned"}:
        return "container-state"
    if plan.get("containerState") == "created":
        identifier = plan.get("containerId")
        if type(identifier) is not str or not re.fullmatch(r"[a-f0-9]{64}", identifier):
            return "container-id"
    processes = plan.get("processes")
    if type(processes) is not dict:
        return "processes"
    for process_role, record in processes.items():
        if type(process_role) is not str or type(record) is not dict:
            return "process-record"
        if record.get("spawnState") not in {
                "not-started", "spawn-attempted", "started", "unknown"}:
            return "spawn-state"
    proof = plan.get("resourceProof")
    if proof is not None:
        if type(proof) is not dict or proof.get("protocol") != RESOURCE_PROOF_PROTOCOL:
            return "resource-proof"
        if proof.get("phase") not in RESOURCE_PHASES:
            return "resource-proof-phase"
    return None


def update_lifecycle_plan(prepare_id, **fields):
    plan, path = read_lifecycle_plan(prepare_id)
    current = classify_lifecycle_plan(plan)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecordValidationError(
            "prepare-plan-invalid:" + ",".join(current["recordIssues"][:4]))
    if "prepareId" in fields and fields["prepareId"] != prepare_id:
        die(78, "prepare-plan-id-immutable")
    for field in ("role", "operationRole"):
        if field in fields and fields[field] != plan.get(field):
            die(78, "prepare-plan-role-immutable")
    candidate = dict(plan)
    candidate.update(fields)
    reason = plan_identity_reason(candidate)
    if reason:
        die(78, "prepare-plan-update-identity:" + reason)
    fresh = classify_lifecycle_plan(candidate)
    if fresh["recordState"] == "invalid":
        raise RecordValidationError(
            "prepare-plan-update-invalid:" + ",".join(fresh["recordIssues"][:4]))
    write_json_document(path, candidate)
    return candidate


def mark_lifecycle_unknown(prepare_id, reason, **fields):
    """Best effort only: the caller must still treat the result as unknown."""
    try:
        return update_lifecycle_plan(
            prepare_id, state="unknown", unknownReason=reason, **fields
        )
    except BaseException:  # noqa: BLE001 - an unpersisted unknown is still unknown
        return None


def _cleanup_receipt_key(value):
    if type(value) is not dict:
        return None
    return (value.get("state"), value.get("checkedAt"))


def _append_cleanup_receipt(receipts, cleanup):
    """Append one completed historical cleanup receipt, never a checking one.

    A malformed existing history or a malformed completed outcome raises before
    the caller can write.  There is deliberately no list/string coercion.
    """
    issues = []
    _validate_cleanup_receipts(receipts, "cleanupReceipts", issues)
    if issues:
        raise RecordValidationError(
            "cleanup-history-invalid:" + ",".join(issues[:4]))
    rows = [] if receipts is None else list(receipts)
    if cleanup is None:
        return rows[-32:]
    if type(cleanup) is not dict:
        raise RecordValidationError("cleanup-outcome-not-object")
    _validate_cleanup(cleanup, "cleanup", issues)
    if issues:
        raise RecordValidationError(
            "cleanup-outcome-invalid:" + ",".join(issues[:4]))
    state = cleanup.get("state")
    if state not in CLEANUP_RECEIPT_STATES:
        return rows[-32:]
    if type(cleanup.get("confirmed")) is not bool \
            or type(cleanup.get("checkedAt")) is not str \
            or not cleanup.get("checkedAt"):
        raise RecordValidationError("cleanup-outcome-incomplete-receipt")
    key = _cleanup_receipt_key(cleanup)
    if key is not None and any(_cleanup_receipt_key(row) == key for row in rows):
        return rows[-32:]
    rows.append({
        "state": state,
        "confirmed": cleanup.get("confirmed"),
        "checkedAt": cleanup.get("checkedAt"),
        "resourceCreationPhase": cleanup.get("resourceCreationPhase"),
    })
    return rows[-32:]


def begin_attempt_cleanup_check(number):
    """Durably record a current cleanup check before any resource query.

    Historical ``resourceProof`` creation bytes are deliberately not touched.
    Only the current cleanup status, reservation hold and settlement flag move.
    """
    record, _ = read_json(attempt_path(number))
    if type(record) is not dict:
        raise RuntimeError("attempt-record-shape")
    current = classify_attempt_record(record)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecordValidationError(
            "attempt-record-invalid:" + ",".join(current["recordIssues"][:4]))
    receipts = _append_cleanup_receipt(
        record.get("cleanupReceipts"), record.get("cleanup"))
    previous = record.get("cleanupCheck") \
        if type(record.get("cleanupCheck")) is dict else {}
    started = now()
    started_count = previous.get("startedCount")
    if type(started_count) is not int:
        started_count = 0
    check = {
        "protocol": CLEANUP_CHECK_PROTOCOL,
        "state": "checking",
        "attempt": number,
        "startedAt": started,
        "startedCount": started_count + 1,
        "previousState": previous.get("state"),
    }
    cleanup = {
        "confirmed": False,
        "state": "checking",
        "checkedAt": started,
        "finalStageCheck": "not-attempted",
    }
    return durable_update_attempt(
        number,
        cleanup=cleanup,
        cleanupCheck=check,
        cleanupReceipts=receipts,
        reservationHeld=True,
        settled=False,
    )


def begin_plan_cleanup_check(prepare_id, plan):
    """Durably hold one preparation before its resources are queried."""
    current = classify_lifecycle_plan(plan)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecordValidationError(
            "prepare-plan-invalid:" + ",".join(current["recordIssues"][:4]))
    receipts = _append_cleanup_receipt(
        plan.get("cleanupReceipts"), plan.get("cleanup"))
    previous = plan.get("cleanupCheck") \
        if type(plan.get("cleanupCheck")) is dict else {}
    started = now()
    started_count = previous.get("startedCount")
    if type(started_count) is not int:
        started_count = 0
    check = {
        "protocol": CLEANUP_CHECK_PROTOCOL,
        "state": "checking",
        "prepareId": prepare_id,
        "startedAt": started,
        "startedCount": started_count + 1,
        "previousState": previous.get("state"),
    }
    cleanup = {
        "confirmed": False,
        "state": "checking",
        "checkedAt": started,
        "finalStageCheck": "not-attempted",
    }
    return _durable_update_plan(
        prepare_id,
        state="cleanup-checking",
        cleanup=cleanup,
        cleanupCheck=check,
        cleanupReceipts=receipts,
        reservationHeld=True,
    )


def finish_plan_cleanup(prepare_id, confirmed, outcome):
    """Final durable preparation cleanup status with an append-only receipt."""
    plan, _ = read_json(lifecycle_plan_path(prepare_id))
    current = classify_lifecycle_plan(plan)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecordValidationError(
            "prepare-plan-invalid:" + ",".join(current["recordIssues"][:4]))
    check = plan.get("cleanupCheck") if type(plan.get("cleanupCheck")) is dict else {}
    state = "confirmed" if confirmed else "incomplete"
    receipt_outcome = {
        **outcome,
        "state": state,
        "confirmed": confirmed,
        "checkedAt": outcome.get("checkedAt") or now(),
    }
    receipts = _append_cleanup_receipt(
        plan.get("cleanupReceipts"), receipt_outcome)
    check = {
        "protocol": CLEANUP_CHECK_PROTOCOL,
        "state": state,
        "prepareId": prepare_id,
        "startedAt": check.get("startedAt"),
        "startedCount": check.get("startedCount"),
        "finishedAt": now(),
        "resourceCreationPhase": plan.get("resourceProof", {}).get("phase")
        if isinstance(plan.get("resourceProof"), dict) else None,
    }
    return _durable_update_plan(
        prepare_id,
        state="cleanup-confirmed" if confirmed else "cleanup-unconfirmed",
        cleanup=receipt_outcome,
        cleanupCheck=check,
        cleanupReceipts=receipts,
        reservationHeld=not confirmed,
    )


def _hold_plan(prepare_id, reason, final_stage_check="not-attempted-parent-scope-held"):
    """Durably invalidate one preparation's current success without touching it.

    Historical creation proof and completed cleanup receipts are preserved.
    Missing, unreadable, malformed and contradictory files are never replaced
    with invented metadata; the caller receives an explicit unconfirmed state.
    """
    try:
        opened = open_lifecycle_plan(prepare_id)
        if opened["state"] == "contradiction":
            if opened.get("detail") == "selector-mismatch":
                die(78, "prepare-plan-selector-mismatch")
            die(78, "prepare-plan-identity:" + str(opened.get("detail")))
        if opened["state"] != "present":
            result = {"held": False, "state": opened["state"],
                      "detail": opened.get("detail")}
            classification = opened.get("classification")
            if classification is not None:
                result["recordState"] = classification["recordState"]
                result["recordIssues"] = list(classification["recordIssues"])
            return result
        plan = opened["plan"]
        current = classify_lifecycle_plan(plan)
        if current["recordState"] in {"invalid", "unreadable"}:
            return {"held": False, "state": "invalid",
                    "recordState": current["recordState"],
                    "recordIssues": list(current["recordIssues"]),
                    "detail": "record-fields"}
        receipts = _append_cleanup_receipt(
            plan.get("cleanupReceipts"), plan.get("cleanup"))
        check = plan.get("cleanupCheck") \
            if type(plan.get("cleanupCheck")) is dict else {}
        outcome = {
            "confirmed": False,
            "state": "incomplete",
            "reason": reason,
            "checkedAt": now(),
            "finalStageCheck": final_stage_check,
            "stage": {"removed": False, "state": final_stage_check},
        }
        _durable_update_plan(
            prepare_id,
            state="cleanup-unconfirmed",
            cleanup=outcome,
            cleanupCheck={
                "protocol": CLEANUP_CHECK_PROTOCOL,
                "state": "incomplete",
                "prepareId": prepare_id,
                "startedAt": check.get("startedAt"),
                "startedCount": check.get("startedCount"),
                "finishedAt": now(),
                "reason": reason,
            },
            cleanupReceipts=_append_cleanup_receipt(receipts, outcome),
            reservationHeld=True,
        )
        return {"held": True, "state": "held", "cleanup": outcome}
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 - caller maps to incomplete 3
        return {"held": False, "state": "unconfirmed",
                "detail": type(error).__name__ + ":" + str(error)[:160]}


def remove_plan_container(plan):
    """Remove a plan-owned container after a fresh, validated identity query."""
    name = plan.get("containerName")
    tag = plan.get("tag")
    identifier = plan.get("containerId")
    state = plan.get("containerState")
    created = state == "created" and isinstance(identifier, str)
    if created:
        return guard.remove_container_verified({
            "containerId": identifier,
            "containerName": name,
            "tag": tag,
            "containerCreated": True,
            "image": IMAGE,
        })
    # Ambiguous create: a random tag plus exact name is the ownership proof.
    by_name = guard.container_lookup(name)
    by_tag = guard.container_tag_lookup(tag)
    if by_name["state"] == "absent" and by_tag["state"] == "absent":
        return {"removed": True, "state": "never-created",
                "queries": {"name": by_name, "tag": by_tag}}
    if by_name["state"] != "present" or by_tag["state"] != "present":
        return {"removed": False, "state": "unknown",
                "detail": "ambiguous-create-query",
                "queries": {"name": by_name, "tag": by_tag}}
    observed = guard.parse_container(by_name["container"])
    if observed is None or observed.get("name") != name \
            or (observed.get("labels") or {}).get("sce.tag") != tag \
            or observed.get("image") != IMAGE:
        return {"removed": False, "state": "identity-mismatch",
                "queries": {"name": by_name, "tag": by_tag}}
    return guard.remove_container_verified({
        "containerId": observed["id"],
        "containerName": name,
        "tag": tag,
        "containerCreated": True,
        "image": IMAGE,
    })


def cleanup_lifecycle_plan(plan, prepare_id):
    """Final resource handling for one validated prepare/bind/compile plan."""
    if type(plan) is not dict or plan.get("prepareId") != prepare_id:
        die(78, "prepare-plan-selector-mismatch")
    reason = plan_identity_reason(plan)
    if reason:
        die(78, "prepare-plan-identity:" + reason)
    if lifecycle_role(plan) is None:
        die(78, "operation-role-unknown")
    identity_state, identity_detail = lifecycle_identity_state(prepare_id, plan)
    if identity_state == "contradiction":
        die(78, "prepare-plan-identity-journal:" + str(identity_detail))
    if identity_state in {"unreadable", "invalid"}:
        raise RuntimeError("prepare-plan-identity-journal:" + str(identity_detail))
    if identity_state == "present":
        plan = plan_with_identity_journal(plan, identity_detail)
    # The current check is durable and held before the first resource query.
    begin_plan_cleanup_check(prepare_id, plan)
    container = remove_plan_container(plan)
    processes = plan.get("processes") or {}
    if "client" in processes:
        client_state, client_stop = _query_process(_process_record(processes.get("client")), 3, 2)
    else:
        client_state = {"state": "exited", "proof": "not-applicable"}
        client_stop = {"stopped": True, "state": "exited", "proof": "not-applicable"}
    if "observer" in processes:
        observer_state, observer_stop = _query_process(_process_record(processes.get("observer")), 5, 2)
    else:
        observer_state = {"state": "exited", "proof": "not-applicable"}
        observer_stop = {"stopped": True, "state": "exited", "proof": "not-applicable"}
    resources_clear = (
        container.get("removed") is True
        and client_state.get("state") == "exited"
        and observer_state.get("state") == "exited"
    )
    # Clean a verified stage only after the resource proofs; the final lstat
    # still happens last, for every path including initially absent ones.
    if resources_clear:
        stage = cleanup_stage(plan.get("stageDir"), plan.get("stageIdentity"))
    else:
        final = guard.path_state(plan.get("stageDir")) if plan.get("stageDir") else {
            "state": "unknown"}
        stage = {"removed": False, "state": "retained-resources-unresolved",
                 "lstatAfter": final.get("state", "unknown")}
    confirmed = resources_clear and stage.get("removed") is True
    outcome = {
        "confirmed": confirmed,
        "state": "confirmed" if confirmed else "incomplete",
        "container": container,
        "clientState": client_state,
        "clientStop": client_stop,
        "observerState": observer_state,
        "observerStop": observer_stop,
        "stage": stage,
        "finalStageCheck": "after-resources",
        "resourceCreationPhase": (plan.get("resourceProof") or {}).get("phase")
        if isinstance(plan.get("resourceProof"), dict) else None,
        "checkedAt": now(),
    }
    # A failed durable final journal can never be a successful cleanup.
    finish_plan_cleanup(prepare_id, confirmed, outcome)
    return confirmed, outcome


def _last_json_line(stdout):
    lines = [line for line in stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty-output")
    return json.loads(lines[-1])


def run_tool_container(role, tag, command, mounts, stage_dir, stage_id, prepare_id):
    """Run one pure tool container with the same ownership protocol.

    The resource plan was written and fsynced by the caller *before* the stage
    existed.  This function records the stage identity, the create attempt and
    the process spawn state before each operation, and keeps the actual
    container identity in this outer frame before any identity journal write.
    """
    name = container_name(role, tag)
    client = None
    process_record = {"spawnState": "not-started"}
    container_record = None
    try:
        update_lifecycle_plan(prepare_id, stageState="created", stageIdentity=stage_id)
        update_lifecycle_plan(prepare_id, state="creating", containerState="create-attempted")
        try:
            container = create_container(name, tag, role, command, mounts)
        except BaseException:
            # A failed create is ambiguous until a fresh name/tag query proves
            # otherwise.  Never report the resource as not-started.
            mark_lifecycle_unknown(prepare_id, "create-failed",
                                   containerState="create-unknown")
            try:
                plan, _ = read_lifecycle_plan(prepare_id)
                cleanup_lifecycle_plan(plan, prepare_id)
            except BaseException:  # noqa: BLE001 - original failure is the cause
                pass
            raise
        identifier = container["id"]
        container_record = {
            "containerId": identifier,
            "containerName": name,
            "tag": tag,
            "containerCreated": True,
            "image": IMAGE,
        }
        # The actual identity is retained in this outer frame before the
        # identity journal is written.  A journal failure is unknown, not
        # absent, and cleanup still has ``container_record``.
        try:
            update_lifecycle_plan(prepare_id, containerState="created",
                                  containerId=identifier, lifecycle="created")
        except BaseException:
            try:
                guard.write_new_json_document(lifecycle_identity_path(prepare_id), {
                    **container_record, "prepareId": prepare_id,
                    "identityJournal": "failed-after-create",
                    "createdAt": now(),
                })
            except BaseException:  # noqa: BLE001
                pass
            raise
        update_lifecycle_plan(prepare_id, processes={"client": {"spawnState": "spawn-attempted"}})
        try:
            client = start_attached(identifier)
        except BaseException as error:
            process_record = {"spawnState": "unknown", "reason": type(error).__name__}
            mark_lifecycle_unknown(prepare_id, "spawn-failed",
                                   processes={"client": process_record})
            raise
        stdout_drain = guard.StreamDrain(client.stdout, LIMITS["outputBytes"])
        stderr_drain = guard.StreamDrain(client.stderr, LIMITS["outputBytes"])
        client_identity = guard.process_identity(client.pid)
        process_record = {
            "spawnState": "started" if client_identity is not None else "unknown",
            "pid": client.pid,
            "identity": client_identity,
            "reason": None if client_identity is not None else "identity-unreadable",
        }
        # The actual process identity is held in this outer frame before the
        # identity journal write.
        update_lifecycle_plan(prepare_id, processes={"client": process_record})
        if client_identity is None:
            raise RuntimeError("client-identity")
        try:
            client.stdin.write(b"GO\n")
            client.stdin.flush()
        except (BrokenPipeError, OSError):
            # Pure tools do not consume stdin; a fast exit can close the pipe.
            pass
        try:
            returncode = client.wait(timeout=120)
        except subprocess.TimeoutExpired:
            stop = guard.stop_group(client_identity, graceful=2, term=2)
            raise RuntimeError("tool-timeout:" + stop.get("state", "unknown")) from None
        stdout_drain.finish()
        stderr_drain.finish()
        stdout = stdout_drain.data()
        if not stdout_drain.drain_complete() or not stderr_drain.drain_complete():
            raise RuntimeError("tool-drain-incomplete")
        if stdout_drain.truncated or stderr_drain.truncated:
            raise RuntimeError("tool-output-truncated")
        if returncode != 0:
            raise RuntimeError("tool-exit:%s:%s" % (
                returncode, stderr_drain.data()[-160:].decode("utf-8", "replace")))
        return stdout
    finally:
        active = sys.exc_info()[1]
        cleanup_failure = None
        try:
            if client is not None:
                client.stdin.close()
        except (OSError, AttributeError):
            pass
        try:
            plan, _ = read_lifecycle_plan(prepare_id)
            confirmed, cleanup = cleanup_lifecycle_plan(plan, prepare_id)
            if not confirmed:
                cleanup_failure = RuntimeError(
                    "tool-cleanup-unconfirmed:" + json.dumps(cleanup, sort_keys=True))
        except BaseException as error:  # noqa: BLE001
            cleanup_failure = error
        # Never mask the original create/spawn/tool failure with a secondary
        # cleanup error.  A successful body still requires confirmed cleanup.
        if cleanup_failure is not None and active is None:
            raise cleanup_failure


def prepare_container_layout():
    """Formal layout preparation validates and uses the preflight bytes only."""
    preflight_result = preflight_context()
    layout, layout_sha = prepare_layout_from_preflight(preflight_result)
    write_json_document(PREPARE / "layout" / "layout.sha256", {
        "version": 3,
        "layoutSha256": layout_sha,
        "layoutStructureSha256": preflight_result["layoutStructureSha256"],
        "preflightReceiptSha256": preflight_result["receiptSha256"],
    })
    return layout, layout_sha


def prepare_container_bind(plan, plan_sha):
    preflight_result = preflight_context()
    inputs = verify_prepare_inputs(preflight_result)
    tag = random_tag()
    role = "bind-" + tag[:8]
    stage = Path(PREPARE) / ("stage-bind-" + tag)
    prepare_id, _plan = write_lifecycle_plan(
        role, stage, tag, container_name(role, tag),
        mounts={str(stage / "tools"): "/review/tools",
                str(stage / "input"): "/review/input"},
    )
    for sub in ("tools", "input/fixtures"):
        _safe_mkdir(stage / sub)
    for name in ("experiment_compile.py", "structure.py"):
        (stage / "tools" / name).write_bytes((TOOLS / name).read_bytes())
    (stage / "input" / "experiment-plan.json").write_bytes(PLAN.read_bytes())
    (stage / "input" / "layout.json").write_bytes(inputs["layoutBytes"])
    for entry in plan["fixtures"]:
        target = stage / "input" / "fixtures" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / entry["path"]).read_bytes())
    for path in stage.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    stage.chmod(0o555)
    stage_id = guard.stage_identity(stage)
    command = ["-I", "-B", "-S", "/review/tools/experiment_compile.py",
               "--mode", "bind", "--plan", "/review/input/experiment-plan.json",
               "--layout", "/review/input/layout.json", "--workspace", "/review/input/fixtures",
               "--image-id", IMAGE, "--expected-python", PYTHON_VERSION,
               "--out", "/tmp/bind.json"]
    stdout = run_tool_container(
        role, tag, command,
        {str(stage / "tools"): "/review/tools", str(stage / "input"): "/review/input"},
        str(stage), stage_id, prepare_id,
    )
    receipt = _last_json_line(stdout)
    if receipt.get("state") != "accepted":
        die(79, "bind-blocked")
    if receipt.get("layoutSha256") != inputs["layoutSha256"]:
        die(79, "bind-layout-digest")
    if receipt.get("layoutStructureSha256") != inputs["layoutStructureSha256"]:
        die(79, "bind-layout-structure")
    for result in receipt["results"]:
        if result.get("derivation", {}).get("layoutSha256") != inputs["layoutSha256"]:
            die(79, "bind-result-layout-digest")
    receipt, receipt_sha = write_json_document(PREPARE / "bind" / "bind.json", receipt)
    write_json_document(PREPARE / "bind-receipt.json", {
        "version": 3, "protocolRevision": PROTOCOL_REVISION,
        "kind": "prepare-receipt", "step": "bind-all",
        "state": "completed", "targetExecutions": 0, "imageId": IMAGE,
        "preflightId": preflight_result["preflightId"],
        "preflightReceiptSha256": preflight_result["receiptSha256"],
        "profileSha256": preflight_result["profileSha256"],
        "layoutSha256": inputs["layoutSha256"],
        "layoutStructureSha256": inputs["layoutStructureSha256"],
        "observerTemplateSha256": inputs["templateSha256"],
        **observation_identity_fields(inputs),
        "planSha256": plan_sha, "bindSha256": receipt_sha,
        "bindings": {
            result["classId"]: {
                "bindingId": result["bindingId"],
                "pointId": result["point"]["id"],
                "bindingSha256": result["binding"]["bindingSha256"],
                "callerSha256": result["callerSha256"],
                "stagedPath": result["stagedPath"],
                "callerCandidates": len(result.get("callerCandidates") or []),
            }
            for result in receipt["results"]
        },
        "createdAt": now(),
    })
    return receipt, receipt_sha


def compile_attempt(plan, plan_sha, number, challenge):
    preflight_result = preflight_context()
    inputs = verify_prepare_inputs(preflight_result)
    tag = random_tag()
    role = "compile-%04d-%s" % (number, tag[:8])
    stage = Path(PREPARE) / ("stage-compile-%04d-%s" % (number, tag))
    prepare_id, _plan = write_lifecycle_plan(
        role, stage, tag, container_name(role, tag), attempt=number,
        mounts={str(stage / "tools"): "/review/tools",
                str(stage / "input"): "/review/input"},
    )
    # Link the preparation plan to its parent target before any stage,
    # container or process can exist.  A standalone ``prepare compile`` has no
    # target record and stays a self-contained preparation plan.  The three
    # durable association writes are ordered parent intent, child link,
    # parent completion; an incomplete link blocks stage creation.
    if attempt_path(number).is_file():
        associate_preparation(number, prepare_id)
        require_association_complete(number, prepare_id)
    for sub in ("tools", "input/fixtures"):
        _safe_mkdir(stage / sub)
    for name in ("experiment_compile.py", "structure.py"):
        (stage / "tools" / name).write_bytes((TOOLS / name).read_bytes())
    (stage / "input" / "experiment-plan.json").write_bytes(PLAN.read_bytes())
    (stage / "input" / "layout.json").write_bytes(inputs["layoutBytes"])
    for entry in plan["fixtures"]:
        target = stage / "input" / "fixtures" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / entry["path"]).read_bytes())
    for path in stage.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    stage.chmod(0o555)
    stage_id = guard.stage_identity(stage)
    command = ["-I", "-B", "-S", "/review/tools/experiment_compile.py",
               "--mode", "structure", "--plan", "/review/input/experiment-plan.json",
               "--layout", "/review/input/layout.json", "--workspace", "/review/input/fixtures",
               "--image-id", IMAGE, "--expected-python", PYTHON_VERSION,
               "--attempt", str(number), "--challenge", challenge, "--out", "/tmp/expected.json"]
    stdout = run_tool_container(
        role, tag, command,
        {str(stage / "tools"): "/review/tools", str(stage / "input"): "/review/input"},
        str(stage), stage_id, prepare_id,
    )
    receipt = _last_json_line(stdout)
    if receipt.get("state") != "prepared":
        die(79, "compile-blocked")
    if receipt.get("challenge") != challenge:
        die(79, "compile-challenge")
    if receipt.get("layoutSha256") != inputs["layoutSha256"]:
        die(79, "compile-layout-digest")
    if receipt.get("layoutStructureSha256") != inputs["layoutStructureSha256"]:
        die(79, "compile-layout-structure")
    receipt, receipt_sha = write_json_document(
        PREPARE / ("compile-%04d" % number) / "expected.json", receipt
    )
    write_json_document(PREPARE / ("compile-%04d-receipt.json" % number), {
        "version": 3, "protocolRevision": PROTOCOL_REVISION,
        "kind": "prepare-receipt", "step": "compile-per-attempt",
        "attempt": number, "state": "completed", "targetExecutions": 0,
        "preflightId": preflight_result["preflightId"],
        "preflightReceiptSha256": preflight_result["receiptSha256"],
        "profileSha256": preflight_result["profileSha256"],
        "layoutSha256": inputs["layoutSha256"],
        "layoutStructureSha256": inputs["layoutStructureSha256"],
        "observerTemplateSha256": inputs["templateSha256"],
        **observation_identity_fields(inputs),
        "challenge": challenge, "expectedSha256": receipt_sha, "createdAt": now(),
    })
    return receipt, receipt_sha


# ------------------------------------------------------------------- target run
def run_target(record, plan):
    number = record["attempt"]
    preflight_result = preflight_context()
    inputs = verify_prepare_inputs(preflight_result)
    item = next(entry for entry in plan["attempts"] if entry["attempt"] == number)
    bind, bind_sha = read_json(PREPARE / "bind" / "bind.json")
    result = next(
        entry for entry in bind["results"] if entry["classId"] == record["classId"]
    )
    if result.get("derivation", {}).get("layoutSha256") != inputs["layoutSha256"]:
        die(79, "binding-layout-digest")
    if result.get("derivation", {}).get("layoutStructureSha256") != inputs["layoutStructureSha256"]:
        die(79, "binding-layout-structure")
    expected, expected_sha = read_json(
        PREPARE / ("compile-%04d" % number) / "expected.json"
    )
    if expected.get("challenge") != record["challenge"]:
        die(79, "prepared-challenge-mismatch")
    if record.get("expectedSha256") not in (None, expected_sha):
        die(79, "expected-digest-mismatch")
    if expected.get("layoutSha256") != inputs["layoutSha256"]:
        die(79, "expected-layout-digest")
    if expected.get("layoutStructureSha256") != inputs["layoutStructureSha256"]:
        die(79, "expected-layout-structure")
    payload = expected["payload"]
    argv = list(item["argvBase"])
    argv[item["probeIndex"]] = item["probePrefix"] + payload + item["probeSuffix"]
    sources = closure_sources_for(plan, record["classId"])
    if set(sources) != set(result["closure"]):
        die(79, "closure-sources")
    config = {
        "version": 1,
        "module": result["module"],
        "callable": result["callable"],
        "argv": argv,
        "closure": result["closure"],
        "stdlibPaths": ["/usr/lib/python3.12", "/usr/lib/python3.12/lib-dynload"],
        "allowedEnvKeys": sorted(ALLOWED_ENV),
        "optionalThirdParty": item.get("optionalThirdParty", []),
        "optionalLocalAbsent": item.get("optionalLocalAbsent", []),
    }
    run_dir = Path(RUNS) / ("%04d" % number)
    tag = random_tag()
    stage_dir = run_dir / ("stage-" + tag)
    role = "run-%04d" % number
    name = container_name(role, tag)
    planned_mounts = {
        str(stage_dir / "runroot"): "/review/runroot",
        str(stage_dir / "config"): "/review/config",
        str(stage_dir / "tools"): "/review/tools",
    }
    # The resource plan and fsync happen BEFORE the config file, the stage or
    # any container/process can exist.
    prepare_id, resource_plan = write_lifecycle_plan(
        role, stage_dir, tag, name, attempt=number, mounts=planned_mounts,
        process_roles=("client", "observer"),
    )
    resource_plan.update({
        "targetUser": "%s:%s" % (TARGET_UID, TARGET_GID),
        "entrypoint": INTERPRETER,
        "interactive": True,
        "envKeys": sorted(ALLOWED_ENV),
        "layoutSha256": inputs["layoutSha256"],
        "layoutStructureSha256": inputs["layoutStructureSha256"],
        "observerTemplateSha256": inputs["templateSha256"],
        **observation_identity_fields(inputs),
        "preflightReceiptSha256": preflight_result["receiptSha256"],
    })
    update_lifecycle_plan(prepare_id, **resource_plan)
    update_attempt(
        number,
        state="planned",
        prepareId=prepare_id,
        resourcePlanPath=str(lifecycle_plan_path(prepare_id).relative_to(ROOT)),
        resourceIntent=resource_plan,
        stageDir=str(stage_dir),
        checkpointStep="planned",
    )
    advance_attempt_proof(number, "plan-created")
    checkpoint(number, "planned")
    # The proof is durably advanced before each resource can exist.
    advance_attempt_proof(number, "stage-creation", not_created={"stage": False})
    _safe_mkdir(run_dir)
    config_path = run_dir / "run.json"
    config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    staged = stage_run_inputs(stage_dir, config_path, sources)
    for relative, source_sha in staged["closure"].items():
        if result["closure"].get(relative) != source_sha:
            die(79, "closure-digest:" + relative)
    if staged["mounts"] != planned_mounts:
        die(79, "stage-mount-plan-mismatch")
    try:
        update_lifecycle_plan(
            prepare_id, stageState="created", stageIdentity=staged["stageIdentity"],
            configSha256=staged["configSha256"], launcherSha256=staged["launcherSha256"],
        )
        update_attempt(
            number, state="staged", stageIdentity=staged["stageIdentity"],
            checkpointStep="staged",
        )
        advance_attempt_proof(number, "stage-created")
    except BaseException:
        mark_lifecycle_unknown(prepare_id, "stage-identity-journal",
                               stageState="unknown")
        raise
    checkpoint(number, "staged")
    update_lifecycle_plan(prepare_id, state="creating", containerState="create-attempted")
    advance_attempt_proof(number, "container-creation",
                          not_created={"container": False})
    try:
        container = create_container(
            name, tag, role,
            ["-I", "-B", "-S", "/review/tools/target_launcher.py"],
            staged["mounts"], attempt=number,
        )
    except BaseException:
        mark_lifecycle_unknown(prepare_id, "create-failed",
                               containerState="create-unknown")
        raise
    identifier = container["id"]
    container_record = {
        "containerId": identifier,
        "containerName": name,
        "tag": tag,
        "containerCreated": True,
        "image": IMAGE,
    }
    # The actual identity is retained in this outer frame before any identity
    # journal write.  ``command_run`` still has this record if a journal fails.
    identity_context = {**resource_plan, **container_record}
    try:
        update_lifecycle_plan(prepare_id, containerState="created",
                              containerId=identifier, lifecycle="created")
        update_attempt(
            number,
            resourceIdentity=identity_context,
            containerId=identifier,
            containerCreated=True,
            lifecycle="created",
            checkpointStep="created",
        )
    except BaseException:
        try:
            guard.write_new_json_document(lifecycle_identity_path(prepare_id), {
                **identity_context, "prepareId": prepare_id,
                "identityJournal": "failed-after-create", "createdAt": now(),
            })
        except BaseException:  # noqa: BLE001
            pass
        raise
    checkpoint(number, "created")
    processes = {
        "client": {"spawnState": "not-started"},
        "observer": {"spawnState": "not-started"},
    }
    client = None
    observer = None
    observer_drain = None
    observer_err = None
    stdout_drain = None
    stderr_drain = None
    raw_path = run_dir / "observer.raw"
    observer_path = run_dir / "observer.bt"
    execution = {"targetExit": None, "goState": "not-attempted", "executionState": "not-started"}
    stop_info = None
    end_info = None
    try:
        processes["client"] = {
            "spawnState": "spawn-attempted", "pid": None, "identity": None,
        }
        update_lifecycle_plan(prepare_id, processes=processes)
        update_attempt(number, processes=processes, lifecycle="client-spawn-attempted",
                       checkpointStep="client-spawn-attempted")
        advance_attempt_proof(number, "client-spawn", not_created={"client": False})
        try:
            client = start_attached(identifier)
        except BaseException as error:
            # An exception around spawn is ambiguous: the process may exist.
            processes["client"] = {
                "spawnState": "unknown", "pid": None, "identity": None,
                "reason": type(error).__name__,
            }
            mark_lifecycle_unknown(prepare_id, "client-spawn-failed",
                                   processes=processes)
            update_attempt(number, processes=processes, lifecycle="client-spawn-unknown",
                           checkpointStep="client-spawn-unknown")
            raise
        stdout_drain = guard.StreamDrain(client.stdout, LIMITS["outputBytes"])
        stderr_drain = guard.StreamDrain(client.stderr, LIMITS["outputBytes"])
        client_identity = guard.process_identity(client.pid)
        processes["client"] = {
            "spawnState": "started" if client_identity is not None else "unknown",
            "pid": client.pid,
            "identity": client_identity,
            "reason": None if client_identity is not None else "identity-unreadable",
        }
        update_attempt(number, processes=processes, lifecycle="client-started",
                       checkpointStep="client-started")
        update_lifecycle_plan(prepare_id, processes=processes)
        checkpoint(number, "client-started")
        if client_identity is None:
            die(79, "client-identity")
        reason = verify_config_inside(identifier, staged["configSha256"])
        if reason:
            die(79, reason)
        inspect = guard.docker("inspect", "--type", "container", "-f", "{{.State.Pid}}", identifier)
        target_pid_text = (inspect.stdout or "").strip()
        if inspect.returncode != 0 or not target_pid_text.isdigit() or int(target_pid_text) <= 0:
            die(79, "container-pid")
        target_pid = int(target_pid_text)
        rendered = render_observer(record, target_pid)
        try:
            observer_sha = guard.write_new_bytes(observer_path, rendered)
        except FileExistsError:
            die(79, "observer-exists")
        processes["observer"] = {
            "spawnState": "spawn-attempted", "pid": None, "identity": None,
        }
        update_lifecycle_plan(prepare_id, processes=processes)
        update_attempt(number, processes=processes, lifecycle="observer-spawn-attempted",
                       checkpointStep="observer-spawn-attempted")
        advance_attempt_proof(number, "observer-spawn", not_created={"observer": False})
        try:
            observer = start_observer(observer_path)
        except BaseException as error:
            processes["observer"] = {
                "spawnState": "unknown", "pid": None, "identity": None,
                "reason": type(error).__name__,
            }
            mark_lifecycle_unknown(prepare_id, "observer-spawn-failed",
                                   processes=processes)
            update_attempt(number, processes=processes, lifecycle="observer-spawn-unknown",
                           checkpointStep="observer-spawn-unknown")
            raise
        observer_id = guard.process_identity(observer.pid)
        processes["observer"] = {
            "spawnState": "started" if observer_id is not None else "unknown",
            "pid": observer.pid,
            "identity": observer_id,
            "reason": None if observer_id is not None else "identity-unreadable",
        }
        update_attempt(number, processes=processes, lifecycle="observer-started",
                       checkpointStep="observer-started")
        update_lifecycle_plan(prepare_id, processes=processes)
        checkpoint(number, "observer-started")
        if observer_id is None:
            die(79, "observer-identity")
        observer_drain = guard.StreamDrain(observer.stdout, LIMITS["outputBytes"])
        observer_err = guard.StreamDrain(observer.stderr, LIMITS["outputBytes"])
        begin = observer_drain.wait_for_prefix(b"BEGIN ", LIMITS["observerArmTimeoutSeconds"])
        if begin is None:
            raise RuntimeError("observer-not-armed")
        update_attempt(
            number,
            state="running",
            runId="attempt-%04d" % number,
            observerPath=str(observer_path.relative_to(ROOT)),
            observerSha256=observer_sha,
            targetPid=target_pid,
            processes=processes,
            layoutSha256=inputs["layoutSha256"],
            layoutStructureSha256=inputs["layoutStructureSha256"],
            observerTemplateSha256=inputs["templateSha256"],
            **observation_identity_fields(inputs),
            profileSha256=inputs["profileSha256"],
            lifecycle="armed",
            checkpointStep="armed",
            startedAt=now(),
        )
        checkpoint(number, "armed")
        update_attempt(number, goState="writing")
        try:
            client.stdin.write(b"GO\n")
            client.stdin.flush()
            update_attempt(number, goState="sent", targetExecutions=1,
                           checkpointStep="go-sent")
            checkpoint(number, "go-sent")
            execution["goState"] = "sent"
        except (BrokenPipeError, OSError) as error:
            # The GO write is ambiguous; treat the slot as attempted.
            update_attempt(number, goState="write-unknown", targetExecutions=1,
                           checkpointStep="go-write-unknown")
            checkpoint(number, "go-write-unknown", detail=type(error).__name__)
            execution["goState"] = "write-unknown"
            raise RuntimeError("go-write:" + type(error).__name__) from None
        try:
            returncode = client.wait(timeout=LIMITS["targetTimeoutSeconds"])
            execution["targetExit"] = returncode
            execution["executionState"] = "observed"
        except subprocess.TimeoutExpired:
            execution["executionState"] = "timeout"
            update_attempt(number, executionState="timeout", targetExecutions=1,
                           checkpointStep="target-timeout")
            raise RuntimeError("target-timeout") from None
        finally:
            stdout_drain.finish(5)
            stderr_drain.finish(5)
            (run_dir / "target.stdout").write_bytes(stdout_drain.data())
            (run_dir / "target.stderr").write_bytes(stderr_drain.data())
        stop_info = guard.stop_group(
            observer_id,
            graceful=LIMITS["observerStopGraceSeconds"],
            term=2.0,
        )
        observer_drain.finish(5)
        observer_err.finish(5)
        raw = observer_drain.data()
        try:
            guard.write_new_bytes(raw_path, raw)
        except FileExistsError:
            die(79, "raw-exists")
        parsed_events, parse_errors, details = buffer_protocol_v2.parse_output(
            raw, "attempt-%04d" % number, record["challenge"][:12],
            "/review/runroot/" + result["stagedPath"], result["callOffset"], 4,
            raw_truncated=observer_drain.truncated or observer_err.truncated,
            framing_policy=FRAMING_POLICY,
        )
        end_info = {
            "present": details.get("endCount") == 1,
            "multiple": (details.get("endCount") or 0) > 1,
            "trailing": details.get("trailingAfterEnd") is True,
            "truncated": observer_drain.truncated or observer_err.truncated,
            "beginCount": details.get("beginCount"),
            "endCount": details.get("endCount"),
            "marker": details.get("marker"),
            "markerCount": details.get("markerCount"),
            "trailingBlankLines": details.get("trailingBlankLines"),
            "observationProtocol": OBSERVATION_PROTOCOL,
            "framingPolicy": FRAMING_POLICY,
            "line": details.get("end"),
            "parseErrors": parse_errors,
            "forcedStop": stop_info.get("forced") is True,
            "gracefulStop": (
                stop_info.get("stopped") is True
                and stop_info.get("forced") is False
                and stop_info.get("signal") == "SIGINT"
            ),
            "drainComplete": (
                observer_drain.drain_complete() and observer_err.drain_complete()
            ),
        }
        update_attempt(
            number,
            state="observed",
            targetExit=execution["targetExit"],
            executionState=execution["executionState"],
            targetExecutions=1 if execution["goState"] == "sent" else 0,
            goState="sent",
            observationRawSha256=sha_file(raw_path),
            observerStop=stop_info,
            observerEnd=end_info,
            clientExited=execution["executionState"] == "observed",
            observerStopped=stop_info.get("stopped") is True,
            processes=processes,
            finishedAt=now(),
            checkpointStep="observed",
        )
        checkpoint(number, "observed")
        advance_attempt_proof(number, "running")
        return {
            "targetExit": execution["targetExit"],
            "rawPath": raw_path,
            "observerPath": observer_path,
            "executionState": "observed",
        }
    finally:
        current, _ = read_json(attempt_path(number))
        proc = dict(current.get("processes") or processes)
        if observer is not None:
            stopped = guard.stop_group(
                (proc.get("observer") or {}).get("identity"), graceful=2, term=2
            ) if isinstance(proc.get("observer"), dict) and proc["observer"].get("identity") else {
                "stopped": (proc.get("observer") or {}).get("spawnState") == "not-started",
                "state": "not-started" if (proc.get("observer") or {}).get("spawnState") == "not-started" else "unknown",
                "forced": False,
            }
        else:
            stopped = {"stopped": True, "state": "not-started", "forced": False}
        if client is not None:
            client_stop = guard.stop_group(
                (proc.get("client") or {}).get("identity"), graceful=2, term=2
            ) if isinstance(proc.get("client"), dict) and proc["client"].get("identity") else {
                "stopped": (proc.get("client") or {}).get("spawnState") == "not-started",
                "state": "not-started" if (proc.get("client") or {}).get("spawnState") == "not-started" else "unknown",
                "forced": False,
            }
        else:
            client_stop = {"stopped": True, "state": "not-started", "forced": False}
        try:
            if client is not None:
                client.stdin.close()
        except (OSError, AttributeError):
            pass
        update_attempt(
            number,
            processes=proc,
            resourceFinalize={"observer": stopped, "client": client_stop, "at": now()},
        )


# -------------------------------------------------------------------- cleanup
def _process_record(value):
    if isinstance(value, dict) and "spawnState" in value:
        return value
    if isinstance(value, dict) and value.get("pid"):
        return {"spawnState": "started", "identity": value, "pid": value.get("pid")}
    if value is None:
        return {"spawnState": "unknown", "reason": "not-recorded"}
    return {"spawnState": "unknown", "reason": "malformed-record"}


def _query_process(record, graceful, term):
    state = guard.spawn_group_state(record)
    stopped = {"stopped": state.get("state") == "exited", "state": state.get("state"),
               "forced": False, "proof": state.get("proof")}
    if state.get("state") == "alive":
        stopped = guard.stop_group(record.get("identity"), graceful=graceful, term=term)
        state = guard.spawn_group_state(record)
        stopped = {**stopped, "state": state.get("state"), "proof": state.get("proof")}
    return state, stopped


def plan_record_reason(plan, intent, record):
    """Reject cross-record identity contradictions before any destructive call."""
    if type(plan) is not dict:
        return "plan-shape"
    info = lifecycle_role(plan)
    if info is None:
        return "role"
    if plan.get("attempt") is not None and record.get("attempt") != plan.get("attempt"):
        return "attempt"
    if record.get("prepareId") is not None \
            and record.get("prepareId") != plan.get("prepareId"):
        return "prepareId"
    if type(intent) is dict and intent.get("prepareId") is not None \
            and intent.get("prepareId") != plan.get("prepareId"):
        return "prepareId"
    for field in ("role", "operationRole"):
        if type(intent) is dict and intent.get(field) is not None \
                and intent.get(field) != plan.get(field):
            return field
    for field in ("tag", "containerName", "imageId", "image", "stageDir"):
        if type(intent) is dict and intent.get(field) is not None \
                and plan.get(field) is not None and intent.get(field) != plan.get(field):
            return field
    if record.get("stageDir") is not None and plan.get("stageDir") is not None \
            and record.get("stageDir") != plan.get("stageDir"):
        return "stageDir"
    if record.get("containerId") is not None and plan.get("containerId") is not None \
            and record.get("containerId") != plan.get("containerId"):
        return "containerId"
    if record.get("stageIdentity") is not None and plan.get("stageIdentity") is not None \
            and record.get("stageIdentity") != plan.get("stageIdentity"):
        return "stageIdentity"
    if type(intent) is dict and intent.get("stageIdentity") is not None \
            and plan.get("stageIdentity") is not None \
            and intent.get("stageIdentity") != plan.get("stageIdentity"):
        return "stageIdentity"
    return None


def _cleanup_unknown(number, reason, final_stage_check="not-attempted-identity-mismatch",
                     **fields):
    record, _ = read_json(attempt_path(number))
    current = classify_attempt_record(record)
    if current["recordState"] in {"invalid", "unreadable"}:
        raise RecordValidationError(
            "attempt-record-invalid:" + ",".join(current["recordIssues"][:4]))
    receipts = _append_cleanup_receipt(
        record.get("cleanupReceipts"), record.get("cleanup"))
    check = record.get("cleanupCheck") \
        if type(record.get("cleanupCheck")) is dict else {}
    outcome = {
        "confirmed": False,
        "state": "incomplete",
        "identityReason": reason,
        "reason": reason,
        "finalStageCheck": final_stage_check,
        "stage": {"removed": False, "state": final_stage_check},
        "checkedAt": now(),
        **fields,
    }
    durable_update_attempt(
        number,
        cleanup=outcome,
        cleanupCheck={
            "protocol": CLEANUP_CHECK_PROTOCOL,
            "state": "incomplete",
            "attempt": number,
            "startedAt": check.get("startedAt"),
            "startedCount": check.get("startedCount"),
            "finishedAt": now(),
            "reason": reason,
        },
        cleanupReceipts=_append_cleanup_receipt(receipts, outcome),
        reservationHeld=True,
        settled=False,
    )
    return False


def assess_associations(number, record):
    """Pure association reconciliation before any target/child destruction.

    Contradictions block 78.  Directory enumeration must have completed; an
    unreadable/malformed potentially relevant plan or an incomplete association
    keeps every known child and the parent held and prevents destructive calls.
    """
    assessment = scan_association_candidates(number, record)
    if assessment["contradictions"] and not assessment.get("reason"):
        assessment["reason"] = "association-contradiction"
    assessment["outcomes"] = {}
    assessment["clear"] = (
        assessment.get("directory", {}).get("state") in {"present", "absent"}
        and not assessment["unreadable"]
        and not assessment["damaged"]
        and not assessment["incomplete"]
        and not assessment["contradictions"]
    )
    if not assessment["clear"]:
        reason = assessment.get("reason") or "association-incomplete"
        assessment["reason"] = reason
        assessment["outcomes"] = {
            prepare_id: {"confirmed": False, "reason": reason}
            for prepare_id in sorted(assessment["candidates"])
        }
    return assessment


def perform_association_cleanup(assessment):
    """Re-query every reconciled child; no unrelated/global cleanup."""
    outcomes = {}
    clear = True
    for prepare_id, _assessed in sorted(assessment["candidates"].items()):
        try:
            _revalidate_association_scope(assessment)
        except RecoveryIncomplete as error:
            outcomes[prepare_id] = {
                "confirmed": False,
                "reason": "association-directory-unknown",
                "detail": str(error)[:160],
            }
            clear = False
            continue
        try:
            # Re-read the exact disk plan immediately before its resources are
            # queried; an external change is a contradiction or incomplete.
            plan, _path = read_lifecycle_plan(prepare_id)
            confirmed, outcome = cleanup_lifecycle_plan(plan, prepare_id)
        except SystemExit as error:
            if error.code == 78:
                raise
            outcomes[prepare_id] = {
                "confirmed": False, "reason": "cleanup-incomplete:system-exit"}
            clear = False
            continue
        except BaseException as error:  # noqa: BLE001 - incomplete, not success
            outcomes[prepare_id] = {
                "confirmed": False,
                "reason": "cleanup-incomplete:" + type(error).__name__,
            }
            clear = False
            continue
        outcomes[prepare_id] = {"confirmed": confirmed, "cleanup": outcome}
        clear = clear and confirmed
    return clear, outcomes


def cleanup_associated_plans(record):
    """Compatibility wrapper: reconcile the original association, then clean."""
    number = record.get("attempt")
    assessment = assess_associations(number, record)
    if not assessment["clear"]:
        hold_association_candidates(assessment, assessment["reason"])
        if assessment["contradictions"]:
            die(78, assessment["contradictions"][0])
        return False, assessment["outcomes"]
    hold_association_candidates(assessment, "parent-full-recheck-required")
    return perform_association_cleanup(assessment)


def _cleanup_invalid_record(number, record, classification):
    """Hold valid related records without rewriting the damaged source bytes."""
    prepare_id = record.get("prepareId")
    valid_prepare_id = _is_prepare_id(prepare_id)
    assessment = assess_associations(number, record)
    held_ok, holds = hold_association_candidates(
        assessment, "parent-record-invalid",
        exclude={prepare_id} if valid_prepare_id else set())
    parent_hold = None
    if valid_prepare_id:
        opened = open_lifecycle_plan(prepare_id)
        if opened["state"] == "present":
            parent_hold = _hold_plan(prepare_id, "parent-record-invalid")
        elif opened["state"] == "contradiction":
            die(78, "prepare-plan-identity:" + str(opened.get("detail")))
    if assessment["contradictions"]:
        sys.stderr.write(
            "runner: association-contradiction:%s:holds=%s\n"
            % (assessment["contradictions"][0],
               json.dumps(holds, sort_keys=True)[:1200]))
        die(78, assessment["contradictions"][0])
    sys.stderr.write(
        "runner: record-invalid:attempt=%s:issues=%s:held=%s:holdFailures=%s\n"
        % (number, ",".join(classification["recordIssues"][:6]),
           held_ok, json.dumps(
               {key: value for key, value in holds.items()
                if value.get("held") is not True}, sort_keys=True)[:1200]))
    return False


def cleanup_attempt(record):
    """Re-query the original target resources; no invalid-plan fallback.

    Before any resource query the current cleanup check is durably recorded as
    checking, the reservation is held and settlement is false.  Historical
    resource-creation proof is never moved backward or overwritten.  Missing,
    unreadable, damaged or invalid plans are incomplete (3), never permission to
    rebuild identity from ``resourceIntent``.  Ownership contradictions block
    (78) before any signal/delete.  The final durable journals are part of the
    success predicate; the reservation stays held until settlement.
    """
    number = record["attempt"]
    # Read/classify the original bytes before mutating either journal.  An
    # invalid resource/history field leaves those bytes untouched, but valid
    # related records are still independently discovered and held.
    original = classify_attempt_record(record)
    if original["recordState"] in {"invalid", "unreadable"}:
        return _cleanup_invalid_record(number, record, original)

    # B5: current cleanup status first, durably, before any resource query.
    begin_attempt_cleanup_check(number)
    stored, _ = read_json(attempt_path(number))
    merged = dict(stored)
    guarded = {"cleanup", "cleanupCheck", "cleanupReceipts",
               "reservationHeld", "settled"}
    for key, value in record.items():
        if key in guarded:
            continue
        if value is not None:
            merged[key] = value
    for key in guarded:
        merged[key] = stored.get(key)

    intent = merged.get("resourceIntent") or merged.get("resourceIdentity") or {}
    if type(intent) is not dict:
        return _cleanup_unknown(number, "intent-shape")
    associated_prepare_ids(merged)
    association_intents(merged)
    prepare_id = merged.get("prepareId")
    plan = None
    valid_prepare_id = (type(prepare_id) is str
                        and PREPARE_ID_RE.fullmatch(prepare_id) is not None)

    # Reconcile the original association purely before any destructive call,
    # even if the target plan itself is unreadable.  Every readable known
    # child is durably held/current-success-invalidated first.
    assessment = assess_associations(number, merged)
    reason = assessment.get("reason") or "association-incomplete"
    association_holds = {}
    if assessment["clear"]:
        held_ok, association_holds = hold_association_candidates(
            assessment, "parent-full-recheck-required",
            exclude={prepare_id} if valid_prepare_id else set())
    else:
        held_ok, association_holds = hold_association_candidates(
            assessment, reason,
            exclude={prepare_id} if valid_prepare_id else set())
    if not assessment["clear"]:
        if valid_prepare_id:
            _hold_plan(prepare_id, reason)
        if assessment["contradictions"]:
            sys.stderr.write(
                "runner: association-contradiction:%s:holds=%s\n"
                % (assessment["contradictions"][0],
                   json.dumps({
                       key: value for key, value in association_holds.items()
                       if value.get("held") is not True
                   }, sort_keys=True)[:1200]))
            die(78, assessment["contradictions"][0])
        return _cleanup_unknown(
            number, reason,
            associated=association_holds,
            associatedClear=False,
            associationCandidates=len(assessment["candidates"]),
            associationUnreadable=assessment["unreadable"],
            associationDamaged=assessment["damaged"],
            associationIncomplete=assessment["incomplete"],
            associationScan={
                "scanned": assessment["scanned"],
                "listed": assessment["listed"],
                "pendingIntents": len(assessment["pending"]),
                "directory": assessment.get("directory", {}).get("state"),
                "directoryDetail": assessment.get("directory", {}).get("detail"),
            },
        )
    if not held_ok:
        if valid_prepare_id:
            _hold_plan(prepare_id, "association-child-hold-unconfirmed")
        return _cleanup_unknown(
            number, "association-child-hold-unconfirmed",
            associated=association_holds,
            associatedClear=False,
            associationCandidates=len(assessment["candidates"]),
            associationUnreadable=assessment["unreadable"],
            associationIncomplete=assessment["incomplete"],
            associationScan={
                "scanned": assessment["scanned"],
                "listed": assessment["listed"],
                "pendingIntents": len(assessment["pending"]),
                "directory": assessment.get("directory", {}).get("state"),
                "directoryDetail": assessment.get("directory", {}).get("detail"),
            },
        )

    if valid_prepare_id:
        opened = open_lifecycle_plan(prepare_id)
        if opened["state"] == "contradiction":
            if opened.get("detail") == "selector-mismatch":
                die(78, "prepare-plan-selector-mismatch")
            die(78, "prepare-plan-identity:" + str(opened.get("detail")))
        if opened["state"] != "present":
            _hold_plan(prepare_id, "prepare-plan-" + opened["state"])
            return _cleanup_unknown(
                number, "prepare-plan-" + opened["state"],
                associated=association_holds,
                associatedClear=False,
                associationCandidates=len(assessment["candidates"]),
                associationUnreadable=assessment["unreadable"],
                associationIncomplete=assessment["incomplete"],
                associationScan={
                    "scanned": assessment["scanned"],
                    "listed": assessment["listed"],
                    "pendingIntents": len(assessment["pending"]),
                    "directory": assessment.get("directory", {}).get("state"),
                    "directoryDetail": assessment.get("directory", {}).get("detail"),
                },
            )
        plan = opened["plan"]
        if merged.get("prepareId") != plan.get("prepareId"):
            die(78, "resource-identity-mismatch:prepareId")
        info = lifecycle_role(plan)
        if info is None or info["kind"] != "run":
            die(78, "resource-identity-mismatch:target-plan-role")
        if plan.get("attempt") != number:
            die(78, "resource-identity-mismatch:target-attempt")
        reason = plan_record_reason(plan, intent, merged)
        if reason:
            die(78, "resource-identity-mismatch:" + reason)
        identity_state, identity_detail = lifecycle_identity_state(prepare_id, plan)
        if identity_state == "contradiction":
            die(78, "resource-identity-mismatch:identity-journal:" + str(identity_detail))
        if identity_state in {"unreadable", "invalid"}:
            return _cleanup_unknown(number, "identity-journal-unavailable",
                                    associated=association_holds,
                                    associatedClear=False)
        if identity_state == "present":
            plan = plan_with_identity_journal(plan, identity_detail)
        # The target plan is held/checking before its resources are queried.
        begin_plan_cleanup_check(prepare_id, plan)
    elif prepare_id is not None and not valid_prepare_id:
        return _cleanup_unknown(number, "prepare-id-invalid")

    # Re-prove the exact directory scope before the first destructive call.
    try:
        _revalidate_association_scope(assessment)
    except RecoveryIncomplete as error:
        if valid_prepare_id:
            _hold_plan(prepare_id, "association-directory-unknown")
        return _cleanup_unknown(
            number, "association-directory-unknown",
            associated=association_holds,
            associatedClear=False,
            associationReason=str(error)[:160],
        )

    if plan is not None:
        container = remove_plan_container(plan)
        processes = plan.get("processes") or {}
    else:
        container_record = {
            "containerId": merged.get("containerId") or intent.get("containerId"),
            "containerName": intent.get("containerName"),
            "tag": intent.get("tag"),
            "containerCreated": (merged.get("containerCreated") is True
                                 or intent.get("containerCreated") is True),
            "image": IMAGE,
        }
        has_scope = bool(intent or merged.get("containerId") or merged.get("stageDir"))
        if has_scope:
            container = guard.remove_container_verified(container_record)
            processes = merged.get("processes") or {}
        elif has_not_created_proof(merged):
            container = {"removed": True, "state": "never-created",
                         "proof": "resource-phase-not-created"}
            processes = merged.get("processes") or {
                "client": {"spawnState": "not-started"},
                "observer": {"spawnState": "not-started"},
            }
        else:
            # Old records without the explicit new-protocol proof remain
            # incomplete.  Absence of a plan, elapsed time or an empty process
            # map is never an absence proof.
            return _cleanup_unknown(number, "no-resource-proof")

    if not processes and plan is not None:
        processes = plan.get("processes")
    processes = processes or {}
    if "client" in processes:
        client_state, client_stop = _query_process(_process_record(processes.get("client")), 3, 2)
    else:
        client_state = {"state": "unknown", "proof": "process-record-missing"}
        client_stop = {"stopped": False, "state": "unknown", "proof": "process-record-missing"}
    if "observer" in processes:
        observer_state, observer_stop = _query_process(_process_record(processes.get("observer")), 5, 2)
    else:
        observer_state = {"state": "unknown", "proof": "process-record-missing"}
        observer_stop = {"stopped": False, "state": "unknown", "proof": "process-record-missing"}

    associated_clear, associated = perform_association_cleanup(assessment)
    client_exited = client_state.get("state") == "exited"
    observer_exited = observer_state.get("state") == "exited"
    container_clear = container.get("removed") is True

    try:
        _revalidate_association_scope(assessment)
    except RecoveryIncomplete as error:
        return _cleanup_unknown(
            number, "association-directory-unknown",
            associated=associated,
            associatedClear=False,
            associationReason=str(error)[:160],
        )

    resources_clear = (container_clear and client_exited and observer_exited
                       and associated_clear)
    # Final stage handling happens after every resource query, on every path.
    # Clean only after the container/process/associated proofs; on an
    # unconfirmed cleanup the stage files are retained as evidence.
    stage_path = (merged.get("stageDir") or intent.get("stageDir")
                  or (plan or {}).get("stageDir"))
    stage_identity = (merged.get("stageIdentity") or intent.get("stageIdentity")
                      or (plan or {}).get("stageIdentity"))
    if resources_clear and not stage_path:
        stage = {"removed": True, "state": "never-created", "lstatAfter": "absent"}
    elif resources_clear:
        stage = cleanup_stage(stage_path, stage_identity)
    else:
        final = guard.path_state(stage_path) if stage_path else {"state": "unknown"}
        stage = {"removed": False, "state": "retained-resources-unresolved",
                 "lstatAfter": final.get("state", "unknown")}

    confirmed = resources_clear and stage.get("removed") is True
    outcome = {
        "confirmed": confirmed,
        "state": "confirmed" if confirmed else "incomplete",
        "container": container,
        "clientExited": client_exited,
        "clientState": client_state,
        "clientStop": client_stop,
        "observerExited": observer_exited,
        "observerState": observer_state,
        "observerStop": observer_stop,
        "associated": associated,
        "associatedClear": associated_clear,
        "associationCandidates": len(assessment["candidates"]),
        "associationScan": {
            "scanned": assessment["scanned"],
            "listed": assessment["listed"],
            "pendingIntents": len(assessment["pending"]),
            "directory": assessment.get("directory", {}).get("state"),
            "directoryDetail": assessment.get("directory", {}).get("detail"),
        },
        "associationHold": association_holds,
        "stage": stage,
        "finalStageCheck": "after-resources",
        "resourceCreationPhase": (merged.get("resourceProof") or {}).get("phase")
        if isinstance(merged.get("resourceProof"), dict) else None,
        "checkedAt": now(),
    }
    if plan is not None:
        try:
            finish_plan_cleanup(prepare_id, confirmed, outcome)
        except BaseException as error:
            raise RuntimeError("cleanup-plan-journal:" + type(error).__name__) from None

    # The final durable attempt journal is part of the success predicate.  The
    # reservation deliberately stays held until the settlement write.
    current, _ = read_json(attempt_path(number))
    receipts = _append_cleanup_receipt(
        current.get("cleanupReceipts"), current.get("cleanup"))
    check_started = current.get("cleanupCheck") \
        if type(current.get("cleanupCheck")) is dict else {}
    state = "confirmed" if confirmed else "incomplete"
    final_outcome = dict(outcome)
    receipts = _append_cleanup_receipt(receipts, final_outcome)
    check = {
        "protocol": CLEANUP_CHECK_PROTOCOL,
        "state": state,
        "attempt": number,
        "startedAt": check_started.get("startedAt"),
        "startedCount": check_started.get("startedCount"),
        "finishedAt": now(),
        "resourceCreationPhase": final_outcome.get("resourceCreationPhase"),
    }
    try:
        durable_update_attempt(
            number,
            cleanup=final_outcome,
            cleanupCheck=check,
            cleanupReceipts=receipts,
            reservationHeld=True,
            settled=False,
            clientExited=client_exited,
            observerStopped=observer_exited,
        )
    except BaseException as error:
        try:
            durable_update_attempt(
                number,
                cleanupCheck={**check, "state": "incomplete",
                              "finishedAt": now(), "reason": "final-journal-failed"},
                reservationHeld=True,
                settled=False,
            )
        except BaseException:  # noqa: BLE001 - original failure is the cause
            pass
        raise RuntimeError("cleanup-attempt-journal:" + type(error).__name__) from None
    return confirmed


def collect_and_judge(record, plan):
    number = record["attempt"]
    run_dir = Path(RUNS) / ("%04d" % number)
    raw_path = run_dir / "observer.raw"
    observer_path = run_dir / "observer.bt"
    if not raw_path.is_file() or not observer_path.is_file():
        die(79, "observation-missing")
    bind, _ = read_json(PREPARE / "bind" / "bind.json")
    result = next(
        entry for entry in bind["results"] if entry["classId"] == record["classId"]
    )
    observation_path = run_dir / "observation.json"
    if os.path.lexists(observation_path):
        die(79, "observation-exists")
    end_info = record.get("observerEnd") or {}
    collected = subprocess.run(
        [
            sys.executable, str(TOOLS / "collect_observer.py"),
            # Formal admission is explicitly buffer-v2 with the tool-fixed
            # END-LF framing policy.  There is no sniffing or legacy fallback.
            "--observation-protocol", OBSERVATION_PROTOCOL,
            "--framing-policy", FRAMING_POLICY,
            "--raw", str(raw_path),
            "--run-id", "attempt-%04d" % number,
            "--tag", record["challenge"][:12],
            "--caller-path", "/review/runroot/" + result["stagedPath"],
            "--call-offset", str(result["callOffset"]),
            "--target-pid", str(record["targetPid"]),
            "--target-uid", TARGET_UID,
            "--max-events", "4",
            "--out", str(observation_path),
        ] + (["--raw-truncated"] if end_info.get("truncated") else [])
          + (["--forced-stop"] if end_info.get("forcedStop") or end_info.get("gracefulStop") is False else [])
          + (["--drain-incomplete"] if end_info.get("drainComplete") is False else []),
        capture_output=True, text=True,
    )
    if not observation_path.is_file() or os.path.islink(observation_path):
        guard.write_new_json_document(observation_path, {
            "version": 2, "kind": "dynstruct-observation", "state": "invalid",
            "protocol": OBSERVATION_PROTOCOL,
            "framingPolicy": FRAMING_POLICY,
            "runId": "attempt-%04d" % number, "tag": record["challenge"][:12],
            "events": [], "errors": ["collector-failed:" + (collected.stderr or collected.stdout)[-120:]],
            "targetPid": record["targetPid"], "targetUid": int(TARGET_UID),
            "rawSha256": sha_file(raw_path), "rawBytes": raw_path.stat().st_size,
            "callerPath": "/review/runroot/" + result["stagedPath"],
            "callOffset": result["callOffset"], "targetExecuted": True,
            "targetSelfReportUsed": False,
        })
    observation, observation_sha = read_json(observation_path)
    update_attempt(number, observationSha256=observation_sha,
                   observationCollectorExit=collected.returncode,
                   observationFresh=True)
    verdict_path = run_dir / "verification.json"
    subprocess.run(
        [
            sys.executable, str(TOOLS / "judge.py"),
            "--binding", str(PREPARE / "bind" / "bind.json"),
            "--expected", str(PREPARE / ("compile-%04d" % number) / "expected.json"),
            "--observation", str(observation_path),
            "--attempt", str(attempt_path(number)),
            "--admission", str(ADMISSION),
            "--manifest", str(MANIFEST),
            "--preflight", str(preflight_context()["receiptPath"]),
            "--review-receipt", str(SOURCE_REVIEW_RECEIPT),
            "--observer", str(observer_path),
            "--raw", str(raw_path),
            "--layout", str(PREPARE / "layout" / "layout.json"),
            "--template", str(TOOLS / BUFFER_TEMPLATE_NAME),
            "--profile", str(PROFILE),
            "--out", str(verdict_path),
        ],
        check=False,
    )
    if not verdict_path.is_file() or os.path.islink(verdict_path):
        die(79, "verdict-missing")
    verdict, verdict_sha = read_json(verdict_path)
    update_attempt(
        number,
        state="judged",
        observationSha256=observation_sha,
        verificationSha256=verdict_sha,
        decision=verdict["decision"],
        reason=verdict["reason"],
        judgedAt=now(),
    )
    return verdict, verdict_sha


def _invalidate_refused_settlement(number, reason):
    """Durably hold a parent whose current settlement scope was refused.

    This reuses the same existing current-cleanup invalidating helper used for
    resource-scope holds.  It performs no resource operation, refunds no
    counter slot and never rewrites a damaged related record.  The previous
    cleanup receipt/history is appended before the current cleanup is marked
    incomplete, so ``effectiveCleanupConfirmed`` becomes false for query/status.

    A failed hold write is reported as unpersisted unknown.  It is never
    converted into a success claim; the caller must keep the result unknown.
    """
    try:
        _cleanup_unknown(
            number, reason,
            final_stage_check="not-attempted-settlement-refused")
        return {"ok": True, "reason": reason}
    except BaseException as error:  # noqa: BLE001 - unpersisted hold is not success
        sys.stderr.write("runner: settlement-hold-failed:%s:%s\n" % (
            type(error).__name__, str(error)[:200]))
        try:
            durable_update_attempt(number, reservationHeld=True, settled=False)
            return {"ok": False, "minimalHold": True,
                    "error": type(error).__name__}
        except BaseException as error2:  # noqa: BLE001 - explicit unknown
            sys.stderr.write("runner: settlement-hold-unpersisted:%s:%s\n" % (
                type(error2).__name__, str(error2)[:200]))
            return {"ok": False, "minimalHold": False,
                    "error": type(error2).__name__}


def settle(number, cleanup_confirmed, decision, executed):
    """Settle only from a recomputed complete scope, never caller booleans."""
    opened, validation = _attempt_validation(number)
    if opened["state"] != "present" \
            or validation["recordState"] in {"invalid", "unreadable"}:
        sys.stderr.write("runner: settlement-refused:attempt-record-%s\n"
                         % validation["recordState"])
        return "unknown"
    scope = settlement_scope(number)
    safe_cleanup = (cleanup_confirmed is True
                    and validation["effectiveCleanupConfirmed"] is True
                    and scope["state"] == "releasable")
    if not safe_cleanup:
        sys.stderr.write(
            "runner: settlement-refused:scope:%s\n"
            % ",".join(scope.get("problems") or [])[:600])
        # A related child failure invalidates the valid parent's *current*
        # cleanup success while preserving its historical receipts.  This is
        # the same durable hold helper used before resource-scope operations.
        _invalidate_refused_settlement(number, "settlement-refused-scope")
        try:
            update_attempt(
                number,
                state="unknown",
                targetExecutions=1 if executed else 0,
                reservationHeld=True,
                settled=False,
                completedAt=now(),
            )
        except BaseException as error:  # noqa: BLE001 - never claim success
            sys.stderr.write("runner: settlement-state-unknown:%s:%s\n" % (
                type(error).__name__, str(error)[:200]))
        return "unknown"
    final_state = "completed" if decision in {"confirmed", "excluded"} \
        else "unknown"
    update_attempt(
        number,
        state=final_state,
        targetExecutions=1 if executed else 0,
        reservationHeld=False,
        settled=True,
        completedAt=now(),
    )
    return final_state


# -------------------------------------------------------------------- commands
def command_status():
    """Read-only status with additive raw and effective record truth."""
    counter = load_counter()
    records = []
    directory = _explicit_directory_entries(Path(STATE))
    if directory["state"] == "present":
        for name in directory["entries"]:
            match = ATTEMPT_RECORD_RE.fullmatch(name)
            if not match:
                continue
            number = int(match.group(1))
            opened, validation = _attempt_validation(number)
            if opened["state"] == "missing":
                continue
            raw = opened.get("record") if opened["state"] == "present" else {}
            raw = raw if type(raw) is dict else {}
            row = {
                "attempt": number,
                "state": raw.get("state", opened["state"]),
                "decision": raw.get("decision"),
                "reason": raw.get("reason"),
                "reservationHeld": raw.get("reservationHeld"),
                "settled": raw.get("settled"),
                "executionState": raw.get("executionState"),
            }
            records.append(_add_validation_fields(row, validation))
    elif directory["state"] != "absent":
        records.append({
            "attempt": None,
            "state": directory["state"],
            "recordState": "unreadable",
            "recordIssues": ["state-directory:" + str(directory.get("detail"))],
            "effectiveCleanupConfirmed": False,
            "effectiveReservationHeld": True,
        })
    preparations = []
    plan_dir = _explicit_directory_entries(plans_dir())
    if plan_dir["state"] == "present":
        for name in plan_dir["entries"]:
            if name.endswith(".identity.json"):
                continue
            prepare_id = name[:-5] if name.endswith(".json") else ""
            if not PREPARE_ID_RE.fullmatch(prepare_id):
                continue
            opened, validation = _plan_validation(prepare_id)
            if opened["state"] == "missing":
                continue
            plan = opened.get("plan") if type(opened.get("plan")) is dict else {}
            row = {
                "prepareId": plan.get("prepareId", prepare_id),
                "operationRole": plan.get("operationRole") or plan.get("role"),
                "attempt": plan.get("attempt"),
                "state": plan.get("state", opened["state"]),
                "stageState": plan.get("stageState"),
                "containerState": plan.get("containerState"),
                "stageDir": plan.get("stageDir"),
                "tag": plan.get("tag"),
                "containerName": plan.get("containerName"),
                "reservationHeld": plan.get("reservationHeld"),
            }
            if not plan:
                row["path"] = str((plans_dir() / name))
            preparations.append(_add_validation_fields(row, validation))
    elif plan_dir["state"] != "absent":
        preparations.append({
            "prepareId": None,
            "state": plan_dir["state"],
            "recordState": "unreadable",
            "recordIssues": ["prepare-directory:" + str(plan_dir.get("detail"))],
            "effectiveCleanupConfirmed": False,
            "effectiveReservationHeld": True,
        })
    print(json.dumps({"counter": counter, "attempts": records,
                      "preparations": preparations},
                     sort_keys=True, indent=1))


def _query_attempt_payload(number):
    opened, validation = _attempt_validation(number)
    if opened["state"] == "missing":
        die(79, "attempt-not-found")
    if opened["state"] == "present":
        payload = dict(opened["record"])
        return _add_validation_fields(payload, validation)
    if opened["state"] == "contradiction":
        die(78, "attempt-record-selector-mismatch")
    payload = {"attempt": number}
    return _add_validation_fields(payload, validation)


def command_query(number=None, prepare_id=None):
    """Read-only query; damaged raw bytes are reported, never rewritten."""
    if prepare_id is not None:
        opened, validation = _plan_validation(prepare_id)
        if opened["state"] == "missing":
            die(79, "attempt-not-found")
        if opened["state"] == "contradiction":
            if opened.get("detail") == "selector-mismatch":
                die(78, "prepare-plan-selector-mismatch")
            die(78, "prepare-plan-identity:" + str(opened.get("detail")))
        plan = opened.get("plan") if type(opened.get("plan")) is dict else None
        if plan is None:
            payload = {"prepareId": prepare_id}
        else:
            if lifecycle_role(plan) is None:
                die(78, "operation-role-unknown")
            payload = {"prepareId": prepare_id, "plan": dict(plan)}
        _add_validation_fields(payload, validation)
        attempt_number = plan.get("attempt") if type(plan) is dict else None
        if type(attempt_number) is int:
            attempt_opened, attempt_validation = _attempt_validation(attempt_number)
            if attempt_opened["state"] == "present":
                payload["attemptRecord"] = _add_validation_fields(
                    dict(attempt_opened["record"]), attempt_validation)
            elif attempt_opened["state"] != "missing":
                payload["attemptRecord"] = _add_validation_fields(
                    {"attempt": attempt_number}, attempt_validation)
        print(json.dumps(payload, sort_keys=True, indent=1))
        return 0
    if number is None:
        die(79, "selector-required")
    payload = _query_attempt_payload(number)
    print(json.dumps(payload, sort_keys=True, indent=1))
    return 0


def command_run(number):
    admission, _manifest, manifest_sha, _admission_sha, preflight_result = (
        require_admission("run", attempt=number)
    )
    # Layout/template/profile changes are rejected before an attempt slot is
    # reserved or a stage/container is created.
    verify_prepare_inputs(preflight_result)
    acquire_batch_lock()
    plan, plan_sha = load_plan()
    bind_path = PREPARE / "bind" / "bind.json"
    if not bind_path.is_file():
        die(79, "binding-missing")
    expected_path = PREPARE / ("compile-%04d" % number) / "expected.json"
    prepared_challenge = None
    if expected_path.is_file():
        expected, expected_sha = read_json(expected_path)
        prepared_challenge = expected.get("challenge")
        if not CHALLENGE_RE.fullmatch(prepared_challenge or ""):
            die(79, "prepared-challenge")
    record = reserve_attempt(plan, plan_sha, number, admission, prepared_challenge)
    executed = False
    try:
        if prepared_challenge is None:
            require_admission("compile", attempt=number, prepare_step="compile-per-attempt")
            expected, expected_sha = compile_attempt(plan, plan_sha, number, record["challenge"])
        bind, bind_sha = read_json(bind_path)
        result = next(
            entry for entry in bind["results"] if entry["classId"] == record["classId"]
        )
        # A pre-existing standalone compile plan for this attempt is linked to
        # the parent before any target stage/container/process exists.
        associate_existing_preparations(number)
        require_all_associations_complete(number)
        # The expected link is the expected file's bytes, as read back now.
        expected_disk, expected_disk_sha = read_json(expected_path)
        if expected_disk_sha != expected_sha:
            die(79, "expected-readback")
        update_attempt(
            number,
            state="prepared",
            expectedSha256=expected_disk_sha,
            expectedFile=str(expected_path.relative_to(ROOT)),
            bindingSha256=bind_sha,
            bindingId=result["bindingId"],
            pointId=result["point"]["id"],
            prepare={
                "layout": "prepare/layout/layout.json",
                "bind": "prepare/bind/bind.json",
                "expected": str(expected_path.relative_to(ROOT)),
            },
            checkpointStep="prepared",
        )
        checkpoint(number, "prepared")
        result_run = run_target(record, plan)
        executed = result_run.get("executionState") == "observed"
        record, _ = read_json(attempt_path(number))
        cleanup_ok = cleanup_attempt(record)
        record, _ = read_json(attempt_path(number))
        verdict, _ = collect_and_judge(record, plan)
        final_state = settle(number, cleanup_ok, verdict["decision"], executed)
        return 0 if final_state == "completed" else 3
    except (SystemExit, Exception) as error:  # noqa: BLE001 - fail closed
        record, _ = read_json(attempt_path(number))
        try:
            cleanup_ok = cleanup_attempt(record)
        except Exception:  # noqa: BLE001
            cleanup_ok = False
        record, _ = read_json(attempt_path(number))
        attempted = (
            record.get("executionState") == "observed"
            or record.get("targetExecutions") == 1
            or record.get("goState") in {"sent", "write-unknown"}
        )
        update_attempt(
            number,
            state="unknown",
            targetExecutions=1 if attempted else 0,
            reservationHeld=not cleanup_ok,
            settled=cleanup_ok,
            failure=type(error).__name__ + ":" + str(error)[:200],
            failedAt=now(),
            checkpointStep="failed",
        )
        raise


def hold_parent_for_prepare(prepare_id, reason):
    """Retain exactly bound parents and every readable known child.

    This performs no resource operation and never invents a parent relation:
    only an attempt whose prepareId/list/intent names the requested id is held.
    State-directory enumeration is explicit; an unreadable attempt journal is
    reported as unconfirmed rather than silently skipped.
    """
    scan = _scan_attempt_records()
    held = []
    unconfirmed = []
    if scan["state"] == "contradiction":
        die(78, "state-directory-" + str(
            (scan.get("directory") or {}).get("detail")))
    if scan["state"] == "unknown":
        return {"held": [], "unconfirmed": [{
            "state": "state-directory-unknown",
            "detail": (scan.get("directory") or {}).get("detail"),
        }]}
    for item in scan["unreadable"]:
        unconfirmed.append(item)
    for item in scan.get("invalid") or []:
        unconfirmed.append({
            "attempt": item.get("attempt"),
            "state": "invalid",
            "issues": item.get("issues"),
        })
    for item in scan["contradictions"]:
        unconfirmed.append({"state": "contradiction", "detail": item})
    for number, record in sorted(scan["records"].items()):
        try:
            relevant = attempt_references_prepare(record, prepare_id)
        except SystemExit:
            raise
        if not relevant:
            continue
        classification = classify_attempt_record(record)
        if classification["recordState"] in {"invalid", "unreadable"}:
            unconfirmed.append({
                "attempt": number,
                "state": classification["recordState"],
                "issues": classification["recordIssues"],
            })
            continue
        try:
            assessment = assess_associations(number, record)
            held_ok, holds = hold_association_candidates(
                assessment, reason,
                exclude={prepare_id} if type(prepare_id) is str else set())
            if assessment["contradictions"]:
                sys.stderr.write(
                    "runner: association-contradiction:%s:holds=%s\n"
                    % (assessment["contradictions"][0],
                       json.dumps({
                           key: value for key, value in holds.items()
                           if value.get("held") is not True
                       }, sort_keys=True)[:1200]))
                die(78, assessment["contradictions"][0])
            begin_attempt_cleanup_check(number)
            _cleanup_unknown(number, reason,
                             final_stage_check="not-attempted-parent-scope-held")
            held.append(number)
        except SystemExit as error:
            if error.code == 78:
                raise
            unconfirmed.append({"attempt": number, "state": "unconfirmed"})
        except BaseException as error:  # noqa: BLE001 - unpersisted hold is still held
            try:
                durable_update_attempt(
                    number, reservationHeld=True, settled=False)
                held.append(number)
            except BaseException:  # noqa: BLE001
                unconfirmed.append({"attempt": number,
                                    "error": type(error).__name__})
    return {"held": held, "unconfirmed": unconfirmed}


def _settlement_validation_ok(number):
    """Recompute shared effective truth and the whole related scope.

    On any refusal the selected parent is durably held and its current cleanup
    is invalidated through the shared hold helper.  This is the same class of
    state as a direct ``settle()`` refusal: historical receipts and raw related
    bytes stay intact, no resource is touched and no counter slot is refunded.
    """
    opened, validation = _attempt_validation(number)
    if opened["state"] != "present" \
            or validation["recordState"] in {"invalid", "unreadable"}:
        validation["settlementProblems"] = [
            "attempt-record-" + validation["recordState"]]
        _invalidate_refused_settlement(
            number, "settlement-refused-attempt-record")
        return False, validation
    if validation["effectiveCleanupConfirmed"] is not True:
        validation["settlementProblems"] = ["parent-cleanup-unconfirmed"]
        _invalidate_refused_settlement(
            number, "settlement-refused-parent-cleanup")
        return False, validation
    scope = settlement_scope(number)
    validation["settlementScope"] = scope
    validation["settlementProblems"] = list(scope.get("problems") or [])
    if scope["state"] != "releasable":
        _invalidate_refused_settlement(
            number, "settlement-refused-scope")
        return False, validation
    return True, validation


def command_recover(number=None, prepare_id=None):
    """Recover by role; never replay a target and never refund a spent slot."""
    acquire_batch_lock()
    if prepare_id is not None:
        directory_scan = _explicit_directory_entries(plans_dir())
        if directory_scan["state"] == "contradiction":
            die(78, "association-directory-" + str(
                directory_scan.get("detail")))
        opened = open_lifecycle_plan(prepare_id)
        if opened["state"] in {"missing", "unreadable", "invalid"}:
            hold_parent_for_prepare(prepare_id,
                                    "prepare-plan-" + opened["state"])
            sys.stderr.write("runner: prepare-plan-incomplete:%s:%s\n"
                             % (opened["state"], opened.get("detail")))
            return 3
        if opened["state"] == "contradiction":
            if opened.get("detail") == "selector-mismatch":
                die(78, "prepare-plan-selector-mismatch")
            die(78, "prepare-plan-identity:" + str(opened.get("detail")))
        plan = opened["plan"]
        info = lifecycle_role(plan)
        if info is None:
            die(78, "operation-role-unknown")
        if directory_scan["state"] == "unknown":
            _hold_plan(prepare_id, "association-directory-unknown")
            hold_parent_for_prepare(prepare_id,
                                    "association-directory-unknown")
            sys.stderr.write(
                "runner: prepare-scope-incomplete:association-directory-unknown:%s\n"
                % directory_scan.get("detail"))
            return 3
        if info["kind"] == "run":
            attempt_number = plan.get("attempt")
            if type(attempt_number) is not int:
                die(78, "target-attempt-missing")
            opened_attempt = open_attempt_record(attempt_number)
            if opened_attempt["state"] in {"missing", "unreadable", "invalid"}:
                _hold_plan(prepare_id,
                           "attempt-record-" + opened_attempt["state"])
                hold_parent_for_prepare(
                    prepare_id, "attempt-record-" + opened_attempt["state"])
                sys.stderr.write("runner: attempt-incomplete:%s:%s\n" % (
                    opened_attempt["state"], opened_attempt.get("detail")))
                return 3
            if opened_attempt["state"] == "contradiction":
                die(78, "resource-identity-mismatch:attempt")
            record = opened_attempt["record"]
            if record.get("prepareId") != prepare_id:
                die(78, "resource-identity-mismatch:prepareId")
            intent = record.get("resourceIntent") or record.get("resourceIdentity") or {}
            reason = plan_record_reason(plan, intent, record)
            if reason:
                die(78, "resource-identity-mismatch:" + reason)
            try:
                confirmed = cleanup_attempt(record)
            except SystemExit:
                raise
            except Exception as error:  # noqa: BLE001 - incomplete, not success
                sys.stderr.write("runner: incomplete-cleanup:%s:%s\n" % (
                    type(error).__name__, str(error)[:200]))
                return 3
            if confirmed:
                settlement_ok, settlement = _settlement_validation_ok(attempt_number)
                if not settlement_ok:
                    sys.stderr.write(
                        "runner: settlement-refused:attempt-record-%s:%s\n" % (
                            settlement["recordState"],
                            ",".join(settlement["recordIssues"][:4])))
                    return 3
                current, _ = read_json(attempt_path(attempt_number))
                fields = {"settled": True, "reservationHeld": False}
                if current.get("state") not in {"completed", "unknown"}:
                    fields["state"] = "aborted"
                    fields["settlement"] = "resources-cleaned"
                try:
                    durable_update_attempt(attempt_number, **fields)
                except Exception as error:  # noqa: BLE001 - incomplete, not success
                    sys.stderr.write("runner: incomplete-settlement:%s:%s\n" % (
                        type(error).__name__, str(error)[:200]))
                    return 3
                record = current
            print(json.dumps({
                "prepareId": prepare_id,
                "attempt": attempt_number,
                "cleanupConfirmed": confirmed,
                "targetExecutions": 1 if record.get("executionState") == "observed" else 0,
                "executionState": record.get("executionState"),
                "replayed": False,
            }, sort_keys=True))
            return 0 if confirmed else 3

        relation = resolve_prepare_parent(plan, prepare_id)
        parent_numbers = set(relation.get("referencing") or [])
        if type(plan.get("parentAttempt")) is int:
            parent_numbers.add(plan["parentAttempt"])
        if relation["state"] == "contradiction":
            # No resource operation, but never leave the selected child or a
            # durably referencing parent reporting a stale success.
            _hold_plan(prepare_id, "parent-full-recheck-required")
            hold_attempt_numbers(parent_numbers, "parent-full-recheck-required")
            die(78, relation.get("reason") or "association-parent-ambiguous")
        if relation["state"] == "incomplete":
            _hold_plan(prepare_id, "parent-full-recheck-required")
            hold_attempt_numbers(parent_numbers, "parent-full-recheck-required")
            sys.stderr.write("runner: parent-scope-incomplete:%s\n"
                             % relation.get("reason"))
            return 3
        if relation["state"] == "bound":
            held, failures = hold_attempt_numbers(
                [relation["parentAttempt"]], "parent-full-recheck-required")
            if failures:
                _hold_plan(prepare_id, "parent-full-recheck-required")
                sys.stderr.write(
                    "runner: incomplete-parent-hold:%s:%s\n" % (
                        failures[0].get("attempt"),
                        failures[0].get("error") or failures[0].get("detail")))
                return 3
        try:
            _revalidate_association_scope({"directory": directory_scan})
        except RecoveryIncomplete as error:
            _hold_plan(prepare_id, "association-directory-unknown")
            sys.stderr.write("runner: prepare-scope-incomplete:%s\n" % str(error)[:160])
            return 3
        try:
            confirmed, outcome = cleanup_lifecycle_plan(plan, prepare_id)
        except SystemExit:
            raise
        except Exception as error:  # noqa: BLE001 - incomplete, not success
            sys.stderr.write("runner: incomplete-cleanup:%s:%s\n" % (
                type(error).__name__, str(error)[:200]))
            return 3
        print(json.dumps({
            "prepareId": prepare_id,
            "operationRole": plan.get("operationRole") or plan.get("role"),
            "cleanupConfirmed": confirmed,
            "cleanup": outcome,
            "replayed": False,
        }, sort_keys=True))
        return 0 if confirmed else 3

    if number is None:
        die(79, "selector-required")
    opened = open_attempt_record(number)
    if opened["state"] in {"missing", "unreadable", "invalid"}:
        sys.stderr.write("runner: attempt-incomplete:%s:%s\n" % (
            opened["state"], opened.get("detail")))
        return 3
    if opened["state"] == "contradiction":
        die(78, "attempt-record-selector-mismatch")
    record = opened["record"]
    try:
        confirmed = cleanup_attempt(record)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - incomplete, not success
        sys.stderr.write("runner: incomplete-cleanup:%s:%s\n" % (
            type(error).__name__, str(error)[:200]))
        return 3
    if confirmed:
        settlement_ok, settlement = _settlement_validation_ok(number)
        if not settlement_ok:
            sys.stderr.write(
                "runner: settlement-refused:attempt-record-%s:%s\n" % (
                    settlement["recordState"],
                    ",".join(settlement["recordIssues"][:4])))
            return 3
        current, _ = read_json(attempt_path(number))
        fields = {"settled": True, "reservationHeld": False}
        if current.get("state") not in {"completed", "unknown"}:
            fields["state"] = "aborted"
            fields["settlement"] = "resources-cleaned"
        try:
            durable_update_attempt(number, **fields)
        except Exception as error:  # noqa: BLE001 - incomplete, not success
            sys.stderr.write("runner: incomplete-settlement:%s:%s\n" % (
                type(error).__name__, str(error)[:200]))
            return 3
        record = current
    print(json.dumps({
        "attempt": number,
        "cleanupConfirmed": confirmed,
        "targetExecutions": 1 if record.get("executionState") == "observed" else 0,
        "executionState": record.get("executionState"),
        "replayed": False,
    }, sort_keys=True))
    return 0 if confirmed else 3


def command_prepare(step, number=None):
    _admission, _manifest, _manifest_sha, _admission_sha, preflight_result = (
        require_admission("prepare", prepare_step=step)
    )
    acquire_batch_lock()
    plan, plan_sha = load_plan()
    # Same-batch global start gate: read the complete STATE and PREPARE/plans
    # scope while holding the lock.  A damaged/unreadable/unknown task or
    # preparation record pauses every new preparation resource start before a
    # counter write, task record, lifecycle plan, stage, container or process.
    problems = _known_scope_problems()
    if problems:
        die(3, "known-record-state:" + ";".join(problems[:6]))
    if step == "layout-v1":
        layout, layout_sha = prepare_container_layout()
        print(json.dumps({"step": step, "state": layout["state"], "sha256": layout_sha}))
        return 0
    if step == "bind-all":
        verify_prepare_inputs(preflight_result)
        bind, bind_sha = prepare_container_bind(plan, plan_sha)
        print(json.dumps({"step": step, "state": bind["state"], "sha256": bind_sha}))
        return 0
    if step == "compile-per-attempt":
        if number is None:
            die(79, "attempt-required")
        verify_prepare_inputs(preflight_result)
        expected_path = PREPARE / ("compile-%04d" % number) / "expected.json"
        if expected_path.is_file():
            expected, expected_sha = read_json(expected_path)
            if expected.get("layoutSha256") != preflight_result["layoutSha256"]:
                die(79, "expected-layout-digest")
            if expected.get("layoutStructureSha256") != preflight_result["layoutStructureSha256"]:
                die(79, "expected-layout-structure")
            print(json.dumps({"step": step, "state": expected["state"],
                              "sha256": expected_sha, "reused": True}))
            return 0
        challenge = os.urandom(16).hex()
        expected, expected_sha = compile_attempt(plan, plan_sha, number, challenge)
        print(json.dumps({"step": step, "state": expected["state"],
                          "sha256": expected_sha, "reused": False}))
        return 0
    die(79, "prepare-step-unsupported")


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    query = sub.add_parser("query")
    query_group = query.add_mutually_exclusive_group(required=True)
    query_group.add_argument("--attempt", type=int)
    query_group.add_argument("--prepare-id")
    cleanup = sub.add_parser("cleanup")
    cleanup_group = cleanup.add_mutually_exclusive_group(required=True)
    cleanup_group.add_argument("--attempt", type=int)
    cleanup_group.add_argument("--prepare-id")
    recover = sub.add_parser("recover")
    recover_group = recover.add_mutually_exclusive_group(required=True)
    recover_group.add_argument("--attempt", type=int)
    recover_group.add_argument("--prepare-id")
    sub.add_parser("prepare-layout")
    sub.add_parser("prepare-bind")
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--attempt", type=int, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            command_status()
            return 0
        if args.command == "query":
            return command_query(args.attempt, args.prepare_id)
        if args.command == "cleanup":
            return command_recover(args.attempt, args.prepare_id)
        if args.command == "recover":
            return command_recover(args.attempt, args.prepare_id)
        if args.command == "prepare-layout":
            return command_prepare("layout-v1")
        if args.command == "prepare-bind":
            return command_prepare("bind-all")
        if args.command == "compile":
            return command_prepare("compile-per-attempt", args.attempt)
        if args.command == "run":
            return command_run(args.attempt)
    except RecoveryIncomplete as error:
        # Known incomplete association/recovering reads are a bounded
        # diagnostic (3), not a traceback.  Ownership contradictions continue
        # to use SystemExit(78) and are not caught here.
        sys.stderr.write("runner: incomplete:%s\n" % str(error)[:240])
        return 3
    except RecordValidationError as error:
        sys.stderr.write("runner: record-incomplete:%s\n" % str(error)[:240])
        return 3
    finally:
        release_batch_lock()
    die(79, "unknown-command")


if __name__ == "__main__":
    raise SystemExit(main())
