import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {RedteamStore} from '../package/lib/redteam/store-core.js';
import {SecurityWorkbench,executeSecurityOp,securityFor} from '../package/lib/redteam/personal-security-workbench.mjs';

async function fixture(){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'security-page-'))),store=new RedteamStore(path.join(root,'facts'));store.openEngagement('a');store.openEngagement('b');
 const bench=securityFor(store);bench.toolStatus=()=>({semgrep:{ready:true,version:'fixture'},trivy:{ready:true,version:'fixture'},zap:{ready:true,version:'fixture'}});const db=bench.db('a');
 const run=db.prepare('INSERT INTO security_run(id,request_id,request_hash,tool,profile_revision,state,started_at,complete,details) VALUES(?,?,?,?,?,?,?,?,?)');
 for(let i=1;i<=45;i++)run.run('run-'+String(i).padStart(3,'0'),'request-'+i,'hash','semgrep',1,'completed','2026-10-30T10:00:00.000Z',1,'{}');
 const finding=db.prepare('INSERT INTO security_finding(fingerprint,tool,rule,title,severity,location,evidence,status,first_run,last_run,coverage_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)');
 for(let i=1;i<=620;i++)finding.run('fingerprint-'+i,i%2?'semgrep':'trivy','fixture.rule',i===600?'literal %_ marker':'Fixture '+i,i%3?'medium':'high','fixture-'+i+'.js:1','synthetic evidence',i%5?'unverified':'confirmed','run-001','run-045','fixture');
 return{store,bench,db,finding,run,close:async()=>{await bench.dispose();await store.close();fs.rmSync(root,{recursive:true,force:true})}};
}
test('UI keyset pages read every stored finding and task beyond former preview caps without duplicates',async()=>{
 const f=await fixture();try{
  let runCursor=null,findingCursor=null,runs=[],findings=[],pages=0,runsDone=false,findingsDone=false;
  do{
   const value=await executeSecurityOp(f.store,{op:'securityStatus',engagement:'a',pages:{runs:{cursor:runCursor,limit:7},findings:{cursor:findingCursor,limit:73}}});assert.equal(value.ok,true,value.error);assert.ok(value.pagination,'UI pagination metadata missing');
   if(!runsDone)runs.push(...value.runs.map(row=>row.id));if(!findingsDone)findings.push(...value.findings.map(row=>row.id));
   assert.equal(value.totalRuns,45);assert.equal(value.totalFindings,620);assert.equal(value.pagination.runs.total,45);assert.equal(value.pagination.findings.total,620);
   if(!runsDone){runCursor=value.pagination.runs.nextCursor;runsDone=!runCursor}if(!findingsDone){findingCursor=value.pagination.findings.nextCursor;findingsDone=!findingCursor}pages++;
  }while((!runsDone||!findingsDone)&&pages<20);
  assert.equal(runs.length,45);assert.equal(new Set(runs).size,45);assert.equal(findings.length,620);assert.equal(new Set(findings).size,620);assert.equal(findings[0],620);assert.equal(findings.at(-1),1);
 }finally{await f.close()}
});
test('New insertions stay outside an in-progress page window and appear after refresh',async()=>{
 const f=await fixture();try{
  const first=f.bench.read('a',{}, {runs:{limit:5},findings:{limit:50}});assert.ok(first.pagination,'UI pagination metadata missing');
  f.finding.run('new-item','semgrep','fixture.rule','New','high','new.js:1','synthetic','unverified','run-045','run-045','fixture');
  const second=f.bench.read('a',{}, {runs:{limit:5},findings:{limit:50,cursor:first.pagination.findings.nextCursor}});assert.equal(second.pagination.findings.total,620);assert.equal(second.findings[0].id,570);assert.ok(second.findings.every(row=>row.id<=620));
  const refreshed=f.bench.read('a',{}, {runs:{},findings:{}});assert.equal(refreshed.pagination.findings.total,621);assert.equal(refreshed.findings[0].id,621);
 }finally{await f.close()}
});
test('Filters execute before counts and pagination, and search wildcard characters are literal',async()=>{
 const f=await fixture();try{
  const value=f.bench.read('a',{}, {runs:{tool:'trivy'},findings:{tool:'semgrep',status:'unverified',severity:'high',limit:13}});assert.ok(value.pagination,'UI pagination metadata missing');assert.equal(value.runs.length,0);assert.equal(value.pagination.runs.total,0);assert.equal(value.totalRuns,45);assert.equal(value.totalFindings,620);assert.equal(value.pagination.findings.total,82);assert.ok(value.findings.every(row=>row.tool==='semgrep'&&row.status==='unverified'&&row.severity==='high'));
  const literal=f.bench.read('a',{}, {runs:{},findings:{search:'%_'}});assert.equal(literal.pagination.findings.total,1);assert.equal(literal.findings[0].id,600);
 }finally{await f.close()}
});
test('Cursors cannot cross collections, filters or projects and unsafe query shapes are rejected without mutation',async()=>{
 const f=await fixture();try{
  const first=f.bench.read('a',{}, {runs:{limit:5},findings:{limit:50}});assert.ok(first.pagination,'UI pagination metadata missing');const cursor=first.pagination.findings.nextCursor;
  for(const [engagement,pages] of [['b',{findings:{cursor}}],['a',{runs:{cursor}}],['a',{findings:{cursor,status:'fixed'}}],['a',{findings:{cursor:'A'.repeat(3000)}}],['a',{findings:{limit:1000}}],['a',{findings:{status:['unverified']}}],['a',{findings:{unknown:true}}],['a',{unknown:{}}]]){
   const value=await executeSecurityOp(f.store,{op:'securityStatus',engagement,pages});assert.equal(value.ok,false,JSON.stringify(pages));
  }
  assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM security_finding').get().n,620);assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM security_event').get().n,0);
  const model=await executeSecurityOp(f.store,{op:'securityStatus',engagement:'a',pages:{findings:{}}},{model:true});assert.equal(model.ok,false,'UI query must not silently expand model status');
 }finally{await f.close()}
});
test('Paged or filtered history retains the current running task and independent comparison choices',async()=>{
 const f=await fixture();try{
  f.db.prepare("UPDATE security_run SET state='running',complete=0 WHERE id='run-001'").run();
  const value=f.bench.read('a',{}, {runs:{state:'completed',limit:5},findings:{status:'fixed'}});assert.ok(value.pagination,'UI pagination metadata missing');assert.equal(value.activeRun.id,'run-001');assert.equal(value.activeRun.state,'running');assert.ok(!value.runs.some(row=>row.id==='run-001'));assert.equal(value.comparisonRuns.length,30);assert.ok(value.comparisonRuns.every(row=>row.state==='completed'&&row.complete===1));assert.equal(value.findings.length,0);assert.equal(value.pagination.findings.total,0);
  const legacy=f.bench.read('a');assert.equal(legacy.runs.length,30);assert.equal(legacy.findings.length,500);assert.equal(legacy.pagination,undefined);
 }finally{await f.close()}
});
