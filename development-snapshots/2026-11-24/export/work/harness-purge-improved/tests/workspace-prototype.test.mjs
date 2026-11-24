import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Run the actual inline controller with a minimal event surface. This checks
// preview invalidation only; Chrome observations cover real layout and focus.
function fixture(){
 const html=readFileSync(new URL('../../../docs/security-workspace/prototype.html',import.meta.url),'utf8');
 const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];assert.equal(scripts.length,1);
 const nodes=new Map();
 function element(key){
  if(!nodes.has(key)){
   let content='';
   nodes.set(key,{hidden:key==='#plan',value:key==='#filter'?'all':'',checked:false,
    get innerHTML(){return content},set innerHTML(value){content=value},
    get textContent(){return content},set textContent(value){content=value},
    focus(){},dispatch(type){this['on'+type]?.({target:this})}});
  }
  return nodes.get(key);
 }
 const modes=['ordinary','deep'].map(value=>({...element('mode-'+value),value,checked:value==='ordinary'}));
 const document={
  querySelector(selector){return selector==='input[name=mode]:checked'?modes.find(mode=>mode.checked):element(selector)},
  querySelectorAll(selector){return selector==='input[name=mode]'?modes:[]},
  addEventListener(){},
 };
 vm.runInNewContext(scripts[0][1],{document},{timeout:1000});
 return {element,preview:()=>element('#preview').dispatch('click'),changeMode(value){for(const mode of modes)mode.checked=mode.value===value;modes.find(mode=>mode.checked).dispatch('change')}};
}

test('Changing check mode invalidates the previously displayed preview in both directions',()=>{
 const f=fixture(),plan=f.element('#plan');
 f.preview();assert.equal(plan.hidden,false);assert.match(plan.innerHTML,/普通检查 · 计划预览/);
 f.changeMode('deep');assert.equal(plan.hidden,true);assert.equal(plan.innerHTML,'');
 f.preview();assert.equal(plan.hidden,false);assert.match(plan.innerHTML,/深度检查 · 计划预览/);
 f.changeMode('ordinary');assert.equal(plan.hidden,true);assert.equal(plan.innerHTML,'');
});
test('Changing the selected project clears old preview and updates object identity text',()=>{
 const f=fixture();f.preview();const select=f.element('#project-select');
 select.value='示例 PHP 项目';select.selectedIndex=1;select.dispatch('change');
 assert.equal(f.element('#plan').hidden,true);assert.equal(f.element('#plan').innerHTML,'');
 assert.equal(f.element('#project-title').textContent,'示例 PHP 项目');
 assert.match(f.element('#project-summary').textContent,/^PHP ·/);
});
