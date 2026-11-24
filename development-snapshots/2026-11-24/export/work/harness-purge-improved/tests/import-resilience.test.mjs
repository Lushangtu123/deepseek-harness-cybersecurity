import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8');
const settle=()=>new Promise(setImmediate);
function fixture(stage='create') {
 const timers=new Map(),calls=[];let id=0,release,selected='A',items=[];
 const slow=new Promise(resolve=>{release=resolve});
 const host={sidebarRight:{mounted:{getSnapshot:()=>selected}},workspaces:{list:{getSnapshot:()=>({phase:'ready',state:'idle',items})},create:async()=>{calls.push('create');if(stage==='create')await slow;const workspace={workspaceId:'W',path:'/home/purge/workspace/repo'};items=[workspace];return workspace}},uiWorkspace:{openWorkspace:async(_id,ready)=>{calls.push('open');if(stage==='open')await slow;ready('B');selected='B'}}};
 const scope={AbortController,AbortSignal,setTimeout:(fn)=>{timers.set(++id,fn);return id},clearTimeout:key=>timers.delete(key)};
 const start=source.indexOf('async function importVmClone('),end=source.indexOf('\n\t\tfunction vmToolchainLabel(',start);
 vm.runInNewContext(source.slice(start,end)+'\nrun=importVmClone;outcome=typeof readVmImportOutcome==="function"?readVmImportOutcome:null;',scope);
 return{calls,timers,host,run:signal=>scope.run(host,'/home/purge/workspace/repo',()=>true,signal),release,selected:()=>selected,expire:()=>[...timers.values()].forEach(fn=>fn()),list:value=>{items=value},outcome:()=>scope.outcome(host,'/home/purge/workspace/repo')};
}
for(const stage of ['create','open'])test('Stopping a pending '+stage+' returns uncertainty and prevents late navigation',async()=>{
 const f=fixture(stage),controller=new AbortController();let settled=false;
 const pending=f.run(controller.signal).then(value=>{settled=true;return value});await settle();controller.abort();await settle();
 assert.equal(settled,true,'Stopping wait must settle while the official RPC remains pending');
 const result=await pending;assert.equal(result.uncertain,true);assert.equal(f.selected(),'A');
 const repeat=await f.run();assert.equal(repeat.uncertain,true);assert.equal(f.calls.filter(x=>x==='create').length,1);assert.equal(f.calls.filter(x=>x==='open').length,stage==='open'?1:0);
 f.release();await settle();assert.equal(f.selected(),'A');assert.equal(f.timers.size,0);
 assert.equal(f.outcome().state,'registered');assert.equal(f.outcome().pending,false);
});
test('A deadline returns uncertainty without replaying create or claiming failure',async()=>{
 const f=fixture();let settled=false;const pending=f.run().then(value=>{settled=true;return value});await settle();f.expire();await settle();
 assert.equal(settled,true);assert.equal((await pending).uncertain,true);assert.deepEqual(f.calls,['create']);
 f.release();await settle();assert.equal(f.selected(),'A');assert.equal(f.outcome().state,'registered');
});
test('A read-only reconciliation distinguishes registered and unconfirmed without a new create',async()=>{
 const f=fixture();const controller=new AbortController();let settled=false;const task=f.run(controller.signal).then(value=>{settled=true;return value});await settle();controller.abort();await settle();assert.equal(settled,true);await task;
 assert.equal(f.outcome().state,'unconfirmed');f.list([{workspaceId:'W',path:'/home/purge/workspace/repo'}]);
 assert.equal(f.outcome().state,'registered');assert.deepEqual(f.calls,['create']);f.release();await settle();
});
test('A cancelled signal before submission performs no mutation',async()=>{
 const f=fixture(),controller=new AbortController();controller.abort();await assert.rejects(f.run(controller.signal));assert.deepEqual(f.calls,[]);
});
test('An uncertain rejected create can be reconciled from the official list without resubmission',async()=>{
 const f=fixture('fast');let creates=0;f.host.workspaces.create=async()=>{creates++;throw Error('synthetic response lost')};
 await assert.rejects(f.run());f.list([{workspaceId:'W',path:'/home/purge/workspace/repo'}]);
 assert.equal(f.outcome().state,'registered');const resumed=await f.run();assert.equal(resumed.opened,true);assert.equal(creates,1);
});
