#!/usr/bin/env python3
"""Recompute the frozen baseline manifest and fixed inputs without writing them."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "baseline"
OUT = ROOT / "checks" / "baseline-verification.json"
FIXTURES = (
    "fixtures/echo/sce_echo_sink.py",
    "fixtures/safe-quoting/sce_quoted_sink.py",
    "fixtures/structure-controlled/sce_raw_sink.py",
    "fixtures/wrong-function/sce_two_sites.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((BASE / "protocol-manifest.json").read_text(encoding="utf-8"))
    mismatched = []
    total = 0
    for relative, expected in manifest["files"].items():
        path = BASE / relative
        if not path.is_file() or sha(path) != expected:
            mismatched.append(relative)
        else:
            total += path.stat().st_size
    fixtures = {relative: sha(BASE / relative) for relative in FIXTURES}
    payload = {
        "kind": "baseline-verification",
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "manifestFile": "baseline/protocol-manifest.json",
        "manifestSha256": sha(BASE / "protocol-manifest.json"),
        "fileCount": manifest.get("fileCount"),
        "recomputed": len(manifest["files"]),
        "mismatched": mismatched,
        "totalBytes": total,
        "fixtures": fixtures,
        "experimentPlanSha256": sha(BASE / "experiment-plan.json"),
        "directoryFileCount": len([path for path in BASE.rglob("*") if path.is_file()]),
        "note": "All manifest entries recomputed from baseline bytes; baseline/ untouched.",
    }
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                           encoding="utf-8")
    print(json.dumps({"fileCount": payload["fileCount"],
                      "mismatched": mismatched,
                      "manifestSha256": payload["manifestSha256"]}, sort_keys=True))
    return 0 if not mismatched and payload["fileCount"] == payload["recomputed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
