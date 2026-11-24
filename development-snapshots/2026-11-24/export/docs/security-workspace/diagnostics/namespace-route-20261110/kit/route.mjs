// Real joint collector and default namespace sandbox, with a recorded scanner result replay.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const identity = JSON.parse(fs.readFileSync(path.join(root, 'frozen-inputs.json')));
function checkProgram() {
  for (const [name, expected] of Object.entries(identity.programFiles)) {
    const file = path.join(root, 'package', name);
    assert.equal(fs.realpathSync(file), file);
    assert.equal(digest(fs.readFileSync(file)), expected);
  }
}
checkProgram();
for (const [name, expected] of Object.entries(identity.dataFiles)) {
  assert.equal(digest(fs.readFileSync(path.join(root, name))), expected);
}
const {SecurityWorkbench, parseScanOutput} = await import('./package/lib/redteam/personal-security-workbench.mjs');
const {RedteamStore} = await import('./package/lib/redteam/store-core.js');
const {deepSemgrepProfile} = await import('./package/lib/redteam/personal-semgrep-profile.mjs');
const profile = deepSemgrepProfile();
const candidateScan = JSON.parse(fs.readFileSync(path.join(root, 'candidate-scan.json'))).native.result;
const cases = [
  {name: 'namespace-candidate', scan: candidateScan, expectedFindings: 1, expectedEligible: 1},
  {name: 'patched-only', scan: {...candidateScan, results: [],
    paths: {...candidateScan.paths, scanned: ['/src/fixed.py']}},
    expectedFindings: 0, expectedEligible: 0},
];
const result = [];
for (const fixture of cases) {
  const work = path.join(root, fixture.name);
  fs.mkdirSync(work, {mode: 0o700});
  const project = path.join(work, 'project');
  fs.mkdirSync(project, {mode: 0o700});
  const names = fixture.name === 'patched-only' ? ['fixed.py'] : ['before.py', 'fixed.py'];
  for (const name of names) fs.copyFileSync(path.join(root, name), path.join(project, name));
  const store = new RedteamStore(path.join(work, 'state'));
  const engagement = store.openEngagement('Namespace routing diagnostic ' + fixture.name).id;
  const bench = new SecurityWorkbench(store, {workspaceRoot: work,
    toolStatus: () => ({semgrep: {ready: true, version: 'recorded-scan-replay',
      admissionIdentity: 'b'.repeat(64), rules: {sha256: profile.baseRulesSha256},
      deepRules: {ready: true, profile}}})});
  let scannerReplayCalls = 0;
  const seen = [];
  const defaultCollector = bench.namespaceEvidence;
  bench.namespaceEvidence = async (...args) => {
    const value = await defaultCollector(...args);
    seen.push(value.summary);
    return value;
  };
  bench.runner = async (_tool, _plan, options) => {
    scannerReplayCalls++;
    assert.equal(options.ruleProfile.rulesSha256, profile.rulesSha256);
    return {...parseScanOutput('semgrep', structuredClone(fixture.scan)),
      ruleProfile: options.ruleProfile,
      executedRules: {sha256: profile.rulesSha256, count: profile.ruleCount},
      coverageKey: digest(Buffer.from(JSON.stringify({profile, recordedScan: fixture.scan})))};
  };
  try {
    bench.saveScope(engagement, {requestId: 'namespace-scope-' + fixture.name, revision: 0,
      repoRoot: project, tools: ['semgrep'], expiresAt: new Date(Date.now() + 120000).toISOString(), confirm: true});
    const run = bench.joint.start(engagement, {requestId: 'namespace-start-' + fixture.name,
      mode: 'deep', profileRevision: 1, steps: ['semgrep'], budgetSeconds: 40});
    await bench.joint.wait(engagement, {id: run.id, waitSeconds: 30});
    const task = bench.joint.status(engagement, {id: run.id}).task;
    assert.equal(task.state, 'completed', JSON.stringify(task));
    assert.equal(scannerReplayCalls, 1);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].eligible, fixture.expectedEligible);
    const sections = {};
    for (const section of ['findings', 'artifacts']) {
      sections[section] = [];
      let cursor;
      do {
        const reply = bench.joint.report(engagement, {id: run.id, section, limit: 10, ...(cursor ? {cursor} : {})});
        sections[section].push(...reply.page.items);
        cursor = reply.page.nextCursor;
        if (reply.page.complete) assert.equal(sections[section].length, reply.page.total);
      } while (cursor);
    }
    assert.equal(sections.findings.length, fixture.expectedFindings);
    if (fixture.expectedEligible) {
      assert.equal(seen[0].state, 'completed');
      assert.equal(seen[0].checked, 1);
      assert.equal(seen[0].observations, 1);
      assert.equal(seen[0].execution.pythonVersion, '3.12.15');
      const artifact = sections.artifacts.find(row => row.evidenceKind === 'python-namespace-structure');
      assert.ok(artifact);
      assert.equal(artifact.path, 'before.py');
      assert.equal(artifact.line, 46);
      assert.equal(artifact.argumentCount, 3);
      assert.equal(artifact.status, 'unverified');
      assert.equal(artifact.externalControl, 'unverified');
      assert.equal(artifact.builtinIdentity, 'unverified');
      assert.equal(artifact.sourceLocation.start.offset, 1466);
      assert.equal(artifact.sourceLocation.end.offset, 1492);
      assert.equal(artifact.sourceLocation.sourceSha256, digest(fs.readFileSync(path.join(root, 'before.py'))));
      assert.equal(sections.findings[0].status, 'unverified');
    } else {
      assert.equal(seen[0].state, 'not-applicable');
      assert.equal(sections.artifacts.filter(row => row.evidenceKind === 'python-namespace-structure').length, 0);
    }
    assert.equal(bench.db(engagement).prepare('SELECT COUNT(*) n FROM security_finding').get().n, 0);
    result.push({name: fixture.name, scannerReplayCalls,
      replayScope: fixture.name === 'patched-only' ? 'fixed-file subset of recorded candidate scan' : 'entire recorded candidate scan', task, sections,
      namespaceReview: seen[0], ordinaryFindingRows: 0});
  } finally {
    await bench.dispose();
    await store.close();
  }
}
checkProgram();
console.log(JSON.stringify({state: 'passed', nodeVersion: process.version,
  nodeExecutable: process.execPath, nodeExecutableSha256: digest(fs.readFileSync(process.execPath)),
  programFilesRechecked: Object.keys(identity.programFiles).length,
  scannerInvocations: 0, scannerReplays: result.length, modelCalls: 0,
  qualificationCasesAdded: 0, ordinaryR3Qualified: false,
  scope: 'Existing joint deep orchestration with recorded scanner JSON and fixture readiness. Default real namespace sandbox. No fresh scan or full UI/model acceptance.',
  cases: result}));
