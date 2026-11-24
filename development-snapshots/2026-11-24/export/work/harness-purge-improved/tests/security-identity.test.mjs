import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {RedteamStore} from '../package/lib/redteam/store-core.js';
import {SecurityWorkbench,parseScanOutput,buildScanPlan} from '../package/lib/redteam/personal-security-workbench.mjs';
import {createHash} from 'node:crypto';
import {createScanSnapshot,compareScanSnapshots} from '../package/lib/redteam/personal-security-comparison.mjs';
const pkg=(name,version='1.0',pkgPath='')=>({VulnerabilityID:'CVE-2026-0000',Title:'Synthetic package issue',Severity:'HIGH',PkgName:name,InstalledVersion:version,FixedVersion:'9.0',PkgPath:pkgPath,PkgID:name+'@'+version+':'+pkgPath,PkgIdentifier:{PURL:'pkg:pypi/'+name+'@'+version}});
const parsed=rows=>parseScanOutput('trivy',{Results:[{Target:'requirements.txt',Vulnerabilities:rows}]});
async function fixture(){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'security-identity-'))),workspace=path.join(root,'workspace'),repo=path.join(workspace,'repo');fs.mkdirSync(repo,{recursive:true});fs.writeFileSync(path.join(repo,'requirements.txt'),'# synthetic\n');const store=new RedteamStore(path.join(root,'facts'));store.openEngagement('A');let answer,count=0;const bench=new SecurityWorkbench(store,{workspaceRoot:workspace,runner:async()=>answer,toolStatus:()=>({trivy:{ready:true,version:'fixture'}})});
 bench.saveScope('a',{requestId:'identity-scope-request',revision:0,repoRoot:repo,tools:['trivy'],url:null,expiresAt:new Date(Date.now()+3600000).toISOString(),confirm:true});
 return{root,repo,store,bench,async run(rows,extra={}){answer={...parsed(rows),coverageKey:'identity-test-policy',...extra.result};const run=bench.start('a',{requestId:'identity-run-'+(++count),profileRevision:1,tool:'trivy',...extra.input});await bench.active.promise;return run.id},async close(){await bench.dispose();await store.close();fs.rmSync(root,{recursive:true,force:true})}}
}
test('Trivy preserves distinct packages, versions and paths sharing a CVE/file, while exact duplicates stay one record',async()=>{
 const f=await fixture();try{
  const rows=[pkg('alpha'),pkg('beta'),pkg('alpha','2.0'),pkg('alpha','1.0','nested/site-packages')];const base=await f.run([]),current=await f.run([...rows,rows[0]]);const state=f.bench.read('a');assert.equal(state.findings.length,4,'Different package components must not collapse');assert.equal(new Set(state.findings.map(v=>v.fingerprint)).size,4);assert.ok(state.findings.every(v=>v.rule==='CVE-2026-0000'&&v.location==='requirements.txt'&&v.status==='unverified'&&v.identityVersion===1));assert.equal(state.findings.filter(v=>v.subject.name==='alpha').length,3);assert.equal(f.bench.compare('a',{baseRunId:base,currentRunId:current}).summary.added,4);
  const again=await f.run(rows);assert.equal(f.bench.read('a').findings.length,4);assert.equal(f.bench.compare('a',{baseRunId:current,currentRunId:again}).summary.persisting,4);assert.match(f.bench.report('a').markdown,/alpha/);assert.match(f.bench.report('a').markdown,/nested\/site-packages/)
 }finally{await f.close()}
});
test('Package retest ignores a different package/path, but reopens an upgraded affected package family',async()=>{
 const f=await fixture();try{
  await f.run([pkg('alpha'),pkg('alpha','1.0','nested'),pkg('beta')]);let target=f.bench.read('a').findings.find(v=>v.subject.name==='alpha'&&!v.subject.path);
  const fix=()=>{target=f.bench.read('a').findings.find(v=>v.id===target.id);target=f.bench.review('a',{id:target.id,revision:target.revision,status:'confirmed',note:'Synthetic confirmation',requestId:'identity-confirm-'+target.revision});target=f.bench.review('a',{id:target.id,revision:target.revision,status:'fixed',note:'Synthetic fix recorded',requestId:'identity-fix-'+target.revision})};fix();
  await f.run([pkg('alpha','1.0','nested'),pkg('beta')],{input:{retestFindingId:target.id}});assert.equal(f.bench.read('a').findings.find(v=>v.id===target.id).status,'retest-passed','Other components must not reopen the target');
  fix();await f.run([pkg('alpha','2.0'),pkg('beta')],{input:{retestFindingId:target.id}});assert.equal(f.bench.read('a').findings.find(v=>v.id===target.id).status,'reopened','Same family at new version still vulnerable must reopen')
 }finally{await f.close()}
});
test('Legacy Trivy rows remain unchanged and ambiguous old snapshots or retests never invent package history',async()=>{
 const f=await fixture();try{
  const db=f.bench.db('a');db.prepare("INSERT INTO security_finding(fingerprint,tool,rule,title,severity,location,evidence,status,revision,first_run,last_run,coverage_key,note) VALUES('legacy','trivy','CVE-2026-0000','Legacy merged record','high','requirements.txt','old evidence','fixed',7,'old-run','old-run','identity-test-policy','Original reviewed note')").run();
  const baseline=await f.run([pkg('alpha'),pkg('beta')],{input:{retestFindingId:1}}),state=f.bench.read('a'),old=state.findings.find(v=>v.id===1);assert.equal(state.findings.length,3);assert.equal(old.identityVersion,0);assert.equal(old.subject,null);assert.equal(old.status,'fixed');assert.equal(old.revision,7);assert.equal(old.note,'Original reviewed note');assert.match(state.runs[0].details.retestOutcome,/旧Trivy/);assert.match(f.bench.report('a').markdown,/历史可能已合并/);
  const current=await f.run([pkg('alpha')]);const row=db.prepare('SELECT data FROM security_run_snapshot WHERE run_id=?').get(baseline),snapshot=JSON.parse(row.data);snapshot.schemaVersion=1;snapshot.findings=snapshot.findings.slice(0,1).map(({subject,...item})=>item);db.prepare('UPDATE security_run_snapshot SET data=? WHERE run_id=?').run(JSON.stringify(snapshot),baseline);const comparison=f.bench.compare('a',{baseRunId:baseline,currentRunId:current});assert.equal(comparison.available,false);assert.match(comparison.reason,/旧Trivy/);
  const run={id:'old-semgrep',tool:'semgrep',state:'completed',complete:1,coverage_key:'same',started_at:'2026-10-29T00:00:00Z'},v1=JSON.stringify({schemaVersion:1,findings:[],coverageFiles:['a.py']}),v2=createScanSnapshot([],['a.py']);assert.equal(compareScanSnapshots(run,{...run,id:'new-semgrep'},v1,v2).available,true)
 }finally{await f.close()}
});
test('Subject storage failure rolls back evidence, revision and new snapshot without losing the previous record',async()=>{
 const f=await fixture();try{
  await f.run([pkg('alpha')]);const before=f.bench.read('a').findings[0],db=f.bench.db('a');db.exec("CREATE TRIGGER subject_fail BEFORE INSERT ON security_finding_subject BEGIN SELECT RAISE(ABORT,'owned subject failure'); END;");const id=await f.run([{...pkg('alpha'),Title:'Must not commit'}]);const state=f.bench.read('a');assert.equal(state.runs.find(v=>v.id===id).state,'failed');assert.deepEqual(state.findings,[before]);assert.equal(db.prepare('SELECT COUNT(*) n FROM security_finding_subject').get().n,1);assert.equal(db.prepare('SELECT COUNT(*) n FROM security_run_snapshot').get().n,1)
 }finally{await f.close()}
});
test('Package identity uses full bounded metadata, ignores fix-version changes and rejects malformed package fields',()=>{
 const a=pkg('a'.repeat(240)+'alpha'),b=pkg('a'.repeat(240)+'beta');assert.notEqual(parsed([a]).findings[0].subject.key,parsed([b]).findings[0].subject.key);assert.equal(parsed([a]).findings[0].subject.key,parsed([{...a,FixedVersion:'10.0'}]).findings[0].subject.key);
 for(const change of [{PkgName:null},{PkgName:{}},{InstalledVersion:1},{PkgIdentifier:[]},{PkgIdentifier:{PURL:{}}},{PkgPath:'bad\npath'}])assert.throws(()=>parsed([{...pkg('alpha'),...change}]),/包/);
 const subject=parsed([pkg('alpha')]).findings[0].subject;assert.equal(subject.name,'alpha');assert.equal(subject.purl,'pkg:pypi/alpha@1.0');assert.equal(subject.family,parsed([pkg('alpha','2.0')]).findings[0].subject.family)
});
test('Trivy package identity and Semgrep parser-text policy are distinct from legacy coverage',()=>{
 const imageId='sha256:'+'a'.repeat(64),manifest={tools:['trivy','semgrep'].map(tool=>({tool,imageId,version:'fixture'})),rulesSha256:'b'.repeat(64),database:{digest:'database-v1'}},profile={repoRoot:'/home/purge/workspace/project'},old=tool=>createHash('sha256').update(JSON.stringify([tool,imageId,manifest.rulesSha256,manifest.database.digest,profile.repoRoot,null])).digest('hex');
 assert.notEqual(buildScanPlan('trivy',profile,'/tmp/fixture',manifest).coverageKey,old('trivy'));assert.notEqual(buildScanPlan('semgrep',profile,'/tmp/fixture',manifest).coverageKey,old('semgrep'))
});
test('Comparison package labels stay literal Markdown rather than introducing HTML or links',()=>{
 const run={id:'base-test',tool:'trivy',state:'completed',complete:1,coverage_key:'same-policy',started_at:'2026-10-29T00:00:00Z'},raw=parsed([pkg('<script>[package](https://example.invalid)')]),comparison=compareScanSnapshots(run,{...run,id:'next-test'},createScanSnapshot([],['requirements.txt']),createScanSnapshot(raw.findings,raw.coverageFiles));assert.equal(comparison.summary.added,1);assert.doesNotMatch(comparison.markdown,/<script>|\[package\]\(https:/);assert.match(comparison.markdown,/&lt;script&gt;/)
});
