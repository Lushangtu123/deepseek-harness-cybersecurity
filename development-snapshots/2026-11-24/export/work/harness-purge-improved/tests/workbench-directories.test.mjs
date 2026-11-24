import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8')
function fixture(fail=false){
 const start=source.indexOf('async function readVmDirectory(');assert.ok(start>=0,'Read-only VM directory validation is missing')
 const end=source.indexOf('\n\t\tfunction vmTerminalUnavailable(',start);const calls=[]
 const scope={AbortController,AbortSignal,setTimeout,clearTimeout}
 vm.runInNewContext(source.slice(start,end)+'\nread=readVmDirectory;',scope)
 const host={remote:{directoryPicker:{list:async path=>{calls.push(path);return fail?{ok:false,error:{message:'ENOENT private internals'}}:{ok:true,value:{path,entries:[{name:'repo',path:'/home/purge/workspace/repo'},{name:'outside',path:'/etc'},{name:'.hidden',path:'/home/purge/workspace/.hidden',hidden:true}],truncated:false}}}}}}
 return{calls,read:(path,allowRoot=false)=>scope.read(host,path,undefined,allowRoot)}
}
test('Directory browsing uses the official read-only namespace and filters out-of-root and hidden entries',async()=>{
 const f=fixture();const result=await f.read('/home/purge/workspace/',true)
 assert.equal(result.entries.length,1);assert.equal(result.entries[0].name,'repo');assert.equal(f.calls.length,1)
})
test('Import preflight rejects root, traversal, controls and outside paths before any remote read',async()=>{
 for(const path of ['', '/home/purge/workspace/', '/home/purge/workspace/../.dsh', '/home/purge/workspaceevil/repo','/Users/host','/home/purge/workspace/a\0b']){
  const f=fixture();await assert.rejects(f.read(path));assert.equal(f.calls.length,0)
 }
})
test('A missing directory gives an actionable error without leaking internal server output',async()=>{
 const f=fixture(true);await assert.rejects(f.read('/home/purge/workspace/missing'),error=>/目录.*检查/.test(error.message)&&!error.message.includes('private internals'))
})
