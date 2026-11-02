import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import vm from 'node:vm';import {resolveEngagement} from '../package/lib/redteam/personal-session-resolution.mjs';
import {execFileSync} from 'node:child_process';
const snapshots=await import('../package/lib/redteam/personal-review-snapshot.mjs').catch(()=>({}));
import {RedteamStore} from '../package/lib/redteam/store-core.js';
import {SecurityWorkbench} from '../package/lib/redteam/personal-security-workbench.mjs';
const jointPreset=await import('../package/lib/personal-joint.js').catch(()=>({}));
const jointFilter=await import('../package/lib/personal-joint-filter.js').catch(()=>({}));
const jointWire=await import('../package/lib/redteam/personal-joint-review.mjs');
function fixture(options={}){
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-bench-'))),workspace=path.join(base,'workspace'),root=path.join(workspace,'repo');fs.mkdirSync(root,{recursive:true});fs.writeFileSync(path.join(root,'app.py'),'eval(input())\n');const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('Joint fixture').id;
 const bench=new SecurityWorkbench(store,{workspaceRoot:workspace,toolStatus:()=>({semgrep:{ready:true,version:'test'},trivy:{ready:true,version:'test'}}),...options});
 bench.saveScope(eng,{requestId:'joint-scope-0001',revision:0,repoRoot:root,tools:['semgrep','trivy'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
 return{base,root,store,eng,bench,async close(){await bench.dispose();await store.close();fs.rmSync(base,{recursive:true,force:true})}};
}
test('Joint review hands off a fixed redacted source copy and accounts for excluded files',()=>{
 assert.equal(typeof snapshots.createReviewSnapshot,'function','Managed snapshot capture is missing');
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-snapshot-'))),root=path.join(base,'repo'),target=path.join(base,'capture');fs.mkdirSync(root);
 try{
  fs.writeFileSync(path.join(root,'app.py'),'import os\nos.system(input())\n');fs.writeFileSync(path.join(root,'config.py'),"password='SYNTHETIC_JOINT_SECRET'\n");fs.writeFileSync(path.join(root,'.env'),'SYNTHETIC_ENV');fs.writeFileSync(path.join(root,'sample.bin'),Buffer.from([0,1,2]));fs.symlinkSync(path.join(root,'app.py'),path.join(root,'link.py'));
  const captured=snapshots.createReviewSnapshot({repoRoot:root,revision:4,expiresAt:'2099-01-01T00:00:00Z'},target);
  assert.equal(captured.version,1);assert.equal(captured.scopeRevision,4);assert.match(captured.id,/^[a-f0-9]{64}$/);assert.equal(captured.files.length,2);assert.equal(captured.excluded.total,3);assert.equal(captured.redactedFiles,1);assert.equal(captured.coverageComplete,false);
  assert.ok(!fs.readFileSync(path.join(target,'source/config.py'),'utf8').includes('SYNTHETIC_JOINT_SECRET'));
  fs.writeFileSync(path.join(root,'app.py'),'changed');assert.equal(fs.readFileSync(path.join(target,'source/app.py'),'utf8'),'import os\nos.system(input())\n');
  assert.equal(snapshots.verifyReviewSnapshot(captured),true);fs.chmodSync(path.join(target,'source/app.py'),0o600);fs.writeFileSync(path.join(target,'source/app.py'),'tampered');assert.throws(()=>snapshots.verifyReviewSnapshot(captured),/变化|匹配/);
 }finally{fs.rmSync(base,{recursive:true,force:true})}
});
test('Project-local git fsmonitor cannot execute code while collecting snapshot metadata',()=>{
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-git-hook-'))),root=path.join(base,'repo'),marker=path.join(base,'executed');fs.mkdirSync(root);fs.writeFileSync(path.join(root,'app.py'),'print(1)\n');const hook=path.join(base,'monitor.sh');fs.writeFileSync(hook,'#!/bin/sh\nprintf called > "'+marker+'"\n');fs.chmodSync(hook,0o700);
 const git=args=>execFileSync('/usr/bin/git',['-C',root,...args],{stdio:['ignore','pipe','pipe']});
 try{git(['init']);git(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','add','app.py']);git(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture']);git(['config','core.fsmonitor',hook]);snapshots.createReviewSnapshot({repoRoot:root,revision:1,expiresAt:'2099-01-01T00:00:00Z'},path.join(base,'snapshot'));assert.equal(fs.existsSync(marker),false,'Untrusted git hook executed')}finally{fs.rmSync(base,{recursive:true,force:true})}
});
test('Project-local Git clean filters cannot execute during snapshot metadata collection',()=>{
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-git-filter-'))),root=path.join(base,'repo'),marker=path.join(base,'executed');fs.mkdirSync(root);fs.writeFileSync(path.join(root,'app.py'),'print(1)\n');const hook=path.join(base,'filter.sh');fs.writeFileSync(hook,'#!/bin/sh\nprintf called > "'+marker+'"\ncat\n');fs.chmodSync(hook,0o700);const git=args=>execFileSync('/usr/bin/git',['-C',root,...args],{stdio:['ignore','pipe','pipe']});
 try{git(['init']);git(['add','app.py']);git(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture']);fs.writeFileSync(path.join(root,'.gitattributes'),'*.py filter=fixture\n');git(['config','filter.fixture.clean',hook]);fs.writeFileSync(path.join(root,'app.py'),'print(2)\n');snapshots.createReviewSnapshot({repoRoot:root,revision:1,expiresAt:'2099-01-01T00:00:00Z'},path.join(base,'snapshot'));assert.equal(fs.existsSync(marker),false,'Untrusted Git filter executed')}finally{fs.rmSync(base,{recursive:true,force:true})}
});
test('Unknown remote outcome blocks a different request and restart never replays the original child',async()=>{
 let starts=0;const f=fixture({jointOptions:{kali:async(mode)=>{if(mode==='run')starts++;throw Error('injected lost transport')}}});
 try{
  const p=f.bench.profile(f.bench.db(f.eng));f.bench.saveScope(f.eng,{requestId:'unknown-scope-001',revision:1,repoRoot:f.root,tools:p.tools,expiresAt:p.expiresAt,confirm:true,jointKali:true});const input={requestId:'unknown-start-001',profileRevision:2,steps:['kali']},run=f.bench.joint.start(f.eng,input);await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});assert.equal(f.bench.joint.status(f.eng,{id:run.id}).task.state,'unconfirmed');
  assert.throws(()=>f.bench.joint.start(f.eng,{...input,requestId:'unknown-start-002'}),/未确认|原任务/);assert.equal(starts,1);await f.bench.dispose();
  const restored=new SecurityWorkbench(f.store,{workspaceRoot:path.dirname(f.root),jointOptions:{kali:async()=>{throw Error('must not start')}}});try{assert.equal(restored.joint.status(f.eng,{id:run.id}).task.state,'unconfirmed');assert.equal(restored.joint.start(f.eng,input).id,run.id)}finally{await restored.dispose()}
 }finally{await f.close()}
});
test('Cancel before the scanner dispatch cannot launch a new scanner process',async()=>{
 let calls=0;const f=fixture({runner:async()=>{calls++;return{findings:[],complete:true,coverageKey:'coverage',coverageFiles:['app.py']}}});
 try{const run=f.bench.joint.start(f.eng,{requestId:'early-cancel-001',profileRevision:1,steps:['semgrep']});const result=await f.bench.joint.cancel(f.eng,{id:run.id});assert.equal(result.task.state,'cancelled');assert.equal(calls,0)}finally{await f.close()}
});
test('Native joint tool binds to the current project and forwards only to the managed service',async()=>{
 const f=fixture();try{f.store.sessionBindings.bind(['joint-root'],f.eng);const session={id:'joint-root',header:{}};f.store.sessionLookup=id=>id==='joint-root'?session:undefined;
  const source=fs.readFileSync(new URL('../package/lib/redteam/tools.js',import.meta.url),'utf8'),at=source.indexOf("name: 'redteam_joint_review'");assert.ok(at>0,'Joint tool is missing');const begin=source.lastIndexOf('  ctx.tools.register(',at),end=source.indexOf('\n  ctx.tools.register(',at);let tool;
  vm.runInNewContext(source.slice(begin,end),{ctx:{tools:{register:v=>tool=v}},store:f.store,resolveEngagement,handleSecurityOp:async(_store,request)=>({ok:true,request}),defineTool:x=>x,reviewedTool:x=>x,text:x=>x});
  const result=JSON.parse(await tool.execute({action:'plan'},{agent:{session}}));assert.equal(result.request.op,'securityJoint');assert.equal(result.request.engagement,f.eng);assert.equal(result.request.action,'plan');await assert.rejects(tool.execute({action:'start',engagement:'other'},{agent:{session}}));
 }finally{await f.close()}
});
test('Kali handoff is an explicit saved scope choice and parent cancellation awaits the original remote task',async()=>{
 let starts=0,cancels=0;const f=fixture({jointOptions:{kali:async(mode,id,{snapshot}={})=>{if(mode==='run'){starts++;return{id,snapshotId:snapshot.id,state:'running'}}if(mode==='cancel'){cancels++;return{id,snapshotId:f.bench.joint.active.data.snapshot.id,state:'cancelled',cleanupVerified:true,findings:[]}}return{id,snapshotId:f.bench.joint.active.data.snapshot.id,state:'running'}}}});
 try{
  const p=f.bench.profile(f.bench.db(f.eng));f.bench.saveScope(f.eng,{requestId:'joint-kali-scope-001',revision:1,repoRoot:f.root,tools:p.tools,expiresAt:p.expiresAt,confirm:true,jointKali:true});
  const run=f.bench.joint.start(f.eng,{requestId:'joint-kali-start-001',profileRevision:2,steps:['kali']});while(starts===0)await new Promise(r=>setTimeout(r,5));
  const result=await f.bench.joint.cancel(f.eng,{id:run.id});assert.equal(result.task.state,'cancelled');assert.equal(result.task.cleanupVerified,true);assert.equal(starts,1);assert.equal(cancels,1);assert.equal(f.bench.joint.start(f.eng,{requestId:'joint-kali-start-001',profileRevision:2,steps:['kali']}).id,run.id);
 }finally{await f.close()}
});
test('Joint preset has a separate managed dispatch guard and preserves the restricted preset',()=>{
 assert.equal(typeof jointPreset.jointDefinition,'function','Joint preset missing');const standard={plugins:[{id:'tools',config:{mode:'ptc'}},{id:'persona',config:{prefix:'VM'}}]},before=JSON.stringify(standard),p=jointPreset.jointDefinition(standard);assert.equal(p.id,'personal-joint');assert.equal(JSON.stringify(standard),before);assert.equal(p.plugins.at(-1).name,'dsh-purge/personal-joint-filter');
 assert.equal(typeof jointFilter.jointToolDenial,'function');const call=(name,args)=>({name,arguments:args,agent:{session:{id:'joint'}}});assert.equal(jointFilter.jointToolDenial(call('redteam_joint_review',{action:'plan'}),{bound:'a'}),undefined);assert.ok(jointFilter.jointToolDenial(call('redteam_joint_review',{action:'start',engagement:'b'}),{bound:'a'}));for(const name of ['bash','run_code','mcp__pentagi__task','mcp__rea__exec'])assert.ok(jointFilter.jointToolDenial(call(name,{}),{bound:'a'}));
});
test('Joint task pins scope, deduplicates start and records scanner evidence against the captured copy',async()=>{
 const calls=[],f=fixture({runner:async(tool,profile)=>{calls.push({tool,root:profile.repoRoot,text:fs.readFileSync(path.join(profile.repoRoot,'app.py'),'utf8')});return{findings:[{rule:'eval-test',title:'Synthetic eval hit',severity:'high',location:'app.py:1',evidence:'synthetic only'}],complete:true,coverageKey:'test-coverage',coverageFiles:['app.py']}}});
 try{
  assert.equal(typeof f.bench.joint?.start,'function','Joint lifecycle is missing');
  assert.ok(f.bench.joint.plan(f.eng).projectHints.rootFiles.includes('app.py'),'Tool selection needs observed project file hints');
  assert.throws(()=>f.bench.joint.start(f.eng,{requestId:'joint-invalid-001',profileRevision:999,steps:['semgrep']}));
  assert.throws(()=>f.bench.joint.start(f.eng,{requestId:'joint-invalid-002',profileRevision:1,steps:['kali']}),'Kali transfer needs separate saved consent');
  const input={requestId:'joint-start-0001',profileRevision:1,steps:['semgrep']},run=f.bench.joint.start(f.eng,input);assert.equal(f.bench.joint.start(f.eng,input).id,run.id);
  assert.equal(f.bench.joint.status(f.eng,{requestId:input.requestId}).task.id,run.id,'Lost startup reply must be recovered without replaying start');
  assert.throws(()=>f.bench.joint.start(f.eng,{...input,steps:['trivy']}));assert.throws(()=>f.bench.start(f.eng,{requestId:'other-scan-0001',profileRevision:1,tool:'semgrep'}));
  await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});const report=f.bench.joint.report(f.eng,{id:run.id,section:'findings'});
  assert.equal(report.task.state,'completed');assert.equal(report.page.items.length,1);assert.equal(report.page.items[0].status,'unverified');assert.equal(report.task.snapshot.files,1);assert.ok(report.task.snapshot.id);assert.equal(calls.length,1);assert.notEqual(calls[0].root,f.root);assert.equal(calls[0].text,'eval(input())\n');assert.equal(f.bench.read(f.eng).totalFindings,0,'Joint observations belong to their own evidence set');
 }finally{await f.close()}
});
test('Joint snapshots cannot rewrite or reopen an existing ordinary audit finding',async()=>{
 const f=fixture({runner:async()=>({findings:[{rule:'shared-rule',title:'hit',severity:'medium',location:'app.py:1',evidence:'ordinary evidence'}],complete:true,coverageKey:'coverage',coverageFiles:['app.py']})});
 try{
  const run=f.bench.start(f.eng,{requestId:'original-scan-001',profileRevision:1,tool:'semgrep'});await f.bench.wait(f.eng,{id:run.id,waitSeconds:2});const db=f.bench.db(f.eng);db.prepare("UPDATE security_finding SET status='fixed',note='Original record must stay fixed'").run();const before=db.prepare('SELECT * FROM security_finding ORDER BY id').all();
  const parent=f.bench.joint.start(f.eng,{requestId:'isolated-joint-001',profileRevision:1,steps:['semgrep']});await f.bench.joint.wait(f.eng,{id:parent.id,waitSeconds:2});assert.deepEqual(db.prepare('SELECT * FROM security_finding ORDER BY id').all(),before);assert.equal(f.bench.joint.report(f.eng,{id:parent.id}).page.items[0].status,'unverified');
 }finally{await f.close()}
});
test('Snapshot verification rejects additions as well as changed admitted files',()=>{
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-extra-'))),root=path.join(base,'repo');fs.mkdirSync(root);fs.writeFileSync(path.join(root,'app.py'),'print(1)');try{const snapshot=snapshots.createReviewSnapshot({repoRoot:root,revision:1,expiresAt:'2099-01-01T00:00:00Z'},path.join(base,'snapshot'));const extra=path.join(snapshot.sourceRoot,'extra.py');fs.writeFileSync(extra,'print(2)');assert.throws(()=>snapshots.verifyReviewSnapshot(snapshot),/变化|匹配|集合/);fs.unlinkSync(extra);fs.symlinkSync(path.join(root,'app.py'),extra);assert.throws(()=>snapshots.verifyReviewSnapshot(snapshot))}finally{fs.rmSync(base,{recursive:true,force:true})}
});
test('Rejected starts have a durable read-only rejection receipt without creating tasks',async()=>{
 const f=fixture();try{const input={requestId:'rejected-start-001',profileRevision:99,steps:['semgrep']};assert.throws(()=>f.bench.joint.start(f.eng,input));const result=f.bench.joint.status(f.eng,{requestId:input.requestId});assert.equal(result.task,null);assert.equal(result.requestState,'rejected');assert.match(result.rejection,/范围/)}finally{await f.close()}
});
test('Unified report retains parser diagnostics and explicitly reports bounded diagnostic coverage',async()=>{
 const diagnostics={total:25,items:Array.from({length:20},()=>({code:'PartialParsing',path:'app.py',line:1})),truncated:true},f=fixture({runner:async()=>({findings:[],complete:false,coverageKey:'coverage',coverageFiles:['app.py'],diagnostics})});
 try{const run=f.bench.joint.start(f.eng,{requestId:'diagnostic-joint-001',profileRevision:1,steps:['semgrep']});await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});const report=f.bench.joint.report(f.eng,{id:run.id,section:'diagnostics'});assert.equal(report.task.state,'partial');assert.equal(report.task.steps[0].diagnostics.total,25);assert.equal(report.task.steps[0].diagnostics.truncated,true);assert.equal(report.page.items[0].code,'PartialParsing')}finally{await f.close()}
});
test('Final joint wire rejects redaction-expanded results and altered task/hash/cursor identities',()=>{
 assert.equal(typeof jointWire.jointModelWire,'function','Post-redaction joint wire guard is missing');const original={ok:true,engagement:'fixture',task:{id:'task-identifier',state:'completed',snapshot:{id:'a'.repeat(64)}},page:{section:'findings',nextCursor:'cursor',complete:false,total:1,items:[{title:'X'.repeat(4000),status:'unverified',sourceTask:'child'}]}};
 const expanded=structuredClone(original);expanded.page.items[0].title='[REDACTED]'.repeat(4000);assert.equal(JSON.parse(jointWire.jointModelWire(original,expanded)).ok,false);
 for(const mutate of [v=>v.task.id='hidden',v=>v.task.snapshot.id='hidden',v=>v.page.nextCursor='hidden']){const safe=structuredClone(original);mutate(safe);assert.equal(JSON.parse(jointWire.jointModelWire(original,safe)).ok,false)}
});
test('Kali completeness describes the handed-off Python subset without claiming whole-project coverage',async()=>{
 const f=fixture({jointOptions:{kali:async(_mode,id,{snapshot})=>({id,snapshotId:snapshot.id,state:'completed',cleanupVerified:true,checkedFiles:1,version:'1.9.4',findings:[],diagnostics:[],diagnosticsTotal:0})}});
 try{const p=f.bench.profile(f.bench.db(f.eng));f.bench.saveScope(f.eng,{requestId:'complete-scope-001',revision:1,repoRoot:f.root,tools:p.tools,expiresAt:p.expiresAt,jointKali:true,confirm:true});const run=f.bench.joint.start(f.eng,{requestId:'complete-start-001',profileRevision:2,steps:['kali']});const result=await f.bench.joint.wait(f.eng,{id:run.id,waitSeconds:2});assert.equal(result.task.steps[0].complete,true);assert.equal(result.task.steps[0].coverageScope,'handed-off-python-files');assert.equal(result.task.coverageComplete,false)}finally{await f.close()}
});
