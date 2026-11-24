import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { resolveEngagement, bindingKeyOf } from '../package/lib/redteam/personal-session-resolution.mjs'
import { RedteamStore } from '../package/lib/redteam/store-core.js'
import { installNativeEvidenceObserver } from '../package/lib/redteam/personal-evidence-receipts.mjs'
function resolver(store) {
  store.sessionLookup ??= id => ({ id, header: {} })
  return (exec, explicit) => resolveEngagement(store, { agent: { session: { id: exec.id, header: exec.parent ? { parentSession: exec.parent } : {} } } }, explicit)
}
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-binding-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  return root
}
test('An unbound session never adopts the globally active project', t => {
  const store = new RedteamStore(fixture(t)); t.after(() => store.close())
  store.openEngagement('project-B', [])
  assert.throws(() => resolver(store)({ id: 'session-A' }), /绑定|bound/)
})
test('Official-shaped nested sessions resolve the complete ancestor chain and reject conflicting grandchildren', t => {
  const store = new RedteamStore(fixture(t)); t.after(() => store.close())
  const a = store.openEngagement('project-A', []), b = store.openEngagement('project-B', [])
  const root = { id: 'root', header: {} }, child = { id: 'child', header: { parentSession: 'root' } }, grand = { id: 'grand', header: { parentSession: 'child' } }
  const sessions = new Map([root, child, grand].map(session => [session.id, session]))
  store.sessionLookup = id => sessions.get(id)
  store.sessionBindings.bind(['root'], a.id)
  assert.equal(resolveEngagement(store, { agent: { session: grand } }), a.id)
  store.sessionLookup = () => undefined
  assert.equal(bindingKeyOf({ agent: { session: grand } }, store).rootId, 'root', 'Cold descendants must preserve their real root identity')
  store.sessionBindings.bind(['grand'], b.id)
  assert.throws(() => resolveEngagement(store, { agent: { session: grand } }), /conflict|冲突/)
})
test('Two projects retain isolated bindings and records through three store restarts', t => {
  const root = fixture(t)
  let store = new RedteamStore(root)
  const a = store.openEngagement('project-A', []), b = store.openEngagement('project-B', [])
  assert.ok(store.sessionBindings, 'The store must own persistent session bindings')
  try {
    store.sessionBindings.bind(['session-A'], a.id)
    store.sessionBindings.bind(['session-B'], b.id)
    for (let restart = 0; restart < 3; restart++) {
      store.close(); store = new RedteamStore(root)
      for (const [session, expected] of [['session-A', a.id], ['session-B', b.id]]) {
        const id = resolver(store)({ id: session })
        assert.equal(id, expected)
        const db = store.db(id)
        db.exec('CREATE TABLE IF NOT EXISTS binding_canary (owner TEXT)')
        for (let n = 0; n < 25; n++) db.prepare('INSERT INTO binding_canary VALUES (?)').run(session)
        assert.equal(db.prepare('SELECT COUNT(*) AS n FROM binding_canary WHERE owner != ?').get(session).n, 0)
      }
    }
    assert.equal(store.db(a.id).prepare('SELECT COUNT(*) AS n FROM binding_canary').get().n, 75)
    assert.equal(store.db(b.id).prepare('SELECT COUNT(*) AS n FROM binding_canary').get().n, 75)
  } finally { store.close() }
})
test('Cold descendants check every persisted ancestor after intermediate rebinding', t => {
  const store = new RedteamStore(fixture(t)); t.after(() => store.close())
  const a = store.openEngagement('project-A', []), b = store.openEngagement('project-B', [])
  const chain = ['root', 'child', 'grand', 'great'].map((id, i, ids) => ({ id, header: i ? { parentSession: ids[i - 1] } : {} }))
  const sessions = new Map(chain.map(session => [session.id, session])); store.sessionLookup = id => sessions.get(id)
  store.sessionBindings.bind(['root'], a.id)
  const exec = { agent: { session: chain[3] } }
  assert.equal(resolveEngagement(store, exec), a.id)
  store.sessionBindings.bind(['root', 'child'], b.id)
  store.sessionBindings.bind(['root'], a.id)
  assert.throws(() => resolveEngagement(store, exec), /conflict|冲突/)
  store.sessionLookup = () => undefined
  assert.throws(() => resolveEngagement(store, exec), /conflict|冲突/)
})
test('A child inherits its parent binding and conflicting ancestry fails closed', t => {
  const store = new RedteamStore(fixture(t)); t.after(() => store.close())
  const a = store.openEngagement('project-A', []), b = store.openEngagement('project-B', [])
  assert.ok(store.sessionBindings)
  store.sessionBindings.bind(['parent-A'], a.id)
  assert.equal(resolver(store)({ id: 'child', parent: 'parent-A' }), a.id)
  store.sessionBindings.bind(['child'], b.id)
  assert.throws(() => resolver(store)({ id: 'child', parent: 'parent-A' }), /conflict|冲突/)
})
test('A deleted target and unavailable binding database cannot trigger global fallback', t => {
  const root = fixture(t), store = new RedteamStore(root); t.after(() => store.close())
  const a = store.openEngagement('project-A', []); store.openEngagement('project-B', [])
  assert.ok(store.sessionBindings)
  store.sessionBindings.bind(['session-A'], a.id)
  fs.rmSync(store.dbPathOf(a.id))
  assert.throws(() => resolver(store)({ id: 'session-A' }), /missing|失效|不存在/)
  store.sessionBindings.close()
  assert.throws(() => resolver(store)({ id: 'session-A' }))
})
test('Binding validates every key and target before replacing any prior association', t => {
  const store = new RedteamStore(fixture(t)); t.after(() => store.close())
  const a = store.openEngagement('project-A', [])
  assert.ok(store.sessionBindings)
  store.sessionBindings.bind(['session-A'], a.id)
  assert.throws(() => store.sessionBindings.bind(['session-A', ''], a.id))
  assert.throws(() => store.sessionBindings.bind(['session-A'], '../outside'))
  assert.equal(resolver(store)({ id: 'session-A' }), a.id)
})
test('An invalid binding cannot break a completed native tool result event', () => {
  let listener, warned = false
  installNativeEvidenceObserver({ on(_name, fn) { listener = fn }, effect() {}, logger: { warn() { warned = true } } }, {}, () => { throw new Error('binding unavailable') })
  assert.doesNotThrow(() => listener({ name: 'read', callId: 'done', arguments: {} }, { value: { text: 'synthetic' } }))
  assert.equal(warned, true)
})
