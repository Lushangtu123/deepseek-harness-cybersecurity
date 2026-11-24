#!/usr/bin/env python3
"""Build the recovery-close evidence index outside the source manifest.

Every capture directory is read, never rewritten.  Initial RED, supplemental
RED, historical old-script replays and final post-freeze runs are separate
sections so a historical reproduction is never relabelled as a final pass.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "checks" / "evidence-index.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def bound_files(directory):
    directory = Path(directory).resolve()
    rows = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rows.append({
                "file": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            })
    return rows


def result_summary(capture, directory):
    result_file = capture.get("resultFile")
    if not result_file:
        command_path = Path(directory) / "command.json"
        if command_path.is_file():
            result_file = read_json(command_path).get("resultFile")
    if not result_file:
        return None
    path = Path(result_file)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return {"path": str(path), "missing": True}
    value = read_json(path)
    return {
        "path": str(path.relative_to(ROOT)) if str(path).startswith(str(ROOT)) else str(path),
        "sha256": sha(path),
        "passed": value.get("passed"),
        "total": value.get("total"),
        "failed": value.get("failed"),
    }


def capture_summary(directory, section):
    directory = Path(directory).resolve()
    record_path = directory / "capture.json"
    if not record_path.is_file():
        return {"path": str(directory), "error": "capture.json missing"}
    capture = read_json(record_path)
    stdout = (directory / "stdout.bin").read_bytes() if (directory / "stdout.bin").is_file() else b""
    stderr = (directory / "stderr.bin").read_bytes() if (directory / "stderr.bin").is_file() else b""
    return {
        "section": section,
        "label": capture.get("label"),
        "path": str(directory.relative_to(ROOT)) if directory.is_relative_to(ROOT) else str(directory),
        "command": capture.get("argv"),
        "returncode": capture.get("returncode"),
        "stdoutBytes": capture.get("stdoutBytes"),
        "stderrBytes": capture.get("stderrBytes"),
        "stdoutHead": stdout.decode("utf-8", "replace")[:2000],
        "stderrHead": stderr.decode("utf-8", "replace")[:2000],
        "sourceBeforeDigest": capture.get("sourceBeforeDigest"),
        "sourceAfterDigest": capture.get("sourceAfterDigest"),
        "sourceChangedDuringInvocation": capture.get("sourceChangedDuringInvocation"),
        "sourceBeforeFileCount": capture.get("sourceBeforeFileCount"),
        "sourceAfterFileCount": capture.get("sourceAfterFileCount"),
        "resultFileSha256": capture.get("resultFileSha256"),
        "bundleSha256": capture.get("bundleSha256"),
        "resultSummary": result_summary(capture, directory),
        "raw": bound_files(directory),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial", action="append", default=[])
    parser.add_argument("--supplemental", action="append", default=[])
    parser.add_argument("--history", action="append", default=[])
    parser.add_argument("--final", action="append", default=[])
    parser.add_argument("--gap", action="append", default=[])
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    manifest_path = ROOT / "protocol-manifest.json"
    manifest = read_json(manifest_path)
    files = manifest.get("files") or {}
    mismatched = []
    for relative, expected in files.items():
        path = ROOT / relative
        if not path.is_file() or sha(path) != expected:
            mismatched.append(relative)
    index = {
        "kind": "recovery-close-evidence-index",
        "protocolRevision": 3,
        "offlineOnly": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "selfcheckExecutions": 0,
        "admissionIssued": False,
        "preflightExecuted": False,
        "formalTargets": "0/16",
        "r3": "blocked",
        "manifest": {
            "path": "protocol-manifest.json",
            "sha256": sha(manifest_path),
            "fileCount": manifest.get("fileCount"),
            "listedFiles": len(files),
            "mismatched": mismatched,
            "allFilesMatch": not mismatched,
        },
        "sections": {
            "initialRed": [capture_summary(path, "initial-red") for path in args.initial],
            "supplementalRed": [capture_summary(path, "supplemental-red")
                                for path in args.supplemental],
            "historyReplayOnRepairedSource": [
                capture_summary(path, "history-replay-not-pass") for path in args.history
            ],
            "finalPostFreeze": [capture_summary(path, "final-post-freeze")
                                for path in args.final],
        },
        "gaps": list(args.gap),
        "note": "Initial RED was run against the read-only baseline before product "
                "repair. Historical old-script replays on repaired source abort or "
                "assert because they encode the old outcomes; they are not product "
                "passes and not new execution evidence. Final runs are against one "
                "frozen source manifest. All suites are simulated/offline; no real "
                "Docker, bpftrace, target, fixture, selfcheck, preflight, admission "
                "or formal batch was run.",
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output),
        "sha256": sha(output),
        "manifestMismatched": mismatched,
        "initial": len(index["sections"]["initialRed"]),
        "supplemental": len(index["sections"]["supplementalRed"]),
        "history": len(index["sections"]["historyReplayOnRepairedSource"]),
        "final": len(index["sections"]["finalPostFreeze"]),
    }, sort_keys=True))
    return 0 if not mismatched else 1


if __name__ == "__main__":
    raise SystemExit(main())
