#!/usr/bin/env python3
"""Bind END-LF RED, final suites, manifest and historical raw into an index.

This index is deliberately outside ``protocol-manifest.json`` and is written
only after source/test/contract freeze.  It never rewrites a RED run, final run
or manifest.  Every listed file is bound by bytes and SHA-256.
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


def bound_files(path):
    path = Path(path)
    rows = []
    for item in sorted(path.rglob("*")):
        if item.is_file():
            rows.append({
                "file": str(item.relative_to(ROOT)),
                "bytes": item.stat().st_size,
                "sha256": sha(item),
            })
    return rows


def summary(run_dir, note):
    run_dir = Path(run_dir)
    record = read_json(run_dir / "run.json") if (run_dir / "run.json").is_file() else {}
    result = None
    result_file = record.get("resultFile")
    if result_file and (ROOT / result_file).is_file():
        value = read_json(ROOT / result_file)
        result = {
            "file": result_file,
            "sha256": sha(ROOT / result_file),
            "passed": value.get("passed"),
            "failed": value.get("failed"),
            "total": value.get("total"),
        }
    return {
        "path": str(run_dir.relative_to(ROOT)),
        "runJson": str((run_dir / "run.json").relative_to(ROOT))
        if (run_dir / "run.json").is_file() else None,
        "runJsonSha256": sha(run_dir / "run.json")
        if (run_dir / "run.json").is_file() else None,
        "command": record.get("command"),
        "commandLine": record.get("commandLine"),
        "returncode": record.get("returncode"),
        "startedUtc": record.get("startedUtc"),
        "finishedUtc": record.get("finishedUtc"),
        "intervalSeconds": record.get("intervalSeconds"),
        "sourceUnchanged": record.get("sourceUnchanged"),
        "result": result,
        "note": note,
        "raw": bound_files(run_dir),
    }


def standalone_summary(run_dir, note):
    run_dir = Path(run_dir)
    result_path = run_dir / "red-results.json"
    result = read_json(result_path) if result_path.is_file() else {}
    command_path = run_dir / "command.txt"
    return {
        "path": str(run_dir.relative_to(ROOT)),
        "command": command_path.read_text(encoding="utf-8").strip()
        if command_path.is_file() else None,
        "returncode": int((run_dir / "returncode.txt").read_text().strip())
        if (run_dir / "returncode.txt").is_file() else None,
        "resultFile": str(result_path.relative_to(ROOT))
        if result_path.is_file() else None,
        "resultSha256": sha(result_path) if result_path.is_file() else None,
        "passed": result.get("passed"),
        "failed": result.get("failed"),
        "total": result.get("total"),
        "sourceBeforeSha256": sha(run_dir / "source-before.json")
        if (run_dir / "source-before.json").is_file() else None,
        "note": note,
        "raw": bound_files(run_dir),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-run", action="append", required=True)
    parser.add_argument("--closure-run", action="append", default=[])
    parser.add_argument("--red-run", action="append", required=True)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    manifest_path = ROOT / "protocol-manifest.json"
    manifest = read_json(manifest_path)
    proof = ROOT / "proof" / "observer.raw"
    red = [standalone_summary(path, "Pre-implementation RED preserved as-is; not "
                              "replayed and not a post-freeze execution receipt.")
           for path in args.red_run]
    final = [summary(path, "Post-freeze final suite against the frozen manifest bytes.")
             for path in args.final_run]
    closures = [summary(path, "Post-freeze focused closure/regression run.")
                for path in args.closure_run]
    payload = {
        "kind": "end-lf-padding-v1-evidence-index",
        "version": 1,
        "protocolRevision": 3,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "state": "pending-codex-review",
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "selfcheckExecuted": False,
        "admissionIssued": False,
        "formalTargets": "0/16",
        "r3": "blocked",
        "manifest": {
            "file": "protocol-manifest.json",
            "sha256": sha(manifest_path),
            "fileCount": manifest.get("fileCount"),
            "totalBytes": manifest.get("totalBytes"),
            "sourceOnly": manifest.get("sourceOnly") is True,
            "selfExcluded": "protocol-manifest.json" not in (manifest.get("files") or {}),
            "observationProtocol": manifest.get("observationProtocol"),
            "framingPolicy": manifest.get("framingPolicy"),
            "baselineManifestSha256": manifest.get("baselineManifestSha256"),
            "baselineFileCount": manifest.get("baselineFileCount"),
        },
        "historicalRawDiagnostic": {
            "path": "proof/observer.raw",
            "bytes": proof.stat().st_size,
            "sha256": sha(proof),
            "acceptedEvidence": False,
            "newExecution": False,
            "note": "Unchanged 306-byte historical stream; parsed only as "
                    "diagnostic data, never a new post-freeze receipt.",
        },
        "initialRedRuns": red,
        "postFreezeFinalSuites": final,
        "postFreezeClosureRuns": closures,
        "rawEvidenceIndex": {
            "red": [row["raw"] for row in red],
            "final": [row["raw"] for row in final],
            "closures": [row["raw"] for row in closures],
        },
    }
    output = Path(args.out)
    output.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                      encoding="utf-8")
    print(json.dumps({"out": str(output.relative_to(ROOT)),
                      "sha256": sha(output),
                      "manifestSha256": payload["manifest"]["sha256"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
