"""Submit once and read the same route acceptance job."""
from hashlib import sha256
import base64
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import uuid

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('vm_bridge', root / 'vm-bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def read(name):
    return json.loads((root / name).read_bytes())


def save(name, value):
    with (root / name).open('x') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')


def launch():
    if (root / 'attempt.json').exists():
        raise ValueError('Existing attempt, inspect original instead of replaying')
    entries = {}
    for path in (root / 'kit').rglob('*'):
        if path.is_file():
            entries[str(path.relative_to(root / 'kit'))] = base64.b64encode(path.read_bytes()).decode()
    job = (root / 'job.py').read_text()
    remote = '/home/purge/.cache/harness-namespace-route-' + uuid.uuid4().hex[:12]
    encoded = base64.b64encode(gzip.compress(json.dumps(entries).encode())).decode()
    save('attempt.json', {'state': 'intent-before-submit', 'remoteRoot': remote,
                         'jobSha256': sha256(job.encode()).hexdigest(),
                         'archiveSha256': sha256(encoded.encode()).hexdigest(),
                         'driverSha256': sha256((root / 'kit/route.mjs').read_bytes()).hexdigest()})
    values = 'REMOTE=' + repr(remote) + '\nENCODED=' + repr(encoded) + '\nJOB=' + repr(job) + '\n'
    script = values + '''from pathlib import Path,PurePosixPath
from hashlib import sha256
import base64,gzip,json,os,subprocess
os.umask(0o077)
root=Path(REMOTE);root.mkdir(mode=0o700,exist_ok=False)
entries=json.loads(gzip.decompress(base64.b64decode(ENCODED)))
for name,data in entries.items():
 parts=PurePosixPath(name)
 if parts.is_absolute() or any(p in ['..','.'] for p in parts.parts):raise ValueError('Unsafe archive name')
 path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(base64.b64decode(data));path.chmod(0o644)
(root/'job.py').write_text(JOB)
daily=Path('/home/purge/tools/dsh-purge-personal-1.1.77-personal.1/lib/redteam/personal-joint-review.mjs')
source=daily.read_text()
dailyRoute={'sha256':sha256(daily.read_bytes()).hexdigest(),'callsNamespaceCollector':"this.bench.namespaceEvidence(data.snapshot,findings" in source,'workspaceGuardPresent':"step.tool==='semgrep'&&data.workspace" in source}
with (root/'job.stdout').open('wb') as out,(root/'job.stderr').open('wb') as err:
 p=subprocess.Popen(['/usr/bin/timeout','--signal=TERM','--kill-after=10','100','/usr/bin/python3','-I','-B',str(root/'job.py')],stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True,close_fds=True)
print(json.dumps({'state':'submitted','pid':p.pid,'dailyJointRoute':dailyRoute}))
'''
    compile(script, '<route-submission>', 'exec')
    with (root / 'submission-script.txt').open('x') as output:
        output.write(script)
    result = bridge.call(script, 15)
    save('submitted.json', result)
    return result


def poll():
    script = '''from pathlib import Path
from hashlib import sha256
import json
root=Path(REMOTE)
state=json.loads((root/'status.json').read_bytes())
result={'status':state}
if state['state'] in ['completed','failed']:
 for name in ['route.stdout','route.stderr','job.stderr']:
  path=root/name
  if path.exists():
   if path.is_symlink() or path.stat().st_size>2097152:raise ValueError('Result limit')
   result[name]=path.read_text()
print(json.dumps(result))
'''.replace('REMOTE', repr(read('attempt.json')['remoteRoot']))
    result = bridge.call(script, 10)
    (root / 'poll.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if result['status']['state'] == 'completed':
        raw = result['route.stdout'].encode()
        if sha256(raw).hexdigest() != result['status']['resultSha256']:
            raise ValueError('Received result digest mismatch')
        (root / 'route.json').write_bytes(raw)
    return {'status': result['status'], 'stderr': result.get('route.stderr', '')[:1800]}


def cleanup():
    meta, result = read('attempt.json'), read('poll.json')
    if result['status']['state'] not in {'completed', 'failed'}:
        raise ValueError('Original job still running')
    outputs = {name: sha256(result[name].encode()).hexdigest()
               for name in ['route.stdout', 'route.stderr', 'job.stderr'] if name in result}
    script = '''from pathlib import Path
from hashlib import sha256
import json,re,shutil
root=Path(REMOTE)
if not re.fullmatch('/home/purge/[.]cache/harness-namespace-route-[0-9a-f]{12}',str(root)):raise ValueError('Wrong owned root')
if root.resolve()!=root or root.stat().st_uid!=1000 or root.stat().st_mode&0o077:raise ValueError('Wrong root metadata')
if json.loads((root/'status.json').read_bytes())['state'] not in ['completed','failed']:raise ValueError('Original worker not ended')
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  raw=p.read_bytes()
  if str(root/'job.py').encode() in raw or str(root/'route.mjs').encode() in raw:raise ValueError('Owned process still running')
 except (PermissionError,FileNotFoundError,ProcessLookupError):pass
if sha256((root/'job.py').read_bytes()).hexdigest()!=JOB_SHA or sha256((root/'route.mjs').read_bytes()).hexdigest()!=DRIVER_SHA:raise ValueError('Owned source changed')
for name,expected in OUTPUTS.items():
 if sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('Original output not preserved')
shutil.rmtree(root)
print(json.dumps({'state':'cleaned','workerStopped':True,'scratchRemoved':not root.exists()}))
'''
    script = ('REMOTE=' + repr(meta['remoteRoot']) + '\nJOB_SHA=' + repr(meta['jobSha256'])
              + '\nDRIVER_SHA=' + repr(meta['driverSha256']) + '\nOUTPUTS=' + repr(outputs) + '\n' + script)
    value = bridge.call(script, 15)
    save('vm-cleanup.json', value)
    return value


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'launch', 'poll', 'cleanup'}:
        raise ValueError('Choose launch, poll or cleanup')
    print(json.dumps(globals()[sys.argv[1]]()))
