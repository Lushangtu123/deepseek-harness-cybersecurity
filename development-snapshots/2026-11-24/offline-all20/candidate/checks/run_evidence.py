#!/usr/bin/env python3
"""Run each evidence suite in its own unique UTC run directory.

Every suite gets a ``run.json`` with the actual command, UTC and monotonic
interval, return code, raw stdout/stderr digests and source/test/tool SHA-256
before and after.  No old result is copied into a new run and no run is deleted.
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline"
RUNS = ROOT / "checks" / "evidence-runs"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_files(root):
    root = Path(root)
    files = []
    if (root / "docs").is_dir():
        files.extend(sorted((root / "docs").glob("*.md")))
    else:
        files.extend(sorted(root.glob("CONTRACTS-REV*.md")))
        if (root / "EXPERIMENT-PROTOCOL.md").is_file():
            files.append(root / "EXPERIMENT-PROTOCOL.md")
    for relative in ("experiment-plan.json", "DIAGNOSTICS-CONTRACT.md",
                     "REPAIR-CONTRACT.md", "BUFFER-PREFLIGHT-CONTRACT.md",
                     "BUFFER-V2-CONTRACT.md", "END-LF-CONTRACT.md",
                     "RECORD-VALIDATION-CONTRACT.md",
                     "RECORD-VALIDATION-SUPPORT.md"):
        path = root / relative
        if path.is_file():
            files.append(path)
    for directory, pattern in (
        ("tools", "*"),
        ("checks", "*.py"),
        ("checks/shims", "*"),
        ("fixtures", "**/*.py"),
    ):
        base = root / directory
        if base.is_dir():
            files.extend(path for path in sorted(base.glob(pattern)) if path.is_file())
    return [path for path in files if "__pycache__" not in path.parts]


def source_hashes(root):
    return {
        str(path.relative_to(Path(root))): sha(path)
        for path in stable_files(root)
    }


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=1) + "\n",
                    encoding="utf-8")


def run_suite(suite, command, run_dir, source_root, timeout=1800,
              expected_failure=False):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    before = source_hashes(source_root)
    started_utc = utc_now()
    started_monotonic = time.monotonic()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    process = subprocess.run(
        command, cwd=str(ROOT), capture_output=True, text=True, env=env,
        timeout=timeout,
    )
    finished_monotonic = time.monotonic()
    after = source_hashes(source_root)
    stdout_path.write_text(process.stdout, encoding="utf-8")
    stderr_path.write_text(process.stderr, encoding="utf-8")
    result_path = None
    for token in command:
        if token.endswith(".json") and "/evidence-runs/" in token:
            result_path = Path(token)
            break
    record = {
        "kind": "observer-early-exit-diagnostics-suite-run",
        "version": 1,
        "suite": suite,
        "command": [str(item) for item in command],
        "commandLine": " ".join(str(item) for item in command),
        "cwd": str(ROOT),
        "sourceRoot": str(source_root),
        "startedUtc": started_utc,
        "finishedUtc": utc_now(),
        "startedMonotonic": started_monotonic,
        "finishedMonotonic": finished_monotonic,
        "intervalSeconds": round(finished_monotonic - started_monotonic, 6),
        "returncode": process.returncode,
        "expectedFailure": bool(expected_failure),
        "stdoutFile": str(stdout_path.relative_to(ROOT)),
        "stdoutSha256": sha(stdout_path),
        "stderrFile": str(stderr_path.relative_to(ROOT)),
        "stderrSha256": sha(stderr_path),
        "sourceSha256Before": before,
        "sourceSha256After": after,
        "sourceUnchanged": before == after,
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "admissionIssued": False,
        "r3": "blocked",
    }
    if result_path is not None and result_path.is_file():
        record["resultFile"] = str(result_path.relative_to(ROOT))
        record["resultSha256"] = sha(result_path)
        try:
            result = json.loads(result_path.read_text())
            record["resultPassed"] = result.get("passed")
            record["resultTotal"] = result.get("total")
            record["resultFailed"] = result.get("failed")
        except (OSError, ValueError):
            pass
    write_json(run_dir / "run.json", record)
    return record


def after_suites(run_root):
    commands = [
        ("baseline", [sys.executable, "checks/verify_baseline.py",
                      "--out", str(run_root / "baseline-verification.json")]),
        ("compile", [sys.executable, "checks/compile_check.py",
                     "--out", str(run_root / "compile-results.json")]),
        ("buffer", [sys.executable, "checks/run_buffer_preflight_checks.py",
                    "--out", str(run_root / "buffer-preflight-results.json")]),
        ("original28", [sys.executable, "checks/run_regressions.py",
                        "--out", str(run_root / "regression-results.json"),
                        "--evidence", str(run_root / "regression-evidence")]),
        ("rev6", [sys.executable, "checks/run_rev6_checks.py",
                  "--out", str(run_root / "rev6-results.json")]),
        ("rev7", [sys.executable, "checks/run_rev7_checks.py",
                  "--out", str(run_root / "rev7-results.json")]),
        ("rev8", [sys.executable, "checks/run_rev8_checks.py",
                  "--out", str(run_root / "rev8-results.json")]),
        ("diagnostics", [sys.executable, "checks/run_diagnostics_checks.py",
                         "--root", str(ROOT),
                         "--out", str(run_root / "diagnostics-results.json")]),
        ("repair", [sys.executable, "checks/run_repair_checks.py",
                    "--root", str(ROOT),
                    "--out", str(run_root / "repair-results.json")]),
        ("static", [sys.executable, "checks/static_check.py",
                    "--run-dir", str(run_root),
                    "--out", str(run_root / "static-checks.json")]),
    ]
    records = []
    for suite, command in commands:
        target = run_root / ("suite-" + suite)
        if suite in ("baseline", "compile", "buffer", "original28", "rev6",
                     "rev7", "rev8", "diagnostics"):
            # Results are written at the run root so the static checker can
            # bind one immutable run directory.
            result = run_suite(suite, command, target, ROOT)
        else:
            result = run_suite(suite, command, target, ROOT)
        records.append(result)
        print("%-12s rc=%s result=%s" % (suite, result["returncode"],
                                         result.get("resultFailed")))
    return records


def before_suites(run_root):
    command = [sys.executable, "checks/run_diagnostics_checks.py",
               "--root", str(BASELINE),
               "--out", str(run_root / "diagnostics-before-results.json")]
    record = run_suite("diagnostics-before", command,
                       run_root / "suite-diagnostics-before", BASELINE,
                       expected_failure=True)
    print("%-18s rc=%s result=%s" % ("diagnostics-before", record["returncode"],
                                     record.get("resultFailed")))
    return [record]


def red_suites(run_root):
    """Focused RED evidence only; the old module-absent baseline 20 are not rerun."""
    command = [sys.executable, "checks/run_repair_checks.py",
               "--root", str(BASELINE),
               "--out", str(run_root / "repair-before-results.json")]
    record = run_suite("repair-before", command,
                       run_root / "suite-repair-before", BASELINE,
                       expected_failure=True)
    print("%-18s rc=%s result=%s" % ("repair-before", record["returncode"],
                                     record.get("resultFailed")))
    return [record]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after", "red"), required=True)
    parser.add_argument("--run-dir", default=None)
    args = parser.parse_args(argv)
    if args.run_dir:
        run_root = Path(args.run_dir).resolve()
    else:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        run_root = RUNS / (stamp + "-" + secrets.token_hex(4) + "-" + args.phase)
    run_root.mkdir(parents=True, exist_ok=True)
    source_root = BASELINE if args.phase in ("before", "red") else ROOT
    before = source_hashes(source_root)
    started_utc = utc_now()
    started_monotonic = time.monotonic()
    if args.phase == "before":
        records = before_suites(run_root)
    elif args.phase == "red":
        records = red_suites(run_root)
    else:
        records = after_suites(run_root)
    after = source_hashes(source_root)
    failed = [item for item in records
              if item["returncode"] != 0 and not item["expectedFailure"]]
    top = {
        "kind": "observer-early-exit-diagnostics-evidence-run",
        "version": 1,
        "diagnosticVersion": 1,
        "protocolRevision": 3,
        "phase": args.phase,
        "runId": run_root.name,
        "runDir": str(run_root.relative_to(ROOT)),
        "sourceRoot": str(source_root),
        "startedUtc": started_utc,
        "finishedUtc": utc_now(),
        "startedMonotonic": started_monotonic,
        "finishedMonotonic": time.monotonic(),
        "intervalSeconds": round(time.monotonic() - started_monotonic, 6),
        "sourceSha256Before": before,
        "sourceSha256After": after,
        "sourceUnchanged": before == after,
        "suites": records,
        "failedSuites": [item["suite"] for item in failed],
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "admissionIssued": False,
        "r3": "blocked",
        "note": "Actual commands and raw outputs are preserved in each suite "
                "subdirectory. No old result was copied into this run.",
    }
    write_json(run_root / "run.json", top)
    print(json.dumps({"runId": run_root.name, "failedSuites": top["failedSuites"],
                      "intervalSeconds": top["intervalSeconds"]}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
