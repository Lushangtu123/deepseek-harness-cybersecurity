// Post-review deterministic replay. Original freezes and raw scans stay immutable.
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {digest, evaluateReviewQuality} from '../../exports/deepseek-harness-vm/scripts/review_quality_gate.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const read = name => JSON.parse(readFileSync(path.join(root, name), 'utf8'));
const save = (name, value) => writeFileSync(path.join(root, name), JSON.stringify(value, null, 2) + '\n');
const dataset = read('dataset.json');
const diagnostic = read('dataset-diagnostic.json');
const policy = read('policy.json');
const ledger = read('ledger-before.json');
const checks = [];
for (const phase of ['baseline', 'candidate']) {
  const run = read(phase + '-run.json');
  const freeze = read(phase + '-freeze.json');
  if (run.datasetSha256 !== digest(dataset) || freeze.datasetSha256 !== digest(dataset)
      || run.freezeSha256 !== digest(freeze) || freeze.policySha256 !== digest(policy)
      || freeze.ledgerSha256 !== digest(ledger)) throw Error('Original canonical binding mismatch');
  const replayed = evaluateReviewQuality(dataset, run, freeze, policy, ledger);
  if (digest(replayed) !== digest(read(phase + '-quality.json'))) throw Error('Original quality changed');
  const corrected = evaluateReviewQuality(diagnostic, run, freeze, policy, ledger);
  if (corrected.state !== 'blocked' || corrected.r3Qualified !== false
      || corrected.categories['python/CWE-95'].total !== 0) throw Error('Curated pair entered qualification');
  save(phase + '-diagnostic-quality.json', corrected);
  checks.push({phase, originalReplayMatched: true, originalCanonicalBindingsMatched: true,
    correctedQualificationCases: corrected.categories['python/CWE-95'].total,
    diagnosticCases: corrected.categories['python/CWE-95'].diagnostic.total});
}
const raw = readFileSync(path.join(root, 'before.py'));
const hit = read('candidate-scan.json').native.result.results[0];
if (raw.subarray(hit.start.offset, hit.end.offset).toString() !== 'eval(model_output, {}, {})') {
  throw Error('Actual byte range mismatch');
}
save('evaluation-replay.json', {state: 'passed', capturedAt: new Date().toISOString(), checks,
  actualByteRangeMatched: true, offset: hit.start.offset,
  sourceSha256: createHash('sha256').update(raw).digest('hex'),
  retrospectiveCorrection: true, newFreezeCreated: false,
  correctionScope: 'Selection metadata and non-qualifying oracle role added after feedback. Old freeze/run mismatch remains explicit. This is not a fresh acceptance run.'});
console.log(JSON.stringify({state: 'passed', originalQualityReportsMatched: 2,
  correctedQualificationCases: 0, diagnosticCases: 2, newFreezeCreated: false}));
