#!/usr/bin/env python3
"""Generate the revision-8 protocol manifest from an explicit file set."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCS = [
    "CONTRACTS-REV3.md",
    "CONTRACTS-REV4.md",
    "CONTRACTS-REV5.md",
    "CONTRACTS-REV6.md",
    "CONTRACTS-REV7.md",
    "CONTRACTS-REV8.md",
    "EXPERIMENT-PROTOCOL.md",
]
FIXTURES = [
    "fixtures/echo/sce_echo_sink.py",
    "fixtures/safe-quoting/sce_quoted_sink.py",
    "fixtures/structure-controlled/sce_raw_sink.py",
    "fixtures/wrong-function/sce_two_sites.py",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise SystemExit("run directory missing: " + str(run_dir))
    files = {}
    for relative in DOCS + ["experiment-plan.json"] + FIXTURES:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit("missing: " + relative)
        files[relative] = sha(path)
    for path in sorted((ROOT / "tools").glob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files[str(path.relative_to(ROOT))] = sha(path)
    for path in sorted((ROOT / "checks").glob("*.py")):
        files[str(path.relative_to(ROOT))] = sha(path)
    for path in sorted((ROOT / "checks" / "shims").glob("*")):
        if path.is_file():
            files[str(path.relative_to(ROOT))] = sha(path)
    for path in sorted((ROOT / "checks" / "diffs").glob("*.diff")):
        if path.is_file():
            files[str(path.relative_to(ROOT))] = sha(path)
    evidence = ROOT / "checks" / "regression-evidence"
    if evidence.is_dir():
        for path in sorted(evidence.rglob("*")):
            if path.is_file():
                files[str(path.relative_to(ROOT))] = sha(path)
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "static-checks.json":
            files[str(path.relative_to(ROOT))] = sha(path)
    total = sum((ROOT / relative).stat().st_size for relative in files)
    manifest = {
        "excluded": [
            "baseline/",
            "protocol-manifest.json",
            "REPORT.md",
            "phase-result.json",
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
            "checks/current-run.json",
            "checks/validation-summary.json",
            "checks/evidence-runs/**/static-checks.json",
            "checks/tmp/",
            "**/__pycache__/",
            "state/",
            "runs/",
            "prepare/",
            "codex-review/",
            "preflight/",
        ],
        "fileCount": len(files),
        "files": files,
        "kind": "stdlib-cli-admission-protocol-manifest",
        "note": "Do not modify any listed file after this manifest is generated. "
                "The runner refuses any admitted action whose manifest bytes differ.",
        "phase": "final-stage-recheck",
        "protocolRevision": 3,
        "selfExcluded": True,
        "state": "pending-codex-review",
        "targetExecutions": 0,
        "totalBytes": total,
        "version": 3,
    }
    payload = json.dumps(manifest, sort_keys=True, indent=1) + "\n"
    (ROOT / "protocol-manifest.json").write_text(payload, encoding="utf-8")
    print(json.dumps({"fileCount": len(files), "totalBytes": total,
                      "sha256": sha(ROOT / "protocol-manifest.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
