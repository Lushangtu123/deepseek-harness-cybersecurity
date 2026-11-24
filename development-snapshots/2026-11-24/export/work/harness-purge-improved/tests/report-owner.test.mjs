import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm'
const source=fs.readFileSync(new URL('../package/lib/redteam/client.js',import.meta.url),'utf8'),fixture=fs.readFileSync(new URL('./ui-regression.test.mjs',import.meta.url),'utf8')
const scope={source,vm,assert,console,AbortController,Event,setTimeout,clearTimeout,setInterval,clearInterval,Date,performance}
vm.runInNewContext(fixture.slice(fixture.indexOf('function host('),fixture.indexOf("test('API rejects")).replace('writeText: async () => {}','writeText: timer.writeText || (async () => {})'),scope)
const {host,nodes,text,button}=scope,flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve()},response=x=>({ok:true,status:200,json:async()=>x})
const report=(name,n=0)=>{const items=Array.from({length:n},(_,i)=>({id:i+1,seq:i+1,points:1,point_name:name+'-'+i,requests:[],steps:[],counted:true}));return {ok:true,target:name,markdown:name+'-markdown',items,stages:n?[{code:'owned',name:'Owned',color:'#123456',points:n,cumulative:n,items}]:[],summary:{count:n,points:n}}}
test('Report hides old data before effects and invalidates old copy and reload actions',async()=>{
  const copies=[],requests=[],h=host(async(_u,o)=>{const q=JSON.parse(o.body);requests.push(q);return response(report(q.engagement,1))},{writeText:async x=>copies.push(x)})
  try{h.mount('ReportTab',{engagement:'A'});await flush();const tree=h.render(),oldCopy=button(tree,'复制全文'),oldReload=button(tree,'重新生成')
    const next=h.preview({engagement:'B'});assert.doesNotMatch(text(next),/A-0/);assert.equal(button(next,'复制全文').props.disabled,true)
    h.render({engagement:'B'});await flush();h.render();const before=requests.length;oldCopy.props.onClick();oldReload.props.onClick();await flush()
    assert.equal(copies.length,0);assert.equal(requests.length,before);button(h.render(),'复制全文').props.onClick();await flush();assert.deepEqual(copies,['B-markdown'])
  }finally{h.unmount()}
})
test('Report pagination renders bounded details while full export stays complete',async()=>{
  const copies=[],h=host(async()=>response(report('Owned',26)),{writeText:async x=>copies.push(x)})
  try{h.mount('ReportTab',{engagement:'A'});await flush();let tree=h.render();assert.match(text(tree),/Owned-0/);assert.doesNotMatch(text(tree),/Owned-25/)
    button(tree,'下一页').props.onClick();tree=h.render();assert.match(text(tree),/Owned-25/);assert.doesNotMatch(text(tree),/Owned-0 /)
    button(tree,'复制全文').props.onClick();await flush();assert.equal(copies[0],'Owned-markdown')
  }finally{h.unmount()}
})
test('Incomplete report response remains unconfirmed, legitimate empty report works',async()=>{
  for(const [value,bad] of [[{ok:true},true],[{...report('A'),stages:{}},true],[report('A'),false]]){
    const h=host(async()=>response(value));try{h.mount('ReportTab',{engagement:'A'});await flush();const tree=h.render()
      if(bad){assert.match(text(tree),/报告.*未确认/);assert.doesNotMatch(text(tree),/还没有可交付的成果/);assert.equal(button(tree,'复制全文').props.disabled,true)}else assert.match(text(tree),/还没有可交付的成果/)
    }finally{h.unmount()}
  }
})
for(const leaf of ['request','step-title','how'])test('Malformed report '+leaf+' cannot render an object child',async()=>{
  const value=report('A',1),x=value.items[0]
  if(leaf==='request')x.requests=[{request:{owned:'bad'}}]
  if(leaf==='step-title')x.steps=[{title:{owned:'bad'}}]
  if(leaf==='how')x.how={owned:'bad'}
  const h=host(async()=>response(value));try{h.mount('ReportTab',{engagement:'A'});await flush();const tree=h.render();assert.match(text(tree),/报告.*未确认/);assert.equal(button(tree,'复制全文').props.disabled,true)}finally{h.unmount()}
})
