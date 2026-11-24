import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { RedteamStore } from '../package/lib/redteam/store-core.js'
import { projectSlotsFor } from '../package/lib/redteam/personal-project-slots.mjs'

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-quota-diagnostics-'))
  const store = new RedteamStore(root), a = store.openEngagement('project-A', [], { bindCurrent: false })
  for (const id of ['root-a','root-b','root-c']) store.sessionBindings.bind([id], a.id)
  t.after(() => { store.close(); fs.rmSync(root, { recursive: true, force: true }) })
  return { root, store, a }
}

test('An incomplete root reports scoped progress and still refuses new reservations', async t => {
  const { store, a } = fixture(t)
  const ctx = { get: () => ({ listDescendants: async id => id === 'root-b' ? [{ kind: 'diagnostic', reason: 'SYNTHETIC_SECRET' }] : [] }) }
  const slots = projectSlotsFor(store), result = await slots.status(ctx, a.id)
  assert.equal(result.ok, false); assert.equal(result.used, null); assert.equal(result.free, null)
  assert.equal(result.quota_check?.total, 3); assert.equal(result.quota_check.completed, 2)
  assert.equal(result.quota_check.kind, 'incomplete-branch')
  assert.deepEqual(result.quota_check.failed, [{ rootSession: 'root-b', kind: 'incomplete-branch' }])
  assert.ok(Date.parse(result.quota_check.observedAt)); assert.doesNotMatch(JSON.stringify(result), /SYNTHETIC_SECRET/)
  const acquired = await slots.execute(ctx, { action: 'acquire', label: 'must-refuse' }, { agent: { session: { id: 'root-a', header: {} } } })
  assert.equal(acquired.ok, false); assert.equal(acquired.slot, undefined); assert.equal(acquired.quota_check.kind, 'incomplete-branch')
})

test('Registry exceptions retain a failing root and category without raw exception text', async t => {
  const { store, a } = fixture(t)
  const result = await projectSlotsFor(store).status({ get: () => ({ listDescendants: async id => {
    if (id === 'root-b') throw new Error('SYNTHETIC_SECRET_TOKEN'); return []
  } }) }, a.id)
  assert.equal(result.ok, false); assert.equal(result.quota_check?.kind, 'registry-error')
  assert.equal(result.quota_check.failed[0].rootSession, 'root-b')
  assert.doesNotMatch(JSON.stringify(result), /SYNTHETIC_SECRET_TOKEN/)
})

test('Deadline diagnostics distinguish pending roots and remain immutable after late replies', async t => {
  const { store, a } = fixture(t), pending = []; let deadline
  t.mock.method(globalThis, 'setTimeout', (fn, ms) => { assert.equal(ms, 5000); deadline = fn; return 0 })
  const request = projectSlotsFor(store).status({ get: () => ({ listDescendants: id => new Promise(resolve => pending.push({ id, resolve })) }) }, a.id)
  await Promise.resolve(); await Promise.resolve(); assert.equal(typeof deadline, 'function'); deadline()
  const result = await request
  assert.equal(result.ok, false); assert.equal(result.quota_check?.kind, 'timeout')
  assert.equal(result.quota_check.total, 3); assert.equal(result.quota_check.completed, 0)
  assert.deepEqual(result.quota_check.pendingRoots.slice().sort(), ['root-a','root-b','root-c'])
  assert.equal(result.quota_check.unconfirmed, 3); assert.deepEqual(result.quota_check.failed, [])
  const snapshot = structuredClone(result.quota_check)
  for (const row of pending) row.resolve([])
  await Promise.resolve(); await Promise.resolve(); assert.deepEqual(result.quota_check, snapshot)
})

test('Invalid global settings input is explicitly rejected before any settings write', async t => {
  const { apply } = await import('../package/lib/redteam/ui.js'), { root, store } = fixture(t)
  let route
  apply({ redteam: store, __dshpEnvAdaptPreStep: true, connection: { admit: () => ({ peer: { principal: { kind: 'owner' } } }) },
    effect: fn => fn(), webServer: { register: spec => { route = spec } } })
  const data = Buffer.from(JSON.stringify({ op: 'setAgentsMax', max: [9] }))
  const req = { method: 'POST', headers: { host: '127.0.0.1:49224', origin: 'http://127.0.0.1:49224', 'content-type': 'application/json' }, socket: {},
    on(event, fn) { if (event === 'data') fn(data); if (event === 'end') fn(); return this } }
  const res = { writeHead(status) { this.status = status }, end(data) { this.body = JSON.parse(data) } }
  await route.handler(req, res)
  assert.equal(res.body.ok, false); assert.equal(res.body.outcome, 'rejected')
  assert.equal(fs.existsSync(path.join(root, 'settings.json')), false)
})

test('Registry error objects cannot spoof internal failure categories or another root', async t => {
  const { store, a } = fixture(t)
  const result = await projectSlotsFor(store).status({ get: () => ({ listDescendants: async id => {
    if (id === 'root-b') throw { quotaKind: 'timeout', quotaRoot: 'OTHER_PROJECT_ROOT', message: 'SYNTHETIC_SECRET' }; return []
  } }) }, a.id)
  assert.equal(result.ok, false); assert.equal(result.quota_check.kind, 'registry-error')
  assert.equal(result.quota_check.failed[0].rootSession, 'root-b')
  assert.doesNotMatch(JSON.stringify(result), /OTHER_PROJECT_ROOT|SYNTHETIC_SECRET/)
})
