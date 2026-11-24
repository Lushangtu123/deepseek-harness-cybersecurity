import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../package/lib/redteam/client.js', import.meta.url), 'utf8');
const start = source.indexOf('    function TestingTab(props) {');
const end = source.indexOf('      const testing = ', start);
function fixture() {
  const hooks = [], effects = [], requests = [], timers = new Set();
  let cursor = 0, writes = 0;
  const React = {
    useState(value) { const i = cursor++; hooks[i] ??= { value: typeof value === 'function' ? value() : value }; return [hooks[i].value, next => { writes++; hooks[i].value = typeof next === 'function' ? next(hooks[i].value) : next; }]; },
    useRef(value) { const i = cursor++; return hooks[i] ??= { current: value }; },
    useEffect(fn, deps) { const i = cursor++, old = hooks[i]; if (!old || deps.some((dep, j) => dep !== old.deps[j])) { effects.push(() => { old?.cleanup?.(); hooks[i] = { deps, cleanup: fn() }; }); } }
  };
  const component = vm.runInNewContext('(' + source.slice(start, end) + 'return {load,data,err};})', {
    React, useCollapse: () => ({}), AbortController,
    api: (body, options) => new Promise((resolve, reject) => requests.push({ body, options, resolve, reject })),
    setInterval: fn => { timers.add(fn); return fn; }, clearInterval: fn => timers.delete(fn)
  });
  return { requests, timers, writes: () => writes,
    render(engagement, refreshKey = 0) { cursor = 0; const result = component({ engagement, refreshKey }); effects.splice(0).forEach(fn => fn()); return result; },
    unmount() { for (const hook of hooks) hook?.cleanup?.(); }
  };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
test('pending A cannot block B; late A cannot replace B or release its request guard', async () => {
  const f = fixture(); f.render('A'); f.render('B');
  assert.deepEqual(f.requests.map(x => x.body.engagement), ['A', 'B']);
  assert.equal(f.requests[0].options?.signal?.aborted, true);
  f.requests[0].resolve({ testing: ['old A'] }); await flush();
  f.render('B').load(); assert.equal(f.requests.length, 2);
  f.requests[1].resolve({ testing: ['new B'] }); await flush();
  assert.deepEqual(f.render('B').data.testing, ['new B']);
  f.render('B').load(); assert.equal(f.requests.length, 3); f.unmount();
});
test('global refresh during an in-flight request starts a new generation', async () => {
  const f = fixture(); f.render('A', 0); f.render('A', 1);
  assert.equal(f.requests.length, 2); f.requests[0].resolve({ stale: true }); await flush();
  f.requests[1].resolve({ fresh: true }); await flush();
  assert.equal(f.render('A', 1).data.fresh, true); f.unmount();
});
test('a rejected request allows a later manual retry', async () => {
  const f = fixture(); f.render('A'); f.requests[0].reject(Error('synthetic timeout')); await flush();
  f.render('A').load(); assert.equal(f.requests.length, 2); f.unmount();
});
test('unmount aborts pending work and removes polling; late completion makes no state writes', async () => {
  const f = fixture(); f.render('A'); f.unmount(); const writes = f.writes();
  assert.equal(f.requests[0].options?.signal?.aborted, true); assert.equal(f.timers.size, 0);
  f.requests[0].resolve({ stale: true }); await flush(); assert.equal(f.writes(), writes);
});
