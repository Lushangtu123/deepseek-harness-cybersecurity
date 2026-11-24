"""Preserve the original diagnostic producer stdout as result bytes, without edits."""
import subprocess,sys
from pathlib import Path
out,script,candidate,references=map(Path,sys.argv[1:5])
if out.exists():raise SystemExit('result-exists')
p=subprocess.run([sys.executable,'-I','-B',str(script),str(candidate),str(references)],capture_output=True,timeout=120)
out.parent.mkdir(parents=True,exist_ok=True)
with out.open('xb') as f:f.write(p.stdout)
sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr)
raise SystemExit(p.returncode)
