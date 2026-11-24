import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, realpathSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { RedteamStore, applyScoreCaps } from '../package/lib/redteam/store-core.js'

const RULE = 9002

function fixture(t, caps, { disabled = [], rule = RULE } = {}) {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), 'inert-score-cap-')))
  const store = new RedteamStore(dir)
  t.after(async () => {
    await store.close()
    rmSync(dir, { recursive: true, force: true })
  })
  const id = store.openEngagement('Inert cap conflict').id
  const db = store.db(id)
  const points = caps.map((cap, index) => {
    const point = store.saveScorePoint(id, {
      name: 'Inert tier ' + index, category: 'OTHER', enabled: !disabled.includes(index), points: 1,
    })
    db.prepare("UPDATE score_point SET cap=?,rule=?,dedup_scope='none' WHERE id=?").run(cap, rule, point.id)
    return point.id
  })
  const add = (index, pointsValue) => store.addScoreHit(id, {
    point_id: points[index], points: pointsValue, target: 'inert.invalid:443', evidence: 'inert',
  })
  const views = () => ({ board: store.listScorePoints(id), chain: store.scoreChain(id), report: store.scoreReport(id) })
  return { store, db, id, points, add, views }
}

function assertViews(views, total, conflicts) {
  const { board, chain, report } = views
  assert.equal(board.summary.achievedPoints, total, 'board total')
  assert.equal(chain.summary.points, total, 'chain total')
  assert.equal(report.summary.points, total, 'report total')
  assert.deepEqual(board.summary.capConflicts, conflicts, 'board conflicts')
  assert.deepEqual(chain.summary.capConflicts, conflicts, 'chain conflicts')
  assert.deepEqual(report.summary.capConflicts, conflicts, 'report conflicts')
}

const conflict = (configuredCaps, effectiveCap = 10) => ({ rule: RULE, configuredCaps, effectiveCap })

for (const reversed of [false, true]) {
  test('shared 10/15 cap follows the strictest declaration in both read orders: ' + reversed, t => {
    const f = fixture(t, [10, 15])
    const hits = reversed ? [[1, 7], [0, 8]] : [[0, 8], [1, 7]]
    const receipts = hits.map(([index, points]) => f.add(index, points))
    const views = f.views()
    assertViews(views, 8, [conflict([10, 15])])
    assert.deepEqual(receipts[1].summary.capConflicts, [conflict([10, 15])])
    assert.match(receipts[1].warning, /9002.*10.*15.*10/)
    const excluded = views.chain.items.find(row => row.points === 7)
    assert.equal(excluded.rule_cap, 10)
    assert.match(excluded.capped_reason, /cap \(10 pts\)/)
    assert.deepEqual(views.board.items.filter(p => f.points.includes(p.id)).map(p => p.effective_cap), [10, 10])
    assert.equal(views.board.ruleGroups.find(g => g.code === 'OTHER').capSum, 10)
    assert.match(views.report.markdown, /9002.*10.*15.*10/)
    assert.match(views.report.markdown, /scoring group has used 8\/10 pts/)
    assert.deepEqual(f.points.map(id => f.db.prepare('SELECT cap FROM score_point WHERE id=?').get(id).cap), [10, 15])
  })
}

test('unhit declarations apply and zero never bypasses a positive shared cap', t => {
  const f = fixture(t, [10, 0, 15])
  assertViews(f.views(), 0, [conflict([0, 10, 15])])
  const receipt = f.add(1, 12)
  assert.equal(receipt.counted, false)
  assert.match(receipt.warning, /unlimited/i)
  assertViews(f.views(), 0, [conflict([0, 10, 15])])
})

test('a disabled point is excluded from active declarations, an all-unlimited rule still accumulates', t => {
  const f = fixture(t, [10, 0, 0], { disabled: [0] })
  f.add(0, 500)
  f.add(1, 8)
  f.add(2, 7)
  assertViews(f.views(), 15, [])
})

test('separate points without a rule number keep their own caps', t => {
  const f = fixture(t, [10, 15], { rule: null })
  f.add(0, 8)
  f.add(1, 7)
  assertViews(f.views(), 15, [])
  assert.deepEqual(f.views().board.items.filter(p => f.points.includes(p.id)).map(p => p.effective_cap), [10, 15])
})

test('legacy code-only evaluation selects a shared cap before dedup discards a declaration', () => {
  const meta = new Map([
    ['a', { rule: RULE, cap: 10, dedup_scope: 'target' }],
    ['b', { rule: RULE, cap: 15, dedup_scope: 'target' }],
  ])
  const rows = [{ id: 1, code: 'a', points: 8 }, { id: 2, code: 'b', points: 12 }]
  for (const order of [rows, [...rows].reverse()]) {
    const result = applyScoreCaps(order, meta)
    assert.deepEqual(result.capConflicts, [conflict([10, 15])])
    assert.deepEqual(result.items.map(x => [x.id, x.capped_reason_kind, x.rule_cap]).sort(),
      [[1, 'dedup', 10], [2, 'cap', 10]])
  }
})

test('score and chain tools distinguish limited, unlimited and disabled alongside shared conflicts', async t => {
  const f = fixture(t, [10, 15, 7, 0], { disabled: [2] })
  f.db.prepare('UPDATE score_point SET rule=NULL WHERE id=?').run(f.points[3])
  f.add(0, 8)
  f.add(1, 7)
  f.add(2, 9)
  f.add(3, 1)
  const source = readFileSync(new URL('../package/lib/redteam/tools.js', import.meta.url), 'utf8')
  const read = async name => {
    const at = source.indexOf("    name: '" + name + "',")
    const slice = source.slice(source.lastIndexOf('  ctx.tools.register(', at), source.indexOf('  ctx.tools.register(', at))
    const register = new Function('ctx','reviewedTool','defineTool','resolveEngagement','store',slice)
    let tool
    register({ tools: { register: value => { tool = value } } }, x => x, x => x, (_s,_e,id) => id, f.store)
    return JSON.parse(await tool.execute({ engagement: f.id }, {}))
  }
  const board = await read('redteam_score_list')
  const chain = await read('redteam_attack_chain')
  assert.deepEqual(board.summary.capConflicts, [conflict([10, 15])])
  const limited = board.items.find(p => p.id === f.points[1])
  assert.deepEqual([limited.cap_status, limited.cap, limited.effective_cap], ['limited', 15, 10])
  const disabled = board.items.find(p => p.id === f.points[2])
  assert.deepEqual([disabled.cap_status, disabled.enabled, disabled.cap, disabled.effective_cap, disabled.cap_used, disabled.counted],
    ['disabled', false, 7, null, null, 0])
  const unlimited = board.items.find(p => p.id === f.points[3])
  assert.deepEqual([unlimited.cap_status, unlimited.enabled, unlimited.effective_cap], ['unlimited', true, 0])
  assert.equal(f.views().chain.items.find(row => row.point_id === f.points[2]).rule_cap, null)
  assert.deepEqual(chain.capConflicts, [conflict([10, 15])])
  assert.equal(chain.totals.points, 9)
  const hits = new Map(chain.stages.flatMap(stage => stage.scored).map(hit => [hit.point, hit]))
  assert.deepEqual([hits.get('Inert tier 1').cap_status, hits.get('Inert tier 1').rule_cap, hits.get('Inert tier 1').counted],
    ['limited', 10, false])
  assert.deepEqual([hits.get('Inert tier 2').cap_status, hits.get('Inert tier 2').rule_cap, hits.get('Inert tier 2').counted],
    ['disabled', null, false])
  assert.deepEqual([hits.get('Inert tier 3').cap_status, hits.get('Inert tier 3').rule_cap, hits.get('Inert tier 3').counted],
    ['unlimited', 0, true])
})

test('report keeps project-wide cap conflicts and totals across detail pages', t => {
  const f = fixture(t, [10, 15])
  f.add(0, 4)
  f.add(0, 3)
  f.add(1, 2)
  const full = f.store.scoreReport(f.id)
  const first = f.store.scoreReport(f.id, { limit: 1, offset: 0 })
  const next = f.store.scoreReport(f.id, { limit: 1, offset: 1 })
  assert.equal(full.summary.points, 9)
  for (const page of [first, next]) {
    assert.deepEqual(page.summary.capConflicts, [conflict([10, 15])])
    assert.equal(page.summary.points, 9)
    assert.equal(page.markdown, full.markdown)
    assert.equal(page.items.length, 1)
  }
  assert.notEqual(first.items[0].id, next.items[0].id)
})
