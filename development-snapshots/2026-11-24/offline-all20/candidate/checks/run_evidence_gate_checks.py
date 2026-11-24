#!/usr/bin/env python3
"""Checks for manifest-complete evidence capture and the sequential closure gate.

The evidence-capture helper must bind the selected frozen manifest mapping
(``baseline/protocol-manifest.json`` for RED, the final candidate manifest for
GREEN), reject missing/type-changed/symlinked/mismatched declared files, keep
metadata separate and never count a file count as a substitution for hashes.

The closure gate must run report generation, proof verification and durable
sealing/readback strictly in order.  A failure at any stage must leave the
archive function uncalled.  The normal path must put the final REPORT,
phase-result and evidence index in the closure input manifest and read back
every member.  No real resource is used.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TMP = ROOT / "checks" / "tmp"
BASELINE = ROOT / "baseline"
RESULTS = []


def check(identifier, description):
    def decorate(function):
        RESULTS.append((identifier, description, function))
        return function
    return decorate


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_helper(name):
    path = HERE / (name + ".py")
    spec = importlib.util.spec_from_file_location(
        name + "_consumer_closure_" + os.urandom(4).hex(), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def copy_baseline(prefix):
    root = Path(tempfile.mkdtemp(prefix=prefix, dir=TMP))
    shutil.copytree(BASELINE, root / "root")
    # The frozen baseline is deliberately read-only.  A synthetic test may
    # mutate its private copy; that never changes the immutable baseline.
    for path in (root / "root").rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                path.chmod(0o600)
            except OSError:
                pass
    return root / "root"


def run_capture(module, source_root, run_dir, command, label="synthetic"):
    out = run_dir / "stdout.bin"
    err = run_dir / "stderr.bin"
    code = module.main([
        "--suite", label,
        "--source-root", str(source_root),
        "--run-dir", str(run_dir),
        "--", *command,
    ])
    return code, out, err


def metadata_names(closure):
    meta = closure.get("metadata") or {}
    names = set()

    def collect(value):
        if isinstance(value, dict):
            if value.get("path"):
                names.add(value["path"])
                return
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(meta)
    return names


@check("capture-full-baseline-87-map",
       "the capture helper records every declared baseline file hash")
def capture_full_baseline(evidence_capture):
    source = copy_baseline("capture-baseline-")
    try:
        run_dir = Path(tempfile.mkdtemp(prefix="capture-run-", dir=TMP)) / "run"
        code, _out, _err = run_capture(
            evidence_capture, source, run_dir,
            [sys.executable, "-c", "print('synthetic-capture')"])
        result = json.loads((run_dir / "run.json").read_text())
        before = result["sourceManifestBefore"]
        after = result["sourceManifestAfter"]
        manifest = json.loads((source / "protocol-manifest.json").read_text())
        checks = {
            "exit0": code == 0,
            "beforeCount87": before["fileCount"] == 87 == len(manifest["files"]),
            "afterCount87": after["fileCount"] == 87,
            "entriesEqualManifest": before["entries"] == manifest["files"],
            "afterEqualBefore": after["entries"] == before["entries"],
            "closureOk": before["ok"] is True and after["ok"] is True,
            "commandRaw": (run_dir / "stdout.bin").read_bytes()
            == b"synthetic-capture\n",
            "exitCodeRecorded": result.get("returncode") == 0,
        }
        return all(checks.values()), {"checks": checks}
    finally:
        shutil.rmtree(source.parent, ignore_errors=True)


@check("capture-rejects-missing-declared-document",
       "a missing declared UNIFIED/RECORD document is an explicit rejection")
def capture_missing(evidence_capture):
    source = copy_baseline("capture-missing-")
    try:
        (source / "UNIFIED-RECOVERY-CONTRACT.md").unlink()
        run_dir = Path(tempfile.mkdtemp(prefix="capture-run-", dir=TMP)) / "run"
        code, _out, _err = run_capture(
            evidence_capture, source, run_dir,
            [sys.executable, "-c", "print('x')"])
        result = json.loads((run_dir / "run.json").read_text())
        before = result["sourceManifestBefore"]
        reasons = [item.get("reason") for item in before.get("problems") or []]
        checks = {
            "nonzero": code != 0,
            "closureNotOk": before.get("ok") is False,
            "missingRecorded": any(
                item.get("path") == "UNIFIED-RECOVERY-CONTRACT.md"
                for item in before.get("problems") or []),
            "reasonMissing": "missing" in reasons,
            "countStillDeclared": before.get("declaredCount") == 87,
        }
        return all(checks.values()), {"checks": checks, "problems": before.get(
            "problems")}
    finally:
        shutil.rmtree(source.parent, ignore_errors=True)


@check("capture-rejects-same-count-swap-and-mutation",
       "same file count with a changed byte is rejected by the declared hash")
def capture_swap(evidence_capture):
    source = copy_baseline("capture-swap-")
    try:
        target = source / "tools" / "buffer_protocol.py"
        original = target.read_bytes()
        target.write_bytes(original + b"\n# same-count-swap\n")
        run_dir = Path(tempfile.mkdtemp(prefix="capture-run-", dir=TMP)) / "run"
        code, _out, _err = run_capture(
            evidence_capture, source, run_dir,
            [sys.executable, "-c", "print('x')"])
        result = json.loads((run_dir / "run.json").read_text())
        before = result["sourceManifestBefore"]
        problems = before.get("problems") or []
        checks = {
            "nonzero": code != 0,
            "closureNotOk": before.get("ok") is False,
            "sameDeclaredCount": before.get("declaredCount") == 87,
            "mismatchRecorded": any(
                item.get("path") == "tools/buffer_protocol.py"
                and item.get("reason") == "digest-mismatch"
                for item in problems),
            "hashExplicit": any(item.get("expected")
                                and item.get("actual") for item in problems),
        }
        return all(checks.values()), {"checks": checks, "problems": problems}
    finally:
        shutil.rmtree(source.parent, ignore_errors=True)


@check("capture-metadata-separate-not-source-counted",
       "TASK and extra metadata are listed separately, never counted as source")
def capture_metadata(evidence_capture):
    source = copy_baseline("capture-metadata-")
    try:
        (source / "TASK.md").write_text("# synthetic task\n", encoding="utf-8")
        (source / "EXTRA-METADATA.json").write_text("{}\n", encoding="utf-8")
        run_dir = Path(tempfile.mkdtemp(prefix="capture-run-", dir=TMP)) / "run"
        code, _out, _err = run_capture(
            evidence_capture, source, run_dir,
            [sys.executable, "-c", "print('x')"])
        result = json.loads((run_dir / "run.json").read_text())
        before = result["sourceManifestBefore"]
        meta = metadata_names(before)
        checks = {
            "exit0": code == 0,
            "sourceCountUnchanged": before["fileCount"] == 87,
            "taskNotSource": "TASK.md" not in (before.get("entries") or {}),
            "extraNotSource": "EXTRA-METADATA.json" not in (
                before.get("entries") or {}),
            "metadataTask": "TASK.md" in meta,
            "metadataManifest": "protocol-manifest.json" in meta,
        }
        return all(checks.values()), {"checks": checks, "metadata": sorted(meta)}
    finally:
        shutil.rmtree(source.parent, ignore_errors=True)


@check("capture-target-launch-failure-retained",
       "a missing target command is retained as a checked launch failure")
def capture_launch_failure(evidence_capture):
    source = copy_baseline("capture-launch-")
    try:
        run_dir = Path(tempfile.mkdtemp(prefix="capture-run-", dir=TMP)) / "run"
        code, _out, err = run_capture(
            evidence_capture, source, run_dir,
            ["/nonexistent/consumer-closure-target"])
        result = json.loads((run_dir / "run.json").read_text())
        exception = result.get("launchException") or {}
        checks = {
            "nonzero": code != 0,
            "launchRecorded": exception.get("type") in {
                "FileNotFoundError", "PermissionError", "OSError"},
            "launchTraceback": bool(exception.get("traceback")),
            "runJsonPresent": (run_dir / "run.json").is_file(),
            "closureOk": result["sourceManifestBefore"]["ok"] is True,
            "stderrPresent": (run_dir / "stderr.bin").is_file(),
        }
        return all(checks.values()), {"checks": checks, "exception": exception}
    finally:
        shutil.rmtree(source.parent, ignore_errors=True)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=1) + "\n",
                    encoding="utf-8")


def source_snapshot(source, files, manifest_sha):
    """The exact per-path source map recorded by a captured invocation."""
    return {
        "sourceRoot": str(source),
        "manifestSha256": manifest_sha,
        "declaredCount": len(files),
        "fileCount": len(files),
        "entries": dict(files),
        "problems": [],
        "ok": True,
        "sourceOnly": True,
    }


def write_capture(root, source, files, manifest_sha, suite='consumer',
                  returncode=0, passed=2, total=2, failed=None):
    raw = root / 'raw' / suite
    raw.mkdir(parents=True, exist_ok=True)
    command = ['synthetic-suite']
    stdout_body = b'synthetic-stdout' + bytes([10])
    stderr_body = b''
    returncode_body = (str(returncode) + chr(10)).encode('ascii')
    (raw / 'stdout.bin').write_bytes(stdout_body)
    (raw / 'stderr.bin').write_bytes(stderr_body)
    (raw / 'returncode.txt').write_bytes(returncode_body)
    total = int(total)
    passed = int(passed)
    failed = list(failed or [])
    rows = []
    for index in range(total):
        row = {'id': 'synthetic-check-%d' % (index + 1),
               'passed': index < passed}
        if index >= passed:
            row['reason'] = 'synthetic-failed'
        rows.append(row)
    result_path = raw / 'results.json'
    write_json(result_path, {
        'kind': 'synthetic-final-suite-results',
        'suite': suite,
        'command': command,
        'passed': passed,
        'total': total,
        'failed': failed,
        'results': rows,
    })
    snapshot = source_snapshot(source, files, manifest_sha)
    capture_rel = 'raw/%s/run.json' % suite
    result_rel = 'raw/%s/results.json' % suite
    stdout_rel = 'raw/%s/stdout.bin' % suite
    stderr_rel = 'raw/%s/stderr.bin' % suite
    returncode_rel = 'raw/%s/returncode.txt' % suite
    capture_path = root / capture_rel
    write_json(capture_path, {
        'kind': 'consumer-closure-evidence-capture',
        'version': 2,
        'suite': suite,
        'command': command,
        'cwd': str(root),
        'returncode': returncode,
        'returncodeFile': 'returncode.txt',
        'returncodeSha256': sha(root / returncode_rel),
        'returncodeBytes': len(returncode_body),
        'stdoutFile': 'stdout.bin',
        'stdoutSha256': sha(root / stdout_rel),
        'stdoutBytes': len(stdout_body),
        'stderrFile': 'stderr.bin',
        'stderrSha256': sha(root / stderr_rel),
        'stderrBytes': len(stderr_body),
        'sourceManifestBefore': snapshot,
        'sourceManifestAfter': snapshot,
        'sourceUnchanged': True,
        'sourceClosureOk': True,
        'resultFile': result_rel,
        'resultSha256': sha(result_path),
        'targetExecutions': 0,
        'realContainers': 0,
        'realBpftrace': 0,
        'formalTargets': '0/16',
        'r3': 'blocked',
    })
    return {
        'suite': suite,
        'command': command,
        'resultFile': result_rel,
        'resultSha256': sha(result_path),
        'captureFile': capture_rel,
        'captureSha256': sha(capture_path),
        'stdoutFile': stdout_rel,
        'stdoutSha256': sha(root / stdout_rel),
        'stdoutBytes': len(stdout_body),
        'stderrFile': stderr_rel,
        'stderrSha256': sha(root / stderr_rel),
        'stderrBytes': len(stderr_body),
        'returncode': returncode,
        'returncodeFile': returncode_rel,
        'returncodeSha256': sha(root / returncode_rel),
        'returncodeBytes': len(returncode_body),
        'sourceManifestBefore': snapshot,
        'sourceManifestAfter': snapshot,
    }

def write_evidence_index(root, files, manifest_sha, entries,
                         name='checks-evidence-index.json'):
    path = root / name
    write_json(path, {
        'kind': 'consumer-closure-evidence-index',
        'version': 1,
        'state': 'completed',
        'sourceManifest': {
            'path': 'protocol-manifest.json',
            'sha256': manifest_sha,
            'fileCount': len(files),
            'entries': dict(files),
        },
        'entries': [dict(entry) for entry in entries],
        'checks': {
            'sourceUnchanged': True,
            'allReturncodesZero': True,
            'allResultsPassed': True,
        },
        'targetExecutions': 0,
        'realContainers': 0,
        'realBpftrace': 0,
        'formalTargets': '0/16',
        'r3': 'blocked',
    })
    return path


def write_proof(root, source, index_path, manifest_sha, name='proof.json',
                **overrides):
    path = root / name
    manifest = json.loads((source / 'protocol-manifest.json').read_text())
    proof = {
        'kind': 'consumer-closure-proof',
        'version': 1,
        'state': 'verified',
        'decision': 'pass',
        'verdict': 'pass',
        'sourceRoot': str(source.resolve()),
        'sourceManifestSha256': manifest_sha,
        'sourceFileCount': len(manifest.get('files') or {}),
        'evidenceIndexSha256': sha(index_path),
        'checks': {
            'sourceManifest': True,
            'evidenceIndex': True,
            'rawMembers': True,
            'derivedDecision': 'pass',
        },
        'targetExecutions': 0,
        'formalTargets': '0/16',
        'r3': 'blocked',
    }
    proof.update(overrides)
    write_json(path, proof)
    return path


def gate_fixture(prefix):
    root = Path(tempfile.mkdtemp(prefix=prefix, dir=TMP))
    source = root / 'source'
    source.mkdir()
    (source / 'a.txt').write_text('a' + chr(10), encoding='utf-8')
    (source / 'docs').mkdir()
    (source / 'docs' / 'b.md').write_text('b' + chr(10), encoding='utf-8')
    (source / 'tools').mkdir()
    write_json(source / 'tools' / 'closure-suite-plan.json', {
        'kind': 'consumer-closure-suite-plan',
        'version': 1,
        'scope': 'diagnostic-contract',
        'requiredSuites': ['consumer'],
        'suites': {
            'consumer': {
                'command': ['synthetic-suite'],
                'description': 'synthetic diagnostic contract suite',
            },
        },
    })
    files = {
        'a.txt': sha(source / 'a.txt'),
        'docs/b.md': sha(source / 'docs' / 'b.md'),
        'tools/closure-suite-plan.json': sha(
            source / 'tools' / 'closure-suite-plan.json'),
    }
    write_json(source / 'protocol-manifest.json', {
        'kind': 'synthetic', 'state': 'pending-codex-review',
        'fileCount': len(files), 'files': files,
    })
    manifest_sha = sha(source / 'protocol-manifest.json')
    entry = write_capture(root, source, files, manifest_sha)
    evidence = write_evidence_index(root, files, manifest_sha, [entry])
    write_proof(root, source, evidence, manifest_sha)
    write_json(root / 'phase-result.json', {
        'state': 'pending-independent-review', 'r3': 'blocked',
        'formalTargets': '0/16',
    })
    return root, source, evidence


def contract_state(root, source):
    manifest = json.loads((source / "protocol-manifest.json").read_text())
    return manifest["files"], sha(source / "protocol-manifest.json")


def verify_contract(closure_gate, root, source, proof=None, evidence=None):
    proof = proof or (root / "proof.json")
    evidence = evidence or (root / "checks-evidence-index.json")
    return closure_gate.verify_proof(proof, evidence, source_root=source)


@check("gate-report-failure-prevents-archive",
       "a report generator exception prevents proof, sealing and archive")
def gate_report_failure(closure_gate):
    root, source, evidence = gate_fixture("gate-report-fail-")
    calls = []
    try:
        def failing_report(*args, **kwargs):
            raise RuntimeError("synthetic-report-failure")

        result = closure_gate.run_gate(
            source_root=source, evidence_index=evidence,
            proof_path=root / "proof.json", phase_result=root / "phase-result.json",
            report_path=root / "REPORT.md",
            closure_manifest=root / "closure-input-manifest.json",
            archive_function=lambda path: calls.append(path),
            report_generator=failing_report)
        checks = {
            "failed": result["state"] == "failed",
            "stageReport": result["failedStage"] == "report",
            "archiveCalls0": len(calls) == 0 == result["archiveCalls"],
            "noManifest": not (root / "closure-input-manifest.json").exists(),
        }
        return all(checks.values()), {"checks": checks, "result": result}
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check("gate-proof-failure-prevents-archive",
       "proof verification failure prevents sealing and archive")
def gate_proof_failure(closure_gate):
    root, source, evidence = gate_fixture("gate-proof-fail-")
    calls = []
    try:
        def failing_proof(*args, **kwargs):
            return {"ok": False, "reason": "synthetic-proof-mismatch"}

        result = closure_gate.run_gate(
            source_root=source, evidence_index=evidence,
            proof_path=root / "proof.json", phase_result=root / "phase-result.json",
            report_path=root / "REPORT.md",
            closure_manifest=root / "closure-input-manifest.json",
            archive_function=lambda path: calls.append(path),
            proof_verifier=failing_proof)
        checks = {
            "failed": result["state"] == "failed",
            "stageProof": result["failedStage"] == "proof",
            "archiveCalls0": len(calls) == 0 == result["archiveCalls"],
            "noManifest": not (root / "closure-input-manifest.json").exists(),
        }
        return all(checks.values()), {"checks": checks, "result": result}
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check("gate-missing-and-mismatched-member-prevents-archive",
       "a missing or changed closure member is refused before archive")
def gate_member_failure(closure_gate):
    variants = {}
    cases = []
    for mode in ("missing", "mismatch"):
        root, source, evidence = gate_fixture("gate-member-" + mode + "-")
        calls = []
        try:
            def mutate(_root=root, _mode=mode):
                if _mode == "missing":
                    (source / "docs" / "b.md").unlink()
                else:
                    (source / "docs" / "b.md").write_text(
                        "changed\n", encoding="utf-8")

            result = closure_gate.run_gate(
                source_root=source, evidence_index=evidence,
                proof_path=root / "proof.json",
                phase_result=root / "phase-result.json",
                report_path=root / "REPORT.md",
                closure_manifest=root / "closure-input-manifest.json",
                archive_function=lambda path: calls.append(path),
                hooks={"after_proof": mutate})
            checks = {
                "failed": result["state"] == "failed",
                "stageManifest": result["failedStage"] == "manifest",
                "archiveCalls0": len(calls) == 0 == result["archiveCalls"],
                "memberDiagnostic": bool(result.get("detail")),
            }
            cases.append(all(checks.values()))
            variants[mode] = {"checks": checks, "result": result}
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return all(cases), {"variants": variants}


@check("gate-normal-closure-readback-and-report",
       "normal path seals every member, includes REPORT/phase/evidence and archives once")
def gate_normal(closure_gate):
    root, source, evidence = gate_fixture("gate-normal-")
    calls = []
    try:
        result = closure_gate.run_gate(
            source_root=source, evidence_index=evidence,
            proof_path=root / "proof.json", phase_result=root / "phase-result.json",
            report_path=root / "REPORT.md",
            closure_manifest=root / "closure-input-manifest.json",
            archive_function=lambda path: calls.append(path))
        manifest = json.loads((root / "closure-input-manifest.json").read_text())
        files = manifest.get("files") or {}
        index_text = evidence.read_text(encoding="utf-8")
        proof_text = (root / "proof.json").read_text(encoding="utf-8")
        checks = {
            "completed": result["state"] == "completed",
            "archiveCalls1": len(calls) == 1 == result["archiveCalls"],
            "reportPresent": (root / "REPORT.md").is_file()
            and "REPORT.md" in files,
            "phasePresent": "phase-result.json" in files,
            "evidencePresent": "checks-evidence-index.json" in files,
            "proofBound": "proof.json" in files,
            "allReadback": result.get("readback", {}).get("ok") is True,
            "allMembersRead": result.get("readback", {}).get("fileCount")
            == len(files),
            "reportSha": result.get("report", {}).get("sha256")
            == sha(root / "REPORT.md"),
            "manifestMembers": all((source / relative).is_file()
                                   for relative in ("a.txt", "docs/b.md")),
            "indexDoesNotReferenceProof": "consumer-closure-proof" not in index_text,
            "proofDoesNotBindClosure": "closure-input-manifest" not in proof_text,
            "noToolResource": result.get("targetExecutions") == 0,
        }
        return all(checks.values()), {"checks": checks, "result": result,
                                      "files": sorted(files)}
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check("proof-contract-rejects-state-only-unbound-and-wrong-digests",
       "proof must bind the source manifest and evidence index, not self-claims")
def proof_contract_basics(closure_gate):
    root, source, evidence = gate_fixture("gate-proof-contract-")
    variants = {}
    try:
        files, manifest_sha = contract_state(root, source)
        base = verify_contract(closure_gate, root, source)
        checks = {"validAccepted": base.get("ok") is True,
                  "validDecision": base.get("decision") == "pass"}
        valid = json.loads((root / "proof.json").read_text())

        def reject(name, payload, expected, evidence_path=None):
            path = root / ("proof-" + name + ".json")
            write_json(path, payload)
            outcome = closure_gate.verify_proof(
                path, evidence_path or evidence, source_root=source)
            variants[name] = {"ok": outcome.get("ok"),
                              "reason": outcome.get("reason")}
            return (outcome.get("ok") is False
                    and expected in str(outcome.get("reason") or ""))

        checks.update({
            "stateOnlyRejected": reject(
                "state-only", {"state": "completed", "verdict": "ready",
                               "result": "ready"}, "proof:kind"),
            "unboundRejected": reject(
                "unbound", {key: value for key, value in valid.items()
                            if key != "evidenceIndexSha256"},
                "proof:evidence-index-digest"),
            "wrongIndexDigest": reject(
                "wrong-index", dict(valid, evidenceIndexSha256="0" * 64),
                "proof:evidence-index-digest"),
            "wrongSourceDigest": reject(
                "wrong-source", dict(valid, sourceManifestSha256="0" * 64),
                "proof:source-manifest-digest"),
            "wrongSourceRoot": reject(
                "wrong-root", dict(valid, sourceRoot="/nonexistent/source"),
                "proof:source-root"),
            "wrongDecision": reject(
                "wrong-decision", dict(valid, decision="not-pass"),
                "proof:decision"),
        })
        return all(checks.values()), {"checks": checks, "variants": variants}
    finally:
        shutil.rmtree(root, ignore_errors=True)


@check("proof-contract-rejects-forged-summary-and-stale-index",
       "verification parses actual results/source maps instead of trusting summaries")
def proof_contract_forged(closure_gate):
    variants = {}
    cases = []

    def fresh():
        return gate_fixture("gate-proof-forged-")

    # A result record that says it passed while its own raw result does not.
    root, source, evidence = fresh()
    try:
        files, manifest_sha = contract_state(root, source)
        result_path = root / "raw" / "consumer" / "results.json"
        write_json(result_path, {
            "kind": "synthetic-final-suite-results", "suite": "consumer",
            "passed": 1, "total": 2, "failed": ["synthetic-forged"],
            "results": [{"id": "synthetic-check", "passed": True}],
        })
        capture_path = root / "raw" / "consumer" / "run.json"
        capture = json.loads(capture_path.read_text())
        capture["resultSha256"] = sha(result_path)
        write_json(capture_path, capture)
        index = json.loads(evidence.read_text())
        index["entries"][0]["resultSha256"] = sha(result_path)
        index["entries"][0]["captureSha256"] = sha(capture_path)
        write_json(evidence, index)
        write_proof(root, source, evidence, manifest_sha)
        outcome = verify_contract(closure_gate, root, source)
        variants["forged-summary"] = outcome
        cases.append(outcome.get("ok") is False
                     and "result:failed" in str(outcome.get("reason")))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # A stale index whose declared source map no longer matches the manifest.
    root, source, evidence = fresh()
    try:
        files, manifest_sha = contract_state(root, source)
        index = json.loads(evidence.read_text())
        index["sourceManifest"]["entries"]["a.txt"] = "0" * 64
        write_json(evidence, index)
        write_proof(root, source, evidence, manifest_sha)
        outcome = verify_contract(closure_gate, root, source)
        variants["stale-index"] = outcome
        cases.append(outcome.get("ok") is False
                     and "index:source-entries" in str(outcome.get("reason")))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return all(cases), {"variants": variants}


@check("proof-contract-rejects-member-digest-missing-symlink-and-escape",
       "listed raw members are rehashed and unsafe paths are refused")
def proof_contract_members(closure_gate):
    variants = {}
    cases = []

    def fresh():
        return gate_fixture("gate-proof-member-")

    # Wrong declared member digest.
    root, source, evidence = fresh()
    try:
        files, manifest_sha = contract_state(root, source)
        index = json.loads(evidence.read_text())
        index["entries"][0]["resultSha256"] = "0" * 64
        write_json(evidence, index)
        write_proof(root, source, evidence, manifest_sha)
        outcome = verify_contract(closure_gate, root, source)
        variants["wrong-member-digest"] = outcome
        cases.append(outcome.get("ok") is False
                     and "member:digest" in str(outcome.get("reason")))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # Missing listed member.
    root, source, evidence = fresh()
    try:
        (root / "raw" / "consumer" / "results.json").unlink()
        outcome = verify_contract(closure_gate, root, source)
        variants["missing-member"] = outcome
        cases.append(outcome.get("ok") is False
                     and "member:missing" in str(outcome.get("reason")))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # Symlinked listed member.
    root, source, evidence = fresh()
    try:
        outside = root / "outside-results.json"
        write_json(outside, {"passed": 2, "total": 2, "failed": []})
        result_path = root / "raw" / "consumer" / "results.json"
        result_path.unlink()
        os.symlink(outside, result_path)
        outcome = verify_contract(closure_gate, root, source)
        variants["symlink-member"] = outcome
        cases.append(outcome.get("ok") is False
                     and "member:symlink" in str(outcome.get("reason")))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # Path escape in a listed entry.
    root, source, evidence = fresh()
    try:
        files, manifest_sha = contract_state(root, source)
        write_json(root / "outside.json", {"passed": 2, "total": 2})
        index = json.loads(evidence.read_text())
        index["entries"][0]["resultFile"] = "../outside.json"
        index["entries"][0]["resultSha256"] = sha(root / "outside.json")
        write_json(evidence, index)
        write_proof(root, source, evidence, manifest_sha)
        outcome = verify_contract(closure_gate, root, source)
        variants["path-escape"] = outcome
        cases.append(outcome.get("ok") is False
                     and "member:path-escape" in str(outcome.get("reason")))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return all(cases), {"variants": variants}


@check("gate-forged-proof-prevents-archive",
       "a self-claimed proof with no bound evidence stops before sealing/archive")
def gate_forged_proof(closure_gate):
    root, source, evidence = gate_fixture("gate-forged-proof-")
    calls = []
    try:
        forged = root / "proof-forged.json"
        write_json(forged, {"kind": "consumer-closure-proof", "state": "verified",
                            "decision": "pass", "verdict": "pass",
                            "result": "ready"})
        result = closure_gate.run_gate(
            source_root=source, evidence_index=evidence,
            proof_path=forged, phase_result=root / "phase-result.json",
            report_path=root / "REPORT.md",
            closure_manifest=root / "closure-input-manifest.json",
            archive_function=lambda path: calls.append(path))
        checks = {
            "failed": result["state"] == "failed",
            "stageProof": result["failedStage"] == "proof",
            "archiveCalls0": len(calls) == 0 == result["archiveCalls"],
            "noManifest": not (root / "closure-input-manifest.json").exists(),
        }
        return all(checks.values()), {"checks": checks, "result": result}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--tools", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if out.exists():
        raise SystemExit("refusing to overwrite results: " + str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    evidence_capture = load_helper("evidence_capture")
    closure_gate = load_helper("finalize_closure")
    results = []
    for identifier, description, function in RESULTS:
        try:
            argument = closure_gate if (
                identifier.startswith("gate-")
                or identifier.startswith("proof-")) else evidence_capture
            passed, detail = function(argument)
            error = None
        except BaseException as exc:  # noqa: BLE001 - classify, never hide
            passed = False
            detail = {}
            error = {"type": type(exc).__name__,
                     "message": str(exc)[:400],
                     "traceback": traceback.format_exc()[-2000:]}
        results.append({"id": identifier, "description": description,
                        "passed": bool(passed), "detail": detail,
                        "error": error})
        print(("PASS " if passed else "FAIL ") + identifier)
    payload = {
        "kind": "consumer-closure-evidence-and-archive-gate-checks",
        "sourceTools": str(Path(args.tools).resolve()),
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "realTargets": 0,
        "fixturesImported": 0,
        "selfcheckExecutions": 0,
        "formalTargets": "0/16",
        "r3": "blocked",
        "results": results,
        "passed": sum(1 for item in results if item["passed"]),
        "failed": [item["id"] for item in results if not item["passed"]],
        "total": len(results),
    }
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                   encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not payload["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
