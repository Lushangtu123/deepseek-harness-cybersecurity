import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import vm from 'node:vm'
import { RedteamStore } from '../package/lib/redteam/store-core.js'
import { resolveSubagentRoleText } from '../package/lib/redteam/role-section.js'
import { installAssembleGuard } from '../package/lib/identity.js'

function fixture(t) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-role-isolation-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  const store = new RedteamStore(path.join(home, 'redteam'))
  t.after(() => {
    store.close()
    if (previous === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previous
    fs.rmSync(home, { recursive: true, force: true })
  })
  const a = store.openEngagement('project-A', []), b = store.openEngagement('project-B', [])
  for (const [target, text] of [[a, 'ROLE_FOR_PROJECT_A'], [b, 'ROLE_FOR_PROJECT_B']]) {
    const file = path.join(store.root, 'engagements', target.id, 'agents/recon.md')
    fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, text)
  }
  const parent = { id: 'root-A', header: { agentPreset: 'redteam' } }
  const session = { id: 'child-A', header: { origin: 'subagent', delegationDepth: 1, parentSession: parent.id, agentPreset: 'redteam' }, events: [{ type: 'user/message', data: { content: 'redteamRole: recon' } }] }
  store.sessionLookup = id => id === parent.id ? parent : undefined
  return { store, a, b, parent, context: { agent: { session } } }
}

test('A child uses project A role while the globally current project is B', t => {
  const { store, a, context, parent } = fixture(t)
  store.sessionBindings.bind([parent.id], a.id)
  assert.equal(resolveSubagentRoleText(context, store), 'ROLE_FOR_PROJECT_A')
})

test('Missing or conflicting bindings reject role assembly instead of using current', t => {
  const { store, a, b, context, parent } = fixture(t)
  assert.throws(() => resolveSubagentRoleText(context, store), error => error.code === 'redteam/role-binding')
  store.sessionBindings.bind([parent.id], a.id)
  store.sessionBindings.bind([context.agent.session.id], b.id)
  assert.throws(() => resolveSubagentRoleText(context, store), /冲突|conflict/)
})

test('Role binding failures escape both assembly guard fallback paths', async () => {
  for (const code of ['redteam/role-binding', 'redteam/role-file']) for (const inner of [true, false]) {
    const error = Object.assign(new Error('synthetic unavailable role'), { code })
    const prompt = { assemble: async () => { if (inner) throw error; return { sections: [] } } }
    installAssembleGuard(prompt, () => { throw error })
    await assert.rejects(prompt.assemble({}), err => err === error)
  }
})

test('Cold nested children retain project A roles and reject stale targets', t => {
  const { store, a, context, parent } = fixture(t)
  store.sessionBindings.bind([parent.id], a.id)
  const child = context.agent.session
  const grand = { id: 'grandchild-A', header: { ...child.header, parentSession: child.id, delegationDepth: 2 }, events: child.events }
  store.sessionLookup = id => new Map([[parent.id, parent], [child.id, child]]).get(id)
  const nested = { agent: { session: grand } }
  assert.equal(resolveSubagentRoleText(nested, store), 'ROLE_FOR_PROJECT_A')
  store.sessionLookup = () => undefined
  assert.equal(resolveSubagentRoleText(nested, store), 'ROLE_FOR_PROJECT_A')
  fs.rmSync(store.dbPathOf(a.id))
  assert.throws(() => resolveSubagentRoleText(nested, store), error => error.code === 'redteam/role-binding')
})

test('The authoritative store root wins over a different DSH_HOME', t => {
  const { store, a, context, parent } = fixture(t)
  store.sessionBindings.bind([parent.id], a.id)
  process.env.DSH_HOME = path.join(store.root, 'unrelated-home')
  assert.equal(resolveSubagentRoleText(context, () => store), 'ROLE_FOR_PROJECT_A')
})

test('Non-role sessions do not require a store; unavailable stores fail clearly for role children', t => {
  const { context } = fixture(t)
  const missing = () => { throw new Error('synthetic unavailable service') }
  assert.equal(resolveSubagentRoleText({ agent: { session: { id: 'ordinary', header: {} } } }, missing), '')
  assert.throws(() => resolveSubagentRoleText(context, missing), error => error.code === 'redteam/role-binding')
})

test('The improved entrypoint registers a bound role section without enabling legacy prompt rewriting', t => {
  const { store, a, context, parent } = fixture(t)
  store.sessionBindings.bind([parent.id], a.id)
  const sections = []
  const source = fs.readFileSync(new URL('../package/lib/index.js', import.meta.url), 'utf8')
  const start = source.indexOf('export function apply('), end = source.indexOf('\nfunction applyHostHooks(', start)
  const scope = { DEFAULTS: { enabled: true }, originalCapabilitiesEnabled: () => false, installPresetDefaultCleanup() {}, core: {findDshHome:()=>''}, installStartupRecovery() {}, installSubagentRoleCapture() {},
    addPromptSection(_ctx, section) { sections.push(section) }, vmAutonomyEnabled: () => false,
    PERSONAL_POLICY: 'consent-policy', VM_POLICY: '', applyHostHooks() {}, resolveSubagentRoleText,
    REDTEAM_ROLE_SECTION: 'dshpg-redteam-role', GLOBAL_PROMPT_ORDER: -100000 }
  vm.runInNewContext(source.slice(start, end).replace('export function', 'function') + '\nboot=apply', scope)
  scope.boot({ get: name => name === 'redteam' ? store : undefined }, {})
  const section = sections.find(section => section.name === 'dshpg-redteam-role')
  assert.ok(section, 'Improved startup must actually mount the role prompt')
  assert.equal(section.text(context), 'ROLE_FOR_PROJECT_A')
})

test('An assigned role with a missing, unreadable, or blank file fails with an actionable role-file error', t => {
  const { store, a, context, parent } = fixture(t)
  store.sessionBindings.bind([parent.id], a.id)
  const file = path.join(store.promptsDirOf(a.id), 'recon.md')
  const check = () => assert.throws(() => resolveSubagentRoleText(context, store), error => {
    assert.equal(error.code, 'redteam/role-file')
    assert.ok(error.message.includes(a.id)); assert.match(error.message, /recon/)
    assert.match(error.message, /恢复默认|重新保存/); return true
  })
  fs.renameSync(file, file + '.fixture-backup'); check()
  fs.mkdirSync(file); check(); fs.rmdirSync(file)
  fs.writeFileSync(file, '   \n'); check()
  fs.writeFileSync(file, 'RESTORED_ROLE')
  assert.equal(resolveSubagentRoleText(context, store), 'RESTORED_ROLE')
})
