from pathlib import Path
from hashlib import sha256
import importlib.util,json
w=Path(__file__).resolve().parent;plan=json.loads((w/'protocol-v3.json').read_text());manager=Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py';before=sha256(manager.read_bytes()).hexdigest();spec=importlib.util.spec_from_file_location('m',manager);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
source='EXPECTED='+repr(plan['candidateProgram'])+'\n'+r'''
from pathlib import Path
from hashlib import sha256
import json,os,sqlite3,subprocess
home=Path('/home/purge');p=home/'tools/dsh-purge-personal-1.1.77-personal.1';assert {str(f.relative_to(p)):sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file() and '__pycache__' not in f.parts}==EXPECTED
docker=['sudo','-n','/usr/bin/docker'];names=subprocess.check_output([*docker,'ps','-a','--format','{{.Names}}'],text=True,timeout=8).splitlines();assert not any(n.startswith(('independent-lab-oracle-','ordinary-rules-','cve-namespace-structure-','pymatgen-runtime-check-')) for n in names)
assert not any(home.joinpath('.cache').glob('independent-lab-oracle-*')) and not any(home.joinpath('.cache').glob('ordinary-rules-*')) and not any(home.joinpath('.cache').glob('cve-namespace-structure-*'))
assert not subprocess.check_output([*docker,'ps','-aq','--filter','label=personal.harness.namespace-review=1'],text=True,timeout=8).strip()
with sqlite3.connect((home/'.dsh-improved/redteam/engagements/personal-security-real-20261029/assets.db').as_uri()+'?mode=ro',uri=True) as db:statuses=dict(db.execute('SELECT status,COUNT(*) FROM security_finding GROUP BY status'));assert statuses=={'unverified':95}
services={u:subprocess.run(['systemctl','--user','is-active',u],env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'},capture_output=True,text=True,timeout=6).returncode==0 for u in ['dsh-original.service','harness-security.socket','harness-security.service']};assert all(services.values());rules=home/'tools/security-workbench/rules.json';assert len(json.loads(rules.read_text())['rules'])==16
print(json.dumps({'dailyProgramFilesMatched':169,'servicesActive':services,'ruleCount':16,'rulesSha256':sha256(rules.read_bytes()).hexdigest(),'realFindingStates':statuses,'diagnosticContainersAbsent':True,'diagnosticDirectoriesAbsent':True,'namespaceWorkersAbsent':True,'browseProject':(home/'.dsh-improved/redteam/current').read_text().strip()}))
'''
v=json.loads(m.ssh('python3 -B -',input=source,timeout=25,phase='native-check').stdout);assert sha256(manager.read_bytes()).hexdigest()==before;v['hostManagerUnchanged']=True;(w/'postcheck.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
