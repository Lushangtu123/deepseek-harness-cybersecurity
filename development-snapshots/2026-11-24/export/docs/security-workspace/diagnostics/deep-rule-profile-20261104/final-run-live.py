from pathlib import Path,PurePosixPath
from hashlib import sha256
import base64,gzip,importlib.util,json
w=Path(__file__).resolve().parent;intent=json.loads((w/'native-intent.json').read_text());kit=w/'kit';names=[n for n in intent['files'] if n.startswith('work/harness-purge-improved/package/') or n=='replay-input.json'];files={n:base64.b64encode((kit/n).read_bytes()).decode() for n in names};files['live-scan.mjs']=base64.b64encode((w/'live-scan.mjs').read_bytes()).decode();hashes={n:sha256(base64.b64decode(raw)).hexdigest() for n,raw in files.items()};payload={'files':files,'hashes':hashes,'baseline':json.loads((w/'daily-baseline-program.json').read_text())};(w/'live-intent.json').write_text(json.dumps({'version':1,'files':hashes,'candidateDeployed':False,'source':'frozen172 candidate plus live harness'},indent=2)+'\n')
source='PAYLOAD='+repr(base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode())+'\n'+r'''
from pathlib import Path,PurePosixPath
from tempfile import TemporaryDirectory
from hashlib import sha256
import base64,gzip,json,sqlite3,subprocess,time
home=Path('/home/purge');program=home/'tools/dsh-purge-personal-1.1.77-personal.1';runtime=home/'tools/security-workbench';node=home/'.local/node/bin/node';data=json.loads(gzip.decompress(base64.b64decode(PAYLOAD)))
def inventory():return {str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def databases():
 result={}
 for p in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
  digest=sha256()
  with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for row in db.iterdump():digest.update((row+'\n').encode())
  result[str(p)]=digest.hexdigest()
 return result
before=inventory();assert before==data['baseline'] and len(before)==169;db=databases();pins={n:sha256((runtime/n).read_bytes()).hexdigest() for n in ['rules.json','images.json']};started=time.time()
with TemporaryDirectory(prefix='deep-rule-profile-live-',dir=home/'.cache') as temporary:
 root=Path(temporary)
 for name,raw in data['files'].items():
  rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts;content=base64.b64decode(raw);assert sha256(content).hexdigest()==data['hashes'][name];p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
 run=subprocess.run([str(node),'live-scan.mjs'],cwd=root,capture_output=True,text=True,timeout=190)
 if run.returncode:
  print(json.dumps({'ok':False,'stdout':run.stdout,'stderr':run.stderr,'debug':(root/'live-debug.json').read_text() if (root/'live-debug.json').exists() else None}));raise SystemExit(1)
 output=json.loads(run.stdout);assert output['ok'];events=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/docker','events','--since',str(started),'--until',str(time.time()),'--filter','type=container','--filter','event=create','--filter','label=personal.harness.namespace-review=1','--format','{{json .}}'],capture_output=True,text=True,timeout=10);assert events.returncode==0;creates=[json.loads(s) for s in events.stdout.splitlines() if s.strip()];assert len(creates)==1,len(creates);output['observedNamespaceCreates']=len(creates)
 assert inventory()==before and databases()==db and pins=={n:sha256((runtime/n).read_bytes()).hexdigest() for n in pins}
 assert all(sha256((root/n).read_bytes()).hexdigest()==digest for n,digest in data['hashes'].items());output.update(dailyProgramHashesMatched=len(before),dailyDatabaseLogicalHashesMatched=len(db),runtimePinsMatched=True,stderr=run.stderr)
assert not root.exists();output['candidateTemporaryRemoved']=True;print(json.dumps(output))
'''
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
try:response=m.ssh('python3 -B -',input=source,timeout=220,phase='native-check')
except m.SSHFailure as e:
 (w/'live-failure.json').write_text(json.dumps({'stdout':e.stdout,'stderr':e.stderr,'error':str(e)},indent=2)+'\n');raise
value=json.loads(response.stdout);(w/'live.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k not in ['joint','legacy','stderr','launches']}));print(json.dumps(value['launches']))
