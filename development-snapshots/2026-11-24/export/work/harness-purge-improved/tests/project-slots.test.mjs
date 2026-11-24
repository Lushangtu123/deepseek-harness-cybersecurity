import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import vm from 'node:vm'
import { RedteamStore } from '../package/lib/redteam/store-core.js'
import { bindingKeyOf } from '../package/lib/redteam/personal-session-resolution.mjs'
import { maxAgentsOf } from '../package/lib/redteam/settings.js'

const moduleUrl = new URL('../package/lib/redteam/personal-project-slots.mjs', import.meta.url)
const slotsModule = fs.existsSync(moduleUrl) ? await import(moduleUrl) : {}
const source = fs.readFileSync(new URL('../package/lib/redteam/tools.js', import.meta.url), 'utf8')
function fixture(t, registry = { listDescendants: async () => [], listChildren: async () => [] }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-project-slots-'))
  const store = new RedteamStore(root)
  t.after(() => { store.close(); fs.rmSync(root, { recursive: true, force: true }) })
  const a = store.openEngagement('project-A', [], { bindCurrent: false }), b = store.openEngagement('project-B', [], { bindCurrent: false })
  const sessions = ['root-one', 'root-two', 'root-other'].map(id => ({ id, header: {} }))
  for (const [i, session] of sessions.entries()) store.sessionBindings.bind([session.id], i === 2 ? b.id : a.id)
  store.sessionLookup = id => sessions.find(session => session.id === id)
  const at = source.indexOf("name: 'redteam_agent_slot'"), begin = source.lastIndexOf('  ctx.tools.register(', at), end = source.indexOf('\n  ctx.tools.register(', at)
  const legacy = source.includes('const reservations =')
    ? source.slice(source.indexOf('const reservations ='), source.indexOf('/** 一次调用的会话解析结果。')) + source.slice(source.indexOf('async function liveRunningChildren('), source.indexOf('/**\n * 产出这条记录的智能体角色')) : ''
  let tool
  const ctx = { redteam: store, get: name => name === 'subagents' ? registry : undefined, tools: { register: value => { tool = value } } }
  class SameMillisecond extends Date { static now() { return 1793136000000 } }
  vm.runInNewContext(legacy + source.slice(begin, end), { ctx, store, bindingKeyOf, maxAgentsOf, ...slotsModule, Date: SameMillisecond, process: { env: {} }, reviewedTool: x => x, defineTool: x => x, text: x => x })
  return { store, a, b, sessions, ctx, call: async (index, args) => JSON.parse(await tool.execute(args, { agent: { session: sessions[index] } })) }
}

test('One project shares three reservations across roots while another project keeps its own quota', async t => {
  const f = fixture(t)
  for (let n = 0; n < 3; n++) assert.equal((await f.call(0, { action: 'acquire', label: 'task-' + n })).ok, true)
  assert.equal((await f.call(1, { action: 'acquire', label: 'fourth' })).ok, false)
  assert.equal((await f.call(2, { action: 'acquire', label: 'other-project' })).ok, true)
})
test('Repeated same-label acquisitions retain distinct reservations and enforce the limit', async t => {
  const f = fixture(t), keys = []
  for (let n = 0; n < 3; n++) keys.push((await f.call(0, { action: 'acquire', label: 'same' })).slot)
  assert.equal(new Set(keys).size, 3)
  assert.equal((await f.call(0, { action: 'acquire', label: 'same' })).ok, false)
})
test('Acquire requires an explicit task label for deterministic native child association', async t => {
  const f = fixture(t)
  assert.equal((await f.call(0, { action: 'acquire' })).ok, false)
  assert.equal((await f.call(0, { action: 'status' })).used, 0)
})
test('Unknown registry state cannot grant a new reservation', async t => {
  const f = fixture(t, { listChildren: async () => { throw Error('synthetic offline') }, listDescendants: async () => { throw Error('synthetic offline') } })
  const result = await f.call(0, { action: 'acquire', label: 'unknown' })
  assert.equal(result.ok, false)
  assert.match(result.error, /核实|未知|不可用/)
})

test('Parallel acquisitions across roots are serialized against one project quota', async t => {
  const f = fixture(t)
  const results = await Promise.all(Array.from({ length: 10 }, (_, n) => f.call(n % 2, { action: 'acquire', label: 'parallel-' + n })))
  assert.equal(results.filter(result => result.ok).length, 3)
})
test('Explicit release cannot free another root reservation and live descendants consume the same quota', async t => {
  const rows = [], f = fixture(t, { listDescendants: async () => rows })
  const slot = await f.call(0, { action: 'acquire', label: 'owned' })
  assert.equal((await f.call(1, { action: 'release', key: slot.slot })).ok, false)
  assert.equal((await f.call(0, { action: 'release' })).ok, false)
  assert.equal((await f.call(0, { action: 'release', key: slot.slot })).ok, true)
  rows.push(...[1, 2, 3].map(n => ({ kind: 'child', id: 'live-' + n, activity: 'running' })))
  assert.equal((await f.call(1, { action: 'acquire', label: 'over-live-limit' })).ok, false)
})
test('Lifecycle linking counts a real child once and only the matching run releases it', async t => {
  const rows = [], f = fixture(t, { listDescendants: async () => rows }), events = new Map()
  assert.equal(typeof slotsModule.installProjectSlotLifecycle, 'function', 'Missing exact lifecycle association')
  f.ctx.on = (name, callback) => { events.set(name, callback); return () => events.delete(name) }
  f.ctx.effect = () => {}
  slotsModule.installProjectSlotLifecycle(f.ctx, f.store)
  const first = await f.call(0, { action: 'acquire', label: 'first' })
  const second = await f.call(0, { action: 'acquire', label: 'second' })
  f.sessions[0].events = [{ type: 'subagent/catalog', data: { childId: 'child-1', label: 'first' } }]
  const parent = { session: f.sessions[0] }
  events.get('subagent/start')({ id: 'child-1', runId: 'run-1' })
  rows.push({ kind: 'child', id: 'child-1', activity: 'running' })
  assert.equal((await f.call(1, { action: 'status' })).used, 2)
  assert.equal((await f.call(0, { action: 'release', key: first.slot })).ok, false, 'A running child cannot be manually made free')
  events.get('subagent/end')({ id: 'unknown', runId: 'unrelated' })
  assert.equal((await f.call(1, { action: 'status' })).used, 2)
  events.get('subagent/start')({ id: 'child-1', runId: 'run-2' })
  events.get('subagent/end')({ id: 'child-1', runId: 'run-1' })
  assert.equal((await f.call(1, { action: 'status' })).used, 2, 'Late prior-epoch end must not free the active epoch')
  rows.length = 0
  events.get('subagent/end')({ id: 'child-1', runId: 'run-2' })
  assert.equal((await f.call(1, { action: 'status' })).used, 1)
  assert.equal((await f.call(0, { action: 'release', key: second.slot })).ok, true)
})
test('Native start before catalog publication links the reservation when the catalog event arrives', async t => {
  const f = fixture(t), events = new Map()
  f.ctx.on = (name, callback) => { events.set(name, callback); return () => {} }; f.ctx.effect = () => {}
  slotsModule.installProjectSlotLifecycle(f.ctx, f.store)
  await f.call(0, { action: 'acquire', label: 'late-catalog' })
  const parent = { session: f.sessions[0] }, info = { id: 'late-child', runId: 'late-run' }
  events.get('subagent/start')(info)
  const event = { type: 'subagent/catalog', data: { childId: info.id, label: 'late-catalog' } }
  f.sessions[0].events = [event]
  events.get('session/event')?.(f.sessions[0], event)
  assert.equal((await f.call(0, { action: 'release', key: (await f.call(0, { action: 'status' })).reservations[0].key })).ok, false, 'An external epoch absent from the local session registry is still active until its end edge')
  events.get('subagent/end')(info)
  assert.equal((await f.call(1, { action: 'status' })).used, 0)
})
test('An exact padded task label matches the unchanged native description', async t => {
  const f = fixture(t), events = new Map()
  f.ctx.on = (name, callback) => { events.set(name, callback); return () => {} }; f.ctx.effect = () => {}
  slotsModule.installProjectSlotLifecycle(f.ctx, f.store)
  await f.call(0, { action: 'acquire', label: ' task with padding ' })
  f.sessions[0].events = [{ type: 'subagent/catalog', data: { childId: 'padded-child', label: ' task with padding ' } }]
  events.get('subagent/start')({ id: 'padded-child', runId: 'padded-run' })
  assert.equal((await f.call(0, { action: 'status' })).reservations[0].childId, 'padded-child')
  events.get('subagent/end')({ id: 'padded-child', runId: 'padded-run' })
  assert.equal((await f.call(0, { action: 'status' })).used, 0)
})
test('A fork cannot claim a sibling from an inherited catalog and lose its own reservation', async t => {
  const f = fixture(t), events = new Map()
  f.ctx.on = (name, callback) => { events.set(name, callback); return () => {} }; f.ctx.effect = () => {}
  slotsModule.installProjectSlotLifecycle(f.ctx, f.store)
  await f.call(0, { action: 'acquire', label: 'same-label' })
  const inherited = { seq: 0, type: 'subagent/catalog', data: { childId: 'sibling-of-fork', label: 'same-label' } }
  f.sessions[0].events = [inherited]; f.sessions[0].inheritedEventCount = 1
  f.sessions[0].ownEvents = () => []
  events.get('subagent/start')({ id: 'sibling-of-fork', runId: 'sibling-run' })
  events.get('subagent/end')({ id: 'sibling-of-fork', runId: 'sibling-run' })
  const status = await f.call(0, { action: 'status' })
  assert.equal(status.used, 1); assert.equal(status.reservations[0].childId, undefined)
})

test('Corrupt quota settings return unavailable status and refuse new reservations', async t => {
  const f = fixture(t)
  fs.writeFileSync(path.join(f.store.root, 'settings.json'), '{"maxAgents":')
  const status = await slotsModule.projectSlotsFor(f.store).status(f.ctx, f.a.id)
  assert.equal(status.ok, false); assert.equal(status.used, null); assert.equal(status.max, null)
  assert.match(status.error, /并发设置不可用/)
  const acquire = await f.call(0, { action: 'acquire', label: 'must-not-widen' })
  assert.equal(acquire.ok, false)
})
