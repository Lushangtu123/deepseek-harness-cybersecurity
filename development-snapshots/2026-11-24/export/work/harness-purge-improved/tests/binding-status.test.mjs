import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import * as ui from '../package/lib/redteam/ui.js'
import { RedteamStore } from '../package/lib/redteam/store-core.js'

test('Binding status follows the selected session, ignores global current, and does not create lineage rows', t => {
  assert.equal(typeof ui.sessionBindingStatus, 'function', 'Missing session binding indicator backend')
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-binding-status-')), store = new RedteamStore(root)
  t.after(() => { store.close(); fs.rmSync(root, { recursive: true, force: true }) })
  const a = store.openEngagement('project-A', []), b = store.openEngagement('project-B', [])
  const parent = { id: 'parent', header: {} }, child = { id: 'child', header: { parentSession: 'parent' } }
  const sessions = new Map([parent, child].map(session => [session.id, session]))
  store.sessionBindings.bind([parent.id], a.id)
  store.sessionLookup = id => sessions.get(id)
  const ctx = { redteam: store, get: name => name === 'sessions' ? { get: id => sessions.get(id) } : undefined }
  const result = ui.sessionBindingStatus(ctx, child.id)
  assert.equal(result.state, 'bound'); assert.equal(result.engagement, a.id); assert.equal(result.rootSession, parent.id)
  assert.equal(store.activeEngagementId(), b.id)
  assert.equal(store.sessionBindings.db.prepare('SELECT COUNT(*) AS n FROM session_lineage').get().n, 0)
  assert.equal(ui.sessionBindingStatus(ctx, '').state, 'no-session')
  assert.equal(ui.sessionBindingStatus(ctx, 'new-unbound').state, 'unbound')
  store.sessionBindings.bind([child.id], b.id)
  assert.equal(ui.sessionBindingStatus(ctx, child.id).state, 'unavailable')
})
