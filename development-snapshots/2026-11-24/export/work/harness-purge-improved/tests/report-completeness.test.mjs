import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { RedteamStore } from '../package/lib/redteam/store-core.js'
for (const variant of ['distinct','self-created','disabled','late-winner']) test('Complete report evaluates every hit before '+variant+' filtering', t => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'report-complete-')),store=new RedteamStore(root)
  t.after(()=>{store.close();fs.rmSync(root,{recursive:true,force:true})})
  const id=store.openEngagement('owned '+variant,[],{bindCurrent:false}).id,db=store.db(id)
  const point=store.saveScorePoint(id,{code:'owned-valid',name:'owned valid',points:1})
  const disabled=variant==='disabled'?store.saveScorePoint(id,{code:'owned-off',name:'owned off',points:1,enabled:false}):null
  const insert=db.prepare('INSERT INTO score_hit(point_id,target,evidence,points,self_created,recorded_at) VALUES(?,?,?,?,?,?)')
  db.exec('BEGIN')
  for(let i=0;i<2001;i++)insert.run(disabled?.id||point.id,variant==='late-winner'?'same.invalid:80':'owned-'+i+'.invalid:80','owned prefix '+i,1,variant==='self-created'?1:0,'2026-10-28T00:00:00Z')
  insert.run(point.id,'late-winner'===variant?'same.invalid:80':'last.invalid:80','owned last',variant==='distinct'?1:50,0,'2026-10-28T00:00:00Z');db.exec('COMMIT')
  const earned=store.listScorePoints(id).items.find(x=>x.id===point.id).earned,r=store.scoreReport(id)
  assert.equal(r.summary.points,earned);assert.equal(r.summary.count,variant==='distinct'?2002:1)
  assert.equal(r.coverage.totalHits,2002);assert.equal(r.coverage.complete,true);assert.equal(r.coverage.markdownComplete,true)
  if(variant==='distinct'){
    const page=store.scoreReport(id,{limit:1,offset:1})
    assert.equal(page.items.length,1);assert.equal(page.items[0].id,r.items[1].id)
    assert.equal(page.summary.points,earned);assert.equal(page.coverage.totalItems,2002)
    assert.equal(page.coverage.returnedItems,1);assert.equal(page.coverage.complete,false);assert.equal(page.coverage.nextOffset,2)
    assert.equal(page.markdown,r.markdown,'Detail pagination must never truncate export')
  }
})
