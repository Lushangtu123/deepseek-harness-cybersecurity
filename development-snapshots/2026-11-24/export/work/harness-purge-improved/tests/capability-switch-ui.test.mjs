import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function fixture(request) {
 const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8');
 const start=source.indexOf('function createOriginalSwitchModel('),end=source.indexOf('function OriginalCapabilitiesSwitch(',start);
 assert.ok(start>=0&&end>start,'In-Harness switch model missing');
 const tasks=[],updates=[];let now=0;
 const scope={performance:{now:()=>now},setTimeout:callback=>{tasks.push(callback);return tasks.length;},clearTimeout(){}};
 vm.runInNewContext(source.slice(start,end)+'\ncreate=createOriginalSwitchModel;',scope);
 const model=scope.create({request,publish:value=>updates.push({...value}),onVerified(){}});
 return {model,tasks,updates,tick:()=>{now+=2000;const task=tasks.shift();return task?.();}};
}
const current=enabled=>({ok:true,enabled,pluginStatus:{ok:true,ready:true,originalCapabilities:{enabled,managed:true}},operation:null});

test('flipping the switch requires a separate confirmation before sending one write',async()=>{
 const calls=[];const f=fixture(async(method,body)=>{calls.push({method,body});return current(false);});
 await f.model.refresh();f.model.select(true);
 assert.equal(f.updates.at(-1).confirm,true);assert.equal(calls.filter(call=>call.method==='POST').length,0);
 f.model.cancel();assert.equal(f.updates.at(-1).confirm,null);
});

test('a lost POST acknowledgement is followed by read-only status checks, never a retry',async()=>{
 const calls=[];let reads=0;
 const f=fixture(async(method)=>{
  calls.push(method);
  if(method==='POST')throw Error('lost response');
  reads++;return reads===1?current(false):{ok:true,enabled:null,operation:{id:'one',state:'running',targetEnabled:true}};
 });
 await f.model.refresh();f.model.select(true);await f.model.confirm();await f.tick();
 assert.equal(calls.filter(method=>method==='POST').length,1);assert.ok(calls.filter(method=>method==='GET').length>=2);
 assert.equal(f.updates.at(-1).busy,true);assert.notEqual(f.updates.at(-1).enabled,true);
});

test('running operations disable duplicate confirmation and a verified receipt updates the actual switch',async()=>{
 let posts=0,done=false;
 const f=fixture(async(method)=>{
  if(method==='POST'){posts++;return {ok:true,operation:{id:'one',state:'running',targetEnabled:true}};}
  return done?{...current(true),operation:{id:'one',state:'succeeded',targetEnabled:true}}:posts?{ok:true,enabled:null,operation:{id:'one',state:'running',targetEnabled:true}}:current(false);
 });
 await f.model.refresh();f.model.select(true);await f.model.confirm();await f.model.confirm();assert.equal(posts,1);
 done=true;await f.tick();assert.equal(f.updates.at(-1).enabled,true);assert.equal(f.updates.at(-1).busy,false);
});

test('disposed views do not receive late responses or schedule more polling',async()=>{
 let resolve;const f=fixture(()=>new Promise(done=>{resolve=done;}));
 const reading=f.model.refresh();f.model.dispose();resolve(current(false));await reading;
 assert.equal(f.tasks.length,0);assert.equal(f.updates.filter(value=>value.known===true).length,0);
});

test('an older read cannot overwrite a newer actual mode',async()=>{
 const pending=[];const f=fixture(()=>new Promise(resolve=>pending.push(resolve)));
 const old=f.model.refresh(),newer=f.model.refresh();
 pending[1](current(true));await newer;pending[0](current(false));await old;
 assert.equal(f.updates.at(-1).enabled,true);
});
