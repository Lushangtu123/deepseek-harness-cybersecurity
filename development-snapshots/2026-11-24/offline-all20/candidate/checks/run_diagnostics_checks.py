#!/usr/bin/env python3
"""Observer early-exit diagnostics checks (version 1).

The suite runs against an explicit ``--root``.  The pre-implementation run uses
the frozen ``baseline/`` source; the post-implementation run uses this
candidate's ``tools/``.  Harmless Python child processes are used for real
exit-code/drain behaviour.  Docker, bpftrace, signals and resource deletions are
recorded shims or explicit no-effect recorders; no real container, observer,
fixture, target, preflight or admission is created.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
sys.path.insert(0, str(ROOT / "checks"))
import regression_lib  # noqa: E402
RESULTS = ROOT / "checks" / "diagnostics-results.json"

ENTRIES = []
TARGET = None
PREFLIGHT = None
GUARD = None
DIAGNOSTICS = None
SHIM_RESOLUTIONS = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(name, passed, **fields):
    entry = {"test": name, "passed": bool(passed), "simulated": True, **fields}
    ENTRIES.append(entry)
    print(("PASS " if passed else "FAIL ") + name)
    return entry


def require_diagnostics():
    if DIAGNOSTICS is None:
        raise AssertionError("preflight_diagnostics module missing from target source")
    return DIAGNOSTICS


def temp_evidence(name):
    TMP.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=name + "-", dir=TMP))


def make_runtime(evidence, **overrides):
    diagnostics = require_diagnostics()
    values = dict(
        evidence=evidence,
        preflight_id="a" * 32,
        tag="b" * 16,
        protocol_manifest_sha="c" * 64,
        candidate_manifest_sha="c" * 64,
        license_sha="d" * 64,
        review_sha="e" * 64,
        claim_sha="f" * 64,
        resource_plan={"tag": "b" * 16, "containerName": "stdlib-cli-preflight-" + "b" * 16},
        resource_plan_sha="1" * 64,
        limit=262144,
    )
    values.update(overrides)
    return diagnostics.InvocationRuntime(**values)


def py_child(code):
    return subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )


def close_child(process):
    if process is None:
        return
    try:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
    except BaseException:  # noqa: BLE001
        pass
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            if stream is not None:
                stream.close()
        except BaseException:  # noqa: BLE001
            pass


def runtime_context(*roles):
    return {
        role: {"identity": {"pid": 1, "pgid": 1, "starttime": 1,
                            "bootId": "synthetic", "groupLeader": True},
               "identityPersisted": True}
        for role in roles
    }


class ModuleSandbox:
    """Point the target preflight module at one checks/tmp sandbox."""

    NAMES = ("ROOT", "PREFLIGHT_ROOT", "EVIDENCE_ROOT", "CLAIMS_ROOT",
             "RECOVERIES_ROOT", "LOCK_PATH", "MANIFEST", "LICENSE", "REVIEW",
             "TOOLS", "PROFILE")

    def __init__(self, box):
        self.box = box
        self.originals = {}
        self.env_originals = {}

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
            self.originals[name] = getattr(PREFLIGHT, name)
            setattr(PREFLIGHT, name, values[name])
        for key, value in box.env().items():
            self.env_originals[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, *_exc):
        for name, value in self.originals.items():
            setattr(PREFLIGHT, name, value)
        for key, value in self.env_originals.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


def sandbox(name, tools_source=None):
    sys.path.insert(0, str(ROOT / "checks"))
    import regression_lib
    box = regression_lib.Sandbox(name, tools_source=tools_source or (TARGET / "tools"))
    SHIM_RESOLUTIONS.update(regression_lib.SHIM_RESOLUTIONS)
    return box


# --------------------------------------------------------------------- tests
def test_observer_compile_error_stderr_exit2():
    require_diagnostics()
    evidence = temp_evidence("diag-compile-error")
    runtime = make_runtime(evidence)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child(
        "import sys\n"
        "sys.stderr.write('synthetic-compile-error: <marker>\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(2)\n"
    )
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        ready = runtime.observer_ready(timeout=3.0)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("client", "observer"))
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        stderr_bytes = (evidence / "diagnostic-observer.stderr").read_bytes()
        checks = {
            "noBegin": ready is None,
            "readinessEarlyExit": document["readiness"]["result"] == "early-exit",
            "observedExitCode2": document["readiness"]["processReturncode"] == 2,
            "observerPostReturncode2":
                document["roles"]["observer"]["postCleanupReturncode"]["returncode"] == 2,
            "markerPreserved": b"synthetic-compile-error: <marker>" in stderr_bytes,
            "stdoutEmpty": (evidence / "diagnostic-observer.stdout").read_bytes() == b"",
            "clientStreamSeparate": (evidence / "diagnostic-client.stdout").is_file(),
            "confirmed": result["confirmed"] is True,
            "shaMatchesFile": result["sha256"] == sha(evidence / "process-diagnostics.json"),
        }
        return record("observer-compile-error-stderr-exit2-before-begin",
                      all(checks.values()), checks=checks,
                      readiness=document["readiness"])
    finally:
        close_child(client)
        close_child(observer)


def test_identity_journal_failure_preserves_handle():
    require_diagnostics()
    evidence = temp_evidence("diag-identity-fail")
    tag = "0123456789abcdef"
    context = PREFLIGHT.new_context(
        evidence, tag, "stdlib-cli-preflight-" + tag, "a" * 32,
        "b" * 64, "c" * 64, "d" * 64, "e" * 64,
    )
    original_write = GUARD.write_new_json_document
    original_identity = GUARD.process_identity
    observed = {"journalCalls": 0, "identityCalls": 0}

    def identity(pid):
        observed["identityCalls"] += 1
        return original_identity(pid)

    def write(path, value):
        if str(path).endswith("process-observer-identity.json"):
            observed["journalCalls"] += 1
            raise OSError("synthetic identity journal failure")
        return original_write(path, value)

    error = None
    try:
        GUARD.process_identity = identity
        GUARD.write_new_json_document = write
        try:
            PREFLIGHT.spawn_process(
                context, "observer",
                [sys.executable, "-u", "-c",
                 "import sys; sys.stdout.write('observer-before-journal\\n'); "
                 "sys.stdout.flush()"],
            )
        except BaseException as raised:  # noqa: BLE001
            error = type(raised).__name__
    finally:
        GUARD.process_identity = original_identity
        GUARD.write_new_json_document = original_write
    runtime = context.get("_diagnostics")
    try:
        result = runtime.finalize(phase="preflight-failure", context=context)
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        checks = {
            "raisedPreflightFailure": error == "PreflightFailure",
            "journalFailureObserved": observed["journalCalls"] == 1,
            "identityRead": observed["identityCalls"] == 1,
            "handleRetained": runtime.roles["observer"]["process"] is not None,
            "drainsRetained": all(runtime.roles["observer"]["drains"].values()),
            "pidKnown": document["roles"]["observer"]["pid"] is not None,
            "identityKnown": isinstance(document["roles"]["observer"]["identity"], dict),
            "identityNotPersisted":
                document["roles"]["observer"]["identityPersisted"] is False,
            "stdoutCaptured":
                b"observer-before-journal" in
                (evidence / "diagnostic-observer.stdout").read_bytes(),
            "exitCodeKnown":
                document["roles"]["observer"]["postCleanupReturncode"]["known"] is True,
        }
        return record("identity-journal-failure-preserves-handle-and-streams",
                      all(checks.values()), checks=checks, error=error,
                      pid=document["roles"]["observer"]["pid"])
    finally:
        close_child(runtime.roles["observer"]["process"] if runtime else None)


def test_eof_with_live_process_is_stream_error():
    require_diagnostics()
    evidence = temp_evidence("diag-eof-alive")
    runtime = make_runtime(evidence)
    observer = py_child(
        "import os,time\n"
        "os.close(1)\n"
        "time.sleep(5)\n"
    )
    try:
        runtime.attach_process("observer", observer, ["python", "eof-alive"])
        ready = runtime.observer_ready(timeout=3.0)
        document_ready = dict(runtime.readiness)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("observer"))
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        checks = {
            "noBegin": ready is None,
            "streamError": document_ready["result"] == "stream-error",
            "stdoutEof": document_ready["stdoutEof"] is True,
            "notCalledEarlyExit": document_ready["result"] != "early-exit",
            "noExitCodeClaim": document_ready["processReturncode"] is None,
            "postReturncodeNull":
                document["roles"]["observer"]["postCleanupReturncode"]["returncode"] is None,
            "stillAliveAfterReadiness": observer.poll() is None,
            "diagnosticsWritten": result["sha256"] is not None,
        }
        return record("eof-with-live-process-is-stream-error-not-exit",
                      all(checks.values()), checks=checks, readiness=document_ready)
    finally:
        close_child(observer)


def test_readiness_timeout_then_deliberate_cleanup():
    require_diagnostics()
    evidence = temp_evidence("diag-timeout")
    runtime = make_runtime(evidence)
    observer = py_child("import time; time.sleep(5)")
    try:
        runtime.attach_process("observer", observer, ["python", "timeout"])
        ready = runtime.observer_ready(timeout=0.3)
        before = runtime.snapshot_poll("observer", "before-deliberate-cleanup")
        observer.send_signal(signal.SIGINT)
        code = observer.wait(timeout=3)
        runtime.note_cleanup_signal("observer", {
            "signal": "SIGINT", "stopped": True, "forced": False,
            "state": "exited", "proof": "wait",
        })
        runtime.finalize(phase="preflight-failure", context=runtime_context("observer"))
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        role = document["roles"]["observer"]
        checks = {
            "noBegin": ready is None,
            "timeout": document["readiness"]["result"] == "timeout",
            "prePollUnknown": before["returncode"] is None and before["known"] is False,
            "cleanupSignalSeparate":
                role["cleanupSignals"] and role["cleanupSignals"][0]["signal"] == "SIGINT",
            "negativeReturncode": role["postCleanupReturncode"]["returncode"] == -signal.SIGINT,
            "actualChildExit": code == -signal.SIGINT,
        }
        return record("readiness-timeout-then-deliberate-cleanup",
                      all(checks.values()), checks=checks)
    finally:
        close_child(observer)


def test_cancellation_finalizes_boundedly():
    require_diagnostics()
    evidence = temp_evidence("diag-cancel")
    runtime = make_runtime(evidence)
    observer = py_child("import time; time.sleep(5)")
    try:
        runtime.attach_process("observer", observer, ["python", "cancel"])
        runtime.set_phase("cancelled")
        started = time.monotonic()
        result = runtime.finalize(phase="cancelled", error="KeyboardInterrupt",
                                  context=runtime_context("observer"))
        interval = time.monotonic() - started
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        checks = {
            "boundedFinalize": interval < 8.0,
            "documentWritten": result["sha256"] is not None,
            "phaseCancelled": document["outcome"]["phase"] == "cancelled",
            "reasonPreserved": document["outcome"]["originalReason"] == "KeyboardInterrupt",
            "returncodeNull":
                document["roles"]["observer"]["postCleanupReturncode"]["returncode"] is None,
            "noSignalSent": document["roles"]["observer"]["cleanupSignals"] == [],
        }
        return record("cancellation-finalizes-bounded-diagnostics",
                      all(checks.values()), checks=checks, intervalSeconds=round(interval, 3))
    finally:
        close_child(observer)


def test_success_path_separates_diagnostics_and_raw():
    require_diagnostics()
    box = sandbox("diag-success")
    try:
        box.write_preflight_license()
        result = box.preflight(timeout=180)
        evidence = box.preflight_evidence()
        receipt = json.loads((evidence / "preflight-receipt.json").read_text())
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        raw = (evidence / "observer.raw").read_bytes()
        diagnostic_raw = (evidence / "diagnostic-observer.stdout").read_bytes()
        client_stdout = (evidence / "diagnostic-client.stdout").read_bytes()
        checks = {
            "preflightExitZero": result.returncode == 0,
            "stateAccepted": receipt.get("state") == "accepted",
            "diagnosticsPresent": (evidence / "process-diagnostics.json").is_file(),
            "confirmed": receipt.get("diagnostics", {}).get("confirmed") is True,
            "receiptDigestBindsFile":
                receipt.get("processDiagnosticsSha256") == sha(evidence / "process-diagnostics.json"),
            "diagnosticVersion": receipt.get("diagnosticVersion") == 1,
            "rawStillObserverBytes": raw.startswith(b"BEGIN "),
            "diagnosticSeparateFile": diagnostic_raw == raw,
            "clientAndObserverSeparate": client_stdout != diagnostic_raw,
            "clientConfigSeen": b"PREFLIGHT-CONFIG " in client_stdout,
            "readinessReady": document["readiness"]["result"] == "ready",
            "milestonesObserved": all(
                document["lifecycle"][name]["observed"]
                for name in ("configAcquired", "observerReadyObserved",
                             "goSendAttempted", "goFlushCompleted", "clientExited")
            ),
            "controllerStatus": isinstance(document["controller"].get("effectiveUid"), int),
            "bpftracePathResolved": str(document["bpftrace"].get("resolvedPath", "")).endswith(
                "checks/shims/bpftrace"),
            "bpftraceNotSpawnedForVersion":
                document["bpftrace"].get("probeSpawned") is False,
            "fileDigestsMatch": all(
                row["sha256"] == sha(evidence / row["file"])
                for row in document["files"].values()
            ),
        }
        return record("success-path-separates-diagnostics-and-observer-raw",
                      all(checks.values()), checks=checks,
                      readiness=document["readiness"])
    finally:
        regression_lib.retire_sandbox(box.path)


def test_truncates_at_256k_and_is_incomplete():
    require_diagnostics()
    evidence = temp_evidence("diag-truncate")
    runtime = make_runtime(evidence)
    observer = py_child(
        "import sys\n"
        "sys.stdout.write('X' * 300000)\n"
        "sys.stdout.flush()\n"
    )
    try:
        runtime.attach_process("observer", observer, ["python", "truncate"])
        observer.wait(timeout=10)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("observer"))
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        row = document["roles"]["observer"]["streams"]["stdout"]
        payload = (evidence / "diagnostic-observer.stdout").read_bytes()
        checks = {
            "boundedAt256k": len(payload) == 262144,
            "metadataBytes": row["bytes"] == 262144,
            "truncatedFlag": row["truncated"] is True,
            "shaOfBoundedPrefix": row["sha256"] == hashlib.sha256(payload).hexdigest(),
            "notConfirmed": result["confirmed"] is False,
            "anyTruncated": result["anyTruncated"] is True,
            "diagnosticsStillWritten": result["sha256"] is not None,
        }
        return record("output-over-256k-is-truncated-and-not-confirmed",
                      all(checks.values()), checks=checks)
    finally:
        close_child(observer)


class BrokenStream:
    def fileno(self):
        raise OSError("synthetic-stream-read-failure")


class BrokenProcess:
    pid = 424242

    def poll(self):
        return None

    stdout = BrokenStream()
    stderr = BrokenStream()


def test_stream_read_failure_is_captured():
    require_diagnostics()
    evidence = temp_evidence("diag-read-failure")
    runtime = make_runtime(evidence)
    runtime.attach_process("observer", BrokenProcess(), ["broken"])
    result = runtime.finalize(phase="preflight-failure", context=runtime_context("observer"))
    document = json.loads((evidence / "process-diagnostics.json").read_text())
    row = document["roles"]["observer"]["streams"]["stdout"]
    checks = {
        "errorRecorded": row["error"] == "OSError",
        "notCompleted": row["completed"] is False,
        "notConfirmed": result["confirmed"] is False,
        "captureErrorPresent": bool(result["captureError"]),
        "metadataWritten": result["sha256"] is not None,
    }
    return record("stream-read-failure-is-captured", all(checks.values()), checks=checks)


def test_diagnostic_write_failure_is_incomplete():
    require_diagnostics()
    evidence = temp_evidence("diag-write-failure")
    runtime = make_runtime(evidence)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import sys; sys.exit(0)")
    original = GUARD.write_new_bytes
    calls = {"failed": 0}

    def write(path, payload):
        if Path(path).name == "diagnostic-observer.stdout":
            calls["failed"] += 1
            raise OSError("synthetic-diagnostic-write")
        return original(path, payload)

    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        GUARD.write_new_bytes = write
        first = runtime.finalize(phase="preflight-failure",
                                 context=runtime_context("client", "observer"))
        second = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("client", "observer"))
    finally:
        GUARD.write_new_bytes = original
        close_child(client)
        close_child(observer)
    checks = {
        "writeFailureRecorded": calls["failed"] == 1,
        "notConfirmed": first["confirmed"] is False,
        "captureError": "synthetic" in (first["captureError"] or "")
                        or "OSError" in (first["captureError"] or ""),
        "metadataWritten": first["sha256"] is not None,
        "noDuplicateWrite": calls["failed"] == 1,
        "sameResult": first["sha256"] == second["sha256"],
        "noStreamFile": not (evidence / "diagnostic-observer.stdout").exists(),
    }
    return record("diagnostic-write-failure-is-incomplete", all(checks.values()),
                  checks=checks, calls=calls)


def test_diagnostic_fsync_failure_is_incomplete():
    require_diagnostics()
    evidence = temp_evidence("diag-fsync-failure")
    runtime = make_runtime(evidence)
    observer = py_child("import sys; sys.exit(0)")
    original_fsync = GUARD._fsync_directory
    original_write = GUARD.write_new_bytes
    calls = {"fsync": 0}

    def fail_fsync(path):
        calls["fsync"] += 1
        raise OSError("synthetic-directory-fsync")

    try:
        runtime.attach_process("observer", observer, ["python", "observer"])
        observer.wait(timeout=3)
        GUARD._fsync_directory = fail_fsync
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("observer"))
    finally:
        GUARD._fsync_directory = original_fsync
        GUARD.write_new_bytes = original_write
        close_child(observer)
    document = None
    if (evidence / "process-diagnostics.json").is_file():
        document = json.loads((evidence / "process-diagnostics.json").read_text())
    checks = {
        "fsyncAttempted": calls["fsync"] > 0,
        "notConfirmed": result["confirmed"] is False,
        "streamNotMarkedWritten":
            result["files"]["diagnostic-observer.stdout"]["written"] is False,
        "diagnosticsDigestUnknown": result["sha256"] is None,
        "captureErrorPresent": bool(result["captureError"]),
        "onDiskDocumentNotConfirmed":
            document is None or document["outcome"]["confirmed"] is False,
    }
    return record("diagnostic-fsync-failure-is-incomplete", all(checks.values()),
                  checks=checks, calls=calls)


def test_stale_cross_id_not_adopted():
    require_diagnostics()
    evidence = temp_evidence("diag-cross-id")
    stale_path = evidence / "process-diagnostics.json"
    stale = {
        "kind": "zero-target-preflight-process-diagnostics",
        "diagnosticVersion": 1,
        "preflightId": "9" * 32,
        "state": "complete",
        "confirmed": True,
    }
    stale_bytes = json.dumps(stale, sort_keys=True, indent=1).encode() + b"\n"
    stale_path.write_bytes(stale_bytes)
    runtime = make_runtime(evidence)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import sys; sys.exit(0)")
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("client", "observer"))
        summary = DIAGNOSTICS.read_status_summary(evidence, "a" * 32)
        checks = {
            "staleBytesUnchanged": stale_path.read_bytes() == stale_bytes,
            "notConfirmed": result["confirmed"] is False,
            "exclusiveWriteFailed": "FileExistsError" in (result["captureError"] or ""),
            "statusCrossId": summary.get("state") == "cross-id",
            "statusNotPresent": summary.get("state") != "present",
        }
        return record("stale-cross-id-diagnostics-not-adopted", all(checks.values()),
                      checks=checks, status=summary.get("state"))
    finally:
        close_child(client)
        close_child(observer)


def test_finalization_twice_no_duplicate_writes():
    require_diagnostics()
    evidence = temp_evidence("diag-finalize-twice")
    runtime = make_runtime(evidence)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import sys; sys.exit(0)")
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        first = runtime.finalize(phase="success", context=runtime_context("client", "observer"))
        before = {path.name: (sha(path), path.stat().st_mtime_ns)
                  for path in evidence.iterdir() if path.is_file()}
        second = runtime.finalize(phase="success", context=runtime_context("client", "observer"))
        after = {path.name: (sha(path), path.stat().st_mtime_ns)
                 for path in evidence.iterdir() if path.is_file()}
        checks = {
            "sameDigest": first["sha256"] == second["sha256"],
            "sameFiles": before == after,
            "oneFinalization": second["finalizationCount"] == 1,
            "diagnosticCount": len([name for name in after if name.startswith("diagnostic-")]) == 4,
        }
        return record("finalization-twice-no-duplicate-writes",
                      all(checks.values()), checks=checks)
    finally:
        close_child(client)
        close_child(observer)


def test_unknown_returncode_stays_null():
    require_diagnostics()
    evidence = temp_evidence("diag-unknown-rc")
    runtime = make_runtime(evidence)
    observer = py_child("import time; time.sleep(5)")
    try:
        runtime.attach_process("observer", observer, ["python", "alive"])
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("observer"))
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        row = document["roles"]["observer"]["postCleanupReturncode"]
        checks = {
            "returncodeNull": row["returncode"] is None,
            "notZero": row["returncode"] != 0,
            "knownFalse": row["known"] is False,
            "prePollNull": document["roles"]["observer"]["preCleanupPoll"]["returncode"] is None,
            "stillAlive": observer.poll() is None,
            "diagnosticsWritten": result["sha256"] is not None,
        }
        return record("cannot-determine-returncode-remains-null-not-zero",
                      all(checks.values()), checks=checks, returncode=row)
    finally:
        close_child(observer)


def test_poll_and_cleanup_signal_are_separate():
    require_diagnostics()
    evidence = temp_evidence("diag-poll-signal")
    runtime = make_runtime(evidence)
    exited = py_child("import sys; sys.exit(7)")
    try:
        runtime.attach_process("observer", exited, ["python", "exit7"])
        exited.wait(timeout=3)
        pre = runtime.snapshot_poll("observer", "before-cleanup")
        runtime.finalize(phase="preflight-failure", context=runtime_context("observer"))
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        first = document["roles"]["observer"]
        checks = {
            "prePollSaw7": pre["returncode"] == 7,
            "noCleanupSignal": first["cleanupSignals"] == [],
            "postReturncode7": first["postCleanupReturncode"]["returncode"] == 7,
        }
    finally:
        close_child(exited)
    evidence2 = temp_evidence("diag-poll-signal2")
    runtime2 = make_runtime(evidence2)
    alive = py_child("import time; time.sleep(5)")
    try:
        runtime2.attach_process("observer", alive, ["python", "alive"])
        pre2 = runtime2.snapshot_poll("observer", "before-cleanup")
        alive.send_signal(signal.SIGTERM)
        code = alive.wait(timeout=3)
        runtime2.note_cleanup_signal("observer", {
            "signal": "SIGTERM", "stopped": True, "forced": True,
            "state": "exited", "proof": "wait",
        })
        runtime2.finalize(phase="preflight-failure", context=runtime_context("observer"))
        document2 = json.loads((evidence2 / "process-diagnostics.json").read_text())
        second = document2["roles"]["observer"]
        checks.update({
            "prePollAliveUnknown": pre2["returncode"] is None,
            "cleanupSignalTerm": second["cleanupSignals"][0]["signal"] == "SIGTERM",
            "negativeTerm": second["postCleanupReturncode"]["returncode"] == -signal.SIGTERM,
            "actualTerm": code == -signal.SIGTERM,
        })
    finally:
        close_child(alive)
    return record("pre-cleanup-poll-separate-from-cleanup-signal",
                  all(checks.values()), checks=checks)


def test_finalize_makes_no_forbidden_calls():
    require_diagnostics()
    evidence = temp_evidence("diag-no-forbidden")
    runtime = make_runtime(evidence)
    observer = py_child("import sys; sys.exit(0)")
    counters = {"stopGroup": 0, "docker": 0, "removeContainer": 0,
                "cleanupStage": 0, "killpg": 0, "kill": 0, "popen": 0}
    originals = {
        "stop_group": GUARD.stop_group,
        "docker": GUARD.docker,
        "remove_container_verified": GUARD.remove_container_verified,
        "cleanup_stage": GUARD.cleanup_stage,
        "killpg": os.killpg,
        "kill": os.kill,
        "popen": subprocess.Popen,
    }

    def counter(name, value=None):
        def call(*_args, **_kwargs):
            counters[name] += 1
            return value
        return call

    try:
        runtime.attach_process("observer", observer, ["python", "noop"])
        observer.wait(timeout=3)
        GUARD.stop_group = counter("stopGroup", {"stopped": False})
        GUARD.docker = counter("docker", None)
        GUARD.remove_container_verified = counter("removeContainer", {"removed": False})
        GUARD.cleanup_stage = counter("cleanupStage", {"removed": False})
        os.killpg = counter("killpg", None)
        os.kill = counter("kill", None)
        subprocess.Popen = counter("popen", None)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("observer"))
    finally:
        GUARD.stop_group = originals["stop_group"]
        GUARD.docker = originals["docker"]
        GUARD.remove_container_verified = originals["remove_container_verified"]
        GUARD.cleanup_stage = originals["cleanup_stage"]
        os.killpg = originals["killpg"]
        os.kill = originals["kill"]
        subprocess.Popen = originals["popen"]
        close_child(observer)
    checks = {
        "noForbiddenCalls": all(value == 0 for value in counters.values()),
        "diagnosticsStillWritten": result["sha256"] is not None,
    }
    return record("finalize-makes-no-signal-resource-or-spawn-calls",
                  all(checks.values()), checks=checks, counters=counters)


def test_status_exposes_diagnostics_read_only():
    require_diagnostics()
    box = sandbox("diag-status")
    try:
        box.write_preflight_license()
        preflight_result = box.preflight(timeout=180)
        before = {path.name: sha(path) for path in box.preflight_evidence().iterdir()
                  if path.is_file()}
        status = box.status(box.preflight_id)
        payload = json.loads(status.stdout.strip().splitlines()[-1])
        after = {path.name: sha(path) for path in box.preflight_evidence().iterdir()
                 if path.is_file()}
        checks = {
            "preflightExitZero": preflight_result.returncode == 0,
            "statusExitZero": status.returncode == 0,
            "legacyCompleted": payload.get("state") == "completed",
            "diagnosticsPresent": payload.get("diagnostics", {}).get("state") == "present",
            "diagnosticShaMatches":
                payload.get("diagnostics", {}).get("sha256")
                == sha(box.preflight_evidence() / "process-diagnostics.json"),
            "readinessReady":
                payload.get("diagnostics", {}).get("readiness", {}).get("result") == "ready",
            "noFileChanges": before == after,
        }
        return record("status-exposes-diagnostics-read-only", all(checks.values()),
                      checks=checks)
    finally:
        regression_lib.retire_sandbox(box.path)


def test_recover_does_not_replay_or_rewrite_diagnostics():
    require_diagnostics()
    box = sandbox("diag-recover")
    try:
        box.write_preflight_license()
        box.preflight(timeout=180)
        evidence = box.preflight_evidence()
        diagnostic_sha = sha(evidence / "process-diagnostics.json")
        raw_sha = sha(evidence / "observer.raw")
        diagnostic_names = {path.name for path in evidence.iterdir()
                            if path.name.startswith("diagnostic-")}
        receipts = []
        for _index in range(2):
            run = subprocess.run(
                [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
                 "recover", "--preflight-id", box.preflight_id],
                capture_output=True, text=True, env=box.env(), timeout=60,
            )
            receipts.append(run)
        checks = {
            "recoverExitZero": all(item.returncode == 0 for item in receipts),
            "diagnosticsUnchanged": sha(evidence / "process-diagnostics.json") == diagnostic_sha,
            "rawUnchanged": sha(evidence / "observer.raw") == raw_sha,
            "noNewDiagnosticFiles":
                {path.name for path in evidence.iterdir()
                 if path.name.startswith("diagnostic-")} == diagnostic_names,
            "noDiagnosticsReplayField":
                "processDiagnostics" not in "".join(item.stdout for item in receipts),
        }
        return record("recover-does-not-replay-or-rewrite-diagnostics",
                      all(checks.values()), checks=checks)
    finally:
        regression_lib.retire_sandbox(box.path)


def test_diagnostic_failure_keeps_stage_and_preserves_reason():
    require_diagnostics()
    box = sandbox("diag-failure-stage")
    try:
        box.write_preflight_license()
        original = GUARD.write_new_bytes

        def write(path, payload):
            if Path(path).name == "diagnostic-client.stdout":
                raise OSError("synthetic-diagnostic-write")
            return original(path, payload)

        setattr(GUARD, "write_new_bytes", write)
        os.environ["SCE_OBSERVER_COMPILE_ERROR"] = "1"
        try:
            with ModuleSandbox(box):
                code = PREFLIGHT.preflight()
        finally:
            os.environ.pop("SCE_OBSERVER_COMPILE_ERROR", None)
            setattr(GUARD, "write_new_bytes", original)
        evidence = box.preflight_evidence()
        failure = json.loads((evidence / "failure.json").read_text())
        diagnostics = failure.get("diagnostics") or {}
        stage_dirs = [path for path in evidence.iterdir()
                      if path.is_dir() and path.name.startswith("stage-")]
        checks = {
            "exit79": code == 79,
            "originalReasonPreserved": failure.get("reason") == "preflight-observer-not-armed",
            "captureErrorSeparate": bool(diagnostics.get("captureError")),
            "diagnosticsNotConfirmed": diagnostics.get("confirmed") is False,
            "noReceipt": not (evidence / "preflight-receipt.json").exists(),
            "cleanupNotConfirmed": (failure.get("cleanup") or {}).get("confirmed") is False,
            "stageRetained": bool(stage_dirs),
            "stagePersistenceFailed":
                ((failure.get("cleanup") or {}).get("stage") or {}).get("state")
                == "persistence-failed",
            "digestFieldPresent": "processDiagnosticsSha256" in failure,
        }
        return record("diagnostic-failure-keeps-stage-and-preserves-original-reason",
                      all(checks.values()), checks=checks,
                      reason=failure.get("reason"),
                      captureError=diagnostics.get("captureError"))
    finally:
        regression_lib.retire_sandbox(box.path)


def test_metadata_binds_manifest_claim_plan_and_digests():
    require_diagnostics()
    evidence = temp_evidence("diag-binding")
    runtime = make_runtime(evidence)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import sys; sys.exit(0)")
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        result = runtime.finalize(phase="success",
                                  context=runtime_context("client", "observer"))
        document = json.loads((evidence / "process-diagnostics.json").read_text())
        checks = {
            "kind": document["kind"] == "zero-target-preflight-process-diagnostics",
            "diagnosticVersion": document["diagnosticVersion"] == 1,
            "protocolRevision": document["protocolRevision"] == 3,
            "preflightId": document["preflightId"] == "a" * 32,
            "manifestSha": document["protocolManifestSha256"] == "c" * 64,
            "candidateManifestSha": document["candidateManifestSha256"] == "c" * 64,
            "claimSha": document["claimSha256"] == "f" * 64,
            "planSha": document["resourcePlanSha256"] == "1" * 64,
            "planBound": document["resourcePlan"]["tag"] == "b" * 16,
            "fileDigests": all(
                row["sha256"] == sha(evidence / row["file"])
                for row in document["files"].values()
            ),
            "bytesMatch": all(
                row["bytes"] == (evidence / row["file"]).stat().st_size
                for row in document["files"].values()
            ),
            "resultDigest": result["sha256"] == sha(evidence / "process-diagnostics.json"),
        }
        return record("diagnostic-metadata-binds-manifest-claim-plan-and-digests",
                      all(checks.values()), checks=checks)
    finally:
        close_child(client)
        close_child(observer)


def test_cleanup_branch_visits_and_zero_real_boundaries():
    require_diagnostics()
    evidence = temp_evidence("diag-cleanup-branches")
    runtime = make_runtime(evidence)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import sys; sys.exit(0)")
    client.wait(timeout=3)
    observer.wait(timeout=3)
    runtime.attach_process("client", client, ["python", "client"])
    runtime.attach_process("observer", observer, ["python", "observer"])
    counters = {"process": 0, "container": 0, "stage": 0,
                "stopGroup": 0, "docker": 0, "remove": 0,
                "killpg": 0, "kill": 0}
    originals = {
        "process": PREFLIGHT._process_cleanup,
        "container": PREFLIGHT._cleanup_container,
        "stage": PREFLIGHT._cleanup_stage,
        "stopGroup": GUARD.stop_group,
        "docker": GUARD.docker,
        "remove": GUARD.remove_container_verified,
        "killpg": os.killpg,
        "kill": os.kill,
    }

    def process(record):
        counters["process"] += 1
        role = (record or {}).get("role") if isinstance(record, dict) else None
        return {"state": "exited", "proof": "recorder-no-effect", "role": role}

    def container(_context):
        counters["container"] += 1
        return {"removed": True, "state": "never-created"}

    def stage(_context, _resources_clear):
        counters["stage"] += 1
        return {"removed": True, "lstatAfter": "absent", "state": "absent"}

    def bump(name, value):
        def call(*_args, **_kwargs):
            counters[name] += 1
            return value
        return call

    context = {
        "evidence": evidence,
        "preflightId": "a" * 32,
        "tag": "b" * 16,
        "protocolManifestSha256": "c" * 64,
        "preflightLicenseSha256": "d" * 64,
        "sourceReviewReceiptSha256": "e" * 64,
        "claimSha256": "f" * 64,
        "resourcePlan": {"tag": "b" * 16},
        "resourcePlanSha256": "1" * 64,
        "client": {"role": "client", "spawnState": "started", "identity": None,
                   "identityPersisted": False},
        "observer": {"role": "observer", "spawnState": "started", "identity": None,
                     "identityPersisted": False},
        "container": {"createState": "not-attempted"},
        "stageDir": str(evidence / "stage-synthetic"),
        "stageIdentity": None,
        "stageBuildState": "not-created",
        "persistFailure": None,
        "journals": {},
        "_diagnostics": runtime,
    }
    try:
        PREFLIGHT._process_cleanup = process
        PREFLIGHT._cleanup_container = container
        PREFLIGHT._cleanup_stage = stage
        GUARD.stop_group = bump("stopGroup", {"stopped": False})
        GUARD.docker = bump("docker", None)
        GUARD.remove_container_verified = bump("remove", {"removed": False})
        os.killpg = bump("killpg", None)
        os.kill = bump("kill", None)
        result = PREFLIGHT.cleanup_resources(context)
    finally:
        PREFLIGHT._process_cleanup = originals["process"]
        PREFLIGHT._cleanup_container = originals["container"]
        PREFLIGHT._cleanup_stage = originals["stage"]
        GUARD.stop_group = originals["stopGroup"]
        GUARD.docker = originals["docker"]
        GUARD.remove_container_verified = originals["remove"]
        os.killpg = originals["killpg"]
        os.kill = originals["kill"]
        close_child(client)
        close_child(observer)
    checks = {
        "processBranchesVisitedTwice": counters["process"] == 2,
        "containerBranchVisitedOnce": counters["container"] == 1,
        "stageBranchVisitedOnce": counters["stage"] == 1,
        "zeroForbiddenCalls": all(counters[name] == 0 for name in
                                  ("stopGroup", "docker", "remove", "killpg", "kill")),
        "cleanupConfirmed": result["confirmed"] is True,
        "diagnosticsConfirmed": (result.get("diagnostics") or {}).get("confirmed") is True,
        "diagnosticsRecorded": (evidence / "process-diagnostics.json").is_file(),
    }
    return record("cleanup-branch-visits-and-zero-real-boundaries",
                  all(checks.values()), checks=checks, counters=counters)


SCENARIOS = [
    test_observer_compile_error_stderr_exit2,
    test_identity_journal_failure_preserves_handle,
    test_eof_with_live_process_is_stream_error,
    test_readiness_timeout_then_deliberate_cleanup,
    test_cancellation_finalizes_boundedly,
    test_success_path_separates_diagnostics_and_raw,
    test_truncates_at_256k_and_is_incomplete,
    test_stream_read_failure_is_captured,
    test_diagnostic_write_failure_is_incomplete,
    test_diagnostic_fsync_failure_is_incomplete,
    test_stale_cross_id_not_adopted,
    test_finalization_twice_no_duplicate_writes,
    test_unknown_returncode_stays_null,
    test_poll_and_cleanup_signal_are_separate,
    test_finalize_makes_no_forbidden_calls,
    test_status_exposes_diagnostics_read_only,
    test_recover_does_not_replay_or_rewrite_diagnostics,
    test_diagnostic_failure_keeps_stage_and_preserves_reason,
    test_metadata_binds_manifest_claim_plan_and_digests,
    test_cleanup_branch_visits_and_zero_real_boundaries,
]


def main(argv=None):
    global TARGET, PREFLIGHT, GUARD, DIAGNOSTICS
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT),
                        help="target candidate root (contains tools/)")
    parser.add_argument("--out", default=str(RESULTS))
    args = parser.parse_args(argv)
    TARGET = Path(args.root).resolve()
    tools = TARGET / "tools"
    sys.path.insert(0, str(tools))
    sys.path.insert(0, str(ROOT / "checks"))
    import zero_target_preflight as preflight_module
    import resource_guard as guard_module
    PREFLIGHT = preflight_module
    GUARD = guard_module
    try:
        import preflight_diagnostics as diagnostics_module
        DIAGNOSTICS = diagnostics_module
    except ImportError:
        DIAGNOSTICS = None
    TMP.mkdir(parents=True, exist_ok=True)
    source_hashes = {}
    for path in sorted(tools.glob("*")):
        if path.is_file():
            source_hashes[str(path.relative_to(TARGET))] = sha(path)
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started_monotonic = time.monotonic()
    failures = []
    for scenario in SCENARIOS:
        try:
            entry = scenario()
        except BaseException as error:  # noqa: BLE001
            entry = record(scenario.__name__ + "-exception", False,
                           error=type(error).__name__ + ":" + str(error)[:600],
                           trace=traceback.format_exc()[-4000:])
        if not entry.get("passed"):
            failures.append(entry["test"])
    finished_monotonic = time.monotonic()
    after_hashes = {str(path.relative_to(TARGET)): sha(path)
                    for path in sorted(tools.glob("*")) if path.is_file()}
    payload = {
        "kind": "observer-early-exit-diagnostics-checks",
        "version": 1,
        "diagnosticVersion": 1,
        "protocolRevision": 3,
        "simulated": True,
        "realContainers": 0,
        "realBpftrace": 0,
        "realTargets": 0,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "preflightExecuted": False,
        "admissionIssued": False,
        "targetRoot": str(TARGET),
        "diagnosticsModulePresent": DIAGNOSTICS is not None,
        "shimResolution": dict(SHIM_RESOLUTIONS),
        "startedUtc": started_utc,
        "startedMonotonic": started_monotonic,
        "finishedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "finishedMonotonic": finished_monotonic,
        "intervalSeconds": round(finished_monotonic - started_monotonic, 6),
        "sourceSha256Before": source_hashes,
        "sourceSha256After": after_hashes,
        "sourceUnchanged": source_hashes == after_hashes,
        "results": ENTRIES,
        "passed": sum(1 for item in ENTRIES if item["passed"]),
        "total": len(ENTRIES),
        "failed": failures,
        "note": "Local Python child processes only; Docker/bpftrace are recorded "
                "shims. No real container, observer, target, preflight or admission.",
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                           encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": failures,
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
