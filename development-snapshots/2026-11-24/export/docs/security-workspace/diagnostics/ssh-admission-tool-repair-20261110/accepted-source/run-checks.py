from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json,subprocess,sys,time
root=Path(__file__).resolve().parent
receipt=root/'checks.json'
if receipt.exists():raise SystemExit('Existing check receipt; do not replace')
files=['tooling/admission.py','record-analysis.py','tooling/regression.test.py','tooling/analysis.test.py','inputs/manage.py','inputs/ssh-queue.test.py','tooling/r2.test.py']
def digest(p):return sha256(p.read_bytes()).hexdigest()
before={name:digest(root/name) for name in files};rows=[]
for name in ['tooling/regression.test.py','tooling/analysis.test.py','inputs/ssh-queue.test.py','tooling/r2.test.py']:
 argv=[sys.executable,'-I','-B',str(root/name)];start=datetime.now(timezone.utc).isoformat();began=time.monotonic()
 result=subprocess.run(argv,capture_output=True,text=True,timeout=30)
 log=root/(Path(name).stem+'.checked.txt');log.write_text(result.stdout+result.stderr)
 rows.append({'argv':argv,'startedAtUtc':start,'finishedAtUtc':datetime.now(timezone.utc).isoformat(),'elapsedSeconds':round(time.monotonic()-began,3),'exitCode':result.returncode,'log':log.name,'logSha256':digest(log),'testedSourceSha256':before[name]})
after={name:digest(root/name) for name in files}
value={'state':'passed' if all(r['exitCode']==0 for r in rows) and before==after else 'failed','sourceHashes':before,'sourcesUnchanged':before==after,'suites':rows,'newVmRequests':0,'newLoopbackControlRuns':0,'scope':'synthetic lifecycle and evidence validation plus existing manager regression; no SSH process or daily configuration modification'}
receipt.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(value,ensure_ascii=False));raise SystemExit(0 if value['state']=='passed' else 1)
