import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source=fs.readFileSync(new URL('../package/lib/redteam/client.js',import.meta.url),'utf8')
const fixture=fs.readFileSync(new URL('./ui-regression.test.mjs',import.meta.url),'utf8')
const copied=[]
const helper=fixture.slice(fixture.indexOf('function host('),fixture.indexOf("test('API rejects")).replace('writeText: async () => {}','writeText: async value => { copied.push(value) }')
const scope={source,vm,assert,console,AbortController,Event,setTimeout,clearTimeout,setInterval,clearInterval,Date,performance,copied}
vm.runInNewContext(helper,scope)
const {host,nodes,text,button}=scope
const flush=async()=>{for(let i=0;i<32;i++)await Promise.resolve()}
const response=value=>({ok:true,status:200,json:async()=>value})
const empty=()=>({ok:true,webshells:[],tunnels:[],totals:{webshells:0,webshellsOnline:0,tunnels:0,tunnelsActive:0,tunnelsLegit:0,tunnelsSelfOnly:0,credentials:0,access:0}})
const shell=url=>({...empty(),webshells:[{id:1,url,shell_type:'behinder'}],totals:{...empty().totals,webshells:1}})
const variants=[['missing arrays',()=>({ok:true})],['object array',()=>({...empty(),webshells:{}})],['null row',()=>({...empty(),webshells:[null]})],['bad success flag',()=>({...empty(),ok:'yes'})],['missing totals',()=>({...empty(),totals:undefined})],['negative count',()=>({...empty(),totals:{...empty().totals,access:-1}})],['infinite count',()=>({...empty(),totals:{...empty().totals,access:Infinity}})],['invalid id',()=>({...shell('synthetic'),webshells:[{id:0,url:'synthetic'}]})],['object text',()=>({...empty(),tunnels:[{id:1,listen:{private:'must-not-render'}}]})],['duplicate id',()=>({...empty(),tunnels:[{id:1},{id:1}],totals:{...empty().totals,tunnels:2}})],['inconsistent count',()=>({...empty(),totals:{...empty().totals,webshells:1}})]]
for(const [label,value] of variants)test('Malformed session '+label+' stays unconfirmed without rows or controls',async()=>{
 const h=host(async()=>response(value()))
 try{h.mount('SessionTab',{engagement:'A'});await flush();const tree=h.render();assert.match(text(tree),/记录未确认|数据未确认/);assert.doesNotMatch(text(tree),/还没有登记任何|WebShell 0\/0|内网隧道 0\/0|must-not-render/);assert.ok(!nodes(tree).some(n=>n.type==='button'&&/标记失效|标记可用|复制 URL|复制地址/.test(text(n))));assert.ok(button(tree,'刷新'))}finally{h.unmount()}
})
test('Valid empty response explicitly displays no records',async()=>{const h=host(async()=>response(empty()));try{h.mount('SessionTab',{engagement:'A'});await flush();assert.match(text(h.render()),/还没有登记任何/)}finally{h.unmount()}})
test('Invalid response after valid data removes earlier actionable records and can recover by read-only refresh',async()=>{
 let reads=0,writes=0
 const h=host(async(_u,o)=>{const q=JSON.parse(o.body);if(q.op!=='sessions')writes++;return response(++reads===1?shell('old-url'):reads===2?{ok:true}:empty())})
 try{h.mount('SessionTab',{engagement:'A'});await flush();let tree=h.render();const old=button(tree,'标记失效');button(tree,'刷新').props.onClick();await flush();tree=h.render();old.props.onClick();assert.match(text(tree),/记录未确认|数据未确认/);assert.doesNotMatch(text(tree),/old-url/);assert.equal(writes,0);button(tree,'刷新').props.onClick();await flush();assert.match(text(h.render()),/还没有登记任何/)}finally{h.unmount()}
})
test('Copy URL writes only the exact address and keeps feedback',async()=>{
 copied.length=0;const url='https://synthetic.invalid/path?q=one&n=2',h=host(async()=>response(shell(url)))
 try{h.mount('SessionTab',{engagement:'A'});await flush();button(h.render(),'复制 URL').props.onClick();await flush();assert.deepEqual(copied,[url]);assert.match(text(h.render()),/已复制/)}finally{h.unmount()}
})
