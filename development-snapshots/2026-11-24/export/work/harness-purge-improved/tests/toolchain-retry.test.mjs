import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../package/client.js', import.meta.url), 'utf8');
function helper(name, end, scope = {}) {
  const start = source.indexOf('function ' + name + '('); assert.ok(start >= 0, name + ' is missing');
  return vm.runInNewContext('(' + source.slice(start, source.indexOf(end, start)).trim() + ')', scope);
}
const oldTime = '2026-10-26T22:30:00Z', nextTime = '2026-10-26T22:31:00Z';
const row = (project, checkedAt = oldTime) => ({ project, checkedAt, installed: { available: true, version: '6.8.0' }, comparison: { matchesLatestRelease: true }, queryState: 'completed' });
const report = (projects, checkedAt = oldTime) => ({ checkedAt, projects });
const merge = () => helper('mergeVmToolchainReport', '\n\t\tasync function readVmToolchain');

test('A single-project retry retains other project data and their original times', () => {
  const previous = report(['rea', 'reverse-skill', 'pentagi'].map(name => row(name)));
  const next = merge()(previous, report([row('rea', nextTime)], nextTime), 'rea');
  assert.deepEqual(JSON.parse(JSON.stringify(next.projects.slice(1))), previous.projects.slice(1));
  assert.equal(next.projects[0].checkedAt, nextTime);
});
test('An older per-project response cannot overwrite a newer successful result', () => {
  const previous = { ...report([{ ...row('rea', nextTime), _requestOrder: 2 }], nextTime), _requestOrder: 2 };
  const next = merge()(previous, report([{ ...row('rea'), queryState: 'timeout', comparison: {} }]), 'rea', 1);
  assert.equal(next.projects[0].queryState, 'completed');assert.equal(next.projects[0].checkedAt, nextTime);
});
test('A later request replaces an old result even when VM time moves backwards', () => {
  const previous = { ...report([{ ...row('rea', nextTime), _requestOrder: 1 }], nextTime), _requestOrder: 1 };
  const corrected = { ...row('rea'), installed: { available: true, version: 'synthetic-new' } };
  const next = merge()(previous, report([corrected]), 'rea', 2);
  assert.equal(next.projects[0].installed.version, 'synthetic-new');assert.equal(next.projects[0].checkedAt, oldTime);assert.equal(next.checkedAt, oldTime);
});
test('A late request with a future wall-clock time cannot replace the newest request', () => {
  const previous = { ...report([{ ...row('rea'), _requestOrder: 3 }]), _requestOrder: 3 };
  const next = merge()(previous, report([{ ...row('rea', nextTime), queryState: 'timeout' }], nextTime), 'rea', 2);
  assert.equal(next.projects[0].queryState, 'completed');assert.equal(next.projects[0].checkedAt, oldTime);
});
test('A retry cannot replace an unrelated project or accept duplicate and unknown rows', () => {
  const method = merge();
  for (const projects of [[row('pentagi')], [row('rea'), row('rea')], [row('outside')]]) assert.throws(() => method(null, report(projects), 'rea'));
});
test('Known error categories yield distinct safe Chinese instructions', () => {
  const issues = helper('vmToolchainIssues', '\n\t\tfunction mergeVmToolchainReport');
  const limited = issues({ latestRelease: { state: 'unavailable', errorCode: 'rate_limited', reason: 'PRIVATE_CANARY' } });
  const modified = issues({ installed: { available: false, errorCode: 'local_modified', changedFiles: 2 } });
  const container = issues({ installed: { available: false, errorCode: 'container_unavailable' } });
  assert.match(limited.join(' '), /GitHub.*限流/);assert.match(modified.join(' '), /本地文件.*改动/);assert.match(container.join(' '), /容器.*元数据/);
  assert.ok(!limited.join(' ').includes('PRIVATE_CANARY'));
});

function componentFixture() {
  const states = [], refs = [], pending = []; let stateIndex, refIndex, cleanup;
  const component = helper('VmToolchainStatusCard', '\n\t\tfunction VmWorkbenchManager', {
    useState(initial) { const index = stateIndex++; if (!(index in states)) states[index] = initial; return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }]; },
    useRef(initial) { const index = refIndex++; return refs[index] ??= { current: initial }; },
    useEffect(effect) { cleanup ??= effect(); },
    h: (tag, props, ...children) => ({ tag, props, children }), AbortController,
    vmToolchainLabel: () => '已确认', vmToolchainIssues: () => [], mergeVmToolchainReport: merge(),
    readVmToolchain(signal, project = 'all') { return new Promise((resolve, reject) => pending.push({ signal, project, resolve, reject })); }
  });
  return { states, pending, render() { stateIndex = refIndex = 0; return component(); }, close() { cleanup(); } };
}
function buttons(tree) {
  const result = []; const visit = node => { if (Array.isArray(node)) return node.forEach(visit); if (node && typeof node === 'object') { if (node.tag === 'button') result.push(node); visit(node.children); } }; visit(tree); return result;
}
test('The actual card retries the selected project and preserves completed peers', async () => {
  const f = componentFixture(); const all = buttons(f.render())[0].props.onClick();
  f.pending[0].resolve(report(['rea', 'reverse-skill', 'pentagi'].map(name => row(name)))); await all;
  const button = buttons(f.render()).find(node => node.props['aria-label'] === '仅重查 REA'); assert.ok(button);
  const retry = button.props.onClick(); assert.equal(f.pending[1].project, 'rea');
  assert.ok(buttons(f.render()).every(node => node.props.disabled));
  f.pending[1].resolve(report([row('rea', nextTime)], nextTime)); await retry;
  assert.equal(f.states[0].projects.find(item => item.project === 'pentagi').checkedAt, oldTime);
  assert.equal(f.states[0].projects[0].checkedAt, nextTime); f.close();
});
test('The actual card accepts a later retry after a backwards guest clock correction', async () => {
  const f = componentFixture();const first = buttons(f.render())[0].props.onClick();
  f.pending[0].resolve(report(['rea','reverse-skill','pentagi'].map(name=>row(name,nextTime)),nextTime));await first;
  const retry=buttons(f.render()).find(node=>node.props['aria-label']==='仅重查 REA').props.onClick();
  f.pending[1].resolve(report([{...row('rea'),installed:{available:true,version:'synthetic-new'}}]));await retry;
  assert.equal(f.states[0].projects[0].installed.version,'synthetic-new');assert.equal(f.states[0].projects[1].checkedAt,nextTime);f.close();
});
test('A failed or cancelled retry retains the previous report and ignores a late response', async () => {
  const f = componentFixture(); const first = buttons(f.render())[0].props.onClick();
  f.pending[0].resolve(report(['rea', 'reverse-skill', 'pentagi'].map(name => row(name)))); await first;
  const saved = f.states[0]; let retry = buttons(f.render()).find(node => node.props['aria-label'] === '仅重查 REA').props.onClick();
  f.pending[1].reject(Error('synthetic connection failure')); await retry; assert.equal(f.states[0], saved);
  retry = buttons(f.render()).find(node => node.props['aria-label'] === '仅重查 REA').props.onClick();
  f.close(); assert.equal(f.pending[2].signal.aborted, true);
  f.pending[2].resolve(report([row('rea', nextTime)], nextTime)); await retry; assert.equal(f.states[0], saved);
});
