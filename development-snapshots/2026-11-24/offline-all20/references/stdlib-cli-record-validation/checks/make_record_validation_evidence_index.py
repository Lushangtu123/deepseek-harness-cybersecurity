#!/usr/bin/env python3
"""Bind the frozen source manifest to raw record-validation evidence runs.

The index is written after the source/test/contract freeze. It never rewrites a
run, a RED directory or a result file. Actual result counts are copied from the
raw result files; they are not maintained in this script.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "checks" / "record-validation-evidence-index.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def bound_files(directory):
    directory = Path(directory)
    rows = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rows.append({
                "file": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            })
    return rows


def suite_run(path, label):
    path = Path(path).resolve()
    top = read_json(path / "run.json")
    result = None
    if top.get("resultFile"):
        result_path = Path(top["resultFile"])
        if result_path.is_file():
            result = {
                "file": str(result_path.relative_to(ROOT)),
                "sha256": sha(result_path),
                "passed": top.get("resultPassed"),
                "total": top.get("resultTotal"),
                "failed": top.get("resultFailed"),
            }
    return {
        "label": label,
        "kind": "suite-run",
        "directory": str(path.relative_to(ROOT)),
        "command": top.get("command"),
        "cwd": top.get("cwd"),
        "path": top.get("path"),
        "returncode": top.get("returncode"),
        "launchException": top.get("launchException"),
        "intervalSeconds": top.get("intervalSeconds"),
        "sourceUnchanged": top.get("sourceUnchanged"),
        "sourceManifestBefore": {
            "manifestSha256": (top.get("sourceManifestBefore") or {}).get("manifestSha256"),
            "fileCount": (top.get("sourceManifestBefore") or {}).get("fileCount"),
            "mismatches": (top.get("sourceManifestBefore") or {}).get("mismatches"),
        },
        "sourceManifestAfter": {
            "manifestSha256": (top.get("sourceManifestAfter") or {}).get("manifestSha256"),
            "fileCount": (top.get("sourceManifestAfter") or {}).get("fileCount"),
            "mismatches": (top.get("sourceManifestAfter") or {}).get("mismatches"),
        },
        "stdout": {"file": top.get("stdoutFile"), "sha256": top.get("stdoutSha256")},
        "stderr": {"file": top.get("stderrFile"), "sha256": top.get("stderrSha256")},
        "result": result,
        "raw": bound_files(path),
    }


def capture_run(path, label):
    path = Path(path).resolve()
    capture = read_json(path / "capture.json")
    return {
        "label": label,
        "kind": "capture-run",
        "directory": str(path.relative_to(ROOT)),
        "argv": capture.get("argv"),
        "cwd": (read_json(path / "command.json").get("cwd")
                if (path / "command.json").is_file() else None),
        "path": (read_json(path / "command.json").get("path")
                 if (path / "command.json").is_file() else None),
        "returncode": capture.get("returncode"),
        "sourceChangedDuringInvocation": capture.get("sourceChangedDuringInvocation"),
        "sourceBeforeDigest": capture.get("sourceBeforeDigest"),
        "sourceAfterDigest": capture.get("sourceAfterDigest"),
        "sourceBeforeFileCount": capture.get("sourceBeforeFileCount"),
        "sourceAfterFileCount": capture.get("sourceAfterFileCount"),
        "bundleSha256": capture.get("bundleSha256"),
        "raw": bound_files(path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", default=[],
                        help="label=directory from checks/capture_suite.py")
    parser.add_argument("--capture", action="append", default=[],
                        help="label=directory from checks/evidence_capture.py")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    manifest_path = ROOT / "protocol-manifest.json"
    baseline_path = ROOT / "baseline" / "protocol-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("frozen protocol-manifest.json is missing")
    manifest = read_json(manifest_path)
    mismatched = []
    for relative, expected in (manifest.get("files") or {}).items():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink() or sha(path) != expected:
            mismatched.append(relative)
    baseline = read_json(baseline_path)
    runs = []
    for item in args.run:
        label, _, directory = item.partition("=")
        if not directory:
            raise SystemExit("--run needs label=directory")
        runs.append(suite_run(ROOT / directory, label))
    captures = []
    for item in args.capture:
        label, _, directory = item.partition("=")
        if not directory:
            raise SystemExit("--capture needs label=directory")
        captures.append(capture_run(ROOT / directory, label))
    payload = {
        "kind": "stdlib-cli-record-validation-evidence-index",
        "version": 1,
        "protocolRevision": 3,
        "state": "pending-codex-review",
        "sourceManifest": {
            "file": "protocol-manifest.json",
            "sha256": sha(manifest_path),
            "fileCount": manifest.get("fileCount"),
            "totalBytes": manifest.get("totalBytes"),
            "baselineManifestSha256": manifest.get("baselineManifestSha256"),
            "baselineFileCount": manifest.get("baselineFileCount"),
            "allFilesMatch": not mismatched,
            "mismatched": mismatched,
        },
        "baselineManifest": {
            "file": "baseline/protocol-manifest.json",
            "sha256": sha(baseline_path),
            "fileCount": baseline.get("fileCount"),
        },
        "runs": runs,
        "captures": captures,
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "admissionIssued": False,
        "formalTargets": "0/16",
        "r3": "blocked",
        "note": "Raw suite/capture directories are bound by every file digest. "
                "Actual pass/total values are copied from the raw result files; "
                "no run was replayed, overwritten or relabelled.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                   encoding="utf-8")
    print(json.dumps({"out": str(out), "runs": len(runs),
                      "captures": len(captures),
                      "manifestAllFilesMatch": not mismatched,
                      "mismatched": mismatched}, sort_keys=True))
    return 0 if not mismatched else 1


if __name__ == "__main__":
    raise SystemExit(main())
