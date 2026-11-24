import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import vm from 'node:vm'
import {RedteamStore} from '../package/lib/redteam/store-core.js'
import {SecurityWorkbench} from '../package/lib/redteam/personal-security-workbench.mjs'

function fixture(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'project-isolation-')))
  const workspace = path.join(root, 'workspace'), repo = path.join(workspace, 'project')
  fs.mkdirSync(repo, {recursive: true}); fs.writeFileSync(path.join(repo, 'app.py'), 'print("synthetic")\n')
  const store = new RedteamStore(path.join(root, 'facts')), eng = store.openEngagement('healthy').id
  const bench = new SecurityWorkbench(store, {workspaceRoot: workspace,
    toolStatus: () => ({semgrep: {ready: true}, zap: {ready: true}}),
    runner: async () => ({findings: [], complete: true, coverageKey: 'fixture', coverageFiles: ['app.py']})})
  const scope = {requestId: 'initial-scope-1', revision: 0, repoRoot: repo, tools: ['semgrep', 'zap'],
    url: 'http://127.0.0.1:18783', expiresAt: new Date(Date.now() + 3600000).toISOString(), confirm: true}
  bench.saveScope(eng, scope)
  t.after(async () => { await bench.dispose(); await store.close(); fs.rmSync(root, {recursive: true, force: true}) })
  return {root, store, bench, eng, scope}
}

function damage(store) {
  fs.mkdirSync(path.join(store.engagementsDir, 'missing'))
  fs.mkdirSync(path.join(store.engagementsDir, 'corrupt'))
  fs.writeFileSync(path.join(store.engagementsDir, 'corrupt/assets.db'), 'synthetic corrupt database')
}

test('unrelated missing and corrupt databases do not block healthy scope saves or isolated static scans', async t => {
  const {store, bench, eng, scope} = fixture(t); damage(store)
  const saved = bench.saveScope(eng, {...scope, requestId: 'save-healthy-again', revision: 1, expiresAt: new Date(Date.now() + 7200000).toISOString()})
  assert.equal(saved.revision, 2)
  const run = bench.start(eng, {requestId: 'healthy-static-run', profileRevision: 2, tool: 'semgrep'})
  await bench.active.promise
  assert.equal(bench.db(eng).prepare('SELECT state FROM security_run WHERE id=?').get(run.id).state, 'completed')
  assert.equal(fs.readFileSync(path.join(store.engagementsDir, 'corrupt/assets.db'), 'utf8'), 'synthetic corrupt database')
  assert.equal(fs.existsSync(path.join(store.engagementsDir, 'missing/assets.db')), false)
})

test('global runtime, web and joint admission retain unreadable projects as unknown with visible reasons', async t => {
  const {store, bench, eng} = fixture(t); damage(store)
  const availability = bench.runtimeUI.availability()
  assert.equal(availability.state, 'unavailable')
  assert.deepEqual(availability.unavailableProjects.map(x => x.engagement).sort(), ['corrupt', 'missing'])
  assert.equal(bench.runtimeUI.transitionBusy(), true)
  assert.equal(bench.runtimeUI.transitionBusy(eng), false)
  assert.throws(() => bench.start(eng, {requestId: 'unknown-web-start', profileRevision: 1, tool: 'zap'}), /未确认|不可读取|未知/)
  assert.throws(() => bench.joint.start(eng, {requestId: 'unknown-joint-start', profileRevision: 1, steps: ['semgrep']}), /未确认|不可读取|未知/)
  await assert.rejects(() => bench.runtimeUI.preview(eng, {profileRevision: 1, entry: 'app.py', seconds: 30}), /未确认|不可读取|未知/)
  const view = bench.read(eng)
  assert.equal(view.projectAvailability.state, 'unavailable')
  assert.deepEqual(view.review.canStartTools, ['semgrep'])
  assert.ok(view.review.warnings.some(x => /不可读取|未知/.test(x)))
})

test('a current-project runtime transition still excludes its scope changes and static scans', t => {
  const {bench, eng, scope} = fixture(t)
  bench.db(eng).prepare('INSERT INTO security_event(request_id,kind,record_id,at,data) VALUES(?,?,?,?,?)').run('owned-transition', 'runtime-start', 'open', new Date().toISOString(), JSON.stringify({phase: 'prepared', cleanupVerified: false, preview: {origin: scope.url}}))
  assert.equal(bench.runtimeUI.transitionBusy(eng), true)
  assert.throws(() => bench.saveScope(eng, {...scope, requestId: 'busy-owned-scope', revision: 1}), /运行|切换/)
  assert.throws(() => bench.start(eng, {requestId: 'busy-owned-start', profileRevision: 1, tool: 'semgrep'}), /未确认/)
})

test('a rejected database open closes its handle before repeated health checks can retry', () => {
  const source=fs.readFileSync(new URL('../package/lib/redteam/store-core.js',import.meta.url),'utf8')
  const a=source.indexOf('  db(id, options = {}) {'),b=source.indexOf('\n  close() {',a)
  assert.ok(a>=0&&b>a)
  let closed=0
  const context={DatabaseSync:class{exec(){throw Error('synthetic corrupt DB')}close(){closed++}},existsSync:()=>true,HAS_FTS5:false,DDL:'',migrate(){}}
  vm.runInNewContext('this.open=({'+source.slice(a,b)+'}).db',context)
  const store={handles:new Map(),dbPathOf:()=>'/synthetic/assets.db'}
  assert.throws(()=>context.open.call(store,'fixture'),/corrupt DB/)
  assert.equal(closed,1)
  assert.equal(store.handles.size,0)
})

test('malformed or contradictory open-runtime records remain unavailable rather than clean or idle', t => {
  const {bench, eng, scope}=fixture(t),db=bench.db(eng)
  const valid={phase:'prepared',cleanupVerified:false,preview:{origin:scope.url}}
  for(const patch of [{cleanupVerified:'not-confirmed'},{cleanupVerified:true},{preview:null},{preview:{}},{phase:'invented'}]){
    db.prepare('INSERT OR REPLACE INTO security_event(request_id,kind,record_id,at,data) VALUES(?,?,?,?,?)').run('malformed-runtime','runtime-start','open',new Date().toISOString(),JSON.stringify({...valid,...patch}))
    assert.equal(bench.runtimeUI.availability().state,'unavailable',JSON.stringify(patch))
    assert.equal(bench.runtimeUI.transitionBusy(),true)
    assert.deepEqual(bench.read(eng).review.canStartTools,[])
  }
})
