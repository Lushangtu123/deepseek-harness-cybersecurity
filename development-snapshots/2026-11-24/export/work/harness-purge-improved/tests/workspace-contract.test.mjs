import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const api=()=>import('../package/lib/redteam/personal-workspace-contract.mjs');
const identity='a'.repeat(64);
const tool=(level=3)=>({level,sandbox:'S1',sandboxLevel:3,imageId:'sha256:'+'b'.repeat(64),policyIdentity:'c'.repeat(64)});
const input=(changes={})=>({mode:'ordinary',scopeRevision:1,inputIdentity:identity,files:['src/app.py','requirements.txt'],...changes});

test('Ordinary planning is deterministic, deduplicated, metadata only and needs no Kali',async()=>{
 const {previewWorkspacePlan}=await api();const inventory={semgrep:tool(),trivy:tool(),kali:tool()};
 const a=previewWorkspacePlan(input(),inventory),b=previewWorkspacePlan(input({files:['requirements.txt','src/app.py','src/app.py']}),inventory);
 assert.deepEqual(a,b);assert.equal(a.previewOnly,true);assert.equal(a.executable,false);
 assert.deepEqual(a.steps.map(s=>s.tool),['semgrep','trivy']);assert.ok(a.steps.every(s=>s.sandboxProfile==='S1'&&s.state==='eligible-preview'));
 assert.ok(a.steps.every(s=>s.expectedEvidence.length&&s.reason&&s.resultDestination==='workspace-observations'));
 assert.ok(!JSON.stringify(a).includes('command'));assert.equal(a.steps.filter(s=>s.tool==='kali').length,0);
});
test('A version query or missing sandbox cannot qualify a tool for ordinary checks',async()=>{
 const {previewWorkspacePlan}=await api();
 const p=previewWorkspacePlan(input(),{semgrep:tool(1),trivy:{...tool(),sandboxLevel:0}});
 assert.deepEqual(p.steps.map(s=>s.state),['unavailable','unavailable']);
 assert.equal(p.steps[1].unavailableReason,'sandbox_unavailable');
 assert.ok(p.steps.every(s=>s.coverage==='incomplete'));assert.equal(p.executable,false);
});
test('Bandit is added only for explicitly recorded complementary Python coverage',async()=>{
 const {previewWorkspacePlan}=await api();const inventory={semgrep:tool(),trivy:tool(),bandit:tool()};
 assert.equal(previewWorkspacePlan(input(),inventory).steps.length,2);
 const selected=previewWorkspacePlan(input({banditCoverageDelta:['CWE-703']}),inventory);
 assert.equal(selected.steps.at(-1).tool,'bandit');assert.equal(selected.steps.at(-1).sandboxProfile,'S1');
 const js=previewWorkspacePlan(input({files:['src/app.ts'],banditCoverageDelta:['CWE-703']}),inventory);assert.ok(!js.steps.some(s=>s.tool==='bandit'));
});
test('Configuration-only inputs select Trivy, while unsupported input has an explicit gap',async()=>{
 const {previewWorkspacePlan}=await api();
 const plan=previewWorkspacePlan(input({files:['.env','config/settings.yaml','Dockerfile']}),{trivy:tool()});
 assert.deepEqual(plan.steps.map(step=>step.tool),['trivy']);assert.deepEqual(plan.gaps,[]);
 const unsupported=previewWorkspacePlan(input({files:['notes.txt']}),{});
 assert.deepEqual(unsupported.steps,[]);assert.deepEqual(unsupported.gaps,['no-supported-static-input']);
});
test('Plan identity binds pinned scanner and policy identities rather than readiness alone',async()=>{
 const {previewWorkspacePlan}=await api();const base={semgrep:tool(),trivy:tool()};
 const original=previewWorkspacePlan(input(),base);
 assert.notEqual(original.planIdentity,previewWorkspacePlan(input(),{...base,semgrep:{...tool(),imageId:'sha256:'+'d'.repeat(64)}}).planIdentity);
 assert.notEqual(original.planIdentity,previewWorkspacePlan(input(),{...base,semgrep:{...tool(),policyIdentity:'e'.repeat(64)}}).planIdentity);
 assert.equal(previewWorkspacePlan(input(),{semgrep:{...tool(),policyIdentity:null}}).steps[0].state,'unavailable');
});
test('Static preview includes mode policy and declares an absent budget without becoming executable',async()=>{
 const {previewWorkspacePlan}=await api();
 const p=previewWorkspacePlan(input(),{semgrep:tool(),trivy:tool()});
 assert.equal(p.policy.presetRecommendation,'personal-review');assert.equal(p.policy.changesCurrentPreset,false);
 assert.equal(p.budgetAssessment.state,'unavailable');assert.ok(p.budgetAssessment.reasons.includes('budget-not-declared'));assert.equal(p.executable,false);
});
test('A preview budget is bound to selected tool IDs, scope deadline and its identity',async()=>{
 const {previewWorkspacePlan}=await api();const resource={wallSeconds:30,cpuMillis:500,memoryBytes:268435456,pids:32,tmpBytes:16777216,outputBytes:1000,modelRequests:0,outputTokensPerCall:0};
 const budget={task:{...resource,wallSeconds:120,parallelism:1,outputBytes:10000},steps:['semgrep','trivy'].map(id=>({id,budget:resource,priceState:'not-applicable'})),nowMs:1000,scopeExpiresAtMs:1000000};
 const p=previewWorkspacePlan(input({budget}),{semgrep:tool(),trivy:tool()});
 assert.equal(p.budgetAssessment.state,'eligible-preview');assert.equal(p.budgetAssessment.executionEnforced,false);assert.equal(p.executable,false);
 assert.notEqual(p.planIdentity,previewWorkspacePlan(input({budget:{...budget,scopeExpiresAtMs:31000}}),{semgrep:tool(),trivy:tool()}).planIdentity);
 assert.throws(()=>previewWorkspacePlan(input({budget:{...budget,steps:[{id:'shell',budget:resource,priceState:'not-applicable'}]}}),{}));
});
test('Untrusted or out of scope file names and unsupported plan options fail before selection',async()=>{
 const {previewWorkspacePlan}=await api();
 for(const files of [['../escape.py'],['/home/private.py'],['a\\b.py'],['a\0.py']])assert.throws(()=>previewWorkspacePlan(input({files}),{}));
 for(const change of [{mode:'full-access'},{scopeRevision:0},{inputIdentity:'not-a-digest'},{shell:'anything'},{files:[]}])assert.throws(()=>previewWorkspacePlan(input(change),{}));
});
test('Four task dimensions retain a successful process with incomplete or unknown coverage',async()=>{
 const {describeTaskDimensions}=await api();
 assert.deepEqual(describeTaskDimensions({execution:'ended',ingestion:'recorded',coverage:'incomplete',cleanup:'confirmed'}),{execution:'步骤已结束',ingestion:'已收录',coverage:'覆盖不完整',cleanup:'已确认'});
 assert.equal(describeTaskDimensions({execution:'ended',ingestion:'recorded',coverage:'unknown',cleanup:'unconfirmed'}).coverage,'覆盖未知');
 assert.throws(()=>describeTaskDimensions({execution:'completed',ingestion:'recorded',coverage:'complete',cleanup:'confirmed'}));
 assert.throws(()=>describeTaskDimensions({execution:'ended',ingestion:'recorded',coverage:'checked'}));
});
test('An old successful retest followed by absent coverage queues as unable to judge',async()=>{
 const {findingView}=await api();
 const p={detection:'uncovered',disposition:'unhandled',remediation:'retest-passed',recurrence:false};
 assert.deepEqual(findingView(p),{label:'无法判断',queued:true});
 assert.deepEqual(findingView({...p,detection:'not-detected'}),{label:'已修复',queued:false});
 assert.deepEqual(findingView({...p,remediation:'unfixed',detection:'not-detected'}),{label:'疑似已消失',queued:false});
 assert.deepEqual(findingView({...p,remediation:'registered-fixed'}),{label:'修复待复查',queued:false});
});
test('Persisted problem examples roundtrip into the status projection, including null reason',async()=>{
 const {findingView}=await api();
 const schema=JSON.parse(readFileSync(new URL('../../../docs/security-workspace/contracts.schema.json',import.meta.url),'utf8'));
 const stored=schema.examples.find(row=>row.kind==='problem');
 const project=p=>Object.fromEntries(['detection','disposition','remediation','recurrence','detectionReason'].map(key=>[key,p[key]]));
 assert.deepEqual(findingView(project(stored)),{label:'待处理',queued:true});
 assert.deepEqual(findingView(project({...stored,recurrence:true})),{label:'再次出现',queued:true});
 assert.deepEqual(findingView(project({...stored,detection:'not-detected',detectionReason:'advisory-withdrawn'})),{label:'公告已撤回',queued:false});
});
test('Accepted risk needs a currently valid disposition; evidence is not automatically VEX',async()=>{
 const {findingView}=await api();const p={detection:'present',disposition:'accepted-risk',remediation:'unfixed',recurrence:false};
 assert.deepEqual(findingView({...p,dispositionValid:true}),{label:'已接受风险',queued:false});
 assert.deepEqual(findingView({...p,dispositionValid:false}),{label:'待处理',queued:true});
 assert.deepEqual(findingView(p),{label:'待处理',queued:true});
 assert.ok(!Object.hasOwn(findingView(p),'vex'));assert.throws(()=>findingView({...p,detection:'safe'}));
});
test('Recurrence does not hide registered repair; withdrawn advisories remain distinguishable',async()=>{
 const {findingView}=await api();const p={detection:'present',disposition:'unhandled',remediation:'registered-fixed',recurrence:true};
 assert.deepEqual(findingView(p),{label:'再次出现',queued:false});
 assert.deepEqual(findingView({...p,detection:'not-detected',remediation:'unfixed',detectionReason:'advisory-withdrawn'}),{label:'公告已撤回',queued:false});
});
