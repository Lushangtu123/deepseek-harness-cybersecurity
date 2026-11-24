import test from 'node:test';
import assert from 'node:assert/strict';
import {createRecoveryReader,createWebEntry} from './web-entry.mjs';
const catalog={readOnly:true,currentRecovery:'ready-probe',observedAt:'2026-10-29T00:00:00Z',snapshotState:'observed',snapshots:[],images:[],storage:{freeBytes:1},truncated:false};
test('Malformed required lists are rejected instead of becoming confirmed empty lists',async()=>{
 for(const change of [{snapshots:{}},{snapshots:null},{images:'bad'},{images:null},{archiveScan:{reasons:{}}}]){
  const read=createRecoveryReader({run:async()=>({stdout:JSON.stringify({...catalog,...change})})});
  await assert.rejects(()=>read(),error=>error.catalogCode==='invalid-catalog');
 }
});
test('Filtered records leave an explicit gap without exposing their names',async()=>{
 const read=createRecoveryReader({run:async()=>({stdout:JSON.stringify({...catalog,snapshots:[{name:'../private',present:true}],images:[{id:'folder/token.qcow2'}]})})});
 const value=await read();assert.equal(value.truncated,true);assert.deepEqual(value.archiveScan.reasons,['snapshot-invalid-record','image-invalid-record']);
 assert.ok(!JSON.stringify(value).includes('private'));assert.ok(!JSON.stringify(value).includes('token.qcow2'));
});
test('Selected-list reads use separate cache keys and allow the unrelated list to be absent',async()=>{
 const calls=[];const read=createRecoveryReader({run:async(a,s,part)=>{calls.push([a,s,part]);const value={...catalog};if(part==='images'){delete value.snapshots;delete value.snapshotState}else if(part==='snapshots')delete value.images;return{stdout:JSON.stringify(value)}}});
 const images=await read('','','images');const snapshots=await read('','','snapshots');await read('','','images');
 assert.deepEqual(calls,[['','','images'],['','','snapshots']]);assert.equal(images.part,'images');assert.ok(!('snapshots' in images));assert.equal(snapshots.part,'snapshots');assert.ok(!('images' in snapshots));
});
test('Catalog HTTP errors and diagnostics correlate safe classifications, never raw errors',async()=>{
 const failures=[Object.assign(Error('private secret stderr /home/private'),{code:7}),Object.assign(Error('private'),{killed:true,signal:'SIGTERM'}),{stdout:'{broken'}, {stdout:JSON.stringify({...catalog,images:null})},{stdout:JSON.stringify({...catalog,nextCursor:'../invalid'})}];
 const expected=['controller-failed','controller-terminated','invalid-json','invalid-catalog','invalid-catalog'];
 const read=createRecoveryReader({run:async()=>{const value=failures.shift();if(value instanceof Error)throw value;return value}});
 const server=createWebEntry({recoveryReader:read});await new Promise(done=>server.listen(0,'127.0.0.1',done));const base='http://127.0.0.1:'+server.address().port;
 try{
  for(const code of expected){const res=await fetch(base+'/__harness/recoveries',{headers:{'x-harness-local':'1'}});assert.equal(res.status,503);const data=await res.json();assert.equal(data.diagnostic.code,code);assert.match(data.diagnostic.requestId,/^[a-f0-9-]{36}$/);assert.equal(res.headers.get('x-harness-request-id'),data.diagnostic.requestId)}
  const value=await (await fetch(base+'/__harness/diagnostics')).json();assert.equal(value.recent.length,expected.length);assert.deepEqual(value.recent.map(item=>item.code),expected);assert.equal(value.recent[0].exitCode,7);assert.equal(value.recent[1].signal,'SIGTERM');
  assert.ok(value.recent.every(item=>item.category==='recovery'&&item.requestId&&item.responseMs>=0));assert.ok(!JSON.stringify(value).includes('private'));
 }finally{server.closeAllConnections();await new Promise(done=>server.close(done))}
});
test('HTTP selected-list parameters are fixed and incompatible cursors are rejected before execution',async()=>{
 const calls=[];const server=createWebEntry({recoveryReader:async(...args)=>{calls.push(args);return catalog}});await new Promise(done=>server.listen(0,'127.0.0.1',done));const base='http://127.0.0.1:'+server.address().port;
 try{
  for(const query of ['part=other','part=images&part=snapshots','part=images&snapshotAfter=snap-a','part=snapshots&after=archive-a']){const response=await fetch(base+'/__harness/recoveries?'+query,{headers:{'x-harness-local':'1'}});assert.equal(response.status,400);await response.text()}
  assert.equal(calls.length,0);const response=await fetch(base+'/__harness/recoveries?part=images&after=archive-a',{headers:{'x-harness-local':'1'}});assert.equal(response.status,200);await response.text();assert.deepEqual(calls,[['archive-a','','images']]);
 }finally{server.closeAllConnections();await new Promise(done=>server.close(done))}
});
