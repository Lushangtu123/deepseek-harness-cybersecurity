import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = fs.mkdtempSync(path.join(here, '.reliability-fixtures-'));
process.env.DSH_HOME = path.join(root, 'isolated-home');
process.env.HOME = process.env.DSH_HOME;
process.env.DSH_SURFACE = 'web';
const core = await import('../package/lib/core.js');
test.after(() => fs.rmSync(root, { recursive: true, force: true }));

function fixture(label) {
  return fs.mkdtempSync(path.join(root, label + '-'));
}
function write(fp, text, mode = 0o644) {
  fs.mkdirSync(path.dirname(fp), { recursive: true });
  fs.writeFileSync(fp, text, { mode });
  fs.chmodSync(fp, mode);
}
function versionTree(dir, version) {
  write(path.join(dir, 'package.json'), JSON.stringify({ name: 'fixture-plugin', version }));
  write(path.join(dir, 'lib', 'index.js'), `export const version = '${version}';\n`);
  write(path.join(dir, 'client.js'), `client:${version}\n`);
}
function snapshot(dir) {
  const out = {};
  function visit(base, rel = '') {
    for (const name of fs.readdirSync(base).sort()) {
      const p = path.join(base, name), key = path.join(rel, name), st = fs.lstatSync(p);
      if (st.isSymbolicLink()) out[key] = ['link', fs.readlinkSync(p)];
      else if (st.isDirectory()) visit(p, key);
      else out[key] = [st.mode & 0o777, fs.readFileSync(p).toString('base64')];
    }
  }
  visit(dir);
  return out;
}
async function api() {
  let mod = {};
  try { mod = await import('../package/lib/personal-reliability.js'); } catch (e) {
    if (e.code !== 'ERR_MODULE_NOT_FOUND') throw e;
  }
  assert.equal(typeof mod.beginPackageUpdate, 'function', 'staged package transaction must be available');
  return mod;
}

test('sync and async atomic writes preserve private and executable modes', async () => {
  for (const mode of [0o600, 0o755]) {
    const fp = path.join(fixture('mode'), 'entry');
    write(fp, 'old', mode);
    core.atomicWriteSync(fp, 'sync');
    assert.equal(fs.statSync(fp).mode & 0o777, mode);
    await core.atomicWriteFile(fp, 'async');
    assert.equal(fs.statSync(fp).mode & 0o777, mode);
  }
});

test('patchShim preserves executable shell mode and is idempotent', async () => {
  const dir = fixture('shell space'), fp = path.join(dir, 'dsh');
  const old = '#!/bin/sh\nprintf fixture\n';
  write(fp, old, 0o755);
  assert.equal((await core.patchShim(dir)).dsh, 'patched');
  assert.equal(fs.statSync(fp).mode & 0o777, 0o755);
  const first = fs.readFileSync(fp, 'utf8');
  assert.equal((await core.patchShim(dir)).dsh, 'already_patched');
  assert.equal(fs.readFileSync(fp, 'utf8'), first);
  assert.equal((await core.revertShim(dir)).dsh, 'reverted');
  assert.equal(fs.readFileSync(fp, 'utf8'), old);
  assert.equal(fs.statSync(fp).mode & 0o777, 0o755);
});

test('npm launcher link and target survive patch, repeated patch, and restore', async () => {
  const dir = fixture('npm space'), bin = path.join(dir, 'bin');
  const target = path.join(dir, 'lib', 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');
  const old = '#!/usr/bin/env node\nconsole.log("fixture");\n';
  write(target, old, 0o755);
  fs.mkdirSync(bin);
  const launcher = path.join(bin, 'dsh');
  const link = path.relative(bin, target);
  fs.symlinkSync(link, launcher);
  assert.equal((await core.patchShim(bin)).dsh, 'patched');
  assert.ok(fs.lstatSync(launcher).isSymbolicLink(), 'patch must not replace the launcher symlink');
  assert.equal(fs.readlinkSync(launcher), link);
  assert.match(fs.readFileSync(target, 'utf8'), /dsh-purge shim begin/);
  assert.equal(fs.statSync(target).mode & 0o777, 0o755);
  const patched = fs.readFileSync(target, 'utf8');
  assert.equal((await core.patchShim(bin)).dsh, 'already_patched');
  assert.equal(fs.readFileSync(target, 'utf8'), patched);
  assert.equal((await core.revertShim(bin)).dsh, 'reverted');
  assert.ok(fs.lstatSync(launcher).isSymbolicLink());
  assert.equal(fs.readFileSync(target, 'utf8'), old);
});

test('staged update switches complete packages and preserves unrelated entries', async () => {
  const { beginPackageUpdate } = await api(), dir = fixture('transaction');
  const source = path.join(dir, 'source'), dest = path.join(dir, 'installed');
  versionTree(source, '2'); versionTree(dest, '1');
  write(path.join(dest, 'local-note'), 'keep');
  const tx = await beginPackageUpdate(source, [dest], ['lib', 'client.js', 'package.json']);
  assert.equal(JSON.parse(fs.readFileSync(path.join(dest, 'package.json'))).version, '2');
  assert.equal(fs.readFileSync(path.join(dest, 'lib/index.js'), 'utf8'), "export const version = '2';\n");
  assert.equal(fs.readFileSync(path.join(dest, 'local-note'), 'utf8'), 'keep');
  await tx.finalize();
  assert.deepEqual(fs.readdirSync(dir).sort(), ['installed', 'source']);
});

test('failure before second package switch restores both complete originals', async () => {
  const { beginPackageUpdate } = await api(), dir = fixture('rollback');
  const source = path.join(dir, 'source'), a = path.join(dir, 'a'), b = path.join(dir, 'b');
  versionTree(source, '2'); versionTree(a, '1a'); versionTree(b, '1b');
  const beforeA = snapshot(a), beforeB = snapshot(b);
  await assert.rejects(beginPackageUpdate(source, [a, b], ['lib', 'client.js', 'package.json'], {
    checkpoint: async ({ phase, destination }) => {
      if (phase === 'before-backup' && destination === b) throw new Error('injected switch failure');
    },
  }), /injected switch failure/);
  assert.deepEqual(snapshot(a), beforeA);
  assert.deepEqual(snapshot(b), beforeB);
  assert.deepEqual(fs.readdirSync(dir).sort(), ['a', 'b', 'source']);
});

test('caller rejection rolls back a committed update and keeps the old package usable', async () => {
  const { beginPackageUpdate } = await api(), dir = fixture('post-check');
  const source = path.join(dir, 'source'), dest = path.join(dir, 'installed');
  versionTree(source, '2'); versionTree(dest, '1');
  const before = snapshot(dest);
  const tx = await beginPackageUpdate(source, [dest], ['lib', 'client.js', 'package.json']);
  await tx.rollback();
  assert.deepEqual(snapshot(dest), before);
  assert.deepEqual(fs.readdirSync(dir).sort(), ['installed', 'source']);
});

test('source and destination symlinks or symlink ancestors are rejected before mutation', async () => {
  const { beginPackageUpdate } = await api();
  for (const kind of ['source-child', 'dest-child', 'dest-root', 'dest-parent']) {
    const dir = fixture(kind), source = path.join(dir, 'source'), dest = path.join(dir, 'installed');
    versionTree(source, '2'); versionTree(dest, '1');
    const before = snapshot(dest);
    let chosen = dest;
    if (kind === 'source-child') fs.symlinkSync('/etc/hosts', path.join(source, 'lib', 'linked'));
    if (kind === 'dest-child') fs.symlinkSync('/etc/hosts', path.join(dest, 'lib', 'linked'));
    if (kind === 'dest-root') { chosen = path.join(dir, 'linked'); fs.symlinkSync(dest, chosen); }
    if (kind === 'dest-parent') { fs.symlinkSync(dir, path.join(dir, 'parent')); chosen = path.join(dir, 'parent', 'installed'); }
    const current = snapshot(dest);
    await assert.rejects(beginPackageUpdate(source, [chosen], ['lib', 'client.js', 'package.json']), /symlink/i);
    assert.deepEqual(snapshot(dest), current);
    if (kind !== 'dest-child') assert.deepEqual(snapshot(dest), before);
  }
});

test('a second transaction cannot update a package with an unfinished transaction', async () => {
  const { beginPackageUpdate } = await api(), dir = fixture('lock');
  const source = path.join(dir, 'source'), dest = path.join(dir, 'installed');
  versionTree(source, '2'); versionTree(dest, '1');
  const tx = await beginPackageUpdate(source, [dest], ['lib', 'client.js', 'package.json']);
  await assert.rejects(beginPackageUpdate(source, [dest], ['lib', 'client.js', 'package.json']), /lock|in progress/i);
  await tx.rollback();
  assert.equal(JSON.parse(fs.readFileSync(path.join(dest, 'package.json'))).version, '1');
});

test('updater settlement rolls back a real package when runtime reapply rejects', async () => {
  const { beginPackageUpdate } = await api();
  const { settlePackageUpdate } = await import('../package/lib/update.js');
  assert.equal(typeof settlePackageUpdate, 'function');
  const dir = fixture('update-integration'), source = path.join(dir, 'source'), dest = path.join(dir, 'installed');
  versionTree(source, '2'); versionTree(dest, '1');
  const before = snapshot(dest);
  const tx = await beginPackageUpdate(source, [dest], ['lib', 'client.js', 'package.json']);
  assert.equal((await settlePackageUpdate(tx, { ok: false })).rolledBack, true);
  assert.deepEqual(snapshot(dest), before);
});

test('updater settlement accepts complete tree only after runtime reapply succeeds', async () => {
  const { beginPackageUpdate } = await api();
  const { settlePackageUpdate } = await import('../package/lib/update.js');
  assert.equal(typeof settlePackageUpdate, 'function');
  const dir = fixture('update-accept'), source = path.join(dir, 'source'), dest = path.join(dir, 'installed');
  versionTree(source, '2'); versionTree(dest, '1');
  const tx = await beginPackageUpdate(source, [dest], ['lib', 'client.js', 'package.json']);
  await settlePackageUpdate(tx, { ok: true });
  assert.equal(JSON.parse(fs.readFileSync(path.join(dest, 'package.json'))).version, '2');
  assert.deepEqual(fs.readdirSync(dir).sort(), ['installed', 'source']);
});
