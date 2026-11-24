#!/usr/bin/env python3
"""Write the END-LF source-only protocol manifest from explicit paths.

The manifest excludes itself, README/REPORT deliverables, proof/baseline data,
raw evidence runs, temporary sandboxes and the evidence index.  It is written
once after source/test/contract freeze and is never rewritten by the runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline"
BASELINE_MANIFEST = BASELINE / "protocol-manifest.json"

CONTRACTS = [
    "BUFFER-PREFLIGHT-CONTRACT.md",
    "BUFFER-V2-CONTRACT.md",
    "DIAGNOSTICS-CONTRACT.md",
    "REPAIR-CONTRACT.md",
    "END-LF-CONTRACT.md",
    "FORMAL-ADMISSION-CONTRACT.md",
    "FORMAL-ADMISSION-SUPPORT.md",
]
SOURCE_REFERENCES = [
    ("source-evidence/bpftrace-v0.20.2-utils.cpp",
     "pinned-upstream-hex-format-buffer"),
    ("source-evidence/format_string.cpp", "pinned-upstream-format-string-flags"),
    ("source-evidence/printf.cpp", "pinned-upstream-printable-buffer-call"),
    ("source-evidence/upstream-source.json", "pinned-upstream-commit-metadata"),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "protocol-manifest.json"))
    args = parser.parse_args(argv)
    baseline = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    files = {}
    for relative in CONTRACTS + ["experiment-plan.json"]:
        files[relative] = sha(ROOT / relative)
    for path in sorted((ROOT / "docs").glob("*.md")):
        files[str(path.relative_to(ROOT))] = sha(path)
    for path in sorted((ROOT / "fixtures").rglob("*.py")):
        files[str(path.relative_to(ROOT))] = sha(path)
    excluded_top_level = {
        "checks/evidence-index.json",
        "checks/current-run.json",
        "checks/validation-summary.json",
        "checks/static-checks.json",
        "checks/compile-results.json",
        "checks/regression-results.json",
        "checks/end-lf-results.json",
        "checks/buffer-preflight-results.json",
        "checks/formal-admission-results.json",
        "checks/baseline-verification.json",
    }
    for directory in ("tools", "checks"):
        for path in sorted((ROOT / directory).glob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                relative = str(path.relative_to(ROOT))
                if relative in excluded_top_level:
                    continue
                if relative.startswith("checks/") and (
                        relative.endswith("-results.json")
                        or relative.endswith("-verification.json")):
                    continue
                files[relative] = sha(path)
    for path in sorted((ROOT / "checks" / "shims").glob("*")):
        if path.is_file():
            files[str(path.relative_to(ROOT))] = sha(path)
    formal_dir = ROOT / "checks" / "formal_admission"
    if formal_dir.is_dir():
        for path in sorted(formal_dir.rglob("*.py")):
            if "__pycache__" not in path.parts:
                files[str(path.relative_to(ROOT))] = sha(path)
    total = sum((ROOT / relative).stat().st_size for relative in files)
    references = []
    for relative, role in SOURCE_REFERENCES:
        path = ROOT / relative
        references.append({
            "path": relative,
            "role": role,
            "bytes": path.stat().st_size,
            "sha256": sha(path),
            "executable": False,
            "runtimeLoaded": False,
        })
    payload = {
        "kind": "stdlib-cli-admission-protocol-manifest",
        "version": 3,
        "phase": "formal-buffer-v2-admission-offline-implementation",
        "state": "pending-codex-review",
        "protocolRevision": 3,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "bufferParser": "tools/buffer_protocol_v2.py",
        "bufferParserSha256": files["tools/buffer_protocol_v2.py"],
        "bufferTemplate": "tools/observer_template_buffer_v2.bt",
        "bufferTemplateSha256": files["tools/observer_template_buffer_v2.bt"],
        "baselineManifestSha256": sha(BASELINE_MANIFEST),
        "baselineFileCount": baseline.get("fileCount"),
        "baselineTotalBytes": baseline.get("totalBytes"),
        "historicalRawSha256":
            "5e61c6b689cf4e31905fb6e2863648a0c1d0376446d8dc237189b9cc8627806b",
        "historicalRawBytes": 306,
        "files": files,
        "fileCount": len(files),
        "totalBytes": total,
        "selfExcluded": True,
        "sourceOnly": True,
        "sourceReferences": references,
        "sourceEvidenceInRuntimeClosure": False,
        "excluded": [
            "protocol-manifest.json",
            "phase-result.json",
            "REPORT.md",
            "TASK.md",
            "checks/evidence-index.json",
            "checks/current-run.json",
            "checks/validation-summary.json",
            "checks/end-lf-results.json",
            "checks/buffer-preflight-results.json",
            "checks/formal-admission-results.json",
            "checks/evidence-runs/",
            "checks/formal_admission/red-evidence/",
            "checks/formal_admission/evidence/",
            "checks/evidence-runs/",
            "checks/tmp/",
            "checks/diffs/",
            "baseline/",
            "proof/",
            "source-evidence/",
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
        "preflightExecuted": False,
        "selfcheckExecutions": 0,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "formalTargets": "0/16",
        "realContainers": 0,
        "realBpftrace": 0,
        "admissionIssued": False,
        "r3": "blocked",
        "note": "Source-only manifest for bounded formal buffer-v2 admission. "
                "Do not modify any listed byte after this write. The historical "
                "306-byte raw stream and the old successful preflight are "
                "diagnostic/historical data, not a new execution receipt. No real "
                "Docker/bpftrace/preflight/selfcheck/target was run.",
    }
    output = Path(args.out)
    output.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                      encoding="utf-8")
    print(json.dumps({"fileCount": len(files), "totalBytes": total,
                      "sha256": sha(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
