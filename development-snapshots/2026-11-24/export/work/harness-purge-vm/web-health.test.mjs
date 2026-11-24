import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { ENVIRONMENT_BANNER } from './web-health.mjs'
const bannerRuntime=()=>({performance:{now:()=>Date.now()},window:{addEventListener(){}},setInterval:()=>0,setTimeout,clearTimeout,AbortController})
test('Version banner distinguishes actual runtime and program-only recovery coverage',async()=>{
 for(const [mode,state,label,coverage] of [['original','older','完整原版','存在未覆盖或已变更项'],['improved','matches','改进版','已覆盖程序、工具和配置']]){
  const nodes=[]
  const element=tag=>({tag,style:{},children:[],appendChild(child){this.children.push(child)},addEventListener(){},textContent:''})
  const document={getElementById:()=>null,createElement:element,body:{appendChild:node=>nodes.push(node)}}
  vm.runInNewContext(ENVIRONMENT_BANNER,{...bannerRuntime(),document,AbortSignal,fetch:async()=>({ok:true,json:async()=>({mode,modeFileMatches:true,configDir:'/home/purge/.dsh',observedAt:'2026-10-26T00:00:00Z',recovery:{state,name:'ready-workbench-20261026'}})})})
  for(let i=0;i<8;i++)await Promise.resolve()
  assert.match(nodes[0].children[0].textContent,new RegExp(label));assert.match(nodes[0].children[0].textContent,new RegExp(coverage));assert.match(nodes[0].children[1].textContent,/不代表之后新增的数据已备份/)
 }
})

import { HEALTH_HTML } from './web-health.mjs'
test('Recovery details distinguish an uncovered core runtime from corrupted files',async()=>{
 const nodes=[],element=tag=>({tag,style:{},children:[],appendChild(child){this.children.push(child)},addEventListener(){},textContent:''});
 const document={getElementById:()=>null,createElement:element,body:{appendChild:node=>nodes.push(node)}};
 vm.runInNewContext(ENVIRONMENT_BANNER,{...bannerRuntime(),document,AbortSignal,fetch:async()=>({ok:true,json:async()=>({mode:'improved',runtimePackageVersion:'0.2.1-rc.3',modeFileMatches:true,configDir:'/home/purge/.dsh-improved',observedAt:'2026-10-26T00:00:00Z',recovery:{state:'older',groups:{runtime:{state:'uncovered'}}}})})});
 for(let i=0;i<8;i++)await Promise.resolve();const text=nodes[0].children[1].textContent;
 assert.match(text,/Harness 安装包版本：0.2.1-rc.3/);assert.match(text,/核心运行时：未纳入核对/);assert.doesNotMatch(text,/损坏/);
})
test('Recovery banner explains exact changes and host launch mismatch without exposing config bodies',async()=>{
 const nodes=[],element=tag=>({tag,style:{},children:[],appendChild(child){this.children.push(child)},addEventListener(){},textContent:''});
 const document={getElementById:()=>null,createElement:element,body:{appendChild:node=>nodes.push(node)}};
 vm.runInNewContext(ENVIRONMENT_BANNER,{...bannerRuntime(),document,AbortSignal,fetch:async()=>({ok:true,json:async()=>({mode:'improved',modeFileMatches:true,configDir:'/home/purge/.dsh-improved',observedAt:'2026-10-26T00:00:00Z',recovery:{state:'older',launchAgentsMatch:false,name:'ready-workbench-v4-20261026',groups:{config:{state:'older'}},differentFiles:['.dsh-improved/cordis.patch.yml','host-launch-agents/com.personal.harness-purge-original-web-entry.plist'],differentFileCount:2}})})});
 for(let i=0;i<8;i++)await Promise.resolve();const text=nodes[0].children[1].textContent;
 assert.match(text,/变更文件/);assert.match(text,/cordis.patch.yml/);assert.match(text,/宿主启动配置/);assert.match(text,/确认改动来源/);
})
function healthFixture(){
 const pending=[],timers=new Map();let timerId=0
 const element=()=>({textContent:'',disabled:false,children:[],appendChild(child){this.children.push(child)},replaceChildren(){this.children=[]},addEventListener(){}})
 const nodes={error:element(),layers:element(),summary:element(),refresh:element(),events:element()}
 const scope={document:{getElementById:id=>nodes[id],createElement:element},AbortController,AbortSignal,setTimeout:fn=>{timers.set(++timerId,fn);return timerId},clearTimeout:id=>timers.delete(id),fetch:(_url,options)=>new Promise((resolve,reject)=>{pending.push({resolve,reject,options})})}
 vm.runInNewContext(HEALTH_HTML.match(/<script>([\s\S]*?)<\/script>/)[1],scope)
 const answer=(i,count,layers={})=>pending[i].resolve({ok:true,json:async()=>({layers,active:{websocket:0,sse:0},recent:Array(count).fill({})})})
 return{scope,nodes,pending,timers,answer}
}
const tick=()=>new Promise(setImmediate)
test('The health page explains body interruption, body timeout and complete receipt',async()=>{
 const f=healthFixture();f.answer(0,3,{assets:{state:'connection-error',error:'body-incomplete',phase:'body'},api:{state:'timeout',error:'body-timeout',phase:'body'},index:{state:'ok',phase:'complete'}});await tick();
 const text=f.nodes.layers.children.map(row=>row.children.map(cell=>cell.textContent).join(' ')).join('\n');
 assert.match(text,/正文中断/);assert.match(text,/正文等待超时/);assert.match(text,/正文已完整接收/);
})
test('An older diagnostics response cannot overwrite the newest refresh result',async()=>{
 const f=healthFixture();f.answer(0,1);await tick()
 const old=f.scope.refresh(),latest=f.scope.refresh();f.answer(2,3);await latest;f.answer(1,2);await old
 assert.match(f.nodes.summary.textContent,/3 条/)
})
test('A stalled diagnostics refresh has a visible deadline and restores the refresh button',async()=>{
 const f=healthFixture();assert.equal(f.nodes.refresh.disabled,true)
 assert.ok(f.timers.size>0,'diagnostics need a deadline')
 for(const fn of [...f.timers.values()])fn();await tick()
 assert.match(f.nodes.error.textContent,/超时/);assert.equal(f.nodes.refresh.disabled,false)
 f.answer(0,9);await tick();assert.ok(!f.nodes.summary.textContent.includes('9 条'))
})
