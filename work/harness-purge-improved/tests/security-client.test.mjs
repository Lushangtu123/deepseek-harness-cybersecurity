import test from 'node:test'
import assert from 'node:assert/strict'
import {createSecurityTab} from '../package/lib/redteam/personal-security-client.mjs'
const flush=()=>new Promise(setImmediate);
const memoryStorage=()=>{const values=new Map();return{get length(){return values.size},key:index=>[...values.keys()][index]??null,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key)}};
const memoryLocks=()=>{const held=new Set();return{async request(name,options,run){assert.deepEqual(options,{mode:'exclusive',ifAvailable:true});if(held.has(name))return run(null);held.add(name);try{return await run({name,mode:'exclusive'})}finally{held.delete(name)}}}};
const eventHub=()=>{const listeners=new Map();return{addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn)},removeEventListener(type,fn){listeners.get(type)?.delete(fn)},emit(type,event={}){for(const fn of listeners.get(type)??[])fn(event)},get count(){return[...listeners.values()].reduce((n,rows)=>n+rows.size,0)}}};
function host(api,{storage=memoryStorage(),locks=memoryLocks(),events=null,...lifecycle}={}){
 let cells=[],index=0,pending=[],dirty=false,tree,props={engagement:'a',refreshKey:0},unmounted=false,late=0;
 const React={createElement:(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity).filter(v=>v!==false&&v!==null&&v!==undefined)}),useState(initial){const at=index++;if(!cells[at])cells[at]={value:typeof initial==='function'?initial():initial};return[cells[at].value,value=>{if(unmounted){late++;return}cells[at].value=typeof value==='function'?value(cells[at].value):value;dirty=true}]},useRef(initial){const at=index++;return cells[at]||(cells[at]={current:initial})},useEffect(effect,deps){const at=index++,previous=cells[at];if(!previous||deps.some((value,i)=>value!==previous.deps[i]))pending.push(()=>{previous?.cleanup?.();cells[at]={deps,cleanup:effect()}})}};
 const Component=createSecurityTab(React,api,{storage,locks,events,...lifecycle});
 const render=(next=props)=>{props=next;for(let n=0;n<10;n++){dirty=false;index=0;tree=Component(props);const effects=pending;pending=[];effects.forEach(fn=>fn());if(!dirty)return tree}throw Error('Unsettled hooks')};
 return{render,unmount(){unmounted=true;cells.forEach(row=>row.cleanup?.())},get late(){return late}};
}
const text=n=>typeof n==='string'||typeof n==='number'?String(n):(n?.children||[]).map(text).join(' ');
const nodes=n=>n&&typeof n==='object'?[n,...(n.children||[]).flatMap(nodes)]:[];
const btn=(tree,label)=>{const result=nodes(tree).find(n=>n.type==='button'&&text(n)===label);assert.ok(result,'Missing '+label);return result};
const state=(engagement='a')=>({ok:true,engagement,profile:{revision:1,repoRoot:'/home/purge/workspace/test',url:null,expiresAt:new Date(Date.now()+86400000).toISOString(),tools:['semgrep','trivy']},tools:{semgrep:{ready:true,version:'test'},trivy:{ready:true,version:'test'},zap:{ready:false}},runs:[],findings:[],observedAt:new Date().toISOString()});
test('Two pages cannot retry the same pending operation concurrently or queue a later replay',async()=>{
 const storage=memoryStorage(),locks=memoryLocks(),writes=[];let finish;
 const api=async request=>{if(request.op==='securityStart'){writes.push(structuredClone(request));return new Promise(resolve=>{finish=resolve})}return state(request.engagement)};
 const a=host(api,{storage,locks}),b=host(api,{storage,locks});let first,second;
 try{
  a.render();await flush();first=btn(a.render(),'开始检查').props.onClick();await flush();b.render();await flush();second=btn(b.render(),'重试同一请求').props.onClick();await flush();
  const during=writes.length;finish({ok:true,run:{id:'one-synthetic-run',state:'completed'}});
  // A second pre-fix call would overwrite finish and leave the first unresolved;
  // fail before awaiting either call so the RED control cannot hang the runner.
  assert.equal(during,1,'Only the lock holder may send; the other page must not queue');
  await Promise.all([first,second]);await flush();assert.equal(writes.length,1);assert.equal(storage.length,0);assert.match(text(b.render()),/窗口|协调/);
 }finally{a.unmount();b.unmount()}
});
test('Storage notifications refresh the other page without replay or losing its draft',async()=>{
 const storage=memoryStorage(),locks=memoryLocks(),events=eventHub(),writes=[];let finish,revision=1,reads=0;
 const api=async request=>{if(request.op==='securityStart'){writes.push(request);return new Promise(resolve=>{finish=resolve})}reads++;return{...state(request.engagement),profile:{...state().profile,revision}}};
 const a=host(api,{storage,locks}),b=host(api,{storage,locks,events});
 try{
  a.render();b.render();await flush();let tree=b.render();nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/unsaved-window-b'}});b.render();
  const start=btn(a.render(),'开始检查').props.onClick();await flush();events.emit('storage',{key:'dsh-security-request-v1:a',storageArea:storage});await flush();tree=b.render();
  assert.match(text(tree),new RegExp(writes[0].requestId));assert.ok(btn(tree,'重试同一请求'));assert.ok(nodes(tree).some(n=>n.props.value==='/home/purge/workspace/unsaved-window-b'));
  revision=2;finish({ok:true,run:{id:'one-synthetic-run',state:'completed'}});await start;events.emit('storage',{key:'dsh-security-request-v1:a',storageArea:storage});await flush();tree=b.render();
  assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='重试同一请求'));assert.match(text(tree),/当前版本 2/);assert.ok(btn(tree,'采用最新范围（丢弃本地草稿）'));assert.ok(nodes(tree).some(n=>n.props.value==='/home/purge/workspace/unsaved-window-b'));assert.equal(writes.length,1);
  const before=reads;events.emit('storage',{key:'dsh-security-request-v1:another',storageArea:storage});await flush();assert.equal(reads,before);
 }finally{a.unmount();b.unmount();assert.equal(events.count,0)}
});
test('Explicit recovery of another page scope request keeps the local unsaved scope draft',async()=>{
 const storage=memoryStorage(),locks=memoryLocks();let request,saved=false;
 const api=async input=>{
  if(input.op==='securityScopeSave'){if(!request){request=structuredClone(input);saved=true;throw Error('lost reply')}assert.deepEqual(input,request);return{ok:true,profile:{...state().profile,revision:2,expiresAt:request.expiresAt}}}
  return{...state(input.engagement),profile:{...state().profile,revision:saved?2:1}};
 };
 const a=host(api,{storage,locks}),b=host(api,{storage,locks});try{
  a.render();b.render();await flush();let tree=b.render();nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/local-draft-b'}});b.render();
  tree=a.render();nodes(nodes(tree).find(n=>n.type==='label'&&text(n).includes('我确认上述目录'))).find(n=>n.type==='input').props.onChange({target:{checked:true}});await btn(a.render(),'保存范围').props.onClick();await btn(b.render(),'刷新').props.onClick();await btn(b.render(),'重试同一请求').props.onClick();tree=b.render();
  assert.equal(storage.length,0);assert.ok(nodes(tree).some(n=>n.props.value==='/home/purge/workspace/local-draft-b'));assert.ok(btn(tree,'采用最新范围（丢弃本地草稿）'));assert.match(text(tree),/当前版本 2/);
 }finally{a.unmount();b.unmount()}
});
test('Another page cannot discard an active request, and a rejected lock never exposes platform errors',async()=>{
 const storage=memoryStorage(),locks=memoryLocks();let finish;
 const api=async request=>request.op==='securityStart'?new Promise(resolve=>{finish=resolve}):state(request.engagement);
 const a=host(api,{storage,locks}),b=host(api,{storage,locks});
 try{
  a.render();await flush();const writing=btn(a.render(),'开始检查').props.onClick();await flush();b.render();await flush();let tree=b.render();nodes(tree).find(n=>n.props['aria-label']==='确认清除恢复提示').props.onChange({target:{checked:true}});tree=b.render();await btn(tree,'仅清除恢复提示').props.onClick();const remaining=storage.length;finish({ok:true,run:{id:'one-synthetic-run',state:'completed'}});await writing;
  assert.equal(remaining,1,'Clearing must acquire the same lock as sending');assert.equal(storage.length,0);
 }finally{a.unmount();b.unmount()}
 for(const locks of [null,{request:()=>Promise.reject(Error('PRIVATE_PLATFORM_ERROR'))}]){
  const writes=[],h=host(async request=>{if(request.op!=='securityStatus')writes.push(request);return state(request.engagement)},{locks});try{h.render();await flush();assert.equal(btn(h.render(),'开始检查').props.disabled,locks===null);await btn(h.render(),'开始检查').props.onClick();assert.equal(writes.length,0);assert.equal(btn(h.render(),'开始检查').props.disabled,true);assert.match(text(h.render()),/多窗口协调/);assert.doesNotMatch(text(h.render()),/PRIVATE_PLATFORM_ERROR/)}finally{h.unmount()}
 }
});
test('A full remount restores an uncertain request without replay and explicitly retries identical content',async()=>{
 const storage=memoryStorage(),starts=[];let uncertain=true;
 const api=async request=>{if(request.op==='securityStart'){starts.push(structuredClone(request));if(uncertain)throw Error('reply lost');return{ok:true,run:{id:'saved-run',state:'running'}}}return state(request.engagement)};
 let h=host(api,{storage});try{
  h.render();await flush();await btn(h.render(),'开始检查').props.onClick();assert.equal(starts.length,1);assert.equal(storage.length,1,'Persist before sending and keep an uncertain request');h.unmount();
  h=host(api,{storage});h.render();await flush();let tree=h.render();assert.equal(starts.length,1,'Mount must never replay a write');assert.equal(btn(tree,'开始检查').props.disabled,true);assert.match(text(tree),new RegExp(starts[0].requestId));assert.ok(btn(tree,'重试同一请求'));uncertain=false;
  await btn(tree,'重试同一请求').props.onClick();assert.deepEqual(starts,[starts[0],starts[0]]);assert.equal(storage.length,0,'Confirmed result removes only its receipt');
 }finally{h.unmount()}
});
test('Unavailable persistence fails closed before any mutation and does not pretend reload protection',async()=>{
 const writes=[],storage={getItem:()=>null,setItem:()=>{throw Error('quota PRIVATE')},removeItem:()=>{}};
 const h=host(async request=>{if(request.op==='securityStart')writes.push(request);return state(request.engagement)},{storage});try{
  h.render();await flush();await btn(h.render(),'开始检查').props.onClick();const tree=h.render();assert.equal(writes.length,0);assert.match(text(tree),/恢复记录.*保存|保存.*恢复记录/);assert.doesNotMatch(text(tree),/PRIVATE/);assert.equal(btn(tree,'开始检查').props.disabled,true);
 }finally{h.unmount()}
});
test('Project changes and remounts do not expose another project pending request',async()=>{
 const storage=memoryStorage(),writes=[];const api=async request=>{if(request.op==='securityStart'){writes.push(request);throw Error('reply lost')}return state(request.engagement)};
 const h=host(api,{storage});try{
  h.render();await flush();await btn(h.render(),'开始检查').props.onClick();const pending=writes[0];h.render({engagement:'b',refreshKey:0});await flush();let tree=h.render();assert.equal(btn(tree,'开始检查').props.disabled,false);assert.doesNotMatch(text(tree),new RegExp(pending.requestId));
  h.render({engagement:'a',refreshKey:0});await flush();tree=h.render();assert.equal(btn(tree,'开始检查').props.disabled,true);assert.match(text(tree),new RegExp(pending.requestId));assert.equal(writes.length,1);
 }finally{h.unmount()}
});
test('Retained start and retry handlers cannot send work after their project changes',async()=>{
 const storage=memoryStorage(),writes=[];const api=async request=>{if(request.op==='securityStart'){writes.push(request);throw Error('lost reply')}return state(request.engagement)};
 const h=host(api,{storage});try{
  h.render();await flush();const oldStart=btn(h.render(),'开始检查').props.onClick;h.render({engagement:'b',refreshKey:0});await flush();await oldStart();assert.equal(writes.length,0,'Old A start must not act while B is selected');
  h.render({engagement:'a',refreshKey:0});await flush();await btn(h.render(),'开始检查').props.onClick();const oldRetry=btn(h.render(),'重试同一请求').props.onClick;
  h.render({engagement:'b',refreshKey:0});await flush();await btn(h.render(),'开始检查').props.onClick();const count=writes.length;await oldRetry();assert.equal(writes.length,count,'Old A retry must not read B pending request');
 }finally{h.unmount()}
});
test('A retained refresh cannot restore a previous project receipt into the current project',async()=>{
 const storage=memoryStorage(),calls=[],h=host(async request=>{calls.push(request);if(request.op==='securityStart')throw Error('lost reply');return state(request.engagement)},{storage});try{
  h.render();await flush();await btn(h.render(),'开始检查').props.onClick();const oldRefresh=btn(h.render(),'刷新').props.onClick;h.render({engagement:'b',refreshKey:0});await flush();const count=calls.length;await oldRefresh();const tree=h.render();assert.equal(calls.length,count);assert.equal(btn(tree,'开始检查').props.disabled,false);assert.doesNotMatch(text(tree),/"engagement": "a"/);
 }finally{h.unmount()}
});
test('Malformed successful launch responses retain the durable request through remount',async()=>{
 for(const reply of [{ok:true},{ok:true,run:{id:'',state:'running'}},{ok:true,run:{id:'saved-run',state:'unrecognized'}}]){
  const storage=memoryStorage(),api=async request=>request.op==='securityStart'?reply:state(request.engagement);let h=host(api,{storage});try{
   h.render();await flush();await btn(h.render(),'开始检查').props.onClick();assert.equal(storage.length,1);h.unmount();h=host(api,{storage});h.render();await flush();assert.ok(btn(h.render(),'重试同一请求'));assert.equal(btn(h.render(),'开始检查').props.disabled,true);
  }finally{h.unmount()}
 }
});
test('Scope and review requests preserve complete original content across remount',async()=>{
 const finding={id:7,revision:2,tool:'semgrep',title:'Synthetic',rule:'fixture',location:'app.js:1',evidence:'synthetic',note:'',severity:'high',status:'unverified'};
 for(const op of ['securityScopeSave','securityReview']){
  const storage=memoryStorage(),writes=[];let uncertain=true;const api=async request=>{if(request.op===op){writes.push(structuredClone(request));if(uncertain)throw Error('reply lost');return op==='securityScopeSave'?{ok:true,profile:{...state().profile,revision:request.revision+1,repoRoot:'/home/purge/workspace/owned-reload',expiresAt:request.expiresAt}}:{ok:true,finding:{...finding,revision:request.revision+1,status:request.status,note:request.note}}}return{...state(request.engagement),findings:[finding]}};
  let h=host(api,{storage});try{
   h.render();await flush();let tree=h.render();if(op==='securityScopeSave'){nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge//workspace/ignored/../owned-reload/.'}});tree=h.render();nodes(nodes(tree).find(n=>n.type==='label'&&text(n).includes('我确认上述目录'))).find(n=>n.type==='input').props.onChange({target:{checked:true}});tree=h.render();await btn(tree,'保存范围').props.onClick()}else{nodes(tree).find(n=>n.type==='textarea').props.onChange({target:{value:'Synthetic review note preserving Unicode 中文'}});tree=h.render();await btn(tree,'确认发现').props.onClick()}
   assert.equal(writes.length,1);assert.equal(storage.length,1);h.unmount();h=host(api,{storage});h.render();await flush();tree=h.render();assert.match(text(tree),new RegExp(op));assert.equal(writes.length,1);uncertain=false;await btn(tree,'重试同一请求').props.onClick();assert.deepEqual(writes,[writes[0],writes[0]]);assert.equal(storage.length,0);
  }finally{h.unmount()}
 }
});
test('Corrupt, foreign, unsupported and oversized stored requests block fresh work and require explicit discard',async()=>{
 for(const raw of ['{',JSON.stringify({version:2,createdAt:Date.now(),request:{}}),JSON.stringify({version:1,createdAt:Date.now(),request:{op:['securityReview'],engagement:'a',requestId:'array-operation-1',id:7,revision:2,status:'confirmed',note:'Synthetic malformed operation'}}),JSON.stringify({version:1,createdAt:Date.now(),request:{op:'securityStart',engagement:'b',requestId:'foreign-request-1',profileRevision:1,tool:'semgrep'}}),'x'.repeat(16385)]){
  const storage=memoryStorage();storage.setItem('dsh-security-request-v1:a',raw);const writes=[],h=host(async request=>{if(request.op!=='securityStatus')writes.push(request);return state(request.engagement)},{storage});try{
   h.render();await flush();let tree=h.render();assert.equal(btn(tree,'开始检查').props.disabled,true);assert.match(text(tree),/恢复记录.*无效/);assert.equal(writes.length,0);assert.equal(btn(tree,'仅清除恢复提示').props.disabled,true);await btn(tree,'仅清除恢复提示').props.onClick();assert.equal(storage.length,1);
   nodes(tree).find(n=>n.props['aria-label']==='确认清除恢复提示').props.onChange({target:{checked:true}});tree=h.render();await btn(tree,'仅清除恢复提示').props.onClick();assert.equal(storage.length,0);assert.equal(writes.length,0);assert.equal(btn(h.render(),'开始检查').props.disabled,false);
  }finally{h.unmount()}
 }
});
test('Storage read failures never become an empty pending queue and a failed status read prevents discard',async()=>{
 const writes=[],bad={getItem:()=>{throw Error('PRIVATE')},setItem:()=>{},removeItem:()=>{throw Error('must not clear')}};
 const h=host(async request=>{if(request.op!=='securityStatus')writes.push(request);return state(request.engagement)},{storage:bad});try{h.render();await flush();const tree=h.render();assert.match(text(tree),/恢复记录无法读取/);assert.doesNotMatch(text(tree),/PRIVATE/);assert.equal(btn(tree,'开始检查').props.disabled,true);assert.equal(writes.length,0)}finally{h.unmount()}
 const storage=memoryStorage();storage.setItem('dsh-security-request-v1:a','{');const failed=host(async()=>{throw Error('status unavailable')},{storage});try{failed.render();await flush();const tree=failed.render();assert.equal(btn(tree,'仅清除恢复提示').props.disabled,true);assert.equal(nodes(tree).find(n=>n.props['aria-label']==='确认清除恢复提示').props.disabled,true);assert.equal(storage.length,1)}finally{failed.unmount()}
});
test('Late completion and stale discard preserve a replacement pending request',async()=>{
 const storage=memoryStorage();let complete;const h=host(async request=>request.op==='securityStart'?new Promise(resolve=>{complete=resolve}):state(request.engagement),{storage});try{
  h.render();await flush();const old=btn(h.render(),'开始检查').props.onClick();const key=storage.key(0),replacement=JSON.parse(storage.getItem(key));replacement.request.requestId='replacement-request-1';storage.setItem(key,JSON.stringify(replacement));complete({ok:true,run:{id:'original-run',state:'completed'}});await old;let tree=h.render();assert.match(text(tree),/replacement-request-1/);assert.equal(storage.length,1);
  nodes(tree).find(n=>n.props['aria-label']==='确认清除恢复提示').props.onChange({target:{checked:true}});tree=h.render();const remove=btn(tree,'仅清除恢复提示').props.onClick;replacement.request.requestId='replacement-request-2';storage.setItem(key,JSON.stringify(replacement));await remove();assert.equal(JSON.parse(storage.getItem(key)).request.requestId,'replacement-request-2');assert.match(text(h.render()),/记录已变化/);
 }finally{h.unmount()}
});
test('An old discard acknowledgment cannot clear a refreshed receipt or run during a later read',async()=>{
 const storage=memoryStorage();storage.setItem('dsh-security-request-v1:a','{');let finishRead,stall=false;const h=host(async request=>stall?new Promise(resolve=>{finishRead=()=>resolve(state(request.engagement))}):state(request.engagement),{storage});try{
  h.render();await flush();let tree=h.render();nodes(tree).find(n=>n.props['aria-label']==='确认清除恢复提示').props.onChange({target:{checked:true}});tree=h.render();const oldClear=btn(tree,'仅清除恢复提示').props.onClick;storage.setItem('dsh-security-request-v1:a','replacement');await btn(tree,'刷新').props.onClick();await oldClear();assert.equal(storage.getItem('dsh-security-request-v1:a'),'replacement');
  tree=h.render();nodes(tree).find(n=>n.props['aria-label']==='确认清除恢复提示').props.onChange({target:{checked:true}});tree=h.render();const clearBeforeRead=btn(tree,'仅清除恢复提示').props.onClick;stall=true;const reading=btn(tree,'刷新').props.onClick();await clearBeforeRead();assert.equal(storage.length,1);finishRead();await reading;
 }finally{h.unmount()}
});
const pagedState=request=>{
 const r=request.pages?.runs||{},f=request.pages?.findings||{},filters={tool:f.tool||'',status:f.status||'',severity:f.severity||'',search:f.search||''},filtered=Object.values(filters).some(Boolean),last=!!f.cursor;
 const findings=filtered?[]:(last?[1]:Array.from({length:50},(_,i)=>51-i)).map(id=>({id,revision:1,tool:'semgrep',title:'Finding '+id,rule:'fixture.rule',location:'fixture-'+id+'.js:1',evidence:'synthetic',note:'',severity:'medium',status:'unverified'}));
 return{...state(request.engagement),totalRuns:0,totalFindings:51,runs:[],findings,activeRun:null,comparisonRuns:[],pagination:{runs:{cursor:r.cursor??null,limit:r.limit??10,total:0,hasMore:false,nextCursor:null,filters:{tool:r.tool||'',state:r.state||''}},findings:{cursor:f.cursor??null,limit:f.limit??50,total:filtered?0:51,hasMore:!filtered&&!last,nextCursor:!filtered&&!last?'find-next':null,filters}}};
};
test('UI paginates findings independently, goes back, and retains unsaved scope while changing pages',async()=>{
 const calls=[],h=host(async request=>{calls.push(request);return pagedState(request)});try{
  h.render();await flush();let tree=h.render();assert.equal(btn(tree,'发现上一页').props.disabled,true);assert.equal(btn(tree,'发现下一页').props.disabled,false);
  nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/edited'}});tree=h.render();
  await btn(tree,'发现下一页').props.onClick();tree=h.render();assert.equal(calls.at(-1).pages.findings.cursor,'find-next');assert.equal(calls.at(-1).pages.runs.cursor,null);assert.match(text(tree),/Finding 1(?:\s|$)/);assert.doesNotMatch(text(tree),/Finding 51/);assert.match(text(tree),/第2页/);assert.ok(nodes(tree).some(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/edited'));
  await btn(tree,'发现上一页').props.onClick();tree=h.render();assert.equal(calls.at(-1).pages.findings.cursor,null);assert.match(text(tree),/Finding 51/);assert.equal(btn(tree,'发现上一页').props.disabled,true);
 }finally{h.unmount()}
});
test('Explicit and parent refresh start a new page window while keeping filters and unsaved scope',async()=>{
 const calls=[],h=host(async request=>{calls.push(request);return pagedState(request)});try{
  h.render();await flush();let tree=h.render();nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/edited'}});tree=h.render();await btn(tree,'发现下一页').props.onClick();tree=h.render();assert.equal(calls.at(-1).pages.findings.cursor,'find-next');
  await btn(tree,'刷新').props.onClick();tree=h.render();assert.equal(calls.at(-1).pages.findings.cursor,null);assert.equal(calls.at(-1).pages.runs.cursor,null);assert.equal(btn(tree,'发现上一页').props.disabled,true);assert.ok(nodes(tree).some(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/edited'));assert.match(text(tree),/Finding 51/);
  await btn(tree,'发现下一页').props.onClick();h.render({engagement:'a',refreshKey:1});await flush();tree=h.render();assert.equal(calls.at(-1).pages.findings.cursor,null);assert.equal(btn(tree,'发现上一页').props.disabled,true);
 }finally{h.unmount()}
});
test('Failed or mismatched page reads retain the last accepted page and disable writes',async()=>{
 for(const mode of ['throw','cursor','count']){
  const h=host(async request=>{const value=pagedState(request);if(request.pages?.findings.cursor){if(mode==='throw')throw Error('page unavailable');if(mode==='cursor')value.pagination.findings.cursor='foreign';if(mode==='count')value.pagination.findings.total=0}return value});try{
   h.render();await flush();let tree=h.render();await btn(tree,'发现下一页').props.onClick();tree=h.render();assert.match(text(tree),/page unavailable|资料无效/);assert.match(text(tree),/Finding 51/);assert.equal(btn(tree,'导出报告').props.disabled,true);assert.equal(btn(tree,'发现上一页').props.disabled,true);assert.equal(btn(tree,'发现下一页').props.disabled,true);
  }finally{h.unmount()}
 }
});
test('Changing a finding filter resets its cursor and literal search applies only on submit',async()=>{
 const calls=[],h=host(async request=>{calls.push(request);return pagedState(request)});try{
  h.render();await flush();let tree=h.render();await btn(tree,'发现下一页').props.onClick();tree=h.render();
  await nodes(tree).find(n=>n.type==='select'&&n.props['aria-label']==='发现工具').props.onChange({target:{value:'trivy'}});tree=h.render();assert.equal(calls.at(-1).pages.findings.cursor,null);assert.equal(calls.at(-1).pages.findings.tool,'trivy');assert.equal(btn(tree,'发现上一页').props.disabled,true);assert.match(text(tree),/匹配 0/);
  const count=calls.length;nodes(tree).find(n=>n.type==='input'&&n.props['aria-label']==='发现搜索').props.onChange({target:{value:'%_'}});tree=h.render();assert.equal(calls.length,count);await btn(tree,'搜索发现').props.onClick();assert.equal(calls.at(-1).pages.findings.search,'%_');
 }finally{h.unmount()}
});
test('Changing projects resets UI cursors and the global running task stays visible on filtered history',async()=>{
 const calls=[],h=host(async request=>{calls.push(request);const value=pagedState(request);value.activeRun={id:'active-run',tool:'semgrep',state:'running',complete:0,started_at:'2026-10-30T10:00:00.000Z',details:{}};return value});try{
  h.render();await flush();let tree=h.render();assert.match(text(tree),/active-run/);assert.equal(btn(tree,'取消当前任务').props.disabled,false);await btn(tree,'发现下一页').props.onClick();tree=h.render();assert.match(text(tree),/active-run/);
  h.render({engagement:'b',refreshKey:0});await flush();tree=h.render();assert.equal(calls.at(-1).engagement,'b');assert.equal(calls.at(-1).pages.findings.cursor,null);assert.equal(btn(tree,'发现上一页').props.disabled,true);
 }finally{h.unmount()}
});
test('Diagnostic-shaped uncertain mutation outcomes retain the exact request ID through refresh and retry',async()=>{
 for(const [code,stage] of [['RPC_TIMEOUT','wait'],['RPC_RESPONSE_ENCODING','encode'],['RPC_DISPATCH_FAILED','dispatch'],['UNKNOWN_CODE','dispatch']]){
  const starts=[],h=host(async request=>{if(request.op==='securityStart'){starts.push(request);return starts.length===1?{ok:false,error:'结果未确认',diagnostic:{requestId:'5e24e176-4b65-4023-a5ef-c4c7842e25f3',operation:'securityStart',stage,code,elapsedMs:10}}:{ok:true,run:{id:'retained-run',state:'running'}}}return state(request.engagement)});try{
   h.render();await flush();let tree=h.render();await btn(tree,'开始检查').props.onClick();tree=h.render();assert.ok(btn(tree,'重试同一请求'));await btn(tree,'刷新').props.onClick();tree=h.render();assert.equal(btn(tree,'开始检查').props.disabled,true);await btn(tree,'重试同一请求').props.onClick();tree=h.render();assert.equal(starts.length,2);assert.equal(starts[1].requestId,starts[0].requestId);assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='重试同一请求'));
  }finally{h.unmount()}
 }
});
test('A validated business rejection clears the saved receipt and allows a corrected fresh request',async()=>{
 const starts=[],h=host(async request=>{if(request.op==='securityStart'){starts.push(request);return starts.length===1?{ok:false,error:'范围已变化',diagnostic:{requestId:'5e24e176-4b65-4023-a5ef-c4c7842e25f3',operation:'securityStart',stage:'dispatch',code:'RPC_REJECTED',elapsedMs:2}}:{ok:true}}return state()});try{
  h.render();await flush();let tree=h.render();await btn(tree,'开始检查').props.onClick();tree=h.render();assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='重试同一请求'));await btn(tree,'刷新').props.onClick();tree=h.render();assert.equal(btn(tree,'开始检查').props.disabled,false);await btn(tree,'开始检查').props.onClick();assert.notEqual(starts[0].requestId,starts[1].requestId);
 }finally{h.unmount()}
});
test('Coverage diagnostics display source-free type and file, reject malformed nested fields and retain unknown legacy reasons',async()=>{
 const run={id:'diagnostic-run',tool:'semgrep',state:'partial',complete:0,started_at:'2026-10-29T12:00:00Z',details:{diagnostics:{total:1,items:[{code:'PartialParsing',path:'a.js',line:7}],truncated:false}}};
 for(const diagnostic of [run.details.diagnostics,{total:1,items:[{code:{bad:true},path:'a.js',line:7}],truncated:false},null]){
  const h=host(async()=>({...state(),runs:[{...run,details:diagnostic?{diagnostics:diagnostic}:{}}]}));try{h.render();await flush();const tree=h.render();if(diagnostic?.items[0].code?.bad){assert.match(text(tree),/资料无效/);assert.equal(btn(tree,'导出报告').props.disabled,true)}else if(diagnostic){assert.match(text(tree),/PartialParsing · a.js:7/);assert.match(text(tree),/扫描诊断 1 项/)}else assert.match(text(tree),/旧任务未保存具体覆盖诊断/)}finally{h.unmount()}
 }
});
test('An unavailable or foreign project response never becomes an empty successful audit',async()=>{
 for(const response of [{ok:false,error:'unavailable'},state('foreign')]){const h=host(async()=>response);h.render();await flush();const tree=h.render();assert.match(text(tree),/unavailable|资料无效/);assert.doesNotMatch(text(tree),/当前没有已收录发现/);assert.equal(btn(tree,'导出报告').props.disabled,true);h.unmount()}
});
test('Refreshing preserves unsaved scope and stale responses cannot update an unmounted project',async()=>{
 const h=host(async()=>state());h.render();await flush();let tree=h.render();nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/changed'}});h.render({engagement:'a',refreshKey:1});await flush();tree=h.render();assert.ok(nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/changed'));assert.equal(btn(tree,'开始检查').props.disabled,true);h.unmount();
 let done;const old=host(()=>new Promise(resolve=>{done=resolve}));old.render();old.unmount();done(state());await flush();assert.equal(old.late,0);
});
test('Uncertain launch has no automatic replay, blocks new work and retries the exact request ID',async()=>{
 const calls=[];const h=host(async request=>{calls.push(request);if(request.op==='securityStart')throw Error('offline');return state()});h.render();await flush();let tree=h.render();await btn(tree,'开始检查').props.onClick();tree=h.render();assert.equal(calls.filter(r=>r.op==='securityStart').length,1);assert.equal(btn(tree,'开始检查').props.disabled,true);const first=calls.find(r=>r.op==='securityStart');await btn(tree,'重试同一请求').props.onClick();assert.deepEqual(calls.filter(r=>r.op==='securityStart'),[first,first]);h.unmount();
});
test('Explicit revision rejection clears an uncertain receipt and allows a fresh action',async()=>{
 const h=host(async request=>request.op==='securityStart'?{ok:false,error:'范围已变化，请刷新'}:state());h.render();await flush();let tree=h.render();await btn(tree,'开始检查').props.onClick();tree=h.render();assert.match(text(tree),/范围已变化/);assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='重试同一请求'));await btn(tree,'刷新').props.onClick();tree=h.render();assert.equal(btn(tree,'开始检查').props.disabled,false);h.unmount();
});
test('Explicit runtime recheck preserves the scope draft and shows resource errors and DB age',async()=>{
 const calls=[];const h=host(async request=>{calls.push(request);const value=state();value.tools.trivy={ready:false,version:'test',reason:'漏洞数据库摘要不匹配',warning:'漏洞库已超过7天',database:{state:'stale',updatedAt:'2026-10-01T00:00:00Z',ageDays:28},checkedAt:'2026-10-29T22:00:00Z'};return value});h.render();await flush();let tree=h.render();nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/draft'}});tree=h.render();await btn(tree,'重新核对运行资源').props.onClick();tree=h.render();assert.equal(calls.at(-1).refreshRuntime,true);assert.match(text(tree),/漏洞数据库摘要不匹配/);assert.match(text(tree),/2026-10-01/);assert.match(text(tree),/超过7天/);assert.ok(nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/draft'));h.unmount();
});
test('Database update guide names the Mac launcher and displays the last controlled update result',async()=>{
 const h=host(async()=>{const value=state();value.tools.trivy.lastUpdate={state:'current',checkedAt:'2026-10-29T22:00:00Z'};return value});h.render();await flush();let tree=h.render();btn(tree,'漏洞库更新').props.onClick();tree=h.render();assert.match(text(tree),/Mac/);assert.match(text(tree),/选项 9/);assert.match(text(tree),/2026-10-29T22:00:00Z/);h.unmount();
});
test('The rule card shows the verified local policy version and scope without promising completeness',async()=>{
 const h=host(async()=>{const value=state();value.tools.semgrep.rules={version:'local-reviewed-2',count:16,languages:['javascript','python','typescript']};return value});h.render();await flush();const tree=h.render();assert.match(text(tree),/local-reviewed-2/);assert.match(text(tree),/16 条/);assert.match(text(tree),/python/);assert.match(text(tree),/人工复核/);h.unmount();
});
const comparableState=()=>({...state(),runs:[{id:'new-run-0002',tool:'semgrep',state:'completed',complete:1,started_at:'2026-10-29T12:00:00Z',details:{comparisonSnapshot:{available:true}}},{id:'old-run-0001',tool:'semgrep',state:'completed',complete:1,started_at:'2026-10-29T11:00:00Z',details:{comparisonSnapshot:{available:true}}}]});
const comparisonResult=(request)=>({ok:true,engagement:request.engagement,baseRunId:request.baseRunId,currentRunId:request.currentRunId,available:true,summary:{added:1,persisting:2,notSeen:3,uncovered:4},items:{added:[],persisting:[],notSeen:[],uncovered:[]},notice:'未再次命中不等于已修复',truncated:false,markdown:'# comparison'});

async function downloads(check){
 const originalDocument=globalThis.document,originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL,files=[],blobs=[];
 globalThis.document={createElement:()=>({click(){files.push({name:this.download,href:this.href})}})};
 URL.createObjectURL=blob=>{blobs.push(blob);return'blob:security-download-fixture'};URL.revokeObjectURL=()=>{};
 try{await check({files,blobs})}finally{if(originalDocument===undefined)delete globalThis.document;else globalThis.document=originalDocument;URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke}
}
test('Audit export refuses foreign project and malformed success payloads before creating a download',async()=>downloads(async({files,blobs})=>{
 for(const report of [{ok:true,engagement:'foreign',markdown:'# wrong project'},{ok:1,engagement:'a',markdown:'# invalid flag'},{ok:true,engagement:'a',markdown:123}]){
  const h=host(async request=>request.op==='securityReport'?report:state());try{h.render();await flush();let tree=h.render();await btn(tree,'导出报告').props.onClick();tree=h.render();assert.equal(files.length,0);assert.equal(blobs.length,0);assert.match(text(tree),/报告未确认/)}finally{h.unmount()}
 }
}));
test('Refreshing invalidates the pending audit download and the previous rendered export callback',async()=>downloads(async({files})=>{
 let finish,calls=0;const h=host(async request=>{if(request.op==='securityReport'){calls++;return new Promise(resolve=>{finish=()=>resolve({ok:true,engagement:'a',markdown:'# old read'})})}return state()});
 try{h.render();await flush();let tree=h.render();const oldExport=btn(tree,'导出报告').props.onClick,pending=oldExport();await btn(tree,'刷新').props.onClick();finish();await pending;assert.equal(files.length,0);await oldExport();assert.equal(calls,1,'Old callback must not send another request');tree=h.render();const fresh=btn(tree,'导出报告').props.onClick();finish();await fresh;assert.equal(files.length,1);assert.equal(files[0].name,'security-audit-a.md');
 }finally{h.unmount()}
}));
test('Audit export locks repeated same-render clicks and releases only its own pending request',async()=>downloads(async({files,blobs})=>{
 let finish,calls=0;const h=host(async request=>{if(request.op==='securityReport'){calls++;return new Promise(resolve=>{finish=()=>resolve({ok:true,engagement:'a',markdown:'# verified report'})})}return state()});
 try{h.render();await flush();let tree=h.render();const click=btn(tree,'导出报告').props.onClick,pending=click(),duplicate=click();assert.equal(calls,1);tree=h.render();assert.equal(btn(tree,'正在导出…').props.disabled,true);finish();await Promise.all([pending,duplicate]);tree=h.render();assert.equal(btn(tree,'导出报告').props.disabled,false);assert.equal(files.length,1);assert.equal(await blobs[0].text(),'# verified report');assert.equal(blobs[0].type,'text/markdown;charset=utf-8')
 }finally{h.unmount()}
}));
test('A late old export failure cannot clear a newer export lock or replace current page errors',async()=>downloads(async({files})=>{
 const pending=[];let calls=0;const h=host(request=>request.op==='securityReport'?(calls++,new Promise((resolve,reject)=>pending.push({resolve,reject}))):Promise.resolve(state()));
 try{h.render();await flush();let tree=h.render();const first=btn(tree,'导出报告').props.onClick();h.render({engagement:'a',refreshKey:1});await flush();tree=h.render();const second=btn(tree,'导出报告').props.onClick();pending[0].reject(Error('OLD_PRIVATE_ERROR'));await first;tree=h.render();assert.doesNotMatch(text(tree),/OLD_PRIVATE_ERROR/);assert.equal(btn(tree,'正在导出…').props.disabled,true);pending[1].resolve({ok:true,engagement:'a',markdown:'# new report'});await second;assert.equal(files.length,1);assert.equal(calls,2)
 }finally{h.unmount()}
}));
test('The comparison UI sends a read-only exact pair and keeps unknown history distinct from empty changes',async()=>{
 const calls=[];const h=host(async request=>{calls.push(request);return request.op==='securityCompare'?{...comparisonResult(request),available:false,reason:'旧任务没有完整扫描快照'}:comparableState()});h.render();await flush();let tree=h.render();await btn(tree,'对比所选任务').props.onClick();tree=h.render();assert.deepEqual(calls.at(-1),{op:'securityCompare',engagement:'a',baseRunId:'old-run-0001',currentRunId:'new-run-0002'});assert.match(text(tree),/旧任务没有完整扫描快照/);assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='下载对比报告'));h.unmount();
});
test('A stale comparison cannot appear in a new project or after its selected pair changes',async()=>{
 let finish;const h=host(async request=>request.op==='securityCompare'?new Promise(resolve=>{finish=()=>resolve(comparisonResult(request))}):{...comparableState(),engagement:request.engagement});h.render();await flush();let tree=h.render();const pending=btn(tree,'对比所选任务').props.onClick();h.render({engagement:'b',refreshKey:0});finish();await pending;await flush();tree=h.render();assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='下载对比报告'));h.unmount();
});
test('Changing the exact pair invalidates an in-flight comparison and malformed counters remain unconfirmed',async()=>{
 let finish;const h=host(async request=>request.op==='securityCompare'?new Promise(resolve=>{finish=()=>resolve(comparisonResult(request))}):comparableState());h.render();await flush();let tree=h.render();const pending=btn(tree,'对比所选任务').props.onClick();tree=h.render();nodes(tree).find(n=>n.type==='select'&&n.props.value==='old-run-0001').props.onChange({target:{value:'new-run-0002'}});finish();await pending;tree=h.render();assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='下载对比报告'));h.unmount();
 const bad=host(async request=>request.op==='securityCompare'?{...comparisonResult(request),summary:{added:-1,persisting:0,notSeen:0,uncovered:0}}:comparableState());bad.render();await flush();tree=bad.render();await btn(tree,'对比所选任务').props.onClick();tree=bad.render();assert.match(text(tree),/对比结果未确认/);assert.ok(!nodes(tree).some(n=>n.type==='button'&&text(n)==='下载对比报告'));bad.unmount();
});

const statusFinding=()=>({id:1,revision:1,tool:'semgrep',rule:'test.rule',title:'Last verified fixture',severity:'high',location:'app.py:1',evidence:'Synthetic evidence',status:'unverified',note:''});
test('Malformed nested audit records are rejected before rendering or offering record actions',async()=>{
 const cases=[
  v=>{v.runs=[null]},v=>{v.runs=[{...comparableState().runs[0],tool:{}}]},v=>{v.runs=[{...comparableState().runs[0],id:123}]},v=>{v.runs=[{...comparableState().runs[0],complete:'1'}]},
  v=>{v.findings=[null]},v=>{v.findings=[{...statusFinding(),title:{}}]},v=>{v.findings=[{...statusFinding(),revision:0}]},v=>{v.findings=[{...statusFinding(),note:[]}]},
  v=>{v.profile.tools='semgrep'},v=>{v.profile.revision='1'},v=>{v.profile.expiresAt='not-a-date'},v=>{v.profile.tools=['semgrep','semgrep']},
  v=>{v.tools=[]},v=>{v.tools.semgrep.ready='yes'},v=>{v.tools.semgrep.rules={version:'v2',count:16,languages:'python'}},v=>{v.tools.semgrep.rules={version:{},count:16,languages:['python']}},v=>{v.tools.trivy.database={updatedAt:'2026-10-29T00:00:00Z',ageDays:{}}},v=>{v.tools.trivy.lastUpdate={state:{},checkedAt:'2026-10-29T00:00:00Z'}},v=>{v.observedAt={}}
 ];
 for(const change of cases){const value=state();change(value);const h=host(async()=>value);try{h.render();await flush();const tree=h.render();assert.match(text(tree),/资料无效|未确认/);assert.equal(btn(tree,'导出报告').props.disabled,true);assert.ok(!nodes(tree).some(n=>n.type==='button'&&['保存范围','开始检查','确认发现'].includes(text(n))&&!n.props.disabled))}finally{h.unmount()}}
});
test('Duplicate records, impossible totals and oversized audit pages remain unconfirmed',async()=>{
 const cases=[v=>{v.runs=Array(31).fill(comparableState().runs[0])},v=>{v.runs=[comparableState().runs[0],comparableState().runs[0]]},v=>{v.findings=[statusFinding(),statusFinding()]},v=>{v.totalFindings=-1},v=>{v.totalRuns='0'},v=>{v.totalFindings=1},v=>{v.runs=comparableState().runs;v.totalRuns=1}];
 for(const change of cases){const value=state();change(value);const h=host(async()=>value);try{h.render();await flush();const tree=h.render();assert.match(text(tree),/资料无效|未确认/);assert.equal(btn(tree,'导出报告').props.disabled,true)}finally{h.unmount()}}
});
test('Invalid refresh preserves the last verified records and scope draft, pauses writes and resumes after a valid read',async()=>{
 let invalid=false;const calls=[];const h=host(async request=>{calls.push(request);const v=state();v.findings=[statusFinding()];if(invalid)v.runs=[null];return v});
 try{h.render();await flush();let tree=h.render();nodes(tree).find(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/unsaved'}});tree=h.render();invalid=true;await btn(tree,'刷新').props.onClick();tree=h.render();assert.match(text(tree),/上次成功读取/);assert.match(text(tree),/Last verified fixture/);assert.ok(nodes(tree).some(n=>n.type==='input'&&n.props.value==='/home/purge/workspace/unsaved'));assert.equal(btn(tree,'导出报告').props.disabled,true);assert.equal(btn(tree,'确认发现').props.disabled,true);assert.equal(calls.filter(v=>v.op!=='securityStatus').length,0);invalid=false;await btn(tree,'刷新').props.onClick();tree=h.render();assert.doesNotMatch(text(tree),/当前资料未确认/);assert.equal(btn(tree,'导出报告').props.disabled,false)}finally{h.unmount()}
});
test('Legacy optional totals and unknown string states remain displayable with typed runtime metadata',async()=>{
 const value=state();value.profile=null;value.findings=[{...statusFinding(),status:'future-status',severity:'future-severity'}];value.runs=[{...comparableState().runs[0],state:'future-state',details:{}}];value.tools.semgrep.rules={version:'local-reviewed-2',count:16,languages:['python','javascript']};value.tools.trivy={ready:false,version:null,reason:'维护未完成',database:{state:'unknown',updatedAt:null,nextUpdate:null,ageDays:null},checkedAt:'2026-10-29T00:00:00Z',cached:false};const h=host(async()=>value);
 try{h.render();await flush();const tree=h.render();assert.doesNotMatch(text(tree),/资料无效|当前资料未确认/);assert.match(text(tree),/future-status/);assert.match(text(tree),/future-state/);assert.match(text(tree),/维护未完成/);assert.equal(btn(tree,'导出报告').props.disabled,false)}finally{h.unmount()}
});
test('Array-shaped tool identifiers never pass string-key coercion into rendered or actionable records',async()=>{
 for(const change of [v=>{v.runs=[{...comparableState().runs[0],tool:['semgrep']}]},v=>{v.profile.tools=[['semgrep']]},v=>{v.findings=[{...statusFinding(),tool:['semgrep']}] }]){
  const value=state();change(value);const h=host(async()=>value);try{h.render();await flush();const tree=h.render();assert.match(text(tree),/资料无效|未确认/);assert.equal(btn(tree,'导出报告').props.disabled,true)}finally{h.unmount()}
 }
});
test('Prototype-named unknown statuses stay literal text rather than inherited React children',async()=>{
 for(const status of ['__proto__','constructor','toString']){
  const value=state();value.findings=[{...statusFinding(),status}];value.runs=[{...comparableState().runs[0],state:status}];value.tools.trivy.lastUpdate={state:status,checkedAt:'2026-10-29T00:00:00Z'};const h=host(async()=>value);
  try{h.render();await flush();const tree=h.render(),badge=nodes(tree).find(n=>n.type==='span'&&n.props.className==='rts-state');assert.equal(badge.children[0],status);assert.match(text(tree),/上次维护：未确认/);assert.doesNotMatch(text(tree),/\[object Object\]|native code/)}finally{h.unmount()}
 }
});
const packageSubjectFixture=()=>({kind:'package',name:'fixture-alpha',version:'1.2',path:'nested/package',purl:'pkg:pypi/fixture-alpha@1.2',key:'a'.repeat(64),family:'b'.repeat(64)});
test('Package identity appears beside the CVE and legacy Trivy rows disclose missing package history',async()=>{
 const value=state();value.findings=[{...statusFinding(),tool:'trivy',rule:'CVE-2026-0000',subject:packageSubjectFixture(),identityVersion:1},{...statusFinding(),id:2,tool:'trivy',subject:null,identityVersion:0}];const h=host(async()=>value);
 try{h.render();await flush();const tree=h.render();assert.match(text(tree),/依赖包：fixture-alpha@1.2/);assert.match(text(tree),/nested\/package/);assert.match(text(tree),/旧记录未区分依赖包身份/);assert.match(text(tree),/CVE-2026-0000/)}finally{h.unmount()}
});
test('Malformed package subjects never reach the audit page or comparison display',async()=>{
 for(const subject of ['raw-json',{...packageSubjectFixture(),name:{}},{...packageSubjectFixture(),key:'bad'}]){
  const value=state();value.findings=[{...statusFinding(),tool:'trivy',subject,identityVersion:1}];const h=host(async()=>value);try{h.render();await flush();const tree=h.render();assert.match(text(tree),/资料无效/);assert.equal(btn(tree,'导出报告').props.disabled,true)}finally{h.unmount()}
 }
 const h=host(async request=>request.op==='securityCompare'?{...comparisonResult(request),items:{added:[{rule:'CVE-2026-0000',title:'test',severity:'high',location:'requirements.txt',subject:{...packageSubjectFixture(),path:{}}}],persisting:[],notSeen:[],uncovered:[]}}:comparableState());try{h.render();await flush();let tree=h.render();await btn(tree,'对比所选任务').props.onClick();tree=h.render();assert.match(text(tree),/对比结果未确认/)}finally{h.unmount()}
});

test('Named ZAP sessions save and recover only the profile name, and mismatched acknowledgements remain uncertain',async()=>{
 const storage=memoryStorage();let saved=null,writes=[],mismatch=false;
 const api=async request=>{if(request.op==='securityScopeSave'){writes.push(structuredClone(request));saved={...state().profile,...request,revision:2};delete saved.confirm;delete saved.op;delete saved.engagement;delete saved.requestId;return{ok:true,profile:{...saved,...(mismatch?{authProfile:'different-profile'}:{})}}}return{...state(),profile:saved||{...state().profile,tools:['zap'],url:'http://127.0.0.1:18780'}}};
 const h=host(api,{storage});try{h.render();await flush();let tree=h.render();let label=nodes(tree).find(n=>n.type==='label'&&text(n).includes('ZAP 会话配置名'));assert.ok(label);const input=nodes(label).find(n=>n.type==='input');input.props.onChange({target:{value:'local-login-lab'}});tree=h.render();nodes(nodes(tree).find(n=>n.type==='label'&&text(n).includes('我确认上述目录'))).find(n=>n.type==='input').props.onChange({target:{checked:true}});await btn(h.render(),'保存范围').props.onClick();assert.equal(writes[0].authProfile,'local-login-lab');assert.equal(storage.length,0);assert.ok(!JSON.stringify(writes).includes('Cookie'));assert.match(text(h.render()),/私有会话|私有配置/);
 // Change only the session selection; the receipt must compare this field too.
 tree=h.render();label=nodes(tree).find(n=>n.type==='label'&&text(n).includes('ZAP 会话配置名'));nodes(label).find(n=>n.type==='input').props.onChange({target:{value:'second-login'}});tree=h.render();nodes(nodes(tree).find(n=>n.type==='label'&&text(n).includes('我确认上述目录'))).find(n=>n.type==='input').props.onChange({target:{checked:true}});mismatch=true;await btn(h.render(),'保存范围').props.onClick();assert.equal(storage.length,1);assert.match(text(h.render()),/未确认/);
 }finally{h.unmount()}
});
test('Authentication metadata is displayed with pre/post limits and malformed or secret-bearing shapes pause writes',async()=>{
 const auth={version:1,profile:'local-login-lab',revision:'879b1b08-0a7d-4f84-9f1d-d50cb7f94072',state:'verified',verification:'controller-and-zap-before-after',before:true,after:true,scannerBefore:true,scannerAfter:true,checkedRequests:2};let metadata=auth;
 const h=host(async()=>({...state(),runs:[{id:'auth-run',tool:'zap',state:'completed',complete:1,started_at:new Date().toISOString(),details:{authentication:metadata}}]}));try{h.render();await flush();assert.match(text(h.render()),/认证.*前后|前后.*认证/);assert.match(text(h.render()),/持续/);metadata={...auth,value:'PRIVATE_SESSION_CANARY'};await btn(h.render(),'刷新').props.onClick();assert.match(text(h.render()),/未确认|无效/);assert.ok(btn(h.render(),'开始检查').props.disabled);assert.doesNotMatch(text(h.render()),/PRIVATE_SESSION_CANARY/)}finally{h.unmount()}
});
test('Limited parser text checks remain visibly partial and malformed supplement counters pause actions',async()=>{
 let summary={version:1,policy:'parser-text-1',candidateFiles:2,checkedFiles:1,skippedFiles:1,hints:1,truncated:false};const h=host(async()=>({...state(),runs:[{id:'parser-gap',tool:'semgrep',state:'partial',complete:0,started_at:new Date().toISOString(),details:{supplemental:summary,diagnostics:{total:1,items:[{code:'PartialParsing',path:'gap.mjs',line:1}],truncated:false}}}]}));try{h.render();await flush();let tree=h.render();assert.match(text(tree),/有限文本补查/);assert.match(text(tree),/语义.*缺口|解析缺口/);assert.match(text(tree),/PartialParsing/);summary={...summary,checkedFiles:3};await btn(tree,'刷新').props.onClick();tree=h.render();assert.ok(btn(tree,'开始检查').props.disabled);assert.match(text(tree),/未确认|无效/)}finally{h.unmount()}
});

test('Session expiry reminders distinguish local configuration from login proof and keep expired ZAP disabled',async()=>{
 let metadata={version:1,profile:'local-login',revision:'879b1b08-0a7d-4f84-9f1d-d50cb7f94072',state:'expiring',expiresAt:new Date(Date.now()+120000).toISOString(),checkedAt:new Date().toISOString()};const writes=[];
 const h=host(async request=>{if(request.op==='securityStart')writes.push(request);const value=state();return{...value,profile:{...value.profile,url:'http://127.0.0.1:18080',authProfile:'local-login',tools:['zap']},tools:{...value.tools,zap:{ready:true,version:'fixture'}},authSession:metadata}});try{
  h.render();await flush();let tree=h.render();assert.match(text(tree),/会话配置即将到期/);assert.match(text(tree),/未探测.*登录|未验证.*登录/);assert.equal(nodes(tree).filter(n=>n.type==='button'&&text(n)==='开始检查').at(-1).props.disabled,false);
  await btn(tree,'重新导入说明').props.onClick();assert.match(text(h.render()),/renew-session local-login new-session/);assert.match(text(h.render()),/原配置保留/);
  metadata={...metadata,state:'expired',expiresAt:new Date(Date.now()-1000).toISOString(),checkedAt:new Date().toISOString()};await btn(h.render(),'刷新').props.onClick();tree=h.render();assert.match(text(tree),/会话配置已过期/);const start=nodes(tree).filter(n=>n.type==='button'&&text(n)==='开始检查').at(-1);assert.equal(start.props.disabled,true);await start.props.onClick();assert.equal(writes.length,0);
  metadata={...metadata,value:'PRIVATE_STATUS_CANARY'};await btn(tree,'刷新').props.onClick();tree=h.render();assert.match(text(tree),/无效|未确认/);assert.doesNotMatch(text(tree),/PRIVATE_STATUS_CANARY/);
 }finally{h.unmount()}
});

test('Visible resume aborts stale status reads, blocks retained writes and preserves scope drafts',async()=>{
 const events=eventHub(),document=eventHub(),requests=[];document.visibilityState='visible';let finish,signal,hold=false;
 const page=host(async(request,options)=>{requests.push(request.op);if(hold&&request.op==='securityStatus'){signal=options?.signal;return new Promise(resolve=>finish=resolve)}return state(request.engagement)},{events,document});
 try{
  page.render();await flush();let tree=page.render(),oldStart=btn(tree,'开始检查').props.onClick;
  nodes(tree).find(n=>n.props.value==='/home/purge/workspace/test').props.onChange({target:{value:'/home/purge/workspace/resume-draft'}});page.render();
  hold=true;const pending=btn(page.render(),'刷新').props.onClick();await flush();const previous=finish;
  document.visibilityState='hidden';document.emit('visibilitychange');assert.equal(signal?.aborted,true);await oldStart();assert.equal(requests.filter(x=>x==='securityStart').length,0);
  document.visibilityState='visible';document.emit('visibilitychange');await flush();const current=finish;previous({...state(),profile:{...state().profile,revision:20}});await pending;await flush();assert.doesNotMatch(text(page.render()),/当前版本 20/);
  current({...state(),profile:{...state().profile,revision:2}});await flush();tree=page.render();assert.match(text(tree),/当前版本 2/);assert.ok(nodes(tree).some(n=>n.props.value==='/home/purge/workspace/resume-draft'));assert.equal(requests.filter(x=>x!=='securityStatus').length,0);
 }finally{page.unmount();assert.equal(events.count,0);assert.equal(document.count,0)}
});
test('Nine-hour clock gaps and bounded read failures recover through one read-only heartbeat without replay',async()=>{
 const events=eventHub(),document=eventHub(),callbacks=new Map(),storage=memoryStorage(),requests=[];document.visibilityState='visible';let clock=Date.now(),fail=false,hold=false,finish;
 const timers={setInterval(fn,ms){const token={};callbacks.set(token,{fn,ms});return token},clearInterval(token){callbacks.delete(token)}};
 const page=host(async request=>{requests.push(request.op);if(request.op==='securityStart')throw Error('synthetic uncertain response');if(fail)throw Error('synthetic bounded read failure');if(hold)return new Promise(resolve=>finish=resolve);return state(request.engagement)},{events,document,timers,now:()=>clock,storage});
 try{
  page.render();await flush();await btn(page.render(),'开始检查').props.onClick();const receipt=storage.getItem('dsh-security-request-v1:a');assert.ok(receipt);
  const heartbeat=[...callbacks.values()].find(x=>x.ms===30000);assert.ok(heartbeat,'A lifecycle heartbeat must exist even with no running scan');
  fail=true;clock+=9*3600000;heartbeat.fn();await flush();assert.match(text(page.render()),/synthetic bounded read failure/);assert.equal(storage.getItem('dsh-security-request-v1:a'),receipt);
  fail=false;hold=true;clock+=30000;heartbeat.fn();await flush();const count=requests.length;clock+=30000;heartbeat.fn();assert.equal(requests.length,count,'A slow read must not be starved by automatic polling');
  hold=false;finish(state());await flush();assert.doesNotMatch(text(page.render()),/synthetic bounded read failure/);assert.match(text(page.render()),/恢复未确认操作/);assert.equal(storage.getItem('dsh-security-request-v1:a'),receipt);assert.equal(requests.filter(x=>x==='securityStart').length,1);
  const before=requests.length;clock-=3600000;heartbeat.fn();await flush();assert.equal(requests.length,before+1,'A backwards wall clock is also a resume signal');
 }finally{page.unmount();assert.equal(callbacks.size,0)}
});
test('Page restoration refreshes selected session metadata without automatically retrying a write',async()=>{
 const events=eventHub(),document=eventHub(),callbacks=new Map(),requests=[];document.visibilityState='visible';let expired=false;
 const timers={setInterval(fn,ms){const token={};callbacks.set(token,{fn,ms});return token},clearInterval(token){callbacks.delete(token)}};
 const page=host(async request=>{requests.push(request.op);return{...state(),profile:{...state().profile,url:'http://127.0.0.1:19001',tools:['zap'],authProfile:'local-login'},authSession:{version:1,profile:'local-login',revision:'12345678-1234-4123-8123-123456789abc',state:expired?'expired':'expiring',expiresAt:new Date(Date.now()+(expired?-10000:100000)).toISOString(),checkedAt:new Date().toISOString()}}},{events,document,timers});
 try{page.render();await flush();assert.match(text(page.render()),/会话配置即将到期/);expired=true;[...callbacks.values()].find(x=>x.ms===30000).fn();await flush();assert.match(text(page.render()),/会话配置已过期/);const before=requests.length;events.emit('pageshow',{persisted:true});await flush();assert.equal(requests.length,before+1);assert.ok(requests.every(x=>x==='securityStatus'))}finally{page.unmount()}
});
test('A completed old-project mutation releases the shared busy state without changing the new project',async()=>{
 let finish;const writes=[],page=host(async request=>{if(request.op==='securityStart'){writes.push(request.engagement);return new Promise(resolve=>finish=resolve)}return state(request.engagement)});
 try{page.render();await flush();const pending=btn(page.render(),'开始检查').props.onClick();await flush();page.render({engagement:'b',refreshKey:0});await flush();finish({ok:true,run:{id:'old-project-run',state:'completed'}});await pending;await flush();const tree=page.render();assert.equal(btn(tree,'开始检查').props.disabled,false);assert.deepEqual(writes,['a']);assert.match(text(tree),/当前版本 1/)}finally{page.unmount()}
});
test('Review checklist displays observed and manual items but rejects a foreign project checklist',async()=>{
 const review={version:1,engagement:'a',scopeRevision:1,canStartTools:['semgrep'],blockers:[],checks:[{id:'code',label:'代码检查',tool:'semgrep',state:'partial',runId:'run-1'},{id:'authorization',label:'角色与越权',tool:null,state:'manual',runId:null}],complianceClaim:false,notice:'未完成手工验证'};let current=review;const mounted=host(async()=>({...state(),review:current}));try{mounted.render();await flush();assert.match(text(mounted.render()),/审查预检与覆盖清单/);assert.match(text(mounted.render()),/角色与越权.*待人工验证/);current={...review,engagement:'foreign'};mounted.render({engagement:'a',refreshKey:1});await flush();assert.doesNotMatch(text(mounted.render()),/角色与越权/)}finally{mounted.unmount()}
});
