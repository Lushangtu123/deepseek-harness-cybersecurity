import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { ENVIRONMENT_BANNER } from './web-health.mjs';
function fixture() {
  let wall=Date.parse('2026-10-26T22:00:00Z'),mono=1000,id=0;
  const events=new Map(),windowEvents=new Map(),intervals=new Map(),timers=new Map(),due=new Map(),pending=[],nodes=[];
  const element=tag=>({tag,style:{},children:[],textContent:'',disabled:false,appendChild(child){this.children.push(child)},addEventListener(name,fn){this[name]=fn}});
  const document={visibilityState:'visible',getElementById:()=>null,createElement:element,body:{appendChild(node){nodes.push(node)}},addEventListener(name,fn){events.set(name,fn)}};
  class Clock extends Date {constructor(...args){super(...(args.length?args:[wall]))}static now(){return wall}}
  vm.runInNewContext(ENVIRONMENT_BANNER,{document,window:{addEventListener(name,fn){windowEvents.set(name,fn)}},Date:Clock,performance:{now:()=>mono},AbortController,AbortSignal,
    setInterval(fn){intervals.set(++id,fn);return id},clearInterval(key){intervals.delete(key)},setTimeout(fn,delay){timers.set(++id,fn);due.set(id,mono+delay);return id},clearTimeout(key){timers.delete(key);due.delete(key)},
    fetch:(_url,options)=>new Promise((resolve,reject)=>pending.push({resolve,reject,options}))});
  const answer=index=>pending[index].resolve({ok:true,json:async()=>({mode:'improved',modeFileMatches:true,configDir:'/home/purge/.dsh-improved',observedAt:'2026-10-26T22:00:00Z',recovery:{state:'matches',name:'ready-workbench-v7-20261026',groups:{}}})});
  return{pending,timers,intervals,answer,document,events,windowEvents,title:()=>nodes[0].children[0].textContent,button:()=>nodes[0].children[2],advance(ms,{sleep=false}={}){wall+=ms;if(!sleep)mono+=ms},rollback(ms){wall-=ms;mono+=ms},tick(){[...intervals.values()].forEach(fn=>fn())},fireDue(){for(const [key,at]of [...due])if(at<=mono){due.delete(key);const fn=timers.get(key);timers.delete(key);fn?.()}}};
}
const flush=()=>new Promise(setImmediate);
test('The collapsed banner ages into an explicit stale state without issuing background requests',async()=>{
 const f=fixture();f.answer(0);await flush();assert.match(f.title(),/刚刚核对/);
 f.advance(61000);f.tick();assert.match(f.title(),/待重新核对/);assert.doesNotMatch(f.title(),/已覆盖/);assert.equal(f.pending.length,1);
});
test('A slow initial response expires exactly sixty seconds after receipt between display ticks',async()=>{
 const f=fixture();f.advance(9000);f.answer(0);await flush();assert.match(f.title(),/已覆盖/);
 f.advance(60000);f.fireDue();assert.match(f.title(),/待重新核对/);assert.doesNotMatch(f.title(),/已覆盖/);
});
test('Returning focus and visibility coalesces into one throttled read-only refresh',async()=>{
 const f=fixture();f.answer(0);await flush();f.advance(61000);
 f.windowEvents.get('focus')?.();f.events.get('visibilitychange')?.();await flush();assert.equal(f.pending.length,2);
 f.answer(1);await flush();assert.match(f.title(),/刚刚核对/);
 f.windowEvents.get('focus')?.();await flush();assert.equal(f.pending.length,2);
});
test('Sleep with a paused monotonic clock and wall-clock rollback both make old state stale',async()=>{
 for(const mode of ['sleep','rollback']){
  const f=fixture();f.answer(0);await flush();mode==='sleep'?f.advance(120000,{sleep:true}):f.rollback(120000);f.tick();assert.match(f.title(),/待重新核对/);
 }
});
test('A backwards host clock correction during sleep forces a refresh despite the focus throttle',async()=>{
 const f=fixture();f.answer(0);await flush();f.advance(1000);f.advance(-3600000,{sleep:true});f.tick();
 assert.match(f.title(),/待重新核对/);assert.doesNotMatch(f.title(),/Infinity|刚刚核对/);
 f.windowEvents.get('focus')?.();f.events.get('visibilitychange')?.();await flush();assert.equal(f.pending.length,2);
 f.answer(1);await flush();assert.match(f.title(),/刚刚核对/);
});
test('A failed refresh keeps historical data from being presented as current coverage',async()=>{
 const f=fixture();f.answer(0);await flush();f.advance(6000);f.windowEvents.get('focus')?.();await flush();
 assert.equal(f.pending.length,2);f.pending[1].reject(Error('synthetic offline'));await flush();f.tick();assert.match(f.title(),/核对失败|暂时不可用/);assert.doesNotMatch(f.title(),/已覆盖/);
});
test('An ignored abort has a bounded deadline and cannot later overwrite a successful refresh',async()=>{
 const f=fixture();assert.ok(f.timers.size,'Banner request needs an explicit deadline');[...f.timers.values()].forEach(fn=>fn());await flush();assert.equal(f.button().disabled,false);
 const next=f.button().click();await flush();assert.equal(f.pending.length,2);f.answer(1);await next;await flush();const title=f.title();
 f.pending[0].resolve({ok:true,json:async()=>({mode:'original',recovery:{state:'older'}})});await flush();assert.equal(f.title(),title);
});
test('A hidden page does not refresh on focus events',async()=>{
 const f=fixture();f.answer(0);await flush();f.advance(61000);f.document.visibilityState='hidden';f.windowEvents.get('focus')?.();f.events.get('visibilitychange')?.();await flush();assert.equal(f.pending.length,1);
});
