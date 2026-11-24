import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, realpathSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { RedteamStore } from '../package/lib/redteam/store-core.js'

function fixture(t) {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), 'inert-score-receipts-')))
  const store = new RedteamStore(dir)
  t.after(async () => {
    await store.close()
    rmSync(dir, { recursive: true, force: true })
  })
  const id = store.openEngagement('Synthetic scoring receipts').id
  const db = store.db(id)
  const point = ({ name, code, scope = 'service', rule = null, cap = 0, enabled = true }) => {
    const { id: pid } = store.saveScorePoint(id, { name, code, enabled, points: 2 })
    db.prepare('UPDATE score_point SET dedup_scope=?, rule=?, cap=? WHERE id=?').run(scope, rule, cap, pid)
    return pid
  }
  const add = (pid, points, target = 'one.invalid:443', extra = {}) =>
    store.addScoreHit(id, { point_id: pid, points, target, evidence: 'synthetic only', ...extra })
  const views = points => {
    const board = store.listScorePoints(id)
    const chain = store.scoreChain(id)
    const report = store.scoreReport(id)
    assert.equal(board.summary.achievedPoints, points)
    assert.equal(chain.summary.points, points)
    assert.equal(report.summary.points, points)
    return { board, chain, report }
  }
  return { store, id, db, point, add, views }
}

test('two points without code use their own dedup scopes, defaults and point-local cap groups', t => {
  const f = fixture(t)
  const service = f.point({ name: 'service', cap: 6 })
  const additive = f.point({ name: 'additive', scope: 'none', cap: 10 })
  const low = f.add(service, 3)
  const high = f.add(service, 5)
  const first = f.add(additive, 4)
  const second = f.add(additive, 4)
  const { board, chain } = f.views(13)
  assert.deepEqual(chain.items.map(x => x.counted), [false, true, true, true])
  assert.equal(chain.items.find(x => x.id === low.id).capped_reason_kind, 'dedup')
  assert.equal(chain.items.find(x => x.id === high.id).rule_cap, 6)
  assert.ok(chain.items.filter(x => [first.id, second.id].includes(x.id)).every(x => x.service === null))
  const a = board.items.find(x => x.id === service)
  const b = board.items.find(x => x.id === additive)
  assert.deepEqual([a.dedup_scope, a.cap_used, b.dedup_scope, b.cap_used], ['service', 5, 'none', 8])
})

test('nullable points with an explicit shared rule compete across point IDs', t => {
  const f = fixture(t)
  const a = f.point({ name: 'first tier', scope: 'target', rule: 9001, cap: 10 })
  const b = f.point({ name: 'second tier', scope: 'target', rule: 9001, cap: 10 })
  f.add(a, 5)
  const high = f.add(b, 8, 'other.invalid:443')
  const { chain } = f.views(8)
  assert.deepEqual(chain.items.map(x => x.counted), [false, true])
  assert.equal(high.score_change.delta, 3)
})

test('the over-cap winner keeps the documented order and explains the old 5 point loss', t => {
  const f = fixture(t)
  const pid = f.point({ name: 'capped target', code: 'inert-cap', scope: 'target', rule: 9001, cap: 10 })
  const low = f.add(pid, 3)
  const old = f.add(pid, 5)
  const over = f.add(pid, 11)
  const { chain } = f.views(0)
  assert.deepEqual(old.demoted_hits.map(x => x.id), [low.id])
  assert.equal(over.counted, false)
  assert.deepEqual(over.score_change, { before: 5, after: 0, delta: -5 })
  assert.deepEqual(over.demoted_hits.map(x => [x.id, x.points, x.reason]), [[old.id, 5, 'dedup']])
  assert.match(over.warning, /cap \(10 pts\)/)
  assert.match(over.warning, /5.*0/)
  assert.deepEqual(chain.items.map(x => x.capped_reason_kind), ['dedup', 'dedup', 'cap'])
})

test('receipt includes cap reallocation and excludes disabled and self-created writes', t => {
  const f = fixture(t)
  const pid = f.point({ name: 'capped sum', code: 'inert-sum', scope: 'none', rule: 9001, cap: 10 })
  const disabled = f.point({ name: 'disabled', enabled: false })
  const a = f.add(pid, 6, 'one.invalid:443')
  f.add(pid, 4, 'two.invalid:443')
  const b = f.add(pid, 7, 'three.invalid:443')
  assert.equal(b.counted, true)
  assert.deepEqual(b.score_change, { before: 10, after: 7, delta: -3 })
  assert.deepEqual(b.demoted_hits.map(x => [x.points, x.reason]), [[4, 'cap'], [6, 'cap']])
  assert.ok(b.demoted_hits.some(x => x.id === a.id))
  const off = f.add(disabled, 5)
  assert.equal(off.counted, false)
  assert.match(off.warning, /disabled/i)
  const own = f.add(pid, 9, 'three.invalid:443', { self_created: true })
  assert.equal(own.counted, false)
  assert.deepEqual(own.score_change, { before: 7, after: 7, delta: 0 })
  f.views(7)
})

test('a newly counted older hit is reflected after an over-cap winner changes the allocation', t => {
  const f = fixture(t)
  const pid = f.point({ name: 'two services', code: 'inert-two', scope: 'service', rule: 9001, cap: 10 })
  f.add(pid, 8, 'one.invalid:443')
  const waiting = f.add(pid, 6, 'two.invalid:443')
  assert.equal(waiting.counted, false)
  const change = f.add(pid, 11, 'one.invalid:443')
  assert.deepEqual(change.score_change, { before: 8, after: 6, delta: -2 })
  assert.deepEqual(change.promoted_hits, [{ id: waiting.id, points: 6 }])
  f.views(6)
})

test('a failed receipt read rolls back the inserted hit', t => {
  const f = fixture(t)
  const pid = f.point({ name: 'transaction', code: 'inert-transaction' })
  f.add(pid, 2)
  const prepare = f.db.prepare
  f.db.prepare = function(sql) {
    if (sql.startsWith('SELECT * FROM score_point ORDER BY COALESCE')) throw new Error('inert receipt read failure')
    return prepare.call(this, sql)
  }
  try {
    assert.throws(() => f.add(pid, 5), /inert receipt read failure/)
  } finally {
    delete f.db.prepare
  }
  const { chain } = f.views(2)
  assert.equal(chain.items.length, 1)
})

test('model write tool returns the same receipt for an excluded replacement', async t => {
  const f = fixture(t)
  const pid = f.point({ name: 'model target', scope: 'target', rule: 9001, cap: 10 })
  const previous = f.add(pid, 5)
  const source = readFileSync(new URL('../package/lib/redteam/tools.js', import.meta.url), 'utf8')
  const name = source.indexOf("    name: 'redteam_score_hit',")
  const register = new Function('ctx', 'reviewedTool', 'defineTool', 'resolveEngagement', 'store',
    source.slice(source.lastIndexOf('  ctx.tools.register(', name), source.indexOf('  ctx.tools.register(', name)))
  let tool
  register({ tools: { register: value => { tool = value } } }, x => x, x => x, (_s, _e, id) => id, f.store)
  const receipt = JSON.parse(await tool.execute({
    engagement: f.id, point_id: pid, target: 'other.invalid:443', points: 11, evidence: 'synthetic',
  }, {}))
  assert.equal(receipt.ok, true)
  assert.equal(receipt.counted, false)
  assert.deepEqual(receipt.score_change, { before: 5, after: 0, delta: -5 })
  assert.deepEqual(receipt.demoted_hits.map(x => [x.id, x.reason]), [[previous.id, 'dedup']])
})
