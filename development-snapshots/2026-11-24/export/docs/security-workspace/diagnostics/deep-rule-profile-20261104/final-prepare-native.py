from pathlib import Path
from hashlib import sha256
import datetime,json,shutil
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm';kit=w/'kit'
if (w/'native-intent.json').exists():raise SystemExit('Native intent is frozen; use a new run directory')
for directory in ['package','tests']:
 for source in (repo/'work/harness-purge-improved'/directory).rglob('*'):
  if source.is_file() and '__pycache__' not in source.parts and (directory=='package' or source.name.endswith('.test.mjs')):
   p=kit/'work/harness-purge-improved'/directory/source.relative_to(repo/'work/harness-purge-improved'/directory);p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,p)
for source,target in [(w/'replay.mjs',kit/'replay.mjs'),(repo/'scripts/python_namespace_review.py',kit/'offline/python_namespace_review.py')]:
 target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
for name in ['work/harness-purge-improved/security-rules.json','scripts/review_quality_gate.mjs','scripts/workspace_calibration.mjs','scripts/trivy_calibration.mjs',
             'docs/security-workspace/ordinary-calibration-cases.json','docs/security-workspace/contracts.schema.json','docs/security-workspace/prototype.html',
             'docs/security-workspace/calibration-cases.json','docs/security-workspace/calibration-semgrep-vm.json','scripts/python_namespace_review.py','scripts/python_namespace_review.test.py','scripts/namespace_managed_worker.test.py']:
 target=kit/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/name,target)
prior=w.parent/'harness-namespace-arity-20261103';pos=w.parent/'harness-namespace-review-20261103'
phases={};sources=json.loads((prior/'cases.json').read_text());anchors=json.loads((pos/'anchor-cases.json').read_text());anchor_intent=json.loads((pos/'anchor-intent.json').read_text())
for phase in ['arity17','combined20','anchors']:
 p=prior/(phase+'-scan.json') if phase!='anchors' else pos/'anchor-scan.json';receipt=json.loads(p.read_text())
 assert receipt['scannerExitCode']==0 and not receipt['native']['result']['errors']
 cases=sources if phase!='anchors' else [{**c,'sha256':anchor_intent['caseHashes'][c['file']]} for c in anchors]
 phases[phase]={'cases':cases,'scan':receipt['native']['result'],'originalReceiptSha256':sha256(p.read_bytes()).hexdigest(),'scope':'used development data; not independent qualification'}
cve=w.parent/'harness-cve-oracle-20261103';receipt=json.loads((cve/'research20-scan.json').read_text());assert receipt['scannerExitCode']==0 and not receipt['native']['result']['errors']
cases=json.loads((cve/'scan-cases.json').read_text())
for case in cases:case['sha256']=sha256(case['source'].encode()).hexdigest()
phases['pymatgen']={'cases':cases,'scan':receipt['native']['result'],'originalReceiptSha256':sha256((cve/'research20-scan.json').read_bytes()).hexdigest(),'scope':'reused official-CVE development evidence; not new independent qualification'}
(kit/'replay-input.json').write_text(json.dumps({'phases':phases},ensure_ascii=False,indent=2)+'\n')
shutil.copyfile(w/'namespace-live.mjs',kit/'namespace-live.mjs')
intent={'version':1,'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':{str(p.relative_to(kit)):sha256(p.read_bytes()).hexdigest() for p in kit.rglob('*') if p.is_file()},
 'dailyBaselineSha256':sha256((w/'daily-baseline-program.json').read_bytes()).hexdigest(),'candidateDeployed':False,'independentQualificationCasesAdded':0,'r3Qualified':False}
(w/'native-intent.json').write_text(json.dumps(intent,indent=2)+'\n');print(json.dumps({'kitFiles':len(intent['files']),'programFiles':sum(p.is_file() for p in (kit/'work/harness-purge-improved/package').rglob('*')),'phases':len(phases),'newScans':0}))
