from pathlib import Path
import base64,gzip,hashlib,importlib.util,json
w=Path(__file__).resolve().parent
files={'probe.py':(w/'probe.py').read_bytes(),'protocol.json':(w/'protocol.json').read_bytes()}
for directory in ['src','review']:
 for p in (w/directory).rglob('*'):
  if p.is_file():files[directory+'/'+str(p.relative_to(w/directory))]=p.read_bytes()
payload=base64.b64encode(gzip.compress(json.dumps({n:base64.b64encode(v).decode() for n,v in files.items()}).encode())).decode()
source='PAYLOAD='+repr(payload)+'\n'+r'''
from pathlib import Path,PurePosixPath
from tempfile import TemporaryDirectory
from hashlib import sha256
import base64,datetime,gzip,json,os,sqlite3,subprocess,time
home=Path('/home/purge');docker=['sudo','-n','/usr/bin/docker'];program=home/'tools/dsh-purge-personal-1.1.77-personal.1'
manifest=home/'tools/security-workbench/images.json';rules=home/'tools/security-workbench/rules.json'
def inventory():return {str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def databases():
 result={}
 for path in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
  digest=sha256()
  with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for row in db.iterdump():digest.update((row+'\n').encode())
  result[str(path)]=digest.hexdigest()
 return result
before=inventory();db_before=databases();manifest_before=sha256(manifest.read_bytes()).hexdigest();rules_before=sha256(rules.read_bytes()).hexdigest()
volumes_before=subprocess.check_output([*docker,'volume','ls','-q'],text=True,timeout=8).splitlines()
with TemporaryDirectory(prefix='namespace-review-',dir=home/'.cache') as temporary:
 root=Path(temporary);root.chmod(0o755)
 for name,raw in json.loads(gzip.decompress(base64.b64decode(PAYLOAD))).items():
  rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts
  p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(raw));p.chmod(0o444)
 plan=json.loads((root/'protocol.json').read_text());assert sha256((root/'probe.py').read_bytes()).hexdigest()==plan['probeSha256']
 image=next(r['imageId'] for r in json.loads(manifest.read_text())['tools'] if r['tool']=='semgrep');assert image==plan['imageId']
 label='personal.harness.namespace-review='+root.name;container=None
 args=[*docker,'create','--rm','--pull','never','--name',root.name,'--label',label,'--network','none','--read-only','--user','65534:65534','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--memory-swap','256m','--cpus','1','--pids-limit','32','--log-driver','none','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777','--env','HOME=/tmp']
 for a,b in [('src','/src'),('probe.py','/probe.py'),('protocol.json','/protocol.json'),('review','/review')]:args+=['--mount',f'type=bind,src={root/a},dst={b},readonly']
 args+=['--entrypoint','/bin/sh',image,'-c','exec timeout -s KILL 15s python3 -I -S /probe.py']
 try:
  container=subprocess.check_output(args,text=True,timeout=10).strip();assert len(container)==64
  info=json.loads(subprocess.check_output([*docker,'inspect',container],text=True,timeout=8))[0];host=info['HostConfig']
  assert info['Image']==image and host['NetworkMode']=='none' and host['ReadonlyRootfs'] and not host['Privileged'] and info['Config']['User']=='65534:65534'
  assert host['CapDrop']==['ALL'] and 'no-new-privileges' in host['SecurityOpt'] and host['Memory']==268435456 and host['MemorySwap']==268435456 and host['PidsLimit']==32 and host['NanoCpus']==1000000000
  assert {m['Destination'] for m in info['Mounts']}=={'/src','/probe.py','/protocol.json','/review'} and all(m['Type']=='bind' and not m['RW'] for m in info['Mounts'])
  started=datetime.datetime.now(datetime.timezone.utc).isoformat();p=subprocess.run([*docker,'start','--attach',container],capture_output=True,text=True,timeout=22);finished=datetime.datetime.now(datetime.timezone.utc).isoformat()
  if p.returncode:raise RuntimeError('Oracle failed: '+p.stderr[-5000:])
  assert len(p.stdout.encode())<=128*1024;result=json.loads(p.stdout)
  assert result['ok'] and result['probeSha256']==sha256((root/'probe.py').read_bytes()).hexdigest() and result['protocolSha256']==sha256((root/'protocol.json').read_bytes()).hexdigest()
 finally:
  if container:subprocess.run([*docker,'rm','-f','-v',container],capture_output=True,timeout=8)
 for attempt in range(20):
  remaining=subprocess.check_output([*docker,'ps','-aq','--filter','label='+label],text=True,timeout=8).strip()
  if not remaining:break
  time.sleep(0.1)
 assert not remaining
assert not root.exists() and inventory()==before and databases()==db_before
assert manifest_before==sha256(manifest.read_bytes()).hexdigest() and rules_before==sha256(rules.read_bytes()).hexdigest()
assert sorted(volumes_before)==sorted(subprocess.check_output([*docker,'volume','ls','-q'],text=True,timeout=8).splitlines())
print(json.dumps({'ok':True,'startedAt':started,'finishedAt':finished,'imageId':image,'programFilesMatched':len(before),'databaseLogicalDigestsMatched':len(db_before),'manifestAndRulesMatched':True,'containerRemoved':True,'temporaryRemoved':True,'volumeSetUnchanged':True,'result':result}))
'''
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
try:r=m.ssh('python3 -B -',input=source,timeout=60,phase='native-check')
except m.SSHFailure as e:
 (w/'oracle-failure.json').write_text(json.dumps({'stdout':e.stdout,'stderr':e.stderr,'summary':str(e)},indent=2)+'\n');raise
value=json.loads(r.stdout);(w/'native-oracle.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k!='result'}))
