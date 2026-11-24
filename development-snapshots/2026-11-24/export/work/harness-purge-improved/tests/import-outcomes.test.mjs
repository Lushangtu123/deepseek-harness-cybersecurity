import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8');
const path='/home/purge/workspace/repo';
const helper=source.slice(source.indexOf('async function importVmClone('),source.indexOf('\n\t\tfunction vmToolchainLabel('));
function cacheFixture(){
 let selected='A',items=[],phase='ready',state='idle',creates=0;const opens=[];
 const old={workspaceId:'old',path},next={workspaceId:'new',path};
 const host={sidebarRight:{mounted:{getSnapshot:()=>selected}},workspaces:{list:{getSnapshot:()=>({phase,state,items})},create:async()=>{creates++;items=[old];return old}},uiWorkspace:{openWorkspace:async(id,ready)=>{opens.push(id);ready('B');selected='B'}}};
 const scope={AbortController,AbortSignal,setTimeout,clearTimeout};vm.runInNewContext(helper,scope);
 return{host,run:()=>scope.importVmClone(host,path,()=>true),read:()=>scope.readVmImportOutcome(host,path),replace:()=>{items=[next]},remove:()=>{items=[]},loading:()=>{phase='pending';state='loading'},setPhase:(p,s)=>{phase=p;state=s},creates:()=>creates,opens};
}
test('A current replacement ID outranks an older completed registration receipt',async()=>{
 const f=cacheFixture();await f.run();f.replace();assert.equal(f.read().workspace.workspaceId,'new');await f.run();assert.deepEqual(f.opens,['old','new']);assert.equal(f.creates(),1);
});
test('A removed completed registration is reported removed without automatically submitting another create',async()=>{
 const f=cacheFixture();await f.run();f.remove();assert.equal(f.read().state,'removed');assert.equal(f.read().workspace,null);
 const result=await f.run();assert.equal(result.removed,true);assert.equal(f.creates(),1);assert.deepEqual(f.opens,['old']);
});
test('A loading list never presents a historic receipt as a current list confirmation',async()=>{
 const f=cacheFixture();await f.run();f.loading();assert.equal(f.read().confirmed,false);assert.equal(f.creates(),1);
});
test('Loading, pending and failed lists cannot open a historical ID even after the panel is reopened',async()=>{
 for(const [phase,state]of [['ready','loading'],['pending','idle'],['ready','error']]){
  const f=cacheFixture();await f.run();f.remove();f.setPhase(phase,state);const result=await f.run();
  assert.equal(result.uncertain,true);assert.deepEqual(f.opens,['old']);assert.equal(f.creates(),1);
 }
});
function managerFixture({createFailure=false}={}){
 let si=0,ri=0,fail=true;const states=[[],path,path,'',false,path],refs=[];let creates=0;
 const host={sidebarRight:{mounted:{getSnapshot:()=> 'A'}},workspaces:{list:{getSnapshot:()=>({phase:'ready',state:'idle',items:[]})},create:async()=>{creates++;if(createFailure)throw Error('synthetic response lost');return{workspaceId:'W',path}}},uiWorkspace:{openWorkspace:async()=>{}}};
 const scope={AbortController,AbortSignal,setTimeout,clearTimeout,vmShellWorkbenchHost:host,VmToolchainStatusCard:()=>null,
 useState(value){const i=si++;if(!(i in states))states[i]=value;return[states[i],next=>{states[i]=typeof next==='function'?next(states[i]):next}]},useRef:value=>refs[ri++]??={current:value},useEffect(){},h:(tag,props,...children)=>({tag,props,children}),document:{body:{}},require:()=>({createPortal:node=>node}),readVmDirectory:async()=>{if(fail)throw Error('目录核对失败');return{path}}};
 vm.runInNewContext(helper,scope);vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),scope);
 vm.runInNewContext(source.slice(source.indexOf('function VmWorkbenchManager('),source.indexOf('\n\t\tfunction ShellWorkbenchButton('))+'\nrender=VmWorkbenchManager;',scope);
 const render=()=>{si=ri=0;return scope.render({onClose(){}})};
 const button=(text)=>{let found;const walk=node=>{if(Array.isArray(node))return node.forEach(walk);if(node?.tag){if(node.tag==='button'&&node.children.includes(text))found=node;walk(node.children)}};walk(render());return found};
 return{states,button,creates:()=>creates,restore:()=>{fail=false}};
}
test('A failed read-only confirmation preflight remains safely retryable for the same path',async()=>{
 const f=managerFixture();await f.button('确认导入并打开').props.onClick();assert.equal(f.creates(),0);assert.equal(f.states[13],null);assert.match(f.states[3],/目录/);assert.doesNotMatch(f.states[3],/未确认/);
 f.restore();await f.button('检查并导入目录 →').props.onClick();assert.equal(f.button('确认导入并打开').props.disabled,false);
});
test('A dispatched create failure still keeps uncertain-submission protection',async()=>{
 const f=managerFixture({createFailure:true});f.restore();await f.button('确认导入并打开').props.onClick();
 assert.equal(f.creates(),1);assert.equal(f.states[13].state,'unconfirmed');assert.equal(f.button('确认导入并打开').props.disabled,true);assert.match(f.states[3],/未确认/);
});
