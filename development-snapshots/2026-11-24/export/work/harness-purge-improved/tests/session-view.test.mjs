import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source=fs.readFileSync(new URL('../package/lib/redteam/client.js',import.meta.url),'utf8')
const fixture=fs.readFileSync(new URL('./ui-regression.test.mjs',import.meta.url),'utf8')
const scope={source,vm,assert,console,AbortController,Event,setTimeout,clearTimeout,setInterval,clearInterval,Date,performance}
vm.runInNewContext(fixture.slice(fixture.indexOf('function host('),fixture.indexOf("test('API rejects")),scope)
const {host,nodes,text,button}=scope
const flush=async()=>{for(let i=0;i<32;i++)await Promise.resolve()}
const response=data=>({ok:true,status:200,json:async()=>data})
const data=(name,status='active')=>({ok:true,webshells:[],tunnels:[{id:1,listen:name,status}],totals:{webshells:0,webshellsOnline:0,tunnels:1,tunnelsActive:status==='active'?1:0,tunnelsLegit:0,tunnelsSelfOnly:0,credentials:0,access:0}})
function pendingHost(){
 const pending=[],writes=[]
 const h=host((_url,opts)=>{const req=JSON.parse(opts.body);if(req.op==='sessions')return new Promise(resolve=>pending.push({req,resolve}));writes.push(req);return Promise.resolve(response({ok:true}))})
 return {h,pending,writes,finish:async()=>{for(const x of pending)x.resolve(response(data(x.req.engagement)));await flush();h.unmount()}}
}
test('Session reads retain B after a late A and current marks use B records',async()=>{
 const f=pendingHost();try{
  f.h.mount('SessionTab',{engagement:'A'});f.h.render({engagement:'B'});await flush()
  f.pending.find(x=>x.req.engagement==='B').resolve(response(data('B-record')));await flush();f.h.render()
  f.pending.find(x=>x.req.engagement==='A').resolve(response(data('A-record')));await flush();const tree=f.h.render()
  assert.match(text(tree),/B-record/);assert.doesNotMatch(text(tree),/A-record/)
  button(tree,'标记失效').props.onClick();await flush();assert.equal(f.writes.length,1);assert.equal(f.writes[0].engagement,'B')
 }finally{await f.finish()}
})
test('Switching projects hides old records immediately and rejects an old button callback',async()=>{
 const f=pendingHost();try{
  f.h.mount('SessionTab',{engagement:'A'});await flush();f.pending[0].resolve(response(data('A-record')));await flush();const old=button(f.h.render(),'标记失效')
  const beforeEffects=f.h.preview({engagement:'B'});assert.doesNotMatch(text(beforeEffects),/A-record/)
  f.h.render({engagement:'B'});old.props.onClick();await flush();assert.equal(f.writes.length,0)
 }finally{await f.finish()}
})
test('A newer same-project refresh outranks an earlier response and old mark callback',async()=>{
 const f=pendingHost();try{
  f.h.mount('SessionTab',{engagement:'A'});await flush();f.pending[0].resolve(response(data('first')));await flush();let tree=f.h.render();const old=button(tree,'标记失效')
  button(tree,'刷新').props.onClick();f.h.render();old.props.onClick();assert.equal(f.writes.length,0)
  button(f.h.render(),'刷新').props.onClick();f.h.render();await flush()
  f.pending[2].resolve(response(data('newest')));await flush();f.h.render();f.pending[1].resolve(response(data('older')));await flush();tree=f.h.render()
  assert.match(text(tree),/newest/);assert.doesNotMatch(text(tree),/older/)
 }finally{await f.finish()}
})
test('A to B to A cannot adopt the first A request after the newest A',async()=>{
 const f=pendingHost();try{
  f.h.mount('SessionTab',{engagement:'A'});f.h.render({engagement:'B'});f.h.render({engagement:'A'});await flush()
  f.pending[2].resolve(response(data('new-A')));await flush();f.h.render();f.pending[0].resolve(response(data('old-A')));await flush()
  assert.match(text(f.h.render()),/new-A/);assert.doesNotMatch(text(f.h.render()),/old-A/)
 }finally{await f.finish()}
})
test('A completed old write is not replayed or followed by an old-project read',async()=>{
 const reads=[],writes=[];let finishWrite
 const h=host((_u,opts)=>{const req=JSON.parse(opts.body);if(req.op==='sessions'){reads.push(req.engagement);return Promise.resolve(response(data(req.engagement)))}writes.push(req);return new Promise(resolve=>{finishWrite=resolve})})
 try{
  h.mount('SessionTab',{engagement:'A'});await flush();button(h.render(),'标记失效').props.onClick();h.render()
  h.render({engagement:'B'});await flush();h.render();finishWrite(response({ok:true}));await flush();const tree=h.render()
  assert.deepEqual(reads,['A','B']);assert.equal(writes.length,1);assert.equal(writes[0].engagement,'A');assert.match(text(tree),/B/)
 }finally{h.unmount()}
})
test('Unmounting a session view invalidates its retained mutation callbacks',async()=>{
 const f=pendingHost();try{
  f.h.mount('SessionTab',{engagement:'A'});await flush();f.pending[0].resolve(response(data('A')));await flush();const old=button(f.h.render(),'标记失效');f.h.unmount();old.props.onClick();await flush();assert.equal(f.writes.length,0)
 }finally{await f.finish()}
})
test('Unavailable panel probing is explained and cannot issue a request',async()=>{
 const calls=[];const h=host(async(_u,o)=>{const q=JSON.parse(o.body);calls.push(q);return response(data('A'))})
 try{h.mount('SessionTab',{engagement:'A'});await flush();const tree=h.render();assert.equal(button(tree,'检测连通性').props.disabled,true);assert.match(text(tree),/当前面板不发起主动检测/);assert.equal(calls.some(q=>q.op==='probeSessions'),false)}finally{h.unmount()}
})
test('A missing tunnel hint does not direct users to the disabled probe button',async()=>{
 const h=host(async()=>response({ok:true,webshells:[{id:1,url:'synthetic-webshell',shell_type:'behinder'}],tunnels:[],totals:{webshells:1,webshellsOnline:0,tunnels:0,tunnelsActive:0,tunnelsLegit:0,tunnelsSelfOnly:0,credentials:0,access:0}}))
 try{h.mount('SessionTab',{engagement:'A'});await flush();const tree=h.render();assert.doesNotMatch(text(tree),/最后点「检测连通性」/);assert.match(text(tree),/会话中.*范围/)}finally{h.unmount()}
})
