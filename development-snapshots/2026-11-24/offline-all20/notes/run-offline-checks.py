from pathlib import Path
from hashlib import sha256
import json,os,re,subprocess,sys,time
R=Path(__file__).resolve().parents[1];D=R/'evidence/offline-final';D.mkdir(exist_ok=False)
rows=[];env=dict(os.environ);env['PATH']=str(R/'operator/blocked-bin')+os.pathsep+env.get('PATH','')
for p in sorted((R/'checks').glob('test_*.py')):
 argv=[sys.executable,'-I','-B',str(p)]
 if p.name=='test_retention.py':argv.append(str(R/'candidate/checks/run_consumer_closure_checks.py'))
 started=time.monotonic();cp=subprocess.run(argv,cwd=R,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
 (D/(p.stem+'.stdout')).write_bytes(cp.stdout);(D/(p.stem+'.stderr')).write_bytes(cp.stderr)
 match=re.findall(rb'Ran ([0-9]+) tests? in',cp.stderr);rows.append({'file':str(p.relative_to(R)),'sourceSha256':sha256(p.read_bytes()).hexdigest(),'command':argv,'exitCode':cp.returncode,'tests':int(match[-1]) if match else None,'seconds':round(time.monotonic()-started,3)})
 print(json.dumps(rows[-1]),flush=True)
summary={'unitOnly':True,'VMGroupsExecuted':0,'formalTargets':'0/16','rows':rows,'total':sum(row['tests'] or 0 for row in rows),'allPassed':all(row['exitCode']==0 for row in rows)};(D/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
raise SystemExit(0 if summary['allPassed'] else 3)
