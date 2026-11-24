#!/usr/bin/env python3
"""Focused bounded-repair checks for the observer diagnostic strictness fix.

This suite is intentionally separate from the twenty version-1 diagnostics
checks: those were already run against the module-absent baseline and must not
be rerun as a substitute for new RED evidence.  Every scenario here uses a
fixed harmless Python child process, a recorded shim or an in-process no-effect
recorder.  No real Docker, bpftrace, fixture, target, preflight or admission is
executed.

RED evidence is produced by running this same file with ``--root baseline``;
the candidate run uses the normal root.  Expected new fields
(``incompleteReasons``, persisted byte/digest metadata) are read with ``.get``
so the baseline run records exact failed assertions instead of hiding a
regression behind an exception.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
sys.path.insert(0, str(ROOT / "checks"))
import regression_lib  # noqa: E402
RESULTS = ROOT / "checks" / "repair-results.json"

ENTRIES = []
TARGET = None
PREFLIGHT = None
GUARD = None
DIAGNOSTICS = None
PARSER = None
SHIM_RESOLUTIONS = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(name, passed, **fields):
    entry = {"test": name, "passed": bool(passed), "simulated": True, **fields}
    ENTRIES.append(entry)
    print(("PASS " if passed else "FAIL ") + name)
    return entry


def require(module, name):
    if module is None:
        raise AssertionError(name + " missing from target source")
    return module


def temp_evidence(name):
    TMP.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=name + "-", dir=TMP))


def make_runtime(evidence, **overrides):
    diagnostics = require(DIAGNOSTICS, "preflight_diagnostics")
    values = dict(
        evidence=evidence,
        preflight_id="a" * 32,
        tag="b" * 16,
        protocol_manifest_sha="c" * 64,
        candidate_manifest_sha="c" * 64,
        license_sha="d" * 64,
        review_sha="e" * 64,
        claim_sha="f" * 64,
        resource_plan={"tag": "b" * 16,
                       "containerName": "stdlib-cli-preflight-" + "b" * 16},
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


def reasons(result):
    return list(result.get("incompleteReasons") or [])


def read_document(evidence):
    return json.loads((evidence / "process-diagnostics.json").read_text())


def all_stream_rows(document):
    roles = document.get("roles") or {}
    return [(role, stream, ((roles.get(role) or {}).get("streams") or {}).get(stream) or {})
            for role in ("client", "observer")
            for stream in ("stdout", "stderr")]


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


def sandbox(name):
    sys.path.insert(0, str(ROOT / "checks"))
    import regression_lib
    box = regression_lib.Sandbox(name, tools_source=(TARGET / "tools"))
    SHIM_RESOLUTIONS.update(regression_lib.SHIM_RESOLUTIONS)
    return box


# --------------------------------------------------------------------- tests
def test_unfinished_stdout_stderr_is_incomplete():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-unfinished")
    runtime = make_runtime(evidence, finish_timeout=0.15, wait_timeout=0.1)
    client = py_child("import time; time.sleep(3)")
    observer = py_child("import time; time.sleep(3)")
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        started = time.monotonic()
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("client", "observer"))
        interval = time.monotonic() - started
        document = read_document(evidence)
        rows = all_stream_rows(document)
        summary_rows = result.get("files") or {}
        checks = {
            "notConfirmed": result.get("confirmed") is False,
            "stateIncomplete": result.get("state") == "incomplete",
            "captureIncomplete": result.get("captureComplete") is False,
            "persistedButNotCaptured": result.get("persistenceComplete") is True,
            "documentNotConfirmed": document["outcome"].get("confirmed") is False,
            "documentCaptureIncomplete": document["outcome"].get("captureComplete") is False,
            "sameStrictPredicate":
                document["outcome"].get("incompleteReasons")
                == result.get("incompleteReasons"),
            "allAttachedStreamsPresent":
                all(row.get("present") is True for _role, _stream, row in rows),
            "allStreamsNotCompleted":
                all(row.get("completed") is False for _role, _stream, row in rows),
            "allStreamsNotEof":
                all(row.get("eof") is False for _role, _stream, row in rows),
            "noFabricatedBytes":
                all(row.get("bytes") == 0 for _role, _stream, row in rows),
            "returncodesUnknownNull":
                document["roles"]["client"]["postCleanupReturncode"].get("returncode") is None
                and document["roles"]["observer"]["postCleanupReturncode"].get("returncode") is None,
            "drainDeadlineRecorded": any(
                value.startswith("capture-error:drain-deadline:")
                for value in reasons(result)),
            "streamNotEofReasons": (
                "stream-not-eof:client.stdout" in reasons(result)
                and "stream-not-eof:observer.stderr" in reasons(result)),
            "returncodeReasons": (
                "returncode-unknown:client" in reasons(result)
                and "returncode-unknown:observer" in reasons(result)),
            "noSignalSent":
                document["roles"]["client"]["cleanupSignals"] == []
                and document["roles"]["observer"]["cleanupSignals"] == [],
            "boundedFinalize": interval < 8.0,
            "summaryRowsUseSameMetadata":
                summary_rows.get("diagnostic-client.stdout", {}).get("completed") is False
                and summary_rows.get("diagnostic-observer.stderr", {}).get("eof") is False,
            "statusIncomplete":
                (DIAGNOSTICS.read_status_summary(evidence, "a" * 32) or {}).get("state")
                == "incomplete",
        }
        return record("unfinished-stdout-stderr-is-incomplete",
                      all(checks.values()), checks=checks,
                      incompleteReasons=reasons(result),
                      intervalSeconds=round(interval, 3))
    finally:
        close_child(client)
        close_child(observer)


def test_eof_with_alive_child_is_incomplete():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-eof-alive")
    runtime = make_runtime(evidence, finish_timeout=0.2, wait_timeout=0.1)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child(
        "import os,time\n"
        "os.close(1)\n"
        "time.sleep(3)\n"
    )
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "eof-alive"])
        client.wait(timeout=3)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("client", "observer"))
        document = read_document(evidence)
        client_streams = document["roles"]["client"]["streams"]
        observer_streams = document["roles"]["observer"]["streams"]
        checks = {
            "noBeginClaim": document["readiness"].get("result") == "unknown",
            "clientEofComplete":
                client_streams["stdout"].get("completed") is True
                and client_streams["stdout"].get("eof") is True,
            "observedStdoutEof":
                observer_streams["stdout"].get("completed") is True
                and observer_streams["stdout"].get("eof") is True,
            "observedStderrNotEof":
                observer_streams["stderr"].get("completed") is False
                and observer_streams["stderr"].get("eof") is False,
            "notConfirmed": result.get("confirmed") is False,
            "stateIncomplete": result.get("state") == "incomplete",
            "streamNotEofReason": "stream-not-eof:observer.stderr" in reasons(result),
            "returncodeUnknownReason": "returncode-unknown:observer" in reasons(result),
            "observerReturncodeNull":
                document["roles"]["observer"]["postCleanupReturncode"].get("returncode")
                is None,
            "observerReturncodeUnknown":
                document["roles"]["observer"]["postCleanupReturncode"].get("known") is False,
            "clientReturncodeKnown":
                document["roles"]["client"]["postCleanupReturncode"].get("returncode") == 0,
            "streamEofIsNotExitProof": observer.poll() is None,
            "statusIncomplete":
                (DIAGNOSTICS.read_status_summary(evidence, "a" * 32) or {}).get("state")
                == "incomplete",
        }
        return record("eof-with-alive-child-is-incomplete",
                      all(checks.values()), checks=checks,
                      incompleteReasons=reasons(result))
    finally:
        close_child(client)
        close_child(observer)


def test_known_vs_unknown_returncode():
    require(DIAGNOSTICS, "preflight_diagnostics")
    known_evidence = temp_evidence("repair-known-rc")
    known = make_runtime(known_evidence, finish_timeout=1.0, wait_timeout=0.2)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import sys; sys.exit(7)")
    try:
        known.attach_process("client", client, ["python", "client"])
        known.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        known_result = known.finalize(phase="success",
                                      context=runtime_context("client", "observer"))
        known_document = read_document(known_evidence)
        known_status = DIAGNOSTICS.read_status_summary(known_evidence, "a" * 32) or {}
    finally:
        close_child(client)
        close_child(observer)

    unknown_evidence = temp_evidence("repair-unknown-rc")
    unknown = make_runtime(unknown_evidence, finish_timeout=0.2, wait_timeout=0.1)
    client2 = py_child("import sys; sys.exit(0)")
    observer2 = py_child("import time; time.sleep(3)")
    try:
        unknown.attach_process("client", client2, ["python", "client"])
        unknown.attach_process("observer", observer2, ["python", "observer"])
        client2.wait(timeout=3)
        unknown_result = unknown.finalize(phase="preflight-failure",
                                          context=runtime_context("client", "observer"))
        unknown_document = read_document(unknown_evidence)
    finally:
        close_child(client2)
        close_child(observer2)

    checks = {
        "knownConfirmed": known_result.get("confirmed") is True,
        "knownStateComplete": known_result.get("state") == "complete",
        "knownNoReasons": reasons(known_result) == [],
        "knownReturncodes":
            known_document["roles"]["client"]["postCleanupReturncode"].get("returncode") == 0
            and known_document["roles"]["observer"]["postCleanupReturncode"].get("returncode") == 7,
        "knownReturncodesIntegerKnown":
            known_document["roles"]["client"]["postCleanupReturncode"].get("known") is True
            and known_document["roles"]["observer"]["postCleanupReturncode"].get("known") is True,
        "knownStatusPresent": known_status.get("state") == "present",
        "unknownNotConfirmed": unknown_result.get("confirmed") is False,
        "unknownStateIncomplete": unknown_result.get("state") == "incomplete",
        "unknownCodeStaysNull":
            unknown_document["roles"]["observer"]["postCleanupReturncode"].get("returncode")
            is None,
        "unknownKnownFalse":
            unknown_document["roles"]["observer"]["postCleanupReturncode"].get("known")
            is False,
        "unknownReason": "returncode-unknown:observer" in reasons(unknown_result),
        "unknownNotZero":
            unknown_document["roles"]["observer"]["postCleanupReturncode"].get("returncode")
            != 0,
    }
    return record("known-vs-unknown-returncode", all(checks.values()), checks=checks,
                  knownReasons=reasons(known_result),
                  unknownReasons=reasons(unknown_result))


def test_negative_signal_returncode_is_known():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-negative-signal")
    runtime = make_runtime(evidence, finish_timeout=1.0, wait_timeout=0.2)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        code = observer.wait(timeout=3)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("client", "observer"))
        document = read_document(evidence)
        checks = {
            "childWasSignalled": code == -signal.SIGTERM,
            "negativeCodeKnown":
                document["roles"]["observer"]["postCleanupReturncode"].get("returncode")
                == -signal.SIGTERM,
            "negativeCodeKnownFlag":
                document["roles"]["observer"]["postCleanupReturncode"].get("known") is True,
            "negativeCodeAccepted": result.get("confirmed") is True,
            "stateComplete": result.get("state") == "complete",
            "noReasons": reasons(result) == [],
            "controllerSentNoSignal":
                document["roles"]["observer"]["cleanupSignals"] == [],
            "statusPresent":
                (DIAGNOSTICS.read_status_summary(evidence, "a" * 32) or {}).get("state")
                == "present",
        }
        return record("negative-signal-returncode-is-known",
                      all(checks.values()), checks=checks,
                      returncode=document["roles"]["observer"]["postCleanupReturncode"])
    finally:
        close_child(client)
        close_child(observer)


def test_normal_complete_capture_and_status():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-complete")
    runtime = make_runtime(evidence, finish_timeout=1.0, wait_timeout=0.2)
    client = py_child(
        "import sys\n"
        "sys.stdout.write('client-out\\n'); sys.stdout.flush()\n"
        "sys.stderr.write('client-err\\n'); sys.stderr.flush()\n"
        "sys.exit(0)\n"
    )
    observer = py_child(
        "import sys\n"
        "sys.stdout.write('observer-out\\n'); sys.stdout.flush()\n"
        "sys.stderr.write('observer-err\\n'); sys.stderr.flush()\n"
        "sys.exit(0)\n"
    )
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        result = runtime.finalize(phase="success",
                                  context=runtime_context("client", "observer"))
        document = read_document(evidence)
        rows = all_stream_rows(document)
        persisted = {}
        for role, stream, row in rows:
            path = evidence / row.get("file", "")
            persisted[role + "." + stream] = {
                "bytes": row.get("bytes"),
                "persistedBytes": row.get("persistedBytes"),
                "sha256": row.get("sha256"),
                "persistedSha256": row.get("persistedSha256"),
                "fileSha256": sha(path) if path.is_file() else None,
                "fileBytes": path.stat().st_size if path.is_file() else None,
            }
        status = DIAGNOSTICS.read_status_summary(evidence, "a" * 32) or {}
        checks = {
            "confirmed": result.get("confirmed") is True,
            "stateComplete": result.get("state") == "complete",
            "captureComplete": result.get("captureComplete") is True,
            "persistenceComplete": result.get("persistenceComplete") is True,
            "noReasons": reasons(result) == [],
            "documentConfirmed": document["outcome"].get("confirmed") is True,
            "documentSameReasons": document["outcome"].get("incompleteReasons") == [],
            "allCompletedEof":
                all(row.get("completed") is True and row.get("eof") is True
                    for _role, _stream, row in rows),
            "noErrors": all(not row.get("error") and not row.get("writeError")
                            for _role, _stream, row in rows),
            "notTruncated": all(row.get("truncated") is False
                                for _role, _stream, row in rows),
            "exactPersistedBytes": all(
                item["bytes"] == item["persistedBytes"] == item["fileBytes"]
                for item in persisted.values()),
            "exactPersistedDigests": all(
                item["sha256"] == item["persistedSha256"] == item["fileSha256"]
                for item in persisted.values()),
            "knownReturncodes":
                all(document["roles"][role]["postCleanupReturncode"].get("returncode") == 0
                    for role in ("client", "observer")),
            "statusPresent": status.get("state") == "present",
            "statusOutcomeConfirmed":
                (status.get("outcome") or {}).get("confirmed") is True,
            "statusNoReasons": not (status.get("outcome") or {}).get("incompleteReasons"),
            "contentSeparate":
                (evidence / "diagnostic-client.stdout").read_bytes() == b"client-out\n"
                and (evidence / "diagnostic-observer.stderr").read_bytes() == b"observer-err\n",
        }
        return record("normal-complete-capture-and-status",
                      all(checks.values()), checks=checks, persisted=persisted)
    finally:
        close_child(client)
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


def test_stream_read_failure_is_incomplete():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-read-failure")
    runtime = make_runtime(evidence)
    runtime.attach_process("observer", BrokenProcess(), ["broken"])
    result = runtime.finalize(phase="preflight-failure",
                              context=runtime_context("observer"))
    document = read_document(evidence)
    row = document["roles"]["observer"]["streams"]["stdout"]
    checks = {
        "rowError": row.get("error") == "OSError",
        "notCompleted": row.get("completed") is False,
        "notEof": row.get("eof") is False,
        "notConfirmed": result.get("confirmed") is False,
        "stateIncomplete": result.get("state") == "incomplete",
        "reason": "stream-error:observer.stdout:OSError" in reasons(result),
        "captureError": bool(result.get("captureError")),
        "documentSameReasons":
            document["outcome"].get("incompleteReasons") == result.get("incompleteReasons"),
        "statusIncomplete":
            (DIAGNOSTICS.read_status_summary(evidence, "a" * 32) or {}).get("state")
            == "incomplete",
    }
    return record("stream-read-failure-is-incomplete",
                  all(checks.values()), checks=checks, incompleteReasons=reasons(result))


def test_truncation_is_incomplete():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-truncation")
    runtime = make_runtime(evidence, finish_timeout=1.0, wait_timeout=0.2)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child(
        "import sys\n"
        "sys.stdout.write('X' * 300000); sys.stdout.flush()\n"
        "sys.exit(0)\n"
    )
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        result = runtime.finalize(phase="preflight-failure",
                                  context=runtime_context("client", "observer"))
        document = read_document(evidence)
        row = document["roles"]["observer"]["streams"]["stdout"]
        payload = (evidence / "diagnostic-observer.stdout").read_bytes()
        checks = {
            "boundedAtLimit": len(payload) == 262144,
            "metadataBytes": row.get("bytes") == 262144,
            "truncated": row.get("truncated") is True,
            "notConfirmed": result.get("confirmed") is False,
            "stateIncomplete": result.get("state") == "incomplete",
            "reason": "stream-truncated:observer.stdout" in reasons(result),
            "anyTruncated": result.get("anyTruncated") is True,
            "documentWritten": result.get("sha256") is not None,
            "knownReturncodesStillRecorded":
                document["roles"]["observer"]["postCleanupReturncode"].get("known") is True,
        }
        return record("truncation-is-incomplete", all(checks.values()), checks=checks,
                      incompleteReasons=reasons(result))
    finally:
        close_child(client)
        close_child(observer)


def test_diagnostic_write_failure_reason_and_status():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-write-failure")
    runtime = make_runtime(evidence, finish_timeout=1.0, wait_timeout=0.2)
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
    document = read_document(evidence)
    row = document["roles"]["observer"]["streams"]["stdout"]
    checks = {
        "writeFailureObserved": calls["failed"] == 1,
        "writeErrorExact": row.get("writeError") == "OSError",
        "notWritten": row.get("written") is False,
        "noFileLeft": not (evidence / "diagnostic-observer.stdout").exists(),
        "notConfirmed": first.get("confirmed") is False,
        "stateIncomplete": first.get("state") == "incomplete",
        "reasonWriteError": "stream-write-error:observer.stdout:OSError" in reasons(first),
        "reasonNotWritten": "stream-not-written:observer.stdout" in reasons(first),
        "captureErrorRecorded": any(
            value.startswith("capture-error:write:diagnostic-observer.stdout:")
            for value in reasons(first)),
        "metadataWritten": first.get("sha256") is not None,
        "sameResult": first.get("sha256") == second.get("sha256"),
        "oneFinalization": second.get("finalizationCount") == 1,
        "statusIncomplete":
            (DIAGNOSTICS.read_status_summary(evidence, "a" * 32) or {}).get("state")
            == "incomplete",
    }
    return record("diagnostic-write-failure-reason-and-status",
                  all(checks.values()), checks=checks, incompleteReasons=reasons(first))


def test_repeat_finalize_idempotent():
    require(DIAGNOSTICS, "preflight_diagnostics")
    evidence = temp_evidence("repair-repeat-finalize")
    runtime = make_runtime(evidence, finish_timeout=1.0, wait_timeout=0.2)
    client = py_child("import sys; sys.exit(0)")
    observer = py_child("import sys; sys.exit(0)")
    try:
        runtime.attach_process("client", client, ["python", "client"])
        runtime.attach_process("observer", observer, ["python", "observer"])
        client.wait(timeout=3)
        observer.wait(timeout=3)
        first = runtime.finalize(phase="success",
                                 context=runtime_context("client", "observer"))
        before = {path.name: (sha(path), path.stat().st_mtime_ns)
                  for path in evidence.iterdir() if path.is_file()}
        second = runtime.finalize(phase="success",
                                  context=runtime_context("client", "observer"))
        after = {path.name: (sha(path), path.stat().st_mtime_ns)
                 for path in evidence.iterdir() if path.is_file()}
        checks = {
            "firstConfirmed": first.get("confirmed") is True,
            "secondConfirmed": second.get("confirmed") is True,
            "sameDigest": first.get("sha256") == second.get("sha256"),
            "sameFiles": before == after,
            "oneFinalization": second.get("finalizationCount") == 1,
            "sameReasons": reasons(first) == reasons(second) == [],
            "fourStreamFiles":
                len([name for name in after if name.startswith("diagnostic-")]) == 4,
        }
        return record("repeat-finalize-idempotent", all(checks.values()), checks=checks)
    finally:
        close_child(client)
        close_child(observer)


def test_cleanup_unconfirmed_constructor_and_controller():
    require(DIAGNOSTICS, "preflight_diagnostics")
    cleanup_evidence = {"confirmed": False, "state": "synthetic-cleanup-unconfirmed",
                        "stage": {"state": "synthetic-retained"}}
    constructor = {"raised": None, "error": None, "reason": None,
                   "detail": None, "cleanupPreserved": False}
    try:
        failure = PREFLIGHT.PreflightFailure(
            "preflight-cleanup-unconfirmed", detail="synthetic-detail",
            cleanup=cleanup_evidence,
        )
        constructor.update({
            "reason": getattr(failure, "reason", None),
            "detail": getattr(failure, "detail", None),
            "cleanupPreserved": getattr(failure, "cleanup", None) == cleanup_evidence,
        })
    except BaseException as error:  # noqa: BLE001
        constructor["raised"] = type(error).__name__
        constructor["error"] = str(error)[:240]

    box = sandbox("repair-cleanup-unconfirmed")
    visits = {"container": 0, "stage": 0}
    forbidden = {"removeContainer": 0, "killpg": 0, "kill": 0}
    signals = {"stopGroup": 0, "targets": [], "allShimChildren": True}
    originals = {
        "container": PREFLIGHT._cleanup_container,
        "stage": PREFLIGHT._cleanup_stage,
        "stopGroup": GUARD.stop_group,
        "removeContainer": GUARD.remove_container_verified,
        "killpg": os.killpg,
        "kill": os.kill,
    }
    code = None

    def container(_context):
        visits["container"] += 1
        return {"removed": False, "state": "synthetic-unconfirmed"}

    def stage(_context, _resources_clear):
        visits["stage"] += 1
        return {"removed": False, "lstatAfter": "present",
                "state": "synthetic-retained"}

    def counter(name, value):
        def call(*_args, **_kwargs):
            forbidden[name] += 1
            return value
        return call

    def counting_delegate(name, original):
        def call(*args, **kwargs):
            forbidden[name] += 1
            return original(*args, **kwargs)
        return call

    def recording_stop_group(identity, *args, **kwargs):
        signals["stopGroup"] += 1
        pid = (identity or {}).get("pid") if isinstance(identity, dict) else None
        try:
            raw = Path("/proc/%s/cmdline" % pid).read_bytes()
            command = raw.replace(b"\0", b" ").decode("utf-8", "replace")
        except (OSError, TypeError):
            command = ""
        is_shim = ("checks/shims/bpftrace" in command
                   or "checks/shims/docker" in command)
        signals["targets"].append({"pid": pid, "shim": is_shim,
                                   "command": command[:240]})
        if not is_shim:
            signals["allShimChildren"] = False
        return originals["stopGroup"](identity, *args, **kwargs)

    try:
        box.write_preflight_license()
        box_env = box.env()
        resolved = {
            name: (shutil.which(name, path=box_env.get("PATH", "")) or "")
            for name in ("docker", "bpftrace")
        }
        with ModuleSandbox(box):
            PREFLIGHT._cleanup_container = container
            PREFLIGHT._cleanup_stage = stage
            GUARD.stop_group = recording_stop_group
            GUARD.remove_container_verified = counter(
                "removeContainer", {"removed": False})
            os.killpg = counting_delegate("killpg", originals["killpg"])
            os.kill = counting_delegate("kill", originals["kill"])
            code = PREFLIGHT.preflight()
        evidence = box.preflight_evidence()
        failure_path = evidence / "failure.json"
        failure = json.loads(failure_path.read_text()) if failure_path.is_file() else {}
        cleanup = failure.get("cleanup") or {}
        raised = cleanup.get("raised") or {}
        stage_dirs = [path for path in evidence.iterdir()
                      if path.is_dir() and path.name.startswith("stage-")]
        checks = {
            "constructorNoTypeError": constructor["raised"] is None,
            "constructorReason":
                constructor["reason"] == "preflight-cleanup-unconfirmed",
            "constructorDetail": constructor["detail"] == "synthetic-detail",
            "constructorKeepsCleanup": constructor["cleanupPreserved"] is True,
            "controllerFailed79": code == 79,
            "failureExists": failure_path.is_file(),
            "reasonExact": failure.get("reason") == "preflight-cleanup-unconfirmed",
            "stateBlocked": failure.get("state") == "blocked",
            "cleanupUnconfirmed": cleanup.get("confirmed") is False,
            "raisedCleanupPreserved": raised.get("confirmed") is False,
            "raisedContainerState":
                (raised.get("container") or {}).get("state") == "synthetic-unconfirmed",
            "raisedStageState":
                (raised.get("stage") or {}).get("state") == "synthetic-retained",
            "stageRetained": bool(stage_dirs),
            "noReceipt": not (evidence / "preflight-receipt.json").exists(),
            "cleanupBranchesVisited": visits["container"] == 2 and visits["stage"] == 2,
            "zeroForbiddenRemovalCalls": forbidden["removeContainer"] == 0,
            "signalsOnlyControlledShimChildren":
                signals["stopGroup"] >= 1 and signals["allShimChildren"] is True
                and all(item["shim"] and item["pid"] for item in signals["targets"]),
            "shimsControlled":
                bool(resolved["docker"]) and bool(resolved["bpftrace"])
                and str(Path(resolved["docker"]).resolve()).startswith(
                    str((ROOT / "checks" / "shims").resolve()))
                and str(Path(resolved["bpftrace"]).resolve()).startswith(
                    str((ROOT / "checks" / "shims").resolve())),
            "targetExecutionsZero": failure.get("targetExecutions") == 0,
            "fixturesImportedZero": failure.get("fixturesImported") == 0,
        }
        return record("cleanup-unconfirmed-constructor-and-controller",
                      all(checks.values()), checks=checks,
                      constructor=constructor, visits=visits, forbidden=forbidden,
                      signals=signals, failureReason=failure.get("reason"))
    finally:
        PREFLIGHT._cleanup_container = originals["container"]
        PREFLIGHT._cleanup_stage = originals["stage"]
        GUARD.stop_group = originals["stopGroup"]
        GUARD.remove_container_verified = originals["removeContainer"]
        os.killpg = originals["killpg"]
        os.kill = originals["kill"]
        regression_lib.retire_sandbox(box.path)


def _synthetic_raw(run_id, tag, event_count, end_count):
    lines = ["BEGIN run=%s tag=%s" % (run_id, tag)]
    lines.extend(["EVENT 1 0 1 1 0 1 0"] * event_count)
    lines.append("END run=%s tag=%s events=%d" % (run_id, tag, end_count))
    return ("\n".join(lines) + "\n").encode("ascii")


def test_scalar_counter_and_end_grammar():
    require(PARSER, "observation_pure")
    template = (TARGET / "tools" / "observer_template.bt").read_text(encoding="utf-8")
    end_block = template[template.rfind("END {"):]
    increment = "@events = @events + 1;"
    compare = "if (@events > __MAX_EVENTS__)"
    counter_pos = template.find(increment)
    compare_pos = template.find(compare)
    end_printf = re.search(
        r'printf\("END run=%s tag=%s events=%d\\n", "__RUN_ID__", "__TAG__", \$events\);',
        end_block,
    )
    grammar = {
        "noCountFunction": "count()" not in template,
        "scalarIncrement": counter_pos >= 0,
        "incrementBeforeCompare": 0 <= counter_pos < compare_pos,
        "plainIntegerComparison": compare_pos >= 0 and "count" not in compare,
        "endCopiesScalar": "$events = @events;" in end_block,
        "endClearsMap": "clear(@events);" in end_block,
        "endPrintsScalar": end_printf is not None,
        "endDoesNotPrintMapDirectly": "events=%d" in end_block
                                      and ", @events);" not in end_block,
        "uniqueBeginEnd": template.count("BEGIN {") == 1 and template.count("END {") == 1,
        "filtersPreserved":
            "if (pid != __TARGET_PID__)" in template
            and "if (uid != __TARGET_UID__)" in template
            and "if (str($cfn + __STR_DATA__, __PATH_MAX__) != \"__CALLER_PATH__\")"
                in template
            and "if ($off != __CALL_OFFSET__)" in template,
    }
    parser_checks = {}
    for count in (0, 1, 4):
        events, errors, details = PARSER.parse_output(
            _synthetic_raw("r", "t", count, count), "r", "t", "/caller", 0, 4)
        parser_checks["accepted%d" % count] = (
            events is not None and errors == [] and len(events) == count
            and details.get("endEvents") == count)
    over_events, over_errors, over_details = PARSER.parse_output(
        _synthetic_raw("r", "t", 5, 5), "r", "t", "/caller", 0, 4)
    mismatch_events, mismatch_errors, _mismatch_details = PARSER.parse_output(
        _synthetic_raw("r", "t", 5, 4), "r", "t", "/caller", 0, 4)
    parser_checks["overBudgetInvalid"] = (
        over_events is not None and "event-count-overflow" in over_errors
        and len(over_events) == 5 and over_details.get("endEvents") == 5)
    parser_checks["overBudgetMismatchInvalid"] = (
        mismatch_events is not None and "event-count-overflow" in mismatch_errors
        and "event-count-mismatch" in mismatch_errors)
    parser_checks["notSilentlyAccepted"] = bool(over_errors) and bool(mismatch_errors)

    # A local mirror of the fixed single-thread self-check counter.  This is a
    # grammar/semantics simulation, not a claim of multi-thread atomicity and
    # not BPF compilation evidence.
    def counter_mirror(total):
        count = 0
        emitted = 0
        for _index in range(total):
            count += 1
            if count > 4:
                break
            emitted += 1
        return count, emitted

    mirror = {count: counter_mirror(count) for count in (0, 1, 4, 5)}
    grammar["counterMirror"] = (
        mirror[0] == (0, 0) and mirror[1] == (1, 1)
        and mirror[4] == (4, 4) and mirror[5] == (5, 4))
    checks = {**grammar, **parser_checks}
    return record("scalar-counter-and-end-grammar-zero-one-four-over-budget",
                  all(checks.values()), checks=checks, mirror=mirror)


SCENARIOS = [
    test_unfinished_stdout_stderr_is_incomplete,
    test_eof_with_alive_child_is_incomplete,
    test_known_vs_unknown_returncode,
    test_negative_signal_returncode_is_known,
    test_normal_complete_capture_and_status,
    test_stream_read_failure_is_incomplete,
    test_truncation_is_incomplete,
    test_diagnostic_write_failure_reason_and_status,
    test_repeat_finalize_idempotent,
    test_cleanup_unconfirmed_constructor_and_controller,
    test_scalar_counter_and_end_grammar,
]


def main(argv=None):
    global TARGET, PREFLIGHT, GUARD, DIAGNOSTICS, PARSER
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT),
                        help="target candidate root (contains tools/)")
    parser.add_argument("--out", default=str(RESULTS))
    parser.add_argument("--only", nargs="*", default=None,
                        help="optional scenario function names")
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
    try:
        import observation_pure as parser_module
        PARSER = parser_module
    except ImportError:
        PARSER = None
    TMP.mkdir(parents=True, exist_ok=True)
    source_hashes = {}
    for path in sorted(tools.glob("*")):
        if path.is_file():
            source_hashes[str(path.relative_to(TARGET))] = sha(path)
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started_monotonic = time.monotonic()
    selected = SCENARIOS
    if args.only:
        wanted = set(args.only)
        selected = [scenario for scenario in SCENARIOS
                    if scenario.__name__ in wanted]
        missing = wanted - {scenario.__name__ for scenario in selected}
        if missing:
            raise SystemExit("unknown scenarios: " + ",".join(sorted(missing)))
    failures = []
    for scenario in selected:
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
        "kind": "observer-repair-focused-checks",
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
        "runnerPath": str(Path(__file__).resolve()),
        "runnerSha256": sha(Path(__file__)),
        "diagnosticsModulePresent": DIAGNOSTICS is not None,
        "parserModulePresent": PARSER is not None,
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
        "note": "Harmless fixed Python children and recorded no-effect shims only; "
                "no real Docker, bpftrace, fixture, target or preflight.",
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
