from pathlib import Path
from hashlib import sha256
import importlib.util,json
root=Path(__file__).resolve().parent
meta=json.loads((root/'vm-intent-final.json').read_bytes());poll=json.loads((root/'vm-poll-final.json').read_bytes())
assert poll['state']=='completed' and sha256((root/'vm-result-final.json').read_bytes()).hexdigest()==poll['resultSha256']
script='''from pathlib import Path
from hashlib import sha256
import importlib.util,json,os,re,shutil,subprocess
root=Path(REMOTE)
if not re.fullmatch('/home/purge/[.]cache/r3-controlled-storage-[0-9a-f]{12}',str(root)) or root.resolve()!=root or root.stat().st_uid!=1000 or root.stat().st_mode&0o077:raise ValueError('Wrong owned scratch')
if sha256((root/'worker.py').read_bytes()).hexdigest()!=WORKER or sha256((root/'input.json').read_bytes()).hexdigest()!=INPUT:raise ValueError('Control drift')
status=json.loads((root/'status.json').read_bytes())
if status['state']!='completed' or status['resultSha256']!=RESULT:raise ValueError('Original task not completed')
result=json.loads((root/'result.json').read_bytes())
for name,want in result['sourceSha256'].items():
 if sha256((root/name).read_bytes()).hexdigest()!=want:raise ValueError('Source drift')
for path in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  if str(root/'worker.py').encode() in path.read_bytes():raise ValueError('Worker still active')
 except (FileNotFoundError,ProcessLookupError,PermissionError):pass
spec=importlib.util.spec_from_file_location('snapshot',root/'scripts/reviewer_snapshot.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
records=[]
prefix=['/usr/bin/sudo','-n','/usr/bin/timeout','--signal=TERM','--kill-after=2','6']
docker=[*prefix,'/usr/bin/docker','--host','unix:///var/run/docker.sock','--config',str(root/'driver-config')]
for record in root.rglob('attempt.json'):
 if not re.fullmatch(r'review-[0-9a-f]{32}',record.parent.name):continue
 state=api.status(record.parent)
 if state['state'] not in ['completed','recovered'] or not state.get('cleanup',{}).get('confirmed') or (record.parent/'stage').exists():raise ValueError('Attempt not settled')
 for token in ['name=^/'+state['name']+'$',*(['id='+state['containerId']] if state['containerId'] else []),'label=io.deepseek.harness.review.attempt='+state['id']]:
  check=subprocess.run([*docker,'container','ls','--all','--quiet','--no-trunc','--filter',token],capture_output=True,timeout=10)
  if check.returncode or check.stdout.strip():raise ValueError('Owned container remains')
 probe=subprocess.run([*prefix,'/usr/bin/python3','-I','-B','-S','-c',api._CLIENT_PROBE,str(record.parent/'docker-config')],capture_output=True,timeout=10)
 value=json.loads(probe.stdout)
 if probe.returncode or value['active'] or value['readErrors']:raise ValueError('Owned client remains')
 if state['state']=='completed' and api.digest(state['result'])!=state['resultSha256']:raise ValueError('Result drift')
 records.append({'record':state,'recordSha256':sha256(record.read_bytes()).hexdigest(),'laterContainerQueriesAbsent':True,'sameSourceClientProbeEmpty':True})
if len(records)!=1:raise ValueError('Unexpected acceptance attempt count')
pass # Retain synthetic acceptance evidence; no automatic deletion in this stage.
print(json.dumps({'state':'verified-retained','attemptRecords':records,'scratchRemoved':False,'retention':'manual cleanup only; task evidence preserved','noOwnedContainersOrClients':True}))
'''.replace('REMOTE',repr(meta['remoteRoot'])).replace('WORKER',repr(meta['workerSha256'])).replace('INPUT',repr(meta['inputSha256'])).replace('RESULT',repr(poll['resultSha256']))
(root/'vm-finish-script-final.txt').write_text(script)
spec=importlib.util.spec_from_file_location('bridge',root/'vm-bridge.py');bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
if (root/'vm-retained-final.json').exists():raise ValueError('Already reconciled; read record')
value=bridge.call(script,55);(root/'vm-retained-final.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k!='attemptRecords'}))
