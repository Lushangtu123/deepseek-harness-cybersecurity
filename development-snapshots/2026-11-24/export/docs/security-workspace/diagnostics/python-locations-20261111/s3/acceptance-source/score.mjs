import {readFileSync,writeFileSync} from 'node:fs';import {digest,freezeReviewInputs,evaluateReviewQuality} from './scripts/review_quality_gate.mjs';
const read=n=>JSON.parse(readFileSync(n,'utf8')),write=(n,v)=>writeFileSync(n,JSON.stringify(v,null,2)+'\n'),must=(v,m)=>{if(!v)throw Error(m)};
const policy=read('policy.json'),ledger=read('ledger.json'),snapshot=read('snapshot/snapshot.json'),loc=read('locations.json');
const identity={scanner:digest(read('scanner-identity.json')),rules:read('scanner-identity.json').candidateRulesSha256,reviewer:digest(snapshot)};
if(process.argv[2]==='bind'){
 const old=read('historical-dataset.json'),binding=loc.locationBinding;
 const rows=old.cases.map(r=>{const file=binding.inventory.files[r.file],p=file.points.find(p=>p.call.start.line===r.location.line);must(file.points.length===0||p,'Historical point not unique');return{...r,path:r.file,pointId:p?.id??null,location:p?{line:p.call.start.line,column:p.call.start.col}:null}});
 for(const [i,p] of binding.inventory.files['boundary.py'].points.entries())rows.push({id:'synthetic-boundary-'+i,path:'boundary.py',pointId:p.id,sourceSha256:p.sourceSha256,location:{line:p.call.start.line,column:p.call.start.col},language:'python',cwe:p.callee.endsWith('exec')?'CWE-94':'CWE-95',truth:'positive',oracle:{kind:'synthetic-location-control',reference:'byte-boundary only, no runtime truth'},selection:{method:'authored-diagnostic',blind:false,qualificationEligible:false}});
 const dataset={version:3,cases:rows},used=[...new Set(ledger.sources.map(s=>s.sha256))].sort();
 let rejected=false;try{freezeReviewInputs(dataset,policy,identity,ledger,snapshot,[loc])}catch(e){must(e.message==='Acceptance source already used in the sample ledger',e.message);rejected=true}must(rejected,'Used sample freeze was accepted');
 const locations=[{reviewerExecution:loc.reviewerExecution,locationBinding:loc.locationBinding,reportJson:loc.reportJson}];
 const freeze={version:3,diagnosticOnly:true,createdAt:new Date().toISOString(),datasetSha256:digest(dataset),policySha256:digest(policy),ledgerSha256:digest(ledger),identity,reviewerSnapshot:snapshot,developmentSourceSha256:used,locations,locationsSha256:digest(locations)};
 write('diagnostic-dataset.json',dataset);write('diagnostic-freeze.json',freeze);write('binding.json',{identity,datasetSha256:digest(dataset),freezeSha256:digest(freeze),historicalFreezeRejected:rejected});
}else{
 const data=read('diagnostic-dataset.json'),freeze=read('diagnostic-freeze.json'),binding=read('binding.json'),execution=read('execution.json'),scan=read('candidate-scan.json'),maps=execution.report.findingLocations;
 must(maps.length===scan.results.length,'Raw mapping count does not close');
 const byCase=data.cases.map(c=>{const hits=maps.filter(m=>m.state==='bound'&&m.pointId===c.pointId&&m.path===c.path),ambiguous=maps.some(m=>m.path===c.path&&m.state==='unmatched'&&typeof m.rule==='string'&&['policy.harness.python.eval','policy.harness.python.exec','policy.harness.python.request-to-dynamic-code'].includes(m.rule));return{...c,raw:ambiguous?'unknown':hits.length?'hit':'no-hit',rawHits:hits.length}});
 const outputs=byCase.map(c=>({id:c.id,raw:c.raw,decision:c.raw==='no-hit'?'not-required':'unknown',pointId:c.pointId,location:{...c.location,sourceSha256:c.sourceSha256},language:c.language,cwe:c.cwe,evidence:[]}));
 const run={version:3,identity,startedAt:read('run-start.json').startedAt,datasetSha256:binding.datasetSha256,freezeSha256:binding.freezeSha256,reviewerExecutions:[execution.reviewerExecution],reviewArtifacts:[execution.reviewArtifact],outputs};
 const quality=evaluateReviewQuality(data,run,freeze,policy,ledger);must(quality.version===7&&quality.state==='blocked'&&!quality.r3Qualified,'Diagnostic qualification changed');
 must(!quality.blockers.some(x=>x.startsWith('reviewer-')||x.startsWith('review-artifact')||x==='frozen-locations-invalid-or-changed'||x==='execution-point-output-mismatch'),'Binding failed '+quality.blockers.join(','));
 must(quality.reviewerCoverage.coveredCaseIds.length===data.cases.length,'Missing cases');
 must(quality.executionPoints.every(p=>p.actual.raw===outputs.find(o=>o.id===p.id).raw),'Declared versus actual raw mismatch');
 const historical=byCase.filter(c=>!c.id.startsWith('synthetic-'));must(historical.length===4&&historical.every(c=>c.raw!=='unknown'),'Historical mapping unknown');
 must(byCase.some(c=>c.rawHits>1),'No actual duplicate rule mapping exercised');
 write('diagnostic-run.json',run);write('vm-quality.json',quality);write('case-evidence.json',{byCase:byCase.map(c=>({id:c.id,path:c.path,pointId:c.pointId,raw:c.raw,rawHits:c.rawHits})),rawHits:maps.length,bound:maps.filter(m=>m.state==='bound').length,unmatched:maps.filter(m=>m.state==='unmatched').length,ignored:maps.filter(m=>m.state==='ignored').length,uniqueHitPoints:new Set(maps.filter(m=>m.state==='bound').map(m=>m.pointId)).size,priorSamplesOnly:true,newIndependentSamples:0,reviewerDecisionsConfirmed:0});
}
