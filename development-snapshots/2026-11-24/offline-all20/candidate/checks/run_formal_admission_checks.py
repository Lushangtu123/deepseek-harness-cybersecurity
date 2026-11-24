#!/usr/bin/env python3
"""Top-level entry for the SIMULATED formal admission checks."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "formal_admission"))

import run_checks  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run_checks.main())
