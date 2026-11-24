from pathlib import Path
from hashlib import sha256
import base64,importlib.util,json
w=Path(__file__).resolve().parent;baseline=json.loads((w/'baseline.json').read_text());package=json.loads((w.parents[1]/'exports/deepseek-harness-vm/work/harness-purge-improved/package-files.json').read_text());task=json.loads((w/'collected.json').read_text())['report']['task'];synthetic=json.loads((w/'synthetic.json').read_text())
source='BASELINE='+repr(baseline)+'\nPROGRAM='+repr(package)+'\nTASK='+repr(task['id'])+'\nSYNTHETIC='+repr(synthetic)+'\n'+r"""
from pathlib import Path
from hashlib import sha256
import hashlib,json,os,sqlite3,subprocess
home=Path('/home/purge');root=home/'.dsh-improved/redteam';program=home/'tools/dsh-purge-personal-1.1.77-personal.1'
def logical(p):
 h=sha256()
 with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
  for line in db.iterdump():h.update((line+'\n').encode())
 return h.hexdigest()
dbs={n:h for n,h in BASELINE['watched'].items() if n.endswith('/assets.db')};assert all(logical(Path(n))==h for n,h in dbs.items())
configs={n:h for n,h in BASELINE['watched'].items() if not n.endswith('/assets.db')};assert all(sha256(Path(n).read_bytes()).hexdigest()==h for n,h in configs.items())
actual={str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts};assert actual==PROGRAM
with sqlite3.connect((root/'engagements/personal-security-real-20261029/assets.db').as_uri()+'?mode=ro',uri=True) as db:statuses=dict(db.execute('SELECT status,COUNT(*) FROM security_finding GROUP BY status'));assert statuses=={'unverified':95}
with sqlite3.connect((root/'engagements'/SYNTHETIC['engagement']/'assets.db').as_uri()+'?mode=ro',uri=True) as db:
 assert db.execute('SELECT COUNT(*) FROM security_joint').fetchone()[0]==1 and db.execute('SELECT COUNT(*) FROM security_run').fetchone()[0]==1
 v=json.loads(db.execute('SELECT data FROM security_joint WHERE id=?',(TASK,)).fetchone()[0]);assert v['state']=='completed' and v['cleanupVerified'];assert all(f['status']=='unverified' for f in v['findings'])
 assert db.execute('SELECT COUNT(*) FROM security_finding').fetchone()[0]==0
 child=v['steps'][0]['id'];source=v['snapshot']['sourceRoot']
assert not (root/'engagements'/SYNTHETIC['engagement']/'runs/security'/child/'semgrep-rules.json').exists()
r=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/docker','inspect','dsh-sec-'+child],capture_output=True,text=True,timeout=10);assert r.returncode==1 and r.stdout.strip()=='[]' and r.stderr.strip().lower()=='error: no such object: dsh-sec-'+child
image='sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7';control=subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker','image','inspect','--format','{{.Id}}',image],text=True,timeout=10).strip();assert control==image
assert {p.name:sha256(p.read_bytes()).hexdigest() for p in Path(SYNTHETIC['project']).iterdir()}==SYNTHETIC['sourceHashes']
backup=home/'.cache/harness-namespace-managed-release-retry1-20261103/previous';old={str(p.relative_to(backup)):sha256(p.read_bytes()).hexdigest() for p in backup.rglob('*') if p.is_file() and '__pycache__' not in p.parts};assert old==BASELINE['program']
print(json.dumps({'ok':True,'existingDatabaseLogicalDigestsMatched':len(dbs),'protectedConfigDigestsMatched':len(configs),'deployedProgramFilesMatched':len(actual),'rollbackProgramFilesMatched':len(old),'realFindingsByStatus':statuses,'syntheticTasks':1,'syntheticScans':1,'syntheticOrdinaryFindings':0,'allSyntheticUnverified':True,'scannerContainerAbsent':True,'stagedRuleRemoved':True,'syntheticSourcesRetained':5,'managedSnapshotRetained':Path(source).is_dir(),'activeProject':(root/'current').read_text().strip()}))
"""
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate();v=json.loads(m.ssh('python3 -B -',input=source,timeout=40,phase='native-check').stdout)
host=json.loads((w/'host-baseline.json').read_text());assert all(sha256(Path(n).read_bytes()).hexdigest()==h for n,h in host.items());v['hostManagerAndVMConfigUnchanged']=True;(w/'postcheck.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
