import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8');
function fixture(full,granted){
 const start=source.indexOf('let dockBus =');
 const end=source.indexOf('\n\t\tfunction getDock()',start);
 const state={window:{location:{hash:full?'#redteam-full':''}},readDrillAuth:()=>granted,__dshPurgeDrill:{isFullWindow:()=>full}};
 vm.runInNewContext(source.slice(start,end)+'\nresult=dockBus;',state);
 return state.result;
}
test('direct full-window route opens the authorized drill immediately',()=>{
 const state=fixture(true,true);assert.equal(state.open,true);assert.equal(state.tab,'drill');assert.equal(state.authOpen,false);
});
test('full-window route preserves the consent gate and normal route stays closed',()=>{
 const denied=fixture(true,false);assert.equal(denied.open,true);assert.equal(denied.authOpen,true);
 assert.equal(fixture(false,true).open,false);
});
test('full window mounts the standalone Panel instead of the floating embedded panel',()=>{
 const scope={useT:()=>x=>x,useDock:()=>({open:true,tab:'drill',authOpen:false}),
  useState:init=>[typeof init==='function'?init():init,()=>{}],useEffect(){},
  loadDockGeom:()=>({x:0,y:0,w:600,h:500}),detectHostTheme:()=> 'white',readDrillAuth:()=>true,
  __dshPurgeDrill:{isFullWindow:()=>true,Panel:'DRILL_PANEL'},react:{Fragment:'fragment'},ShellWorkbenchButton:'SHELL_WORKBENCH',drillSessionId:()=> 'selected-chat',
  h:(type,props,...children)=>({type,props:props||{},children}),setDock(){},requestDrill(){}};
 const start=source.indexOf('function PurgeDock()');const end=source.indexOf('\n\t\tfunction hasInlinePurgeEntry()',start);
 vm.runInNewContext(source.slice(start,end)+'\nresult=PurgeDock();',scope);
 const nodes=[];function visit(node){if(!node||typeof node!=='object')return;nodes.push(node);for(const child of node.children||[])visit(child);}
 visit(scope.result);
 assert.ok(nodes.some(node=>node.type==='DRILL_PANEL'&&node.props.embedded===false));
 assert.ok(nodes.some(node=>node.type==='DRILL_PANEL'&&node.props.shellWorkbench?.type==='SHELL_WORKBENCH'));
 assert.ok(nodes.some(node=>node.type==='DRILL_PANEL'&&node.props.getSessionId?.()==='selected-chat'));
 assert.ok(!nodes.some(node=>node.props?.className==='dshp-dock'));
});
