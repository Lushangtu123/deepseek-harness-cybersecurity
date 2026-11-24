import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {RedteamStore,dispatch} from '../package/lib/redteam/store-core.js'
function fixture(t){const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'report-score-'))),store=new RedteamStore(root);t.after(async()=>{await store.close();fs.rmSync(root,{recursive:true,force:true})});return store}
function add(store,id,points,note){const db=store.db(id);const point=db.prepare('INSERT INTO score_point(code,name,points,cap,dedup_scope) VALUES(?,?,?,?,?)').run('synthetic-'+points,'Synthetic scoring fixture',points,0,'none');return store.addScoreHit(id,{point_id:Number(point.lastInsertRowid),points,target:'synthetic.invalid',evidence:'inert synthetic data',note})}
test('correction notes never invent prior scores or claim that an independent final review happened',t=>{
 const store=fixture(t),id=store.openEngagement('synthetic seven').id;add(store,id,7,'校正：操作者合成备注')
 for(const report of [store.scoreReport(id),dispatch(store,{op:'scoreReport',engagement:id})]){
  assert.equal(report.summary.points,7)
  assert.ok(report.markdown.includes('7 pts'))
  assert.doesNotMatch(report.markdown,/16180|16090|downgraded during final review/)
  assert.match(report.markdown,/recorded.*note|记录.*备注/i)
  assert.match(report.markdown,/historical.*not|历史.*未|不证明.*历史/i)
 }
})
test('report totals come from each project including zero and legitimately large recorded values',t=>{
 const store=fixture(t),a=store.openEngagement('synthetic empty').id,b=store.openEngagement('synthetic large').id
 assert.equal(store.scoreReport(a).summary.points,0)
 add(store,b,16180,'校正：合法入账的合成分值')
 const report=store.scoreReport(b);assert.equal(report.summary.points,16180);assert.match(report.markdown,/16180 pts/);assert.doesNotMatch(report.markdown,/16090/)
 assert.equal(store.scoreReport(a).summary.points,0);assert.doesNotMatch(store.scoreReport(a).markdown,/16180|16090/)
})
test('correction-note scores use the same effective-value calculation when explicit points are omitted',t=>{
 const store=fixture(t),id=store.openEngagement('synthetic default score').id,db=store.db(id)
 const point=db.prepare('INSERT INTO score_point(code,name,points,cap,dedup_scope) VALUES(?,?,?,?,?)').run('synthetic-default','Synthetic default scoring fixture',7,0,'none')
 store.addScoreHit(id,{point_id:Number(point.lastInsertRowid),target:'synthetic.invalid',evidence:'inert data',note:'校正：未显式覆盖默认分值'})
 const report=store.scoreReport(id),section=report.markdown.split('**Recorded correction notes**')[1].split('### 0.3')[0]
 assert.equal(report.summary.points,7);assert.match(section,/\*\*7 pts\*\*/);assert.doesNotMatch(section,/\*\*0 pts\*\*/)
})
test('correction-note effective values preserve multipliers and persisted zero',t=>{
 for(const [points,multiplier,expected] of [[null,2,14],[3,2,6],[0,3,0]]){
  const store=fixture(t),id=store.openEngagement('synthetic multiplier '+points).id,db=store.db(id)
  const point=db.prepare('INSERT INTO score_point(code,name,points,cap,dedup_scope) VALUES(?,?,?,?,?)').run('synthetic-multiplier','Synthetic multiplier fixture',7,0,'none')
  store.addScoreHit(id,{point_id:Number(point.lastInsertRowid),...(points===null?{}:{points:points||7}),target:'synthetic.invalid',evidence:'inert data',note:'校正：倍率对照'})
  db.prepare('UPDATE score_hit SET points=?,multiplier=?').run(points,multiplier)
  const report=store.scoreReport(id),section=report.markdown.split('**Recorded correction notes**')[1].split('### 0.3')[0]
  assert.equal(report.summary.points,expected);assert.ok(section.includes('**'+expected+' pts**'))
 }
})
