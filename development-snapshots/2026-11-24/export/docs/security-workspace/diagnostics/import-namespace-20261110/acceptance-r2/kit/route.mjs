// Synthetic scanner receipts, real default Python and namespace evidence collectors.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const identity = JSON.parse(fs.readFileSync(path.join(root, 'identity.json')));
function verify() {
  for (const [name, expected] of Object.entries(identity.program)) {
    const file = path.join(root, 'package', name);
    assert.equal(fs.realpathSync(file), file);
    assert.equal(hash(fs.readFileSync(file)), expected);
  }
}
verify();
const {SecurityWorkbench, parseScanOutput} = await import('./package/lib/redteam/personal-security-workbench.mjs');
const {RedteamStore} = await import('./package/lib/redteam/store-core.js');
const {deepSemgrepProfile} = await import('./package/lib/redteam/personal-semgrep-profile.mjs');
const profile = deepSemgrepProfile();
const caller = 'from flask import request\nfrom evaluator import run as execute\ndef route():\n    code = request.args.get("code")\n    return execute(code)\n';
const controls = [
  {sink: 'eval', suffix: ', {}', imported: true},
  {sink: 'eval', suffix: ', {}, {}', imported: true},
  {sink: 'exec', suffix: ', {}', imported: true},
  {sink: 'exec', suffix: ', {}, {}', imported: true},
  {sink: 'eval', suffix: ', scope', imported: false},
  {sink: 'eval', suffix: ', {}, {}', calleeType: 'eval', imported: false},
  {sink: 'exec', suffix: ', {}', calleeType: 'exec', imported: false},
  {sink: 'eval', suffix: ', {}', callerType: 'request', imported: false},
  {sink: 'eval', suffix: ', {}', callerType: 'execute', imported: false},
];
const records = [];
for (const [index, control] of controls.entries()) {
  const home = path.join(root, 'control-' + index);
  const project = path.join(home, 'project');
  fs.mkdirSync(project, {recursive: true, mode: 0o700});
  const calleeName = control.calleeType ? 'run[' + control.calleeType + ']' : 'run';
  const callee = 'def ' + calleeName + '(value):\n    return ' + control.sink + '(value' + control.suffix + ')\n';
  const callerSource = control.callerType ? caller.replace('def route():', 'def route[' + control.callerType + ']():') : caller;
  fs.writeFileSync(path.join(project, 'routes.py'), callerSource);
  fs.writeFileSync(path.join(project, 'evaluator.py'), callee);
  const offset = Buffer.from(callee).indexOf(control.sink + '(');
  const end = Buffer.byteLength(callee) - 1;
  const span = {start: {line: 2, col: 12, offset}, end: {line: 2, col: 12 + end - offset, offset: end}};
  const scan = {results: [{check_id: 'policy.harness.python.dynamic-code-namespace',
    path: '/src/evaluator.py', ...span, extra: {message: 'Synthetic namespace scan fixture',
      severity: 'WARNING', metadata: {cwe: ['CWE-95']}}}], errors: [],
    paths: {scanned: ['/src/routes.py', '/src/evaluator.py']}};
  const store = new RedteamStore(path.join(home, 'state'));
  const engagement = store.openEngagement('Import namespace synthetic ' + index).id;
  const bench = new SecurityWorkbench(store, {workspaceRoot: home,
    toolStatus: () => ({semgrep: {ready: true, version: 'synthetic-scanner-receipt',
      admissionIdentity: 'b'.repeat(64), rules: {sha256: profile.baseRulesSha256},
      deepRules: {ready: true, profile}}})});
  let receiptCalls = 0;
  bench.runner = async (_tool, _plan, options) => {
    receiptCalls++;
    assert.equal(options.ruleProfile.rulesSha256, profile.rulesSha256);
    return {...parseScanOutput('semgrep', structuredClone(scan)), ruleProfile: options.ruleProfile,
      executedRules: {sha256: profile.rulesSha256, count: profile.ruleCount},
      coverageKey: hash(Buffer.from(JSON.stringify(scan)))};
  };
  try {
    bench.saveScope(engagement, {requestId: 'import-scope-' + index, revision: 0,
      repoRoot: project, tools: ['semgrep'], expiresAt: new Date(Date.now() + 120000).toISOString(), confirm: true});
    const run = bench.joint.start(engagement, {requestId: 'import-start-' + index,
      mode: 'deep', profileRevision: 1, steps: ['semgrep'], budgetSeconds: 40});
    await bench.joint.wait(engagement, {id: run.id, waitSeconds: 30});
    const task = bench.joint.status(engagement, {id: run.id}).task;
    assert.equal(task.state, 'completed', JSON.stringify(task));
    const sections = {};
    for (const section of ['findings', 'artifacts']) {
      sections[section] = [];
      let cursor;
      do {
        const response = bench.joint.report(engagement, {id: run.id, section, limit: 10,
          ...(cursor ? {cursor} : {})});
        sections[section].push(...response.page.items);
        cursor = response.page.nextCursor;
        if (response.page.complete) assert.equal(sections[section].length, response.page.total);
      } while (cursor);
    }
    const flows = sections.artifacts.filter(row => row.evidenceKind === 'python-import-flow');
    const structures = sections.artifacts.filter(row => row.evidenceKind === 'python-namespace-structure');
    assert.equal(flows.length, control.imported ? 1 : 0);
    assert.equal(structures.length, 1);
    assert.equal(task.steps[0].namespaceReview.execution.pythonVersion, '3.12.15');
    for (const flow of flows) {
      assert.equal(flow.path, 'routes.py');
      assert.equal(flow.calleeFile, 'evaluator.py');
      assert.equal(flow.sourceLine, 4);
      assert.equal(flow.line, 5);
      assert.equal(flow.sinkLine, 2);
      assert.equal(flow.sink, control.sink);
      assert.equal(flow.status, 'unverified');
    }
    assert.equal(sections.findings.length, 1);
    assert.equal(sections.findings[0].status, 'unverified');
    assert.equal(bench.db(engagement).prepare('SELECT COUNT(*) n FROM security_finding').get().n, 0);
    assert.equal(receiptCalls, 1);
    records.push({control, receiptCalls, task, sections,
      sourceFiles: {'routes.py': hash(Buffer.from(callerSource)), 'evaluator.py': hash(Buffer.from(callee))},
      ordinaryFindingRows: 0});
  } finally {
    await bench.dispose();
    await store.close();
  }
}
verify();
console.log(JSON.stringify({state: 'passed', syntheticControls: controls.length,
  programFilesRechecked: Object.keys(identity.program).length, nodeVersion: process.version,
  scannerInvocations: 0, modelCalls: 0, qualificationCasesAdded: 0, ordinaryR3Qualified: false,
  scope: 'Synthetic scanner/tool receipts with real default Python discovery and namespace sandbox. Conditional syntax observations only, no real Flask request or project code execution.', records}));
