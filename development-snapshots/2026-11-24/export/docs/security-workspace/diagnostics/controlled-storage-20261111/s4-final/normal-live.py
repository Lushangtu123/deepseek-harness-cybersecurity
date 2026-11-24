from pathlib import Path
from hashlib import sha256
import importlib.util,json,subprocess,sys
root=Path(__file__).resolve().parent
script=root/'scripts/reviewer_snapshot.py'
spec=importlib.util.spec_from_file_location('snap',script);api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
package=root/'work/harness-purge-improved/package/scripts'
image='sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7'
manifest=api.freeze(package,root/'snapshot',image)
expected=api.digest(manifest)
# Reuse existing authored unit-test controls; no independent R3 samples.
import ast
tree=ast.parse((root/'scripts/eval_evidence_batch.test.py').read_text())
values={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ['CALLER','CALLEE']}
sources=root/'project';sources.mkdir()
for name,value in [('routes.py',values['CALLER']),('evaluator.py',values['CALLEE'])]:(sources/name).write_text(value)
scan={'results':[{'check_id':'policy.harness.python.eval','path':'/src/routes.py','start':{'line':6}}]}
(root/'scan.json').write_text(json.dumps(scan))
request={'files':{p.name:sha256(p.read_bytes()).hexdigest() for p in sources.iterdir()},'scanSha256':sha256((root/'scan.json').read_bytes()).hexdigest(),'discoverImports':True}
(root/'manifest.json').write_text(json.dumps(request))
(root/'snapshot-input.json').write_text(json.dumps(manifest))
node='/home/purge/.local/node/bin/node'
prep="""import {readFileSync,writeFileSync} from 'node:fs';
import {freezeReviewInputs,digest} from './scripts/review_quality_gate.mjs';
const snapshot=JSON.parse(readFileSync('./snapshot-input.json'));
const request=JSON.parse(readFileSync('./manifest.json'));
const dataset={version:2,cases:[{id:'fixture',language:'python',cwe:'CWE-95',truth:'positive',sourceSha256:request.files['routes.py'],location:{line:6,column:1},oracle:{kind:'authored-control',reference:'existing unit-test CALLER'},selection:{method:'synthetic-technical-fixture',blind:false,qualificationEligible:false}}]};
const policy={version:2,role:'candidate-evaluation',categories:{'python/CWE-95':{minimumPositive:1,minimumNegative:1,minimumRawRecall:1,maximumReviewedFalsePositiveRate:0,maximumFalseExclusionRate:0,maximumUnknownRate:0,minimumConfirmedRecall:1}}};
const ledger={version:1,sources:[]},identity={scanner:'a'.repeat(64),rules:'b'.repeat(64),reviewer:digest(snapshot)};
const freeze=freezeReviewInputs(dataset,policy,identity,ledger,snapshot);
writeFileSync('binding.json',JSON.stringify({dataset,policy,ledger,identity,freeze,datasetSha256:digest(dataset),freezeSha256:digest(freeze)}));
"""
(root/'prep.mjs').write_text(prep)
subprocess.run([node,str(root/'prep.mjs')],cwd=root,check=True,capture_output=True)
binding=json.loads((root/'binding.json').read_bytes())
from datetime import datetime,timezone
started=datetime.now(timezone.utc).isoformat()
result=api.execute(root/'snapshot',expected,sources,root/'manifest.json',root/'scan.json',binding['datasetSha256'],binding['freezeSha256'],attempts_root=root/'normal-attempts')
assert result['report']['guardChecks']==1 and result['report']['importChecks']==1
assert result['temporaryRemoved']
(root/'execution.json').write_text(json.dumps(result))
finish="""import {readFileSync,writeFileSync} from 'node:fs';
import {evaluateReviewQuality,digest} from './scripts/review_quality_gate.mjs';
const binding=JSON.parse(readFileSync('binding.json')),execution=JSON.parse(readFileSync('execution.json'));
const run={version:2,identity:binding.identity,startedAt:process.argv[2],datasetSha256:binding.datasetSha256,freezeSha256:binding.freezeSha256,reviewerExecutions:[execution.reviewerExecution],outputs:[{id:'fixture',raw:'hit',decision:'unknown',evidence:[],location:{line:6,sourceSha256:binding.dataset.cases[0].sourceSha256},language:'python',cwe:'CWE-95'}]};
const result=evaluateReviewQuality(binding.dataset,run,binding.freeze,binding.policy,binding.ledger);
if(result.blockers.some(x=>x.startsWith('reviewer-')))throw Error(JSON.stringify(result.blockers));
if(result.state!=='blocked'||result.r3Qualified||result.categories['python/CWE-95'].total!==0)throw Error('Synthetic control incorrectly qualified');
if(result.reviewerCoverage.missingCaseIds.length||result.reviewerCoverage.coveredCaseIds.join(',')!=='fixture')throw Error('Actual receipt failed source coverage');
const wrong=structuredClone(run);wrong.reviewerExecutions[0].inputFiles['sources/routes.py']='9'.repeat(64);wrong.reviewerExecutions[0].inputSha256=digest(wrong.reviewerExecutions[0].inputFiles);
const unrelated=evaluateReviewQuality(binding.dataset,wrong,binding.freeze,binding.policy,binding.ledger);
if(!unrelated.blockers.includes('reviewer-execution-coverage-incomplete')||unrelated.reviewerCoverage.missingCaseIds.join(',')!=='fixture')throw Error('Unrelated input accepted');
const duplicated=structuredClone(run);duplicated.reviewerExecutions.push(structuredClone(duplicated.reviewerExecutions[0]));
const duplicate=evaluateReviewQuality(binding.dataset,duplicated,binding.freeze,binding.policy,binding.ledger);
if(!duplicate.blockers.includes('reviewer-execution-duplicate'))throw Error('Duplicate receipt accepted');
const stale=structuredClone(run);stale.reviewerExecutions[0].inputFiles['sources/routes.py']='9'.repeat(64);
const staleResult=evaluateReviewQuality(binding.dataset,stale,binding.freeze,binding.policy,binding.ledger);
if(!staleResult.blockers.includes('reviewer-execution-inputs-missing-or-invalid'))throw Error('Stale input inventory accepted');
writeFileSync('coverage-checks.json',JSON.stringify({valid:result.reviewerCoverage,unrelated:unrelated.reviewerCoverage,duplicate:duplicate.reviewerCoverage,stale:staleResult.reviewerCoverage,allExpectedBlockers:true}));
writeFileSync('evaluated.json',JSON.stringify(result));
"""
(root/'finish.mjs').write_text(finish)
subprocess.run([node,str(root/'finish.mjs'),started],cwd=root,check=True,capture_output=True)
# Entry stays unchanged while a transitive dependency is changed: reject before launching.
dep=root/'snapshot/eval_guard_review.py';old=dep.read_bytes();dep.write_bytes(old+b'\n# deliberate drift\n')
try:
 api.verify(root/'snapshot',expected)
 raise AssertionError('Dependency drift accepted')
except ValueError as error:
 assert 'digest' in str(error)
finally:dep.write_bytes(old)
print(json.dumps({'snapshot':manifest,'snapshotSha256':expected,'execution':result,'quality':json.loads((root/'evaluated.json').read_bytes()),'dependencyMutationRejected':True,'coverageChecks':json.loads((root/'coverage-checks.json').read_bytes()),'newIndependentSamples':0,'runtimeImageId':image}))
