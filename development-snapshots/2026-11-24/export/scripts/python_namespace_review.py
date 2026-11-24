"""Repository CLI for the single packaged, trusted structural-review implementation."""
from pathlib import Path
import runpy

globals().update(runpy.run_path(str(Path(__file__).resolve().parents[1]/'work/harness-purge-improved/package/scripts/python_namespace_review.py'),run_name=__name__))
