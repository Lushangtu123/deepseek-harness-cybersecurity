import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const flush=()=>new Promise(setImmediate)
function fixture(){
 const source=fs.readFileSync(new URL('../package/lib/redteam/client.js',import.meta.url),'utf8')
 const a=source.indexOf('function createSnapshotReader('),b=source.indexOf('function Panel(',a)
 assert.ok(a>=0&&b>a,'the production snapshot reader is available')
 const pending=[],values=[],errors=[],scope={AbortController}
 vm.runInNewContext(source.slice(a,b)+'\nthis.create=createSnapshotReader',scope)
 const reader=scope.create({request:(id,signal)=>new Promise((resolve,reject)=>pending.push({id,signal,resolve,reject})),publish:v=>values.push(v),publishError:e=>errors.push(e)})
 return{reader,pending,values,errors}
}
const result=id=>({ok:true,engagement:{id},stats:{assets:id==='a'?1:2}})
test('switching A to B clears old stats and ignores late A success or failure',async()=>{
 const f=fixture();f.reader.select('a');f.pending[0].resolve(result('a'));await flush()
 f.reader.select('b');assert.equal(f.values.at(-1),null);assert.equal(f.pending[0].signal.aborted,true)
 f.pending[1].resolve(result('b'));await flush();assert.equal(f.values.at(-1).engagement.id,'b')
 f.reader.select('a');const old=f.pending[2];f.reader.select('b');f.pending[3].resolve(result('b'));await flush()
 old.reject(Error('stale A failure'));await flush();assert.equal(f.values.at(-1).engagement.id,'b');assert.equal(f.errors.at(-1),null)
 f.reader.dispose()
})
test('A to B to A and same-project refreshes require the newest request generation',async()=>{
 const f=fixture();f.reader.select('a');f.reader.select('b');f.reader.select('a')
 f.pending[2].resolve(result('a'));await flush();const newest=f.values.at(-1)
 f.pending[0].resolve({...result('a'),stats:{assets:999}});f.pending[1].resolve(result('b'));await flush();assert.equal(f.values.at(-1),newest)
 f.reader.read('a');f.reader.read('a');f.pending[4].resolve({...result('a'),stats:{assets:3}});await flush();f.pending[3].resolve({...result('a'),stats:{assets:999}});await flush()
 assert.equal(f.values.at(-1).stats.assets,3);f.reader.dispose()
})
test('wrong-project replies remain unconfirmed and stale callbacks cannot reselect a project',async()=>{
 const f=fixture();f.reader.select('b');f.reader.read('a');assert.equal(f.pending.length,1)
 f.pending[0].resolve(result('a'));await flush();assert.equal(f.values.at(-1),null);assert.match(f.errors.at(-1),/项目|匹配/)
 f.reader.select(null);assert.equal(f.values.at(-1),null);f.reader.dispose()
})
test('dispose aborts outstanding reads and suppresses all late state updates',async()=>{
 const f=fixture();f.reader.select('a');const count=f.values.length;f.reader.dispose();assert.equal(f.pending[0].signal.aborted,true)
 f.pending[0].resolve(result('a'));await flush();assert.equal(f.values.length,count)
})
