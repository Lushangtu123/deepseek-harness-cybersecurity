import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {createDiagnostics,HEALTH_HTML} from './web-health.mjs';
const tick=()=>new Promise(setImmediate);
test('Refreshing diagnostics does not renew an old layer observation',t=>{
 let wall=Date.now(),mono=performance.now();t.mock.method(Date,'now',()=>wall);t.mock.method(performance,'now',()=>mono);
 const d=createDiagnostics();d.finish(d.begin('/redteam/test','POST'),200,undefined,0,'complete');
 const before=d.snapshot().layers.redteam;assert.ok(Number.isFinite(Date.parse(before.observedAt)));assert.equal(before.ageMs,0);
 wall+=120000;mono+=120000;const after=d.snapshot().layers.redteam;
 assert.equal(after.observedAt,before.observedAt);assert.equal(after.ageMs,120000);assert.equal(after.stale,true);
});
function fixture(){
 let wall=Date.parse('2026-10-27T00:00:00Z'),mono=0,fetches=0,id=0;
 class ClockDate extends Date{constructor(...args){super(...(args.length?args:[wall]))}static now(){return wall}}
 const timers=new Map(),intervals=[],handlers={},nodes={};
 const element=()=>({children:[],textContent:'',disabled:false,appendChild(child){this.children.push(child)},replaceChildren(){this.children=[]},addEventListener(){}});
 for(const name of ['refresh','error','layers','summary','events','freshness'])nodes[name]=element();
 const data={layers:{redteam:{state:'ok',phase:'complete',observedAt:new ClockDate().toISOString(),ageMs:0,stale:false}},active:{websocket:0,sse:0},recent:[]};
 const context={Date:ClockDate,performance:{now:()=>mono},AbortController,setTimeout:fn=>{timers.set(++id,fn);return id},clearTimeout:key=>timers.delete(key),setInterval:fn=>{intervals.push(fn);return intervals.length},document:{getElementById:name=>nodes[name],createElement:element,visibilityState:'visible',addEventListener:(name,fn)=>{handlers[name]=fn}},window:{addEventListener:(name,fn)=>{handlers[name]=fn}},fetch:async()=>{fetches++;return{ok:true,json:async()=>data}}};
 vm.runInNewContext(HEALTH_HTML.split('<script>')[1].split('</script>')[0],context);
 return{nodes,data,handlers,context,fetches:()=>fetches,age:ms=>{wall+=ms;mono+=ms;intervals.forEach(fn=>fn())},rows:()=>nodes.layers.children.map(row=>row.children.map(cell=>cell.textContent).join(' ')).join('\n')};
}
test('An idle health page marks old success as a past observation without sending a VM probe',async()=>{
 const f=fixture();await tick();assert.match(f.rows(),/正文已完整接收/);
 f.age(120000);assert.match(f.rows(),/当前待观察/);assert.match(f.nodes.freshness.textContent,/过期/);assert.equal(f.fetches(),1);
});
test('Returning to the health page refreshes records with a five-second throttle and preserves their old age',async()=>{
 const f=fixture();await tick();f.age(120000);f.data.layers.redteam.ageMs=120000;f.data.layers.redteam.stale=true;
 assert.equal(typeof f.handlers.focus,'function');f.handlers.focus();f.handlers.visibilitychange();await tick();assert.equal(f.fetches(),2);
 assert.match(f.rows(),/当前待观察/);assert.match(f.nodes.freshness.textContent,/刚刚/);
 f.handlers.focus();await tick();assert.equal(f.fetches(),2);
 f.age(5000);f.handlers.focus();await tick();assert.equal(f.fetches(),3);
});
test('Expired and clock-rollback snapshots cannot present old subscription counts as current',async()=>{
 for(const age of [60000,-1000]){
  const f=fixture();f.data.active.websocket=1;await tick();assert.match(f.nodes.summary.textContent,/当前订阅：WebSocket 1/);
  f.age(age);assert.match(f.nodes.summary.textContent,/上次记录订阅：WebSocket 1/);assert.doesNotMatch(f.nodes.summary.textContent,/当前订阅/);
 }
});
test('A failed records refresh downgrades subscription counts even within the normal freshness window',async()=>{
 const f=fixture();await tick();f.context.fetch=async()=>{throw Error('synthetic diagnostics unavailable')};await f.context.refresh();
 assert.match(f.nodes.summary.textContent,/上次记录订阅/);assert.match(f.nodes.freshness.textContent,/读取失败/);
});
