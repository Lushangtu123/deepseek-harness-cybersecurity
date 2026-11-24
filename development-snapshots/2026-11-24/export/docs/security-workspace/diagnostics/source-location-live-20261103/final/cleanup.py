from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import URLError
import importlib.util,json,socket,time
w=Path(__file__).resolve().parent;session=json.loads((w/'session.json').read_text());origin=(w/'access-url.txt').read_text().strip().rstrip('/')
try:
 with urlopen(Request(origin+'/__stop',data=b'{}',headers={'Origin':origin,'Content-Type':'application/json'}),timeout=45) as response:r=json.load(response)
 (w/'stop-receipt.json').write_text(json.dumps(r,indent=2)+'\n')
except URLError:
 # A self-expired owned process is inspected below; no other service is stopped.
 pass
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
source='SESSION='+repr(session)+'\n'+r'''
from pathlib import Path
from hashlib import sha256
import json,shutil,socket,sqlite3,subprocess,time
home=Path('/home/purge');root=Path(SESSION['root']);assert root.parent==home/'.cache' and root.name.startswith('source-location-live-') and root.resolve()==root
assert (root/'owned-session').read_text()=='source-location-live-20261103'
for _ in range(40):
 if not Path('/proc/'+str(SESSION['pid'])).exists():break
 time.sleep(.1)
assert not Path('/proc/'+str(SESSION['pid'])).exists(),'Owned service did not stop'
with socket.socket() as s:assert s.connect_ex(('127.0.0.1',SESSION['port']))!=0
final=json.loads((root/'final-evidence.json').read_text());assert final['proofValid'] and final['cleanupErrors']==[] and final['newScannerCalls']==1
intent=json.loads((root/'stage-intent.json').read_text());assert all(sha256((root/n).read_bytes()).hexdigest()==v for n,v in intent['files'].items())
proof_tests=(root/'proof-tests.txt').read_text();assert 'fail 0' in proof_tests
before=json.loads((root/'protected-before.json').read_text())
program=home/'tools/dsh-purge-personal-1.1.77-personal.1';actual={str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts};assert actual==before['program']
dbs={}
for p in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
 digest=sha256()
 with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
  for row in db.iterdump():digest.update((row+'\n').encode())
 dbs[str(p)]=digest.hexdigest()
assert dbs==before['databases']
runtime=home/'tools/security-workbench';assert {n:sha256((runtime/n).read_bytes()).hexdigest() for n in before['pins']}==before['pins']
assert all(sha256(Path(n).read_bytes()).hexdigest()==v for n,v in before['config'].items())
for proof in final['proofs']:
 remain=subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker','ps','-aq','--filter','name=^'+proof['containerName']+'$'],text=True,timeout=8);assert not remain.strip()
summary={'ok':True,'programFilesMatched':len(actual),'databaseLogicalDigestsMatched':len(dbs),'pinsAndConfigsMatched':True,'ownedContainersAbsent':len(final['proofs']),'guestPortClosed':True,'ownedProcessAbsent':True,'root':str(root),'final':final}
shutil.rmtree(root);assert not root.exists();summary['temporaryRootRemoved']=True
print(json.dumps(summary))
'''
r=json.loads(m.ssh('python3 -B -',input=source,timeout=30,phase='native-check').stdout)
(w/'cleanup-full.json').write_text(json.dumps(r,indent=2)+'\n');summary={k:v for k,v in r.items() if k!='final'};(w/'cleanup.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
