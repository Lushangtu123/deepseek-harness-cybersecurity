import test from 'node:test';import assert from 'node:assert/strict';
const module=await import('../package/lib/redteam/personal-security-client.mjs');
const nodes=n=>n&&typeof n==='object'?[n,...(n.children??[]).flatMap(nodes)]:[];
const text=n=>typeof n==='string'?n:(n?.children??[]).map(text).join('');
test('Joint panel retains an uncertain startup request and recovers it with read-only status, without replay',async()=>{
 assert.equal(typeof module.createJointPanel,'function','Joint panel is missing');const cells=[];let index=0;const stored=new Map(),calls=[];
 const storage={getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
 const React={createElement:(type,props,...children)=>({type,props:props??{},children:children.flat(Infinity).filter(v=>v!==false&&v!=null)}),useState:v=>{const at=index++;if(!cells[at])cells[at]={value:typeof v==='function'?v():v};return[cells[at].value,n=>{cells[at].value=typeof n==='function'?n(cells[at].value):n}]},useRef:v=>{const at=index++;return cells[at]??(cells[at]={current:v})},useEffect:()=>{index++}};
 const task={id:'joint-task-0001',engagement:'fixture',state:'running',scopeRevision:1,steps:[],snapshot:null,findings:0,cleanupVerified:false};
 const api=async r=>{calls.push(r);if(r.action==='plan')return{ok:true,engagement:'fixture',profileRevision:1,availableSteps:['semgrep'],kaliAllowed:false};if(r.action==='start')throw Error('lost reply');return{ok:true,engagement:'fixture',task:r.requestId?task:null,requestState:r.requestId?'accepted':'unknown'}};
 const Component=module.createJointPanel(React,api,{storage:()=>storage,exclusive:async(_e,fn)=>fn()});const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 const click=async label=>{const button=nodes(render()).find(n=>n.type==='button'&&text(n)===label);assert.ok(button,'Missing '+label);await button.props.onClick()};
 await click('核对联合范围与原任务');await click('启动联合审查');assert.equal(calls.filter(r=>r.action==='start').length,1);assert.equal(stored.size,1);await click('核对联合范围与原任务');assert.equal(calls.filter(r=>r.action==='start').length,1);assert.ok(calls.some(r=>r.action==='status'&&r.requestId));assert.ok(text(render()).includes(task.id));
});

test('A paid PentAGI step is available after consent but never preselected by refresh',async()=>{
 const cells=[];let index=0;const React={createElement:(type,props,...children)=>({type,props:props??{},children:children.flat(Infinity).filter(v=>v!==false&&v!=null)}),useState:v=>{const at=index++;if(!cells[at])cells[at]={value:typeof v==='function'?v():v};return[cells[at].value,n=>{cells[at].value=typeof n==='function'?n(cells[at].value):n}]},useRef:v=>{const at=index++;return cells[at]??(cells[at]={current:v})},useEffect:()=>{index++}};
 const Component=module.createJointPanel(React,async r=>r.action==='plan'?{ok:true,engagement:'fixture',profileRevision:1,availableSteps:[],kaliAllowed:false,reaAllowed:true,pentagiAllowed:true}:{ok:true,engagement:'fixture',task:null},{storage:()=>({getItem:()=>null})});const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 await nodes(render()).find(n=>n.type==='button'&&text(n)==='核对联合范围与原任务').props.onClick();const choices=nodes(render()).filter(n=>n.type==='label');const paid=choices.find(n=>text(n).includes('pentagi'));assert.ok(paid);const input=nodes(paid).find(n=>n.type==='input');assert.equal(input.props.disabled,false);assert.equal(input.props.checked,false);
});
test('An authorized ZAP step is visible but network checks are never preselected on refresh',async()=>{
 const cells=[];let index=0;const React={createElement:(type,props,...children)=>({type,props:props??{},children:children.flat(Infinity).filter(v=>v!==false&&v!=null)}),useState:v=>{const at=index++;if(!cells[at])cells[at]={value:typeof v==='function'?v():v};return[cells[at].value,n=>{cells[at].value=typeof n==='function'?n(cells[at].value):n}]},useRef:v=>{const at=index++;return cells[at]??(cells[at]={current:v})},useEffect:()=>{index++}};
 const Component=module.createJointPanel(React,async r=>r.action==='plan'?{ok:true,engagement:'fixture',profileRevision:1,availableSteps:['semgrep','zap'],webTarget:{origin:'http://127.0.0.1:18780',appRevision:'not-proven'},kaliAllowed:false}:{ok:true,engagement:'fixture',task:{id:'fixture-task-id',engagement:'fixture',state:'completed',scopeRevision:1,steps:[],findings:0,cleanupVerified:true,webTarget:{appRevision:'managed-source-copy-matched'}}},{storage:()=>({getItem:()=>null})});const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 await nodes(render()).find(n=>n.type==='button'&&text(n)==='核对联合范围与原任务').props.onClick();const choice=nodes(render()).find(n=>n.type==='label'&&text(n).includes('zap'));assert.ok(choice);const input=nodes(choice).find(n=>n.type==='input');assert.equal(input.props.disabled,false);assert.equal(input.props.checked,false);assert.ok(text(render()).includes('http://127.0.0.1:18780'));assert.ok(text(render()).includes('受管源码副本前后匹配'));
});

test('Joint panel pages Python evidence and keeps it separate from scanner findings',async()=>{
 const cells=[];let index=0,badSnapshot=false;const calls=[];
 const React={createElement:(type,props,...children)=>({type,props:props??{},children}),useState:value=>{const i=index++;if(!(i in cells))cells[i]=value;return[cells[i],next=>{cells[i]=typeof next==='function'?next(cells[i]):next}]},useRef:value=>({current:value}),useEffect:()=>{}};
 const task={id:'fixture-task-id',engagement:'fixture',state:'completed',scopeRevision:1,steps:[{id:'semgrep-run',tool:'semgrep',state:'completed',pythonEvidence:'completed',artifacts:3}],findings:5,cleanupVerified:true,snapshot:{id:'a'.repeat(64)}};
 const response=(items,complete,nextCursor)=>({ok:true,engagement:'fixture',task,page:{section:'artifacts',items,total:3,complete,nextCursor}});
 const common={tool:'semgrep',status:'unverified',sourceTask:'semgrep-run',snapshotId:'a'.repeat(64)};
 const guard={...common,evidenceKind:'python-eval-guard',path:'routes.py',line:21,assignmentLine:18,guardLine:19,literalCount:2};
 const stringGuard={...common,evidenceKind:'python-string-guard',path:'guarded.py',line:10,executionLine:11,guardLine:7,sink:'exec'};
 const flow={...common,evidenceKind:'python-import-flow',path:'handler.py',line:5,calleeFile:'evaluator.py',sinkLine:2,sink:'eval'};
 const Component=module.createJointPanel(React,async request=>{
  calls.push(request);
  if(request.action==='plan')return{ok:true,engagement:'fixture',profileRevision:1,availableSteps:['semgrep'],kaliAllowed:false};
  if(request.action==='status')return{ok:true,engagement:'fixture',task};
  if(badSnapshot)return{...response([guard],true,null),task:{...task,snapshot:{id:'other-snapshot'}}};
  if(request.cursor==='page-three')return response([flow],true,null);
  return request.cursor?response([stringGuard],false,'page-three'):response([guard],false,'page-two');
 },{storage:()=>({getItem:()=>null})});
 const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 const click=async label=>nodes(render()).find(n=>n.type==='button'&&text(n)===label).props.onClick();
 await click('核对联合范围与原任务');
 assert.equal(calls.some(x=>x.action==='report'),false);
 await click('查看 Python 证据');
 assert.match(text(render()),/白名单条件/);assert.match(text(render()),/routes.py:21/);assert.match(text(render()),/待核实/);
 await click('下一页证据');
 assert.equal(calls.at(-1).cursor,'page-two');
 assert.match(text(render()),/字符串条件/);assert.match(text(render()),/guarded.py:10/);assert.match(text(render()),/第 11 行/);
 await click('下一页证据');
 assert.equal(calls.at(-1).cursor,'page-three');
 assert.match(text(render()),/handler.py:5/);assert.match(text(render()),/evaluator.py:2/);
 assert.match(text(render()),/工具命中 5 条/);
 badSnapshot=true;await click('查看 Python 证据');
 assert.match(text(render()),/Python 证据分页未确认/);
 assert.match(text(render()),/evaluator.py:2/);

});

test('Deep mode starts only the explicitly planned S1 steps and retains its mode',async()=>{
 const cells=[];let index=0;const calls=[],stored=new Map();
 const React={createElement:(type,props,...children)=>({type,props:props??{},children}),useState:value=>{const i=index++;if(!(i in cells))cells[i]=value;return[cells[i],next=>{cells[i]=typeof next==='function'?next(cells[i]):next}]},useRef:value=>({current:value}),useEffect:()=>{}};
 const task={id:'fixture-deep-task',engagement:'fixture',state:'completed',scopeRevision:1,steps:[],findings:0,cleanupVerified:true,workspace:{mode:'deep'}};
 const Component=module.createJointPanel(React,async r=>{
  calls.push(r);
  if(r.action==='plan')return{ok:true,engagement:'fixture',profileRevision:1,availableSteps:['semgrep'],kaliAllowed:false,workspace:{mode:'deep',maxSeconds:900}};
  return{ok:true,engagement:'fixture',task:r.action==='start'?task:null};
 },{storage:()=>({getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)})});
 const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 const click=async label=>{const button=nodes(render()).find(n=>n.type==='button'&&text(n)===label);assert.ok(button,label);await button.props.onClick()};
 await click('核对深度检查范围');
 await click('启动深度检查');
 assert.equal(calls.find(r=>r.action==='plan').mode,'deep');
 assert.deepEqual(calls.find(r=>r.action==='start').steps,['semgrep']);
 assert.equal(calls.find(r=>r.action==='start').mode,'deep');
 assert.match(text(render()),/深度检查/);
});
