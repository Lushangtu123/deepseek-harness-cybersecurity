#!/usr/bin/env python3
"""Capture one command invocation in a brand-new evidence directory.

This helper is deliberately conservative:

* the destination must not exist (a unique directory per invocation);
* the exact argv, working directory, PATH and a before/after source snapshot
  are written;
* raw stdout/stderr are written as bytes, never re-encoded or overwritten;
* a bundle digest and an optional result-file digest are returned.

It never imports product code and never executes a target.  The caller decides
whether the command is a test, a RED reproduction or a regression suite.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TOP_LEVEL_SOURCE = (
    "BUFFER-PREFLIGHT-CONTRACT.md",
    "BUFFER-V2-CONTRACT.md",
    "DIAGNOSTICS-CONTRACT.md",
    "END-LF-CONTRACT.md",
    "FORMAL-ADMISSION-CONTRACT.md",
    "FORMAL-ADMISSION-SUPPORT.md",
    "RECOVERY-CLOSE-CONTRACT.md",
    "RECOVERY-CLOSE-SUPPORT.md",
    "ASSOCIATION-RECOVERY-CONTRACT.md",
    "ASSOCIATION-RECOVERY-SUPPORT.md",
    "REPAIR-CONTRACT.md",
    "TASK.md",
    "experiment-plan.json",
    "protocol-manifest.json",
)
SOURCE_DIRECTORIES = ("tools", "checks", "docs", "fixtures")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def _excluded(relative):
    parts = relative.split("/")
    if parts[0] in {"baseline", "historical-reference", "headless-home", "proof",
                    "source-evidence"}:
        return True
    if relative.startswith("checks/evidence-runs/"):
        return True
    if relative.startswith("checks/tmp/"):
        return True
    if relative.startswith("checks/regression-evidence/"):
        return True
    if relative in {"checks/current-run.json", "checks/evidence-index.json",
                    "checks/validation-summary.json", "checks/static-checks.json"}:
        return True
    if relative.startswith("checks/diffs/"):
        return True
    if "__pycache__" in parts:
        return True
    if relative.endswith(("regression-results.json", "buffer-preflight-results.json",
                          "end-lf-results.json", "diagnostics-results.json",
                          "compile-results.json",
                          "repair-results.json", "rev6-results.json",
                          "rev7-results.json", "rev8-results.json",
                          "formal-admission-results.json", "baseline-verification.json")):
        return True
    return False


def source_snapshot():
    """Hash the current source/test/document bytes, excluding evidence and history."""
    files = {}
    for relative in TOP_LEVEL_SOURCE:
        path = ROOT / relative
        if path.is_file():
            files[relative] = {"sha256": sha_file(path), "bytes": path.stat().st_size}
    for directory in SOURCE_DIRECTORIES:
        base = ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(ROOT))
            if _excluded(relative):
                continue
            files[relative] = {"sha256": sha_file(path), "bytes": path.stat().st_size}
    digest = sha_bytes(json.dumps(files, sort_keys=True, separators=(",", ":"))
                       .encode("utf-8"))
    baseline_manifest = ROOT / "baseline" / "protocol-manifest.json"
    candidate_manifest = ROOT / "protocol-manifest.json"
    return {
        "root": str(ROOT),
        "fileCount": len(files),
        "digest": digest,
        "files": files,
        "baselineManifestPath": "baseline/protocol-manifest.json",
        "baselineManifestSha256": sha_file(baseline_manifest) if baseline_manifest.is_file() else None,
        "candidateManifestPath": "protocol-manifest.json",
        "candidateManifestSha256": sha_file(candidate_manifest) if candidate_manifest.is_file() else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--result-file", default=None)
    parser.add_argument("--copy", action="append", default=[],
                        help="source:destination copied into the new evidence dir")
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        raise SystemExit("no command")
    destination = Path(args.dir).resolve()
    if destination.exists():
        raise SystemExit("evidence directory already exists: " + str(destination))
    destination.mkdir(parents=True)
    for item in args.copy:
        source, _, relative = item.partition(":")
        if not relative:
            raise SystemExit("--copy needs source:destination")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(source).read_bytes())
    before = source_snapshot()
    (destination / "source-before.json").write_text(
        json.dumps(before, sort_keys=True, indent=1) + "\n", encoding="utf-8")

    environment = dict(os.environ)
    for item in args.env:
        key, _, value = item.partition("=")
        environment[key] = value
    command_record = {
        "kind": "recovery-close-evidence-invocation",
        "label": args.label,
        "argv": list(args.command),
        "cwd": str(ROOT),
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "path": environment.get("PATH"),
        "resultFile": args.result_file,
        "uniqueDirectory": True,
    }
    (destination / "command.json").write_text(
        json.dumps(command_record, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    completed = subprocess.run(
        list(args.command), cwd=str(ROOT), env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    (destination / "stdout.bin").write_bytes(completed.stdout)
    (destination / "stderr.bin").write_bytes(completed.stderr)
    (destination / "returncode.txt").write_text(str(completed.returncode) + "\n",
                                                encoding="utf-8")
    after = source_snapshot()
    (destination / "source-after.json").write_text(
        json.dumps(after, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    result_sha = None
    if args.result_file:
        result_path = Path(args.result_file)
        if not result_path.is_absolute():
            result_path = ROOT / result_path
        if result_path.is_file():
            result_sha = sha_file(result_path)
    changed = before["digest"] != after["digest"]
    payload = {
        "kind": "recovery-close-evidence-capture",
        "label": args.label,
        "directory": str(destination),
        "argv": list(args.command),
        "returncode": completed.returncode,
        "stdoutBytes": len(completed.stdout),
        "stderrBytes": len(completed.stderr),
        "sourceBeforeDigest": before["digest"],
        "sourceAfterDigest": after["digest"],
        "sourceBeforeFileCount": before["fileCount"],
        "sourceAfterFileCount": after["fileCount"],
        "sourceChangedDuringInvocation": changed,
        "resultFileSha256": result_sha,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
    }
    bundle_files = sorted(path.name for path in destination.iterdir() if path.is_file())
    bundle_hasher = hashlib.sha256()
    for name in bundle_files:
        bundle_hasher.update(name.encode("utf-8") + b"\0")
        bundle_hasher.update((destination / name).read_bytes())
    payload["bundleSha256"] = bundle_hasher.hexdigest()
    (destination / "capture.json").write_text(
        json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in (
        "label", "returncode", "sourceChangedDuringInvocation",
        "resultFileSha256", "bundleSha256")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
