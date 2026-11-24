import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
const url=new URL('../package/lib/redteam/personal-security-runtime.mjs',import.meta.url);
const sha=value=>createHash('sha256').update(value).digest('hex');
const clock=Date.parse('2026-10-29T22:00:00Z');
async function fixture(){
 assert.ok(fs.existsSync(url),'Runtime inspector is missing');const {createRuntimeInspector}=await import(url);
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'security-runtime-'))),ids={semgrep:'a',trivy:'b',zap:'c'},rules=Buffer.from('{"rules":[{"id":"fixture.rule","languages":["python"]}]}'),database=Buffer.alloc(4096,5),metadata={Version:2,UpdatedAt:'2026-10-29T19:00:00Z',NextUpdate:'2026-10-30T19:00:00Z'};
 fs.mkdirSync(path.join(root,'cache/db'),{recursive:true});fs.writeFileSync(path.join(root,'rules.json'),rules);fs.writeFileSync(path.join(root,'cache/db/trivy.db'),database);fs.writeFileSync(path.join(root,'cache/db/metadata.json'),JSON.stringify(metadata));
 const manifest={schemaVersion:1,rulesSha256:sha(rules),tools:Object.entries(ids).map(([tool,id])=>({tool,imageId:'sha256:'+id.repeat(64),imageRef:'personal-security/'+tool+'@sha256:'+id.repeat(64),version:'1.2.3'})),database:{ready:true,metadata,fileSha256:sha(database),fileBytes:database.length}};
 const save=()=>fs.writeFileSync(path.join(root,'images.json'),JSON.stringify(manifest));save();let inspections=0,time=clock,refsSeen,images=manifest.tools.map(row=>({id:row.imageId,architecture:'arm64',os:'linux'}));
 const inspector=createRuntimeInspector({root,now:()=>time,inspectImages:refs=>{refsSeen=refs;inspections++;return{available:true,images}}});
 return{root,manifest,save,inspector,get inspections(){return inspections},get refsSeen(){return refsSeen},advance:ms=>{time+=ms},setImages:value=>{images=value},close:()=>fs.rmSync(root,{recursive:true,force:true})};
}
test('Readiness verifies pinned images, rules and DB rather than trusting ready flags',async()=>{
 const f=await fixture();try{const first=f.inspector.read();assert.ok(Object.values(first).every(row=>row.ready));assert.deepEqual(f.refsSeen,f.manifest.tools.map(row=>row.imageId),'Saved/loaded images must be checked by local content ID without a repository digest alias');assert.equal(first.trivy.database.state,'fresh');f.setImages([]);const missing=f.inspector.read({force:true});assert.ok(Object.values(missing).every(row=>!row.ready));assert.match(missing.semgrep.reason,/镜像/)}finally{f.close()}
});
test('Missing, replaced and symbolic runtime assets cannot be reported ready',async()=>{
 for(const defect of ['db-missing','db-corrupt','db-link','rules-corrupt','manifest-shape']){const f=await fixture();try{const file=path.join(f.root,'cache/db/trivy.db');if(defect==='db-missing')fs.unlinkSync(file);if(defect==='db-corrupt')fs.writeFileSync(file,Buffer.alloc(4096,9));if(defect==='db-link'){fs.renameSync(file,file+'.owned');fs.symlinkSync(file+'.owned',file)}if(defect==='rules-corrupt')fs.writeFileSync(path.join(f.root,'rules.json'),'changed');if(defect==='manifest-shape')fs.writeFileSync(path.join(f.root,'images.json'),'{"tools":{}}');const result=f.inspector.read();assert.equal((defect==='rules-corrupt'?result.semgrep:result.trivy).ready,false,defect)}finally{f.close()}}
});
test('Evidence cache is bounded, explicit recheck bypasses it and stale DB is a visible warning',async()=>{
 const f=await fixture();try{const first=f.inspector.read();assert.equal(f.inspections,1);assert.equal(first.trivy.cached,false);assert.equal(f.inspector.read().trivy.cached,true);assert.equal(f.inspections,1);f.inspector.read({force:true});assert.equal(f.inspections,2);f.advance(8*86400000);const old=f.inspector.read();assert.equal(f.inspections,3);assert.equal(old.trivy.database.state,'stale');assert.equal(old.trivy.ready,true);assert.match(old.trivy.warning,/7天/)}finally{f.close()}
});
test('Future and contradictory database metadata remain unconfirmed',async()=>{
 for(const metadata of [{Version:2,UpdatedAt:'2030-01-01T00:00:00Z',NextUpdate:'2030-01-02T00:00:00Z'},{Version:2,UpdatedAt:'2026-10-29T19:00:00Z',NextUpdate:'2026-10-28T19:00:00Z'}]){const f=await fixture();try{f.manifest.database.metadata=metadata;f.save();fs.writeFileSync(path.join(f.root,'cache/db/metadata.json'),JSON.stringify(metadata));assert.equal(f.inspector.read().trivy.ready,false)}finally{f.close()}}
});
test('Database metadata changes invalidate cached evidence and unsafe image references cannot become arguments',async()=>{
 const f=await fixture();try{
  f.inspector.read();const file=path.join(f.root,'cache/db/trivy.db'),before=fs.statSync(file);fs.writeFileSync(file,Buffer.alloc(4096,7));
  // Linux can assign identical timestamps to rapid same-size writes. This case
  // checks metadata invalidation, so make that condition explicit without sleeps.
  fs.utimesSync(file,before.atime,new Date(before.mtimeMs+1000));assert.notEqual(fs.statSync(file).mtimeMs,before.mtimeMs);
  const changed=f.inspector.read();assert.equal(changed.trivy.cached,false);assert.equal(changed.trivy.ready,false);
  f.manifest.tools[0].imageRef='--privileged';f.save();assert.ok(Object.values(f.inspector.read()).every(row=>!row.ready))
 }finally{f.close()}
});
test('The standalone preflight refuses to inspect the Mac host as a dedicated VM',async()=>{
 if(process.platform==='linux'&&os.homedir()==='/home/purge')return;
 const {preflight}=await import('../package/scripts/security-runtime-preflight.mjs');const result=preflight();assert.equal(result.ok,false);assert.equal(result.readOnly,true);assert.deepEqual(result.tools,{});assert.match(result.error,/专用VM/);
});
test('Numeric, date-only and normalized impossible DB timestamps are refused',async()=>{
 for(const metadata of [{Version:2,UpdatedAt:2026,NextUpdate:2027},{Version:2,UpdatedAt:'2026-10-29',NextUpdate:'2026-10-30'},{Version:2,UpdatedAt:'2026-02-30T00:00:00Z',NextUpdate:'2026-03-05T00:00:00Z'}]){const f=await fixture();try{f.manifest.database.metadata=metadata;f.save();fs.writeFileSync(path.join(f.root,'cache/db/metadata.json'),JSON.stringify(metadata));assert.equal(f.inspector.read().trivy.ready,false,JSON.stringify(metadata))}finally{f.close()}}
});
test('An unfinished maintenance marker blocks cached readiness until explicit recovery',async()=>{
 const f=await fixture();try{assert.equal(f.inspector.read().trivy.ready,true);fs.writeFileSync(path.join(f.root,'maintenance.json'),JSON.stringify({state:'updating'}));const blocked=f.inspector.read();assert.ok(Object.values(blocked).every(row=>!row.ready));assert.match(blocked.trivy.reason,/维护/);assert.equal(f.inspector.read({force:true,maintenanceValidation:true}).trivy.ready,true);assert.equal(f.inspector.read().trivy.ready,false);fs.unlinkSync(path.join(f.root,'maintenance.json'));assert.equal(f.inspector.read({force:true}).trivy.ready,true)}finally{f.close()}
});
test('Hash-verified local rules expose their real version, count and language coverage',async()=>{
 const f=await fixture();try{
  const rules={rules:[{id:'harness.fixture.python',languages:['python']},{id:'harness.fixture.js',languages:['javascript','typescript']}]};const raw=JSON.stringify(rules);fs.writeFileSync(path.join(f.root,'rules.json'),raw);f.manifest.rulesSha256=sha(raw);f.manifest.rulesVersion='local-reviewed-2';f.save();
  assert.deepEqual(f.inspector.read({force:true}).semgrep.rules,{sha256:sha(raw),version:'local-reviewed-2',count:2,languages:['javascript','python','typescript']});
  for(const invalid of [{rules:[]},{rules:[rules.rules[0],rules.rules[0]]},{rules:[{id:'bad',languages:['unknown-language']}]},[]]){const bytes=JSON.stringify(invalid);fs.writeFileSync(path.join(f.root,'rules.json'),bytes);f.manifest.rulesSha256=sha(bytes);f.save();assert.equal(f.inspector.read({force:true}).semgrep.ready,false)}
 }finally{f.close()}
});
