import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import * as rules from '../package/lib/rules.js'
import vm from 'node:vm'
import {spawnSync,spawn} from 'node:child_process'
function fixture(t){const home=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'rule-tx-')));fs.writeFileSync(path.join(home,'AGENTS.md'),'synthetic original agents');fs.writeFileSync(path.join(home,'CLAUDE.md'),'synthetic original claude');t.after(()=>fs.rmSync(home,{recursive:true,force:true}));return home}
function snapshot(home){return Object.fromEntries(['AGENTS.md','CLAUDE.md','AGENTS.md.dsh-purge-rule.bak','CLAUDE.md.dsh-purge-rule.bak','rules/a.md','rules/a.json','rules/state.json'].map(n=>{try{return[n,{text:fs.readFileSync(path.join(home,n),'utf8'),mode:fs.statSync(path.join(home,n)).mode&0o777}]}catch(e){if(e.code==='ENOENT')return[n,null];throw e}}))}
async function fault(home,action,{failRestore=false}={}){
 const write=fs.promises.writeFile,rename=fs.promises.rename;let fired=false
 const failState=file=>String(file)===rules.stateFile(home)&&!fired
 fs.promises.writeFile=async function(file,...args){if(failState(file)){fired=true;throw Object.assign(Error('synthetic state EIO'),{code:'EIO'})}return write.call(this,file,...args)}
 fs.promises.rename=async function(from,to,...args){if(failState(to)){fired=true;throw Object.assign(Error('synthetic state EIO'),{code:'EIO'})}if(failRestore&&fired&&String(to)===path.join(home,'AGENTS.md'))throw Object.assign(Error('synthetic restore EIO'),{code:'EIO'});return rename.call(this,from,to,...args)}
 try{await assert.rejects(action)}finally{fs.promises.writeFile=write;fs.promises.rename=rename}
 assert.equal(fired,true)
}
test('failed active edit rolls back rule, metadata, both targets, backup presence and state',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic old rule',{name:'old',target:'AGENTS.md'});await rules.activateRule(home,'a');const before=snapshot(home)
 await fault(home,()=>rules.saveRule(home,'a','synthetic new rule',{name:'new',target:'CLAUDE.md'}))
 assert.deepEqual(snapshot(home),before)
})
test('failed first activation restores original target and removes its newly-created backup',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic new rule',{target:'AGENTS.md'});const before=snapshot(home)
 await fault(home,()=>rules.activateRule(home,'a'));assert.deepEqual(snapshot(home),before)
})
test('a required original-target backup failure cannot silently commit activation',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic new rule',{target:'AGENTS.md'});const before=snapshot(home),copy=fs.promises.copyFile
 try{fs.promises.copyFile=async function(from,...args){if(String(from)===path.join(home,'AGENTS.md'))throw Object.assign(Error('synthetic backup EIO'),{code:'EIO'});return copy.call(this,from,...args)};await assert.rejects(()=>rules.activateRule(home,'a'),/backup EIO/)}finally{fs.promises.copyFile=copy}
 assert.deepEqual(snapshot(home),before)
})
test('private journals are created private from the first temporary write',async t=>{
 const home=fixture(t),write=fs.promises.writeFile,modes=[]
 try{fs.promises.writeFile=async function(file,bytes,options){if(String(file).includes('.transaction.json.')&&String(file).endsWith('.tmp'))modes.push(options?.mode);return write.call(this,file,bytes,options)};await rules.saveRule(home,'a','synthetic private preimage',{})}finally{fs.promises.writeFile=write}
 assert.ok(modes.length>0);assert.ok(modes.every(mode=>mode===0o600))
})
test('a failed partial backup copy is removed rather than left beside the instruction file',async t=>{
 const home=fixture(t),copy=fs.promises.copyFile;await rules.saveRule(home,'a','synthetic rule',{})
 try{fs.promises.copyFile=async function(from,to){if(String(from)===path.join(home,'AGENTS.md')){await fs.promises.writeFile(to,'synthetic partial');throw Object.assign(Error('synthetic partial backup EIO'),{code:'EIO'})}return copy.call(this,from,to)};await assert.rejects(()=>rules.activateRule(home,'a'))}finally{fs.promises.copyFile=copy}
 assert.equal(fs.readdirSync(home).some(name=>name.endsWith('.copytmp')),false)
})
test('rollback failure leaves visible recovery state, blocks writes, and restores on explicit recovery',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic old rule',{target:'AGENTS.md'});await rules.activateRule(home,'a');const before=snapshot(home)
 await fault(home,()=>rules.saveRule(home,'a','synthetic new rule',{target:'AGENTS.md'}),{failRestore:true})
 const status=await rules.rulesStatus(home);assert.equal(status.recoveryRequired,true);assert.equal(status.agents_synced,false)
 await assert.rejects(()=>rules.saveRule(home,'b','synthetic should not write',{}),/恢复|recovery/i)
 assert.equal(await rules.readRule(home,'b'),null)
 assert.equal(typeof rules.recoverRuleTransaction,'function');await rules.recoverRuleTransaction(home)
 assert.deepEqual(snapshot(home),before);assert.equal((await rules.rulesStatus(home)).recoveryRequired,false)
})
test('a process interrupted after target write can recover the persisted preimages on restart',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic old rule',{});await rules.activateRule(home,'a');const before=snapshot(home)
 const source=`import fs from 'node:fs';import * as rules from ${JSON.stringify(new URL('../package/lib/rules.js',import.meta.url).href)};const home=${JSON.stringify(home)},rename=fs.promises.rename;fs.promises.rename=async function(from,to,...args){if(String(to)===rules.stateFile(home))process.exit(73);return rename.call(this,from,to,...args)};await rules.saveRule(home,'a','synthetic interrupted rule',{});`
 const child=spawnSync(process.execPath,['--input-type=module','-'],{input:source,encoding:'utf8',timeout:3000});assert.equal(child.status,73,child.stderr)
 assert.equal((await rules.rulesStatus(home)).recoveryRequired,true)
 await rules.recoverRuleTransaction(home);assert.deepEqual(snapshot(home),before);assert.equal((await rules.rulesStatus(home)).recoveryRequired,false)
})
test('concurrent edits serialize their complete rule and active-target updates',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic old rule',{});await rules.activateRule(home,'a')
 await Promise.all([rules.saveRule(home,'a','synthetic first',{}),rules.saveRule(home,'a','synthetic second',{})])
 assert.equal(await rules.readRule(home,'a'),'synthetic second');assert.equal(fs.readFileSync(path.join(home,'AGENTS.md'),'utf8'),'synthetic second');assert.equal((await rules.rulesStatus(home)).recoveryRequired,false)
})
test('a cross-process recovery owns the same lock as recovery and new mutations',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic old rule',{});await rules.activateRule(home,'a');await fault(home,()=>rules.saveRule(home,'a','synthetic failed',{}),{failRestore:true})
 const ready=path.join(home,'ready'),release=path.join(home,'release'),moduleUrl=new URL('../package/lib/rules.js',import.meta.url).href
 const script=`import fs from 'node:fs';import * as rules from ${JSON.stringify(moduleUrl)};const home=${JSON.stringify(home)},rename=fs.promises.rename;let blocked=false;fs.promises.rename=async function(from,to,...args){if(!blocked&&String(to)===home+'/AGENTS.md'){blocked=true;fs.writeFileSync(home+'/ready','');const end=Date.now()+4000;while(!fs.existsSync(home+'/release')){if(Date.now()>end)throw Error('barrier timeout');await new Promise(r=>setTimeout(r,5))}}return rename.call(this,from,to,...args)};await rules.recoverRuleTransaction(home);`
 const child=spawn(process.execPath,['--input-type=module','-'],{stdio:['pipe','pipe','pipe']});let stderr='';child.stderr.on('data',x=>stderr+=x);const closed=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',resolve)});child.stdin.end(script)
 try{
  const deadline=Date.now()+4000;while(!fs.existsSync(ready)){if(Date.now()>deadline)throw Error('child recovery did not reach barrier: '+stderr);await new Promise(r=>setTimeout(r,5))}
  await assert.rejects(()=>rules.recoverRuleTransaction(home),/其他进程|事务/);await assert.rejects(()=>rules.saveRule(home,'a','must not commit',{}),/其他进程|事务/)
  fs.writeFileSync(release,'');assert.equal(await closed,0,stderr)
  await rules.saveRule(home,'a','synthetic committed after recovery',{});await rules.activateRule(home,'a')
  assert.equal(fs.readFileSync(path.join(home,'AGENTS.md'),'utf8'),'synthetic committed after recovery');assert.equal(await rules.readRule(home,'a'),'synthetic committed after recovery')
 }finally{child.kill('SIGKILL');await closed}
})
test('corrupted recovery paths never write outside the fixed rule transaction file set',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic old rule',{});await rules.activateRule(home,'a')
 await fault(home,()=>rules.saveRule(home,'a','synthetic new rule',{}),{failRestore:true})
 const file=path.join(home,'rules/.transaction.json'),journal=JSON.parse(fs.readFileSync(file,'utf8'));journal.files[0].path='../outside';fs.writeFileSync(file,JSON.stringify(journal))
 await assert.rejects(()=>rules.recoverRuleTransaction(home),/恢复/);assert.equal(fs.existsSync(path.join(home,'outside')),false);assert.equal((await rules.rulesStatus(home)).recoveryRequired,true)
})
test('a stale recovery receipt cannot restore a newer failed transaction',async t=>{
 const home=fixture(t);await rules.saveRule(home,'a','synthetic old rule',{});await rules.activateRule(home,'a')
 await fault(home,()=>rules.saveRule(home,'a','synthetic failed one',{}),{failRestore:true});const first=await rules.rulesStatus(home)
 assert.match(first.recoveryId,/^[a-f0-9-]{36}$/);await rules.recoverRuleTransaction(home,first.recoveryId)
 await fault(home,()=>rules.saveRule(home,'a','synthetic failed two',{}),{failRestore:true});const second=await rules.rulesStatus(home)
 assert.notEqual(first.recoveryId,second.recoveryId);await assert.rejects(()=>rules.recoverRuleTransaction(home,first.recoveryId),/恢复|变更/)
 assert.equal((await rules.rulesStatus(home)).recoveryId,second.recoveryId);await rules.recoverRuleTransaction(home,second.recoveryId)
})
test('a FIFO instruction target is rejected without blocking the rule mutation queue',async t=>{
 const home=fixture(t);fs.unlinkSync(path.join(home,'AGENTS.md'));const mkfifo=spawnSync('mkfifo',[path.join(home,'AGENTS.md')],{encoding:'utf8'});assert.equal(mkfifo.status,0,mkfifo.stderr)
 const source=`import * as rules from ${JSON.stringify(new URL('../package/lib/rules.js',import.meta.url).href)};try{await rules.saveRule(${JSON.stringify(home)},'a','synthetic',{});process.exitCode=2}catch{console.log('rejected-nonordinary')}`
 const child=spawnSync(process.execPath,['--input-type=module','-'],{input:source,encoding:'utf8',timeout:1500});assert.equal(child.status,0,child.error?.code+' '+child.stderr);assert.match(child.stdout,/rejected-nonordinary/)
})
test('failed active deletion and reset also restore their complete preimages',async t=>{
 for(const reset of [false,true]){
  const home=fixture(t);await rules.saveRule(home,'a','synthetic rule',{});await rules.activateRule(home,'a');const before=snapshot(home),unlink=fs.promises.unlink
  try{fs.promises.unlink=async function(file,...args){if(String(file)===rules.stateFile(home))throw Object.assign(Error('synthetic state unlink EIO'),{code:'EIO'});return unlink.call(this,file,...args)};await assert.rejects(()=>reset?rules.resetToOriginal(home):rules.deleteRule(home,'a'))}finally{fs.promises.unlink=unlink}
  assert.deepEqual(snapshot(home),before)
 }
})
test('the existing rule handler exposes explicit recovery while GET and missing confirmation stay read-only',async()=>{
 const source=fs.readFileSync(new URL('../package/lib/index.js',import.meta.url),'utf8')
 const a=source.indexOf('function rulesHttpHandler('),b=source.indexOf('\nasync function handleSkillsOp(',a);assert.ok(a>=0&&b>a)
 let calls=0,answer
 const scope={URL,sendOptions(){},readJsonBody:async request=>request.body,methodNotAllowed:()=>false,sendJson:(_response,status,value)=>{answer={status,value}},handleRulesOp:async()=>{calls++;return{ok:true}}}
 vm.runInNewContext(source.slice(a,b)+'\nthis.handler=rulesHttpHandler',scope)
 await scope.handler()({method:'GET',url:'/dsh-purge/rules/recover'},{});assert.equal(calls,0);assert.ok(answer.status>=400)
 await scope.handler()({method:'POST',url:'/dsh-purge/rules/recover',body:{}},{});assert.equal(calls,0)
 await scope.handler()({method:'POST',url:'/dsh-purge/rules/recover',body:{confirm:true}},{});assert.equal(calls,0)
 await scope.handler()({method:'POST',url:'/dsh-purge/rules/recover',body:{confirm:true,recoveryId:'a'.repeat(36)}},{});assert.equal(calls,1);assert.equal(answer.value.ok,true)
})
test('the production recovery view hides editors and confirms the exact transaction ID',async()=>{
 const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8'),a=source.indexOf('function RulesSection()'),b=source.indexOf('function SkillsSection()',a);assert.ok(a>=0&&b>a)
 const calls=[],id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';let cell=0
 const scope={useT:()=>x=>x,useRef:initial=>({current:initial}),useState:initial=>[cell++===0?{recoveryRequired:true,recoveryId:id}:initial,()=>{}],useCallback:fn=>fn,useEffect(){},Btn:'button',noticeNode:()=>null,rulesApi:async(op,body)=>{calls.push({op,body});return{ok:true}},h:(type,props,...children)=>({type,props:props??{},children})}
 vm.runInNewContext(source.slice(a,b)+'\nthis.tree=RulesSection()',scope)
 const walk=node=>node&&typeof node==='object'?[node,...(node.children??[]).flatMap(walk)]:[],text=node=>typeof node==='string'?node:(node?.children??[]).map(text).join(' ')
 const nodes=walk(scope.tree);assert.equal(nodes.some(node=>node.type==='textarea'),false);assert.match(text(scope.tree),/元数据|激活状态/)
 const recover=nodes.find(node=>node.type==='button'&&text(node)==='恢复上次规则事务');assert.ok(recover);recover.props.onClick();await new Promise(setImmediate)
 assert.equal(calls[0].op,'recover');assert.equal(calls[0].body.confirm,true);assert.equal(calls[0].body.recoveryId,id)
})
