import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';

const url=new URL('../package/lib/redteam/personal-workspace-policy.mjs',import.meta.url);
async function api(){assert.ok(existsSync(url),'Workspace policy contract is missing');return import(url)}
const task=(changes={})=>({wallSeconds:120,parallelism:1,cpuMillis:1000,memoryBytes:512*1024**2,pids:64,tmpBytes:64*1024**2,outputBytes:1024*1024,modelRequests:0,outputTokensPerCall:0,...changes});
const step=(id,changes={})=>({id,budget:{wallSeconds:30,cpuMillis:500,memoryBytes:256*1024**2,pids:32,tmpBytes:16*1024**2,outputBytes:1000,modelRequests:0,outputTokensPerCall:0,...changes},priceState:'not-applicable'});
const input=(changes={})=>({mode:'ordinary',task:task(),steps:[step('semgrep'),step('trivy')],nowMs:1000,scopeExpiresAtMs:1000000,...changes});

test('Mode policy describes review/joint mappings without switching an agent or granting execution',async()=>{
 const {workspaceModePolicy}=await api();const ordinary=workspaceModePolicy('ordinary'),deep=workspaceModePolicy('deep');
 assert.equal(ordinary.presetRecommendation,'personal-review');assert.equal(deep.presetRecommendation,'personal-joint');
 assert.equal(ordinary.minimumToolLevel,3);assert.equal(deep.minimumToolLevel,2);
 assert.equal(ordinary.planner,'rules');assert.equal(deep.planner,'model-assisted');
 assert.deepEqual(ordinary.sandboxProfiles,['S1']);assert.deepEqual(deep.sandboxProfiles,['S1','S2','S3']);
 assert.equal(ordinary.changesCurrentPreset,false);assert.equal(deep.executionEnabled,false);assert.equal(deep.currencyHardLimit,false);
 ordinary.sandboxProfiles.push('unsafe');assert.deepEqual(workspaceModePolicy('ordinary').sandboxProfiles,['S1']);
 assert.throws(()=>workspaceModePolicy('full-access'));
});
test('A bounded ordinary candidate accounts all planned steps but is not runtime enforcement',async()=>{
 const {assessWorkspaceBudget}=await api();const r=assessWorkspaceBudget(input());
 assert.equal(r.state,'eligible-preview');assert.equal(r.executionEnforced,false);assert.equal(r.currencyHardLimit,false);
 assert.equal(r.totals.wallSeconds,60);assert.equal(r.totals.outputBytes,2000);assert.equal(r.totals.modelRequests,0);
 assert.equal(r.deadlineMs,121000);assert.ok(r.identity.match(/^[a-f0-9]{64}$/));
});
test('Scope expiration narrows the parent deadline and can make the candidate infeasible',async()=>{
 const {assessWorkspaceBudget}=await api();const r=assessWorkspaceBudget(input({scopeExpiresAtMs:31000}));
 assert.equal(r.deadlineMs,31000);assert.equal(r.state,'unavailable');assert.ok(r.reasons.includes('wall-budget-exceeded'));
 assert.ok(assessWorkspaceBudget(input({scopeExpiresAtMs:1000})).reasons.includes('scope-expired'));
});
test('Resource ceilings, cumulative output and duplicate steps reject candidates',async()=>{
 const {assessWorkspaceBudget}=await api();
 for(const [key,value] of [['cpuMillis',1001],['memoryBytes',513*1024**2],['pids',65],['tmpBytes',65*1024**2]]){
  const r=assessWorkspaceBudget(input({steps:[step('one',{[key]:value})]}));assert.equal(r.state,'unavailable',key);assert.ok(r.reasons.includes('step-resource-exceeded:'+key));
 }
 assert.ok(assessWorkspaceBudget(input({task:task({outputBytes:1500})})).reasons.includes('output-budget-exceeded'));
 assert.ok(assessWorkspaceBudget(input({steps:[step('same'),step('same')]})).reasons.includes('duplicate-step'));
 assert.ok(assessWorkspaceBudget(input({task:task({parallelism:2})})).reasons.includes('parallelism-exceeded'));
});
test('Ordinary mode reserves no model calls; deep unknown pricing remains a separate decision',async()=>{
 const {assessWorkspaceBudget}=await api();const paid={...step('pentagi',{modelRequests:1,outputTokensPerCall:2048}),priceState:'unknown'};
 assert.equal(assessWorkspaceBudget(input({steps:[paid]})).state,'unavailable');
 const deep=input({mode:'deep',task:task({modelRequests:16,outputTokensPerCall:2048}),steps:[paid]});
 assert.equal(assessWorkspaceBudget(deep).state,'needs-decision');
 const r=assessWorkspaceBudget({...deep,steps:[{...paid,priceState:'known'}]});assert.equal(r.state,'eligible-preview');assert.equal(r.totals.maximumOutputTokens,2048);assert.equal(r.currencyHardLimit,false);
});
test('All appended or retried steps consume the same model/output quota',async()=>{
 const {assessWorkspaceBudget}=await api();const steps=[1,2].map(i=>({...step('attempt-'+i,{modelRequests:9,outputTokensPerCall:2048}),priceState:'known'}));
 const r=assessWorkspaceBudget(input({mode:'deep',task:task({modelRequests:16,outputTokensPerCall:2048}),steps}));
 assert.equal(r.totals.modelRequests,18);assert.equal(r.state,'unavailable');assert.ok(r.reasons.includes('model-budget-exceeded'));
});
test('Unknown pricing on a non-model step remains a decision rather than a free action',async()=>{
 const {assessWorkspaceBudget}=await api();const r=assessWorkspaceBudget(input({steps:[{...step('paid-service'),priceState:'unknown'}]}));
 assert.equal(r.state,'needs-decision');assert.ok(r.reasons.includes('price-unconfirmed:paid-service'));
});
test('Malformed, missing, overflowing or unsupported monetary promises fail closed',async()=>{
 const {assessWorkspaceBudget}=await api();
 for(const change of [{task:task({wallSeconds:NaN})},{task:task({pids:-1})},{task:{wallSeconds:60}},{currencyHardLimit:1},{steps:[]}])assert.throws(()=>assessWorkspaceBudget(input(change)));
 const huge=Number.MAX_SAFE_INTEGER;assert.throws(()=>assessWorkspaceBudget(input({steps:[step('a',{outputBytes:huge}),step('b',{outputBytes:huge})]})));
});
test('Budget preview rejects resource values outside the persisted budget schema ranges',async()=>{
 const {assessWorkspaceBudget}=await api();
 for(const change of [{memoryBytes:1},{pids:513},{wallSeconds:3601},{outputBytes:8388609},{parallelism:33}])assert.throws(()=>assessWorkspaceBudget(input({task:task(change)})),JSON.stringify(change));
});
