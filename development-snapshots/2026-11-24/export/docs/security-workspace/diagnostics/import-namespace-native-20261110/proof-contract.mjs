import assert from 'node:assert/strict';
import {resolve,sep} from 'node:path';
export class AttemptLedger {
 attempts=[];
 reserve(containerName){assert.equal(this.attempts.length,0,'Real runner invocation cap reached');const attempt={containerName,outcome:'pending',observed:null,observerErrors:[]};this.attempts.push(attempt);return attempt}
}
export function validateLive(v,e){
 assert.ok(v,'No running scanner observed');assert.notEqual(resolve(e.sourceRoot),resolve(e.project));assert.ok(resolve(e.sourceRoot).startsWith(resolve(e.stateRoot)+sep));
 assert.equal(v.running,true);assert.equal(v.imageId,e.image);assert.equal(v.ruleSha256,e.rules);assert.deepEqual(v.sourceMount,{source:e.sourceRoot,readonly:true});
 assert.equal(v.user,'1000:1000');assert.equal(v.network,'none');assert.equal(v.readonlyRoot,true);assert.equal(v.privileged,false);
 assert.ok(v.capDrop?.includes('ALL'));assert.ok(v.securityOpt?.includes('no-new-privileges'));assert.equal(v.memory,805306368);assert.equal(v.memorySwap,805306368);assert.equal(v.pids,160);assert.equal(v.nanoCpus,1000000000);return true;
}
export async function collectPages(read,id,snapshotId,maxPages=100){
 let cursor,total,task;const items=[],seen=new Set();
 for(let n=0;n<maxPages;n++){
  const r=await read(cursor);assert.equal(r?.ok,true);assert.equal(r.task?.id,id);assert.equal(r.task?.snapshot?.id,snapshotId);task=r.task;
  const p=r.page;assert.ok(p&&Array.isArray(p.items)&&p.items.length<=5);assert.ok(Number.isSafeInteger(p.total)&&p.total>=0);assert.equal(typeof p.complete,'boolean');
  if(total===undefined)total=p.total;assert.equal(p.total,total);items.push(...p.items);assert.ok(items.length<=total);
  if(p.complete){assert.equal(p.nextCursor,null);assert.equal(items.length,total);return{items,task}}
  assert.ok(p.items.length>0);assert.ok(typeof p.nextCursor==='string'&&p.nextCursor.length>0&&p.nextCursor.length<=512);assert.ok(!seen.has(p.nextCursor));seen.add(p.nextCursor);cursor=p.nextCursor;
 }
 throw Error('Report collection exceeded page cap; incomplete evidence');
}
