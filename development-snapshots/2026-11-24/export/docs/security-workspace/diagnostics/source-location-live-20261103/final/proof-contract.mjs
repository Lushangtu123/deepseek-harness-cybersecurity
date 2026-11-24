import assert from 'node:assert/strict';
import {resolve,sep} from 'node:path';
export class AttemptLedger {
 attempts=[];requests=[];
 reserve(containerName){this.requests.push({containerName,accepted:this.attempts.length===0});assert.equal(this.attempts.length,0,'Real runner invocation cap reached');const attempt={containerName,outcome:'pending',observed:null,observerErrors:[]};this.attempts.push(attempt);return attempt}
}
export function validateLive(v,e){
 assert.ok(v,'No running scanner observed');assert.notEqual(resolve(e.sourceRoot),resolve(e.project));assert.ok(resolve(e.sourceRoot).startsWith(resolve(e.stateRoot)+sep));
 assert.equal(v.running,true);assert.equal(v.imageId,e.image);assert.equal(v.ruleSha256,e.rules);assert.deepEqual(v.sourceMount,{source:e.sourceRoot,readonly:true});
 assert.equal(v.containerName,'/'+e.containerName);assert.match(v.containerId,/^[a-f0-9]{64}$/);assert.ok(!v.capAdd?.length);assert.ok(!v.devices?.length);assert.ok(!v.deviceRequests?.length);assert.equal(v.pidMode,'');assert.equal(v.ipcMode,'private');assert.equal(v.utsMode,'');assert.deepEqual(v.entrypoint,['/bin/sh']);
 const binds=v.mounts.filter(m=>m.type==='bind').sort((a,b)=>a.destination.localeCompare(b.destination));
 const wanted=[{type:'bind',source:e.sourceRoot,destination:'/src',rw:false},{type:'bind',source:e.outputScript,destination:'/policy-output.sh',rw:false},{type:'bind',source:e.ruleFile,destination:'/policy/rules.json',rw:false}].sort((a,b)=>a.destination.localeCompare(b.destination));assert.deepEqual(binds,wanted);assert.ok(v.mounts.every(m=>m.type==='bind'||m.type==='tmpfs'&&['/tmp','/out'].includes(m.destination)));
 assert.deepEqual(v.tmpfs,{'/tmp':'rw,nosuid,nodev,noexec,size=268435456,mode=1777','/out':'rw,nosuid,nodev,noexec,size=67108864,uid=1000,gid=1000,mode=0700'});
 assert.ok(/^\d+$/.test(v.command?.[3])&&+v.command[3]>=1&&+v.command[3]<=230);assert.deepEqual(v.command,['/policy-output.sh','/out','--deadline-seconds',v.command[3],'semgrep','scan','--config','/policy/rules.json','--json','--output','/out/result.json','--metrics=off','--disable-version-check','--jobs','1','--timeout','5','--max-target-bytes','1000000','/src']);
 assert.equal(v.user,'1000:1000');assert.equal(v.network,'none');assert.equal(v.readonlyRoot,true);assert.equal(v.privileged,false);
 assert.ok(v.capDrop?.includes('ALL'));assert.ok(v.securityOpt?.includes('no-new-privileges'));assert.equal(v.memory,805306368);assert.equal(v.memorySwap,805306368);assert.equal(v.pids,160);assert.equal(v.nanoCpus,1000000000);return true;
}
export async function collectPages(read,id,snapshotId,maxPages=100,section='findings'){
 let cursor,total,task;const items=[],seen=new Set();
 for(let n=0;n<maxPages;n++){
  const r=await read(cursor);assert.equal(r?.ok,true);assert.equal(r.task?.id,id);assert.equal(r.task?.snapshot?.id,snapshotId);task=r.task;
  const p=r.page;assert.equal(p?.section,section);assert.ok(p&&Array.isArray(p.items)&&p.items.length<=5);assert.ok(Number.isSafeInteger(p.total)&&p.total>=0);assert.equal(typeof p.complete,'boolean');
  if(total===undefined)total=p.total;assert.equal(p.total,total);items.push(...p.items);assert.ok(items.length<=total);
  if(p.complete){assert.equal(p.nextCursor,null);assert.equal(items.length,total);return{items,task}}
  assert.ok(p.items.length>0);assert.ok(typeof p.nextCursor==='string'&&p.nextCursor.length>0&&p.nextCursor.length<=512);assert.ok(!seen.has(p.nextCursor));seen.add(p.nextCursor);cursor=p.nextCursor;
 }
 throw Error('Report collection exceeded page cap; incomplete evidence');
}

export function validateAcceptance({jointId,requests,proofs,report}){
 assert.ok(jointId);assert.equal(requests.length,1);assert.equal(requests[0].accepted,true);assert.equal(proofs.length,1);const p=proofs[0],t=report.task;assert.equal(p.outcome,'passed');assert.equal(t?.id,jointId);assert.equal(t.state,'completed');assert.equal(t.cleanupVerified,true);assert.equal(t.modelCalls,0);assert.equal(t.snapshot?.files,5);assert.equal(t.snapshot.id,p.snapshotId);assert.equal(t.workspace?.toolIdentities?.semgrep,p.admissionIdentity);
 assert.equal(t.steps.length,1);const step=t.steps[0];assert.equal(step.tool,'semgrep');assert.equal(step.state,'completed');assert.equal(p.containerName,'dsh-sec-'+step.id);assert.equal(step.sourceLocations?.total,7);assert.equal(step.sourceLocations.bound,7);assert.equal(step.sourceLocations.unavailable,0);assert.equal(report.findings.length,7);assert.equal(report.files.length,5);assert.ok(report.findings.every(r=>r.tool==='semgrep'&&r.status==='unverified'&&r.sourceTask===step.id&&r.snapshotId===t.snapshot.id&&r.sourceLocation?.state==='bound'));return true;
}
