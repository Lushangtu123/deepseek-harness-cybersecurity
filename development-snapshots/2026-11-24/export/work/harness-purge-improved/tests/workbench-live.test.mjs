import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8')
function store(value){const listeners=new Set();return{getSnapshot:()=>value,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},set:next=>{value=next;for(const fn of [...listeners])fn()},listeners}}
function fixture({delayed=false,clock=false}={}){
 const start=source.indexOf('function vmTerminalUnavailable(');assert.ok(start>=0,'Live terminal observation is missing')
 const end=source.indexOf('\n\t\tasync function importVmClone(',start)
 const updates=[],errors=[],pending=[],timers=new Map();let poll,cleared=false,unavailable=false,wall=1000,mono=1000,timerId=0
 const tabs=store([{sessionId:'A',kind:'terminal',tabId:'dead',contentId:'dead'},{sessionId:'A',kind:'terminal',tabId:'live',contentId:'live'}]),mounted=store('A')
 const states={dead:store({phase:'failed'}),live:store({phase:'loading'})}
 const infos=[{id:'live',title:'bash',cwd:'/home/purge/workspace/demo',state:'running'}]
 const host={sidebarRight:{mounted,openTabs:tabs,tabDomain:{occurrence:()=>({navigation:{getSnapshot:()=>({params:{}})}})}},webTerminals:{view:(_,key)=>({id:key,state:states[key]})},remote:{terminal:{list:session=>unavailable?Promise.reject(Error('synthetic offline')):delayed?new Promise(resolve=>pending.push({session,resolve})):Promise.resolve({ok:true,value:infos}),environment:async()=>({ok:true,value:{cwd:'/home/purge/workspace/demo'}})}}}
 const scope={AbortController,AbortSignal,setTimeout:clock?((fn,ms)=>{timers.set(++timerId,{fn,due:mono+ms});return timerId}):setTimeout,clearTimeout:clock?(id=>timers.delete(id)):clearTimeout,setInterval:fn=>{poll=fn;return 1},clearInterval:()=>{cleared=true}}
 if(clock){scope.Date=class extends Date{static now(){return wall}};scope.performance={now:()=>mono}}
 vm.runInNewContext(source.slice(start,end)+'\nwatch=observeVmTerminals;label=vmTerminalLabel;',scope)
 const controller=scope.watch(host,value=>updates.push(value),error=>errors.push(error))
 return{controller,updates,errors,states,mounted,tabs,pending,infos,label:scope.label,poll:()=>poll(),cleared:()=>cleared,fail:value=>{unavailable=value},advance:ms=>{wall+=ms;mono+=ms},rollback:ms=>{wall-=ms},fireDue:()=>{for(const[id,t]of [...timers])if(t.due<=mono){timers.delete(id);t.fn()}},timers}
}
const settle=()=>new Promise(setImmediate)
test('The manager distinguishes a running detached process and pushes state changes without manual refresh',async()=>{
 const f=fixture();await settle()
 const live=f.updates.at(-1).rows.find(row=>row.tabId==='live')
 assert.equal(live.processState,'running');assert.match(f.label(live),/运行中/)
 f.states.live.set({phase:'connected',info:f.infos[0]})
 assert.equal(f.updates.at(-1).rows[0].tabId,'live');assert.match(f.label(f.updates.at(-1).rows[0]),/已连接/)
 f.controller.dispose();assert.equal(f.states.live.listeners.size,0);assert.equal(f.tabs.listeners.size,0);assert.equal(f.mounted.listeners.size,0);assert.equal(f.cleared(),true)
 const count=f.updates.length;f.states.live.set({phase:'closed'});assert.equal(f.updates.length,count)
})
test('A host terminal missing after VM restart is classified as unavailable rather than permanently loading',async()=>{
 const f=fixture();await settle();const dead=f.updates.at(-1).rows.find(row=>row.tabId==='dead')
 assert.equal(dead.processState,'missing');assert.match(f.label(dead),/失效/)
 f.controller.dispose()
})
test('A late previous Session inventory cannot overwrite a newly selected Session',async()=>{
 const f=fixture({delayed:true});await settle();f.mounted.set('B');await settle()
 const latest=f.pending.find(p=>p.session==='B');assert.ok(latest);latest.resolve({ok:true,value:[]});await settle()
 f.pending.find(p=>p.session==='A').resolve({ok:true,value:f.infos});await settle()
 assert.equal(f.updates.at(-1).sessionId,'B');assert.equal(f.updates.at(-1).rows.length,0);f.controller.dispose()
})
test('Terminal output frames do not repaint the management list when status metadata is unchanged',async()=>{
 const f=fixture();await settle();f.states.live.set({phase:'connected',info:f.infos[0]});const count=f.updates.length
 f.states.live.set({phase:'connected',info:f.infos[0],render:{revision:99,frame:{type:'output',data:'synthetic output'}}})
 assert.equal(f.updates.length,count);f.controller.dispose()
})
test('A native process exit immediately outranks the last polled running inventory',async()=>{
 const f=fixture();await settle();f.states.live.set({phase:'connected',info:{...f.infos[0],state:'exited'}})
 const row=f.updates.at(-1).rows.find(row=>row.tabId==='live');assert.match(f.label(row),/退出/);assert.equal(row.processState,'exited');f.controller.dispose()
})
test('A failed inventory marks detached history unconfirmed and recovery clears the warning',async()=>{
 const f=fixture();await settle();f.states.live.set({phase:'disconnected',info:f.infos[0]});f.fail(true);await f.controller.refresh();
 let row=f.updates.at(-1).rows.find(row=>row.tabId==='live');assert.equal(row.processVerified,false);assert.match(f.label(row),/待核对/);assert.ok(f.updates.at(-1).lastCheckedAt);assert.match(f.errors.at(-1),/无法核对/);
 f.states.live.set({phase:'connected',info:f.infos[0]});row=f.updates.at(-1).rows.find(row=>row.tabId==='live');assert.match(f.label(row),/已连接/);
 f.fail(false);await f.controller.refresh();assert.equal(f.updates.at(-1).rows.find(row=>row.tabId==='live').processVerified,true);assert.equal(f.errors.at(-1),'');f.controller.dispose();
})
test('Detached inventory expires fifteen seconds after receipt without waiting for the next poll',async()=>{
 const f=fixture({clock:true});await settle();f.states.live.set({phase:'disconnected',info:f.infos[0]});f.advance(15000);f.fireDue();
 assert.equal(f.updates.at(-1).rows.find(row=>row.tabId==='live').processVerified,false);f.controller.dispose();assert.equal(f.timers.size,0);
})
test('Native connected and explicit exit events outrank an older missing inventory',async()=>{
 const f=fixture();f.infos.length=0;await settle();try {
 f.states.live.set({phase:'connected',info:{id:'live',state:'running'}});
 let row=f.updates.at(-1).rows.find(row=>row.tabId==='live');assert.match(f.label(row),/已连接/);
 f.states.live.set({phase:'connected',info:{id:'live',state:'exited'}});row=f.updates.at(-1).rows.find(row=>row.tabId==='live');assert.match(f.label(row),/已退出/); } finally { f.controller.dispose(); }
})
