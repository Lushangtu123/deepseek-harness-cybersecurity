import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync} from 'node:fs';
const url=new URL('../../../scripts/review_quality_gate.mjs',import.meta.url);
async function api(){assert.ok(existsSync(url),'Review quality gate is missing');return import(url)}

const identity={scanner:'a'.repeat(64),rules:'b'.repeat(64),reviewer:'c'.repeat(64)};
const reviewerSnapshot={version:2,storageSha256:'d'.repeat(64),kind:'python-evidence-reviewer',entrypoint:'eval_evidence_batch.py',
 files:Object.fromEntries(['eval_evidence_batch.py','eval_guard_review.py','eval_import_review.py'].map((name,i)=>[name,String(i+1).repeat(64)])),
 launcherSha256:'e'.repeat(64),imageId:'sha256:'+'f'.repeat(64)};
const cases=[
 {id:'p1',language:'python',cwe:'CWE-95',truth:'positive',sourceSha256:'1'.repeat(64),oracle:{kind:'independent-vulnerability',reference:'fixture-review/p1',positionVerified:true,conditionsVerified:true}},
 {id:'p2',language:'python',cwe:'CWE-95',truth:'positive',sourceSha256:'2'.repeat(64),oracle:{kind:'independent-vulnerability',reference:'fixture-review/p2',positionVerified:true,conditionsVerified:true}},
 {id:'n1',language:'python',cwe:'CWE-95',truth:'negative',sourceSha256:'3'.repeat(64),oracle:{kind:'independent-vulnerability',reference:'fixture-review/n1',positionVerified:true,conditionsVerified:true}},
 {id:'n2',language:'python',cwe:'CWE-95',truth:'negative',sourceSha256:'4'.repeat(64),oracle:{kind:'independent-vulnerability',reference:'fixture-review/n2',positionVerified:true,conditionsVerified:true}},
];
const policy={version:2,role:'candidate-evaluation',categories:{'python/CWE-95':{minimumPositive:2,minimumNegative:2,minimumRawRecall:1,maximumReviewedFalsePositiveRate:0,maximumFalseExclusionRate:0,maximumUnknownRate:0,minimumConfirmedRecall:1}}};
const evidence=row=>({kind:'human-review',caseId:row.id,decision:row.truth==='positive'?'confirmed':'excluded',inputSha256:row.sourceSha256,artifactSha256:createHash('sha256').update('proof:'+row.id).digest('hex')});
const outputs=cases.map(row=>({id:row.id,raw:'hit',location:{line:1,sourceSha256:row.sourceSha256},language:row.language,cwe:row.cwe,decision:row.truth==='positive'?'confirmed':'excluded',evidence:[evidence(row)]}));
async function fixture(){
 const a=await api(),dataset={version:2,cases:structuredClone(cases).map(row=>({...row,location:{line:1,column:1}}))},settings=structuredClone(policy);
 const ledger={version:1,sources:[]};
 identity.reviewer=a.digest(reviewerSnapshot);
 for(const row of dataset.cases)row.selection={method:'predeclared-stratified-holdout',blind:true,qualificationEligible:true,protocolSha256:'d'.repeat(64)};
 const freeze={version:2,reviewerSnapshot:structuredClone(reviewerSnapshot),ledgerSha256:a.digest(ledger),createdAt:'2026-11-03T00:00:00Z',datasetSha256:a.digest(dataset),policySha256:a.digest(settings),identity:{...identity},developmentSourceSha256:[]};
 const run={version:2,freezeSha256:a.digest(freeze),datasetSha256:a.digest(dataset),startedAt:'2026-11-03T01:00:00Z',identity:{...identity},outputs:structuredClone(outputs)};
 run.reviewerExecutions=[{version:2,state:'completed',snapshotSha256:identity.reviewer,datasetSha256:run.datasetSha256,freezeSha256:run.freezeSha256,
  inputSha256:'7'.repeat(64),reportSha256:'8'.repeat(64),startedAt:'2026-11-03T01:00:01Z',finishedAt:'2026-11-03T01:00:02Z'}];
 const f={...a,dataset,policy:settings,freeze,run,ledger,evaluateReviewQuality:(...args)=>a.evaluateReviewQuality(...args,ledger)};
 bindInputs(f);return f;
}

function bindInputs(f,files={
 'manifest.json':'5'.repeat(64),'scan.json':'6'.repeat(64),
 ...Object.fromEntries(cases.map(row=>['sources/'+row.id+'.py',row.sourceSha256])),
}){
 const receipt=f.run.reviewerExecutions[0];
 receipt.inputFiles=structuredClone(files);receipt.scanSha256=files['scan.json'];receipt.inputSha256=f.digest(files);
 return receipt;
}

test('Unrelated reviewer inputs cannot satisfy dataset source coverage',async()=>{
 const f=await fixture();
 bindInputs(f,{'manifest.json':'5'.repeat(64),'scan.json':'6'.repeat(64),'sources/unrelated.py':'9'.repeat(64)});
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.equal(result.state,'blocked');
 assert.ok(result.blockers.includes('reviewer-execution-coverage-incomplete'));
 assert.deepEqual(result.reviewerCoverage.missingCaseIds,cases.map(row=>row.id));
 assert.equal(result.caseBlockers.length,4);
 assert.ok(result.caseBlockers.every(row=>row.reasons.includes('reviewer-execution-source-uncovered')));
});

test('Coverage unions distinct batches and includes negative and diagnostic sources',async()=>{
 const f=await fixture();
 const first=bindInputs(f,{'manifest.json':'5'.repeat(64),'scan.json':'6'.repeat(64),'sources/p1.py':cases[0].sourceSha256,'sources/p2.py':cases[1].sourceSha256});
 const second=structuredClone(first);
 second.inputFiles={'manifest.json':'7'.repeat(64),'scan.json':'8'.repeat(64),'sources/n1.py':cases[2].sourceSha256,'sources/n2.py':cases[3].sourceSha256};
 second.scanSha256=second.inputFiles['scan.json'];second.inputSha256=f.digest(second.inputFiles);
 f.run.reviewerExecutions.push(second);
 const complete=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.equal(complete.state,'diagnostic-only');assert.deepEqual(complete.reviewerCoverage.missingCaseIds,[]);
 f.dataset.cases[3].oracle.kind='authored-control';
 f.freeze.datasetSha256=f.digest(f.dataset);f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
 for(const receipt of f.run.reviewerExecutions){receipt.datasetSha256=f.run.datasetSha256;receipt.freezeSha256=f.run.freezeSha256}
 delete second.inputFiles['sources/n2.py'];second.inputSha256=f.digest(second.inputFiles);
 const incomplete=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(incomplete.blockers.includes('reviewer-execution-coverage-incomplete'));
 assert.deepEqual(incomplete.reviewerCoverage.missingCaseIds,['n2']);
 assert.deepEqual(incomplete.reviewerCoverage.coveredCaseIds,['p1','p2','n1']);
});

test('Manifest and scan digests never count as reviewed source files',async()=>{
 const f=await fixture();
 bindInputs(f,{'manifest.json':cases[0].sourceSha256,'scan.json':cases[1].sourceSha256,'sources/other.py':'9'.repeat(64)});
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(result.blockers.includes('reviewer-execution-coverage-incomplete'));
 assert.deepEqual(result.reviewerCoverage.missingCaseIds,cases.map(row=>row.id));
});

test('Input inventories require bound digests and the supported bounded source paths',async()=>{
 let index=0;
 for(const mutate of [
  r=>{r.inputFiles['sources/p1.py']='9'.repeat(64)},
  r=>{r.scanSha256='9'.repeat(64)},
  r=>{delete r.inputFiles['manifest.json']},
  r=>{delete r.inputFiles['scan.json']},
  r=>{r.inputFiles['sources/../outside.py']='9'.repeat(64)},
  r=>{r.inputFiles['sources/x.py']='invalid'},
  r=>{r.inputFiles['extra.json']='9'.repeat(64)},
  r=>{r.inputFiles=[]},
  r=>{r.inputFiles={'manifest.json':'5'.repeat(64),'scan.json':'6'.repeat(64)}},
  r=>{for(let i=0;i<65;i++)r.inputFiles['sources/excess'+i+'.py']='9'.repeat(64)},
  r=>{r.inputFiles['sources/x.py\n']='9'.repeat(64)},
  r=>{r.inputFiles['sources/unicode_é.py']='9'.repeat(64)},
  r=>{r.inputFiles['sources/x.py']='9'.repeat(64)+'\n'},
 ]){
  const f=await fixture(),receipt=bindInputs(f);mutate(receipt);
  if(index++>0)receipt.inputSha256=f.digest(receipt.inputFiles);
  const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
  assert.ok(result.blockers.includes('reviewer-execution-inputs-missing-or-invalid'));
 }
});

test('A batch supports exactly 64 source files and blocks the sixty-fifth',async()=>{
 const f=await fixture(),receipt=bindInputs(f);
 for(let i=0;i<60;i++)receipt.inputFiles['sources/helper'+i+'.py']='9'.repeat(64);
 receipt.inputSha256=f.digest(receipt.inputFiles);
 assert.equal(f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy).state,'diagnostic-only');
 receipt.inputFiles['sources/excess.py']='9'.repeat(64);receipt.inputSha256=f.digest(receipt.inputFiles);
 assert.ok(f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy).blockers.includes('reviewer-execution-inputs-missing-or-invalid'));
});

test('Duplicate input receipts are rejected even with reordered keys or changed timestamps',async()=>{
 for(const alter of [()=>{},r=>{r.startedAt='2026-11-03T01:00:01.500Z';r.reportSha256='9'.repeat(64);r.inputFiles=Object.fromEntries(Object.entries(r.inputFiles).reverse())}]){
  const f=await fixture(),receipt=bindInputs(f),copy=structuredClone(receipt);alter(copy);
  f.run.reviewerExecutions.push(copy);
  const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
  assert.ok(result.blockers.includes('reviewer-execution-duplicate'));
  assert.equal(result.state,'blocked');assert.equal(result.reviewerCoverage.duplicateReceiptIndices.length,1);
 }
});

test('Failed or globally mismatched receipts cannot contribute source coverage',async()=>{
 for(const mutate of [r=>{r.state='failed'},r=>{r.datasetSha256='9'.repeat(64)},r=>{r.snapshotSha256='9'.repeat(64)}]){
  const f=await fixture(),receipt=bindInputs(f);mutate(receipt);
  const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
  assert.ok(result.blockers.includes('reviewer-execution-missing-or-mismatched'));
  assert.deepEqual(result.reviewerCoverage.coveredCaseIds,[]);
 }
});

test('Legacy receipt versions stay diagnostic without inventing source coverage',async()=>{
 const f=await fixture(),receipt=bindInputs(f);receipt.version=1;
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(result.blockers.includes('reviewer-execution-inputs-missing-or-invalid'));
 assert.equal(result.state,'blocked');assert.equal(result.categories['python/CWE-95'].diagnostic.total,4);
});

test('Python reviewer cannot credit unsupported languages even when source bytes match',async()=>{
 for(const language of ['php','javascript','typescript','java','cpp']){
  const f=await fixture();
  for(const row of f.dataset.cases)row.language=language;
  for(const output of f.run.outputs)output.language=language;
  f.policy.categories={[language+'/CWE-95']:f.policy.categories['python/CWE-95']};
  f.freeze.datasetSha256=f.digest(f.dataset);f.freeze.policySha256=f.digest(f.policy);
  f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
  for(const receipt of f.run.reviewerExecutions){receipt.datasetSha256=f.run.datasetSha256;receipt.freezeSha256=f.run.freezeSha256}
  const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
  assert.equal(result.state,'blocked');assert.ok(result.blockers.includes('reviewer-language-unsupported'));
  assert.deepEqual(result.reviewerCoverage.coveredCaseIds,[]);
  assert.deepEqual(result.reviewerCoverage.unsupportedCaseIds,cases.map(row=>row.id));
  assert.deepEqual(result.reviewerCoverage.missingCaseIds,[]);
  assert.ok(result.caseBlockers.every(row=>row.reasons.includes('reviewer-language-unsupported')));
 }
});

test('Legacy receipts mixed with valid current receipts retain a specific compatibility blocker',async()=>{
 const f=await fixture(),legacy=structuredClone(f.run.reviewerExecutions[0]);legacy.version=1;
 f.run.reviewerExecutions.push(legacy);
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(result.blockers.includes('reviewer-execution-legacy-receipt'));
 assert.deepEqual(result.reviewerCoverage.legacyReceiptIndices,[1]);
 assert.deepEqual(result.reviewerCoverage.invalidReceiptIndices,[1]);
 assert.equal(result.reviewerCoverage.coveredCaseIds.length,4);
 assert.equal(result.state,'blocked');
});

test('Independent overlapping batches may share sources without inflating case coverage',async()=>{
 const f=await fixture(),receipt=bindInputs(f),second=structuredClone(receipt);
 second.inputFiles['sources/helper.py']='9'.repeat(64);second.inputSha256=f.digest(second.inputFiles);
 f.run.reviewerExecutions.push(second);
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.equal(result.state,'diagnostic-only');
 assert.equal(result.reviewerCoverage.coveredCaseIds.length,4);assert.equal(result.categories['python/CWE-95'].total,4);
 assert.deepEqual(result.reviewerCoverage.duplicateReceiptIndices,[]);
});

test('Entry-only reviewer identities cannot qualify without dependency snapshot and execution receipt',async()=>{
 const f=await fixture();
 delete f.freeze.reviewerSnapshot;delete f.run.reviewerExecutions;f.run.freezeSha256=f.digest(f.freeze);
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(r.blockers.includes('reviewer-snapshot-missing-or-invalid'));
 assert.equal(r.state,'blocked');
});

test('New freezes reject a reviewer identity that disagrees with the dependency manifest',async()=>{
 const f=await fixture();
 assert.throws(()=>f.freezeReviewInputs(f.dataset,f.policy,identity,f.ledger,{version:1}),/Invalid/);
});

test('Every reviewer dependency and runtime image is bound to the frozen identity',async()=>{
 for(const field of [...Object.keys(reviewerSnapshot.files),'imageId','launcherSha256','storageSha256']){
  const f=await fixture();
  if(field in f.freeze.reviewerSnapshot.files)f.freeze.reviewerSnapshot.files[field]='9'.repeat(64);
  else f.freeze.reviewerSnapshot[field]=(field==='imageId'?'sha256:':'')+'9'.repeat(64);
  f.run.freezeSha256=f.digest(f.freeze);
  const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
  assert.ok(result.blockers.includes('reviewer-snapshot-identity-mismatch'));
 }
});

test('Completed execution must bind current snapshot, inputs, freeze and chronological run',async()=>{
 for(const change of [
  f=>delete f.run.reviewerExecutions,
  f=>{f.run.reviewerExecutions[0].state='failed'},
  f=>{f.run.reviewerExecutions[0].snapshotSha256='9'.repeat(64)},
  f=>{f.run.reviewerExecutions[0].datasetSha256='9'.repeat(64)},
  f=>{f.run.reviewerExecutions[0].freezeSha256='9'.repeat(64)},
  f=>{f.run.reviewerExecutions[0].inputSha256='invalid'},
  f=>{f.run.reviewerExecutions[0].startedAt=f.freeze.createdAt},
  f=>{f.run.reviewerExecutions[0].finishedAt=f.run.startedAt},
 ]){
  const f=await fixture();change(f);
  assert.ok(f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy).blockers.includes('reviewer-execution-missing-or-mismatched'));
 }
});

test('Snapshot-aware freezes retain complete manifest and reject missing dependencies',async()=>{
 const f=await fixture(),snapshot=structuredClone(reviewerSnapshot);
 const freeze=f.freezeReviewInputs(f.dataset,f.policy,identity,f.ledger,snapshot);
 assert.deepEqual(freeze.reviewerSnapshot,snapshot);
 snapshot.files.eval_guard_review_py='9'.repeat(64);
 assert.notDeepEqual(freeze.reviewerSnapshot,snapshot);
 for(const key of Object.keys(reviewerSnapshot.files)){
  const broken=structuredClone(reviewerSnapshot);delete broken.files[key];
  assert.throws(()=>f.freezeReviewInputs(f.dataset,f.policy,identity,f.ledger,broken));
 }
});

test('Raw and reviewed metrics use explicit denominators and never promote R3',async()=>{
 const f=await fixture(),result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.equal(result.state,'diagnostic-only');
 const group=result.categories['python/CWE-95'];
 assert.equal(group.raw.falsePositiveRate,1);
 assert.equal(group.reviewed.falsePositiveRate,0);
 assert.equal(group.reviewed.confirmedRecall,1);
 assert.equal(group.reviewed.unknownRate,0);
 assert.equal(result.r3Qualified,false);assert.equal(result.executionEnabled,false);
});

test('Unverified guard evidence and hidden findings stay unknown, not true negatives',async()=>{
 const f=await fixture();
 f.run.outputs=f.run.outputs.map(row=>({...row,decision:'unknown',evidence:[{kind:'guard-observation',inputSha256:cases.find(c=>c.id===row.id).sourceSha256,artifactSha256:'d'.repeat(64)}]}));
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy).categories['python/CWE-95'];
 assert.equal(r.reviewed.unknownRate,1);assert.equal(r.reviewed.falsePositiveRate,null);
 assert.equal(r.reviewed.confirmedRecall,0);assert.equal(r.reviewed.trueNegative,0);
});

test('Wrong exclusions, raw misses and false confirmations are measured separately',async()=>{
 const f=await fixture();
 f.run.outputs[0].decision='excluded';f.run.outputs[0].evidence[0].decision='excluded';
 f.run.outputs[1]={id:'p2',raw:'no-hit',decision:'not-required',evidence:[]};
 f.run.outputs[2].decision='confirmed';f.run.outputs[2].evidence[0].decision='confirmed';
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 const group=r.categories['python/CWE-95'];
 assert.equal(group.raw.recall,0.5);assert.equal(group.reviewed.falseExclusionRate,0.5);
 assert.equal(group.reviewed.falsePositiveRate,0.5);assert.equal(group.reviewed.falseNegative,2);
 assert.equal(r.state,'blocked');
});

test('Model assertions and stale evidence cannot supply a verified decision',async()=>{
 const f=await fixture();
 f.run.outputs[0].evidence[0].kind='model-assertion';
 f.run.outputs[1].evidence[0].inputSha256='9'.repeat(64);
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.equal(r.categories['python/CWE-95'].reviewed.unknown,2);
 assert.ok(r.blockers.includes('unsupported-review-evidence'));
});

test('Reused samples, changing thresholds or tool identities block independent acceptance',async()=>{
 for(const [change,reason] of [
  [f=>f.freeze.developmentSourceSha256.push(cases[0].sourceSha256),'development-sample-reused'],
  [f=>{f.policy.categories['python/CWE-95'].maximumUnknownRate=0.2},'thresholds-changed-after-freeze'],
  [f=>{f.run.identity.reviewer='f'.repeat(64)},'candidate-identity-changed'],
  [f=>{f.freeze.createdAt=f.run.startedAt},'freeze-not-before-run'],
 ]){
  const f=await fixture();change(f);f.run.freezeSha256=f.digest(f.freeze);
  assert.ok(f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy).blockers.includes(reason));
 }
});

test('Static rule annotations, unknown coverage and missing results block qualification',async()=>{
 const f=await fixture();
 f.dataset.cases[0].oracle.kind='static-expectation';
 f.freeze.datasetSha256=f.digest(f.dataset);
 f.run.outputs.pop();
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(result.blockers.includes('vulnerability-oracle-incomplete'));
 assert.equal(result.categories['python/CWE-95'].raw.unknown,1);
 assert.equal(result.categories['python/CWE-95'].reviewed.unknown,1);
});

test('Malformed labels, duplicate outputs and impossible decisions are rejected',async()=>{
 const f=await fixture();
 f.run.outputs.push(f.run.outputs[0]);
 assert.throws(()=>f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy));
 const g=await fixture();g.run.outputs[0].raw='no-hit';
 assert.throws(()=>g.evaluateReviewQuality(g.dataset,g.run,g.freeze,g.policy));
 const h=await fixture();h.dataset.cases[0].truth='probably';
 assert.throws(()=>h.evaluateReviewQuality(h.dataset,h.run,h.freeze,h.policy));
});

test('Freeze binds policy and candidate and rejects sources already in the usage ledger',async()=>{
 const f=await fixture();
 const freeze=f.freezeReviewInputs(f.dataset,f.policy,identity,{version:1,sources:[]});
 assert.equal(freeze.datasetSha256,f.digest(f.dataset));
 assert.equal(freeze.policySha256,f.digest(f.policy));
 assert.deepEqual(freeze.identity,identity);
 assert.throws(()=>f.freezeReviewInputs(f.dataset,f.policy,identity,{
  version:1,sources:[{sha256:cases[0].sourceSha256,role:'used-external-regression'}],
 }),/already used/);
});

test('CLI emits a blocked report with exit 2 and bounds ordinary JSON inputs',async()=>{
 const {mkdtempSync,writeFileSync,rmSync}=await import('node:fs');
 const {tmpdir}=await import('node:os');
 const {join}=await import('node:path');
 const {fileURLToPath}=await import('node:url');
 const {spawnSync}=await import('node:child_process');
 const f=await fixture(),root=mkdtempSync(join(tmpdir(),'review-quality-'));
 try{
  f.run.outputs.forEach(row=>{row.decision='unknown'});
  const inputs=[f.dataset,f.run,f.freeze,f.policy,f.ledger].map((value,index)=>{
   const path=join(root,index+'.json');writeFileSync(path,JSON.stringify(value));return path;
  });
  let result=spawnSync(process.execPath,[fileURLToPath(url),...inputs],{encoding:'utf8',timeout:5000});
  assert.equal(result.status,2);
  assert.equal(JSON.parse(result.stdout).state,'blocked');
  writeFileSync(inputs[0],' '.repeat(2*1024*1024+1));
  result=spawnSync(process.execPath,[fileURLToPath(url),...inputs],{encoding:'utf8',timeout:5000});
  assert.equal(result.status,1);assert.equal(result.stdout,'');
 }finally{rmSync(root,{recursive:true,force:true})}
});

test('Unknown negatives cannot improve eligibility through the resolved-only denominator',async()=>{
 const f=await fixture();f.policy.categories['python/CWE-95'].maximumUnknownRate=0.25;
 f.freeze.policySha256=f.digest(f.policy);f.run.freezeSha256=f.digest(f.freeze);
 f.run.outputs[2].decision='unknown';
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.equal(r.state,'blocked');
 assert.equal(r.categories['python/CWE-95'].reviewed.falsePositiveRateUpperBound,0.5);
 assert.ok(r.blockers.includes('python/CWE-95:reviewed-false-positive-bound-unqualified'));
});

test('Duplicated or contradictory source locations cannot inflate labelled counts',async()=>{
 const f=await fixture();f.dataset.cases.push({...f.dataset.cases[0],id:'p1-copy'});
 assert.throws(()=>f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy));
});

test('Evidence must bind the individual case and decision',async()=>{
 const f=await fixture();f.run.outputs[0].evidence[0].caseId='n1';
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.equal(r.categories['python/CWE-95'].reviewed.unknown,1);
});

test('Run replay and ledger substitution cannot qualify a frozen evaluation',async()=>{
 for(const [alter,reason] of [
  [f=>{f.run.datasetSha256='e'.repeat(64)},'run-dataset-mismatch'],
  [f=>{f.run.freezeSha256='e'.repeat(64)},'run-freeze-mismatch'],
  [f=>{f.freeze.ledgerSha256='e'.repeat(64);f.run.freezeSha256=f.digest(f.freeze)},'ledger-history-mismatch'],
  [f=>{f.ledger.sources.push({sha256:f.dataset.cases[0].sourceSha256});f.freeze.ledgerSha256=f.digest(f.ledger);f.run.freezeSha256=f.digest(f.freeze)},'development-sample-reused'],
 ]){
  const f=await fixture();alter(f);const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
  assert.equal(r.state,'blocked');assert.ok(r.blockers.includes(reason));
 }
});

test('Timezone-free timestamps and non-array evidence are invalid',async()=>{
 const f=await fixture();f.run.startedAt='2026-11-03T01:00:00';
 assert.throws(()=>f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy));
 const g=await fixture();g.run.outputs[0].decision='unknown';g.run.outputs[0].evidence='fake';
 assert.throws(()=>g.evaluateReviewQuality(g.dataset,g.run,g.freeze,g.policy));
});

test('Explicit-offset Python microsecond timestamps are accepted consistently',async()=>{
 const f=await fixture();f.run.startedAt='2026-11-03T01:00:00.123456+00:00';
 assert.equal(f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy).state,'diagnostic-only');
});

test('Decision artifacts cannot be recycled across different inputs or decisions',async()=>{
 const f=await fixture();f.run.outputs[1].evidence[0].artifactSha256=f.run.outputs[0].evidence[0].artifactSha256;
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(r.blockers.includes('artifact-binding-conflict'));
 assert.equal(r.categories['python/CWE-95'].reviewed.unknown,2);
});

test('Line-only scan hits cannot be credited to another labelled site',async()=>{
 const f=await fixture();f.run.outputs[0].location.line=2;
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(r.blockers.includes('scan-location-mismatch'));
 assert.equal(r.categories['python/CWE-95'].raw.unknown,1);
 const g=await fixture();g.dataset.cases.push({...g.dataset.cases[0],id:'p1-column-copy',location:{line:1,column:2}});
 assert.throws(()=>g.evaluateReviewQuality(g.dataset,g.run,g.freeze,g.policy));
});

test('Freeze and reports declare every attempt must consume the listed sources',async()=>{
 const f=await fixture(),freeze=f.freezeReviewInputs(f.dataset,f.policy,identity,f.ledger);
 assert.equal(freeze.usageRequired.datasetSha256,f.digest(f.dataset));
 assert.deepEqual(freeze.usageRequired.sourceSha256,[...new Set(f.dataset.cases.map(row=>row.sourceSha256))].sort());
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.deepEqual(result.usageRequired,freeze.usageRequired);
});

test('Scan anchors bind the source digest, language and category, not only line',async()=>{
 for(const mutate of [f=>{f.run.outputs[0].location.sourceSha256='f'.repeat(64)},f=>{f.run.outputs[0].cwe='CWE-79'},f=>{f.run.outputs[0].language='php'}]){
  const f=await fixture();mutate(f);const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
  assert.ok(r.blockers.includes('scan-location-mismatch'));
  assert.equal(r.categories['python/CWE-95'].raw.unknown,1);
  assert.ok(r.caseBlockers.find(row=>row.id==='p1').reasons.includes('scan-location-mismatch'));
 }
});

test('Missing anchors report the specific case and shared decision bindings are checked',async()=>{
 const f=await fixture();delete f.run.outputs[0].location;
 const missing=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(missing.caseBlockers.find(row=>row.id==='p1').reasons.includes('scan-location-mismatch'));
 for(const index of [1,2]){
  const g=await fixture(),row=g.dataset.cases[index],out=g.run.outputs[index];
  row.sourceSha256=g.dataset.cases[0].sourceSha256;row.location.line=index+1;
  out.location={line:index+1,sourceSha256:row.sourceSha256};out.evidence[0].inputSha256=row.sourceSha256;
  out.evidence[0].artifactSha256=g.run.outputs[0].evidence[0].artifactSha256;
  g.freeze.datasetSha256=g.digest(g.dataset);g.run.datasetSha256=g.digest(g.dataset);g.run.freezeSha256=g.digest(g.freeze);
  g.run.reviewerExecutions[0].datasetSha256=g.run.datasetSha256;g.run.reviewerExecutions[0].freezeSha256=g.run.freezeSha256;
  const r=g.evaluateReviewQuality(g.dataset,g.run,g.freeze,g.policy);
  if(index===1){assert.equal(r.state,'diagnostic-only');assert.equal(r.artifactReuse.length,1)}
  else{assert.ok(r.blockers.includes('artifact-binding-conflict'));assert.ok(r.caseBlockers.find(row=>row.id==='p1').reasons.includes('artifact-binding-conflict'))}
 }
});

test('Authored positive controls cannot contribute qualification recall or minimum cases',async()=>{
 const f=await fixture();
 for(const row of f.dataset.cases)if(row.truth==='positive')row.oracle.kind='developer-control';
 f.freeze.datasetSha256=f.digest(f.dataset);f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy),group=r.categories['python/CWE-95'];
 assert.equal(group.positive,0);assert.equal(group.negative,2);assert.equal(group.raw.recall,null);
 assert.equal(group.diagnostic.positive,2);assert.equal(group.diagnostic.raw.recall,1);
 assert.deepEqual(group.excludedFromQualification,['p1','p2']);
 assert.ok(r.blockers.includes('python/CWE-95:raw-recall-below-threshold'));
 assert.ok(r.blockers.includes('python/CWE-95:insufficient-labelled-cases'));
});

test('Unqualified oracles stay diagnostic and cannot dilute independent unknown metrics',async()=>{
 for(const alter of [row=>{row.oracle.kind='developer-control'},row=>{row.oracle.positionVerified=false},row=>{row.oracle.conditionsVerified=false}]){
  const f=await fixture();alter(f.dataset.cases[0]);f.run.outputs[0].decision='unknown';
  f.freeze.datasetSha256=f.digest(f.dataset);f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
  const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy),group=r.categories['python/CWE-95'];
  assert.equal(group.total,3);assert.equal(group.reviewed.unknown,0);assert.equal(group.diagnostic.total,4);assert.equal(group.diagnostic.reviewed.unknown,1);
  assert.deepEqual(group.excludedFromQualification,['p1']);assert.equal(r.state,'blocked');
 }
});

test('Easy authored negatives cannot dilute qualification false-positive denominators',async()=>{
 const f=await fixture();f.run.outputs[2].decision='confirmed';f.run.outputs[2].evidence[0].decision='confirmed';
 for(let i=0;i<10;i++){
  const row={...structuredClone(f.dataset.cases[3]),id:'authored-negative-'+i,sourceSha256:createHash('sha256').update('author-negative-source:'+i).digest('hex')};row.oracle.kind='developer-control';
  f.dataset.cases.push(row);f.run.outputs.push({id:row.id,raw:'no-hit',decision:'not-required',evidence:[]});
 }
 f.freeze.datasetSha256=f.digest(f.dataset);f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
 const r=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy),group=r.categories['python/CWE-95'];
 assert.equal(group.negative,2);assert.equal(group.reviewed.falsePositiveRate,0.5);assert.equal(group.reviewed.falsePositiveRateUpperBound,0.5);
 assert.equal(group.diagnostic.negative,12);assert.equal(group.diagnostic.reviewed.falsePositiveRate,1/12);
 assert.equal(group.excludedFromQualification.length,10);
 assert.ok(r.blockers.includes('python/CWE-95:reviewed-false-positive-rate-unqualified'));
});

test('Known vulnerability pairs remain diagnostic even when their oracle is independently verified',async()=>{
 const f=await fixture();
 for(const row of f.dataset.cases)row.selection={method:'curated-known-vulnerability-pair',blind:false,qualificationEligible:false};
 f.freeze.datasetSha256=f.digest(f.dataset);f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
 const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 const group=result.categories['python/CWE-95'];
 assert.equal(group.positive,0);assert.equal(group.negative,0);
 assert.equal(group.diagnostic.total,4);assert.equal(group.diagnostic.reviewed.confirmedRecall,1);
 assert.equal(result.state,'blocked');assert.ok(result.blockers.includes('sample-selection-ineligible'));
 assert.ok(result.caseBlockers.every(row=>row.reasons.includes('sample-selection-ineligible')));
 assert.deepEqual(group.excludedFromQualification,['p1','p2','n1','n2']);
});

test('Missing or incomplete selection provenance cannot supply admission metrics',async()=>{
 const selections=[undefined,null,[],{},'holdout',
  {method:'predeclared-stratified-holdout',blind:true,qualificationEligible:true},
  {method:'',blind:true,qualificationEligible:true,protocolSha256:'d'.repeat(64)},
  {method:'predeclared-stratified-holdout',blind:'true',qualificationEligible:true,protocolSha256:'d'.repeat(64)},
  {method:'predeclared-stratified-holdout',blind:true,qualificationEligible:'true',protocolSha256:'d'.repeat(64)},
  {method:'predeclared-stratified-holdout',blind:true,qualificationEligible:true,protocolSha256:'not-a-hash'}];
 for(const selection of selections){
  const f=await fixture();
  if(selection===undefined)delete f.dataset.cases[0].selection;
  else f.dataset.cases[0].selection=selection;
  f.freeze.datasetSha256=f.digest(f.dataset);f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
  const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy),group=result.categories['python/CWE-95'];
  assert.equal(group.positive,1);assert.equal(group.negative,2);
  assert.equal(group.diagnostic.total,4);assert.deepEqual(group.excludedFromQualification,['p1']);
  assert.ok(result.blockers.includes('sample-selection-incomplete'));
 }
});

test('Explicit selection exclusions cannot be overridden by the other selection fields',async()=>{
 for(const change of [s=>{s.blind=false},s=>{s.qualificationEligible=false},s=>{s.method='curated-known-vulnerability-pair'}]){
  const f=await fixture();change(f.dataset.cases[2].selection);
  f.freeze.datasetSha256=f.digest(f.dataset);f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(f.freeze);
  const result=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy),group=result.categories['python/CWE-95'];
  assert.equal(group.negative,1);assert.equal(group.diagnostic.negative,2);
  assert.ok(result.blockers.includes('sample-selection-ineligible'));
 }
});

test('Selection declarations are frozen and every diagnostic source still consumes the attempt',async()=>{
 const f=await fixture();
 const frozen=f.freezeReviewInputs(f.dataset,f.policy,identity,f.ledger);
 f.dataset.cases[0].selection.blind=false;
 f.run.datasetSha256=f.digest(f.dataset);f.run.freezeSha256=f.digest(frozen);f.run.startedAt=new Date(Date.parse(frozen.createdAt)+1000).toISOString();
 const result=f.evaluateReviewQuality(f.dataset,f.run,frozen,f.policy);
 assert.ok(result.blockers.includes('dataset-changed-after-freeze'));
 assert.ok(result.blockers.includes('sample-selection-ineligible'));
 assert.deepEqual(result.usageRequired.sourceSha256,frozen.usageRequired.sourceSha256);
 assert.equal(result.r3Qualified,false);assert.equal(result.executionEnabled,false);
});

test('Storage closure is mandatory for new freezes and legacy snapshots stay diagnostic',async()=>{
 const f=await fixture();const legacy=structuredClone(f.freeze.reviewerSnapshot);legacy.version=1;delete legacy.storageSha256;
 const oldIdentity={...f.run.identity,reviewer:f.digest(legacy)};
 assert.throws(()=>f.freezeReviewInputs(f.dataset,f.policy,oldIdentity,f.ledger,legacy),/Invalid/);
 f.freeze.reviewerSnapshot=legacy;f.freeze.identity=oldIdentity;f.run.identity=oldIdentity;
 f.run.freezeSha256=f.digest(f.freeze);f.run.reviewerExecutions[0].snapshotSha256=oldIdentity.reviewer;f.run.reviewerExecutions[0].freezeSha256=f.run.freezeSha256;
 const out=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(out.blockers.includes('reviewer-snapshot-legacy-storage-unbound'));
 assert.equal(out.state,'blocked');assert.equal(out.r3Qualified,false);
 f.freeze.reviewerSnapshot.launcherSha256='9'.repeat(64);f.run.freezeSha256=f.digest(f.freeze);f.run.reviewerExecutions[0].freezeSha256=f.run.freezeSha256;
 const changed=f.evaluateReviewQuality(f.dataset,f.run,f.freeze,f.policy);
 assert.ok(changed.blockers.includes('reviewer-snapshot-identity-mismatch'));
});

test('Valid v2 storage closure with another reviewer identity cannot freeze',async()=>{
 const f=await fixture();const changed=structuredClone(f.freeze.reviewerSnapshot);changed.storageSha256='9'.repeat(64);
 assert.throws(()=>f.freezeReviewInputs(f.dataset,f.policy,f.run.identity,f.ledger,changed),/Invalid/);
});
