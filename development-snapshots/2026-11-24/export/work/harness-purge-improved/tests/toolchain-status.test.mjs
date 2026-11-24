import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const url = new URL('../package/lib/redteam/personal-toolchain-status.mjs', import.meta.url);
const runtime = { platform: 'linux', home: '/home/purge', dshHome: '/home/purge/.dsh-improved' };
async function api() { assert.ok(fs.existsSync(url), 'Fixed read-only toolchain bridge is missing'); return import(url); }
test('toolchain bridge uses the same fixed checker and propagates cancellation', async () => {
  const { handleToolchainOp } = await api(); const calls = [], controller = new AbortController();
  const result = await handleToolchainOp({ op: 'toolchainVersions', project: 'all' }, { runtime, signal: controller.signal,
    loadRunner: async () => ({ runJson: async (...args) => { calls.push(args); return { projects: [] }; } }) });
  assert.equal(result.ok, true); assert.equal(calls[0][0], '/usr/bin/python3');
  assert.deepEqual(calls[0][1], ['/home/purge/.dsh-improved/tooling/toolchain-version-checker/check_versions.py', '--project', 'all', '--json']);
  assert.equal(calls[0][2].signal, controller.signal);
  assert.ok(calls[0][2].timeoutMs <= 25000, 'The bridge must settle before the existing 30s entry deadline');
});
test('other hosts, original profile, arbitrary URLs and extra arguments cannot dispatch', async () => {
  const { handleToolchainOp } = await api(); let calls = 0;
  const loadRunner = async () => { calls++; return {}; };
  for (const changed of [{ platform: 'darwin' }, { home: '/other' }, { dshHome: '/home/purge/.dsh' }]) {
    assert.equal((await handleToolchainOp({ op: 'toolchainVersions' }, { runtime: { ...runtime, ...changed }, loadRunner })).ok, false);
  }
  for (const request of [{ op: 'toolchainVersions', project: 'https://outside.invalid' }, { op: 'toolchainVersions', url: 'https://outside.invalid' }]) {
    assert.equal((await handleToolchainOp(request, { runtime, loadRunner })).ok, false);
  }
  assert.equal(calls, 0);
});
test('checker failures have a bounded actionable response without internal paths', async () => {
  const { handleToolchainOp } = await api();
  const result = await handleToolchainOp({ op: 'toolchainVersions' }, { runtime, loadRunner: async () => { throw Error('/private/secret internal module missing'); } });
  assert.equal(result.ok, false); assert.ok(!result.error.includes('/private')); assert.match(result.error, /重试|安装/);
  assert.equal(await handleToolchainOp({ op: 'other' }), undefined);
});
