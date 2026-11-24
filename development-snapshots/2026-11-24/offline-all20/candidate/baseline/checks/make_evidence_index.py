#!/usr/bin/env python3
"""Bind the frozen buffer-v2 source manifest to raw RED/history and final logs.

This evidence index is deliberately *not* in the protocol manifest and is
written only after every listed source byte is frozen.  It never rewrites the
manifest, a RED run or a final run.  RED history is bound as raw files; it is
not replayed or relabelled.
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
    return json.loads(Path(path).read_text())


def bound_files(run_dir):
    run_dir = Path(run_dir)
    rows = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            rows.append({
                "file": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            })
    return rows


def suite_summary(run_dir):
    run_dir = Path(run_dir)
    top = read_json(run_dir / "run.json")
    suites = {}
    for record in top.get("suites") or []:
        suite = record.get("suite")
        item = {
            "runJson": str((run_dir / ("suite-" + suite) / "run.json")
                           .relative_to(ROOT)),
            "runJsonSha256": sha(run_dir / ("suite-" + suite) / "run.json"),
            "command": record.get("command"),
            "returncode": record.get("returncode"),
            "resultFile": record.get("resultFile"),
            "resultSha256": record.get("resultSha256"),
            "resultPassed": record.get("resultPassed"),
            "resultTotal": record.get("resultTotal"),
            "resultFailed": record.get("resultFailed"),
            "intervalSeconds": record.get("intervalSeconds"),
        }
        suites[suite] = item
    return {
        "runJson": str((run_dir / "run.json").relative_to(ROOT)),
        "runJsonSha256": sha(run_dir / "run.json"),
        "runId": top.get("runId"),
        "phase": top.get("phase"),
        "startedUtc": top.get("startedUtc"),
        "finishedUtc": top.get("finishedUtc"),
        "intervalSeconds": top.get("intervalSeconds"),
        "sourceUnchanged": top.get("sourceUnchanged"),
        "failedSuites": top.get("failedSuites"),
        "suites": suites,
    }


def red_summary(run_dir, note):
    run_dir = Path(run_dir)
    record = read_json(run_dir / "run.json") if (run_dir / "run.json").is_file() else {}
    return {
        "path": str(run_dir.relative_to(ROOT)),
        "runJson": str((run_dir / "run.json").relative_to(ROOT))
        if (run_dir / "run.json").is_file() else None,
        "runJsonSha256": sha(run_dir / "run.json")
        if (run_dir / "run.json").is_file() else None,
        "command": record.get("command"),
        "commandLine": record.get("commandLine"),
        "returncode": record.get("returncode"),
        "resultPassed": record.get("resultPassed"),
        "resultTotal": record.get("resultTotal"),
        "resultFailed": record.get("resultFailed"),
        "sourceBeforeFile": record.get("sourceBeforeFile"),
        "sourceBeforeSha256": record.get("sourceBeforeSha256"),
        "sourceBeforeFileCount": record.get("sourceBeforeFileCount"),
        "note": note,
        "raw": bound_files(run_dir),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--after-run", required=True,
                        help="final post-freeze run produced by checks/run_evidence.py")
    parser.add_argument("--before-run", default=None,
                        help="optional historical pre-implementation run; omitted in "
                             "this root because baseline testing did not occur before "
                             "the old v1 development")
    parser.add_argument("--red-run", action="append", default=[],
                        help="raw RED or retained history run; never rewritten")
    parser.add_argument("--closure-run", action="append", default=[],
                        help="post-freeze closure run; bound raw and not rewritten")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    after = Path(args.after_run).resolve()
    manifest_path = ROOT / "protocol-manifest.json"
    manifest = read_json(manifest_path)
    after_summary = suite_summary(after)
    before_summary = suite_summary(Path(args.before_run).resolve()) if args.before_run else None
    compiled = read_json(after / "compile-results.json")
    static = read_json(after / "static-checks.json")
    diagnostics = read_json(after / "diagnostics-results.json")
    repair = read_json(after / "repair-results.json")
    buffer_results = read_json(after / "buffer-preflight-results.json")
    baseline = read_json(after / "baseline-verification.json")
    red_runs = []
    for item in args.red_run:
        path = Path(item).resolve()
        name = path.name
        if "diagnostics-parallel-initial-failure" in name:
            note = ("Initial post-implementation diagnostics run, parallel with four "
                    "other suites; one fixed 3-second SIGINT wait expired under load. "
                    "Raw failure retained; a sequential rerun passed 20/20. Not a "
                    "product-state claim.")
        elif name.endswith("buffer-v2-red"):
            note = ("First focused RED run on the unmodified old interfaces. Retained "
                    "as-is. It also contains two test-harness mistakes (the %r "
                    "nonprintable expectation and a stream builder that spaced every "
                    "v1 payload); the corrected RED run is retained separately.")
        else:
            note = ("Corrected focused RED run, executed on the unmodified old "
                    "interfaces before implementation. v1 rejected spaced QUALB, the "
                    "old collector rejected buffer-v2 and the old verifier selected "
                    "buffer-v1. Preserved as-is.")
        red_runs.append(red_summary(path, note))
    closure_runs = []
    for item in args.closure_run:
        path = Path(item).resolve()
        closure_runs.append(red_summary(
            path,
            "Post-freeze buffer-v2 focused closure run against the final manifest. "
            "The earlier RED directories remain unchanged.",
        ))
    payload = {
        "kind": "buffer-v2-strict-preflight-evidence-index",
        "version": 1,
        "protocolRevision": 3,
        "state": "pending-codex-review",
        "manifest": {
            "file": "protocol-manifest.json",
            "sha256": sha(manifest_path),
            "fileCount": manifest.get("fileCount"),
            "totalBytes": manifest.get("totalBytes"),
            "sourceOnly": manifest.get("sourceOnly") is True,
            "selfExcluded": "protocol-manifest.json" not in (manifest.get("files") or {}),
            "observationProtocol": manifest.get("observationProtocol"),
            "baselineManifestSha256": manifest.get("baselineManifestSha256"),
            "baselineFileCount": manifest.get("baselineFileCount"),
        },
        "baselineReference": {
            "manifestSha256": baseline.get("manifestSha256"),
            "fileCount": baseline.get("fileCount"),
            "recomputed": baseline.get("recomputed"),
            "mismatched": baseline.get("mismatched"),
            "note": "The frozen 54-file baseline was recomputed during the final run. "
                    "No claim is made that a baseline test run preceded the old v1 "
                    "development.",
        },
        "initialBufferRedRuns": red_runs,
        "postFreezeClosureRuns": closure_runs,
        "beforeImplementationRun": before_summary,
        "afterImplementation": after_summary,
        "raw": {
            "after": bound_files(after),
            "red": [{"path": row["path"], "raw": row["raw"]} for row in red_runs],
            "closure": [{"path": row["path"], "raw": row["raw"]}
                        for row in closure_runs],
        },
        "sourceSnapshots": {
            "redSourceBefore": [
                {"file": row.get("sourceBeforeFile"),
                 "sha256": row.get("sourceBeforeSha256"),
                 "fileCount": row.get("sourceBeforeFileCount")}
                for row in red_runs if row.get("sourceBeforeFile")
            ],
            "finalManifestSha256": sha(manifest_path),
            "finalManifestFileCount": manifest.get("fileCount"),
        },
        "counts": {
            "original28": {
                "passed": read_json(after / "regression-results.json").get("passed"),
                "total": read_json(after / "regression-results.json").get("total"),
            },
            "rev6": {
                "passed": read_json(after / "rev6-results.json").get("passed"),
                "total": read_json(after / "rev6-results.json").get("total"),
            },
            "rev7": {
                "passed": read_json(after / "rev7-results.json").get("passed"),
                "total": read_json(after / "rev7-results.json").get("total"),
            },
            "rev8": {
                "passed": read_json(after / "rev8-results.json").get("passed"),
                "total": read_json(after / "rev8-results.json").get("total"),
            },
            "diagnostics": {
                "passed": diagnostics.get("passed"),
                "total": diagnostics.get("total"),
            },
            "repair": {
                "passed": repair.get("passed"),
                "total": repair.get("total"),
                "failed": repair.get("failed"),
            },
            "compile": {
                "passed": compiled.get("passed"),
                "total": compiled.get("total"),
            },
            "bufferV2Focused": {
                "passed": buffer_results.get("passed"),
                "total": buffer_results.get("total"),
                "failed": buffer_results.get("failed"),
                "observationProtocol": buffer_results.get("observationProtocol"),
            },
            "static": {
                "passed": static.get("passed"),
                "total": static.get("total"),
                "failed": static.get("failed"),
            },
        },
        "limitations": [
            "No real Docker, bpftrace, compiler, sudo, fixture, target, formal "
            "attempt, tqdm or NLTK execution is recorded by this index.",
            "The implementer did not execute the preflight or the fixed eval('0') "
            "selfcheck and issued no admission, license or completed claim.",
            "A controller hard crash before finalization, evidence-filesystem loss "
            "and a double-forked process remain unsupported loss windows.",
            "Status/recover historical records without new diagnostic fields remain "
            "readable and are not backfilled or relabelled.",
            "The scalar @events counter is a single-thread fixed-selfcheck counter, "
            "not a multi-thread atomic resource-budget claim.",
            "Real bpftrace compilation and attachment remain Codex-only; no "
            "simulated parser/shim result is compiler evidence.",
            "buffer-v2 runtime support remains unverified. Source-derived formatter "
            "goldens and pure parser results are not observed bpftrace output.",
            "Exactly one fixed selfcheck and zero formal fixtures may be admitted "
            "only later by Codex; this implementer ran neither (selfcheck 0/1, "
            "formal 0/16).",
            "R3 remains blocked.",
        ],
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "selfcheckExecutions": 0,
        "admissionIssued": False,
        "formalTargets": "0/16",
        "r3": "blocked",
        "note": "Binds protocol-manifest.json, every raw RED/history file and every "
                "raw final-run file; it rewrites neither source nor either run.",
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                      encoding="utf-8")
    print(json.dumps({"manifestSha256": payload["manifest"]["sha256"],
                      "after": after_summary["runId"],
                      "redRuns": len(red_runs),
                      "closureRuns": len(closure_runs),
                      "outputSha256": sha(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
