import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import childProcess from 'node:child_process'
import {syncBuiltinESMExports} from 'node:module'
import * as snapshots from '../package/lib/redteam/personal-review-snapshot.mjs'
import {redactText,redactKnownText} from '../package/lib/redteam/personal-evidence-redaction.mjs'
import {RedteamStore} from '../package/lib/redteam/store-core.js'
import {SecurityWorkbench} from '../package/lib/redteam/personal-security-workbench.mjs'
function fixture(t){const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'snapshot-cancel-'))),repo=path.join(root,'repo');fs.mkdirSync(repo);t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return{root,repo,profile:{repoRoot:repo,revision:1,expiresAt:'2099-01-01T00:00:00Z'}}}
function api(){assert.equal(typeof snapshots.createReviewSnapshotAsync,'function','cancellable snapshot capture exists');return snapshots.createReviewSnapshotAsync}
test('async snapshots preserve synchronous identities, redaction, exclusions and nonexecution',async t=>{
 const capture=api(),f=fixture(t),marker=path.join(f.root,'must-not-execute')
 fs.writeFileSync(path.join(f.repo,'app.py'),"password='SYNTHETIC_STATIC'\nnormal='unchanged'\n")
 fs.writeFileSync(path.join(f.repo,'app.mjs'),'import fs from "node:fs";fs.writeFileSync('+JSON.stringify(marker)+', "bad");const token="SYNTHETIC_DYNAMIC";\n')
 fs.writeFileSync(path.join(f.repo,'data.json'),JSON.stringify({normal:'SYNTHETIC_REGISTERED',public_key:'unchanged'}));fs.writeFileSync(path.join(f.repo,'.env'),'synthetic excluded')
 const options={sanitize:(v,o)=>redactText(v,['SYNTHETIC_REGISTERED'],o),sanitizeKnown:v=>redactKnownText(v,['SYNTHETIC_REGISTERED'])}
 const sync=snapshots.createReviewSnapshot(f.profile,path.join(f.root,'sync'),options)
 const asyncResult=await capture(f.profile,path.join(f.root,'async'),{...options,deadline:performance.now()+15000})
 assert.equal(asyncResult.id,sync.id);assert.deepEqual(asyncResult.files,sync.files);assert.deepEqual(asyncResult.excluded,sync.excluded)
 assert.equal(snapshots.verifyReviewSnapshot(asyncResult),true);assert.equal(fs.existsSync(marker),false)
})
test('already-aborted and expired snapshot requests do not create a copy',async t=>{
 const capture=api(),f=fixture(t),c=new AbortController();fs.writeFileSync(path.join(f.repo,'app.py'),'print(1)\n');c.abort()
 for(const [name,options] of [['cancel',{signal:c.signal}],['deadline',{deadline:performance.now()-1}]]){
  const target=path.join(f.root,name);await assert.rejects(()=>capture(f.profile,target,options),/取消|期限|预算/);assert.equal(fs.existsSync(target),false)
 }
})
test('snapshot refusal never removes a target directory it did not create',async t=>{
 const capture=api(),f=fixture(t),target=path.join(f.root,'existing');fs.writeFileSync(path.join(f.repo,'app.py'),'print(1)\n');fs.mkdirSync(target);fs.writeFileSync(path.join(target,'keep.txt'),'synthetic existing data')
 await assert.rejects(()=>capture(f.profile,target),/EEXIST|exist/i);assert.equal(fs.readFileSync(path.join(target,'keep.txt'),'utf8'),'synthetic existing data')
})
test('cancellation waits for the parser child to close, removes partial copy and leaves source bytes unchanged',async t=>{
 const capture=api(),f=fixture(t),controller=new AbortController();let child,closed=false;const spawn=childProcess.spawn
 const source="SECRET_KEY='SYNTHETIC_OWNED'\n";fs.writeFileSync(path.join(f.repo,'app.py'),source)
 childProcess.spawn=function(command,...args){const result=spawn.call(this,command,...args);if(command==='/usr/bin/python3'){child=result;result.once('spawn',()=>controller.abort());result.once('close',()=>{closed=true})}return result};syncBuiltinESMExports()
 try{await assert.rejects(()=>capture(f.profile,path.join(f.root,'partial'),{signal:controller.signal,deadline:performance.now()+5000}),/取消/)}finally{childProcess.spawn=spawn;syncBuiltinESMExports()}
 assert.ok(child);assert.equal(closed,true);assert.equal(fs.existsSync(path.join(f.root,'partial')),false);assert.equal(fs.readFileSync(path.join(f.repo,'app.py'),'utf8'),source)
 assert.throws(()=>process.kill(child.pid,0),/ESRCH|No such process/)
})
test('a timer can cancel a 500-file Python snapshot without running queued scanners',async t=>{
 const capture=api(),f=fixture(t),controller=new AbortController();for(let i=0;i<500;i++)fs.writeFileSync(path.join(f.repo,String(i).padStart(4,'0')+'.py'),'ordinary = "synthetic"\n')
 const started=performance.now(),timer=setTimeout(()=>controller.abort(),25)
 try{await assert.rejects(()=>capture(f.profile,path.join(f.root,'many'),{signal:controller.signal,deadline:started+5000}),/取消/)}finally{clearTimeout(timer)}
 assert.ok(performance.now()-started<2500,'cancellation must yield between files and reap its child')
 assert.equal(fs.existsSync(path.join(f.root,'many')),false)
})
test('actual joint cancellation during AST parsing settles the original task before any scanner starts',async t=>{
 for(const failCleanup of [false,true]){
 const f=fixture(t),store=new RedteamStore(path.join(f.root,'facts')),eng=store.openEngagement('synthetic joint').id;let scanners=0,closed=false,cancelling
 fs.writeFileSync(path.join(f.repo,'app.py'),'ordinary = "synthetic"\n')
 const bench=new SecurityWorkbench(store,{workspaceRoot:f.root,toolStatus:()=>({semgrep:{ready:true}}),runner:async()=>{scanners++;return{findings:[],complete:true,coverageKey:'fixture'}}})
 bench.saveScope(eng,{requestId:'scope-cancel-ast',...f.profile,revision:0,expiresAt:new Date(Date.now()+3600000).toISOString(),tools:['semgrep'],confirm:true})
 const spawn=childProcess.spawn,remove=fs.rmSync;let run
 childProcess.spawn=function(command,...args){const child=spawn.call(this,command,...args);if(command==='/usr/bin/python3'){child.once('spawn',()=>{cancelling=bench.joint.cancel(eng,{id:run.id})});child.once('close',()=>{closed=true})}return child};fs.rmSync=function(file,...args){if(failCleanup&&run&&String(file)===path.join(store.dirOf(eng),'runs','joint',run.id))throw Object.assign(Error('synthetic cleanup EACCES'),{code:'EACCES'});return remove.call(this,file,...args)};syncBuiltinESMExports()
 try{run=bench.joint.start(eng,{requestId:'joint-cancel-ast',profileRevision:1,steps:['semgrep']});await bench.joint.active.promise;const result=await cancelling;assert.equal(result.task.state,failCleanup?'unconfirmed':'cancelled');assert.equal(result.task.cleanupVerified,!failCleanup);if(failCleanup)assert.equal(bench.blocked,true);assert.equal(closed,true);assert.equal(scanners,0)}finally{childProcess.spawn=spawn;fs.rmSync=remove;syncBuiltinESMExports();await bench.dispose();await store.close()}
 }
})
test('a failed partial-copy cleanup is reported instead of being hidden by the cancellation error',async t=>{
 const capture=api(),f=fixture(t),controller=new AbortController(),target=path.join(f.root,'unclean'),spawn=childProcess.spawn,remove=fs.rmSync
 fs.writeFileSync(path.join(f.repo,'app.py'),'ordinary="synthetic"\n')
 childProcess.spawn=function(command,...args){const child=spawn.call(this,command,...args);if(command==='/usr/bin/python3')child.once('spawn',()=>controller.abort());return child}
 fs.rmSync=function(file,...args){if(String(file)===target)throw Object.assign(Error('synthetic cleanup EACCES'),{code:'EACCES'});return remove.call(this,file,...args)};syncBuiltinESMExports()
 try{await assert.rejects(()=>capture(f.profile,target,{signal:controller.signal}),e=>e.code==='SNAPSHOT_CLEANUP_UNCONFIRMED')}finally{childProcess.spawn=spawn;fs.rmSync=remove;syncBuiltinESMExports()}
 assert.equal(fs.existsSync(target),true)
})
