from pathlib import Path
from hashlib import sha256
import base64,gzip,importlib.util,json
w=Path(__file__).resolve().parent;intent=json.loads((w/'native-intent.json').read_text());kit=w/'kit'
assert all(sha256((kit/n).read_bytes()).hexdigest()==digest for n,digest in intent['files'].items())
assert sha256((w/'daily-baseline-program.json').read_bytes()).hexdigest()==intent['dailyBaselineSha256']
data={'files':{n:base64.b64encode((kit/n).read_bytes()).decode() for n in intent['files']},'intent':intent,'baseline':json.loads((w/'daily-baseline-program.json').read_text())}
source='PAYLOAD='+repr(base64.b64encode(gzip.compress(json.dumps(data).encode())).decode())+'\n'+r'''
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
'''
(w/'native-source.py').write_text(source.split('\n',1)[1])
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
try:response=m.ssh('python3 -B -',input=source,timeout=165,phase='native-check')
except m.SSHFailure as e:
 (w/'native-failure.json').write_text(json.dumps({'stdout':e.stdout,'stderr':e.stderr,'error':str(e)},indent=2)+'\n');raise
value=json.loads(response.stdout);(w/'native.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps({k:v for k,v in value.items() if k not in ['testOutput','replay','replayStderr']}));print(json.dumps({'phases':{k:{n:v for n,v in r.items() if n not in ['findings','offlineReport']} for k,r in value['replay']['phases'].items()}}))
