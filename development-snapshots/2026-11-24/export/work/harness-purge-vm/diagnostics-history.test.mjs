import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { createDiagnostics, HEALTH_HTML } from './web-health.mjs';
const tick=()=>new Promise(setImmediate);
function fixture(data){
 const nodes=new Map();const element=()=>({textContent:'',children:[],disabled:false,appendChild(child){this.children.push(child)},replaceChildren(){this.children=[]},addEventListener(){}});
 for(const id of ['refresh','error','layers','summary','events'])nodes.set(id,element());
 vm.runInNewContext(HEALTH_HTML.split('<script>')[1].split('</script>')[0],{document:{getElementById:id=>nodes.get(id),createElement:element},AbortController,setTimeout,clearTimeout,fetch:async()=>({ok:true,json:async()=>data})});
 return{nodes,text:()=>nodes.get('events').children.map(row=>row.children.map(cell=>cell.textContent).join(' ')).join('\n')};
}
test('A recorded failure remains visible after a subsequent complete response succeeds',async()=>{
 const d=createDiagnostics();d.finish(d.begin('/redteam/api?private=SECRET_CANARY','POST'),undefined,'ECONNRESET',0,'headers');d.finish(d.begin('/redteam/api','POST'),200,undefined,0,'complete');
 const data=d.snapshot();assert.ok(Number.isFinite(Date.parse(data.recent[0].observedAt)));assert.ok(data.recent[1].eventId>data.recent[0].eventId);
 const f=fixture(data);await tick();assert.match(f.text(),/连接失败/);assert.match(f.text(),/后续请求完整成功/);assert.match(f.text(),/演练资料 API/);assert.match(f.text(),/等待响应头/);assert.ok(!f.text().includes('SECRET_CANARY'));
});
test('A partial response cannot be described as a completed follow-up success',async()=>{
 const data={layers:{},active:{websocket:0,sse:0},recent:[{category:'api',state:'timeout',phase:'body',error:'body-timeout',observedAt:'2026-10-26T00:00:00Z',eventId:1},{category:'api',state:'ok',phase:'headers',observedAt:'2026-10-26T00:00:01Z',eventId:2}]};
 const f=fixture(data);await tick();assert.match(f.text(),/超时/);assert.doesNotMatch(f.text(),/后续请求完整成功/);
});
test('History displays fixed labels and keeps at most one hundred bounded records',async()=>{
 const d=createDiagnostics();for(let i=0;i<105;i++)d.finish(d.begin('/private-token?SECRET_CANARY','POST'),undefined,'PRIVATE_ERROR_CANARY',0,'body');
 const data=d.snapshot();assert.equal(data.recent.length,100);const f=fixture(data);await tick();assert.equal(f.nodes.get('events').children.length,100);assert.ok(!f.text().includes('PRIVATE_ERROR_CANARY'));assert.ok(!f.text().includes('SECRET_CANARY'));
});
