// Reconstruct the original inline scan-to-run conversion and compare every value.
import {readFileSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {digest} from '../../exports/deepseek-harness-vm/scripts/review_quality_gate.mjs';
const root = path.dirname(fileURLToPath(import.meta.url));
const read = name => JSON.parse(readFileSync(path.join(root, name), 'utf8'));
const dataset = read('dataset.json');
const records = [];
for (const phase of ['baseline', 'candidate']) {
  const scan = read(phase + '-scan.json');
  const raw = scan.native.result;
  const identity = read(phase + '-identity.json');
  const freeze = read(phase + '-freeze.json');
  if (scan.rulesSha256 !== identity.rules || raw.errors.length) throw Error('Rule or parser mismatch');
  const outputs = dataset.cases.map(row => {
    const file = row.id === 'xinference-before' ? 'before.py' : 'fixed.py';
    if (!raw.paths.scanned.includes('/src/' + file)) throw Error('Source not scanned');
    const hits = raw.results.filter(hit => hit.path === '/src/' + file
      && hit.start.line === row.location.line && hit.extra.metadata.cwe.includes(row.cwe));
    return {id: row.id, raw: hits.length ? 'hit' : 'no-hit',
      decision: hits.length ? 'unknown' : 'not-required', evidence: [],
      ...(hits.length ? {location: {sourceSha256: row.sourceSha256, line: row.location.line,
        column: hits[0].start.col}, language: row.language, cwe: row.cwe} : {})};
  });
  const run = {version: 2, identity, startedAt: read('poll.json').status.startedAt,
    datasetSha256: digest(dataset), freezeSha256: digest(freeze), outputs};
  if (digest(run) !== digest(read(phase + '-run.json'))) throw Error('Original conversion mismatch');
  records.push({phase, matched: true, runSha256: digest(run), outputs});
}
writeFileSync(path.join(root, 'scan-to-run-replay.json'), JSON.stringify({state: 'passed',
  capturedAt: new Date().toISOString(), records,
  scope: 'Post-review reconstruction and replay. The original invocation was inline and is not backdated.'}, null, 2) + '\n');
console.log(JSON.stringify({state: 'passed', matchedOriginalRuns: records.length}));
