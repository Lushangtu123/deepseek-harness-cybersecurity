import test from 'node:test';import assert from 'node:assert/strict';
const module=await import('../package/lib/redteam/personal-security-client.mjs');
const nodes=n=>n&&typeof n==='object'?[n,...(n.children??[]).flatMap(nodes)]:[];
const text=n=>typeof n==='string'?n:(n?.children??[]).map(text).join('');
test('Joint panel retains an uncertain startup request and recovers it with read-only status, without replay',async()=>{
 assert.equal(typeof module.createJointPanel,'function','Joint panel is missing');const cells=[];let index=0;const stored=new Map(),calls=[];
 const storage={getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
 const React={createElement:(type,props,...children)=>({type,props:props??{},children:children.flat(Infinity).filter(v=>v!==false&&v!=null)}),useState:v=>{const at=index++;if(!cells[at])cells[at]={value:typeof v==='function'?v():v};return[cells[at].value,n=>{cells[at].value=typeof n==='function'?n(cells[at].value):n}]},useRef:v=>{const at=index++;return cells[at]??(cells[at]={current:v})},useEffect:()=>{index++}};
 const task={id:'joint-task-0001',engagement:'fixture',state:'running',scopeRevision:1,steps:[],snapshot:null,findings:0,cleanupVerified:false};
 const api=async r=>{calls.push(r);if(r.action==='plan')return{ok:true,engagement:'fixture',profileRevision:1,availableSteps:['semgrep'],kaliAllowed:false};if(r.action==='start')throw Error('lost reply');return{ok:true,engagement:'fixture',task:r.requestId?task:null}};
 const Component=module.createJointPanel(React,api,{storage:()=>storage,exclusive:async(_e,fn)=>fn()});const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 const click=async label=>{const button=nodes(render()).find(n=>n.type==='button'&&text(n)===label);assert.ok(button,'Missing '+label);await button.props.onClick()};
 await click('核对联合范围与原任务');await click('启动联合审查');assert.equal(calls.filter(r=>r.action==='start').length,1);assert.equal(stored.size,1);await click('核对联合范围与原任务');assert.equal(calls.filter(r=>r.action==='start').length,1);assert.ok(calls.some(r=>r.action==='status'&&r.requestId));assert.ok(text(render()).includes(task.id));
});

test('A paid PentAGI step is available after consent but never preselected by refresh',async()=>{
 const cells=[];let index=0;const React={createElement:(type,props,...children)=>({type,props:props??{},children:children.flat(Infinity).filter(v=>v!==false&&v!=null)}),useState:v=>{const at=index++;if(!cells[at])cells[at]={value:typeof v==='function'?v():v};return[cells[at].value,n=>{cells[at].value=typeof n==='function'?n(cells[at].value):n}]},useRef:v=>{const at=index++;return cells[at]??(cells[at]={current:v})},useEffect:()=>{index++}};
 const Component=module.createJointPanel(React,async r=>r.action==='plan'?{ok:true,engagement:'fixture',profileRevision:1,availableSteps:[],kaliAllowed:false,reaAllowed:true,pentagiAllowed:true}:{ok:true,engagement:'fixture',task:null},{storage:()=>({getItem:()=>null})});const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 await nodes(render()).find(n=>n.type==='button'&&text(n)==='核对联合范围与原任务').props.onClick();const choices=nodes(render()).filter(n=>n.type==='label');const paid=choices.find(n=>text(n).includes('pentagi'));assert.ok(paid);const input=nodes(paid).find(n=>n.type==='input');assert.equal(input.props.disabled,false);assert.equal(input.props.checked,false);
});
