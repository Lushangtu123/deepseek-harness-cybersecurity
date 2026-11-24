import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {SecurityWorkbench,buildScanPlan} from '../package/lib/redteam/personal-security-workbench.mjs';
import {RedteamStore} from '../package/lib/redteam/store-core.js';
import {scanCoverageNotes,modelSecurityResult,securityModelWire} from '../package/lib/redteam/personal-security-model.mjs';
test('Managed Trivy retains redacted-input evidence in child, joint and model views without claiming original-secret coverage',async()=>{
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'trivy-redaction-'))),repo=path.join(base,'repo');fs.mkdirSync(repo);
 fs.writeFileSync(path.join(repo,'settings.txt'),'api_key = "synthetic-original"\n');fs.writeFileSync(path.join(repo,'.env'),'SYNTHETIC_HIDDEN=1');
 const store=new RedteamStore(path.join(base,'state')),eng=store.openEngagement('Redaction coverage').id;
 let observed='';const bench=new SecurityWorkbench(store,{workspaceRoot:base,toolStatus:()=>({trivy:{ready:true,version:'fixture'}}),runner:async(_tool,profile)=>{observed=fs.readFileSync(path.join(profile.repoRoot,'settings.txt'),'utf8');return{complete:true,findings:[],coverageKey:'fixture',coverageFiles:['settings.txt'],inputPolicy:'archive-xml-exclusions-1',dependencyScope:'including-development-1'}}});
 try{
  bench.saveScope(eng,{requestId:'redact-scope-001',revision:0,repoRoot:repo,tools:['trivy'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
  const parent=bench.joint.start(eng,{requestId:'redact-joint-001',profileRevision:1,steps:['trivy']});
  const result=await bench.joint.wait(eng,{id:parent.id,waitSeconds:2});assert.ok(!observed.includes('synthetic-original'));
  const expected={scope:'managed-copy',redactedFiles:1,excludedEntries:1,originalSecretCoverage:'not-proven'};
  assert.deepEqual(result.task.steps[0].inputRedaction,expected);
  assert.ok(result.task.steps[0].coverageNotes.some(note=>note.includes('原始凭据')&&note.includes('未证明')));
  const child=result.task.steps[0].id,raw=await bench.wait(eng,{id:child,waitSeconds:0});assert.deepEqual(raw.run.details.inputRedaction,expected);
  const model=await modelSecurityResult(bench,eng,{op:'securityWait',id:child,waitSeconds:0});assert.deepEqual(model.run.inputRedaction,expected);
  assert.equal(model.run.dependencyScope,'including-development-1');assert.equal(result.task.steps[0].dependencyScope,'including-development-1');assert.equal(raw.run.details.dependencyScope,'including-development-1');
  assert.ok(bench.report(eng).markdown.includes('原始凭据'),'Markdown must retain the redacted-input limitation');
  assert.equal(result.task.coverageComplete,false);assert.equal(result.task.findings,0);
 }finally{await bench.dispose();await store.close();fs.rmSync(base,{recursive:true,force:true})}
});
test('Legacy or malformed input-redaction data cannot create a new coverage claim',()=>{
 assert.deepEqual(scanCoverageNotes('trivy',{}),[]);
 for(const inputRedaction of [{scope:'managed-copy',redactedFiles:-1,excludedEntries:0,originalSecretCoverage:'not-proven'},{scope:'raw',redactedFiles:1,excludedEntries:0,originalSecretCoverage:'complete'}])assert.deepEqual(scanCoverageNotes('trivy',{inputRedaction}),[]);
});
test('Model wire protects redacted-input controls while permitting redaction of explanatory notes',()=>{
 const run={id:'synthetic-control-run',tool:'trivy',state:'completed',inputRedaction:{scope:'managed-copy',redactedFiles:2,excludedEntries:1,originalSecretCoverage:'not-proven'},coverageNotes:['Synthetic explanation']};
 for(const original of [{ok:true,engagement:'fixture',run},{ok:true,engagement:'fixture',runs:[run]},{ok:true,engagement:'fixture',page:{items:[run]}}]){
  const locate=value=>value.run??value.runs?.[0]??value.page.items[0],changed=structuredClone(original);locate(changed).inputRedaction.redactedFiles=0;
  assert.equal(JSON.parse(securityModelWire(original,changed)).ok,false);
  const safe=structuredClone(original);locate(safe).coverageNotes=['[REDACTED]'];assert.equal(JSON.parse(securityModelWire(original,safe)).ok,true);
 }
});
test('Candidate Trivy scans include development dependencies',()=>{
 const plan=buildScanPlan('trivy',{repoRoot:'/home/purge/workspace/fixture'},'/tmp/fixture',{tools:[{tool:'trivy',imageId:'sha256:'+'a'.repeat(64),version:'fixture'}]});
 assert.ok(plan.args.includes('--include-dev-deps'),'Development dependencies remain outside candidate checks');
 assert.match(plan.coverageKey,/^[a-f0-9]{64}$/);
});
test('Recorded development-dependency scope is projected and protected without inventing it for legacy runs',async()=>{
 const original={ok:true,engagement:'fixture',run:{id:'scoped-trivy-run',tool:'trivy',state:'completed',dependencyScope:'including-development-1'}},changed=structuredClone(original);
 changed.run.dependencyScope='production-only';assert.equal(JSON.parse(securityModelWire(original,changed)).ok,false);
 assert.ok(scanCoverageNotes('trivy',{dependencyScope:'including-development-1'}).some(note=>note.includes('开发依赖')));
 assert.deepEqual(scanCoverageNotes('trivy',{dependencyScope:'unknown'}),[]);
});
