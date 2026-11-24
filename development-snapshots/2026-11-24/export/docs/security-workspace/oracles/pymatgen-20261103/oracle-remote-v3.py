
from pathlib import Path,PurePosixPath
from tempfile import TemporaryDirectory
from hashlib import sha256
import base64,datetime,gzip,io,json,os,sqlite3,stat,subprocess,tarfile,time,zipfile
home=Path('/home/purge');docker=['sudo','-n','/usr/bin/docker']
manifest=home/'tools/security-workbench/images.json';rules=home/'tools/security-workbench/rules.json';program=home/'tools/dsh-purge-personal-1.1.77-personal.1'
program_before={str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
manifest_before=sha256(manifest.read_bytes()).hexdigest();rules_before=sha256(rules.read_bytes()).hexdigest()
def databases():
 result={}
 for path in sorted((home/'.dsh-improved/redteam/engagements').glob('*/assets.db')):
  digest=sha256()
  with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for row in db.iterdump():digest.update((row+'\n').encode())
  result[str(path)]=digest.hexdigest()
 return result
before=databases();container=None
volumes_before=subprocess.check_output([*docker,'volume','ls','-q'],text=True,timeout=8).splitlines()
with TemporaryDirectory(prefix='independent-lab-oracle-',dir=home/'.cache') as temporary:
 root=Path(temporary);root.chmod(0o755)
 for name,raw in json.loads(gzip.decompress(base64.b64decode(PAYLOAD))).items():
  rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts
  path=root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(base64.b64decode(raw));path.chmod(0o444)
 plan=json.loads((root/'protocol.json').read_text());assert program_before==plan['candidateProgram'];assert sha256((root/'probe.py').read_bytes()).hexdigest()==plan['probeSha256'];deps=root/'deps';deps.mkdir();total=0
 for row in json.loads((root/'wheels.json').read_text()):
  wheel=root/'wheels'/row['filename'];assert sha256(wheel.read_bytes()).hexdigest()==row['sha256']
  with zipfile.ZipFile(wheel) as archive:
   for entry in archive.infolist():
    rel=PurePosixPath(entry.filename);assert not rel.is_absolute() and '..' not in rel.parts and not stat.S_ISLNK(entry.external_attr>>16)
    if entry.is_dir():continue
    total+=entry.file_size;assert total<=140*1024*1024 and entry.file_size<=25*1024*1024
    path=deps/rel;assert not path.exists();path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(entry));path.chmod(0o444)
 image=next(r['imageId'] for r in json.loads(manifest.read_text())['tools'] if r['tool']=='semgrep');assert image==plan['runtimeImage']
 label='personal.harness.oracle='+root.name
 args=[*docker,'create','--rm','--pull','never','--name',root.name,'--label',label,'--network','none','--read-only','--user','65534:65534','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--memory-swap','256m','--cpus','1','--pids-limit','32','--log-driver','none','--env','HOME=/tmp','--env','OPENBLAS_NUM_THREADS=1','--env','OMP_NUM_THREADS=1','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777']
 for a,b in [('src','/src'),('deps','/deps'),('probe.py','/probe.py'),('protocol.json','/protocol.json'),('wheels.json','/wheels.json')]:args+=['--mount',f'type=bind,src={root/a},dst={b},readonly']
 args+=['--entrypoint','/bin/sh',image,'-c','exec timeout -s KILL 30s python3 -I -S -B /probe.py']
 try:
  container=subprocess.check_output(args,text=True,timeout=10).strip();assert len(container)==64
  info=json.loads(subprocess.check_output([*docker,'inspect',container],text=True,timeout=8))[0]
  assert info['Image']==image and info['HostConfig']['NetworkMode']=='none' and info['HostConfig']['ReadonlyRootfs']
  host=info['HostConfig'];assert not host['Privileged'] and info['Config']['User']=='65534:65534' and host['CapDrop']==['ALL'] and 'no-new-privileges' in host['SecurityOpt']
  assert host['Memory']==268435456 and host['MemorySwap']==268435456 and host['PidsLimit']==32 and host['NanoCpus']==1000000000
  assert {r['Destination'] for r in info['Mounts']}=={'/src','/deps','/probe.py','/protocol.json','/wheels.json'} and all(r['Type']=='bind' and not r['RW'] for r in info['Mounts'])
  started=datetime.datetime.now(datetime.timezone.utc).isoformat()
  p=subprocess.run([*docker,'start','--attach',container],capture_output=True,text=True,timeout=40)
  finished=datetime.datetime.now(datetime.timezone.utc).isoformat()
  if p.returncode:raise RuntimeError('Oracle process failed: '+p.stderr[-2000:])
  assert len(p.stdout.encode())<=128*1024
  result=json.loads(p.stdout);assert result['ok'] and result['protocolSha256']==sha256((root/'protocol.json').read_bytes()).hexdigest() and result['probeSha256']==sha256((root/'probe.py').read_bytes()).hexdigest()
 finally:
  if container:subprocess.run([*docker,'rm','-f','-v',container],capture_output=True,timeout=8)
 for attempt in range(20):
  remaining=subprocess.check_output([*docker,'ps','-aq','--filter','label='+label],text=True,timeout=8).strip()
  if not remaining:break
  time.sleep(0.1)
 assert not remaining
 assert sorted(volumes_before)==sorted(subprocess.check_output([*docker,'volume','ls','-q'],text=True,timeout=8).splitlines())
assert not root.exists() and before==databases()
assert program_before=={str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
assert manifest_before==sha256(manifest.read_bytes()).hexdigest() and rules_before==sha256(rules.read_bytes()).hexdigest()
print(json.dumps({'ok':True,'startedAt':started,'finishedAt':finished,'imageId':image,'containerRemoved':True,'temporaryRemoved':True,'programFilesMatched':len(program_before),'existingDatabaseLogicalDigestsMatched':len(before),'scannerManifestUnchanged':True,'runtimeRulesUnchanged':True,'probeSha256':result['probeSha256'],'volumeSetUnchanged':True,'containerControlsInspected':True,'result':result}))
