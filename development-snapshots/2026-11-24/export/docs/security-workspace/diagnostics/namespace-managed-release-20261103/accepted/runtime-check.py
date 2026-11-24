from pathlib import Path
from hashlib import sha256
import ast,importlib.util,json
w=Path(__file__).resolve().parent;baseline=json.loads((w/'baseline.json').read_text());task=json.loads((w/'collected.json').read_text())['report']['task'];tree=ast.parse((w/'deploy-remote.py').read_text());health=ast.unparse(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='healthy'))
source='TASK='+repr(task)+'\nBASELINE='+repr(baseline)+'\n'+"from pathlib import Path\nimport datetime,hashlib,http.client,json,os,re,sqlite3,subprocess,time\nfrom http.cookies import SimpleCookie\nhome=Path('/home/purge')\n"+(w/'helpers.py').read_text()+'\n'+health+r'''
assert healthy() and all(active(u) for u in BASELINE['services']);assert_idle()
worker=home/'tools/dsh-purge-personal-1.1.77-personal.1/scripts/python_namespace_review.py';worker_sha=hashlib.sha256(worker.read_bytes()).hexdigest();assert worker_sha=='9ec513ddb83d94c0c2f63629b7f218b1971704b4ff25d21169f30ad6e0ea9a51'
rules=home/'tools/security-workbench/rules.json';manifest=json.loads((home/'tools/security-workbench/images.json').read_text());assert len(json.loads(rules.read_text())['rules'])==16
since=datetime.datetime.fromisoformat(TASK['startedAt'].replace('Z','+00:00')).timestamp()
r=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/docker','events','--since',str(since),'--until',str(time.time()),'--filter','type=container','--filter','event=create','--filter','label=personal.harness.security=true','--format','{{json .}}'],capture_output=True,text=True,timeout=10);assert r.returncode==0,r.stderr
creates=[json.loads(line) for line in r.stdout.splitlines() if line.strip()];ns=[v for v in creates if v['Actor'].get('Attributes',{}).get('personal.harness.namespace-review')=='1'];scan=[v for v in creates if v['Actor'].get('ID') and v['Actor'].get('Attributes',{}).get('name')=='dsh-sec-'+TASK['steps'][0]['id']];eventWindowComplete=len(scan)==1 and not ns
physical=[]
for backup in ['harness-namespace-managed-release-20261103','harness-namespace-managed-release-retry1-20261103']:
 p=home/'.cache'/backup
 before=json.loads((p/'protected-before.json').read_text())
 if not (p/'protected-stopped.json').is_file():
  physical.append({'attempt':backup,'stoppedReceipt':'not reached; first stop gate failed','physicalDeltaRecorded':False});continue
 after=json.loads((p/'protected-stopped.json').read_text());physical.append({'attempt':backup,'changedPaths':[n for n,h in before['raw'].items() if after['raw'].get(n)!=h],'logicalMatched':before['logical']==after['logical']})
print(json.dumps({'authenticatedStatusReady':True,'servicesActive':{u:active(u) for u in BASELINE['services']},'installedWorkerSha256':worker_sha,'ruleCount':16,'rulesSha256':hashlib.sha256(rules.read_bytes()).hexdigest(),'semgrepImageId':next(t['imageId'] for t in manifest['tools'] if t['tool']=='semgrep'),'dockerEventWindowContainsScanner':eventWindowComplete,'securityContainerCreatesSinceTaskStart':len(creates),'scannerCreateMatchedSameTask':len(scan),'namespaceReviewerCreatesSinceTaskStart':len(ns),'ownedResourceIdle':True,'activeBrowseProject':(home/'.dsh-improved/redteam/current').read_text().strip(),'physicalDatabaseChangesAfterStop':physical}))
'''
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate();v=json.loads(m.ssh('python3 -B -',input=source,timeout=35,phase='native-check').stdout);(w/'runtime-postcheck.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
