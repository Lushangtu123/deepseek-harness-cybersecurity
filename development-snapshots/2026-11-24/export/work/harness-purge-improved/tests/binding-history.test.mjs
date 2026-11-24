import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { RedteamStore } from '../package/lib/redteam/store-core.js'
import { projectSlotsFor } from '../package/lib/redteam/personal-project-slots.mjs'

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-binding-history-'))
  const store = new RedteamStore(root)
  t.after(() => { store.close(); fs.rmSync(root, { recursive: true, force: true }) })
  const a = store.openEngagement('project-A', [], { bindCurrent: false })
  const b = store.openEngagement('project-B', [], { bindCurrent: false })
  return { root, store, a, b }
}

test('A project with 129 historical roots checks every root with bounded registry concurrency', async t => {
  const { store, a } = fixture(t)
  for (let i = 0; i < 129; i++) store.sessionBindings.bind(['root-' + String(i).padStart(3, '0')], a.id)
  let active = 0, peak = 0; const reads = []
  const ctx = { get: () => ({ listDescendants: async id => {
    active++; peak = Math.max(peak, active); reads.push(id)
    await new Promise(setImmediate); active--
    return id === 'root-128' ? [{ kind: 'child', id: 'last-live-child', activity: 'running' }] : []
  } }) }
  const result = await projectSlotsFor(store).status(ctx, a.id)
  assert.equal(result.ok, true, result.error)
  assert.equal(result.used, 1); assert.equal(result.free, 2)
  assert.equal(new Set(reads).size, 129); assert.ok(peak <= 8, 'Registry reads must be bounded')
})

test('Binding history pages isolate projects and reversible archive never changes quota roots', async t => {
  const { store, a, b } = fixture(t)
  for (let i = 0; i < 70; i++) store.sessionBindings.bind(['a-' + String(i).padStart(3, '0')], a.id)
  store.sessionBindings.bind(['b-only'], b.id)
  const first = store.sessionBindings.rootPageFor(a.id)
  assert.equal(first.items.length, 32); assert.ok(first.next)
  assert.equal(first.items.some(row => row.rootSession === 'b-only'), false)
  const before = store.sessionBindings.rootsFor(a.id)
  const rootSession = first.items[0].rootSession
  store.sessionBindings.setRootArchived(a.id, rootSession, true)
  assert.equal(store.sessionBindings.find([rootSession]), a.id)
  assert.deepEqual(store.sessionBindings.rootsFor(a.id), before)
  assert.equal(store.sessionBindings.rootPageFor(a.id).items[0].archived, true)
  assert.equal(store.sessionBindings.rootPageFor(a.id, { onlyUnarchived: true }).items.some(row => row.rootSession === rootSession), false)
  assert.throws(() => store.sessionBindings.setRootArchived(b.id, rootSession, true), /不存在|绑定/)
  assert.throws(() => store.sessionBindings.setRootArchived(a.id, rootSession, 'true'), /归档|状态/)
  store.sessionBindings.setRootArchived(a.id, rootSession, false)
  assert.equal(store.sessionBindings.rootPageFor(a.id).items[0].archived, false)
  const ctx = { get: () => ({ listDescendants: async id => id === rootSession ? [{ kind: 'child', id: 'still-counted', activity: 'running' }] : [] }) }
  store.sessionBindings.setRootArchived(a.id, rootSession, true)
  assert.equal((await projectSlotsFor(store).status(ctx, a.id)).used, 1)
})

test('Archive endpoints retain official owner and origin protection and preserve bindings', async t => {
  const { apply } = await import('../package/lib/redteam/ui.js')
  const { store, a } = fixture(t); store.sessionBindings.bind(['archive-root'], a.id)
  let route, owner = true
  apply({ redteam: store, __dshpEnvAdaptPreStep: true, connection: { admit: () => owner ? { peer: { principal: { kind: 'owner' } } } : { rejection: 401 } },
    effect: fn => fn(), webServer: { register: spec => { route = spec } } })
  const send = async (body, origin = 'http://127.0.0.1:49224') => {
    const data = Buffer.from(JSON.stringify(body))
    const req = { method: 'POST', headers: { host: '127.0.0.1:49224', origin, 'content-type': 'application/json' }, socket: {},
      on(event, fn) { if (event === 'data') fn(data); if (event === 'end') fn(); return this } }
    const res = { writeHead(status) { this.status = status }, end(data) { this.body = JSON.parse(data) } }
    await route.handler(req, res); return res
  }
  const request = { op: 'setBindingArchived', engagement: a.id, rootSession: 'archive-root', archived: true }
  owner = false; assert.equal((await send(request)).status, 401)
  owner = true; assert.equal((await send(request, 'https://outside.invalid')).status, 403)
  assert.equal(store.sessionBindings.rootPageFor(a.id).items[0].archived, false)
  const changed = await send(request); assert.equal(changed.body.ok, true, changed.body.error)
  assert.equal(changed.body.engagement, a.id)
  const page = await send({ op: 'bindingHistory', engagement: a.id })
  assert.equal(page.body.items[0].archived, true)
  assert.equal(store.sessionBindings.find(['archive-root']), a.id)
  assert.deepEqual(store.sessionBindings.rootsFor(a.id), ['archive-root'])
})
