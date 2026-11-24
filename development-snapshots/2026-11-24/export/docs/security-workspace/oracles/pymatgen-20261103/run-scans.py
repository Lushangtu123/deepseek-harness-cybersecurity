from pathlib import Path
from hashlib import sha256
import base64,datetime,gzip,importlib.util,json
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm';plan=json.loads((w/'protocol.json').read_text());raw=(w/'scan-cases.json').read_bytes();cases=json.loads(raw)
assert all(sha256(r['source'].encode()).hexdigest()==plan['inputs']['/src/'+r['file']] for r in cases)
paths={'baseline16':repo/'work/harness-purge-improved/security-rules.json','research20':repo/'docs/security-workspace/namespace-combined20.candidate.json'};assert all(sha256(p.read_bytes()).hexdigest()==plan['scannerInputs'][k] for k,p in paths.items())
body=(w.parent/'harness-ordinary-calibration-20261103/native-rules.py').read_text();body=body.replace('print(json.dumps(result))',"assert program()==program_before and databases()==db_before\nresult['dailyProgramFilesMatched']=len(program_before);result['projectDatabaseLogicalHashesMatched']=len(db_before)\nresult['startedAt']=started;result['finishedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()\nprint(json.dumps(result))")
prefix=r'''
from pathlib import Path
from hashlib import sha256
import datetime,json,sqlite3
p=Path('/home/purge/tools/dsh-purge-personal-1.1.77-personal.1')
def program():return{str(f.relative_to(p)):sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file() and '__pycache__' not in f.parts}
def databases():
 out={}
 for f in Path('/home/purge/.dsh-improved/redteam/engagements').glob('*/assets.db'):
  h=sha256()
  with sqlite3.connect(f.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for line in db.iterdump():h.update((line+'\n').encode())
  out[str(f)]=h.hexdigest()
 return out
program_before=program();assert program_before==EXPECTED
db_before=databases();started=datetime.datetime.now(datetime.timezone.utc).isoformat()
'''
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
for phase in ['baseline16','research20']:
 payload={'phase':'baseline' if phase=='baseline16' else 'research20','candidateRules':paths[phase].read_text(),'outputPolicy':(repo/'work/harness-purge-improved/package/scripts/security-output.sh').read_text(),'cases':cases,'datasetSha256':sha256(raw).hexdigest()};encoded=base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode();source='PAYLOAD='+repr(encoded)+'\nEXPECTED='+repr(plan['candidateProgram'])+'\n'+prefix+body
 r=m.ssh('python3 -B -',input=source,timeout=110,phase='native-check');v=json.loads(r.stdout);assert v['rulesSha256']==plan['scannerInputs'][phase];(w/(phase+'-scan.json')).write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({'phase':phase,'hits':len(v['native']['result']['results']),'errors':len(v['native']['result']['errors']),'scanned':v['native']['result']['paths']['scanned'],'programs':v['dailyProgramFilesMatched'],'oldDatabases':v['projectDatabaseLogicalHashesMatched'],'cleaned':v['containerAbsent'] and v['temporaryRemoved']}),flush=True)
