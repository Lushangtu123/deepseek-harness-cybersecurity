"""Run the route acceptance driver in an owned VM scratch directory."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
os.umask(0o077)
status = {'state': 'running', 'startedAt': datetime.now(timezone.utc).isoformat()}


def save():
    path = root / 'status.tmp'
    path.write_text(json.dumps(status, indent=2) + '\n')
    path.replace(root / 'status.json')


save()
try:
    daily = Path('/home/purge/tools/dsh-purge-personal-1.1.77-personal.1')
    before = {str(p.relative_to(daily)): sha256(p.read_bytes()).hexdigest()
              for p in daily.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    runtime = Path('/home/purge/tools/security-workbench')
    protected = {name: sha256((runtime / name).read_bytes()).hexdigest() for name in ['images.json', 'rules.json']}
    node = '/home/purge/.local/node/bin/node'
    with (root / 'route.stdout').open('wb') as output, (root / 'route.stderr').open('wb') as error:
        run = subprocess.run([node, str(root / 'route.mjs')],
                             cwd=root, stdout=output, stderr=error, timeout=85)
    status['driverExitCode'] = run.returncode
    if run.returncode:
        raise RuntimeError('Route driver failed, original stderr retained')
    raw = (root / 'route.stdout').read_bytes()
    if len(raw) > 2097152:
        raise ValueError('Acceptance result too large')
    result = json.loads(raw)
    if result['state'] != 'passed' or result['programFilesRechecked'] != 173:
        raise ValueError('Route result incomplete')
    after = {str(p.relative_to(daily)): sha256(p.read_bytes()).hexdigest()
             for p in daily.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if before != after or len(after) != 169:
        raise ValueError('Daily program drift')
    if protected != {name: sha256((runtime / name).read_bytes()).hexdigest() for name in protected}:
        raise ValueError('Runtime rule or image manifest drift')
    status.update(state='completed', resultSha256=sha256(raw).hexdigest(),
                  dailyProgramFilesChecked=len(after), dailyProgramUnchanged=True,
                  runtimeConfigurationUnchanged=True,
                  finishedAt=datetime.now(timezone.utc).isoformat())
except BaseException as error:
    status.update(state='failed', problem=type(error).__name__, detail=str(error)[:200])
finally:
    save()
