import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { syncBuiltinESMExports } from 'node:module'
import { maxAgentsOf, maxAgentsSourceOf, saveMaxAgents, writeSettings } from '../package/lib/redteam/settings.js'

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-quota-settings-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  return { root, file: path.join(root, 'settings.json') }
}
test('A damaged quota configuration cannot silently widen a configured single slot', t => {
  const { root, file } = fixture(t)
  saveMaxAgents(root, 1); assert.equal(maxAgentsOf(root, {}), 1)
  fs.writeFileSync(file, '{"maxAgents":')
  for (const read of [() => maxAgentsOf(root, {}), () => maxAgentsSourceOf(root, { REDTEAM_MAX_AGENTS: '9' })]) {
    assert.throws(read, error => error.code === 'redteam/settings' && /设置|配置/.test(error.message))
  }
})

test('A failed atomic settings replacement preserves the previous valid quota', t => {
  const { root, file } = fixture(t)
  saveMaxAgents(root, 1); const before = fs.readFileSync(file)
  const rename = fs.renameSync
  fs.renameSync = (from, to) => {
    if (to === file) throw Object.assign(new Error('synthetic replace failure'), { code: 'EIO' })
    return rename(from, to)
  }
  syncBuiltinESMExports()
  try { assert.throws(() => saveMaxAgents(root, 3), /synthetic replace failure/) }
  finally { fs.renameSync = rename; syncBuiltinESMExports() }
  assert.deepEqual(fs.readFileSync(file), before)
  assert.equal(maxAgentsOf(root, {}), 1)
  assert.deepEqual(fs.readdirSync(root), ['settings.json'])
})

test('Only a missing setting uses the normal environment/default policy; invalid files stay errors', t => {
  const { root, file } = fixture(t)
  assert.equal(maxAgentsOf(root, {}), 3)
  assert.equal(maxAgentsOf(root, { REDTEAM_MAX_AGENTS: '2' }), 2)
  for (const invalid of ['[]', 'null', '{"maxAgents":0}', '{"maxAgents":"bad"}']) {
    fs.writeFileSync(file, invalid)
    assert.throws(() => maxAgentsOf(root, {}), error => error.code === 'redteam/settings')
  }
  fs.unlinkSync(file); fs.mkdirSync(file)
  assert.throws(() => maxAgentsOf(root, {}), error => error.code === 'redteam/settings')
  fs.rmdirSync(file)
  writeSettings(root, { maxAgents: 1, preserved: 'synthetic' }); saveMaxAgents(root, 2)
  assert.deepEqual(JSON.parse(fs.readFileSync(file)), { maxAgents: 2, preserved: 'synthetic' })
  assert.equal(fs.statSync(file).mode & 0o777, 0o600)
})

test('A settings symlink never degrades into an unconfigured default', t => {
  const { root, file } = fixture(t), target = path.join(root, 'target.json')
  fs.writeFileSync(target, '{"maxAgents":1}'); fs.symlinkSync(target, file)
  assert.throws(() => maxAgentsOf(root, {}), error => error.code === 'redteam/settings')
  fs.unlinkSync(target)
  assert.throws(() => maxAgentsOf(root, {}), error => error.code === 'redteam/settings')
})

test('Quota fields reject coercible non-scalar JSON values instead of widening the limit', t => {
  const { root, file } = fixture(t)
  for (const value of [[9], true, false, null, {}, '9e0', ' 9 ']) {
    fs.writeFileSync(file, JSON.stringify({ maxAgents: value }))
    assert.throws(() => maxAgentsOf(root, {}), error => error.code === 'redteam/settings', JSON.stringify(value))
  }
  for (const value of [1, 10, '1', '10']) {
    fs.writeFileSync(file, JSON.stringify({ maxAgents: value }))
    assert.equal(maxAgentsOf(root, {}), Number(value))
  }
})

test('Settings writes reject invalid field types before modifying a valid file', t => {
  const { root, file } = fixture(t)
  saveMaxAgents(root, 1); const original = fs.readFileSync(file)
  for (const value of [[9], true, null, {}, '', '9e0', 11, 1.2]) {
    assert.throws(() => saveMaxAgents(root, value), /并发|上限/)
    assert.deepEqual(fs.readFileSync(file), original)
  }
})
