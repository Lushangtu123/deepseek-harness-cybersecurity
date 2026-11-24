#!/usr/bin/env python3
"""Pure compilation of current tools and checks; no import or execution."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "checks" / "compile-results.json"
ENTRIES = []


def check(path):
    try:
        compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
        passed = True
        error = None
    except (SyntaxError, ValueError, TypeError) as raised:
        passed = False
        error = type(raised).__name__ + ":" + str(raised)[:160]
    ENTRIES.append({"file": str(path.relative_to(ROOT)), "passed": passed,
                    "error": error, "simulated": True})
    return passed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    paths = sorted((ROOT / "tools").glob("*.py")) + sorted((ROOT / "checks").glob("*.py"))
    paths += sorted((ROOT / "checks" / "formal_admission").glob("*.py"))
    for path in paths:
        check(path)
    failed = [item["file"] for item in ENTRIES if not item["passed"]]
    payload = {
        "kind": "pure-compile-results",
        "simulated": True,
        "targetExecutions": 0,
        "realContainers": 0,
        "passed": len(ENTRIES) - len(failed),
        "total": len(ENTRIES),
        "failed": failed,
        "results": ENTRIES,
    }
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                           encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "total": payload["total"],
                      "failed": failed}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
