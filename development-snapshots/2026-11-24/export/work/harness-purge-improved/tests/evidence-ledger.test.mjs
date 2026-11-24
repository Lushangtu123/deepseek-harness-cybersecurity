import test from 'node:test'
import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import { EvidenceLedger, evidenceId } from '../package/lib/redteam/evidence-ledger.mjs'

function fixture(t) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  return { db, ledger: new EvidenceLedger(db) }
}
const claim = () => ({ operation: 'bash', parameters: { cwd: '/fixture', command: 'printf ok' },
  result: { stdout: 'ok', exitCode: 0 }, engagement_id: 'fixture-a' })

async function observe(db, ledger, input, callId = 'call-proof') {
  const { recordNativeReceipt } = await import('../package/lib/redteam/personal-evidence-receipts.mjs')
  const c = ledger.record(input)
  const receipt = recordNativeReceipt(db, { ...input, tool_call_id: callId })
  const upgraded = ledger.upgrade({ claimed_ev_id: c.ev_id, receipt_id: receipt.receipt_id })
  assert.equal(upgraded.ok, true)
  return { claim: c.ev_id, observed: upgraded.ev_id, receipt: receipt.receipt_id }
}

test('a native upgrade closes its own claim, not the supporting claims it references', async t => {
  const { db, ledger } = fixture(t)
  const other = ledger.record({ ...claim(), result: { stdout: 'unverified other' } })
  await observe(db, ledger, { ...claim(), supporting_ev_ids: [other.ev_id] })
  assert.equal(ledger.countUnresolvedClaims('fixture-a'), 1)
  assert.equal(ledger.countUnverified('fixture-a'), 2)
})

test('derived evidence requires same-engagement native-observed support and remains pending', async t => {
  const { db, ledger } = fixture(t)
  const a = await observe(db, ledger, claim(), 'call-a')
  const b = await observe(db, ledger, { ...claim(), engagement_id: 'fixture-b' }, 'call-b')
  for (const supporting_ev_ids of [[], ['ev_' + '0'.repeat(64)], [a.claim], [b.observed], null, 'not-an-array', [a.observed, a.observed]]) {
    assert.equal(ledger.record({ ...claim(), confidence: 'derived', supporting_ev_ids }).ok, false,
      JSON.stringify(supporting_ev_ids))
  }
  const derived = ledger.record({ ...claim(), confidence: 'derived', supporting_ev_ids: [a.observed] })
  assert.equal(derived.ok, true)
  assert.equal(ledger.countUnverified('fixture-a'), 2)
  assert.equal(ledger.countUnresolvedClaims('fixture-a'), 1)
})

test('public input cannot self-assert authoritative provenance', t => {
  const { ledger } = fixture(t)
  for (const authority of ['tool-output', 'request-replay', 'database-record', 'screenshot']) {
    assert.equal(ledger.record({ ...claim(), authority, raw_ref: 'native:invented' }).ok, false, authority)
  }
})

test('legacy support links stay pending until an exact receipt is explicitly replayed', async t => {
  const { db, ledger } = fixture(t)
  const a = await observe(db, ledger, claim())
  const original = ledger.get(a.claim)
  // Represents an old database with evidence rows but no explicit verification link.
  db.exec('DROP TABLE IF EXISTS evidence_verification')
  const reopened = new EvidenceLedger(db)
  assert.equal(reopened.countUnresolvedClaims('fixture-a'), 1)
  const replay = reopened.upgrade({ claimed_ev_id: a.claim, receipt_id: a.receipt })
  assert.equal(replay.ev_id, a.observed)
  assert.equal(reopened.countUnresolvedClaims('fixture-a'), 0)
  assert.deepEqual(reopened.get(a.claim), original)
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM evidence').get().n, 2)
})

test('a verification link failure rolls back the observed row atomically', async t => {
  const { db, ledger } = fixture(t)
  db.exec(`CREATE TABLE IF NOT EXISTS evidence_verification (observed_ev_id TEXT, claimed_ev_id TEXT, receipt_id TEXT, engagement_id TEXT);
    CREATE TRIGGER reject_fixture_link BEFORE INSERT ON evidence_verification BEGIN SELECT RAISE(ABORT, 'fixture failure'); END;`)
  const { recordNativeReceipt } = await import('../package/lib/redteam/personal-evidence-receipts.mjs')
  const c = ledger.record(claim())
  const receipt = recordNativeReceipt(db, { ...claim(), tool_call_id: 'call-failure' })
  assert.equal(ledger.upgrade({ claimed_ev_id: c.ev_id, receipt_id: receipt.receipt_id }).ok, false)
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM evidence').get().n, 1)
  assert.equal(ledger.countUnresolvedClaims('fixture-a'), 1)
})

test('the supported reference limit still permits exact upgrade and derived conclusions can be verified', async t => {
  const { db, ledger } = fixture(t)
  const references = Array.from({ length: 64 }, (_, i) => 'ev_' + i.toString(16).padStart(64, '0'))
  const a = await observe(db, ledger, { ...claim(), supporting_ev_ids: references })
  const derived = ledger.record({ ...claim(), confidence: 'derived', supporting_ev_ids: [a.observed] })
  assert.equal(derived.ok, true)
  assert.equal(ledger.upgrade({ claimed_ev_id: derived.ev_id, receipt_id: a.receipt }).ok, true)
  assert.equal(ledger.countUnresolvedClaims('fixture-a'), 0)
})

test('exact replay preserves legacy rows whose references exceed new public input constraints', async t => {
  const { db, ledger } = fixture(t)
  const { recordNativeReceipt } = await import('../package/lib/redteam/personal-evidence-receipts.mjs')
  const input = claim(), receipt = recordNativeReceipt(db, { ...input, tool_call_id: 'legacy-proof' })
  for (const references of [Array.from({ length: 65 }, (_, i) => 'ev_' + i.toString(16).padStart(64, '0')), ['legacy-label', 'legacy-label']]) {
    // Construct the exact old record format; no migration rewrites hashes or references.
    const semantic = { ...input, confidence: 'claimed', authority: 'operator-input', limitations: [], supporting_ev_ids: references }
    const claimed = evidenceId({ ...semantic, supporting_ev_ids: [...references].sort() })
    const supporting = [...references, claimed]
    const observed = evidenceId({ ...semantic, confidence: 'observed', authority: 'tool-output', supporting_ev_ids: [...supporting].sort() })
    const insert = db.prepare(`INSERT INTO evidence (ev_id,confidence,authority,operation,parameters,result,supporting_ev_ids,engagement_id,raw_ref) VALUES(?,?,?,?,?,?,?,?,?)`)
    insert.run(claimed, 'claimed', 'operator-input', input.operation, JSON.stringify(input.parameters), JSON.stringify(input.result), JSON.stringify(references), input.engagement_id, null)
    insert.run(observed, 'observed', 'tool-output', input.operation, JSON.stringify(input.parameters), JSON.stringify(input.result), JSON.stringify(supporting), input.engagement_id, 'native:' + receipt.receipt_id)
    const before = ledger.get(claimed), beforeObserved = ledger.get(observed)
    const replay = ledger.upgrade({ claimed_ev_id: claimed, receipt_id: receipt.receipt_id })
    assert.equal(replay.ok, true)
    assert.equal(replay.ev_id, observed)
    assert.deepEqual(ledger.get(claimed), before)
    assert.deepEqual(ledger.get(observed), beforeObserved)
  }
  assert.equal(ledger.countUnresolvedClaims('fixture-a'), 0)
})

test('agent-provided records default to claimed/operator-input', (t) => {
  const { ledger } = fixture(t)
  const row = ledger.get(ledger.record(claim()).ev_id)
  assert.equal(row.confidence, 'claimed')
  assert.equal(row.authority, 'operator-input')
})

test('agent cannot mint observed/tool-output evidence', (t) => {
  const { ledger } = fixture(t)
  assert.equal(ledger.record({ ...claim(), confidence: 'observed', authority: 'tool-output' }).ok, false)
})

test('upgrade cannot reuse a claim without a native receipt', (t) => {
  const { ledger } = fixture(t)
  const c = ledger.record({ ...claim(), confidence: 'claimed', authority: 'subagent-report' })
  assert.equal(ledger.upgrade({ claimed_ev_id: c.ev_id, verified_result: claim().result }).ok, false)
  assert.equal(ledger.get(c.ev_id).confidence, 'claimed')
})

test('database count failure is unavailable rather than verified zero', (t) => {
  const { db, ledger } = fixture(t)
  db.exec('DROP TABLE evidence')
  assert.throws(() => ledger.countUnresolvedClaims('fixture-a'), /unavailable/i)
  assert.throws(() => ledger.countUnverified('fixture-a'), /unavailable/i)
})

test('native receipt validates engagement, operation, target, parameters and result', async (t) => {
  const { db, ledger } = fixture(t)
  const { recordNativeReceipt } = await import('../package/lib/redteam/personal-evidence-receipts.mjs')
  const original = claim()
  const receipt = recordNativeReceipt(db, { ...original, tool_call_id: 'call-fixture-1' })
  const c = ledger.record({ ...original, authority: 'subagent-report' })
  const valid = ledger.upgrade({ claimed_ev_id: c.ev_id, receipt_id: receipt.receipt_id })
  assert.equal(valid.ok, true)
  assert.equal(ledger.get(valid.ev_id).confidence, 'observed')
  assert.equal(ledger.get(c.ev_id).confidence, 'claimed')
  for (const patch of [
    { engagement_id: 'fixture-b' }, { operation: 'read' },
    { parameters: { ...original.parameters, cwd: '/other' } },
    { parameters: { ...original.parameters, command: 'printf different' } },
    { result: { stdout: 'different', exitCode: 0 } },
  ]) {
    const mismatched = ledger.record({ ...original, ...patch })
    assert.equal(ledger.upgrade({ claimed_ev_id: mismatched.ev_id,
      receipt_id: receipt.receipt_id }).ok, false, JSON.stringify(patch))
  }
  assert.equal(ledger.upgrade({ claimed_ev_id: c.ev_id, receipt_id: receipt.receipt_id,
    verified_result: { stdout: 'made-up', exitCode: 0 } }).ok, false)
})

test('native receipts are insert-only and duplicate call IDs cannot be replaced', async (t) => {
  const { db } = fixture(t)
  const { recordNativeReceipt } = await import('../package/lib/redteam/personal-evidence-receipts.mjs')
  const receipt = recordNativeReceipt(db, { ...claim(), tool_call_id: 'call-fixture-1' })
  assert.throws(() => db.prepare('UPDATE native_execution_receipt SET result_digest = ? WHERE receipt_id = ?')
    .run('fake', receipt.receipt_id), /immutable/i)
  assert.throws(() => db.prepare('DELETE FROM native_execution_receipt WHERE receipt_id = ?')
    .run(receipt.receipt_id), /immutable/i)
  assert.throws(() => recordNativeReceipt(db, { ...claim(), tool_call_id: 'call-fixture-1', result: {} }), /already|duplicate|conflict/i)
})

test('native result observer captures only successful bound native calls and disposes', async (t) => {
  const { db } = fixture(t)
  const { installNativeEvidenceObserver, listNativeReceipts } = await import('../package/lib/redteam/personal-evidence-receipts.mjs')
  let listener
  let dispose
  let removed = false
  const ctx = {
    on(name, handler) { assert.equal(name, 'tools/result'); listener = handler; return () => { removed = true } },
    effect(fn) { dispose = fn() },
    logger: { warn() {} },
  }
  installNativeEvidenceObserver(ctx, { db: () => db }, exec => exec.agent?.bound)
  const exec = { name: 'bash', callId: 'native-fixture', arguments: claim().parameters, agent: { bound: 'fixture-a' } }
  listener({ ...exec, name: 'redteam_evidence_record' }, { value: claim().result })
  listener({ ...exec, agent: {} }, { value: claim().result })
  listener({ ...exec, callId: 'failure' }, { isError: true, value: { stdout: 'failed', exitCode: 1 } })
  listener({ ...exec, callId: 'nonzero' }, { value: { stdout: 'failed', exitCode: 7 } })
  listener(exec, { isError: false, value: claim().result })
  assert.equal(listNativeReceipts(db, 'fixture-a').length, 1)
  dispose()
  assert.equal(removed, true)
})
