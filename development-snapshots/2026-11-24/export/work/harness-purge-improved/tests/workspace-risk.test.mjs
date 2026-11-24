import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';

const url=new URL('../package/lib/redteam/personal-workspace-risk.mjs',import.meta.url);
async function api(){assert.ok(existsSync(url),'Workspace risk contract is missing');return import(url)}
const base=(changes={})=>({id:'sample',firstSeenAtMs:100,detection:'present',disposition:'unhandled',remediation:'unfixed',recurrence:false,category:'dependency',severity:'high',confidence:'high',dependencyScope:'runtime',reachability:'reachable',exposure:'internal',kev:'not-listed',kevExactMatch:false,epssSignal:{band:'low',sourceState:'current'},credentialExposure:'ignored',malwareEvidence:'heuristic',upstreamMatch:'yes',weakHeuristic:false,independentEvidence:false,observationCount:1,previousPriority:null,...changes});
const cases=[
 ['DEP-1','immediate',{kev:'listed',kevExactMatch:true}],
 ['DEP-2','immediate',{reachability:'reproduced'}],
 ['DEP-3','soon',{dependencyScope:'development',kev:'listed',kevExactMatch:true,reachability:'unreachable'}],
 ['DEP-4','soon',{exposure:'public'}],
 ['DEP-5','planned',{severity:'medium'}],
 ['DEP-6','observe',{severity:'low'}],
 ['CODE-1','immediate',{category:'code',reachability:'reproduced'}],
 ['CODE-2','soon',{category:'code',exposure:'public'}],
 ['CODE-3','planned',{category:'code',severity:'medium'}],
 ['CODE-4','observe',{category:'code',severity:'low'}],
 ['CODE-2','soon',{category:'configuration',exposure:'public'}],
 ['CRED-1','immediate',{category:'credential',credentialExposure:'remote'}],
 ['CRED-2','soon',{category:'credential',credentialExposure:'local-commit'}],
 ['CRED-3','planned',{category:'credential',credentialExposure:'uncommitted'}],
 ['CRED-4','observe',{category:'credential'}],
 ['MW-1','immediate',{category:'malware',malwareEvidence:'calibrated-signature',upstreamMatch:'yes'}],
 ['MW-2','soon',{category:'malware',confidence:'medium'}],
 ['MW-3','planned',{category:'malware',confidence:'low',upstreamMatch:'no'}],
 ['MW-4','observe',{category:'malware',confidence:'low'}],
];
for(const [rule,priority,changes] of cases)test(rule+' classifies '+JSON.stringify(changes),async()=>{
 const {rankWorkspaceFinding}=await api();const r=rankWorkspaceFinding(base(changes));assert.equal(r.rule,rule);assert.equal(r.priority,priority);assert.equal(r.queued,true);
});
test('Unknown facts stay unknown while separate conservative ranking inputs are provisional',async()=>{
 const {rankWorkspaceFinding}=await api();const value=base({category:'code',severity:'unknown',exposure:'unknown',confidence:'not-provided'}),before=structuredClone(value),r=rankWorkspaceFinding(value);
 assert.deepEqual(value,before);assert.equal(r.facts.severity,'unknown');assert.equal(r.facts.exposure,'unknown');assert.equal(r.rankingInputs.severity,'high');assert.equal(r.rankingInputs.exposure,'public');
 assert.equal(r.priority,'soon');assert.equal(r.provisional,true);assert.equal(r.assessmentState,'pending');assert.ok(r.missingInputs.includes('severity'));assert.ok(r.missingInputs.includes('exposure'));
});
test('Single weak low-confidence heuristic cap yields to independent or reproduced evidence',async()=>{
 const {rankWorkspaceFinding}=await api();const value=base({category:'code',exposure:'unknown',confidence:'low',weakHeuristic:true});
 assert.equal(rankWorkspaceFinding(value).priority,'planned');
 for(const change of [{independentEvidence:true},{observationCount:2}])assert.equal(rankWorkspaceFinding({...value,...change}).priority,'soon');
 assert.equal(rankWorkspaceFinding({...value,reachability:'reproduced'}).priority,'immediate');
 assert.equal(rankWorkspaceFinding(base({kev:'listed',kevExactMatch:true,confidence:'low',weakHeuristic:true})).priority,'immediate');
});
test('All missing inputs are collected before priority floors',async()=>{
 const {rankWorkspaceFinding}=await api();
 const weakMalware=rankWorkspaceFinding(base({category:'malware',confidence:'low',weakHeuristic:true}));
 assert.equal(weakMalware.assessmentState,'pending');assert.equal(weakMalware.priority,'planned');
});
test('Unrelated category evidence cannot remove a weak-observation cap',async()=>{
 const {rankWorkspaceFinding}=await api();
 const code=rankWorkspaceFinding(base({category:'code',exposure:'public',confidence:'low',weakHeuristic:true,kev:'listed',kevExactMatch:true,malwareEvidence:'calibrated-signature'}));
 assert.equal(code.priority,'planned');
});
test('Unknown incident applicability is not precise KEV evidence; no EPSS for non-CVE is not missing data',async()=>{
 const {rankWorkspaceFinding}=await api();const r=rankWorkspaceFinding(base({kev:'listed',kevExactMatch:false}));
 assert.notEqual(r.rule,'DEP-1');assert.ok(r.missingInputs.includes('kev-applicability'));
 const code=rankWorkspaceFinding(base({category:'code',epssSignal:{band:'unknown',sourceState:'not-applicable'}}));assert.ok(!code.missingInputs.includes('epss'));
});
test('Uncovered history can rise but absent coverage cannot lower its old priority',async()=>{
 const {rankWorkspaceFinding}=await api();const r=rankWorkspaceFinding(base({detection:'uncovered',severity:'low',previousPriority:'immediate'}));
 assert.equal(r.priority,'immediate');assert.ok(r.adjustments.includes('uncovered-priority-retained'));
 assert.equal(rankWorkspaceFinding(base({detection:'uncovered',previousPriority:'observe',kev:'listed',kevExactMatch:true})).priority,'immediate');
});
test('Closed and registered-fix issues use the same queue predicate as the display contract',async()=>{
 const {rankWorkspaceFinding}=await api();
 for(const change of [{disposition:'accepted-risk',dispositionValid:true},{detection:'not-detected'},{remediation:'registered-fixed'}])assert.equal(rankWorkspaceFinding(base(change)).priority,null);
 assert.equal(rankWorkspaceFinding(base({disposition:'accepted-risk',dispositionValid:false})).queued,true);
});
test('Admissible malware evidence cannot be downgraded by upstream equality or a low-confidence observation',async()=>{
 const {rankWorkspaceFinding}=await api();for(const malwareEvidence of ['calibrated-signature','exact-malicious-package','high-confidence-rule']){
  assert.equal(rankWorkspaceFinding(base({category:'malware',malwareEvidence,confidence:'low',weakHeuristic:true})).priority,'immediate');
 }
});
test('Unsupported facts and false score-like values are rejected rather than guessed',async()=>{
 const {rankWorkspaceFinding}=await api();for(const change of [{severity:'safe'},{observationCount:0},{category:'shell'},{confidence:0.9},{command:'anything'},{firstSeenAtMs:NaN}])assert.throws(()=>rankWorkspaceFinding(base(change)));
});

const config={high:0.7,low:0.3,windowMs:3*86400000,maxAgeMs:86400000,maxGapMs:86400000};
const day=86400000;
test('EPSS hysteresis needs explicit calibration; fixtures do not create global product thresholds',async()=>{
 const {updateEpssBand}=await api();assert.throws(()=>updateEpssBand(null,{score:0.8,observedAtMs:day},null,day));
 for(const invalid of [{...config,low:0.8},{...config,windowMs:-1},{...config,high:NaN}])assert.throws(()=>updateEpssBand(null,null,invalid,day));
});
test('High EPSS upgrades immediately and needs consecutive valid low observations to recover',async()=>{
 const {updateEpssBand}=await api();let state=updateEpssBand(null,{score:0.8,observedAtMs:day},config,day);assert.equal(state.band,'high');
 for(let n=2;n<=4;n++){state=updateEpssBand(state,{score:0.2,observedAtMs:n*day},config,n*day);assert.equal(state.band,'high')}
 state=updateEpssBand(state,{score:0.2,observedAtMs:5*day},config,5*day);assert.equal(state.band,'low');
});
test('EPSS configuration changes re-evaluate a repeated sample and restart low-band recovery',async()=>{
 const {updateEpssBand}=await api();const sample={score:0.8,observedAtMs:day};
 const low=updateEpssBand(null,sample,{...config,high:0.9},day);assert.equal(low.band,'low');
 const high=updateEpssBand(low,sample,config,day);assert.equal(high.band,'high');assert.notEqual(high.configurationIdentity,low.configurationIdentity);
 let recovering=updateEpssBand(high,{score:0.2,observedAtMs:2*day},config,2*day);
 recovering=updateEpssBand(recovering,{score:0.2,observedAtMs:3*day},config,3*day);
 const changed=updateEpssBand(recovering,{score:0.2,observedAtMs:3*day},{...config,windowMs:day},3*day);
 assert.equal(changed.band,'high');assert.equal(changed.recoveryStartedAtMs,3*day);
});
test('A missing sample during a configuration change cannot stamp an old classification as current',async()=>{
 const {updateEpssBand}=await api(),sample={score:0.8,observedAtMs:day};
 const old=updateEpssBand(null,sample,{...config,high:0.9},day);
 const missing=updateEpssBand(old,null,config,day);
 const result=updateEpssBand(missing,sample,config,day);
 assert.equal(result.band,'high');assert.equal(result.sourceState,'current');
});
test('Missing/stale data do not advance recovery; gaps and middle-band observations restart it',async()=>{
 const {updateEpssBand}=await api();let high=updateEpssBand(null,{score:0.8,observedAtMs:day},config,day);
 high=updateEpssBand(high,{score:0.2,observedAtMs:2*day},config,2*day);
 const missing=updateEpssBand(high,null,config,5*day);assert.equal(missing.band,'high');assert.equal(missing.sourceState,'unknown');assert.equal(missing.recoveryStartedAtMs,null);
 const stale=updateEpssBand(high,{score:0.2,observedAtMs:2*day},config,5*day);assert.equal(stale.band,'high');assert.equal(stale.sourceState,'stale');assert.equal(stale.recoveryStartedAtMs,null);
 const gap=updateEpssBand(high,{score:0.2,observedAtMs:6*day},config,6*day);assert.equal(gap.band,'high');assert.equal(gap.recoveryStartedAtMs,6*day);
 const middle=updateEpssBand(high,{score:0.5,observedAtMs:3*day},config,3*day);assert.equal(middle.band,'high');assert.equal(middle.recoveryStartedAtMs,null);
});
test('Duplicate, out-of-order and future observations cannot manufacture recovery time',async()=>{
 const {updateEpssBand}=await api();let state=updateEpssBand(null,{score:0.8,observedAtMs:day},config,day);
 state=updateEpssBand(state,{score:0.2,observedAtMs:2*day},config,2*day);
 const repeated=updateEpssBand(state,{score:0.2,observedAtMs:2*day},config,2*day+1000);assert.equal(repeated.recoveryStartedAtMs,2*day);assert.equal(repeated.band,'high');
 const old=updateEpssBand(state,{score:0.1,observedAtMs:day},config,2*day);assert.equal(old.band,'high');assert.equal(old.lastObservedAtMs,2*day);
 const future=updateEpssBand(state,{score:0.1,observedAtMs:4*day},config,3*day);assert.equal(future.band,'high');assert.notEqual(future.sourceState,'current');
});
test('Stale retained high EPSS is shown as pending rather than silently low',async()=>{
 const {rankWorkspaceFinding}=await api();const r=rankWorkspaceFinding(base({epssSignal:{band:'high',sourceState:'stale'}}));assert.equal(r.rule,'DEP-3');assert.equal(r.priority,'soon');assert.equal(r.assessmentState,'pending');assert.ok(r.missingInputs.includes('epss'));
});
test('Priority ordering is stable across severity, confidence and first discovery',async()=>{
 const {rankWorkspaceFinding,compareWorkspaceRisks}=await api();
 const values=[base({id:'late',firstSeenAtMs:200}),base({id:'early',firstSeenAtMs:100}),base({id:'critical',severity:'critical'}),base({id:'immediate',reachability:'reproduced'})].map(rankWorkspaceFinding);
 assert.deepEqual(values.sort(compareWorkspaceRisks).map(row=>row.facts.id),['immediate','critical','early','late']);
});
