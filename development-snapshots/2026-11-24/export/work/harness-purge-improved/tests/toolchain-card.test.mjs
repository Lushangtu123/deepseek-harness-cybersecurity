import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../package/client.js', import.meta.url), 'utf8');
function helper(name, end, scope = {}) {
  const asyncStart = source.indexOf('async function ' + name + '(');
  const start = asyncStart >= 0 ? asyncStart : source.indexOf('function ' + name + '(');
  assert.ok(start >= 0, name + ' is missing');
  return vm.runInNewContext('(' + source.slice(start, source.indexOf(end, start)).trim() + ')', scope);
}
test('card labels distinguish release match, main match, and unknown states', () => {
  const label = helper('vmToolchainLabel', '\n\t\tfunction vmToolchainIssues');
  assert.equal(label({ installed: { available: true }, comparison: { matchesLatestRelease: true, matchesDefaultBranch: false } }), '正式版一致 · main 不同');
  assert.equal(label({ installed: { available: true }, comparison: { matchesLatestRelease: false, matchesDefaultBranch: true } }), 'main 一致 · Release 不同');
  assert.equal(label({ installed: { available: true }, comparison: {} }), '未确认');
  assert.equal(label({ installed: { available: false }, comparison: { matchesLatestRelease: true } }), '本地版本未确认');
  assert.equal(label({ installed: { available: true }, queryState: 'timeout', comparison: {} }), '查询超时 · 未确认');
  assert.equal(label({ installed: { available: true }, queryState: 'timeout', comparison: { matchesLatestRelease: true } }), '部分查询超时 · 正式版一致');
  assert.equal(label({ installed: { available: false }, queryState: 'timeout', comparison: {} }), '查询超时 · 本地版本未确认');
});
test('card request is fixed, manual, authenticated and cancellable', async () => {
  let request;
  const read = helper('readVmToolchain', '\n\t\tfunction VmToolchainStatusCard', { AbortController, setTimeout, clearTimeout,
    fetch: async (...args) => { request = args; return { ok: true, json: async () => ({ ok: true, report: { projects: [] } }) }; } });
  const controller = new AbortController(); await read(controller.signal);
  assert.equal(request[0], '/redteam/api'); assert.equal(request[1].method, 'POST');
  assert.equal(request[1].credentials, 'same-origin'); assert.equal(request[1].cache, 'no-store');
  assert.deepEqual(JSON.parse(request[1].body), { op: 'toolchainVersions', project: 'all' });
  assert.equal(request[1].signal.aborted, false);
});
test('closing the card cancels its query even when fetch ignores abort', async () => {
  const read = helper('readVmToolchain', '\n\t\tfunction VmToolchainStatusCard', { AbortController, setTimeout, clearTimeout, fetch: () => new Promise(() => {}) });
  const controller = new AbortController(); const pending = read(controller.signal); controller.abort();
  await assert.rejects(pending, /取消/);
});
