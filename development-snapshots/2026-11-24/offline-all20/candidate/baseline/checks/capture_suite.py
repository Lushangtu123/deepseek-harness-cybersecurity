#!/usr/bin/env python3
"""Capture one exact test-suite invocation in a new, never-overwritten directory.

The helper records the actual argv, cwd, PATH/shim resolution, environment
subset, raw stdout/stderr bytes and digests, the return code, the result-file
digest and the full source-manifest entries before and after the invocation.
It is deliberately source-parameterised: RED runs can point at ``baseline``
while repaired runs point at the candidate root.  No target, fixture, Docker,
BPF program or selfcheck is executed by this helper.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def manifest_path(source_root):
    return Path(source_root) / "protocol-manifest.json"


def source_snapshot(source_root):
    """Recompute every manifest entry, not just the files this run touched."""
    source_root = Path(source_root)
    path = manifest_path(source_root)
    if not path.is_file():
        return {
            "manifestPath": str(path),
            "manifestPresent": False,
            "manifestSha256": None,
            "fileCount": 0,
            "entries": {},
            "baselineManifestSha256": None,
            "baselineFileCount": None,
            "mismatches": [],
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    files = document.get("files")
    if type(files) is not dict:
        raise SystemExit("manifest files is not an object: " + str(path))
    entries = {}
    mismatches = []
    for relative, expected in sorted(files.items()):
        candidate = source_root / relative
        if not candidate.is_file() or os.path.islink(candidate):
            entries[relative] = None
            mismatches.append({"path": relative, "reason": "missing-or-link"})
            continue
        actual = sha(candidate)
        entries[relative] = actual
        if actual != expected:
            mismatches.append({
                "path": relative, "expected": expected, "actual": actual,
            })
    return {
        "manifestPath": str(path),
        "manifestPresent": True,
        "manifestSha256": sha(path),
        "fileCount": len(entries),
        "entries": entries,
        "baselineManifestSha256": document.get("baselineManifestSha256"),
        "baselineFileCount": document.get("baselineFileCount"),
        "mismatches": mismatches,
    }


def shim_resolution():
    path = os.environ.get("PATH", "")
    rows = {}
    for name in ("docker", "bpftrace"):
        resolved = shutil.which(name, path=path)
        rows[name] = {
            "resolvedPath": resolved,
            "sha256": sha(resolved) if resolved and Path(resolved).is_file() else None,
            "source": "PATH",
        }
    for name in ("docker", "bpftrace"):
        candidate = ROOT / "checks" / "shims" / name
        rows["controlled-" + name] = {
            "resolvedPath": str(candidate),
            "sha256": sha(candidate) if candidate.is_file() else None,
            "source": "checks/shims",
        }
    return rows


def environment_subset():
    keys = (
        "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED",
        "LANG", "LC_ALL", "DSH_HOME", "DSH_PROFILE", "DSH_PROFILE_DIR",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    )
    return {key: os.environ.get(key) for key in keys if key in os.environ}


def write_bytes(path, payload):
    with open(path, "wb") as handle:
        handle.write(payload)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--result", default=None)
    parser.add_argument("--expected-failure", action="store_true")
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("no command after --")

    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    source_root = Path(args.source_root).resolve()
    before = source_snapshot(source_root)
    started_utc = utc_now()
    started = time.monotonic()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    result = {
        "kind": "unified-recovery-suite-invocation",
        "version": 1,
        "suite": args.suite,
        "command": command,
        "cwd": str(ROOT),
        "sourceRoot": str(source_root),
        "startedUtc": started_utc,
        "expectedFailure": bool(args.expected_failure),
        "timeoutSeconds": args.timeout,
        "path": env.get("PATH"),
        "shimResolution": shim_resolution(),
        "environment": environment_subset(),
        "sourceManifestBefore": before,
        "launchException": None,
    }
    stdout_payload = b""
    stderr_payload = b""
    returncode = None
    try:
        process = subprocess.run(
            command, cwd=str(ROOT), env=env, capture_output=True,
            timeout=args.timeout,
        )
        returncode = process.returncode
        stdout_payload = process.stdout
        stderr_payload = process.stderr
    except subprocess.TimeoutExpired as error:
        stdout_payload = error.stdout or b""
        stderr_payload = error.stderr or b""
        result["launchException"] = {
            "type": "TimeoutExpired", "message": str(error)[:500],
            "traceback": traceback.format_exc()[-2000:],
        }
    except BaseException as error:  # noqa: BLE001 - preserve launcher failures
        result["launchException"] = {
            "type": type(error).__name__, "message": str(error)[:500],
            "traceback": traceback.format_exc()[-2000:],
        }
    finished = time.monotonic()
    stdout_path = run_dir / "stdout.bin"
    stderr_path = run_dir / "stderr.bin"
    write_bytes(stdout_path, stdout_payload)
    write_bytes(stderr_path, stderr_payload)
    after = source_snapshot(source_root)
    result.update({
        "finishedUtc": utc_now(),
        "finishedMonotonic": finished,
        "intervalSeconds": round(finished - started, 6),
        "returncode": returncode,
        "stdoutFile": str(stdout_path.relative_to(ROOT)),
        "stdoutSha256": sha(stdout_path),
        "stdoutBytes": len(stdout_payload),
        "stderrFile": str(stderr_path.relative_to(ROOT)),
        "stderrSha256": sha(stderr_path),
        "stderrBytes": len(stderr_payload),
        "sourceManifestAfter": after,
        "sourceUnchanged": (
            before["entries"] == after["entries"]
            and before["manifestSha256"] == after["manifestSha256"]
        ),
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "admissionIssued": False,
        "formalTargets": "0/16",
        "r3": "blocked",
    })
    if args.result:
        result_path = Path(args.result).resolve()
        if result_path.is_file():
            result.update({
                "resultFile": str(result_path),
                "resultSha256": sha(result_path),
            })
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                result["resultPassed"] = payload.get("passed")
                result["resultTotal"] = payload.get("total")
                result["resultFailed"] = payload.get("failed")
            except (OSError, ValueError, UnicodeDecodeError) as error:
                result["resultParseError"] = type(error).__name__
        else:
            result["resultFile"] = str(result_path)
            result["resultMissing"] = True
    (run_dir / "run.json").write_text(
        json.dumps(result, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({
        "run": str(run_dir),
        "suite": args.suite,
        "returncode": returncode,
        "resultPassed": result.get("resultPassed"),
        "resultTotal": result.get("resultTotal"),
        "resultFailed": result.get("resultFailed"),
        "sourceUnchanged": result["sourceUnchanged"],
        "launchException": (result.get("launchException") or {}).get("type"),
    }, sort_keys=True))
    if result.get("launchException"):
        return 2
    if args.expected_failure:
        return 0
    return 0 if returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
