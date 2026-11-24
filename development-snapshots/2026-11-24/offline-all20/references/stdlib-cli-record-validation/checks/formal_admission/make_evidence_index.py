#!/usr/bin/env python3
"""Build the final evidence index separately from the frozen manifest."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "checks" / "evidence-runs"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def read_text(path):
    path = Path(path)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def result_summary(value):
    if not isinstance(value, dict):
        return None
    return {
        "passed": value.get("passed"),
        "failed": value.get("failed"),
        "total": value.get("total"),
        "simulated": value.get("simulated"),
        "targetExecutions": value.get("targetExecutions"),
        "realContainers": value.get("realContainers"),
    }


def run_entry(name, directory, results_file, command, **extra):
    directory = Path(directory)
    results_path = directory / results_file
    return {
        "name": name,
        "command": read_text(directory / (name + ".command.txt")) or command,
        "returncode": int(read_text(directory / (name + ".exit.txt")).strip())
        if (directory / (name + ".exit.txt")).is_file() else None,
        "stdout": str((directory / (name + ".stdout")).relative_to(ROOT))
        if (directory / (name + ".stdout")).is_file() else None,
        "stderr": str((directory / (name + ".stderr")).relative_to(ROOT))
        if (directory / (name + ".stderr")).is_file() else None,
        "resultsFile": str(results_path.relative_to(ROOT)) if results_path.is_file() else None,
        "resultsSha256": sha(results_path) if results_path.is_file() else None,
        "summary": result_summary(read_json(results_path)),
        "sourceBefore": read_text(directory / (name + ".source-before.txt")),
        "sourceAfter": read_text(directory / (name + ".source-after.txt")),
        **extra,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "checks" / "evidence-index.json"))
    parser.add_argument("--manifest", default=str(ROOT / "protocol-manifest.json"))
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = (ROOT / manifest_path).resolve()
    manifest = read_json(manifest_path)
    final = RUNS / "final"
    before = ROOT / "checks" / "formal_admission" / "red-evidence" / "before"
    after = ROOT / "checks" / "formal_admission" / "red-evidence" / "after"
    initial_regression = RUNS / "regressions-initial"
    initial_formal = RUNS / "formal-admission-initial"

    payload = {
        "kind": "formal-admission-evidence-index",
        "version": 1,
        "protocolRevision": 3,
        "state": "pending-codex-review",
        "offlineOnly": True,
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "selfcheckExecutions": 0,
        "formalTargets": "0/16",
        "r3": "blocked",
        "admissionIssued": False,
        "preflightExecuted": False,
        "manifest": {
            "file": str(manifest_path.relative_to(ROOT)),
            "sha256": sha(manifest_path),
            "fileCount": manifest.get("fileCount"),
            "baselineFileCount": manifest.get("baselineFileCount"),
            "protocolRevision": manifest.get("protocolRevision"),
            "state": manifest.get("state"),
        },
        "sourceHashes": {
            "experiment_runner.py": manifest["files"]["tools/experiment_runner.py"],
            "judge.py": manifest["files"]["tools/judge.py"],
            "collect_observer.py": manifest["files"]["tools/collect_observer.py"],
            "buffer_protocol_v2.py": manifest["files"]["tools/buffer_protocol_v2.py"],
            "observer_template_buffer_v2.bt":
                manifest["files"]["tools/observer_template_buffer_v2.bt"],
            "observer_template.bt": manifest["files"]["tools/observer_template.bt"],
        },
        "redEvidence": {
            "before": run_entry(
                "before", before, "probe.json",
                'PATH="$PWD/checks/shims:$PATH" python3 '
                'checks/formal_admission/red_checks.py --tools baseline/tools '
                '--label baseline-before --out '
                'checks/formal_admission/red-evidence/before/probe.json',
                sourceHashesFile=str((before / "source-hashes.json").relative_to(ROOT)),
                expected="behavioural RED on sealed baseline"),
            "after": run_entry(
                "after", after, "probe.json",
                'PATH="$PWD/checks/shims:$PATH" python3 '
                'checks/formal_admission/red_checks.py --tools tools '
                '--label candidate-after --out '
                'checks/formal_admission/red-evidence/after/probe.json',
                sourceHashesFile=str((after / "source-hashes.txt").relative_to(ROOT)),
                expected="same probes PASS on frozen candidate"),
        },
        "initialFailures": [
            run_entry(
                "regression", initial_regression, "regression-results.json",
                'PATH="$PWD/checks/shims:$PATH" python3 checks/run_regressions.py '
                '--out checks/evidence-runs/regressions-initial/regression-results.json '
                '--evidence checks/evidence-runs/regressions-initial/evidence',
                note="kept honestly; one stage-retention assertion failed before the "
                     "final cleanup ordering fix"),
            run_entry(
                "formal", initial_formal, "formal-admission-results.json",
                'PATH="$PWD/checks/shims:$PATH" python3 '
                'checks/formal_admission/run_checks.py --out '
                'checks/evidence-runs/formal-admission-initial/formal-admission-results.json',
                note="kept honestly; six early scenario failures before test/support "
                     "migration"),
        ],
        "finalRuns": [
            run_entry("regression", final, "regression-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 checks/run_regressions.py '
                      '--out checks/evidence-runs/final/regression-results.json '
                      '--evidence checks/evidence-runs/final/regression-evidence'),
            run_entry("formal", final, "formal-admission-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 '
                      'checks/run_formal_admission_checks.py --out '
                      'checks/evidence-runs/final/formal-admission-results.json '
                      '--evidence checks/evidence-runs/final/formal-evidence'),
            run_entry("end-lf", final, "end-lf-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 '
                      'checks/run_end_lf_checks.py --out '
                      'checks/evidence-runs/final/end-lf-results.json'),
            run_entry("rev6", final, "rev6-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 checks/run_rev6_checks.py '
                      '--out checks/evidence-runs/final/rev6-results.json'),
            run_entry("rev7", final, "rev7-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 checks/run_rev7_checks.py '
                      '--out checks/evidence-runs/final/rev7-results.json'),
            run_entry("rev8", final, "rev8-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 checks/run_rev8_checks.py '
                      '--out checks/evidence-runs/final/rev8-results.json'),
            run_entry("diagnostics", final, "diagnostics-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 '
                      'checks/run_diagnostics_checks.py --out '
                      'checks/evidence-runs/final/diagnostics-results.json'),
            run_entry("repair", final, "repair-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 checks/run_repair_checks.py '
                      '--out checks/evidence-runs/final/repair-results.json'),
            run_entry("buffer", final, "buffer-preflight-results.json",
                      'PATH="$PWD/checks/shims:$PATH" python3 '
                      'checks/run_buffer_preflight_checks.py --out '
                      'checks/evidence-runs/final/buffer-preflight-results.json'),
            run_entry("compile", final, "compile-results.json",
                      'python3 checks/compile_check.py --out '
                      'checks/evidence-runs/final/compile-results.json'),
            run_entry("baseline", final, "baseline-verification.json",
                      'python3 checks/verify_baseline.py --out '
                      'checks/evidence-runs/final/baseline-verification.json'),
        ],
        "testsRun": [
            "recorded-shim regression suite (28 scenarios)",
            "SIMULATED formal admission suite (15 scenarios)",
            "END-LF focused suite",
            "rev6/rev7/rev8 focused suites",
            "diagnostics/repair/buffer-preflight suites",
            "pure compile check and baseline byte verification",
            "behavioural RED/PASS probes against baseline and candidate tools",
        ],
        "deferred": [
            "real Docker/bpftrace container and observer execution",
            "zero-target preflight execution against this manifest",
            "new-source selfcheck execution",
            "Codex independent check and external source review",
        ],
        "knownGaps": [
            {
                "gap": "No runtime or product approval in this phase",
                "detail": "All tests are SIMULATED/recorded-shim or in-process. "
                          "Formal targets remain 0/16 and R3 remains blocked.",
            },
            {
                "gap": "Source review and new-source selfcheck pending",
                "detail": "The historical preflight "
                          "0398591de290462b8a6e3f4ec4ff2cbc is not a receipt "
                          "for this 69-file manifest.",
            },
            {
                "gap": "Historical legacy formal fixtures migrated",
                "detail": "Old shim formal flows were moved to explicit buffer-v2; "
                          "their original result files are retained as history.",
            },
        ],
        "note": "Evidence index is separate from protocol-manifest.json. It binds "
                "the frozen manifest to raw RED/final outputs and source hashes. "
                "No real resource was created, queried or deleted.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "manifestSha256": payload["manifest"]["sha256"],
                      "finalRuns": len(payload["finalRuns"])}, sort_keys=True))


if __name__ == "__main__":
    main()
