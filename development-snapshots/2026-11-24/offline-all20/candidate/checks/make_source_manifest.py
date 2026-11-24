#!/usr/bin/env python3
"""Write the source/test/contract-only protocol manifest once.

The manifest deliberately excludes itself, phase results, evidence runs, the
evidence index, temporary sandboxes and every runtime/admission directory.
After this command runs, no listed byte may change; checks are run against the
frozen manifest and a separate evidence index records the raw results.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "protocol-manifest.json"
BASELINE = ROOT / "baseline"
# Current consumer-closure baseline: 87 files, fdeb9734...
BASELINE_MANIFEST_SHA = "fdeb973492f251cba0a9a7aaa0ee702afb76ba8c6b4768d057c6320b43880eb0"
BASELINE_FILE_COUNT = 87
# Historical cbe9d12c.../83 baseline is documentation only and must never be
# accepted as the current consumer-closure baseline.
HISTORICAL_BASELINE_MANIFEST_SHA = "cbe9d12c03a2716adacd55331a9b38798627681cd0787b49e132978ddd5a13dd"
HISTORICAL_BASELINE_FILE_COUNT = 83


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_baseline():
    manifest_path = BASELINE / "protocol-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise SystemExit("baseline-manifest-not-regular-non-symlink-file")
    actual_sha = sha(manifest_path)
    if actual_sha != BASELINE_MANIFEST_SHA:
        if actual_sha == HISTORICAL_BASELINE_MANIFEST_SHA:
            raise SystemExit("historical-baseline-83-not-current")
        raise SystemExit("baseline-manifest-sha-mismatch: " + actual_sha)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise SystemExit("baseline-manifest-unreadable: " + str(error))
    if not isinstance(manifest, dict):
        raise SystemExit("baseline-manifest-not-object")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise SystemExit("baseline-manifest-files-not-object")
    if manifest.get("fileCount") != BASELINE_FILE_COUNT or len(files) != BASELINE_FILE_COUNT:
        raise SystemExit(
            "baseline-manifest-count-mismatch: fileCount=%r actual=%r"
            % (manifest.get("fileCount"), len(files)))
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise SystemExit("baseline-manifest-member-invalid")
        path = BASELINE / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit(
                "baseline-member-not-regular-non-symlink-file: " + relative)
        if sha(path) != expected:
            raise SystemExit("baseline-member-sha-mismatch: " + relative)
    return manifest


def collect():
    files = {}
    explicit = [
        'DIAGNOSTICS-CONTRACT.md',
        'REPAIR-CONTRACT.md',
        'BUFFER-PREFLIGHT-CONTRACT.md',
        'BUFFER-V2-CONTRACT.md',
        'END-LF-CONTRACT.md',
        'FORMAL-ADMISSION-CONTRACT.md',
        'FORMAL-ADMISSION-SUPPORT.md',
        'RECOVERY-CLOSE-CONTRACT.md',
        'RECOVERY-CLOSE-SUPPORT.md',
        'ASSOCIATION-RECOVERY-CONTRACT.md',
        'ASSOCIATION-RECOVERY-SUPPORT.md',
        'UNIFIED-RECOVERY-CONTRACT.md',
        'UNIFIED-RECOVERY-SUPPORT.md',
        'RECORD-VALIDATION-CONTRACT.md',
        'RECORD-VALIDATION-SUPPORT.md',
        'experiment-plan.json',
        'docs/CONTRACTS-REV3.md',
        'docs/CONTRACTS-REV4.md',
        'docs/CONTRACTS-REV5.md',
        'docs/CONTRACTS-REV6.md',
        'docs/CONTRACTS-REV7.md',
        'docs/CONTRACTS-REV8.md',
        'docs/EXPERIMENT-PROTOCOL.md',
        'docs/CLOSURE-EVIDENCE-CONTRACT.md',
    ]
    for relative in explicit:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit('missing: ' + relative)
        files[relative] = sha(path)
    for directory, pattern in (
        ('tools', '*'),
        ('checks', '*.py'),
        ('checks/formal_admission', '*.py'),
        ('checks/shims', '*'),
        ('fixtures', '**/*.py'),
    ):
        for path in sorted((ROOT / directory).glob(pattern)):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            files[str(path.relative_to(ROOT))] = sha(path)
    return files


def source_references():
    """Pinned data-only source references; never imported by runtime code."""
    rows = []
    for relative, role in (
        ("source-evidence/bpftrace-v0.20.2-utils.cpp",
         "pinned-upstream-hex-format-buffer"),
        ("source-evidence/format_string.cpp",
         "pinned-upstream-format-string-flags"),
        ("source-evidence/printf.cpp",
         "pinned-upstream-printable-buffer-call"),
        ("source-evidence/upstream-source.json",
         "pinned-upstream-commit-metadata"),
        ("proof/formatter-counterexample.json",
         "independent-source-derived-counterexample"),
        ("proof/source-review-verification.json",
         "external-review-verification-record"),
    ):
        path = ROOT / relative
        if path.is_file():
            rows.append({
                "path": relative,
                "role": role,
                "bytes": path.stat().st_size,
                "sha256": sha(path),
                "executable": False,
                "runtimeLoaded": False,
            })
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    output = Path(args.out)
    verify_baseline()
    files = collect()
    total = sum((ROOT / relative).stat().st_size for relative in files)
    manifest = {
        "kind": "stdlib-cli-admission-protocol-manifest",
        "version": 3,
        "protocolRevision": 3,
        "diagnosticVersion": 1,
        "phase": "consumer-closure-final-freeze",
        "state": "pending-codex-review",
        "selfExcluded": True,
        "sourceOnly": True,
        "files": files,
        "fileCount": len(files),
        "totalBytes": total,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "selfcheckExecutions": 0,
        "admissionIssued": False,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "bufferParser": "tools/buffer_protocol_v2.py",
        "bufferTemplate": "tools/observer_template_buffer_v2.bt",
        "baselineManifestSha256": BASELINE_MANIFEST_SHA,
        "baselineFileCount": BASELINE_FILE_COUNT,
        "sourceEvidenceInRuntimeClosure": False,
        "bufferRuntimeVerified": False,
        "formalTargets": "0/16",
        "r3": "blocked",
        "excluded": [
            "protocol-manifest.json",
            "phase-result.json",
            "checks/evidence-index.json",
            "checks/current-run.json",
            "checks/validation-summary.json",
            "checks/evidence-runs/",
            "checks/tmp/",
            "checks/diffs/",
            "REPORT.md",
            "baseline/",
            "proof/",
            "source-evidence/",
            "TASK.md",
            "implementation-status.json",
            "implementation-worker.py",
            "implementation.events.jsonl",
            "implementation.stderr.txt",
            "launch.json",
            "model-preflight.json",
            "launcher.stderr",
            "launcher.stdout",
            "headless-home/",
            "state/",
            "runs/",
            "prepare/",
            "codex-review/",
            "preflight/",
            "**/__pycache__/",
        ],
        "sourceReferences": source_references(),
        "note": "Source-only manifest. Do not modify any listed byte after this "
                "write. Raw test results are bound later by checks/evidence-index.json. "
                "Pinned source references are data-only digests and are never loaded "
                "by the runtime parser or preflight.",
    }
    payload = json.dumps(manifest, sort_keys=True, indent=1) + "\n"
    output.write_text(payload, encoding="utf-8")
    print(json.dumps({"fileCount": len(files), "totalBytes": total,
                      "sha256": sha(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
