import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import * as entry from './web-entry.mjs';

async function fixture(run) {
  const upstream=http.createServer((req,res)=>{
    const owner=req.headers.cookie==='owner=synthetic';
    res.writeHead(owner?200:401,{'content-type':'application/json'});
    res.end(JSON.stringify(owner?{ok:true,ready:true,originalCapabilities:{enabled:false,managed:true}}:{ok:false}));
  });
  await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve));
  const host=entry.createWebEntry({upstreamPort:upstream.address().port,capabilityRun:run});
  await new Promise(resolve=>host.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+host.address().port;
  const request=async(method='GET',body,headers={})=>{
    const response=await fetch(origin+'/__harness/capabilities',{method,headers:{cookie:'owner=synthetic',origin,'x-harness-local':'1','content-type':'application/json',...headers},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const text=await response.text();let value;try{value=JSON.parse(text);}catch{value={error:text};}return {status:response.status,body:value};
  };
  return {request,async close(){host.shutdown();upstream.closeAllConnections();await new Promise(resolve=>upstream.close(resolve));}};
}

test('capability switch exposes authenticated actual mode without running a command',async()=>{
 let calls=0;const f=await fixture(()=>{calls++;});
 try{
  const response=await f.request();assert.equal(response.status,200);assert.equal(response.body.enabled,false);assert.equal(calls,0);
  assert.equal((await f.request('GET',undefined,{cookie:''})).status,401);
 }finally{await f.close();}
});

test('cross-origin, missing origin, non-JSON and non-boolean writes never reach the controller',async()=>{
 let calls=0;const f=await fixture(()=>{calls++;});
 try{
  for(const [body,headers] of [[{enabled:true,expectedEnabled:false},{origin:'https://outside.invalid'}],[{enabled:true,expectedEnabled:false},{origin:''}],[{enabled:true,expectedEnabled:false},{'content-type':'text/plain'}],[{enabled:'yes',expectedEnabled:false},{}],[{enabled:true},{}]]){
   assert.ok((await f.request('POST',body,headers)).status>=400);
  }
  assert.equal(calls,0);
 }finally{await f.close();}
});

test('one explicit write starts one job; duplicate submissions are rejected and completion is checked',async()=>{
 let calls=0,complete;const f=await fixture(action=>{calls++;assert.equal(action,'enable');return new Promise(resolve=>{complete=resolve;});});
 try{
  const started=await f.request('POST',{enabled:true,expectedEnabled:false});
  assert.equal(started.status,202);assert.equal(started.body.operation.state,'running');assert.equal(calls,1);
  assert.equal((await f.request('POST',{enabled:true,expectedEnabled:false})).status,409);
  const pending=await f.request();assert.equal(pending.body.operation.state,'running');
  complete({stdout:JSON.stringify({enabled:true,configured:true,changed:true})});
  await new Promise(resolve=>setImmediate(resolve));
  const finished=await f.request();assert.equal(finished.body.operation.state,'succeeded');assert.equal(finished.body.operation.targetEnabled,true);
  assert.equal(calls,1);
 }finally{await f.close();}
});

test('failed or contradictory command receipts never claim success or expose raw stderr',async()=>{
 for(const run of [async()=>{throw Error('SECRET_CANARY');},async()=>({stdout:'{"enabled":false,"configured":true}'})]){
  const f=await fixture(run);
  try{
   assert.equal((await f.request('POST',{enabled:true,expectedEnabled:false})).status,202);
   await new Promise(resolve=>setImmediate(resolve));const response=await f.request();
   assert.equal(response.body.operation.state,'unconfirmed');assert.ok(!JSON.stringify(response).includes('SECRET_CANARY'));
  }finally{await f.close();}
 }
});
