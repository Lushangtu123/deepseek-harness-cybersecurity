import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function fixture(request) {
  const source = fs.readFileSync(new URL('../package/client.js', import.meta.url), 'utf8')
  const a = source.indexOf('function createOriginalSwitchModel('), b = source.indexOf('function OriginalCapabilitiesSwitch(', a)
  assert.ok(a >= 0 && b > a)
  let time = 0
  const updates = [], verified = [], timers = []
  const scope = {performance: {now: () => time}, setTimeout: fn => timers.push(fn), clearTimeout() {}}
  vm.runInNewContext(source.slice(a, b) + '\nthis.create=createOriginalSwitchModel', scope)
  const model = scope.create({request, publish: v => updates.push({...v}), onVerified: v => verified.push(v)})
  return {model, updates, verified, timers, advance: ms => time += ms}
}
const current = (enabled, operation = null, ready = true) => ({ok: true, enabled, operation,
  pluginStatus: {ready, originalCapabilities: {enabled, managed: true}}})
const operation = (id, targetEnabled, state = 'succeeded') => ({id, targetEnabled, state})

test('a failed submission cannot use an old successful operation as its own receipt', async () => {
  const f = fixture(async method => {
    if (method === 'POST') throw Error('synthetic conflict')
    return current(true, operation('old-operation', true))
  })
  await f.model.refresh(); f.model.select(false); await f.model.confirm()
  assert.doesNotMatch(f.updates.at(-1).notice, /切换完成/)
  assert.match(f.updates.at(-1).notice, /未确认/)
  assert.equal(f.updates.at(-1).enabled, true)
  f.model.dispose()
})

test('only the returned operation ID, requested target and verified current state complete a switch', async () => {
  let enabled = false
  const f = fixture(async method => {
    if (method === 'POST') { enabled = true; return {ok: true, operation: operation('own-operation', true, 'running')} }
    return current(enabled, enabled ? operation('own-operation', true) : null)
  })
  await f.model.refresh(); f.model.select(true); await f.model.confirm()
  assert.match(f.updates.at(-1).notice, /切换完成/)
  assert.equal(f.verified.at(-1).originalCapabilities.enabled, true)
  f.model.dispose()
})

test('another operation and a lost POST receipt remain unconfirmed even when the target matches', async () => {
  for (const lost of [false, true]) {
    let writes = 0
    const f = fixture(async method => {
      if (method === 'POST') { writes++; if (lost) throw Error('synthetic response lost'); return {ok: true, operation: operation('own-operation', true, 'running')} }
      return current(writes > 0, writes ? operation('other-operation', true) : null)
    })
    await f.model.refresh(); f.model.select(true); await f.model.confirm()
    assert.doesNotMatch(f.updates.at(-1).notice, /切换完成/)
    assert.match(f.updates.at(-1).notice, /未确认/)
    assert.equal(writes, 1)
    f.model.dispose()
  }
})

test('verified capability is revoked while reading and after failure or contradictory plugin state', async () => {
  let response = current(true), rejectRead = false
  const f = fixture(async () => { if (rejectRead) throw Error('synthetic unavailable'); return response })
  await f.model.refresh(); assert.equal(f.verified.at(-1).originalCapabilities.enabled, true)
  response = current(false, null, false); await f.model.refresh()
  assert.equal(f.verified.at(-1), null)
  assert.equal(f.updates.at(-1).known, false)
  response = current(false); await f.model.refresh(); assert.equal(f.verified.at(-1).originalCapabilities.enabled, false)
  rejectRead = true; await f.model.refresh(); assert.equal(f.verified.at(-1), null)
  assert.equal(f.updates.at(-1).known, false)
  f.model.dispose()
})

test('a switch revokes old editor readiness before its POST completes and timeout never restores it', async () => {
  let release, writes = 0
  const f = fixture(async method => {
    if (method === 'POST') { writes++; return new Promise(resolve => {release = resolve}) }
    return current(true, writes ? operation('own-operation', false, 'running') : null)
  })
  await f.model.refresh(); f.model.select(false)
  const pending = f.model.confirm()
  assert.equal(f.verified.at(-1), null)
  release({ok: true, operation: operation('own-operation', false, 'running')}); await pending
  f.advance(180001); await f.timers.at(-1)()
  assert.equal(f.updates.at(-1).known, false)
  assert.equal(f.verified.at(-1), null)
  assert.equal(writes, 1)
  f.model.dispose()
})
