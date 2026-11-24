from pathlib import Path
from hashlib import sha256
import base64,gzip,importlib.util,json
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm';package=repo/'work/harness-purge-improved/package'
if (w/'session.json').exists():raise SystemExit('This session is already staged; use a new run directory')
files={'package/'+str(p.relative_to(package)):base64.b64encode(p.read_bytes()).decode() for p in package.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
for name in ['index.html','browser-service.mjs','proof-contract.mjs','proof-contract.test.mjs','cleanup.py']:files[name]=base64.b64encode((w/name).read_bytes()).decode()
assets=w.parent/'harness-workspace-browser-20261103/assets';receipts=json.loads((assets/'receipts.json').read_text())
for row in receipts:
 name=row['package']+'.production.min.js';raw=(assets/name).read_bytes();assert sha256(raw).hexdigest()==row['browserFileSha256'];files[name]=base64.b64encode(raw).decode()
files['base.css']=base64.b64encode((assets/'base.css').read_bytes()).decode()
intent={'version':1,'files':{n:sha256(base64.b64decode(v)).hexdigest() for n,v in files.items()},'programFiles':166,'purpose':'isolated formal React component + actual RPC + one owned real static scan','candidateDeployed':False,'apiKeysCopied':False,'r3Qualified':False}
(w/'stage-intent.json').write_text(json.dumps(intent,indent=2)+'\n')
payload=base64.b64encode(gzip.compress(json.dumps({'files':files,'intent':intent,'baseline':json.loads((w/'daily-baseline-program.json').read_text())}).encode())).decode()
source='PAYLOAD='+repr(payload)+'\n'+r'''
from pathlib import Path,PurePosixPath
from tempfile import mkdtemp
from hashlib import sha256
import base64,gzip,json,os,signal,sqlite3,subprocess,time
home=Path('/home/purge');program=home/'tools/dsh-purge-personal-1.1.77-personal.1';runtime=home/'tools/security-workbench';payload=json.loads(gzip.decompress(base64.b64decode(PAYLOAD)))
def protected():
 program_files={str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
 databases={}
 for p in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
  digest=sha256()
  with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for row in db.iterdump():digest.update((row+'\n').encode())
  databases[str(p)]=digest.hexdigest()
 pins={n:sha256((runtime/n).read_bytes()).hexdigest() for n in ['images.json','rules.json']}
 config={str(p):sha256(p.read_bytes()).hexdigest() for p in [home/'.dsh-improved/.credentials.yaml',home/'.dsh-improved/cordis.patch.yml'] if p.is_file()}
 return {'program':program_files,'databases':databases,'pins':pins,'config':config}
before=protected();assert before['program']==payload['baseline'] and len(before['program'])==165
root=Path(mkdtemp(prefix='source-location-live-',dir=home/'.cache'))
(root/'owned-session').write_text('source-location-live-20261103')
for name,encoded in payload['files'].items():
 rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts
 raw=base64.b64decode(encoded);assert sha256(raw).hexdigest()==payload['intent']['files'][name]
 p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
(root/'protected-before.json').write_text(json.dumps(before));(root/'stage-intent.json').write_text(json.dumps(payload['intent']))
proofcheck=subprocess.run([str(home/'.local/node/bin/node'),'--test',str(root/'proof-contract.test.mjs')],cwd=root,capture_output=True,text=True,timeout=20)
(root/'proof-tests.txt').write_text(proofcheck.stdout+proofcheck.stderr);assert proofcheck.returncode==0,proofcheck.stdout+proofcheck.stderr
with (root/'session.log').open('w') as output:
 child=subprocess.Popen([str(home/'.local/node/bin/node'),str(root/'browser-service.mjs')],cwd=root,stdout=output,stderr=output,start_new_session=True)
for attempt in range(160):
 data=(root/'session.log').read_text()
 for line in data.splitlines():
  try:v=json.loads(line)
  except ValueError:continue
  if v.get('browserReady'):
   assert protected()==before
   print(json.dumps({**v,'root':str(root),'pid':child.pid,'programFilesProtected':165,'databasesProtected':len(before['databases']),'noApiKeysCopied':True}));raise SystemExit(0)
 if child.poll() is not None:raise RuntimeError('Isolated service failed: '+data[-6000:])
 time.sleep(.25)
os.killpg(child.pid,signal.SIGTERM)
raise RuntimeError('Isolated service readiness timeout')
'''
(w/'native-stage-source.py').write_text(source.split('\n',1)[1])
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
try:r=m.ssh('python3 -B -',input=source,timeout=95,phase='native-check')
except m.SSHFailure as e:
 (w/'stage-failure.json').write_text(json.dumps({'stdout':e.stdout,'stderr':e.stderr},indent=2)+'\n');raise
v=json.loads(r.stdout);(w/'session.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
