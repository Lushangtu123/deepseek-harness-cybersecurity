import test from 'node:test';import assert from 'node:assert/strict';import http from 'node:http';import {once} from 'node:events';import {createWebEntry} from './web-entry.mjs';
test('Storage page and counter API stay local, read-only and do not turn page polling into probes',async()=>{
 let refreshes=0;
 const monitor={snapshot:()=>({state:'not-observed',readOnly:true,deletionAvailable:false}),refresh:async()=>{refreshes++;return{state:'current',readOnly:true,deletionAvailable:false}},stop(){}};
 const upstream=http.createServer((_req,res)=>res.end('upstream fallback'));upstream.listen(0,'127.0.0.1');await once(upstream,'listening');
 const server=createWebEntry({upstreamPort:upstream.address().port,storageMonitor:monitor});server.listen(0,'127.0.0.1');await once(server,'listening');const base='http://127.0.0.1:'+server.address().port;
 try{
  const page=await fetch(base+'/__harness/storage');assert.equal(page.status,200);assert.match(await page.text(),/存储容量/);assert.equal(refreshes,0);
  const headers={'x-harness-local':'1'};const sample=await fetch(base+'/__harness/storage/status',{headers});assert.equal(sample.status,200);assert.equal((await sample.json()).state,'not-observed');assert.equal(refreshes,0);assert.equal(sample.headers.get('cache-control'),'no-store');
  const fresh=await fetch(base+'/__harness/storage/status?refresh=1',{headers});assert.equal((await fresh.json()).state,'current');assert.equal(refreshes,1);
  assert.equal((await fetch(base+'/__harness/storage/status')).status,403);
  assert.equal((await fetch(base+'/__harness/storage/status',{headers:{...headers,'sec-fetch-site':'cross-site'}})).status,403);
  assert.equal((await fetch(base+'/__harness/storage/status?root=/tmp',{headers})).status,400);
  assert.equal((await fetch(base+'/__harness/storage/status',{method:'POST',headers})).status,405);
  const script=await fetch(base+'/__harness/storage.js');assert.equal(script.status,200);assert.match(script.headers.get('content-type'),/javascript/);
  assert.equal(refreshes,1);
 }finally{server.shutdown();await new Promise(resolve=>upstream.close(resolve))}
});
