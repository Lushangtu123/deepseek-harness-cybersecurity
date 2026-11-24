
from pathlib import Path,PurePosixPath
from tempfile import TemporaryDirectory
from hashlib import sha256
import base64,datetime,gzip,json,sqlite3,subprocess
home=Path('/home/purge');program=home/'tools/dsh-purge-personal-1.1.77-personal.1';runtime=home/'tools/security-workbench';node=home/'.local/node/bin/node'
data=json.loads(gzip.decompress(base64.b64decode(PAYLOAD)))
def inventory():return {str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def databases():
 result={}
 for p in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
  digest=sha256()
  with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for row in db.iterdump():digest.update((row+'\n').encode())
  result[str(p)]=digest.hexdigest()
 return result
before=inventory();assert before==data['baseline'] and len(before)==165
db_before=databases();pins={n:sha256((runtime/n).read_bytes()).hexdigest() for n in ['rules.json','images.json']}
started=datetime.datetime.now(datetime.timezone.utc).isoformat()
with TemporaryDirectory(prefix='source-location-candidate-',dir=home/'.cache') as temporary:
 root=Path(temporary)
 for name,raw in data['files'].items():
  rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts
  p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);content=base64.b64decode(raw);assert sha256(content).hexdigest()==data['intent']['files'][name];p.write_bytes(content)
 tests=sorted(str(p) for p in (root/'work/harness-purge-improved/tests').glob('*.test.mjs'))
 check=subprocess.run([str(node),'--test',*tests],cwd=root,capture_output=True,text=True,timeout=90)
 (root/'test-result.txt').write_text(check.stdout+check.stderr)
 if check.returncode:raise RuntimeError('Candidate tests failed: '+(check.stdout+check.stderr)[-12000:])
 replay=subprocess.run([str(node),'replay.mjs'],cwd=root,capture_output=True,text=True,timeout=45)
 if replay.returncode:raise RuntimeError('Replay failed: '+replay.stderr[-12000:])
 result=json.loads(replay.stdout);assert result['ok'] and result['scannerInvocations']==0 and not result['r3Qualified']
 assert all(sha256((root/n).read_bytes()).hexdigest()==digest for n,digest in data['intent']['files'].items())
 assert inventory()==before and databases()==db_before and pins=={n:sha256((runtime/n).read_bytes()).hexdigest() for n in pins}
 output={'ok':True,'startedAt':started,'finishedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'programFilesMatched':len(before),'databaseLogicalDigestsMatched':len(db_before),'runtimePinsMatched':True,'candidateInputsUnchanged':True,'testExitCode':check.returncode,'testOutput':check.stdout+check.stderr,'replay':result,'replayStderr':replay.stderr[-2000:]}
assert not root.exists();output['candidateTemporaryRemoved']=True
print(json.dumps(output))
