import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {RedteamStore,dispatch} from '../package/lib/redteam/store-core.js'
function fixture(t,{count=501,dedup='none',cap=0}={}){const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'chain-coverage-'))),store=new RedteamStore(dir);t.after(async()=>{await store.close();fs.rmSync(dir,{recursive:true,force:true})});const id=store.openEngagement('inert chain coverage').id,p=store.saveScorePoint(id,{name:'inert point',code:'inert-chain',points:1}),db=store.db(id);db.prepare('UPDATE score_point SET dedup_scope=?,cap=?,rule=901 WHERE id=?').run(dedup,cap,p.id);const insert=db.prepare('INSERT INTO score_hit(point_id,points,multiplier,target,evidence,recorded_at) VALUES(?,?,?,?,?,?)');db.exec('BEGIN');for(let i=0;i<count;i++)insert.run(p.id,1,1,dedup==='target'?'synthetic.invalid':'host-'+i+'.synthetic.invalid','inert '+i,'2026-11-04T00:00:00Z');db.exec('COMMIT');return{store,id,db,pid:p.id}}
function stagePoints(x){return x.stages.reduce((n,s)=>n+s.points,0)}
test('501 hits expose window coverage while keeping project totals',t=>{const f=fixture(t),first=f.store.scoreChain(f.id),last=f.store.scoreChain(f.id,{offset:500});assert.equal(first.summary.points,501);assert.equal(first.summary.hits,501);assert.equal(first.items.length,500);assert.equal(stagePoints(first),500);assert.deepEqual(first.coverage,{totalHits:501,returnedHits:500,offset:0,limit:500,nextOffset:500,complete:false,returnedPoints:500,returnedCountedHits:500,totalsScope:'project',stagesScope:'window'});assert.equal(last.items.length,1);assert.equal(last.items[0].id,501);assert.equal(last.items[0].nth_of_point,501);assert.equal(last.summary.points,501);assert.equal(stagePoints(last),1);assert.equal(last.coverage.nextOffset,null);assert.equal(last.coverage.offset,500)})
test('a later global dedup winner outside the window prevents an earlier low hit from scoring',t=>{const f=fixture(t,{dedup:'target'});f.db.prepare('UPDATE score_hit SET points=70 WHERE id=501').run();const first=f.store.scoreChain(f.id),last=f.store.scoreChain(f.id,{offset:500});assert.equal(first.summary.points,70);assert.equal(stagePoints(first),0);assert.ok(first.items.every(x=>x.capped&&x.counted===false));assert.equal(first.coverage.returnedPoints,0);assert.equal(last.items[0].points,70);assert.equal(last.items[0].counted,true);assert.equal(stagePoints(last),70)})
test('a later cap winner outside the window has the same full-project classification as the board',t=>{const f=fixture(t,{cap:70});f.db.prepare('UPDATE score_hit SET points=70 WHERE id=501').run();const first=f.store.scoreChain(f.id),last=f.store.scoreChain(f.id,{offset:500});assert.equal(first.summary.points,70);assert.equal(stagePoints(first),0);assert.ok(first.items.every(x=>x.capped_reason_kind==='cap'));assert.equal(last.items[0].counted,true);assert.equal(stagePoints(last),70)})
test('points first recorded after500 are not incorrectly marked missing',t=>{const f=fixture(t),p=f.store.saveScorePoint(f.id,{name:'inert later point',code:'inert-later',points:3});f.db.prepare('UPDATE score_hit SET point_id=?,points=3 WHERE id=501').run(p.id);const first=f.store.scoreChain(f.id);assert.ok(first.achieved.some(x=>x.id===p.id));assert.ok(!first.missing.some(x=>x.id===p.id));assert.equal(first.summary.hits,501)})
test('empty windows and projects have explicit bounded coverage',t=>{const f=fixture(t,{count:0});const empty=f.store.scoreChain(f.id);assert.equal(empty.coverage.complete,true);assert.equal(empty.coverage.returnedHits,0);assert.equal(empty.coverage.nextOffset,null);assert.equal(empty.summary.points,0);const far=f.store.scoreChain(f.id,{offset:1000});assert.equal(far.items.length,0);assert.equal(far.coverage.returnedHits,0);assert.equal(far.coverage.nextOffset,null)})
test('invalid pagination is rejected before an unbounded SQL limit; valid large limits remain clamped',t=>{const f=fixture(t,{count:2});for(const options of [{limit:-1},{limit:0},{limit:1.5},{limit:NaN},{limit:Infinity},{offset:-1},{offset:0.5},{offset:Infinity}])assert.throws(()=>f.store.scoreChain(f.id,options),/pagination|分页/i);const x=f.store.scoreChain(f.id,{limit:3000});assert.equal(x.coverage.limit,2000);assert.equal(x.items.length,2);assert.equal(x.coverage.complete,true)})
test('dispatch retains coverage and window request fields',t=>{const f=fixture(t,{count:3});const x=dispatch(f.store,{op:'scoreChain',engagement:f.id,limit:1,offset:1});assert.equal(x.ok,true);assert.equal(x.items[0].id,2);assert.equal(x.coverage.offset,1);assert.equal(x.coverage.nextOffset,2);assert.equal(x.summary.hits,3)})
for(const mode of ['cap','dedup'])test('panel exclusion summary names '+mode+' without labelling all exclusions duplicate',t=>{const f=fixture(t,{count:2,dedup:mode==='dedup'?'target':'none',cap:mode==='cap'?1:0}),p=f.store.listScorePoints(f.id).items.find(x=>x.id===f.pid);assert.equal(p.capped,1);assert.match(p.service_summary,mode==='cap'?/规则上限 1 次不计分/:/重复记录 1 次不计分/);if(mode==='cap')assert.doesNotMatch(p.service_summary,/duplicate|重复记录/)})

function chainTool(store) {
  const source = fs.readFileSync(new URL('../package/lib/redteam/tools.js', import.meta.url), 'utf8')
  const marker = "    name: 'redteam_attack_chain',"
  const start = source.lastIndexOf('  ctx.tools.register(', source.indexOf(marker))
  const end = source.indexOf('  ctx.tools.register(', source.indexOf(marker))
  const register = new Function('ctx', 'reviewedTool', 'defineTool', 'resolveEngagement', 'store', source.slice(start, end))
  let tool
  register({ tools: { register: value => { tool = value } } }, x => x, x => x, (_s, _e, id) => id, store)
  return tool
}

test('model tool exposes project totals, coverage and global scoring flags on the selected page', async t => {
  const f = fixture(t, { dedup: 'target' })
  f.db.prepare('UPDATE score_hit SET points=70 WHERE id=501').run()
  const tool = chainTool(f.store)
  assert.ok(tool.parameters.offset)
  const first = JSON.parse(await tool.execute({ engagement: f.id, limit: 1, offset: 0 }, {}))
  const last = JSON.parse(await tool.execute({ engagement: f.id, limit: 1, offset: 500 }, {}))
  assert.equal(first.totals.hits, 501)
  assert.equal(first.totals.points, 70)
  assert.equal(first.coverage.nextOffset, 1)
  assert.equal(first.stages.flatMap(s => s.scored)[0].counted, false)
  assert.equal(first.stages.flatMap(s => s.scored)[0].capped_reason_kind, 'dedup')
  assert.equal(last.coverage.offset, 500)
  assert.equal(last.stages.flatMap(s => s.scored)[0].counted, true)
})

test('chain and tool distinguish excluded hits from counted zero and expose an undefined project maximum', async t => {
  const f = fixture(t, { count: 5 })
  const disabled = f.store.saveScorePoint(f.id, { name: 'inert disabled', code: 'inert-disabled', points: 7 })
  f.db.prepare('UPDATE score_point SET enabled=0 WHERE id=?').run(disabled.id)
  f.db.prepare('UPDATE score_hit SET point_id=? WHERE id IN (2,3)').run(disabled.id)
  f.db.prepare('UPDATE score_hit SET self_created=1 WHERE id IN (1,3)').run()
  f.db.prepare('UPDATE score_hit SET points=0 WHERE id=4').run()
  f.db.prepare('UPDATE score_hit SET point_id=999999 WHERE id=5').run()
  const expected = ['self_created', 'disabled', 'self_created', null, 'missing_point']
  const chain = f.store.scoreChain(f.id)
  assert.equal(chain.summary.totalPoints, null)
  assert.equal(chain.summary.countedHits, 1)
  assert.equal(chain.summary.points, 0)
  assert.deepEqual(chain.items.map(x => x.exclusion_reason), expected)
  const result = JSON.parse(await chainTool(f.store).execute({ engagement: f.id }, {}))
  assert.equal(result.totals.totalPoints, null)
  const hits = result.stages.flatMap(x => x.scored)
  assert.deepEqual(hits.map(x => x.exclusion_reason), expected)
  assert.deepEqual(hits.map(x => [x.cap_status, x.rule_cap]), [
    ['unlimited', 0], ['disabled', null], ['disabled', null], ['unlimited', 0], ['unknown', null],
  ])
})

test('cap explanation remains distinct from deduplication', t => {
  const f = fixture(t, { count: 2, cap: 1 })
  const excluded = f.store.scoreChain(f.id).items[1]
  assert.equal(excluded.exclusion_reason, 'cap')
  assert.match(excluded.capped_reason, /cap \(1 pts\)/)
})

for (const [scope, label] of [['service', 'same service'], ['system', 'same system instance'], ['target', 'whole target']]) {
  test('deduplication explanation follows the evaluator scope: ' + scope, t => {
    const f = fixture(t, { count: 0, dedup: scope })
    const add = (points, target = 'inert.invalid:443') => f.store.addScoreHit(f.id, {
      point_id: f.pid, points, target, evidence: 'synthetic',
    })
    add(5)
    const lower = add(1, scope === 'target' ? 'other.invalid:443' : undefined)
    const reason = new RegExp('highest-scoring hit in the ' + label)
    const board = f.store.listScorePoints(f.id)
    assert.equal(board.summary.achievedPoints, 5)
    assert.match(board.summary.latestCapped.reason, reason)
    const hit = f.store.scoreChain(f.id).items.find(x => x.id === lower.id)
    assert.equal(hit.exclusion_reason, 'dedup')
    assert.match(hit.capped_reason, reason)
    assert.match(lower.warning, reason)
    assert.equal(f.store.listScorePoints(f.id).items.find(x => x.id === f.pid).hits.find(x => x.id === lower.id).capped_reason,
      hit.capped_reason)
    const higher = add(7)
    assert.equal(higher.summary.achievedPoints, 7)
    assert.doesNotMatch(higher.warning, /same service|asset\+port|total score will not increase/)
  })
}
