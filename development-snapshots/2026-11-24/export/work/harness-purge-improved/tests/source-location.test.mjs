import {deepSemgrepProfile} from '../package/lib/redteam/personal-semgrep-profile.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {parseScanOutput,securityFor} from '../package/lib/redteam/personal-security-workbench.mjs';
import {RedteamStore} from '../package/lib/redteam/store-core.js';
import {jointModelWire} from '../package/lib/redteam/personal-joint-review.mjs';
const hash=v=>createHash('sha256').update(v).digest('hex');
const url=new URL('../package/lib/redteam/personal-security-source-location.mjs',import.meta.url);
async function api(){assert.ok(fs.existsSync(url),'Missing bounded source-location binder');return import(url)}
const rule='policy.harness.python.dynamic-code-namespace';
function scanner(source,needle='eval(value, scope)',index=0){
 const raw=Buffer.from(source);let offset=-1;
 for(let i=0;i<=index;i++)offset=raw.indexOf(needle,offset+1);
 assert.ok(offset>=0);const point=n=>{const prefix=raw.subarray(0,n),lf=prefix.lastIndexOf(10);return{line:prefix.filter(b=>b===10).length+1,col:n-lf,offset:n}};
 return{check_id:rule,path:'/src/app.py',start:point(offset),end:point(offset+Buffer.byteLength(needle)),extra:{message:'synthetic sink','severity':'WARNING'}};
}
function fixture(source){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'source-location-')));fs.writeFileSync(path.join(root,'app.py'),source);
 return{root,snapshot:{id:'a'.repeat(64),sourceRoot:root,files:[{path:'app.py',sha256:hash(Buffer.from(source)),bytes:Buffer.byteLength(source),redacted:false}]},close(){fs.rmSync(root,{recursive:true,force:true})}};
}
test('Semgrep parsing retains exact byte spans and rejects redacted control identities',()=>{
 const raw=scanner('"中文字🙂"; eval(value, scope)\r\n');raw.start.rawSource='SECRET_SCANNER_LINE';raw.extra.lines='SECRET_SCANNER_LINE';
 const parsed=parseScanOutput('semgrep',{results:[raw],errors:[],paths:{scanned:['/src/app.py']}});
 const start={line:raw.start.line,col:raw.start.col,offset:raw.start.offset};
 assert.deepEqual(parsed.findings[0].scannerSpan,{version:1,path:'app.py',start,end:raw.end});
 assert.equal(JSON.stringify(parsed).includes('SECRET_SCANNER_LINE'),false);
 const hidden=parseScanOutput('semgrep',{results:[{...raw,path:'/src/PRIVATE_NAME.py'}],errors:[]},['PRIVATE_NAME']);
 assert.equal(hidden.findings[0].scannerSpan,undefined);
});
test('Missing, negative, oversized or contradictory spans retain warnings without fabricated precision',()=>{
 for(const mutate of [r=>delete r.end,r=>r.start.offset=-1,r=>r.start.col=true,r=>r.end.offset=1048577,r=>r.end.offset=r.start.offset]){
  const row=scanner('eval(value, scope)\n');mutate(row);
  const parsed=parseScanOutput('semgrep',{results:[row],errors:[],paths:{scanned:['/src/app.py']}});
  assert.equal(parsed.findings.length,1);assert.equal(parsed.findings[0].scannerSpan,undefined);
 }
});
test('Managed bindings cross-check raw UTF8 and CRLF bytes with snapshot identity',async()=>{
 const {bindSemgrepSourceLocations}=await api();
 for(const source of ['"中文字🙂"; eval(value, scope)\n','\t"中文字🙂"; eval(value, scope)\r\n']){
  const f=fixture(source);try{
   const raw=scanner(source),parsed=parseScanOutput('semgrep',{results:[raw],errors:[],paths:{scanned:['/src/app.py']}}),before=JSON.stringify(parsed.findings);
   const r=bindSemgrepSourceLocations(f.snapshot,parsed.findings),loc=r.findings[0].sourceLocation;
   assert.equal(loc.state,'bound');assert.equal(loc.scope,'managed-source-copy');assert.equal(loc.sourceSha256,hash(Buffer.from(source)));assert.equal(loc.snapshotId,f.snapshot.id);
   assert.deepEqual(loc.start,raw.start);assert.deepEqual(loc.end,raw.end);assert.equal(r.summary.bound,1);assert.equal(JSON.stringify(parsed.findings),before);
   assert.equal(JSON.stringify(loc).includes('中文字'),false,'source text must not be stored');
  }finally{f.close()}
 }
});
test('Changed bytes, shifted offsets and symlinks cannot inherit exact source identity',async()=>{
 const {bindSemgrepSourceLocations}=await api(),source='eval(value, scope)\n';
 for(const variant of ['bytes','same-size','offset','symlink','hardlink','location']){
  const f=fixture(source);try{
   const parsed=parseScanOutput('semgrep',{results:[scanner(source)],errors:[],paths:{scanned:['/src/app.py']}});
   if(variant==='bytes')fs.writeFileSync(path.join(f.root,'app.py'),source+'# changed\n');
   if(variant==='same-size')fs.writeFileSync(path.join(f.root,'app.py'),source.replace('value','VALUE'));
   if(variant==='offset')parsed.findings[0].scannerSpan.start.offset++;
   if(variant==='symlink'){fs.renameSync(path.join(f.root,'app.py'),path.join(f.root,'other.py'));fs.symlinkSync('other.py',path.join(f.root,'app.py'))}
   if(variant==='hardlink')fs.linkSync(path.join(f.root,'app.py'),path.join(f.root,'linked.py'));
   if(variant==='location')parsed.findings[0].location='other.py:1';
   const r=bindSemgrepSourceLocations(f.snapshot,parsed.findings);assert.equal(r.findings[0].sourceLocation.state,'unavailable');assert.equal(r.summary.bound,0);assert.equal(r.findings.length,1);
   assert.equal(r.findings[0].sourceLocation.reason,{'bytes':'source-unavailable','same-size':'source-digest-mismatch','offset':'source-range-mismatch','symlink':'source-unavailable','hardlink':'source-unavailable','location':'span-not-in-snapshot'}[variant]);
  }finally{f.close()}
 }
});
test('Legacy line-only input is explicitly unavailable while retaining finding status',async()=>{
 const {bindSemgrepSourceLocations}=await api(),f=fixture('eval(value, scope)\n');try{
  const r=bindSemgrepSourceLocations(f.snapshot,[{rule,location:'app.py:1',status:'unverified'}]);
  assert.equal(r.summary.unavailable,1);assert.equal(r.summary.state,'unavailable');assert.equal(r.findings[0].status,'unverified');assert.equal(r.findings[0].sourceLocation.reason,'missing-or-invalid-span');
 }finally{f.close()}
});
test('Missing or non-boolean redaction provenance cannot imply an unredacted copy',async()=>{
 const {bindSemgrepSourceLocations}=await api(),source='eval(value, scope)\n',f=fixture(source);try{
  const rows=parseScanOutput('semgrep',{results:[scanner(source)],errors:[],paths:{scanned:['/src/app.py']}}).findings;
  for(const value of [undefined,'false',0]){
   const result=bindSemgrepSourceLocations({...f.snapshot,files:[{...f.snapshot.files[0],redacted:value}]},rows);
   assert.equal(result.summary.bound,0);assert.equal(result.findings[0].sourceLocation.reason,'snapshot-unavailable');
  }
 }finally{f.close()}
});
test('Later evidence callbacks cannot replace a byte binding or append invented rows',async()=>{
 const {bindSemgrepSourceLocations}=await api(),source='eval(value, scope)\n',f=fixture(source);try{
  const rows=parseScanOutput('semgrep',{results:[scanner(source)],errors:[],paths:{scanned:['/src/app.py']}}).findings;
  const result=bindSemgrepSourceLocations(f.snapshot,rows),location=result.findings[0].sourceLocation;
  assert.throws(()=>{location.sourceSha256='b'.repeat(64)},TypeError);
  assert.throws(()=>{result.findings[0].sourceLocation={state:'bound'}},TypeError);
  assert.throws(()=>result.findings.push({rule:'invented'}),TypeError);
  assert.equal(result.findings[0].sourceLocation.sourceSha256,hash(source));
 }finally{f.close()}
});
test('A partially invalid or duplicate snapshot manifest cannot bind an earlier valid file',async()=>{
 const {bindSemgrepSourceLocations}=await api(),f=fixture('eval(value, scope)\n');try{
  const rows=parseScanOutput('semgrep',{results:[scanner('eval(value, scope)\n')],errors:[],paths:{scanned:['/src/app.py']}}).findings;
  for(const extra of [f.snapshot.files[0],{path:'other.py',sha256:'bad',bytes:0}]){
   const result=bindSemgrepSourceLocations({...f.snapshot,files:[...f.snapshot.files,extra]},rows);
   assert.equal(result.summary.bound,0);assert.equal(result.findings[0].sourceLocation.reason,'snapshot-unavailable');
  }
 }finally{f.close()}
});
test('Only numeric scanner coordinates enter stored source metadata',async()=>{
 const {bindSemgrepSourceLocations}=await api(),source='eval(value, scope)\n',f=fixture(source);try{
  const rows=parseScanOutput('semgrep',{results:[scanner(source)],errors:[],paths:{scanned:['/src/app.py']}}).findings;
  rows[0].scannerSpan.start.rawSource='UNEXPECTED_PRIVATE_SOURCE';
  const result=bindSemgrepSourceLocations(f.snapshot,rows);
  assert.equal(JSON.stringify(result.findings[0].sourceLocation).includes('UNEXPECTED_PRIVATE_SOURCE'),false);
 }finally{f.close()}
});
test('Same-line sites survive managed persistence, pagination and reload, with immutable source hashes',async()=>{
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-source-location-'))),root=path.join(base,'repo');fs.mkdirSync(root);
 const source='"中文字🙂"; eval(value, scope); eval(value, scope)\n';fs.writeFileSync(path.join(root,'app.py'),source);
 const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('source location fixture').id,bench=securityFor(store);let calls=0;
 bench.workspaceRoot=base;bench.pythonEvidence=()=>null;bench.namespaceEvidence=async()=>({summary:{version:1,state:'not-applicable',eligible:0,checked:0,observations:0,unmatched:0,retained:0,cleanupVerified:true},artifacts:[]});bench.toolStatus=()=>({semgrep:{ready:true,rules:{sha256:deepSemgrepProfile().baseRulesSha256},deepRules:{ready:true,profile:deepSemgrepProfile()},version:'fixture',admissionIdentity:'b'.repeat(64)}});
 bench.runner=async(_t,_p,options)=>{calls++;return{ruleProfile:options.ruleProfile,executedRules:options.ruleProfile&&{sha256:options.ruleProfile.rulesSha256,count:options.ruleProfile.ruleCount},...parseScanOutput('semgrep',{results:[scanner(source),scanner(source,'eval(value, scope)',1)],errors:[],paths:{scanned:['/src/app.py']}}),coverageKey:'c'.repeat(64)}};
 try{
  bench.saveScope(eng,{requestId:'source-scope-0001',revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
  const run=bench.joint.start(eng,{mode:'deep',requestId:'source-start-0001',profileRevision:1,steps:['semgrep'],budgetSeconds:30});
  const done=await bench.joint.wait(eng,{id:run.id,waitSeconds:2});assert.equal(done.task.state,'completed');assert.equal(calls,1);
  const first=bench.joint.report(eng,{id:run.id,section:'findings',limit:1});assert.equal(first.page.total,2);assert.ok(first.page.nextCursor);
  const second=bench.joint.report(eng,{id:run.id,section:'findings',limit:1,cursor:first.page.nextCursor});
  const a=first.page.items[0],b=second.page.items[0];assert.equal(a.status,'unverified');assert.equal(b.status,'unverified');assert.equal(a.sourceLocation.state,'bound');assert.equal(b.sourceLocation.state,'bound');assert.notDeepEqual(a.sourceLocation.start,b.sourceLocation.start);
  assert.deepEqual(done.task.steps[0].sourceLocations,{version:1,state:'completed',total:2,bound:2,unavailable:0});
  assert.equal(a.sourceLocation.sourceSha256,hash(source));assert.equal(a.sourceLocation.snapshotId,done.task.snapshot.id);assert.equal(bench.db(eng).prepare('SELECT COUNT(*) n FROM security_finding').get().n,0);
  const saved=bench.db(eng).prepare('SELECT data FROM security_joint_finding ORDER BY ordinal').all().map(r=>JSON.parse(r.data));assert.equal(saved.length,2);assert.deepEqual(saved[1].sourceLocation,b.sourceLocation);
  const safe=structuredClone(first);assert.equal(JSON.parse(jointModelWire(first,safe)).ok,true);safe.page.items[0].sourceLocation.sourceSha256='c'.repeat(64);assert.equal(JSON.parse(jointModelWire(first,safe)).ok,false);
  const reload=bench.joint.load(eng,run.id);assert.equal(reload.findings.length,2);assert.deepEqual(reload.findings[0].sourceLocation,a.sourceLocation);
 }finally{await bench.dispose();store.close();fs.rmSync(base,{recursive:true,force:true})}
});
test('Redacted fixture binds copy bytes and rejects the tested out-of-range original offsets',async()=>{
 for(const mode of ['copy','original']){
  const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'redacted-location-'))),root=path.join(base,'repo');fs.mkdirSync(root);
  const secret='REGISTERED_LOCATION_CANARY_'+'Z'.repeat(50),source='label="'+secret+'"; eval(value, scope); eval(value, scope)\n';fs.writeFileSync(path.join(root,'app.py'),source);
  const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('redacted location '+mode).id,bench=securityFor(store);let copy;
  store.addCredential(eng,{host:'fixture.invalid',secret_type:'api',secret_value:secret});
  bench.workspaceRoot=base;bench.pythonEvidence=()=>null;bench.namespaceEvidence=async()=>({summary:{version:1,state:'not-applicable',eligible:0,checked:0,observations:0,unmatched:0,retained:0,cleanupVerified:true},artifacts:[]});bench.toolStatus=()=>({semgrep:{ready:true,rules:{sha256:deepSemgrepProfile().baseRulesSha256},deepRules:{ready:true,profile:deepSemgrepProfile()},version:'fixture',admissionIdentity:'b'.repeat(64)}});
  bench.runner=async(_tool,profile,options)=>{copy=fs.readFileSync(path.join(profile.repoRoot,'app.py'),'utf8');assert.ok(!copy.includes(secret));const basis=mode==='copy'?copy:source;return{ruleProfile:options.ruleProfile,executedRules:options.ruleProfile&&{sha256:options.ruleProfile.rulesSha256,count:options.ruleProfile.ruleCount},...parseScanOutput('semgrep',{results:[scanner(basis),scanner(basis,'eval(value, scope)',1)],errors:[],paths:{scanned:['/src/app.py']}}),coverageKey:'c'.repeat(64)}};
  try{
   bench.saveScope(eng,{requestId:'redacted-scope-0001',revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
   const run=bench.joint.start(eng,{mode:'deep',requestId:'redacted-start-0001',profileRevision:1,steps:['semgrep'],budgetSeconds:30});
   assert.equal((await bench.joint.wait(eng,{id:run.id,waitSeconds:2})).task.state,'completed');
   const saved=bench.joint.load(eng,run.id),items=saved.findings;assert.equal(items.length,2);assert.equal(saved.snapshot.files[0].redacted,true);
   assert.equal(saved.snapshot.files[0].originalSha256,hash(source));assert.equal(saved.snapshot.files[0].sha256,hash(copy));assert.notEqual(hash(source),hash(copy));
   const persisted=bench.db(eng).prepare('SELECT data FROM security_joint_finding ORDER BY ordinal').all().map(r=>JSON.parse(r.data));assert.equal(JSON.stringify(persisted).includes(secret),false);assert.equal(JSON.stringify(persisted).includes('scannerSpan'),false);
   for(const f of items){
    assert.equal(f.status,'unverified');
    if(mode==='copy'){
     assert.equal(f.sourceLocation.state,'bound');assert.equal(f.sourceLocation.copyRedacted,true);assert.equal(f.sourceLocation.sourceSha256,hash(copy));assert.equal(f.sourceLocation.byteLength,Buffer.byteLength(copy));
     assert.notEqual(f.sourceLocation.start.offset,scanner(source).start.offset);
    }else{assert.equal(f.sourceLocation.state,'unavailable');assert.equal(f.sourceLocation.reason,'source-range-mismatch');assert.equal(f.sourceLocation.start,undefined)}
   }
  }finally{await bench.dispose();store.close();fs.rmSync(base,{recursive:true,force:true})}
 }
});

test('Execution IDs survive managed database, model wire and report pagination',async()=>{
 const {bindPythonExecutionPoints}=await import('../package/lib/redteam/personal-python-evidence.mjs');
 const {digest}=await import('../../../scripts/review_quality_gate.mjs');
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'joint-execution-id-'))),root=path.join(base,'repo');fs.mkdirSync(root);
 const source='"中文😀"; eval(value); eval(value)\r\n';fs.writeFileSync(path.join(root,'app.py'),source);
 const store=new RedteamStore(path.join(base,'store')),eng=store.openEngagement('execution IDs fixture').id,bench=securityFor(store),pointIds=[];
 bench.workspaceRoot=base;bench.namespaceEvidence=async()=>({summary:{version:1,state:'not-applicable',eligible:0,checked:0,observations:0,unmatched:0,retained:0,cleanupVerified:true},artifacts:[]});
 bench.toolStatus=()=>({semgrep:{ready:true,rules:{sha256:deepSemgrepProfile().baseRulesSha256},deepRules:{ready:true,profile:deepSemgrepProfile()},version:'fixture',admissionIdentity:'b'.repeat(64)}});
 bench.runner=async(_t,_p,options)=>({ruleProfile:options.ruleProfile,executedRules:options.ruleProfile&&{sha256:options.ruleProfile.rulesSha256,count:options.ruleProfile.ruleCount},...parseScanOutput('semgrep',{results:[0,1].map(i=>({...scanner(source,'eval(value)',i),check_id:'policy.harness.python.eval'})),errors:[],paths:{scanned:['/src/app.py']}}),coverageKey:'c'.repeat(64)});
 bench.pythonEvidence=(snapshot,findings)=>({state:'completed',artifacts:[],findingLocations:findings.map((f,index)=>{const l=f.sourceLocation,core={sourceSha256:l.sourceSha256,callee:'eval',call:{start:l.start,end:l.end}},p={...core,id:digest(core),builtinIdentity:'unverified',argument:null};pointIds.push(p.id);return{index,state:'bound',rule:f.rule,path:l.path,scannerSpan:{start:l.start,end:l.end},pointId:p.id,point:p}})});
 try{
  bench.saveScope(eng,{requestId:'point-scope-0001',revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
  const run=bench.joint.start(eng,{mode:'deep',requestId:'point-start-0001',profileRevision:1,steps:['semgrep'],budgetSeconds:30});const done=await bench.joint.wait(eng,{id:run.id,waitSeconds:2});assert.equal(done.task.state,'completed');
  const first=bench.joint.report(eng,{id:run.id,section:'findings',limit:1}),second=bench.joint.report(eng,{id:run.id,section:'findings',limit:1,cursor:first.page.nextCursor});
  assert.notEqual(pointIds[0],pointIds[1]);assert.equal(first.page.items[0].pointId,pointIds[0]);assert.equal(second.page.items[0].pointId,pointIds[1]);assert.deepEqual(done.task.steps[0].executionLocations,{version:1,total:2,bound:2,unmatched:0});
  const saved=bench.db(eng).prepare('SELECT data FROM security_joint_finding ORDER BY ordinal').all().map(r=>JSON.parse(r.data));assert.deepEqual(saved.map(r=>r.pointId),pointIds);
  const reload=bench.joint.load(eng,run.id);assert.deepEqual(reload.findings.map(r=>r.pointId),pointIds);
  const safe=structuredClone(first);assert.equal(JSON.parse(jointModelWire(first,safe)).ok,true);safe.page.items[0].pointId='f'.repeat(64);assert.equal(JSON.parse(jointModelWire(first,safe)).ok,false);
  const items=bindPythonExecutionPoints([{...first.page.items[0],rule:'policy.harness.python.eval'}],null);assert.equal(items.findings[0].executionMapping.state,'unmatched');
 }finally{await bench.dispose();store.close();fs.rmSync(base,{recursive:true,force:true})}
});
