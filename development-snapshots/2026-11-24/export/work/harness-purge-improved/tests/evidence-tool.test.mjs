import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {DatabaseSync} from 'node:sqlite';
import {EvidenceLedger} from '../package/lib/redteam/evidence-ledger.mjs';

test('public evidence verify tool preserves engagement identity when matching a real ledger row',async()=>{
  const db=new DatabaseSync(':memory:');
  try{
    const ledger=new EvidenceLedger(db);
    const item={operation:'read',parameters:{path:'/fixture/a'},result:{text:'fixture'},
      engagement_id:'fixture-a'};
    assert.equal(ledger.record(item).ok,true);
    const source=fs.readFileSync(new URL('../package/lib/redteam/tools.js',import.meta.url),'utf8');
    const nameAt=source.indexOf("name: 'redteam_evidence_verify'");
    const start=source.lastIndexOf('  ctx.tools.register(',nameAt);
    const end=source.indexOf('\n  ctx.tools.register(',nameAt);
    let tool;
    vm.runInNewContext(source.slice(start,end),{ctx:{tools:{register:t=>{tool=t;}}},
      store:{},reviewedTool:x=>x,defineTool:x=>x,text:x=>x,resolveEngagement:()=> 'fixture-a',ledgerOf:()=>ledger});
    const result=JSON.parse(await tool.execute(item,{}));
    assert.equal(result.matched,true);
  }finally{db.close();}
});

test('public record enforces provenance and count never presents empty ledger as project safety',async()=>{
  const db=new DatabaseSync(':memory:');
  try{
    const ledger=new EvidenceLedger(db),source=fs.readFileSync(new URL('../package/lib/redteam/tools.js',import.meta.url),'utf8');
    function tool(name){
      const at=source.indexOf("name: '"+name+"'"),start=source.lastIndexOf('  ctx.tools.register(',at),end=source.indexOf('\n  ctx.tools.register(',at);
      let registered;
      vm.runInNewContext(source.slice(start,end),{ctx:{tools:{register:t=>{registered=t;}}},store:{},reviewedTool:x=>x,defineTool:x=>x,text:x=>x,resolveEngagement:()=> 'fixture-a',ledgerOf:()=>ledger,agentOf:()=> 'fixture-agent'});
      return registered;
    }
    const record=tool('redteam_evidence_record'),count=tool('redteam_unverified_count');
    const empty=JSON.parse(await count.execute({},{}));
    assert.equal(empty.unverified_count,0);
    assert.ok(empty.hint.includes('不代表项目'));
    const item={operation:'read',parameters:{path:'/fixture/a'},result:{text:'fixture'}};
    for(const patch of [{authority:'database-record'},{confidence:'derived',supporting_ev_ids:['ev_'+'0'.repeat(64)]}]) {
      assert.equal(JSON.parse(await record.execute({...item,...patch},{})).ok,false);
    }
    assert.equal(JSON.parse(await record.execute(item,{})).ok,true);
    assert.equal(JSON.parse(await count.execute({},{})).unverified_count,1);
  }finally{db.close();}
});
