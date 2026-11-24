import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {syncBuiltinESMExports} from 'node:module';
import {SecurityWorkbench} from '../package/lib/redteam/personal-security-workbench.mjs';
import {RedteamStore} from '../package/lib/redteam/store-core.js';
function fixture(){
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'workspace-input-'))),root=path.join(base,'repo');fs.mkdirSync(root);
 const store=new RedteamStore(path.join(base,'state')),eng=store.openEngagement('Read-only ordinary').id;
 const bench=new SecurityWorkbench(store,{workspaceRoot:base,toolStatus:()=>({semgrep:{ready:true,admissionIdentity:'a'.repeat(64)},trivy:{ready:true,admissionIdentity:'b'.repeat(64)}}),runner:()=>{throw Error('Planning must not start a scanner')}});
 bench.saveScope(eng,{requestId:'input-scope-001',revision:0,repoRoot:root,tools:['semgrep','trivy'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
 return{base,root,store,eng,bench,async close(){await bench.dispose();await store.close();fs.rmSync(base,{recursive:true,force:true})}};
}
test('Ordinary backend planning is deterministic, content-bound and makes no copy or scanner task',async()=>{
 const f=fixture();try{
  fs.mkdirSync(path.join(f.root,'src'));fs.writeFileSync(path.join(f.root,'src/app.php'),'<?php return 1;\n');fs.writeFileSync(path.join(f.root,'composer.lock'),'{}\n');
  const first=f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan;
  assert.ok(first,'Ordinary rule plan is missing');assert.equal(first.executable,false);assert.deepEqual(first.selectedSteps.map(row=>row.tool),['semgrep','trivy']);
  assert.deepEqual(first,f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan);assert.equal(first.inventory.files,2);
  fs.writeFileSync(path.join(f.root,'src/app.php'),'<?php return 2;\n');
  const changed=f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan;assert.notEqual(changed.inputIdentity,first.inputIdentity);assert.notEqual(changed.planIdentity,first.planIdentity);
  assert.equal(fs.existsSync(path.join(f.store.dirOf(f.eng),'runs','joint')),false);assert.equal(f.bench.db(f.eng).prepare('SELECT COUNT(*) AS n FROM security_run').get().n,0);
 }finally{await f.close()}
});
test('Lock-only and unsupported projects select only relevant static tools without needing Kali',async()=>{
 const f=fixture();try{
  fs.writeFileSync(path.join(f.root,'requirements.txt'),'django==2.2.0\n');
  assert.deepEqual(f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan.selectedSteps.map(row=>row.tool),['trivy']);
  fs.unlinkSync(path.join(f.root,'requirements.txt'));fs.writeFileSync(path.join(f.root,'notes.md'),'notes');
  const plan=f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan;assert.deepEqual(plan.selectedSteps,[]);assert.ok(plan.gaps.includes('no-supported-static-input'));
 }finally{await f.close()}
});
test('A Dockerfile-only project selects Trivy and the same file is admissible to the managed copy',async()=>{
 const f=fixture();try{
  fs.writeFileSync(path.join(f.root,'Dockerfile'),'FROM scratch\nUSER root\n');
  const plan=f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan;
  assert.deepEqual(plan.selectedSteps.map(row=>row.tool),['trivy']);assert.equal(plan.inventory.files,1);
  const {createReviewSnapshot}=await import('../package/lib/redteam/personal-review-snapshot.mjs');
  const snapshot=createReviewSnapshot(f.bench.profile(f.bench.db(f.eng)),path.join(f.base,'snapshot'));
  assert.deepEqual(snapshot.files.map(file=>file.path),['Dockerfile']);
 }finally{await f.close()}
});
test('Ordinary inventory excludes hidden files, links, binary files and credential material',async()=>{
 const f=fixture();try{
  fs.writeFileSync(path.join(f.root,'app.py'),'print(1)\n');fs.writeFileSync(path.join(f.root,'.env'),'PASSWORD=TEST_ONLY');fs.writeFileSync(path.join(f.root,'binary.py'),Buffer.from([0,1]));
  fs.writeFileSync(path.join(f.root,'private.txt'),'-----BEGIN TEST PRIVATE KEY-----');fs.symlinkSync('/etc/hosts',path.join(f.root,'link.py'));
  const plan=f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan;assert.equal(plan.inventory.files,1);assert.equal(plan.inventory.excluded,4);assert.ok(!JSON.stringify(plan).includes('PASSWORD'));
 }finally{await f.close()}
});
test('An observed file mutation during the first read rejects the plan instead of hiding it as an exclusion',async t=>{
 const f=fixture();let fired=false;const original=fs.readSync;
 try{
  const target=path.join(f.root,'app.py');fs.writeFileSync(target,'print(1)\n');
  t.mock.method(fs,'readSync',(...args)=>{const result=original(...args);if(!fired){fired=true;fs.appendFileSync(target,'# changed during read\n')}return result});syncBuiltinESMExports();
  assert.throws(()=>f.bench.joint.plan(f.eng,{mode:'ordinary'}),/变化|读取|身份/);
  assert.equal(fired,true,'Mutation control did not fire');
 }finally{t.mock.restoreAll();syncBuiltinESMExports();await f.close()}
});
test('Excluded binary content still consumes the bounded first-pass read budget',async()=>{
 const f=fixture();try{
  for(let i=0;i<9;i++)fs.writeFileSync(path.join(f.root,'binary-'+i+'.txt'),Buffer.alloc(1048576));
  assert.throws(()=>f.bench.joint.plan(f.eng,{mode:'ordinary'}),/8MiB|读取上限/);
 }finally{await f.close()}
});
test('A file growing between its path stat and open cannot exceed the remaining read quota',async t=>{
 const f=fixture();let fired=false;const original=fs.openSync;
 try{
  for(let i=0;i<8;i++)fs.writeFileSync(path.join(f.root,'binary-'+i+'.txt'),Buffer.alloc(1048576));
  const target=path.join(f.root,'zz.txt');fs.writeFileSync(target,'');
  t.mock.method(fs,'openSync',(...args)=>{if(args[0]===target&&!fired){fired=true;fs.appendFileSync(target,'x')}return original(...args)});syncBuiltinESMExports();
  assert.throws(()=>f.bench.joint.plan(f.eng,{mode:'ordinary'}),/变化|读取|身份/);assert.equal(fired,true);
 }finally{t.mock.restoreAll();syncBuiltinESMExports();await f.close()}
});
test('Verification growth cannot read beyond the original accepted file sizes',async t=>{
 const f=fixture();let opens=0,readBytes=0,fired=false;const open=fs.openSync,read=fs.readSync;
 try{
  for(let i=0;i<8;i++)fs.writeFileSync(path.join(f.root,'text-'+i+'.txt'),'x'.repeat(1048576));
  const target=path.join(f.root,'zz.txt');fs.writeFileSync(target,'');
  t.mock.method(fs,'openSync',(...args)=>{if(args[0]===target&&++opens===2){fired=true;fs.writeFileSync(target,'x'.repeat(1048576))}return open(...args)});
  t.mock.method(fs,'readSync',(...args)=>{const result=read(...args);readBytes+=result;return result});syncBuiltinESMExports();
  assert.throws(()=>f.bench.joint.plan(f.eng,{mode:'ordinary'}));assert.equal(fired,true);assert.ok(readBytes<=16*1048576,'First and verification reads exceeded 16MiB');
 }finally{t.mock.restoreAll();syncBuiltinESMExports();await f.close()}
});

test('Ordinary copy binds original bytes and exclusions while allowing a redacted copy',async()=>{
 const f=fixture();try{
  const source=path.join(f.root,'note.txt');
  fs.writeFileSync(source,'original bytes');
  const {createReviewSnapshot}=await import('../package/lib/redteam/personal-review-snapshot.mjs');
  const profile=f.bench.profile(f.bench.db(f.eng));
  const {inputIdentity}=f.bench.joint.plan(f.eng,{mode:'ordinary'}).ordinaryPlan;
  const options={expectedInputIdentity:inputIdentity,sanitize:()=>'<redacted>'};
  const copy=createReviewSnapshot(profile,path.join(f.base,'match'),options);
  assert.equal(copy.redactedFiles,1);assert.notEqual(copy.files[0].originalSha256,copy.files[0].sha256);
  fs.writeFileSync(source,'different bytes');
  assert.throws(()=>createReviewSnapshot(profile,path.join(f.base,'changed'),options),/计划.*副本|副本.*计划/);
  assert.equal(fs.existsSync(path.join(f.base,'changed')),false);
  fs.writeFileSync(source,'original bytes');fs.writeFileSync(path.join(f.root,'.new'),'excluded');
  assert.throws(()=>createReviewSnapshot(profile,path.join(f.base,'excluded'),options),/计划.*副本|副本.*计划/);
 }finally{await f.close()}
});
