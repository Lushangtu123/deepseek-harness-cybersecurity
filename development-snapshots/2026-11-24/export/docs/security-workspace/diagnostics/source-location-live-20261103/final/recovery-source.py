
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
final=json.loads((root/'final-evidence.json').read_text());assert final['proofValid'] and final['cleanupErrors']==['Container absence not proven'] and final['newScannerCalls']==1
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
absence=[]
for proof in final['proofs']:
 ident=proof['observed']['containerId'];assert len(ident)==64 and set(ident)<=set('0123456789abcdef')
 r=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/docker','inspect',ident],capture_output=True,text=True,timeout=8)
 assert r.returncode==1 and r.stdout.strip()=='[]' and r.stderr.strip().casefold()=='error: no such object: '+ident
 control=subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker','image','inspect','--format','{{.Id}}',proof['expected']['image']],text=True,timeout=8).strip();assert control==proof['expected']['image']
 absence.append({'containerId':ident,'absent':True,'imageControlMatched':True})
 remain=subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker','ps','-aq','--filter','name=^'+proof['containerName']+'$'],text=True,timeout=8);assert not remain.strip()
summary={'ok':True,'recovery':{'cause':'case-sensitive Docker no-such-object parser rejected lowercase error','originalFailurePreserved':True,'revalidatedAbsence':absence},'programFilesMatched':len(actual),'databaseLogicalDigestsMatched':len(dbs),'pinsAndConfigsMatched':True,'ownedContainersAbsent':len(final['proofs']),'guestPortClosed':True,'ownedProcessAbsent':True,'root':str(root),'final':final}
shutil.rmtree(root);assert not root.exists();summary['temporaryRootRemoved']=True
print(json.dumps(summary))
