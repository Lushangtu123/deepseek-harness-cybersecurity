import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8');
const helper=source.slice(source.indexOf('async function importVmClone('),source.indexOf('\n\t\tfunction vmToolchainLabel('));
const path='/home/purge/workspace/repo';
function fixture(code,{phase='create',structured=true}={}){
 let selected='A',items=[],reject=true,creates=0;const opens=[];
 const failure=()=>{const error=Error('PRIVATE_ERROR_CANARY');if(structured)error.name='WorkspaceCreateError';error.rpcError={code};return error};
 const host={sidebarRight:{mounted:{getSnapshot:()=>selected}},workspaces:{list:{getSnapshot:()=>({phase:'ready',state:'idle',items})},create:async()=>{creates++;if(reject&&phase==='create')throw failure();const row={workspaceId:'W',path};items=[row];return row}},uiWorkspace:{openWorkspace:async(id,ready)=>{opens.push(id);if(reject&&phase==='open')throw failure();ready('B');selected='B'}}};
 const scope={AbortController,AbortSignal,setTimeout,clearTimeout};vm.runInNewContext(helper,scope);
 return{scope,host,run:()=>scope.importVmClone(host,path,()=>true),read:()=>scope.readVmImportOutcome(host,path),fix:()=>{reject=false},creates:()=>creates,opens};
}
test('An explicit pre-invocation argument rejection permits a new explicit attempt',async()=>{
 for(const code of ['gateway/arguments-invalid','gateway/input-invalid']){
  const f=fixture(code);const result=await f.run();assert.equal(result.rejected,true);assert.ok(!JSON.stringify(result).includes('PRIVATE_ERROR_CANARY'));
  f.fix();assert.equal((await f.run()).opened,true);assert.equal(f.creates(),2);
 }
});
test('Ambiguous business, carrier and result failures retain unknown-submission protection',async()=>{
 for(const code of ['workspace/invalid-path','workspace/name-conflict','gateway/result-invalid','carrier/closed','unrecognized']){
  const f=fixture(code);await assert.rejects(f.run());f.fix();assert.equal((await f.run()).uncertain,true);assert.equal(f.creates(),1);
 }
 const plain=fixture('gateway/input-invalid',{structured:false});await assert.rejects(plain.run());plain.fix();assert.equal((await plain.run()).uncertain,true);assert.equal(plain.creates(),1);
});
test('An open failure cannot clear a successful registration even if its code matches the rejection whitelist',async()=>{
 const f=fixture('gateway/input-invalid',{phase:'open'});await assert.rejects(f.run());assert.equal(f.read().state,'registered');f.fix();assert.equal((await f.run()).opened,true);assert.equal(f.creates(),1);
});
test('The manager clears confirmation after a proven pre-invocation rejection and allows rechecking',async()=>{
 const f=fixture('gateway/arguments-invalid');let si=0,ri=0;const states=[[],path,path,'',false,path],refs=[];
 Object.assign(f.scope,{vmShellWorkbenchHost:f.host,VmToolchainStatusCard:()=>null,useState(value){const i=si++;if(!(i in states))states[i]=value;return[states[i],next=>{states[i]=typeof next==='function'?next(states[i]):next}]},useRef(value){const i=ri++;return refs[i]??={current:value}},useEffect(){},h:(tag,props,...children)=>({tag,props,children}),document:{body:{}},require:()=>({createPortal:node=>node}),readVmDirectory:async()=>({path})});
 vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),f.scope);
 vm.runInNewContext(source.slice(source.indexOf('function VmWorkbenchManager('),source.indexOf('\n\t\tfunction ShellWorkbenchButton('))+'\nrender=VmWorkbenchManager;',f.scope);
 const button=text=>{si=ri=0;let found;const walk=node=>{if(Array.isArray(node))return node.forEach(walk);if(node?.tag){if(node.tag==='button'&&node.children.includes(text))found=node;walk(node.children)}};walk(f.scope.render({onClose(){}}));assert.ok(found,text);return found};
 await button('确认导入并打开').props.onClick();assert.equal(states[13],null);assert.equal(states[5],null);assert.match(states[3],/拒绝/);assert.ok(!states[3].includes('PRIVATE_ERROR_CANARY'));
 await button('检查并导入目录 →').props.onClick();assert.equal(button('确认导入并打开').props.disabled,false);
});
