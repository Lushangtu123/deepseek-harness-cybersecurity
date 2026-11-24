import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import net from 'node:net';
import {spawn,spawnSync} from 'node:child_process';import {once} from 'node:events';
const moduleUrl=new URL('../package/lib/redteam/personal-security-service.mjs',import.meta.url);
async function load(){assert.ok(fs.existsSync(moduleUrl),'independent security service transport is missing');return import(moduleUrl)}
test('A dispatch failure has one correlated source-free diagnostic in the result and owner observation',async()=>{
 const {createSecurityServer,requestSecurityService}=await load(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'sec-trace-')),socket=path.join(dir,'rpc.sock'),events=[];
 const server=createSecurityServer({dispatch:async()=>{throw Error('password=PRIVATE /private/source.js:99')},observe:value=>events.push(value)});
 try{await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o600);const result=await requestSecurityService({op:'securityStatus'},{socketPath:socket});assert.equal(result.ok,false);assert.ok(result.diagnostic,'Missing correlated service diagnostic');assert.equal(result.diagnostic.stage,'dispatch');assert.equal(result.diagnostic.code,'RPC_DISPATCH_FAILED');assert.equal(result.diagnostic.operation,'securityStatus');assert.match(result.diagnostic.requestId,/^[a-f0-9-]{36}$/);assert.ok(Number.isSafeInteger(result.diagnostic.elapsedMs));assert.equal(events.at(-1).requestId,result.diagnostic.requestId);assert.match(result.error,new RegExp(result.diagnostic.requestId));assert.ok(!JSON.stringify([result,events]).includes('PRIVATE'));assert.ok(!JSON.stringify(events).includes('/private'))}finally{await server.shutdown();fs.rmSync(dir,{recursive:true,force:true})}
});
test('A timed out caller reference matches eventual owner completion and never replays the operation',async()=>{
 const {createSecurityServer,requestSecurityService}=await load(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'sec-time-trace-')),socket=path.join(dir,'rpc.sock'),events=[];let count=0,timeout;
 const server=createSecurityServer({dispatch:async()=>{count++;await new Promise(resolve=>setTimeout(resolve,70));return{ok:true}},observe:value=>events.push(value)});
 try{await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o600);await assert.rejects(requestSecurityService({op:'securityStart'},{socketPath:socket,timeoutMs:15}),error=>{timeout=error;return !!error.diagnostic});assert.equal(timeout.diagnostic.stage,'wait');assert.equal(timeout.diagnostic.code,'RPC_TIMEOUT');await new Promise(resolve=>setTimeout(resolve,90));assert.equal(count,1);assert.equal(events.at(-1).requestId,timeout.diagnostic.requestId);assert.equal(events.at(-1).code,'RPC_OK')}finally{await server.shutdown();fs.rmSync(dir,{recursive:true,force:true})}
});
test('Socket and encoding failures stay classified without retaining paths, payloads or raw errors',async()=>{
 const {createSecurityServer,requestSecurityService}=await load(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'sec-code-trace-')),socket=path.join(dir,'rpc.sock'),events=[];
 await assert.rejects(requestSecurityService({op:'securityStart'},{socketPath:path.join(dir,'PRIVATE-missing')}),error=>{assert.equal(error.diagnostic?.stage,'socket');assert.ok(!JSON.stringify(error.diagnostic).includes('PRIVATE'));assert.ok(!error.message.includes('PRIVATE'));return true});
 const server=createSecurityServer({dispatch:async()=>({ok:true,privateValue:1n}),observe:value=>events.push(value)});
 try{await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o600);const result=await requestSecurityService({op:'securityStatus'},{socketPath:socket});assert.equal(result.ok,false);assert.equal(result.diagnostic.stage,'encode');assert.equal(result.diagnostic.code,'RPC_RESPONSE_ENCODING');assert.equal(events.at(-1).requestId,result.diagnostic.requestId)}finally{await server.shutdown();fs.rmSync(dir,{recursive:true,force:true})}
});
test('One missing or corrupt project cannot disable the independent owner for healthy projects',async()=>{
 const {reconcileSecurityProjects}=await load();assert.equal(typeof reconcileSecurityProjects,'function','startup reconciliation must isolate project failures');
 const {RedteamStore}=await import('../package/lib/redteam/store-core.js'),{SecurityWorkbench}=await import('../package/lib/redteam/personal-security-workbench.mjs');const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sec-reconcile-'))),store=new RedteamStore(path.join(dir,'facts')),bench=new SecurityWorkbench(store,{toolStatus:()=>({})});
 try{store.openEngagement('healthy');fs.mkdirSync(path.join(store.engagementsDir,'missing'));fs.mkdirSync(path.join(store.engagementsDir,'corrupt'));fs.writeFileSync(path.join(store.engagementsDir,'corrupt/assets.db'),'not sqlite');const result=reconcileSecurityProjects(store,bench);assert.equal(result.failedProjects,2);assert.equal(result.checkedProjects,3);assert.equal(bench.read('healthy').ok,true);assert.ok(!JSON.stringify(result).includes('corrupt'))}finally{await bench.dispose();await store.close();fs.rmSync(dir,{recursive:true,force:true})}
});
test('Closing a caller never closes the owner or replays a submitted mutation',async()=>{
 const {createSecurityServer,requestSecurityService}=await load();const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sec-service-')),socket=path.join(dir,'rpc.sock');let calls=0,running=false;
 const server=createSecurityServer({dispatch:async(request,{model})=>{assert.equal(model,true);if(request.op==='securityStart'){calls++;running=true;return{ok:true,run:{id:'owned-run',state:'running'}}}return{ok:true,running}}});
 try{await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o600);const first=await requestSecurityService({op:'securityStart'}, {model:true,socketPath:socket});assert.equal(first.run.state,'running');const next=await requestSecurityService({op:'securityStatus'},{model:true,socketPath:socket});assert.equal(next.running,true);assert.equal(calls,1)}finally{await server.shutdown();fs.rmSync(dir,{recursive:true,force:true})}
});
test('Private socket is required; no service or broad socket never falls back to a local start',async()=>{
 const {requestSecurityService,createSecurityServer}=await load();const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sec-deny-')),socket=path.join(dir,'rpc.sock');let calls=0;const server=createSecurityServer({dispatch:async()=>{calls++;return{ok:true}}});
 try{await assert.rejects(requestSecurityService({op:'securityStart'},{socketPath:socket}),/后台|service|socket/i);await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o666);await assert.rejects(requestSecurityService({op:'securityStart'},{socketPath:socket}),/后台|service|socket/i);assert.equal(calls,0)}finally{await server.shutdown();fs.rmSync(dir,{recursive:true,force:true})}
});
test('A lost response times out without cancelling or automatically replaying the accepted operation',async()=>{
 const {requestSecurityService,createSecurityServer}=await load();const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sec-lost-')),socket=path.join(dir,'rpc.sock');let starts=0;
 const server=createSecurityServer({dispatch:async(request)=>{if(request.op==='securityStart'){starts++;await new Promise(resolve=>setTimeout(resolve,80));return{ok:true,run:{id:'retained-run',state:'running'}}}return{ok:true,starts}}});
 try{await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o600);await assert.rejects(requestSecurityService({op:'securityStart'},{socketPath:socket,timeoutMs:20}),/未确认/);await new Promise(resolve=>setTimeout(resolve,90));const state=await requestSecurityService({op:'securityStatus'},{socketPath:socket});assert.equal(state.starts,1)}finally{await server.shutdown();fs.rmSync(dir,{recursive:true,force:true})}
});
test('Malformed or oversized envelopes never dispatch; client errors do not leak server output',async()=>{
 const {createSecurityServer,requestSecurityService}=await load();const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sec-envelope-')),socket=path.join(dir,'rpc.sock');let calls=0;const server=createSecurityServer({dispatch:async()=>{calls++;throw Error('PRIVATE INTERNAL')}});
 try{await new Promise(resolve=>server.listen(socket,resolve));fs.chmodSync(socket,0o600);
  for(const raw of ['{"request":{},"model":"yes"}\n','{"request":{},"model":false,"extra":true}\n',JSON.stringify({id:'-'.repeat(36),model:false,request:{op:'securityStatus'}})+'\n','x'.repeat(70000)+'\n'])await new Promise((resolve,reject)=>{const c=net.connect(socket,()=>c.write(raw));c.on('data',()=>{});c.on('error',reject);c.on('close',resolve)});
  assert.equal(calls,0);const value=await requestSecurityService({op:'securityStatus'},{socketPath:socket});assert.equal(value.ok,false);assert.ok(!JSON.stringify(value).includes('PRIVATE'));assert.equal(calls,1)
 }finally{await server.shutdown();fs.rmSync(dir,{recursive:true,force:true})}
});

test('The independent owner preserves runs across caller exit and its own abrupt restart',async()=>{
 const {requestSecurityService}=await load(),dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sec-life-'))),socket=path.join(dir,'rpc.sock');const ownerFile=path.join(dir,'owner.mjs');
 const storeUrl=new URL('../package/lib/redteam/store-core.js',import.meta.url).href,benchUrl=new URL('../package/lib/redteam/personal-security-workbench.mjs',import.meta.url).href;
 fs.mkdirSync(path.join(dir,'repo'));
 fs.writeFileSync(ownerFile,`import fs from 'node:fs';import {RedteamStore} from ${JSON.stringify(storeUrl)};import {securityFor,executeSecurityOp} from ${JSON.stringify(benchUrl)};import {createSecurityServer,reconcileSecurityProjects} from ${JSON.stringify(moduleUrl.href)};
 const store=new RedteamStore(${JSON.stringify(path.join(dir,'facts'))});store.openEngagement('a');store.openEngagement('b');const bench=securityFor(store);bench.workspaceRoot=${JSON.stringify(dir)};bench.toolStatus=()=>({semgrep:{ready:true,version:'fixture'}});bench.runner=(_t,_p,{signal,runDir})=>new Promise((resolve,reject)=>{const counter=${JSON.stringify(path.join(dir,'starts'))};fs.appendFileSync(counter,'1');const delay=fs.statSync(counter).size===2?60000:600;
 if(delay===60000){
  fs.mkdirSync(runDir,{recursive:true,mode:0o700});
  fs.writeFileSync(runDir+'/semgrep-rules.json','synthetic staged rules');
  fs.mkdirSync(runDir+'/trivy-db');
  fs.writeFileSync(runDir+'/trivy-db/trivy.db','synthetic staged database');
  fs.writeFileSync(runDir+'/trivy-db/metadata.json','{}');
  fs.writeFileSync(runDir+'/keep.txt','unrelated');
 }const timer=setTimeout(()=>resolve({complete:true,coverageKey:'fixture',coverageFiles:['fixture.js'],findings:[]}),delay);signal.addEventListener('abort',()=>{clearTimeout(timer);reject(Error('cancelled'))},{once:true})});
 if(process.argv[2]==='restart'){
  const summary=reconcileSecurityProjects(store,bench);
  const interrupted=store.db('a').prepare("SELECT COUNT(*) AS n FROM security_run WHERE state='interrupted' AND complete=0").get().n;
  if(summary.checkedProjects!==2||summary.failedProjects||interrupted!==1)throw Error('Startup did not reconcile the interrupted run before listening');
  const row=store.db('a').prepare("SELECT id FROM security_run WHERE state='interrupted'").get();
  const files=fs.readdirSync(store.dirOf('a')+'/runs/security/'+row.id);
  if(files.join(',')!=='keep.txt')throw Error('Startup did not reclaim only fixed staged inputs');
 }
 const server=createSecurityServer({dispatch:(request,options)=>executeSecurityOp(store,request,options)});server.listen(${JSON.stringify(socket)},()=>{fs.chmodSync(${JSON.stringify(socket)},0o600);process.stdout.write('ready\\n')});process.once('SIGTERM',async()=>{await server.shutdown();await bench.dispose();await store.close()});`);
 let owner;
 async function launch(mode){
  owner=spawn(process.execPath,['--no-warnings',ownerFile,mode],{stdio:['ignore','pipe','inherit']});
  let ready='';
  owner.stdout.on('data',chunk=>{ready+=chunk});
  await new Promise((resolve,reject)=>{
   const deadline=Date.now()+5000;
   const poll=()=>{if(ready.includes('ready'))resolve();else if(owner.exitCode!==null||owner.signalCode!==null||Date.now()>=deadline)reject(Error('owner not ready'));else setTimeout(poll,10)};
   poll();
  });
 }
 try{
  await launch('initial');
  assert.equal((await requestSecurityService({op:'securityScopeSave',engagement:'a',requestId:'service-scope',revision:0,repoRoot:path.join(dir,'repo'),tools:['semgrep'],expiresAt:new Date(Date.now()+3600000).toISOString(),confirm:true},{socketPath:socket})).ok,true);
  assert.equal((await requestSecurityService({op:'securityScopeSave',engagement:'a',requestId:'model-denied-scope',confirm:true},{model:true,socketPath:socket})).ok,false);
  const request={op:'securityStart',engagement:'a',requestId:'service-run-unique',profileRevision:1,tool:'semgrep'};
  const clientCode=`import {requestSecurityService} from ${JSON.stringify(moduleUrl.href)};console.log(JSON.stringify(await requestSecurityService(${JSON.stringify(request)},{model:true,socketPath:${JSON.stringify(socket)}})));`;
  const caller=spawnSync(process.execPath,['--input-type=module','--eval',clientCode],{encoding:'utf8',timeout:5000});assert.equal(caller.status,0,caller.stderr);const first=JSON.parse(caller.stdout);assert.equal(first.ok,true);assert.equal(first.run.state,'running');assert.equal(owner.exitCode,null);
  const duplicate=await requestSecurityService(request,{model:true,socketPath:socket});assert.equal(duplicate.run.id,first.run.id);
  const wrong=await requestSecurityService({op:'securityCancel',engagement:'b',id:first.run.id},{socketPath:socket});assert.equal(wrong.ok,false);
  const final=await requestSecurityService({op:'securityWait',engagement:'a',id:first.run.id,waitSeconds:2},{model:true,socketPath:socket});assert.equal(final.run.state,'completed');assert.equal(fs.readFileSync(path.join(dir,'starts'),'utf8'),'1');assert.equal(owner.exitCode,null);
  const interruptedRequest={...request,requestId:'service-run-interrupted'};
  const pending=await requestSecurityService(interruptedRequest,{socketPath:socket});
  assert.equal(pending.run.state,'running');
  const exit=once(owner,'exit');
  owner.kill('SIGKILL');
  assert.deepEqual(await exit,[null,'SIGKILL']);
  assert.equal(fs.readFileSync(path.join(dir,'starts'),'utf8'),'11');
  fs.unlinkSync(socket);
  await launch('restart');

  const wait=id=>requestSecurityService({op:'securityWait',engagement:'a',id,waitSeconds:0},{socketPath:socket});
  const recovered=await wait(pending.run.id);
  assert.equal(recovered.run.state,'interrupted');
  assert.equal(recovered.run.complete,0);
  assert.match(recovered.run.error_code,/结果未确认/);
  assert.equal((await wait(first.run.id)).run.state,'completed');
  const replay=await requestSecurityService(interruptedRequest,{socketPath:socket});
  assert.deepEqual(replay.run,{id:pending.run.id,state:'interrupted'});
  assert.equal((await requestSecurityService({...interruptedRequest,profileRevision:2},{socketPath:socket})).ok,false);
  assert.equal(fs.readFileSync(path.join(dir,'starts'),'utf8'),'11');
  const fresh=await requestSecurityService({...request,requestId:'service-run-after-restart'},{socketPath:socket});
  assert.notEqual(fresh.run.id,pending.run.id);
  const completed=await requestSecurityService({op:'securityWait',engagement:'a',id:fresh.run.id,waitSeconds:2},{socketPath:socket});
  assert.equal(completed.run.state,'completed');
  assert.equal(fs.readFileSync(path.join(dir,'starts'),'utf8'),'111');
 }finally{
  if(owner&&owner.exitCode===null&&owner.signalCode===null){const exited=once(owner,'exit');owner.kill('SIGTERM');await exited}
  fs.rmSync(dir,{recursive:true,force:true});
 }
});
