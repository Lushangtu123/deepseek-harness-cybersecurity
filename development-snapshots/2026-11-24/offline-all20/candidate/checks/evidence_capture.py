#!/usr/bin/env python3
"""Capture one exact invocation in a new, never-overwritten evidence directory.

The source closure is the *actual frozen manifest mapping* selected by the
caller: ``baseline/protocol-manifest.json`` for RED evidence and the final
candidate ``protocol-manifest.json`` for GREEN evidence.  Every declared file is
hashed; a missing file, a type change, a symlink, an unreadable entry or a
digest mismatch is an explicit rejection recorded in ``run.json``.

TASK, the protocol manifest, bootstrap/launch metadata, historical references
and other metadata are listed separately and are never counted as source files.

Each invocation records the exact argv, cwd, PATH, shim resolution, environment
subset, raw stdout/stderr bytes, the exit status, the result-file digest and
the complete declared path->hash map before and after.  It never imports
product code, never executes a target and never overwrites an existing
directory.
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA_NAMES = (
    "TASK.md",
    "protocol-manifest.json",
    "bootstrap.json",
    "launch.json",
    "implementation-status.json",
    "implementation-worker.py",
    "implementation.events.jsonl",
    "implementation.stderr.txt",
    "launcher.stdout",
    "launcher.stderr",
    "model-preflight.json",
)
HISTORICAL_NAMES = (
    "historical-reference/closure-archive.json",
    "historical-reference/closure-addendum-archive.json",
    "historical-reference/operator-baseline-red-capture.json",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _file_metadata(root, relative, role):
    path = Path(root) / relative
    if not os.path.lexists(path):
        return None
    info = os.lstat(path)
    row = {
        "path": relative,
        "role": role,
        "symlink": stat.S_ISLNK(info.st_mode),
        "regular": stat.S_ISREG(info.st_mode),
        "bytes": info.st_size,
        "sha256": None,
    }
    if row["regular"] and not row["symlink"]:
        row["sha256"] = sha(path)
    return row


def metadata_map(source_root):
    """Metadata is listed here, never in the source file counts."""
    root = Path(source_root)
    entries = {
        "manifest": _file_metadata(root, "protocol-manifest.json",
                                   "selected-frozen-manifest"),
        "task": _file_metadata(root, "TASK.md", "task-text"),
        "baselineManifest": _file_metadata(
            root, "baseline/protocol-manifest.json",
            "historical-baseline-manifest"),
        "historical": [],
        "other": [],
    }
    if entries["baselineManifest"] is not None:
        entries["historical"].append(entries["baselineManifest"])
    for relative in HISTORICAL_NAMES:
        row = _file_metadata(root, relative, "historical-evidence")
        if row is not None:
            entries["historical"].append(row)
    for relative in METADATA_NAMES:
        if relative in {"TASK.md", "protocol-manifest.json"}:
            continue
        row = _file_metadata(root, relative, "invocation-metadata")
        if row is not None:
            entries["other"].append(row)
    return entries


def source_closure(source_root):
    """Hash every file declared by the selected frozen manifest.

    ``ok`` is false for a missing manifest, a damaged manifest shape, a
    declared file that is missing, a symlink, a non-regular type change, an
    unreadable file or a digest mismatch.  A file count is never a substitute
    for the per-path hash map.
    """
    root = Path(source_root).resolve()
    manifest_path = root / "protocol-manifest.json"
    metadata = metadata_map(root)
    result = {
        "sourceRoot": str(root),
        "manifestPath": str(manifest_path),
        "manifestPresent": manifest_path.is_file(),
        "manifestSymlink": os.path.islink(manifest_path),
        "manifestSha256": None,
        "declaredCount": 0,
        "fileCount": 0,
        "entries": {},
        "problems": [],
        "ok": False,
        "sourceOnly": True,
        "metadata": metadata,
    }
    if not result["manifestPresent"] or result["manifestSymlink"]:
        result["problems"].append({
            "path": "protocol-manifest.json",
            "reason": "manifest-missing" if not result["manifestPresent"]
            else "manifest-symlink",
        })
        return result
    result["manifestSha256"] = sha(manifest_path)
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as error:
        result["problems"].append({
            "path": "protocol-manifest.json",
            "reason": "manifest-invalid",
            "detail": type(error).__name__,
        })
        return result
    files = document.get("files") if type(document) is dict else None
    if type(files) is not dict:
        result["problems"].append({
            "path": "protocol-manifest.json",
            "reason": "manifest-files-not-object",
        })
        return result
    result["declaredCount"] = len(files)
    for relative, expected in sorted(files.items()):
        if type(relative) is not str or not relative:
            result["problems"].append({
                "path": str(relative), "reason": "manifest-entry-path"})
            continue
        path = root / relative
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            result["entries"][relative] = None
            result["problems"].append({
                "path": relative, "reason": "missing"})
            continue
        except OSError as error:
            result["entries"][relative] = None
            result["problems"].append({
                "path": relative, "reason": "unreadable",
                "detail": type(error).__name__})
            continue
        if stat.S_ISLNK(info.st_mode):
            result["entries"][relative] = None
            result["problems"].append({
                "path": relative, "reason": "symlink"})
            continue
        if not stat.S_ISREG(info.st_mode):
            result["entries"][relative] = None
            result["problems"].append({
                "path": relative, "reason": "type-change",
                "detail": oct(stat.S_IFMT(info.st_mode))})
            continue
        try:
            actual = sha(path)
        except PermissionError:
            result["entries"][relative] = None
            result["problems"].append({
                "path": relative, "reason": "unreadable",
                "detail": "PermissionError"})
            continue
        except OSError as error:
            result["entries"][relative] = None
            result["problems"].append({
                "path": relative, "reason": "unreadable",
                "detail": type(error).__name__})
            continue
        result["entries"][relative] = actual
        if actual != expected:
            result["problems"].append({
                "path": relative, "reason": "digest-mismatch",
                "expected": expected, "actual": actual})
    result["fileCount"] = sum(1 for value in result["entries"].values()
                              if value is not None)
    result["ok"] = (
        not result["problems"]
        and result["fileCount"] == result["declaredCount"]
    )
    return result


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
        "SCE_ROOT", "SCE_SHIM_STATE", "SCE_DOCKER_LOG", "SCE_RESOLVED_SHIMS",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    )
    return {key: os.environ.get(key) for key in keys if key in os.environ}


def write_bytes(path, payload):
    with open(path, "wb") as handle:
        handle.write(payload)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", "--label", dest="suite", required=True)
    parser.add_argument("--source-root", default=str(ROOT))
    parser.add_argument("--run-dir", "--dir", dest="run_dir", required=True)
    parser.add_argument("--result", "--result-file", dest="result", default=None)
    parser.add_argument("--cwd", default=str(ROOT))
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--copy", action="append", default=[])
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
    cwd = Path(args.cwd).resolve()
    for item in args.copy:
        source, _, relative = item.partition(":")
        if not relative:
            raise SystemExit("--copy needs source:destination")
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(source).read_bytes())

    before = source_closure(source_root)
    (run_dir / "source-before.json").write_text(
        json.dumps(before, sort_keys=True, indent=1) + "\n", encoding="utf-8")

    environment = dict(os.environ)
    for item in args.env:
        key, _, value = item.partition("=")
        environment[key] = value
    result = {
        "kind": "consumer-closure-evidence-capture",
        "version": 2,
        "suite": args.suite,
        "command": command,
        "cwd": str(cwd),
        "sourceRoot": str(source_root),
        "startedUtc": utc_now(),
        "expectedFailure": bool(args.expected_failure),
        "timeoutSeconds": args.timeout,
        "path": environment.get("PATH"),
        "shimResolution": shim_resolution(),
        "environment": environment_subset(),
        "sourceManifestBefore": before,
        "launchException": None,
    }
    stdout_payload = b""
    stderr_payload = b""
    returncode = None
    started = time.monotonic()
    try:
        process = subprocess.run(
            command, cwd=str(cwd), env=environment, capture_output=True,
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
    (run_dir / "returncode.txt").write_text(
        ("launch-failed\n" if returncode is None else str(returncode) + "\n"),
        encoding="utf-8")
    after = source_closure(source_root)
    (run_dir / "source-after.json").write_text(
        json.dumps(after, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    result.update({
        "finishedUtc": utc_now(),
        "finishedMonotonic": finished,
        "intervalSeconds": round(finished - started, 6),
        "returncode": returncode,
        "stdoutFile": "stdout.bin",
        "stdoutSha256": sha(stdout_path),
        "stdoutBytes": len(stdout_payload),
        "stderrFile": "stderr.bin",
        "stderrSha256": sha(stderr_path),
        "stderrBytes": len(stderr_payload),
        "sourceManifestAfter": after,
        "sourceUnchanged": (
            before["entries"] == after["entries"]
            and before["manifestSha256"] == after["manifestSha256"]
        ),
        "sourceClosureOk": before["ok"] and after["ok"],
        "sourceClosureProblems": {
            "before": before["problems"], "after": after["problems"],
        },
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
        result_path = Path(args.result)
        if not result_path.is_absolute():
            result_path = cwd / result_path
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
        "sourceClosureOk": result["sourceClosureOk"],
        "sourceUnchanged": result["sourceUnchanged"],
        "launchException": (result.get("launchException") or {}).get("type"),
    }, sort_keys=True))
    if result.get("launchException"):
        return 2
    if not result["sourceClosureOk"] or not result["sourceUnchanged"]:
        return 3
    if args.expected_failure:
        return 0
    return 0 if returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
