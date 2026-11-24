"""Aggregate fixed independent component and recovery scripts without live resources."""
from pathlib import Path
from hashlib import sha256
import json,subprocess,sys
R=Path(__file__).resolve().parent;P=Path(sys.argv[1]).resolve();project=sys.argv[2:3];rows=[];parts=[]
for name in ['independent-component.py','independent-recovery.py','independent-association.py','independent-scope.py','independent-validation.py','independent-consumers.py','independent-public-consumer.py','independent-settlement-scope.py','independent-public-main.py','independent-recovery-refusal.py']:
 script=R/name;cmd=[sys.executable,'-I','-B',str(script),str(P)]+(project if name=='independent-component.py' else [])
 r=subprocess.run(cmd,capture_output=True,timeout=60);v=json.loads(r.stdout);rows.extend(v['checks']);parts.append({'script':name,'scriptSha256':sha256(script.read_bytes()).hexdigest(),'command':cmd,'exitCode':r.returncode,'stderr':r.stderr.decode(),'passed':v['passed'],'total':v['total']})
out={'kind':'codex-independent-association-recovery-checks','candidateManifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'allPassed':all(x['passed'] for x in rows) and all(x['exitCode']==0 for x in parts),'passed':sum(x['passed'] for x in rows),'total':len(rows),'checks':rows,'components':parts,'newSelfchecks':0,'formalTargets':'0/16','r3':'blocked'}
print(json.dumps(out,indent=2));raise SystemExit(0 if out['allPassed'] else 1)
