from pathlib import Path
from hashlib import sha256
import datetime,json,shutil
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm';prior=w.parent/'harness-namespace-arity-20261103'
if (w/'protocol.json').exists():raise SystemExit('Use a new run directory; protocol is frozen')
review=w/'review';(review/'scripts').mkdir(parents=True,exist_ok=True)
for name in ['python_namespace_review.py','python_namespace_review.test.py']:
 shutil.copyfile(repo/'scripts'/name,review/'scripts'/name)
helpers=review/'work/harness-purge-improved/package/scripts';helpers.mkdir(parents=True,exist_ok=True)
for name in ['eval_evidence_batch.py','eval_guard_review.py','eval_import_review.py']:
 shutil.copyfile(repo/'work/harness-purge-improved/package/scripts'/name,helpers/name)
cases=json.loads((prior/'cases.json').read_text());sources={}
(w/'src').mkdir(exist_ok=True)
for row in cases:
 raw=row['source'].encode();assert sha256(raw).hexdigest()==row['sha256'];(w/'src'/row['file']).write_bytes(raw);sources[row['file']]=row['sha256']
scans={}
for phase in ['arity17','combined20']:
 original=(prior/(phase+'-scan.json')).read_bytes();receipt=json.loads(original)
 raw=(json.dumps(receipt['native']['result'],indent=2)+'\n').encode();(review/(phase+'-scan.json')).write_bytes(raw)
 manifest={'files':sources,'scanSha256':sha256(raw).hexdigest()};(review/(phase+'-manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n')
 scans[phase]={'originalReceiptSha256':sha256(original).hexdigest(),'rawResultSha256':sha256(raw).hexdigest(),'warningsBefore':len(receipt['native']['result']['results'])}
protocol={'version':1,'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'scope':'Reused development sources and raw scans only; static reviewer, no source execution or finding changes',
          'imageId':'sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7',
          'probeSha256':sha256((w/'probe.py').read_bytes()).hexdigest(),'sources':sources,
          'reviewFiles':{str(p.relative_to(review)):sha256(p.read_bytes()).hexdigest() for p in review.rglob('*') if p.is_file()},
          'expectedConditionalGuardFiles':['guard-complete-eval.py','guard-complete-exec.py'],
          'expectedObservations':19,'sourceCases':26,'scans':scans,'independentCasesAdded':0,'r3Qualified':False}
(w/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
print(json.dumps({'sourceCases':26,'expectedObservations':19,'conditionalGuards':2,'allOtherConstraints':'unresolved'}))
