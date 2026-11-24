import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { runJson } from '../process.mjs';

test('returns structured JSON and ignores credentials inherited from caller', async () => {
  process.env.GITHUB_TOKEN = 'test-secret-never-forward';
  try {
    assert.deepEqual(await runJson(process.execPath, ['-e', 'console.log(JSON.stringify({token:process.env.GITHUB_TOKEN??null}))']), { token: null });
  } finally { delete process.env.GITHUB_TOKEN; }
});
test('malformed output and nonzero exits are errors', async () => {
  await assert.rejects(runJson(process.execPath, ['-e', 'console.log("invalid")']), /invalid JSON/);
  await assert.rejects(runJson(process.execPath, ['-e', 'process.exit(3)']), /failed/);
});
test('timeout and oversized output are bounded', async () => {
  await assert.rejects(runJson(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { timeoutMs: 100 }), /timed out/);
  await assert.rejects(runJson(process.execPath, ['-e', 'console.log("x".repeat(140000));setInterval(()=>{},1000)']), /exceeded/);
});
test('cancellation kills the checker and its helper process', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'versions-cancel-'));
  const pidFile = path.join(dir, 'pid');
  const controller = new AbortController();
  const script = `const {spawn}=require('node:child_process');const fs=require('node:fs');const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});fs.writeFileSync(${JSON.stringify(pidFile)},String(child.pid));setInterval(()=>{},1000)`;
  const promise = runJson(process.execPath, ['-e', script], { signal: controller.signal });
  try {
    for (let i = 0; i < 100 && !fs.existsSync(pidFile); i++) await new Promise(r => setTimeout(r, 10));
    assert.ok(fs.existsSync(pidFile));
    const pid = Number(fs.readFileSync(pidFile, 'utf8'));
    controller.abort();
    await assert.rejects(promise, /cancelled/);
    for (let i = 0; i < 100; i++) {
      try { process.kill(pid, 0); } catch { return; }
      await new Promise(r => setTimeout(r, 10));
    }
    assert.fail('helper survived cancellation');
  } finally { controller.abort(); fs.rmSync(dir, { recursive: true, force: true }); }
});
