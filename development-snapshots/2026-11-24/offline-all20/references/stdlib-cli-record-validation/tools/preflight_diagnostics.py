#!/usr/bin/env python3
"""Version-1 observer early-exit diagnostics for the zero-target preflight.

This module is deliberately an *observer* of the preflight lifecycle.  It never
sends a signal, removes a container, deletes a stage or reaps a process that the
preflight does not already own.  Its only jobs are:

* retain the already-owned ``Popen`` handles and the two ``StreamDrain``
  consumers from the instant the child is spawned;
* record bounded stream bytes and honest lifecycle/returncode metadata;
* persist one exclusive ``process-diagnostics.json`` document plus four
  exclusive stream files in the original preflight evidence directory.

It is stdlib-only and reuses :class:`resource_guard.StreamDrain` so a pipe is
never consumed twice.  No Python object is placed in a JSON document.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

DIAGNOSTIC_VERSION = 1
PROCESS_DIAGNOSTICS_KIND = "zero-target-preflight-process-diagnostics"
DIAGNOSTIC_STREAMS = (
    ("client", "stdout", "diagnostic-client.stdout"),
    ("client", "stderr", "diagnostic-client.stderr"),
    ("observer", "stdout", "diagnostic-observer.stdout"),
    ("observer", "stderr", "diagnostic-observer.stderr"),
)
ROLES = ("client", "observer")
STREAMS = ("stdout", "stderr")
MILESTONE_NAMES = (
    "configAcquired",
    "observerReadyObserved",
    "goSendAttempted",
    "goFlushCompleted",
    "clientExited",
)
READINESS_RESULTS = frozenset({"ready", "early-exit", "stream-error", "timeout", "unknown"})


def now():
    return datetime.now(timezone.utc).isoformat()


def _sha_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _known_integer(value):
    """A real exit status is an int; bool is not an exit status."""
    return isinstance(value, int) and not isinstance(value, bool)


def _normalized_exitcode(value, method):
    """Return (nullable code, known, method, invalid type name)."""
    if value is None:
        return None, False, method, None
    if _known_integer(value):
        return value, True, method, None
    return None, False, method + "-invalid-type", type(value).__name__


def _valid_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _strict_stream_problems(files, returncodes):
    """One strict predicate shared by finalization and read-only status.

    ``files`` is keyed by ``(role, stream)``.  A present stream must have been
    read to EOF, have no read/write/truncation error, have exact persisted
    bytes and digest metadata, and an attached role must have a known integer
    final returncode (negative signal codes are valid).  Never-started roles
    remain conservative: a missing/unattached stream is an explicit problem,
    never a fabricated empty stream or a zero code.
    """
    problems = []
    for role, stream, _name in DIAGNOSTIC_STREAMS:
        label = role + "." + stream
        row = files.get((role, stream))
        if not isinstance(row, dict):
            problems.append("stream-missing:" + label)
            continue
        if row.get("present") is not True:
            problems.append("stream-unattached:" + label)
        if row.get("error"):
            problems.append("stream-error:%s:%s" % (label, row.get("error")))
        if row.get("writeError"):
            problems.append("stream-write-error:%s:%s"
                            % (label, row.get("writeError")))
        if row.get("written") is not True:
            problems.append("stream-not-written:" + label)
        if row.get("truncated") is True:
            problems.append("stream-truncated:" + label)
        if row.get("completed") is not True:
            problems.append("stream-not-completed:" + label)
        if row.get("eof") is not True:
            problems.append("stream-not-eof:" + label)
        if not _valid_sha256(row.get("sha256")):
            problems.append("stream-digest:" + label)
        if row.get("present") is True and row.get("written") is True:
            if (row.get("persistedBytes") != row.get("bytes")
                    or row.get("persistedSha256") != row.get("sha256")):
                problems.append("stream-persisted-mismatch:" + label)
    for role in ROLES:
        value = returncodes.get(role) if isinstance(returncodes, dict) else None
        value = value if isinstance(value, dict) else {}
        if (value.get("known") is not True
                or not _known_integer(value.get("returncode"))):
            problems.append("returncode-unknown:" + role)
    return problems


def read_controller_status():
    """Effective controller credentials from ``/proc/self/status``.

    This is metadata only.  It is never compared with, or used to change, the
    profile/image/ABI/limits/permissions that the preflight fixes.
    """
    result = {
        "source": "/proc/self/status",
        "readAt": now(),
        "uid": None,
        "effectiveUid": None,
        "gid": None,
        "effectiveGid": None,
        "capEff": None,
        "noNewPrivs": None,
        "error": None,
    }
    try:
        raw = Path("/proc/self/status").read_text(encoding="ascii", errors="replace")
    except OSError as error:
        result["error"] = "read:" + type(error).__name__
        return result
    fields = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    uids = fields.get("Uid", "").split()
    gids = fields.get("Gid", "").split()
    result["uid"] = _int_or_none(uids[0]) if uids else None
    result["effectiveUid"] = _int_or_none(uids[1]) if len(uids) > 1 else None
    result["gid"] = _int_or_none(gids[0]) if gids else None
    result["effectiveGid"] = _int_or_none(gids[1]) if len(gids) > 1 else None
    result["capEff"] = fields.get("CapEff") or None
    result["noNewPrivs"] = _int_or_none(fields.get("NoNewPrivs"))
    return result


def resolve_bpftrace(profile=None):
    """Resolve the observer binary without spawning it.

    A version probe would be a second bpftrace invocation and is intentionally
    not performed by this controller.  The sealed profile's declared version is
    recorded separately from any externally supplied observed version.
    """
    path = shutil.which("bpftrace")
    declared = None
    if isinstance(profile, dict):
        declared = profile.get("bpftraceVersion")
    observed = os.environ.get("SCE_BPFTRACE_VERSION") or None
    return {
        "resolvedPath": path,
        "observedVersion": observed,
        "declaredVersion": declared,
        "versionSource": "environment" if observed else (
            "sealed-profile-declared" if declared else "not-available"),
        "probeSpawned": False,
    }


def _safe_poll(process):
    """A poll that never raises and never authorizes an action."""
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return None, "unavailable"
    try:
        return poll(), "poll"
    except BaseException as error:  # noqa: BLE001 - diagnostics must not fail the run
        return None, "poll-error:" + type(error).__name__


def _safe_wait(process, timeout):
    """Bound a wait for an already-owned Popen child only."""
    wait = getattr(process, "wait", None)
    if not callable(wait):
        return None, "unavailable"
    try:
        return wait(timeout=timeout), "wait"
    except subprocess.TimeoutExpired:
        return None, "wait-timeout"
    except BaseException as error:  # noqa: BLE001
        return None, "wait-error:" + type(error).__name__


def _prefix_line(data, prefix):
    for line in bytes(data).splitlines():
        if line.startswith(prefix):
            return line
    return None


def _required_lines_present(data, required_lines):
    lines = bytes(data).splitlines()
    return all(any(line == required for line in lines) for required in required_lines)


def _freshness(drain):
    if drain is None:
        return "unattached"
    if getattr(drain, "error", None):
        return "error"
    try:
        if drain.drain_complete():
            return "eof"
        if drain.data():
            return "live-data"
    except BaseException:  # noqa: BLE001
        return "unknown"
    return "live-empty"


class InvocationRuntime:
    """One outer invocation-owned diagnostic runtime.

    ``roles`` is the only place Python process handles and drainers live.  The
    JSON documents built by :meth:`finalize` contain primitives only.
    """

    def __init__(self, evidence, preflight_id, tag=None, protocol_manifest_sha=None,
                 candidate_manifest_sha=None, license_sha=None, review_sha=None,
                 claim_sha=None, resource_plan=None, resource_plan_sha=None,
                 limit=262144, profile=None, finish_timeout=1.0,
                 wait_timeout=0.25):
        self.evidence = Path(evidence) if evidence is not None else None
        self.preflight_id = preflight_id
        self.tag = tag
        self.protocol_manifest_sha = protocol_manifest_sha
        self.candidate_manifest_sha = candidate_manifest_sha or protocol_manifest_sha
        self.license_sha = license_sha
        self.review_sha = review_sha
        self.claim_sha = claim_sha
        self.resource_plan = copy.deepcopy(resource_plan)
        self.resource_plan_sha = resource_plan_sha
        self.limit = int(limit)
        self.profile = copy.deepcopy(profile) if isinstance(profile, dict) else None
        self.finish_timeout = float(finish_timeout)
        self.wait_timeout = float(wait_timeout)
        self.started_at = now()
        self.started_monotonic = time.monotonic()
        self.phase = None
        self.original_reason = None
        self.capture_error = None
        self.capture_errors = []
        self.readiness = {
            "result": "unknown",
            "reason": "not-observed",
            "observedAt": None,
            "processReturncode": None,
            "stdoutEof": False,
            "stderrEof": False,
            "streamError": None,
        }
        self.milestones = {name: {"observed": False, "count": 0, "at": None,
                                  "monotonic": None, "detail": None}
                           for name in MILESTONE_NAMES}
        self.roles = {
            role: {
                "process": None,
                "command": None,
                "attachedAt": None,
                "attachedMonotonic": None,
                "drains": {"stdout": None, "stderr": None},
                "polls": [],
                "preCleanupPoll": None,
                "observedExitAt": None,
                "observedExitMonotonic": None,
                "cleanupSignals": [],
                "spawnError": None,
                "identity": None,
                "identityPersisted": None,
            }
            for role in ROLES
        }
        self.controller = read_controller_status()
        self.bpftrace = resolve_bpftrace(profile)
        self.finalized = False
        self.finalizing = False
        self.finalization_count = 0
        self.result = None
        self._lock = threading.Lock()

    # --------------------------------------------------------------- binding
    def bind_context(self, context):
        if not isinstance(context, dict):
            return
        self.preflight_id = context.get("preflightId") or self.preflight_id
        self.tag = context.get("tag") or self.tag
        self.protocol_manifest_sha = context.get("protocolManifestSha256") or self.protocol_manifest_sha
        self.candidate_manifest_sha = self.candidate_manifest_sha or self.protocol_manifest_sha
        self.license_sha = context.get("preflightLicenseSha256") or self.license_sha
        self.review_sha = context.get("sourceReviewReceiptSha256") or self.review_sha
        self.claim_sha = context.get("claimSha256") or self.claim_sha
        self.resource_plan = copy.deepcopy(context.get("resourcePlan")) if isinstance(
            context.get("resourcePlan"), dict) else self.resource_plan
        self.resource_plan_sha = context.get("resourcePlanSha256") or self.resource_plan_sha

    def set_phase(self, phase):
        self.phase = str(phase) if phase is not None else None

    def set_error(self, reason):
        if self.original_reason is None and reason is not None:
            self.original_reason = str(reason)

    # --------------------------------------------------------------- process
    def attach_process(self, role, process, command=None):
        """Retain an already-owned handle and start both drains immediately.

        This is called directly after ``Popen`` succeeds and before any
        identity journal write.  It never raises for a drain failure; the
        failure is recorded instead so the handle is not lost.
        """
        if role not in self.roles:
            raise ValueError("unknown-role:" + str(role))
        entry = self.roles[role]
        entry["process"] = process
        entry["command"] = list(command) if command is not None else None
        entry["attachedAt"] = now()
        entry["attachedMonotonic"] = time.monotonic()
        entry["spawnError"] = None
        for stream in STREAMS:
            source = getattr(process, stream, None)
            if source is None:
                self._record_capture_error("stream-unattached:%s.%s" % (role, stream))
                continue
            try:
                # Reuse the existing bounded, continuous consumer.
                from resource_guard import StreamDrain
                entry["drains"][stream] = StreamDrain(source, self.limit)
            except BaseException as error:  # noqa: BLE001
                self._record_capture_error("drain-create:%s.%s:%s"
                                           % (role, stream, type(error).__name__))
        return entry["drains"]

    def attach_failure(self, role, error):
        if role in self.roles:
            self.roles[role]["spawnError"] = type(error).__name__

    def drain(self, role, stream):
        try:
            return self.roles[role]["drains"][stream]
        except KeyError:
            return None

    def _record_capture_error(self, message):
        self.capture_errors.append(str(message))
        if self.capture_error is None:
            self.capture_error = str(message)

    def snapshot_poll(self, role, label):
        """Record poll without replacing group-identity checks or signalling."""
        entry = self.roles.get(role)
        if entry is None:
            return None
        process = entry.get("process")
        if process is None:
            value = {"label": label, "returncode": None, "known": False,
                     "method": "no-process", "at": now(),
                     "monotonic": time.monotonic()}
        else:
            raw_returncode, method = _safe_poll(process)
            returncode, known, method, invalid_type = _normalized_exitcode(
                raw_returncode, method)
            value = {"label": label, "returncode": returncode,
                     "known": known, "method": method,
                     "at": now(), "monotonic": time.monotonic()}
            if invalid_type is not None:
                value["invalidType"] = invalid_type
            if raw_returncode is not None and entry.get("observedExitAt") is None:
                entry["observedExitAt"] = value["at"]
                entry["observedExitMonotonic"] = value["monotonic"]
        entry["polls"].append(value)
        if entry.get("preCleanupPoll") is None:
            entry["preCleanupPoll"] = value
        return value

    def snapshot_polls(self, label):
        return {role: self.snapshot_poll(role, label) for role in ROLES}

    def note_cleanup_signal(self, role, stop_info):
        if not isinstance(stop_info, dict):
            return
        signal_name = stop_info.get("signal")
        forced = stop_info.get("forced")
        if signal_name is None and forced is not True:
            return
        self.roles[role]["cleanupSignals"].append({
            "signal": signal_name,
            "forced": forced,
            "stopped": stop_info.get("stopped"),
            "state": stop_info.get("state"),
            "proof": stop_info.get("proof"),
            "detail": stop_info.get("detail"),
            "recordedAt": now(),
        })

    # ------------------------------------------------------------- milestones
    def milestone(self, name, detail=None):
        if name not in self.milestones:
            self.milestones[name] = {"observed": False, "count": 0, "at": None,
                                     "monotonic": None, "detail": None}
        entry = self.milestones[name]
        entry["observed"] = True
        entry["count"] += 1
        entry["at"] = now()
        entry["monotonic"] = time.monotonic()
        entry["detail"] = detail if detail is None or isinstance(
            detail, (str, int, float, bool, list, dict)) else str(detail)
        return entry

    # -------------------------------------------------------------- readiness
    def observer_ready(self, prefix=b"BEGIN ", timeout=15.0, required_lines=None):
        """Observe readiness without treating early stream EOF as an exit code.

        ``required_lines`` must all be present (exact byte lines) before the
        caller may send GO.  The buffer-v2 preflight passes its protocol marker
        so an early BEGIN alone cannot authorize execution.
        """
        required = tuple(
            item if isinstance(item, bytes) else str(item).encode("utf-8")
            for item in (required_lines or ())
        )
        entry = self.roles["observer"]
        process = entry.get("process")
        stdout = entry["drains"].get("stdout")
        stderr = entry["drains"].get("stderr")
        if process is None or stdout is None:
            self.readiness.update(result="unknown", reason="observer-not-attached",
                                  observedAt=now())
            return None
        deadline = time.monotonic() + float(timeout)
        while True:
            data = stdout.data()
            line = _prefix_line(data, prefix)
            if line is not None and _required_lines_present(data, required):
                self.readiness.update(
                    result="ready",
                    reason=("begin-and-required-lines-observed" if required
                            else "begin-prefix-observed"),
                    observedAt=now(), processReturncode=None,
                    stdoutEof=False, stderrEof=bool(getattr(stderr, "completed", False)),
                    streamError=None,
                )
                detail = {"lineSha256": _sha_bytes(line)}
                if required:
                    detail["requiredLineSha256"] = [_sha_bytes(item) for item in required]
                self.milestone("observerReadyObserved", detail)
                return line
            raw_returncode, method = _safe_poll(process)
            returncode, known, method, invalid_type = _normalized_exitcode(
                raw_returncode, method)
            if raw_returncode is not None:
                if entry.get("observedExitAt") is None:
                    entry["observedExitAt"] = now()
                    entry["observedExitMonotonic"] = time.monotonic()
                self.readiness.update(
                    result="early-exit", reason="process-exited-before-begin",
                    observedAt=now(), processReturncode=returncode,
                    stdoutEof=bool(getattr(stdout, "completed", False)),
                    stderrEof=bool(getattr(stderr, "completed", False)),
                    streamError=None,
                )
                if invalid_type is not None:
                    self.readiness["processInvalidType"] = invalid_type
                return None
            stdout_error = getattr(stdout, "error", None)
            stderr_error = getattr(stderr, "error", None) if stderr is not None else None
            stdout_eof = bool(getattr(stdout, "completed", False))
            stderr_eof = bool(getattr(stderr, "completed", False)) if stderr is not None else False
            if stdout_error or stderr_error:
                self.readiness.update(
                    result="stream-error", reason="stream-read-error",
                    observedAt=now(), processReturncode=None,
                    stdoutEof=stdout_eof, stderrEof=stderr_eof,
                    streamError=stdout_error or stderr_error,
                )
                return None
            if stdout_eof:
                # EOF alone is not an exit-code proof: the process may still be
                # alive.  It is, however, a terminal stream state for readiness.
                self.readiness.update(
                    result="stream-error", reason="stdout-eof-before-begin",
                    observedAt=now(), processReturncode=None,
                    stdoutEof=True, stderrEof=stderr_eof,
                    streamError=None,
                )
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.readiness.update(
                    result="timeout",
                    reason=("required-lines-not-observed-before-deadline" if required
                            else "begin-not-observed-before-deadline"),
                    observedAt=now(), processReturncode=None,
                    stdoutEof=stdout_eof, stderrEof=stderr_eof,
                    streamError=None,
                )
                return None
            time.sleep(min(0.02, max(0.001, remaining)))

    # ------------------------------------------------------------ finalization
    def _finish_drains(self):
        deadline = time.monotonic() + self.finish_timeout
        for role in ROLES:
            for stream in STREAMS:
                drainer = self.drain(role, stream)
                if drainer is None:
                    continue
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    drainer.finish(remaining)
                    error = getattr(drainer, "error", None)
                    done = getattr(drainer, "_done", None)
                    done_set = bool(done.is_set()) if done is not None else False
                    completed = bool(getattr(drainer, "completed", False))
                    if error:
                        self._record_capture_error(
                            "drain-incomplete:%s.%s:%s" % (role, stream, error))
                    elif not (completed and done_set):
                        # The shared global drain deadline expired before EOF.
                        # It is a recorded diagnostic-incomplete reason, never
                        # silent completion merely because a bounded prefix was
                        # already written.
                        self._record_capture_error(
                            "drain-deadline:%s.%s" % (role, stream))
                except BaseException as error:  # noqa: BLE001
                    self._record_capture_error("drain-finish:%s.%s:%s"
                                               % (role, stream, type(error).__name__))

    def _post_cleanup_returncode(self, role):
        entry = self.roles[role]
        process = entry.get("process")
        if process is None:
            return {"returncode": None, "known": False, "method": "no-process",
                    "at": now()}
        raw_returncode, method = _safe_poll(process)
        if raw_returncode is None and method == "poll":
            raw_returncode, method = _safe_wait(process, self.wait_timeout)
        returncode, known, method, invalid_type = _normalized_exitcode(
            raw_returncode, method)
        value = {"returncode": returncode, "known": known,
                 "method": method, "at": now()}
        if invalid_type is not None:
            value["invalidType"] = invalid_type
        if raw_returncode is not None and entry.get("observedExitAt") is None:
            entry["observedExitAt"] = value["at"]
            entry["observedExitMonotonic"] = time.monotonic()
        return value

    def _stream_payload(self, role, stream):
        drainer = self.drain(role, stream)
        if drainer is None:
            return None, {
                "present": False,
                "file": None,
                "bytes": 0,
                "sha256": None,
                "persistedBytes": None,
                "persistedSha256": None,
                "limit": self.limit,
                "truncated": False,
                "completed": False,
                "eof": False,
                "error": "stream-not-attached",
                "freshness": "unattached",
                "returncodeKnown": False,
                "phase": self.phase,
                "capturedAt": now(),
            }
        try:
            payload = drainer.data()
        except BaseException as error:  # noqa: BLE001
            payload = b""
            self._record_capture_error("stream-data:%s.%s:%s"
                                       % (role, stream, type(error).__name__))
        if getattr(drainer, "error", None):
            self._record_capture_error("stream-error:%s.%s:%s"
                                       % (role, stream, drainer.error))
        meta = {
            "present": True,
            "file": None,
            "bytes": len(payload),
            "sha256": _sha_bytes(payload),
            "persistedBytes": None,
            "persistedSha256": None,
            "limit": self.limit,
            "truncated": bool(getattr(drainer, "truncated", False)),
            "completed": bool(getattr(drainer, "completed", False)),
            "eof": bool(getattr(drainer, "completed", False)
                        and getattr(drainer, "_done", None) is not None
                        and drainer._done.is_set()
                        and not getattr(drainer, "error", None)),
            "error": getattr(drainer, "error", None),
            "freshness": _freshness(drainer),
            "returncodeKnown": False,
            "phase": self.phase,
            "capturedAt": now(),
        }
        return payload, meta

    def _write_stream_files(self, stream_rows):
        files = {}
        for role, stream, name in DIAGNOSTIC_STREAMS:
            payload, meta = stream_rows[(role, stream)]
            row = dict(meta)
            row["file"] = name
            row["written"] = False
            row["writeError"] = None
            if payload is not None and self.evidence is not None:
                try:
                    digest = self._write_verified_new_bytes(
                        self.evidence / name, payload)
                    if digest != _sha_bytes(payload):
                        raise OSError("digest-mismatch")
                    row["written"] = True
                    row["sha256"] = digest
                    row["persistedBytes"] = len(payload)
                    row["persistedSha256"] = digest
                except BaseException as error:  # noqa: BLE001
                    row["writeError"] = type(error).__name__
                    self._record_capture_error("write:%s:%s" % (name, type(error).__name__))
            elif payload is None:
                row["writeError"] = "stream-not-attached"
            else:
                row["writeError"] = "evidence-missing"
                self._record_capture_error("write:%s:evidence-missing" % name)
            files[(role, stream)] = row
        return files

    def _write_verified_new_bytes(self, path, payload):
        """Exclusive write plus an exact persisted byte/digest re-read."""
        digest = self._write_new_bytes(path, payload)
        try:
            self._verify_persisted(path, payload, digest)
        except BaseException:
            # The bytes were ours and already created by O_EXCL; never leave a
            # misleading diagnostic that failed persisted-byte verification.
            try:
                Path(path).unlink()
            except OSError:
                pass
            raise
        return digest

    def _verify_persisted(self, path, payload, expected_digest):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise OSError("persisted-not-regular")
        persisted = path.read_bytes()
        if persisted != payload:
            raise OSError("persisted-bytes-mismatch")
        digest = _sha_bytes(persisted)
        if digest != expected_digest:
            raise OSError("persisted-digest-mismatch")
        return len(persisted), digest

    def _write_new_bytes(self, path, payload):
        # Imported lazily so tests can replace the module's writer and so this
        # module never imports a second implementation of the exclusive write.
        import resource_guard
        path = Path(path)
        existed = path.exists() or path.is_symlink()
        try:
            return resource_guard.write_new_bytes(path, payload)
        except BaseException:
            # A write that failed after O_EXCL created our own file must not
            # leave a misleading partial diagnostic behind.  A pre-existing
            # (stale/cross-ID) file is never removed.
            if not existed:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise

    def _json_bytes(self, value):
        return json.dumps(value, sort_keys=True, indent=1,
                          ensure_ascii=True).encode("utf-8") + b"\n"

    def finalize(self, phase=None, context=None, cleanup=None, error=None,
                 capture_error=None):
        """Finalize once; repeated calls return the same result without writes."""
        with self._lock:
            if self.finalized:
                return copy.deepcopy(self.result)
            self.finalized = True
            self.finalizing = True
            self.finalization_count += 1
            if phase is not None:
                self.set_phase(phase)
            if error is not None:
                self.set_error(error)
            if capture_error is not None:
                self._record_capture_error(capture_error)
            if context is not None:
                self.bind_context(context)
                for role in ROLES:
                    record = context.get(role)
                    if isinstance(record, dict):
                        self.roles[role]["identity"] = copy.deepcopy(record.get("identity"))
                        self.roles[role]["identityPersisted"] = record.get("identityPersisted")
            for role in ROLES:
                if self.roles[role].get("preCleanupPoll") is None:
                    self.snapshot_poll(role, "finalize-before-drain")
            self._finish_drains()
            returncodes = {role: self._post_cleanup_returncode(role) for role in ROLES}
            stream_rows = {}
            for role, stream, _name in DIAGNOSTIC_STREAMS:
                stream_rows[(role, stream)] = self._stream_payload(role, stream)
            files = self._write_stream_files(stream_rows)
            for role, stream, _name in DIAGNOSTIC_STREAMS:
                files[(role, stream)]["returncodeKnown"] = returncodes[role]["known"]

            any_truncated = any(row.get("truncated") for row in files.values())
            any_error = any(row.get("error") or row.get("writeError")
                            for row in files.values())
            write_complete = all(row.get("written") for row in files.values())
            persistence_complete = (
                self.evidence is not None
                and write_complete
                and not any(row.get("writeError") for row in files.values())
            )
            stream_problems = _strict_stream_problems(files, returncodes)
            incomplete_reasons = []
            if not persistence_complete:
                incomplete_reasons.append("persistence-incomplete")
            incomplete_reasons.extend(stream_problems)
            if self.capture_error:
                incomplete_reasons.append("capture-error:" + self.capture_error)
            capture_complete = not incomplete_reasons
            strict_complete = bool(persistence_complete and capture_complete)
            document = self._document(files, returncodes, cleanup,
                                      persistence_complete, capture_complete,
                                      strict_complete, incomplete_reasons)
            diagnostics_sha = None
            document_error = None
            if self.evidence is not None:
                try:
                    document_payload = self._json_bytes(document)
                    diagnostics_sha = self._write_verified_new_bytes(
                        self.evidence / "process-diagnostics.json",
                        document_payload,
                    )
                except BaseException as write_error:  # noqa: BLE001
                    document_error = type(write_error).__name__
                    self._record_capture_error("write:process-diagnostics.json:"
                                               + document_error)
            else:
                document_error = "evidence-missing"
                self._record_capture_error("write:process-diagnostics.json:evidence-missing")
            final_reasons = list(incomplete_reasons)
            if document_error is not None:
                final_reasons.append("document-error:" + str(document_error))
            if diagnostics_sha is None:
                final_reasons.append("document-not-written")
                # The persisted document cannot be the same strict predicate
                # if it could not be written/verified.  Keep the in-memory
                # result conservative and identical to the on-disk claim.
                capture_complete = False
                strict_complete = False
            confirmed = bool(
                diagnostics_sha is not None
                and strict_complete
                and document_error is None
            )
            summary = {
                "diagnosticVersion": DIAGNOSTIC_VERSION,
                "state": "complete" if confirmed else "incomplete",
                "confirmed": confirmed,
                "path": ("preflight/evidence/%s/process-diagnostics.json"
                         % self.preflight_id) if self.evidence is not None else None,
                "sha256": diagnostics_sha,
                "captureError": self.capture_error,
                "captureErrors": list(self.capture_errors),
                "persistenceComplete": persistence_complete,
                "captureComplete": capture_complete,
                "anyTruncated": any_truncated,
                "incompleteReasons": final_reasons,
                "documentError": document_error,
                "readiness": copy.deepcopy(self.readiness),
                "returncodes": copy.deepcopy(returncodes),
                "files": {
                    name: copy.deepcopy(files[(role, stream)])
                    for role, stream, name in DIAGNOSTIC_STREAMS
                },
                "phase": self.phase,
                "finalizationCount": self.finalization_count,
            }
            self.result = summary
            self.finalizing = False
            return copy.deepcopy(summary)

    def _document(self, files, returncodes, cleanup, persistence_complete,
                  capture_complete, strict_complete, incomplete_reasons):
        roles = {}
        for role in ROLES:
            entry = self.roles[role]
            process = entry.get("process")
            roles[role] = {
                "role": role,
                "pid": getattr(process, "pid", None) if process is not None else None,
                "identity": copy.deepcopy(entry.get("identity")),
                "identityPersisted": entry.get("identityPersisted"),
                "command": copy.deepcopy(entry.get("command")),
                "spawnedAt": entry.get("attachedAt"),
                "spawnMonotonic": entry.get("attachedMonotonic"),
                "observedExitAt": entry.get("observedExitAt"),
                "observedExitMonotonic": entry.get("observedExitMonotonic"),
                "spawnError": entry.get("spawnError"),
                "preCleanupPoll": copy.deepcopy(entry.get("preCleanupPoll")),
                "polls": copy.deepcopy(entry.get("polls")),
                "postCleanupReturncode": copy.deepcopy(returncodes[role]),
                "cleanupSignals": copy.deepcopy(entry.get("cleanupSignals")),
                "streams": {
                    stream: copy.deepcopy(files[(role, stream)])
                    for stream in STREAMS
                },
            }
        return {
            "version": 1,
            "kind": PROCESS_DIAGNOSTICS_KIND,
            "diagnosticVersion": DIAGNOSTIC_VERSION,
            "protocolRevision": 3,
            "preflightId": self.preflight_id,
            "tag": self.tag,
            "protocolManifestSha256": self.protocol_manifest_sha,
            "candidateManifestSha256": self.candidate_manifest_sha,
            "preflightLicenseSha256": self.license_sha,
            "sourceReviewReceiptSha256": self.review_sha,
            "claimSha256": self.claim_sha,
            "resourcePlan": copy.deepcopy(self.resource_plan),
            "resourcePlanSha256": self.resource_plan_sha,
            "controller": copy.deepcopy(self.controller),
            "bpftrace": copy.deepcopy(self.bpftrace),
            "roles": roles,
            "lifecycle": copy.deepcopy(self.milestones),
            "readiness": copy.deepcopy(self.readiness),
            "outcome": {
                "phase": self.phase,
                "originalReason": self.original_reason,
                "captureError": self.capture_error,
                "persistenceComplete": persistence_complete,
                "captureComplete": capture_complete,
                "confirmed": strict_complete,
                "incompleteReasons": list(incomplete_reasons),
                "cleanupObserved": copy.deepcopy(cleanup) if isinstance(
                    cleanup, dict) else None,
            },
            "files": {
                name: copy.deepcopy(files[(role, stream)])
                for role, stream, name in DIAGNOSTIC_STREAMS
            },
            "startedAt": self.started_at,
            "startedMonotonic": self.started_monotonic,
            "finalizedAt": now(),
            "finalizationCount": self.finalization_count,
        }


def runtime_from_context(context):
    """Create a runtime for tests/direct callers, bound to an existing context."""
    if not isinstance(context, dict):
        raise TypeError("context")
    plan = context.get("resourcePlan") if isinstance(context.get("resourcePlan"), dict) else None
    runtime = InvocationRuntime(
        evidence=context.get("evidence"),
        preflight_id=context.get("preflightId"),
        tag=context.get("tag"),
        protocol_manifest_sha=context.get("protocolManifestSha256"),
        candidate_manifest_sha=context.get("protocolManifestSha256"),
        license_sha=context.get("preflightLicenseSha256"),
        review_sha=context.get("sourceReviewReceiptSha256"),
        claim_sha=context.get("claimSha256"),
        resource_plan=plan,
        resource_plan_sha=context.get("resourcePlanSha256"),
    )
    return runtime


def additive_fields(result):
    """JSON-safe fields added to new receipts/failures; historical records omit them."""
    if not isinstance(result, dict):
        return {}
    return {
        "diagnosticVersion": DIAGNOSTIC_VERSION,
        "processDiagnosticsPath": result.get("path"),
        "processDiagnosticsSha256": result.get("sha256"),
        "diagnostics": result,
    }


def _status_strict_problems(value, evidence):
    """Recompute strict completeness from on-disk primitives, read-only.

    The stored ``outcome.confirmed`` flag is never sufficient: a document that
    merely says the writes succeeded must still prove EOF, known integer
    returncodes, unstruncated streams and exact persisted bytes/digests.
    """
    role_values = value.get("roles") if isinstance(value.get("roles"), dict) else {}
    files = {}
    returncodes = {}
    for role in ROLES:
        record = role_values.get(role) if isinstance(role_values.get(role), dict) else {}
        streams = record.get("streams") if isinstance(record.get("streams"), dict) else {}
        returncodes[role] = (record.get("postCleanupReturncode")
                             if isinstance(record.get("postCleanupReturncode"), dict) else {})
        for stream in STREAMS:
            row = streams.get(stream) if isinstance(streams.get(stream), dict) else {}
            files[(role, stream)] = copy.deepcopy(row)
    problems = _strict_stream_problems(files, returncodes)
    outcome = value.get("outcome") if isinstance(value.get("outcome"), dict) else {}
    if outcome.get("captureError"):
        problems.append("capture-error:" + str(outcome.get("captureError")))
    if outcome.get("confirmed") is not True:
        problems.append("outcome-not-confirmed")
    for role, stream, _name in DIAGNOSTIC_STREAMS:
        row = files.get((role, stream)) or {}
        if row.get("present") is not True or row.get("written") is not True:
            continue
        label = role + "." + stream
        name = row.get("file")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            problems.append("stream-file-name:" + label)
            continue
        path = evidence / name
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError("not-regular")
            persisted = path.read_bytes()
        except OSError:
            problems.append("stream-file-unreadable:" + label)
            continue
        if len(persisted) != row.get("bytes"):
            problems.append("stream-file-bytes:" + label)
        if _sha_bytes(persisted) != row.get("sha256"):
            problems.append("stream-file-digest:" + label)
    return problems


def read_status_summary(evidence, preflight_id, claim=None, claim_sha=None):
    """Read-only, ID-bound summary; never fills, creates or completes a run."""
    evidence = Path(evidence)
    path = evidence / "process-diagnostics.json"
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        return {"state": "unreadable", "detail": "lstat:" + type(error).__name__}
    if os.path.islink(path) or not os.path.isfile(path):
        return {"state": "invalid", "detail": "not-regular"}
    if info.st_size > (1 << 20):
        return {"state": "invalid", "detail": "too-large"}
    try:
        raw = path.read_bytes()
    except OSError as error:
        return {"state": "unreadable", "detail": "read:" + type(error).__name__}
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"state": "invalid", "detail": "json"}
    if type(value) is not dict:
        return {"state": "invalid", "detail": "shape"}
    if (value.get("kind") != PROCESS_DIAGNOSTICS_KIND
            or value.get("diagnosticVersion") != DIAGNOSTIC_VERSION):
        return {"state": "invalid", "detail": "kind-or-version"}
    if value.get("preflightId") != preflight_id:
        return {"state": "cross-id", "detail": "preflight-id-mismatch"}
    if isinstance(claim, dict):
        if value.get("protocolManifestSha256") != claim.get("protocolManifestSha256"):
            return {"state": "cross-id", "detail": "manifest-mismatch"}
        if value.get("resourcePlanSha256") != claim.get("resourcePlanSha256"):
            return {"state": "cross-id", "detail": "plan-mismatch"}
    if claim_sha is not None and value.get("claimSha256") != claim_sha:
        return {"state": "cross-id", "detail": "claim-mismatch"}
    outcome = value.get("outcome") if isinstance(value.get("outcome"), dict) else {}
    strict_problems = _status_strict_problems(value, evidence)
    state = ("present" if outcome.get("confirmed") is True and not strict_problems
             else "incomplete")
    outcome_summary = copy.deepcopy(outcome)
    outcome_summary["confirmed"] = state == "present"
    outcome_summary["incompleteReasons"] = strict_problems
    return {
        "state": state,
        "file": "process-diagnostics.json",
        "sha256": _sha_bytes(raw),
        "bytes": len(raw),
        "diagnosticVersion": DIAGNOSTIC_VERSION,
        "preflightId": value.get("preflightId"),
        "readiness": value.get("readiness"),
        "outcome": outcome_summary,
        "incompleteReasons": strict_problems,
        "roles": {
            role: {
                "pid": (value.get("roles") or {}).get(role, {}).get("pid"),
                "postCleanupReturncode": (value.get("roles") or {}).get(
                    role, {}).get("postCleanupReturncode"),
                "streams": {
                    stream: {
                        "file": ((value.get("roles") or {}).get(role, {}).get(
                            "streams", {}).get(stream, {}) or {}).get("file"),
                        "bytes": ((value.get("roles") or {}).get(role, {}).get(
                            "streams", {}).get(stream, {}) or {}).get("bytes"),
                        "sha256": ((value.get("roles") or {}).get(role, {}).get(
                            "streams", {}).get(stream, {}) or {}).get("sha256"),
                        "truncated": ((value.get("roles") or {}).get(role, {}).get(
                            "streams", {}).get(stream, {}) or {}).get("truncated"),
                    }
                    for stream in STREAMS
                },
            }
            for role in ROLES
        },
    }
