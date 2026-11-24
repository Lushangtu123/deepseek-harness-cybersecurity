import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import vm from 'node:vm'
import {createRequire} from 'node:module'
function fixture(t){const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sdk-boundary-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const runtime=path.join(root,'runtime'),workspace=path.join(root,'project');for(const dir of [runtime,workspace]){fs.mkdirSync(path.join(dir,'lib'),{recursive:true});fs.writeFileSync(path.join(dir,'package.json'),'{}');fs.writeFileSync(path.join(dir,'lib/bin.js'),'')};return{root,runtime,workspace}}
function sdk(root,marker,sentinel){const dir=path.join(root,'node_modules/@deepseek-ai/dsh-tools');fs.mkdirSync(dir,{recursive:true});fs.writeFileSync(path.join(dir,'package.json'),JSON.stringify({name:'@deepseek-ai/dsh-tools',main:'index.cjs'}));fs.writeFileSync(path.join(dir,'index.cjs'),(sentinel?'require("node:fs").writeFileSync('+JSON.stringify(sentinel)+', "synthetic SDK evaluation");':'')+'exports.defineTool=spec=>({...spec,marker:'+JSON.stringify(marker)+'});');return dir}
function loader(f,{roots=[f.runtime],argv=path.join(f.runtime,'lib/bin.js'),env={}}={}){
 const source=fs.readFileSync(new URL('../package/lib/redteam/tools.js',import.meta.url),'utf8');let start=source.indexOf('function addCandidate(');if(start<0)start=source.indexOf('function loadDefineTool(');const end=source.indexOf('const defineToolRaw =',start);assert.ok(start>=0&&end>start)
 const fragment=source.slice(start,end).replaceAll('import.meta.url',JSON.stringify('file://'+path.join(f.root,'plugin/lib/tools.js')))
 const scope={createRequire,existsSync:fs.existsSync,realpathSync:fs.realpathSync,lstatSync:fs.lstatSync,dirname:path.dirname,join:path.join,resolve:path.resolve,isAbsolute:path.isAbsolute,sep:path.sep,homedir:()=>path.join(f.root,'home'),process:{argv:['synthetic-node',argv],execPath:path.join(f.root,'missing-node'),env,cwd:()=>f.workspace}}
 vm.runInNewContext(fragment+'\nthis.load=loadDefineTool',scope)
 return()=>scope.load({trustedRoots:roots})
}
test('missing approved SDK never evaluates a project cwd package or DSH_HOME package',t=>{
 for(const viaHome of [false,true]){const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate');sdk(f.workspace,'untrusted project',sentinel)
  assert.throws(loader(f,{argv:path.join(f.root,'missing-bin'),env:viaHome?{DSH_HOME:f.workspace}:{}}),/SDK|resolve|可信|未就绪/i)
  assert.equal(fs.existsSync(sentinel),false)
 }
})
test('Node ancestor lookup cannot escape an approved runtime before module evaluation',t=>{
 const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate');sdk(f.root,'untrusted ancestor',sentinel)
 assert.throws(loader(f),/SDK|resolve|可信|未就绪/i);assert.equal(fs.existsSync(sentinel),false)
})
test('SDK symlinks to project code are rejected before evaluation',t=>{
 const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate'),outside=sdk(f.workspace,'untrusted symlink',sentinel)
 fs.mkdirSync(path.join(f.runtime,'node_modules/@deepseek-ai'),{recursive:true});fs.symlinkSync(outside,path.join(f.runtime,'node_modules/@deepseek-ai/dsh-tools'),'dir')
 assert.throws(loader(f),/SDK|resolve|可信|未就绪/i);assert.equal(fs.existsSync(sentinel),false)
})
test('approved SDKs work from another cwd and prefer the matching approved runtime',t=>{
 const f=fixture(t),other=path.join(f.root,'original-runtime');fs.mkdirSync(path.join(other,'lib'),{recursive:true});fs.writeFileSync(path.join(other,'package.json'),'{}');fs.writeFileSync(path.join(other,'lib/bin.js'),'');sdk(f.runtime,'improved');sdk(other,'original');sdk(f.workspace,'must not choose project')
 assert.equal(loader(f)()({name:'fixture'}).marker,'improved')
 assert.equal(loader(f,{roots:[f.runtime,other],argv:path.join(other,'lib/bin.js')})()({name:'fixture'}).marker,'original')
})
test('an invalid approved SDK export does not fall through to project code',t=>{
 const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate'),trusted=sdk(f.runtime,'placeholder');fs.writeFileSync(path.join(trusted,'index.cjs'),'exports.defineTool="not-a-function";');sdk(f.workspace,'untrusted fallback',sentinel)
 assert.throws(loader(f),/SDK|resolve|可信|未就绪/i);assert.equal(fs.existsSync(sentinel),false)
})
test('an SDK package main cannot point out of its approved runtime',t=>{
 const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate'),trusted=sdk(f.runtime,'placeholder'),entry=path.join(f.workspace,'outside.cjs')
 fs.writeFileSync(entry,'require("node:fs").writeFileSync('+JSON.stringify(sentinel)+',"synthetic");exports.defineTool=x=>x;')
 fs.writeFileSync(path.join(trusted,'package.json'),JSON.stringify({name:'@deepseek-ai/dsh-tools',main:path.relative(trusted,entry)}))
 assert.throws(loader(f),/SDK|resolve|可信|未就绪/i);assert.equal(fs.existsSync(sentinel),false)
})
test('a matching runtime with a missing SDK does not silently switch SDK versions',t=>{
 const f=fixture(t),other=path.join(f.root,'other-runtime');fs.mkdirSync(path.join(other,'lib'),{recursive:true});fs.writeFileSync(path.join(other,'package.json'),'{}');fs.writeFileSync(path.join(other,'lib/bin.js'),'');sdk(other,'other version')
 assert.throws(loader(f,{roots:[f.runtime,other]}),/SDK_NOT_READY/)
})
test('an ancestor package cannot redirect resolution into an approved root when its SDK is absent',t=>{
 const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate'),ancestor=sdk(f.root,'placeholder'),entry=path.join(f.runtime,'lib/internal.cjs')
 fs.writeFileSync(entry,'require("node:fs").writeFileSync('+JSON.stringify(sentinel)+',"synthetic");exports.defineTool=x=>x;')
 fs.writeFileSync(path.join(ancestor,'package.json'),JSON.stringify({name:'@deepseek-ai/dsh-tools',main:path.relative(ancestor,entry)}))
 assert.throws(loader(f),/SDK_NOT_READY/);assert.equal(fs.existsSync(sentinel),false)
})
test('SDK exports require condition resolves a valid approved entry',t=>{
 const f=fixture(t),trusted=sdk(f.runtime,'exports require')
 fs.writeFileSync(path.join(trusted,'package.json'),JSON.stringify({name:'@deepseek-ai/dsh-tools',exports:{'.':{require:'./index.cjs',default:'./index.cjs'}}}))
 assert.equal(loader(f)()({name:'inert'}).marker,'exports require')
})
test('SDK exports cannot name a parent target',t=>{
 const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate'),outside=sdk(f.workspace,'untrusted exports',sentinel),trusted=sdk(f.runtime,'placeholder')
 fs.writeFileSync(path.join(trusted,'package.json'),JSON.stringify({name:'@deepseek-ai/dsh-tools',exports:{'.':{require:path.relative(trusted,path.join(outside,'index.cjs'))}}}))
 assert.throws(loader(f),/SDK_NOT_READY/);assert.equal(fs.existsSync(sentinel),false)
})
test('a valid relative SDK exports target cannot follow a symlink to project code',t=>{
 const f=fixture(t),sentinel=path.join(f.root,'must-not-evaluate'),outside=sdk(f.workspace,'untrusted export link',sentinel),trusted=sdk(f.runtime,'placeholder')
 fs.symlinkSync(path.join(outside,'index.cjs'),path.join(trusted,'linked.cjs'))
 fs.writeFileSync(path.join(trusted,'package.json'),JSON.stringify({name:'@deepseek-ai/dsh-tools',exports:{'.':{require:'./linked.cjs'}}}))
 assert.throws(loader(f),/SDK_NOT_READY/);assert.equal(fs.existsSync(sentinel),false)
})
