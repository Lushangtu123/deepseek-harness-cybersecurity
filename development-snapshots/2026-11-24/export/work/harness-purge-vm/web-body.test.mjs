import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createWebEntry } from './web-entry.mjs';

async function fixture(handler, options = {}) {
  const upstream = http.createServer(handler), timers = new Set();
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  const entry = createWebEntry({ upstreamPort: upstream.address().port, responseTimeoutMs: 200, bodyIdleTimeoutMs: 35, ...options });
  await new Promise(resolve => entry.listen(0, '127.0.0.1', resolve));
  return { port: entry.address().port, later(fn, delay) { const timer = setTimeout(fn, delay); timers.add(timer); return timer; },
    async close() { timers.forEach(clearTimeout); entry.shutdown(); upstream.closeAllConnections(); await new Promise(resolve => upstream.close(resolve)); } };
}
const open = (port, path) => new Promise((resolve, reject) => {
  http.get({ host: '127.0.0.1', port, path, agent: false }, res => { res.on('error', () => {}); resolve(res); }).on('error', reject);
});
const read = async (port, path) => {
  const res = await open(port, path), chunks = [];
  for await (const chunk of res) chunks.push(chunk);
  return { status: res.statusCode, body: Buffer.concat(chunks).toString() };
};
const diagnostics = async port => JSON.parse((await read(port, '/__harness/diagnostics')).body);

test('Receiving headers alone cannot mark an unfinished ordinary response healthy', async () => {
  const f = await fixture((_req, res) => { res.writeHead(200); res.write('partial'); }, { bodyIdleTimeoutMs: 150 });
  let response;
  try {
    response = await open(f.port, '/assets/pending.js'); response.resume();
    const data = await diagnostics(f.port);
    assert.equal(data.layers.assets.state, 'receiving');
    assert.equal(data.layers.assets.phase, 'headers');
    assert.ok(!data.recent.some(item => item.category === 'assets' && item.state === 'ok'));
  } finally { response?.destroy(); await f.close(); }
});

test('A stalled response body expires and releases a queued healthy request without replay', async () => {
  let stalledCalls = 0;
  const f = await fixture((req, res) => {
    if (req.url === '/assets/stalled.js') { stalledCalls++; res.writeHead(200); res.write('partial'); }
    else res.end('queue-recovered');
  });
  let response;
  try {
    response = await open(f.port, '/assets/stalled.js'); response.resume();
    const next = await read(f.port, '/assets/healthy.js');
    assert.equal(next.status, 200); assert.equal(next.body, 'queue-recovered');
    assert.equal(stalledCalls, 1, 'A partial response must never be replayed');
    const data = await diagnostics(f.port);
    assert.ok(data.recent.some(item => item.error === 'body-timeout' && item.state === 'timeout' && item.phase === 'body'));
    assert.ok(!data.recent.some(item => item.category === 'assets' && item.status === 200 && item.phase === 'headers' && item.state === 'ok'));
  } finally { response?.destroy(); await f.close(); }
});

test('An ordinary response cut off after headers is diagnosed as incomplete', async () => {
  let f;
  f = await fixture((_req, res) => { res.writeHead(200, { 'content-length': '100' }); res.write('partial'); f.later(() => res.destroy(), 12); });
  try {
    await assert.rejects(read(f.port, '/assets/truncated.js'));
    const data = await diagnostics(f.port);
    assert.equal(data.layers.assets.state, 'connection-error');
    assert.equal(data.layers.assets.error, 'body-incomplete');
    assert.equal(data.layers.assets.phase, 'body');
  } finally { await f.close(); }
});

test('Progressing ordinary bodies can outlive the header budget and finish normally', async () => {
  let f;
  f = await fixture((_req, res) => {
    res.writeHead(200); res.write('a');
    f.later(() => res.write('b'), 20); f.later(() => res.write('c'), 40); f.later(() => res.end('d'), 60);
  }, { responseTimeoutMs: 30, bodyIdleTimeoutMs: 45 });
  try {
    const result = await read(f.port, '/assets/progress.js'); assert.equal(result.body, 'abcd');
    const data = await diagnostics(f.port); assert.equal(data.layers.assets.state, 'ok'); assert.equal(data.layers.assets.phase, 'complete');
  } finally { await f.close(); }
});

test('An idle SSE stream survives the ordinary body deadline and leaves HTTP usable', async () => {
  let f;
  f = await fixture((req, res) => {
    if (req.url === '/plugins/events') { res.writeHead(200, { 'content-type': 'text/event-stream' }); res.write(': ready\n\n'); }
    else f.later(() => res.end('after-idle-stream'), 60);
  }, { bodyIdleTimeoutMs: 25 });
  let stream;
  try {
    stream = await open(f.port, '/plugins/events'); stream.resume();
    assert.equal((await read(f.port, '/data')).body, 'after-idle-stream');
    assert.equal(stream.destroyed, false);
    assert.equal((await diagnostics(f.port)).layers.sse.state, 'connected');
  } finally { stream?.destroy(); await f.close(); }
});
