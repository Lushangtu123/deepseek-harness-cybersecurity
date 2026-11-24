import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import vm from 'node:vm';
import {RedteamStore,dispatch} from '../package/lib/redteam/store-core.js';
const source=fs.readFileSync(new URL('../package/lib/redteam/client.js',import.meta.url),'utf8'),fixture=fs.readFileSync(new URL('./ui-regression.test.mjs',import.meta.url),'utf8');
const scope={source,vm,assert,console,AbortController,Event,setTimeout,clearTimeout,setInterval,clearInterval,Date,performance};vm.runInNewContext(fixture.slice(fixture.indexOf('function host('),fixture.indexOf("test('API rejects")).replace('api, FindingsTab','api, ScoreTab, ChainTab, FindingsTab'),scope);
const {host,nodes,text,button}=scope,flush=async()=>{for(let i=0;i<32;i++)await Promise.resolve()},response=x=>({ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(x))});
function owned(){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'score-contract-')),store=new RedteamStore(dir),a=store.openEngagement('A',[],{bindCurrent:false}).id,b=store.openEngagement('B',[],{bindCurrent:false}).id;const ap=store.saveScorePoint(a,{name:'A-owned',points:17}),bp=store.saveScorePoint(b,{name:'B-owned',points:23});assert.equal(ap.id,bp.id);return{store,a,b,ap,bp,close(){store.close();fs.rmSync(dir,{recursive:true,force:true})}}}
function edit(h,name){let tree=h.render();const row=nodes(tree).find(n=>n.props?.role==='button'&&text(n).includes(name));assert.ok(row);row.props.onClick();tree=h.render();button(tree,'编辑').props.onClick({stopPropagation(){}});return h.render()}
for(const action of ['保存','删除'])test('Score project switch removes A editor and rejects its old '+action+' callback with colliding B ID',async()=>{const f=owned(),writes=[],h=host(async(_u,o)=>{const q=JSON.parse(o.body);if(q.op!=='scores')writes.push(q);return response(dispatch(f.store,q))});try{h.mount('ScoreTab',{engagement:f.a});await flush();const old=button(edit(h,'A-owned'),action);const beforeEffects=h.preview({engagement:f.b});assert.ok(!nodes(beforeEffects).some(n=>n.props?.placeholder==='名称（必填）'));h.render({engagement:f.b});await flush();h.render();old.props.onClick();await flush();assert.equal(writes.length,0);assert.equal(dispatch(f.store,{op:'scores',engagement:f.b}).items.find(p=>p.id===f.bp.id).name,'B-owned')}finally{h.unmount();f.close()}});
const scores=(name='current',builtin=false)=>({ok:true,items:[{id:1,name,points:10,hits:[],builtin,enabled:true}],summary:{achievedPoints:0,pointCount:1,countedHits:0}});
test('Score late A response cannot replace B and a same-project refresh invalidates old editor callbacks',async()=>{const pending=[],writes=[],h=host((_u,o)=>{const q=JSON.parse(o.body);if(q.op!=='scores'){writes.push(q);return Promise.resolve(response({ok:true}))}return new Promise(resolve=>pending.push({q,resolve}))});try{h.mount('ScoreTab',{engagement:'A'});h.render({engagement:'B'});await flush();pending[1].resolve(response(scores('B-current')));await flush();pending[0].resolve(response(scores('A-old')));await flush();assert.match(text(h.render()),/B-current/);const old=button(edit(h,'B-current'),'保存');h.render({engagement:'B',refreshKey:1});old.props.onClick();assert.equal(writes.length,0);pending[2].resolve(response(scores('B-new')));await flush();assert.match(text(h.render()),/B-new/)}finally{pending.forEach(p=>p.resolve(response(scores())));await flush();h.unmount()}});
test('Score rapid double save sends one write and an unknown reply only rereads',async()=>{let resolveWrite,reads=0;const writes=[],h=host((_u,o)=>{const q=JSON.parse(o.body);if(q.op==='scores'){reads++;return Promise.resolve(response(scores()))}writes.push(q);return new Promise(resolve=>resolveWrite=resolve)});try{h.mount('ScoreTab',{engagement:'A'});await flush();const save=button(edit(h,'current'),'保存');save.props.onClick();save.props.onClick();assert.equal(writes.length,1);resolveWrite(response({ok:false}));await flush();const tree=h.render();assert.match(text(tree),/结果未确认/);assert.equal(writes.length,1);assert.equal(reads,2);assert.ok(!nodes(tree).some(n=>n.props?.placeholder==='名称（必填）'))}finally{h.unmount()}});
test('Score old write completion cannot clear B editor or release its write lock',async()=>{const writes=[],pending=[],h=host((_u,o)=>{const q=JSON.parse(o.body);if(q.op==='scores')return Promise.resolve(response(scores(q.engagement+'-point')));writes.push(q);return new Promise(resolve=>pending.push(resolve))});try{h.mount('ScoreTab',{engagement:'A'});await flush();button(edit(h,'A-point'),'保存').props.onClick();h.render({engagement:'B'});await flush();const save=button(edit(h,'B-point'),'保存');save.props.onClick();pending[0](response({ok:true,note:'A-complete'}));await flush();let tree=h.render();assert.doesNotMatch(text(tree),/A-complete/);assert.equal(fieldName(tree),'B-point');assert.equal(button(tree,'保存').props.disabled,true);save.props.onClick();assert.equal(writes.length,2);pending[1](response({ok:true}));await flush();h.render()}finally{h.unmount()}});
function fieldName(tree){return nodes(tree).find(n=>n.props?.placeholder==='名称（必填）')?.props.value}
test('Score built-in name/value remain read-only and delete stays disabled',async()=>{const h=host(async()=>response(scores('builtin',true)));try{h.mount('ScoreTab',{engagement:'A'});await flush();const tree=edit(h,'builtin');assert.equal(nodes(tree).find(n=>n.props?.placeholder==='名称（必填）').props.readOnly,true);assert.equal(nodes(tree).find(n=>n.props?.placeholder==='单次分值').props.readOnly,true);assert.equal(button(tree,'删除（内置项不可删）').props.disabled,true)}finally{h.unmount()}});
test('Score callbacks after unmount cannot issue writes',async()=>{let writes=0;const h=host(async(_u,o)=>{const q=JSON.parse(o.body);if(q.op!=='scores')writes++;return response(scores())});h.mount('ScoreTab',{engagement:'A'});await flush();const save=button(edit(h,'current'),'保存');h.unmount();save.props.onClick();await flush();assert.equal(writes,0)});
for(const transition of ['refresh','A-B-A'])test('Score pending write remains locked across '+transition+' and settles into a fresh read',async()=>{const f=owned(),writes=[];let commit;const h=host((_u,o)=>{const q=JSON.parse(o.body);if(q.op==='scores')return Promise.resolve(response(dispatch(f.store,q)));writes.push(q);return new Promise(resolve=>commit=()=>resolve(response(dispatch(f.store,q))))});try{h.mount('ScoreTab',{engagement:f.a});await flush();button(h.render(),'+ 新增得分点').props.onClick();nodes(h.render()).find(n=>n.props?.placeholder==='名称（必填）').props.onChange({target:{value:'one-owned-add'}});const oldSave=button(h.render(),'保存');oldSave.props.onClick();assert.equal(writes.length,1);if(transition==='A-B-A'){h.render({engagement:f.b});await flush();h.render({engagement:f.a})}else h.render({engagement:f.a,refreshKey:1});await flush();assert.equal(button(h.render(),'+ 新增得分点').props.disabled,true);oldSave.props.onClick();assert.equal(writes.length,1);commit();await flush();h.render();await flush();const tree=h.render();assert.equal(button(tree,'+ 新增得分点').props.disabled,false);assert.match(text(tree),/one-owned-add/);assert.equal(dispatch(f.store,{op:'scores',engagement:f.a}).items.filter(x=>x.name==='one-owned-add').length,1)}finally{h.unmount();f.close()}});

test('Score displays the effective cap and explains conflicting declarations', async () => {
  const data = scores('Shared rule')
  Object.assign(data.items[0], { cap: 15, effective_cap: 10, cap_used: 8 })
  data.items.push({ ...data.items[0], id: 2, name: 'Disabled tier', cap: 7, enabled: false })
  data.summary.capConflicts = [{ rule: 9002, configuredCaps: [10, 15], effectiveCap: 10 }]
  const ui = host(async () => response(data))
  try {
    ui.mount('ScoreTab', { engagement: 'A' })
    await flush()
    const view = text(ui.render())
    assert.match(view, /上限 8\/10/)
    assert.match(view, /规则 9002.*10.*15.*暂按 10 分/)
    assert.match(view, /Disabled tier.*停用 · 配置上限 7 分/)
    assert.equal((view.match(/上限 8\/10/g) || []).length, 1)
    assert.doesNotMatch(view, /上限 8\/15/)
  } finally {
    ui.unmount()
  }
})

test('Chain displays an empty project’s cap conflict from the actual project endpoint', async () => {
  const f = owned()
  const extra = f.store.saveScorePoint(f.a, { name: 'Second tier', points: 5 })
  const db = f.store.db(f.a)
  const change = db.prepare("UPDATE score_point SET rule=9002, cap=? WHERE id=?")
  change.run(10, f.ap.id)
  change.run(15, extra.id)
  const requests = []
  const ui = host(async (_url, options) => {
    const req = JSON.parse(options.body)
    requests.push(req.op)
    return response(dispatch(f.store, req))
  })
  try {
    ui.mount('ChainTab', { engagement: f.a })
    await flush()
    assert.deepEqual(requests, ['scoreChain'])
    const view = text(ui.render())
    assert.match(view, /规则 9002.*10.*15.*暂按 10 分/)
    assert.match(view, /当前项目没有得分记录/)
  } finally {
    ui.unmount()
    f.close()
  }
})
