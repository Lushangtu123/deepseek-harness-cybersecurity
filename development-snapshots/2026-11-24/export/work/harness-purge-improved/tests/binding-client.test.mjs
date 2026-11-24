import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const url = new URL('../package/lib/redteam/personal-binding-client.mjs', import.meta.url)
const mod = fs.existsSync(url) ? await import(url) : {}
const flush = () => new Promise(setImmediate)

test('Selected-chat changes discard old binding responses and failures never look current', async () => {
  assert.equal(typeof mod.createBindingMonitor, 'function', 'Missing session-aware binding reader')
  let selected = 'session-A', time = 1000, last
  const pending = []
  const monitor = mod.createBindingMonitor({ getSessionId: () => selected, now: () => time,
    read: (id, signal) => new Promise((resolve, reject) => pending.push({ id, signal, resolve, reject })), publish: value => { last = value } })
  monitor.check(); assert.equal(last.state, 'checking')
  selected = 'session-B'; monitor.check(); assert.equal(pending[0].signal.aborted, true)
  pending[1].resolve({ ok: true, state: 'bound', sessionId: selected, engagement: 'project-B' }); await flush()
  assert.equal(last.engagement, 'project-B')
  pending[0].resolve({ ok: true, state: 'bound', sessionId: 'session-A', engagement: 'project-A' }); await flush()
  assert.equal(last.engagement, 'project-B')
  time += 61000; monitor.check(); assert.equal(last.state, 'stale')
  monitor.check(true); pending[2].reject(Error('synthetic offline')); await flush()
  assert.equal(last.state, 'unavailable'); assert.equal(last.engagement, undefined)
  selected = ''; monitor.check(); assert.equal(last.state, 'no-session')
  monitor.dispose()
})
test('A reply for a different session cannot be accepted as the selected chat binding', async () => {
  assert.equal(typeof mod.createBindingMonitor, 'function')
  let last
  const monitor = mod.createBindingMonitor({ getSessionId: () => 'selected', read: async () => ({ ok: true, state: 'bound', sessionId: 'foreign', engagement: 'project-X' }), publish: value => { last = value } })
  monitor.check(); await flush(); assert.equal(last.state, 'unavailable'); assert.equal(last.engagement, undefined)
  monitor.dispose()
})
test('A selected blank new chat cannot fall back to the previously current session', () => {
  const source = fs.readFileSync(new URL('../package/client.js', import.meta.url), 'utf8')
  const start = source.indexOf('const drillSessionId ='), end = source.indexOf('\n\t\tfunction sessionKnown(', start)
  const scope = { rewindWorkspace: { selection: { getSnapshot: () => ({}) } }, rewindSessions: { list: { getSnapshot: () => ({ current: 'old-chat' }) } } }
  vm.runInNewContext(source.slice(start, end) + '\nselected=drillSessionId()', scope)
  assert.equal(scope.selected, '')
})
