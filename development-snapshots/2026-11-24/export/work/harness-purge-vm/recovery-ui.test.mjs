import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {RECOVERY_HTML} from './web-health.mjs';
const page=(id,nextCursor=null,truncated=false)=>({readOnly:true,currentRecovery:'ready-v30',observedAt:'2026-10-29T05:30:00Z',snapshotState:'observed',snapshots:[],images:[{id,logicalBytes:4,allocatedBytes:4}],storage:{freeBytes:10},truncated,nextCursor,archiveScan:{entriesScanned:1,entriesRemaining:nextCursor?1:0,visitedDirectories:3,skippedMetadataDirectories:1,reasons:truncated?['depth-limit']:[]}});
function fixture(responses){
 const element=()=>({textContent:'',hidden:false,disabled:false,children:[],events:{},appendChild(node){this.children.push(node)},replaceChildren(){this.children=[]},addEventListener(name,fn){this.events[name]=fn}});
 const nodes=Object.fromEntries(['free','snap-count','history-count','image-count','status','error','snapshots','history','images','refresh','more','more-snapshots'].map(id=>[id,element()]));
 const urls=[];const context={document:{getElementById:id=>nodes[id],createElement:element},AbortController,URLSearchParams,setTimeout:()=>0,clearTimeout(){},fetch:async url=>{urls.push(url);const result=responses.shift();if(result instanceof Error)throw result;if(result?.httpResponse)return result.httpResponse;return{ok:true,json:async()=>result}}};
 vm.runInNewContext(RECOVERY_HTML.match(/<script>([\s\S]*)<\/script>/)[1],context);
 return{nodes,urls,async settle(){for(let i=0;i<12;i++)await Promise.resolve()}};
}
test('Load-more appends distinct images, preserves previous limitations and ends pagination',async()=>{
 const f=fixture([page('a.qcow2','probe-a',true),page('b.qcow2')]);await f.settle();
 assert.equal(typeof f.nodes.more.events.click,'function','Recovery page needs a working continuation control');assert.equal(f.nodes.more.hidden,false);
 await f.nodes.more.events.click();await f.settle();
 assert.equal(f.nodes['image-count'].textContent,'2');assert.equal(f.nodes.images.children.length,2);assert.equal(f.nodes.more.hidden,true);assert.match(f.nodes.status.textContent,/深度/);assert.match(f.urls[1],/after=probe-a/);
});
test('A failed next page retains visible results and the same retry cursor',async()=>{
 const f=fixture([page('a.qcow2','probe-a'),Error('synthetic unavailable'),page('b.qcow2')]);await f.settle();
 assert.equal(typeof f.nodes.more.events.click,'function');await f.nodes.more.events.click();await f.settle();assert.equal(f.nodes.images.children.length,1);assert.equal(f.nodes.more.disabled,false);
 await f.nodes.more.events.click();await f.settle();assert.equal(f.urls[1],f.urls[2]);assert.equal(f.nodes.images.children.length,2);
});

test('Snapshot pages append independently of archive pages and keep the pinned first page',async()=>{
 const first={...page('a.qcow2','archive-a'),nextSnapshotCursor:'snap-a',snapshots:[{name:'current',present:true,current:true,protected:true,bundleState:'verified'}]};
 const second={...page('a.qcow2','archive-a'),nextSnapshotCursor:null,snapshots:[{name:'old',present:true,bundleState:'verified'}]};
 const third={...page('b.qcow2'),nextSnapshotCursor:'snap-a',snapshots:first.snapshots};
 const f=fixture([first,second,third]);await f.settle();
 assert.equal(typeof f.nodes['more-snapshots'].events.click,'function','Snapshot list needs its own continuation control');
 await f.nodes['more-snapshots'].events.click();await f.settle();
 assert.equal(f.nodes.snapshots.children.length,2);assert.equal(f.nodes['more-snapshots'].hidden,true);assert.equal(f.nodes.images.children.length,1);assert.match(f.urls[1],/snapshotAfter=snap-a/);
 await f.nodes.more.events.click();await f.settle();assert.equal(f.nodes.snapshots.children.length,2);assert.equal(f.nodes.images.children.length,2);assert.equal(f.nodes['more-snapshots'].hidden,true);assert.equal(f.nodes.more.hidden,true);
});

test('A failed snapshot continuation preserves rows and retries the same cursor',async()=>{
 const first={...page('a.qcow2'),nextSnapshotCursor:'snap-a',snapshots:[{name:'current',present:true}]};
 const f=fixture([first,Error('synthetic unavailable'),{...page('a.qcow2'),snapshots:[{name:'old',present:true}]}]);await f.settle();
 assert.equal(typeof f.nodes['more-snapshots'].events.click,'function');await f.nodes['more-snapshots'].events.click();await f.settle();assert.equal(f.nodes.snapshots.children.length,1);assert.equal(f.nodes['more-snapshots'].disabled,false);
 await f.nodes['more-snapshots'].events.click();await f.settle();assert.equal(f.urls[1],f.urls[2]);assert.equal(f.nodes.snapshots.children.length,2);
});

test('Archive pages cannot turn unknown snapshot rows into a confirmed zero',async()=>{
 const first={...page('a.qcow2','archive-a'),snapshotState:'unavailable',snapshots:[{name:'current',present:null}]};
 const f=fixture([first,{...page('b.qcow2'),observedAt:'2026-10-29T06:30:00Z'}]);await f.settle();
 await f.nodes.more.events.click();await f.settle();
 assert.equal(f.nodes['snap-count'].textContent,'未确认');assert.match(f.nodes.status.textContent,/快照元数据暂不可读/);
 assert.match(f.nodes.status.textContent,/快照核对/);assert.match(f.nodes.status.textContent,/归档核对/);
});

test('A successful archive request retains the snapshot continuation failure',async()=>{
 const first={...page('a.qcow2','archive-a'),nextSnapshotCursor:'snap-a',snapshots:[{name:'current',present:true}]};
 const f=fixture([first,Error('synthetic snapshot failure'),page('b.qcow2')]);await f.settle();
 await f.nodes['more-snapshots'].events.click();await f.settle();
 await f.nodes.more.events.click();await f.settle();
 assert.match(f.nodes.error.textContent,/快照.*失败/);assert.equal(f.nodes['snap-count'].textContent,'1');
});

test('Snapshot pagination keeps archive failure status and archive observation time',async()=>{
 const first={...page('a.qcow2','archive-a'),nextSnapshotCursor:'snap-a',snapshots:[{name:'current',present:true}]};
 const f=fixture([first,Error('synthetic archive failure'),{...page('a.qcow2'),observedAt:'2026-10-29T06:30:00Z',snapshots:[{name:'other',present:true}]}]);await f.settle();
 await f.nodes.more.events.click();await f.settle();await f.nodes['more-snapshots'].events.click();await f.settle();
 assert.match(f.nodes.error.textContent,/归档.*失败/);assert.equal(f.nodes['snap-count'].textContent,'2');
 assert.equal(f.nodes.images.children.length,1);
});

test('First request failure never presents either list as complete or empty',async()=>{
 const f=fixture([Error('synthetic unavailable')]);await f.settle();
 assert.match(f.nodes.error.textContent,/快照读取失败/);assert.match(f.nodes.error.textContent,/归档读取失败/);
 assert.doesNotMatch(f.nodes.status.textContent,/已读取完/);assert.match(f.nodes.status.textContent,/尚未取得清单/);
 assert.equal(f.nodes.refresh.disabled,false);assert.equal(f.nodes.snapshots.children.length,0);assert.equal(f.nodes.images.children.length,0);
});

test('A pending initial request is loading, and a successful retry is complete',async()=>{
 let resolve;const pending=new Promise(done=>{resolve=done});const f=fixture([pending]);await f.settle();
 assert.match(f.nodes.status.textContent,/正在读取/);assert.doesNotMatch(f.nodes.status.textContent,/已读取完/);
 resolve(page('a.qcow2'));await f.settle();assert.match(f.nodes.status.textContent,/已读取完/);assert.equal(f.nodes['image-count'].textContent,'1');
});

test('Retry after initial failure replaces failure with a confirmed successful list',async()=>{
 const f=fixture([Error('synthetic unavailable'),page('a.qcow2')]);await f.settle();await f.nodes.refresh.events.click();await f.settle();
 assert.equal(f.nodes.error.textContent,'');assert.equal(f.nodes['image-count'].textContent,'1');assert.match(f.nodes.status.textContent,/已读取完/);
});

test('Unknown snapshot metadata and archive gaps cannot claim complete lists',async()=>{
 const f=fixture([{...page('a.qcow2',null,true),snapshotState:'unavailable',snapshots:[{name:'baseline',present:null}]}]);await f.settle();
 assert.doesNotMatch(f.nodes.status.textContent,/已读取完/);assert.match(f.nodes.status.textContent,/快照读取未确认/);assert.match(f.nodes.status.textContent,/清单仍有缺口/);
});

test('Failed refresh keeps the previous partial lists and their retry positions',async()=>{
 const f=fixture([{...page('a.qcow2','archive-a'),nextSnapshotCursor:'snap-a'},Error('synthetic refresh failure'),page('b.qcow2')]);await f.settle();
 await f.nodes.refresh.events.click();await f.settle();assert.equal(f.nodes.images.children.length,1);assert.equal(f.nodes.more.hidden,false);assert.doesNotMatch(f.nodes.status.textContent,/已读取完/);
 await f.nodes.more.events.click();await f.settle();assert.match(f.urls[2],/after=archive-a/);assert.equal(f.nodes.images.children.length,2);assert.match(f.nodes.error.textContent,/快照读取失败/);
});

test('Malformed refresh preserves previous rows before reporting unconfirmed data',async()=>{
 const f=fixture([page('a.qcow2','archive-a'),{...page('b.qcow2'),images:null}]);await f.settle();await f.nodes.refresh.events.click();await f.settle();
 assert.equal(f.nodes['image-count'].textContent,'1');assert.equal(f.nodes.images.children.length,1);assert.equal(f.nodes.more.hidden,false);assert.match(f.nodes.error.textContent,/清单结构未确认/);
});
test('Continuations request only their own list and accept isolated responses',async()=>{
 const first={...page('a.qcow2','archive-a'),nextSnapshotCursor:'snap-a'};
 const f=fixture([first,{readOnly:true,currentRecovery:first.currentRecovery,observedAt:first.observedAt,images:[],nextCursor:null,archiveScan:{reasons:[]}}, {readOnly:true,currentRecovery:first.currentRecovery,observedAt:first.observedAt,snapshotState:'observed',snapshots:[],nextSnapshotCursor:null}]);await f.settle();
 await f.nodes.more.events.click();await f.settle();assert.match(f.urls[1],/part=images/);assert.equal(f.nodes.error.textContent,'');
 await f.nodes['more-snapshots'].events.click();await f.settle();assert.match(f.urls[2],/part=snapshots/);assert.equal(f.nodes.error.textContent,'');
});
test('Present and confirmed absent snapshot records render in different groups',async()=>{
 const f=fixture([{...page('a.qcow2'),snapshots:[{name:'present',present:true},{name:'historical',present:false}]}]);await f.settle();
 assert.equal(f.nodes.snapshots.children.length,1);assert.equal(f.nodes.history.children.length,1);assert.equal(f.nodes['history-count'].textContent,'1');assert.equal(f.nodes['snap-count'].textContent,'1');
});
test('Invalid scan metadata cannot partially commit a refresh or consume its previous cursor',async()=>{
 const f=fixture([page('a.qcow2','archive-a'),{...page('changed.qcow2'),archiveScan:{reasons:[null]}},page('b.qcow2')]);await f.settle();await f.nodes.refresh.events.click();await f.settle();
 assert.match(f.nodes.error.textContent,/清单结构未确认/);await f.nodes.more.events.click();await f.settle();assert.match(f.urls[2],/after=archive-a/);assert.equal(f.nodes['image-count'].textContent,'2');
});
test('HTTP failure displays the safe classification and correlated request ID',async()=>{
 const id='12345678-1234-1234-1234-123456789abc';const f=fixture([{httpResponse:{ok:false,headers:{get:()=>id},json:async()=>({error:'private raw data',diagnostic:{code:'invalid-catalog',requestId:id}})}}]);await f.settle();
 assert.match(f.nodes.error.textContent,/清单结构未确认/);assert.ok(f.nodes.error.textContent.includes(id));assert.ok(!f.nodes.error.textContent.includes('private'));
});
test('Snapshot-only generic truncation remains incomplete after its last cursor',async()=>{
 const f=fixture([{...page('a.qcow2'),nextSnapshotCursor:'snap-a'}, {...page('a.qcow2'),truncated:true,nextSnapshotCursor:null,snapshots:[{name:'last-visible',present:true}],archiveScan:{reasons:[]}}]);await f.settle();
 await f.nodes['more-snapshots'].events.click();await f.settle();assert.match(f.nodes.status.textContent,/清单仍有缺口/);assert.doesNotMatch(f.nodes.status.textContent,/本轮快照批次已读取完/);
});
