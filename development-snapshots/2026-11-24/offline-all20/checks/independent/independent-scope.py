"""Independent desired safety assertions over old recorded counterexample families."""
from pathlib import Path
from hashlib import sha256
import subprocess,json,sys
R=Path(__file__).resolve().parent;P=Path(sys.argv[1]).resolve();parts=[];rows=[]
for n in ['independent-directory-check.py','independent-direct-child-check.py','review-followup-checks.py']:
 script=R/'independent-baseline-scripts'/n;cmd=[sys.executable,'-I','-B',str(script),str(P)];v=subprocess.run(cmd,capture_output=True,timeout=60);data=json.loads(v.stdout);parts.append({'script':n,'scriptSha256':sha256(script.read_bytes()).hexdigest(),'command':cmd,'exitCode':v.returncode,'stdout':v.stdout.decode(),'stderr':v.stderr.decode()})
 if n=='independent-directory-check.py':rows.append({'id':'B8-directory-unreadable','passed':data['recoverExitCode']==3 and data['parentReservationHeld'] is True and data['parentSettled'] is not True,'observed':data})
 elif n=='independent-direct-child-check.py':rows.append({'id':'B9-direct-child-parent-current-state','passed':data['secondRecoverExit']==3 and data['parentReservationHeld'] is True and data['parentSettled'] is not True and data['parentCleanupConfirmed'] is not True,'observed':data})
 else:
  for x in data['checks']:
   good=(x['secondExit']==3 and x['childReservationHeld'] is True and x['childCleanupConfirmed'] is not True) if x['id'].startswith('B10') else (x['exitCode']==3 and x['uncaughtException'] is None)
   rows.append({'id':x['id'],'passed':good,'observed':x})
result={'kind':'independent-unified-recovery-safety','manifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'passed':sum(x['passed'] for x in rows),'total':len(rows),'allPassed':all(x['passed'] for x in rows),'checks':rows,'commands':parts,'scope':'Private synthetic records and effect-free resource doubles only; no target or product execution. Reproducer exit0 does not mean safety passed.','formalTargets':'0/16','r3':'blocked'}
print(json.dumps(result,indent=2));raise SystemExit(0 if result['allPassed'] else 1)
