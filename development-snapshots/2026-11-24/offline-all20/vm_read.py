"""Pinned existing VM transport; guest script arrives on stdin, never a file."""
from pathlib import Path
from hashlib import sha256
import json, types, sys, subprocess, time

ROOT = Path(__file__).resolve().parent
MANAGER = Path.home() / 'Library/Application Support/Harness Purge Original/host-tools/manage.py'
PIN = '19bd85c390e6d7482f78e77f6fe9de733258df0454d9a7921125be82b4a48bbf'

def manager():
    raw = MANAGER.read_bytes()
    if sha256(raw).hexdigest() != PIN:
        raise ValueError('manager-digest-changed')
    mod = types.ModuleType('capacity_read_manager')
    mod.__file__ = str(MANAGER)
    exec(compile(raw, str(MANAGER), 'exec'), mod.__dict__)
    mod.validate()
    return mod

if __name__ == '__main__':
    script_path, output = map(Path, sys.argv[1:3])
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 240
    script = script_path.read_bytes()
    if output.exists():
        raise SystemExit('existing-result-not-overwritten')
    start = time.monotonic()
    result = manager().ssh('/usr/bin/python3 -I -B -', input=script.decode(), timeout=timeout, phase='native-check')
    data = json.loads(result.stdout)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    event = {'scriptSha256': sha256(script).hexdigest(), 'output': str(output),
             'outputSha256': sha256(output.read_bytes()).hexdigest(), 'exitCode': result.returncode,
             'elapsedSeconds': round(time.monotonic()-start, 3), 'guestScriptStored': False}
    with (ROOT / 'transport.jsonl').open('a') as stream:
        stream.write(json.dumps(event) + '\n')
    summary={k:data[k] for k in ('kind','uid','complete','idleConfirmed','scope') if k in data}
    summary['errorCount']=len(data.get('errors',[]))
    print(json.dumps({**event,'summary':summary}))
