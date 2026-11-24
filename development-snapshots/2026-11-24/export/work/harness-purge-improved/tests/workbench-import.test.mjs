import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8')
function fixture({cancel=false,invalid=false,switchDuringCreate=false,switchDuringOpen=false}={}) {
  const calls=[];let current='old-session'
  const services={sidebarRight:{mounted:{getSnapshot:()=>current}},workspaces:{create:async input=>{calls.push(['create',input.path]);if(invalid)throw Error('directory not found');if(switchDuringCreate)current='other-session';return{workspaceId:'new-workspace',path:input.path}}},uiWorkspace:{openWorkspace:async(id,beforeOpen)=>{calls.push(['open',id]);beforeOpen?.('new-session');current=switchDuringOpen?'other-session':'new-session'}}}
  const scope={AbortController,AbortSignal,setTimeout,clearTimeout};const start=source.indexOf('async function importVmClone(')
  assert.ok(start>=0,'Clone directory import is missing')
  const end=source.indexOf('\n\t\tfunction VmWorkbenchManager(',start)
  vm.runInNewContext(source.slice(start,end)+'\nrun=importVmClone;',scope)
  return{calls,run:path=>scope.run({get:name=>services[name]},path,()=>{calls.push(['confirm']);return !cancel})}
}
test('Import confirms the exact directory then uses official create/open without touching the old Session',async()=>{
  const f=fixture();const result=await f.run('/home/purge/workspace/example')
  assert.equal(result.opened,true);assert.deepEqual(f.calls,[['confirm'],['create','/home/purge/workspace/example'],['open','new-workspace']])
})
test('Cancellation and unsafe/ambiguous paths do not register or navigate',async()=>{
  const f=fixture({cancel:true});assert.equal((await f.run('/home/purge/workspace/example')).cancelled,true);assert.deepEqual(f.calls,[['confirm']])
  for(const path of ['','relative','/home/purge/workspace/../.dsh','/home/purge/workspace','/home/purge/workspace/','/Users/example','/home/purge/workspace/x\0y']){
    const bad=fixture();await assert.rejects(bad.run(path));assert.deepEqual(bad.calls,[])
  }
})
test('A missing directory never changes Session selection',async()=>{
  const f=fixture({invalid:true});await assert.rejects(f.run('/home/purge/workspace/missing'),/directory not found/);assert.ok(!f.calls.some(c=>c[0]==='open'))
})
test('Navigation during registration preserves the new selected Session',async()=>{
  const f=fixture({switchDuringCreate:true});const result=await f.run('/home/purge/workspace/example');assert.equal(result.opened,false);assert.ok(!f.calls.some(c=>c[0]==='open'))
})
test('Navigation during official open cannot be reported as a completed workspace switch',async()=>{
 const f=fixture({switchDuringOpen:true});const result=await f.run('/home/purge/workspace/example');assert.equal(result.opened,false)
})
