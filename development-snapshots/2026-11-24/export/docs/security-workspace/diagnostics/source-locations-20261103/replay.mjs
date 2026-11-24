import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {parseScanOutput,securityFor} from './work/harness-purge-improved/package/lib/redteam/personal-security-workbench.mjs';
import {RedteamStore} from './work/harness-purge-improved/package/lib/redteam/store-core.js';
const hash=v=>createHash('sha256').update(v).digest('hex');
const input=JSON.parse(fs.readFileSync('replay-input.json','utf8')),results={};
for(const [phase,cohort] of Object.entries(input.phases)){
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'source-location-replay-'))),root=path.join(base,'project');fs.mkdirSync(root);
 for(const f of cohort.cases){assert.equal(hash(f.source),f.sha256);fs.writeFileSync(path.join(root,f.file),f.source)}
 const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('location replay '+phase).id,bench=securityFor(store);let calls=0;
 try{
  bench.workspaceRoot=base;bench.pythonEvidence=()=>null;
  bench.toolStatus=()=>({semgrep:{ready:true,version:'replayed-scanner-output-fixture',admissionIdentity:hash('fixture-admission-only')}});
  bench.runner=async()=>{calls++;return{...parseScanOutput('semgrep',structuredClone(cohort.scan)),coverageKey:hash('replay-'+phase)}};
  bench.saveScope(eng,{requestId:'source-scope-'+phase,revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
  const run=bench.joint.start(eng,{mode:'deep',requestId:'source-start-'+phase,profileRevision:1,steps:['semgrep'],budgetSeconds:30});
  const done=await bench.joint.wait(eng,{id:run.id,waitSeconds:30});assert.equal(done.task.state,'completed');assert.equal(calls,1);
  const saved=bench.joint.load(eng,run.id),findings=[];let cursor;
  do{const page=bench.joint.report(eng,{id:run.id,section:'findings',limit:5,...(cursor?{cursor}:{})});findings.push(...page.page.items);cursor=page.page.nextCursor}while(cursor);
  assert.equal(findings.length,cohort.scan.results.length);
  const exact=new Set(cohort.scan.results.map(r=>JSON.stringify([r.check_id,r.path.replace(/^\/src\//,''),r.start,r.end])));
  for(const f of findings){
   const l=f.sourceLocation;assert.equal(f.status,'unverified');assert.equal(l.state,'bound');assert.equal(l.scope,'managed-source-copy');
   assert.equal(l.snapshotId,saved.snapshot.id);assert.equal(l.sourceSha256,hash(fs.readFileSync(path.join(saved.snapshot.sourceRoot,l.path))));
   assert.ok(exact.has(JSON.stringify([f.rule,l.path,l.start,l.end])));
  }
  const rawRows=bench.db(eng).prepare('SELECT data FROM security_joint_finding ORDER BY ordinal').all().map(r=>JSON.parse(r.data));
  assert.equal(rawRows.length,findings.length);assert.deepEqual(rawRows.map(r=>r.sourceLocation),findings.map(r=>r.sourceLocation));
  assert.equal(bench.db(eng).prepare('SELECT COUNT(*) n FROM security_finding').get().n,0);
  const scan={results:findings.map(f=>({check_id:f.rule,path:'/src/'+f.sourceLocation.path,start:f.sourceLocation.start,end:f.sourceLocation.end}))};
  const raw=JSON.stringify(scan);fs.writeFileSync(path.join(base,'bound-scan.json'),raw);
  const manifest={files:Object.fromEntries(saved.snapshot.files.map(f=>[f.path,f.sha256])),scanSha256:hash(raw)};fs.writeFileSync(path.join(base,'bound-manifest.json'),JSON.stringify(manifest));
  const text=execFileSync('/usr/bin/python3',['-I','-B',path.resolve('offline/python_namespace_review.py'),saved.snapshot.sourceRoot,path.join(base,'bound-manifest.json'),path.join(base,'bound-scan.json')],{encoding:'utf8',timeout:8000,maxBuffer:128*1024,env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  const report=JSON.parse(text),expected=phase==='anchors'?6:19;
  assert.equal(report.state,'completed');assert.equal(report.observations.length,expected);assert.equal(report.unmatchedAnchors.length,0);assert.equal(report.r3Qualified,false);
  const conditional=report.observations.filter(r=>r.constraint.state==='fixed-set-guard-observed').length;assert.equal(conditional,phase==='anchors'?0:2);
  results[phase]={fixtureRunnerCalls:calls,newScannerInvocations:0,rawWarnings:cohort.scan.results.length,persistedFindings:rawRows.length,pagedFindings:findings.length,
   bound:findings.length,offlineObservations:report.observations.length,conditionalGuards:conditional,unresolved:report.observations.length-conditional,
   fullRangeAndSourceHashesMatched:true,legacyFindingTableRows:0,sourceLocations:saved.steps[0].details.sourceLocations,
   findings,offlineReport:report,scope:'candidate replay of prior real scanner bytes; fixture admission, not live tool or R3 acceptance'};
 }finally{await bench.dispose();store.close();fs.rmSync(base,{recursive:true,force:true})}
 assert.equal(fs.existsSync(base),false);
}
assert.equal(results.arity17.rawWarnings,results.combined20.rawWarnings);
console.log(JSON.stringify({ok:true,phases:results,sourceOnlyCandidate:true,scannerInvocations:0,modelInvocations:0,findingDispositionChanges:0,r3Qualified:false,temporaryFixturesRemoved:true}));
