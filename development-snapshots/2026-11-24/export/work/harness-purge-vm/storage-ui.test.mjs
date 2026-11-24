import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import * as health from './web-health.mjs';
const gib=1024**3,flush=()=>new Promise(setImmediate);
const sample=()=>({version:1,readOnly:true,deletionAvailable:false,state:'current',monitoring:true,intervalSeconds:60,staleAfterSeconds:90,ageMs:0,checkedAt:'2026-11-01T22:00:00Z',hostFilesystem:{state:'healthy',totalBytes:500*gib,availableBytes:100*gib,availablePercent:20},guest:{state:'observed',filesystem:{state:'warning',totalBytes:100*gib,availableBytes:9*gib,availablePercent:9,inodeTotal:1000,inodeAvailable:900}}});
function fixture(panel=true){
 assert.equal(typeof health.STORAGE_SCRIPT,'string','Storage browser view missing');
 let wall=Date.parse('2026-11-01T22:00:00Z'),mono=0;const pending=[],timers=new Map(),intervals=[],events={},windowEvents={},nodes=new Map();let id=0;
 const element=tag=>({tag,style:{},children:[],textContent:'',attrs:{},appendChild(node){this.children.push(node)},setAttribute(k,v){this.attrs[k]=String(v)},getAttribute(k){return this.attrs[k]},addEventListener(k,v){this[k]=v}});
 if(panel){for(const name of ['app','summary','checked','error','refresh','monitor','inodes',...['host','guest'].flatMap(k=>['status','free','total','percent','bar'].map(t=>k+'-'+t))])nodes.set('storage-'+name,element('div'))}
 else{const box=element('details');box.children.push(element('summary'));box.children[0].textContent='VM · 改进版';nodes.set('harness-vm-identity',box)}
 const document={visibilityState:'visible',getElementById:k=>nodes.get(k),createElement:element,body:element('body'),addEventListener(k,v){events[k]=v}};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[wall]))}static now(){return wall}}
 vm.runInNewContext(health.STORAGE_SCRIPT,{document,window:{addEventListener(k,v){windowEvents[k]=v}},Date:Clock,performance:{now:()=>mono},AbortController,Promise,
  setInterval:fn=>{intervals.push(fn);return intervals.length},clearInterval(){},setTimeout:fn=>{timers.set(++id,fn);return id},clearTimeout:key=>timers.delete(key),
  fetch:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject}))});
 return{nodes,pending,timers,document,events,windowEvents,answer(value=sample(),at=pending.length-1){pending[at].resolve({ok:true,json:async()=>value})},advance(ms){wall+=ms;mono+=ms},jumpWall(ms){wall+=ms},tick(){intervals.forEach(fn=>fn())}};
}
test('A browser response crossing sleep or clock rollback cannot renew an old healthy sample',async()=>{
 for(const jump of [3600000,-3600000]){
  const f=fixture(false),value=sample();value.guest.filesystem.state='healthy';value.guest.filesystem.availableBytes=30*gib;
  f.jumpWall(jump);f.answer(value);await flush();const box=f.nodes.get('harness-vm-identity');assert.match(box.getAttribute('data-storage-label'),/失败|待重新/);assert.doesNotMatch(box.children[0].textContent,/存储：正常/);
 }
});
test('Capacity cards show warning and inode counters; expired and failed reads cannot look healthy',async()=>{
 const f=fixture();f.answer();await flush();assert.match(f.nodes.get('storage-summary').textContent,/预警/);assert.match(f.nodes.get('storage-guest-free').textContent,/9.00/);assert.match(f.nodes.get('storage-inodes').textContent,/90/);
 f.advance(91000);f.tick();assert.match(f.nodes.get('storage-summary').textContent,/过期|待重新/);assert.doesNotMatch(f.nodes.get('storage-summary').textContent,/容量正常/);
 f.pending.at(-1).reject(Error('private error'));await flush();assert.match(f.nodes.get('storage-summary').textContent,/失败/);assert.doesNotMatch(f.nodes.get('storage-error').textContent,/private/);
 f.advance(6000);f.windowEvents.focus();f.answer();await flush();assert.match(f.nodes.get('storage-summary').textContent,/预警/);
});
test('Hidden views stop polling; focus and visibility coalesce; read deadline frees the refresh button',async()=>{
 const f=fixture();f.answer();await flush();f.advance(16000);f.document.visibilityState='hidden';f.tick();assert.equal(f.pending.length,1);
 f.document.visibilityState='visible';f.windowEvents.focus();f.events.visibilitychange();assert.equal(f.pending.length,2);
 [...f.timers.values()].forEach(fn=>fn());await flush();assert.equal(f.nodes.get('storage-refresh').disabled,false);assert.match(f.nodes.get('storage-summary').textContent,/失败/);
});
test('Collapsed Harness identity carries a visible warning and storage link',async()=>{
 const f=fixture(false);f.answer();await flush();const box=f.nodes.get('harness-vm-identity');assert.match(box.getAttribute('data-storage-label'),/预警/);assert.match(box.children[0].textContent,/存储：.*预警/);assert.ok(box.children.some(row=>row.href==='/__harness/storage'));
});
