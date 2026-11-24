import {deepSemgrepProfile} from '../package/lib/redteam/personal-semgrep-profile.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {RedteamStore} from '../package/lib/redteam/store-core.js';
import {SecurityWorkbench,executeSecurityOp,securityFor} from '../package/lib/redteam/personal-security-workbench.mjs';
import {createSecurityServer,requestSecurityService} from '../package/lib/redteam/personal-security-service.mjs';
import {jointModelWire} from '../package/lib/redteam/personal-joint-review.mjs';

const identities={semgrep:'a'.repeat(64),trivy:'b'.repeat(64)};
function fixture(){
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'workspace-dispatch-'))),root=path.join(base,'repo');
 fs.mkdirSync(root);fs.writeFileSync(path.join(root,'app.py'),'eval(input())\n');
 const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('Mode fixture').id,bench=securityFor(store),calls=[];
 bench.workspaceRoot=base;
 bench.toolStatus=()=>Object.fromEntries(Object.entries(identities).map(([tool,admissionIdentity])=>[tool,{ready:true,version:'fixture',admissionIdentity,...(tool==='semgrep'?{rules:{sha256:deepSemgrepProfile().baseRulesSha256},deepRules:{ready:true,profile:deepSemgrepProfile()}}:{})}]));
 bench.runner=async(tool,_profile,options)=>{calls.push(tool);return{ruleProfile:options.ruleProfile,executedRules:options.ruleProfile&&{sha256:options.ruleProfile.rulesSha256,count:options.ruleProfile.ruleCount},complete:true,coverageKey:'c'.repeat(64),coverageFiles:['app.py'],findings:[]}};
 bench.saveScope(eng,{requestId:'mode-scope-0001',revision:0,repoRoot:root,tools:['semgrep','trivy'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
 return{base,root,store,eng,bench,calls,async close(){await bench.dispose();await store.close();fs.rmSync(base,{recursive:true,force:true})}};
}
const start=(changes={})=>({mode:'deep',requestId:'mode-start-0001',profileRevision:1,steps:['semgrep'],budgetSeconds:30,...changes});

test('Ordinary plan reports missing R3 qualification without handing off files or starting tools',async()=>{
 const f=fixture();try{
  const result=f.bench.joint.plan(f.eng,{mode:'ordinary'});
  assert.equal(result.workspace.mode,'ordinary');assert.equal(result.workspace.minimumToolLevel,3);
  assert.deepEqual(result.availableSteps,[]);assert.equal(result.workspace.fullWorkspaceReady,false);
  assert.ok(result.workspace.unavailableSteps.some(row=>row.tool==='semgrep'&&row.reason==='r3-qualification-missing'));
  assert.equal(result.kaliAllowed,false);assert.equal(f.calls.length,0);
  assert.equal(fs.existsSync(path.join(f.store.dirOf(f.eng),'runs','joint')),false);
  assert.throws(()=>f.bench.joint.start(f.eng,start({mode:'ordinary',steps:['semgrep','trivy'],budgetSeconds:360,planIdentity:result.ordinaryPlan.planIdentity})),/R3/);
  assert.equal(f.bench.joint.status(f.eng,{requestId:'mode-start-0001'}).requestState,'rejected');
  assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) AS n FROM security_joint').get().n,0);
 }finally{await f.close()}
});

test('Deep S1 dispatch persists the original mode and identities and launches only selected steps',async()=>{
 const f=fixture();try{
  const plan=f.bench.joint.plan(f.eng,{mode:'deep'});
  assert.deepEqual(plan.availableSteps,['semgrep','trivy']);assert.equal(plan.workspace.minimumToolLevel,2);
  assert.deepEqual(plan.workspace.sandboxProfiles,['S1']);assert.equal(plan.workspace.modelRequests,0);
  const input=start(),run=f.bench.joint.start(f.eng,input);
  assert.equal(run.workspace.mode,'deep');assert.deepEqual(run.workspace.selectedSteps,['semgrep']);
  assert.deepEqual(run.workspace.toolIdentities,{semgrep:identities.semgrep});
  assert.equal(f.bench.joint.start(f.eng,input).id,run.id);
  const ordinary=f.bench.joint.plan(f.eng,{mode:'ordinary'});assert.equal(ordinary.workspace.mode,'ordinary');
  const result=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});
  assert.equal(result.task.state,'completed');assert.equal(result.task.workspace.mode,'deep');
  assert.deepEqual(f.calls,['semgrep']);
  const saved=JSON.parse(f.bench.db(f.eng).prepare('SELECT data FROM security_joint WHERE id=?').get(run.id).data);
  assert.deepEqual(saved.workspace,result.task.workspace);
  assert.throws(()=>f.bench.joint.start(f.eng,{...input,mode:'ordinary'}),/重复请求内容不同/);
 }finally{await f.close()}
});

test('Mode dispatch rejects unqualified adapters, invalid modes and over-budget work before creating a task',async()=>{
 const f=fixture();try{
  for(const [index,change] of [{steps:['kali']},{steps:['rea']},{steps:['pentagi']},{steps:['zap']},{budgetSeconds:901},{mode:'full-access'}].entries()){
   assert.throws(()=>f.bench.joint.start(f.eng,start({...change,requestId:'mode-reject-'+index})));
  }
  assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) AS n FROM security_joint').get().n,0);
  assert.equal(f.calls.length,0);assert.equal(fs.existsSync(path.join(f.store.dirOf(f.eng),'runs','joint')),false);
 }finally{await f.close()}
});

test('A pinned runtime identity change after acceptance prevents dispatch of the original step',async()=>{
 const f=fixture();try{
  const run=f.bench.joint.start(f.eng,start());
  f.bench.toolStatus=()=>({semgrep:{ready:true,rules:{sha256:deepSemgrepProfile().baseRulesSha256},deepRules:{ready:true,profile:deepSemgrepProfile()},version:'fixture',admissionIdentity:'c'.repeat(64)}});
  const result=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});
  assert.equal(result.task.state,'failed');assert.match(result.task.problem,/身份/);
  assert.deepEqual(f.calls,[]);assert.equal(result.task.steps[0].state,'not-run');
 }finally{await f.close()}
});

test('Child admission cannot swap the pinned identity after the parent pre-dispatch check',async()=>{
 const f=fixture();try{
  const read=f.bench.toolStatus;let reads=0;
  // submission, pre-snapshot, pre-step, then child admission
  f.bench.toolStatus=(...args)=>{const value=read(...args);if(++reads>=4)value.semgrep.admissionIdentity='c'.repeat(64);return value};
  const run=f.bench.joint.start(f.eng,start());
  const result=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});
  assert.equal(result.task.state,'failed');assert.match(result.task.problem,/身份/);
  assert.deepEqual(f.calls,[]);assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) AS n FROM security_run').get().n,0);
  assert.equal(result.task.steps[0].state,'not-run','Rejected child admission is not a running scanner');
 }finally{await f.close()}
});

test('Mode admission requires a current runtime identity instead of trusting a ready flag',async()=>{
 const f=fixture();try{
  f.bench.toolStatus=()=>({semgrep:{ready:true,rules:{sha256:deepSemgrepProfile().baseRulesSha256},deepRules:{ready:true,profile:deepSemgrepProfile()},version:'fixture'}});
  const plan=f.bench.joint.plan(f.eng,{mode:'deep'});assert.deepEqual(plan.availableSteps,[]);
  assert.throws(()=>f.bench.joint.start(f.eng,start()),/身份|就绪/);assert.equal(f.calls.length,0);
 }finally{await f.close()}
});

test('Mode contract survives reopening the existing database and old joint tasks retain a null mode',async()=>{
 const f=fixture();try{
  const deep=f.bench.joint.start(f.eng,start());await f.bench.joint.wait(f.eng,{id:deep.id,waitSeconds:2});
  const legacyInput=start({requestId:'legacy-start-001'});delete legacyInput.mode;
  const legacy=f.bench.joint.start(f.eng,legacyInput);await f.bench.joint.wait(f.eng,{id:legacy.id,waitSeconds:2});
  assert.equal(legacy.workspace,null);
  const reopened=new SecurityWorkbench(f.store,{workspaceRoot:f.base,toolStatus:f.bench.toolStatus});
  try{assert.equal(reopened.joint.status(f.eng,{id:deep.id}).task.workspace.mode,'deep');assert.equal(reopened.joint.status(f.eng,{id:legacy.id}).task.workspace,null)}finally{await reopened.dispose()}
 }finally{await f.close()}
});

test('Native service mode requests share one ledger and protect mode metadata against redaction',async()=>{
 const f=fixture(),socket=path.join(f.base,'rpc.sock'),server=createSecurityServer({dispatch:(request,options)=>executeSecurityOp(f.store,request,options)});
 try{
  await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o600);
  const rpc=(args,model=false)=>requestSecurityService({op:'securityJoint',engagement:f.eng,...args},{model,socketPath:socket});
  const first=await rpc({action:'start',...start()},true);assert.equal(first.ok,true);assert.equal(first.task.workspace.mode,'deep');
  const again=await rpc({action:'start',...start()});assert.equal(again.task.id,first.task.id);
  const report=await rpc({action:'wait',id:first.task.id,waitSeconds:2});assert.equal(report.task.state,'completed');assert.deepEqual(f.calls,['semgrep']);
  const changed=structuredClone(report);changed.task.workspace.mode='ordinary';assert.equal(JSON.parse(jointModelWire(report,changed)).ok,false);
  const plan=await rpc({action:'plan',mode:'deep'}),badPlan=structuredClone(plan);badPlan.workspace.mode='ordinary';assert.equal(JSON.parse(jointModelWire(plan,badPlan)).ok,false);
  const ordinary=await rpc({action:'plan',mode:'ordinary',budgetSeconds:30},true);
  assert.equal(ordinary.ok,true);
  const input={action:'start',...start({mode:'ordinary',requestId:'ordinary-rpc-001',steps:['semgrep','trivy'],planIdentity:ordinary.ordinaryPlan.planIdentity})};
  const rejected=await rpc(input,true);
  assert.equal(rejected.ok,false);assert.match(rejected.error,/R3/);
  const replay=await rpc(input);assert.equal(replay.ok,false);assert.match(replay.error,/R3/);
  assert.equal((await rpc({action:'status',requestId:input.requestId})).requestState,'rejected');
  assert.deepEqual(f.calls,['semgrep']);

 }finally{await server.shutdown();await f.close()}
});

test('Ordinary submission binds the current preview, exact steps and bounded budget before R3',async()=>{
 const f=fixture();try{
  const preview=()=>f.bench.joint.plan(f.eng,{mode:'ordinary',budgetSeconds:30}).ordinaryPlan;
  const plan=preview();
  assert.equal(plan.budgetSeconds,30);
  assert.equal(plan.executable,false);
  const input=start({mode:'ordinary',steps:['semgrep','trivy'],planIdentity:plan.planIdentity});
  const reject=(id,patch,error)=>assert.throws(()=>f.bench.joint.start(f.eng,{...input,requestId:id,...patch}),error);
  reject('missing-plan', {planIdentity:undefined}, /计划摘要/);
  reject('extra-step', {steps:['semgrep','trivy','kali']}, /计划步骤/);
  reject('reordered-step', {steps:['trivy','semgrep']}, /计划步骤/);
  reject('changed-budget', {budgetSeconds:31}, /计划已变化/);
  reject('excess-budget', {budgetSeconds:361}, /时限/);
  assert.throws(()=>f.bench.joint.plan(f.eng,{mode:'ordinary',budgetSeconds:29}),/时限/);
  reject('different-mode', {mode:'deep'}, /计划摘要/);
  fs.writeFileSync(path.join(f.root,'app.py'),'print(1)\n');
  reject('changed-input', {}, /计划已变化/);
  const current=preview();
  const status=f.bench.toolStatus;
  f.bench.toolStatus=(...args)=>{const tools=status(...args);tools.semgrep.admissionIdentity='c'.repeat(64);return tools};
  reject('changed-tool', {planIdentity:current.planIdentity}, /计划已变化/);
  reject('current-plan', {planIdentity:preview().planIdentity}, /R3/);
  assert.equal(f.bench.joint.status(f.eng,{requestId:'current-plan'}).requestState,'rejected');
  assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) AS n FROM security_joint').get().n,0);
  assert.equal(fs.existsSync(path.join(f.store.dirOf(f.eng),'runs','joint')),false);
  assert.deepEqual(f.calls,[]);
 }finally{await f.close()}
});

test('A late S1 scanner result does not persist findings after the monotonic deadline',async()=>{
 const f=fixture();try{
  f.bench.runner=async(_tool,_profile,options)=>{
   assert.ok(options.deadlineMonotonic>performance.now());
   f.bench.joint.active.deadlineMonotonic=performance.now()-1;
   return{complete:true,coverageKey:'c'.repeat(64),coverageFiles:['app.py'],findings:[{rule:'fixture',location:'app.py:1'}]};
  };
  const run=f.bench.joint.start(f.eng,start());
  const result=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});
  assert.equal(result.task.state,'timed-out');
  assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) AS n FROM security_joint_finding').get().n,0);
 }finally{await f.close()}
});

test('Managed Semgrep persists Python review evidence separately from findings',async()=>{
 const f=fixture();try{
  const evidence={tool:'semgrep',evidenceKind:'python-string-guard',path:'app.py',line:1,rule:'policy.harness.python.eval',status:'unverified',executionLine:1,guardLine:1,sink:'eval'};
  f.bench.pythonEvidence=(snapshot,findings)=>{assert.equal(snapshot.files[0].path,'app.py');assert.equal(findings[0].location,'app.py:1');return {state:'completed',artifacts:[evidence]}};
  f.bench.runner=async(_t,_p,options)=>({ruleProfile:options.ruleProfile,executedRules:options.ruleProfile&&{sha256:options.ruleProfile.rulesSha256,count:options.ruleProfile.ruleCount},complete:true,coverageKey:'c'.repeat(64),coverageFiles:['app.py'],findings:[{rule:'policy.harness.python.eval',location:'app.py:1'}]});
  const run=f.bench.joint.start(f.eng,start());
  await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});
  const report=f.bench.joint.report(f.eng,{id:run.id,section:'artifacts'});
  assert.equal(report.task.steps[0].pythonEvidence,'completed');
  assert.deepEqual(report.page.items.map(({sourceTask,snapshotId,...item})=>item),[evidence]);
  const changed=structuredClone(report);changed.page.items[0].guardLine=2;
  assert.equal(JSON.parse(jointModelWire(report,changed)).ok,false);
  assert.equal(f.bench.joint.report(f.eng,{id:run.id}).page.items[0].status,'unverified');
  f.bench.pythonEvidence=()=>{throw Error('synthetic failure')};
  const next=f.bench.joint.start(f.eng,start({requestId:'evidence-failure-1'}));
  const done=await f.bench.joint.wait(f.eng,{id:next.id,waitSeconds:2});
  assert.equal(done.task.steps[0].pythonEvidence,'unavailable');
  assert.equal(done.task.findings,1);
 }finally{await f.close()}
});

test('deep Semgrep selection binds the fixed profile to parent, child options and persisted runtime details',async()=>{const f=fixture();try{const m=await import('../package/lib/redteam/personal-semgrep-profile.mjs'),p=m.deepSemgrepProfile(),options=[];f.bench.runner=async(_tool,_root,o)=>{options.push(o);return{ruleProfile:o.ruleProfile,executedRules:o.ruleProfile&&{sha256:o.ruleProfile.rulesSha256,count:o.ruleProfile.ruleCount},complete:true,coverageKey:'c'.repeat(64),coverageFiles:['app.py'],findings:[]}};assert.deepEqual(f.bench.joint.plan(f.eng,{mode:'deep'}).workspace.ruleProfiles,{semgrep:p});const run=f.bench.joint.start(f.eng,start());assert.deepEqual(run.workspace.ruleProfiles,{semgrep:p});const done=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});assert.equal(done.task.state,'completed');assert.deepEqual(options[0].ruleProfile,p);assert.equal(options[0].workspaceMode,'deep');const child=f.bench.db(f.eng).prepare('SELECT details FROM security_run WHERE id=?').get(done.task.steps[0].id);const details=JSON.parse(child.details);assert.deepEqual(details.runtime.ruleProfile,p);assert.equal(details.runtime.rules.sha256,p.rulesSha256);assert.equal(details.runtime.rules.count,17);const legacy=f.bench.start(f.eng,{requestId:'legacy-profile-0001',profileRevision:1,tool:'semgrep'});await f.bench.active.promise;assert.ok(legacy.id);assert.equal(options[1].ruleProfile,undefined);assert.equal(options[1].workspaceMode,undefined)}finally{await f.close()}});
test('deep rule base mismatch is unavailable without silently dispatching the baseline',async()=>{const f=fixture();try{const read=f.bench.toolStatus;f.bench.toolStatus=()=>{const value=read();value.semgrep.rules={sha256:'f'.repeat(64)};return value};const plan=f.bench.joint.plan(f.eng,{mode:'deep'});assert.equal(plan.availableSteps.includes('semgrep'),false);assert.ok(plan.workspace.unavailableSteps.some(s=>s.tool==='semgrep'&&s.reason==='deep-rule-base-mismatch'));assert.throws(()=>f.bench.joint.start(f.eng,start()));assert.deepEqual(f.calls,[])}finally{await f.close()}});
test('a deep profile changed after acceptance is rejected before handing off the source',async()=>{const f=fixture();try{const run=f.bench.joint.start(f.eng,start());assert.ok(f.bench.joint.active.data.workspace.ruleProfiles?.semgrep);f.bench.joint.active.data.workspace.ruleProfiles.semgrep.mode='ordinary';const done=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});assert.equal(done.task.state,'failed');assert.equal(done.task.snapshot,null);assert.deepEqual(f.calls,[])}finally{await f.close()}});
for(const change of [s=>delete s.rules,s=>s.rules=null,s=>s.deepRules={ready:false},s=>delete s.deepRules])test('deep preflight does not snapshot a source with missing baseline or bundle identity: '+change.toString(),async()=>{const f=fixture();try{const status=f.bench.toolStatus;f.bench.toolStatus=()=>{const v=status();change(v.semgrep);return v};assert.equal(f.bench.joint.plan(f.eng,{mode:'deep'}).availableSteps.includes('semgrep'),false);assert.throws(()=>f.bench.joint.start(f.eng,start()));assert.equal(fs.existsSync(path.join(f.store.dirOf(f.eng),'runs','joint')),false)}finally{await f.close()}});
for(const receipt of [undefined,{mode:'ordinary'},{rulesSha256:'f'.repeat(64)}])test('unconfirmed executed rule receipt cannot persist a selected17 result: '+JSON.stringify(receipt),async()=>{const f=fixture();try{f.bench.runner=async()=>({complete:true,coverageKey:'forged',coverageFiles:['app.py'],findings:[{rule:'invented',location:'app.py:1'}],ruleProfile:receipt});const run=f.bench.joint.start(f.eng,start());const done=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});assert.equal(done.task.state,'partial');assert.equal(done.task.steps[0].state,'failed');assert.equal(done.task.findings,0);assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) n FROM security_joint_finding').get().n,0);const d=JSON.parse(f.bench.db(f.eng).prepare('SELECT details FROM security_run WHERE id=?').get(done.task.steps[0].id).details);assert.equal(d.runtime.ruleProfile,undefined)}finally{await f.close()}});
for(const change of [r=>r.executedRules.sha256=deepSemgrepProfile().baseRulesSha256,r=>r.executedRules.count=16,r=>delete r.executedRules,r=>r.coverageKey='legacy-key'])test('a valid planned profile cannot substitute for measured rule bytes and coverage identity: '+change.toString(),async()=>{const f=fixture();let returned=false;try{f.bench.runner=async(_t,_p,o)=>{const r={complete:true,coverageKey:'c'.repeat(64),coverageFiles:['app.py'],findings:[{rule:'invented',location:'app.py:1'}],ruleProfile:o.ruleProfile,executedRules:{sha256:o.ruleProfile.rulesSha256,count:17}};change(r);returned=true;return r};const run=f.bench.joint.start(f.eng,start());const done=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});assert.equal(done.task.state,'partial');assert.equal(done.task.steps[0].state,'failed');assert.equal(done.task.findings,0);assert.equal(returned,true)}finally{await f.close()}});
test('child admission rechecks deep bundle readiness after the parent check',async()=>{const f=fixture();try{let reads=0;const status=f.bench.toolStatus;f.bench.toolStatus=()=>{const r=status();if(++reads>=4)r.semgrep.deepRules.ready=false;return r};const run=f.bench.joint.start(f.eng,start());const done=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});assert.equal(done.task.state,'failed');assert.ok(done.task.snapshot,'Parent snapshot exists before child admission rejection');assert.deepEqual(f.calls,[]);assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) n FROM security_run').get().n,0)}finally{await f.close()}});
test('legacy scan rejects an unexpected extra-rule receipt instead of recording it',async()=>{const f=fixture();let returned=false;try{f.bench.runner=async()=>{returned=true;return{complete:true,coverageKey:'c'.repeat(64),coverageFiles:['app.py'],findings:[],ruleProfile:deepSemgrepProfile()}};const run=f.bench.start(f.eng,{requestId:'legacy-stray-profile',profileRevision:1,tool:'semgrep'});await f.bench.active.promise;const row=f.bench.db(f.eng).prepare('SELECT state FROM security_run WHERE id=?').get(run.id);assert.equal(row.state,'failed');assert.equal(returned,true)}finally{await f.close()}});
