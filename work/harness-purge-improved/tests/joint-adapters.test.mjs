import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {RedteamStore} from '../package/lib/redteam/store-core.js';import {SecurityWorkbench} from '../package/lib/redteam/personal-security-workbench.mjs';
test('Managed REA and PentAGI need saved consent, deduplicate, and keep analysis separate from findings',async()=>{
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-adapters-'))),root=path.join(base,'workspace/repo');fs.mkdirSync(root,{recursive:true});fs.writeFileSync(path.join(root,'app.js'),'export const value=1;');const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('Adapters fixture').id;let calls=0;
 const b=new SecurityWorkbench(store,{workspaceRoot:path.dirname(root),toolStatus:()=>({semgrep:{ready:true},trivy:{ready:true}}),jointOptions:{adapter:async(tool,mode,id,{snapshot}={})=>{calls++;assert.equal(mode,'run');return{id,snapshotId:snapshot.id,state:'completed',cleanupVerified:true,checkedFiles:tool==='rea'?1:0,modelCalls:tool==='pentagi'?2:0,artifacts:[{tool,sha256:'a'.repeat(64),claim:'unverified analysis'}]}}}});
 try{
  const scope={repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true};b.saveScope(eng,{...scope,requestId:'adapter-scope-001',revision:0});
  assert.throws(()=>b.joint.start(eng,{requestId:'adapter-no-consent',profileRevision:1,steps:['rea']}));
  b.saveScope(eng,{...scope,requestId:'adapter-scope-002',revision:1,jointRea:true,jointPentagi:true});
  const req={requestId:'adapter-start-001',profileRevision:2,steps:['rea','pentagi']},r=b.joint.start(eng,req);await b.joint.wait(eng,{id:r.id,waitSeconds:2});const v=b.joint.status(eng,{id:r.id}).task;
  assert.equal(v.state,'completed');assert.equal(v.findings,0);assert.equal(v.modelCalls,2);assert.equal(b.joint.start(eng,req).id,r.id);assert.equal(calls,2);const page=b.joint.report(eng,{id:r.id,section:'artifacts'}).page;assert.equal(page.total,2);assert.equal(page.items[0].snapshotId,v.snapshot.id);
 }finally{await b.dispose();await store.close();fs.rmSync(base,{recursive:true,force:true})}
});
test('Uncertain REA stop blocks new joint requests until original child is reconciled',async()=>{
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-rea-unknown-'))),root=path.join(base,'workspace/repo');fs.mkdirSync(root,{recursive:true});fs.writeFileSync(path.join(root,'app.js'),'export const x=1;');const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('Unknown child').id;let snapshotId,starts=0;
 const b=new SecurityWorkbench(store,{workspaceRoot:path.dirname(root),toolStatus:()=>({semgrep:{ready:true}}),jointOptions:{adapter:async(_tool,mode,id,{snapshot}={})=>{if(mode==='run'){starts++;snapshotId=snapshot.id;throw Error('lost acknowledgement')}if(mode==='cancel')throw Error('stop unconfirmed');return{id,snapshotId,state:'running',artifacts:[]}}}});
 try{b.saveScope(eng,{requestId:'unknown-rea-scope',revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),jointRea:true,confirm:true});const q={requestId:'unknown-rea-start',profileRevision:1,steps:['rea']};const v=b.joint.start(eng,q);await b.joint.wait(eng,{id:v.id,waitSeconds:2});assert.equal(b.joint.status(eng,{id:v.id}).task.state,'unconfirmed');assert.throws(()=>b.joint.start(eng,{...q,requestId:'unknown-rea-other'}));assert.equal(starts,1)}finally{await b.dispose();await store.close();fs.rmSync(base,{recursive:true,force:true})}
});
test('Model-side project redaction cannot silently change adapter authorization',async()=>{
 const {jointModelWire}=await import('../package/lib/redteam/personal-joint-review.mjs');const original={engagement:'fixture',reaAllowed:true,pentagiAllowed:false},changed={...original,pentagiAllowed:true};assert.equal(JSON.parse(jointModelWire(original,changed)).ok,false);
});
