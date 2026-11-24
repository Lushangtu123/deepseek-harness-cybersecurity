#!/usr/bin/env python3
"""Run the END-LF focused/affected suites in unique UTC directories.

All suites are offline/synthetic and use ``checks/shims`` for Docker/bpftrace.
The script never runs a real container, observer, selfcheck, compiler, fixture,
target or deployment.  Byte snapshots before/after each suite come from
``checks/run_evidence.py`` and include changed tools/tests/contracts.
"""
import argparse
import json
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "checks"))

import run_evidence  # noqa: E402

RUNS = ROOT / "checks" / "evidence-runs"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default=None)
    args = parser.parse_args(argv)
    if args.run_dir:
        run_root = Path(args.run_dir).resolve()
    else:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        run_root = RUNS / (stamp + "-" + secrets.token_hex(4) + "-end-lf-final")
    run_root.mkdir(parents=True, exist_ok=True)
    commands = [
        ("baseline", [sys.executable, "checks/verify_baseline.py",
                      "--out", str(run_root / "baseline-verification.json")]),
        ("compile", [sys.executable, "checks/compile_check.py",
                     "--out", str(run_root / "compile-results.json")]),
        ("end-lf", [sys.executable, "checks/run_end_lf_checks.py",
                    "--out", str(run_root / "end-lf-results.json")]),
        ("buffer", [sys.executable, "checks/run_buffer_preflight_checks.py",
                    "--out", str(run_root / "buffer-preflight-results.json")]),
        ("buffer-v2-red", [sys.executable, "checks/run_buffer_v2_red.py",
                           "--out", str(run_root / "buffer-v2-red-results.json")]),
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
    ]
    before = run_evidence.source_hashes(ROOT)
    started = time.monotonic()
    records = []
    for suite, command in commands:
        result = run_evidence.run_suite(
            suite, command, run_root / ("suite-" + suite), ROOT, timeout=1800
        )
        records.append(result)
        print("%-14s rc=%s failed=%s" % (suite, result["returncode"],
                                         result.get("resultFailed")))
    static_command = [sys.executable, "checks/static_check.py",
                      "--run-dir", str(run_root),
                      "--out", str(run_root / "static-checks.json")]
    static = run_evidence.run_suite("static", static_command,
                                    run_root / "suite-static", ROOT, timeout=1800)
    records.append(static)
    print("%-14s rc=%s failed=%s" % ("static", static["returncode"],
                                     static.get("resultFailed")))
    after = run_evidence.source_hashes(ROOT)
    failed = [item["suite"] for item in records if item["returncode"] != 0]
    payload = {
        "kind": "end-lf-padding-v1-final-evidence-run",
        "version": 1,
        "phase": "end-lf-final",
        "runId": run_root.name,
        "runDir": str(run_root.relative_to(ROOT)),
        "startedUtc": run_evidence.utc_now(),
        "finishedUtc": run_evidence.utc_now(),
        "intervalSeconds": round(time.monotonic() - started, 6),
        "sourceSha256Before": before,
        "sourceSha256After": after,
        "sourceUnchanged": before == after,
        "suites": records,
        "failedSuites": failed,
        "simulated": True,
        "protocolRevision": 3,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "selfcheckExecuted": False,
        "admissionIssued": False,
        "formalTargets": "0/16",
        "r3": "blocked",
    }
    run_evidence.write_json(run_root / "run.json", payload)
    print(json.dumps({"runDir": payload["runDir"],
                      "failedSuites": failed,
                      "sourceUnchanged": payload["sourceUnchanged"]},
                     sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
