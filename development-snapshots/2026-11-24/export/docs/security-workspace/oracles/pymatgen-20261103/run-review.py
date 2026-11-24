from pathlib import Path
from hashlib import sha256
import base64,gzip,importlib.util,json
w=Path(__file__).resolve().parent;plan=json.loads((w/'protocol-v3.json').read_text());files={'review.mjs':(w/'review.mjs').read_bytes()}
for v in ['vulnerable','patched']:files['project/'+v+'.py']=(w/(v+'.py')).read_bytes()
for v in ['baseline16','research20']:files[v+'.json']=json.dumps(json.loads((w/(v+'-scan.json')).read_text())['native']['result']).encode()
payload=base64.b64encode(gzip.compress(json.dumps({n:base64.b64encode(b).decode() for n,b in files.items()}).encode())).decode()
s='PAYLOAD='+repr(payload)+'\nEXPECTED='+repr(plan['candidateProgram'])+'\n'+r'''
from pathlib import Path,PurePosixPath
from tempfile import TemporaryDirectory
from hashlib import sha256
import base64,gzip,json,sqlite3,subprocess,time
home=Path('/home/purge');program=home/'tools/dsh-purge-personal-1.1.77-personal.1'
def inventory():return{str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def databases():
 d={}
 for p in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
  h=sha256()
  with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for line in db.iterdump():h.update((line+'\n').encode())
  d[str(p)]=h.hexdigest()
 return d
assert inventory()==EXPECTED;before=databases();pins={n:sha256((home/'tools/security-workbench'/n).read_bytes()).hexdigest() for n in ['rules.json','images.json']};started=time.time()
with TemporaryDirectory(prefix='cve-namespace-structure-',dir=home/'.cache') as temporary:
 root=Path(temporary)
 for name,raw in json.loads(gzip.decompress(base64.b64decode(PAYLOAD))).items():
  rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts;p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(raw))
 r=subprocess.run([str(home/'.local/node/bin/node'),'review.mjs'],cwd=root,capture_output=True,text=True,timeout=35);assert r.returncode==0,r.stderr;result=json.loads(r.stdout)
 events=subprocess.check_output(['sudo','-n','/usr/bin/docker','events','--since',str(started),'--until',str(time.time()),'--filter','type=container','--filter','event=create','--filter','label=personal.harness.namespace-review=1','--format','{{json .}}'],text=True,timeout=10);created=[json.loads(line) for line in events.splitlines() if line.strip()];assert len(created)==1;result['observedNamespaceContainerCreates']=1
assert not root.exists() and inventory()==EXPECTED and databases()==before and pins=={n:sha256((home/'tools/security-workbench'/n).read_bytes()).hexdigest() for n in pins};result.update(programFilesMatched=169,oldDatabaseLogicalHashesMatched=len(before),pinsUnchanged=True,temporaryRemoved=True);print(json.dumps(result))
'''
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate();v=json.loads(m.ssh('python3 -B -',input=s,timeout=55,phase='native-check').stdout);(w/'structure-review.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({'phases':[{k:r[k] for k in ['phase','originalWarnings','summary']} for r in v['rows']],'namespaceContainers':v['observedNamespaceContainerCreates'],'programFilesMatched':v['programFilesMatched'],'oldDatabases':v['oldDatabaseLogicalHashesMatched']}))
