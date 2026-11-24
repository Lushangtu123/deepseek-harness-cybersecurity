import test from 'node:test';
import assert from 'node:assert/strict';
import * as entry from './web-entry.mjs';
import * as health from './web-health.mjs';
const catalog={readOnly:true,currentRecovery:'ready-workbench-v12-20261027',observedAt:'2026-10-27T00:00:00Z',snapshotState:'observed',snapshots:[{name:'ready-workbench-v12-20261027',present:true,current:true,protected:true,reviewCandidate:false,bundleState:'verified',createdAt:'2026-10-27T00:00:00Z'}],images:[{id:'restore-probe-v10/offline-image/Data/ubuntu.qcow2',logicalBytes:20,allocatedBytes:16,reviewCandidate:true}],storage:{freeBytes:200,totalBytes:400,primaryLogicalBytes:100,primaryAllocatedBytes:80},truncated:false};
test('Recovery reader coalesces fixed metadata reads and strips private or malformed fields',async()=>{
 assert.equal(typeof entry.createRecoveryReader,'function','Missing recovery metadata reader');
 let calls=0,resolve;
 const read=entry.createRecoveryReader({run:()=>{calls++;return new Promise(done=>{resolve=done})}});
 const a=read(),b=read();await Promise.resolve();assert.equal(calls,1);
 resolve({stdout:JSON.stringify({...catalog,privateKey:'private-secret',images:[...catalog.images,{id:'../private.qcow2'},{id:'folder/token.qcow2'}]})});
 const value=await a;assert.deepEqual(await b,value);assert.equal(value.images.length,1);assert.ok(!JSON.stringify(value).includes('private-secret'));
 assert.equal((await read()).readOnly,true);assert.equal(calls,1);
});
test('Recovery metadata is read-only, fixed-target, same-origin and requires the local header',async()=>{
 assert.equal(typeof entry.createRecoveryReader,'function');
 let calls=0;const server=entry.createWebEntry({recoveryReader:async()=>{calls++;return catalog}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const base='http://127.0.0.1:'+server.address().port;
 try{
  for(const [method,headers,status] of [['GET',{},403],['POST',{'x-harness-local':'1'},405],['GET',{'x-harness-local':'1','sec-fetch-site':'cross-site'},403],['GET',{'x-harness-local':'1',origin:'https://outside.invalid'},403]]){
   const response=await fetch(base+'/__harness/recoveries',{method,headers});assert.equal(response.status,status);await response.text();
  }
  assert.equal(calls,0);
  const response=await fetch(base+'/__harness/recoveries',{headers:{'x-harness-local':'1'}});assert.equal(response.status,200);assert.deepEqual(await response.json(),catalog);assert.equal(calls,1);
  const page=await fetch(base+'/__harness/recovery');assert.equal(page.status,200);assert.match(await page.text(),/恢复点与验收副本/);
 }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
});
test('Recovery page explains shared allocation, review-only candidates and protection',()=>{
 assert.equal(typeof health.RECOVERY_HTML,'string','Missing recovery page');
 for(const text of ['只读','共享','人工','最近三个','恢复点与验收副本'])assert.ok(health.RECOVERY_HTML.includes(text),text);
 assert.ok(!health.RECOVERY_HTML.includes('innerHTML'));
});

test('Catalog pagination has per-cursor caching and bounded safe cursor forwarding',async()=>{
 const calls=[];const read=entry.createRecoveryReader({run:async cursor=>{calls.push(cursor);return{stdout:JSON.stringify({...catalog,nextCursor:cursor?'probe-c':'probe-b',archiveScan:{entriesScanned:16,entriesRemaining:20,visitedDirectories:50,skippedMetadataDirectories:16,reasons:[]}})}}});
 const first=await read();const second=await read('probe-b');await read('probe-b');
 assert.equal(first.nextCursor,'probe-b');assert.equal(second.nextCursor,'probe-c');assert.deepEqual(calls,['','probe-b']);assert.equal(second.archiveScan.entriesRemaining,20);
 for(const cursor of ['../outside','a/b','secret-name','x'.repeat(241)])await assert.rejects(async()=>read(cursor));
});
test('Recovery HTTP cursor is passed only after the existing local request checks',async()=>{
 const calls=[];const server=entry.createWebEntry({recoveryReader:async cursor=>{calls.push(cursor);return catalog}});await new Promise(done=>server.listen(0,'127.0.0.1',done));const base='http://127.0.0.1:'+server.address().port;
 try{
  for(const suffix of ['?after=../private','?after=a&after=b','?other=x']){const r=await fetch(base+'/__harness/recoveries'+suffix,{headers:{'x-harness-local':'1'}});assert.equal(r.status,400);await r.text()}
  const denied=await fetch(base+'/__harness/recoveries?after=probe-b');assert.equal(denied.status,403);await denied.text();assert.equal(calls.length,0);
  const result=await fetch(base+'/__harness/recoveries?after=probe-b',{headers:{'x-harness-local':'1'}});assert.equal(result.status,200);await result.text();assert.deepEqual(calls,['probe-b']);
 }finally{server.closeAllConnections();await new Promise(done=>server.close(done))}
});

test('Snapshot continuation has an independent cache key and advancing cursor validation',async()=>{
 const calls=[];const read=entry.createRecoveryReader({run:async(after,snapshotAfter)=>{calls.push([after,snapshotAfter]);return{stdout:JSON.stringify({...catalog,nextSnapshotCursor:snapshotAfter?'snap-c':'snap-b'})}}});
 assert.equal((await read()).nextSnapshotCursor,'snap-b');
 assert.equal((await read('','snap-b')).nextSnapshotCursor,'snap-c');await read('','snap-b');await read('archive-a','snap-b');
 assert.deepEqual(calls,[['',''],['','snap-b'],['archive-a','snap-b']]);
 for(const cursor of ['../outside','a/b','token-name','x'.repeat(241)])await assert.rejects(()=>read('',cursor));
 const invalid=entry.createRecoveryReader({run:async()=>({stdout:JSON.stringify({...catalog,nextSnapshotCursor:'snap-a'})})});await assert.rejects(()=>invalid('','snap-b'));
});

test('Snapshot HTTP continuation preserves the fixed-origin and local-header boundary',async()=>{
 const calls=[];const server=entry.createWebEntry({recoveryReader:async(...cursors)=>{calls.push(cursors);return catalog}});await new Promise(done=>server.listen(0,'127.0.0.1',done));const base='http://127.0.0.1:'+server.address().port;
 try{
  const denied=await fetch(base+'/__harness/recoveries?snapshotAfter=snap-a');assert.equal(denied.status,403);await denied.text();
  for(const query of ['snapshotAfter=../outside','snapshotAfter=a&snapshotAfter=b']){const r=await fetch(base+'/__harness/recoveries?'+query,{headers:{'x-harness-local':'1'}});assert.equal(r.status,400);await r.text()}
  const r=await fetch(base+'/__harness/recoveries?snapshotAfter=snap-a',{headers:{'x-harness-local':'1'}});assert.equal(r.status,200);await r.text();assert.deepEqual(calls,[['','snap-a']]);
 }finally{server.closeAllConnections();await new Promise(done=>server.close(done))}
});

test('Internal archive continuation passes as one bounded argument and keeps snapshot cursors separate',async()=>{
 const cursor='v1:'+Buffer.from(JSON.stringify(['large',[['large','image-079.qcow2']]])).toString('base64url');const calls=[];
 const read=entry.createRecoveryReader({run:async after=>{calls.push(after);return{stdout:JSON.stringify({...catalog,nextCursor:after?null:cursor})}}});
 assert.equal((await read()).nextCursor,cursor);assert.equal((await read(cursor)).nextCursor,null);assert.deepEqual(calls,['',cursor]);
 await assert.rejects(()=>read('',cursor));
 for(const invalid of ['v1:../outside','v1:'+'a'.repeat(4096)])await assert.rejects(()=>read(invalid));
});
