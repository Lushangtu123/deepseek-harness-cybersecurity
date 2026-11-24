/** Trusted executor receipts. No model tool or HTTP operation may call the writer. */
import { createHash } from 'node:crypto'

export const NATIVE_RECEIPT_DDL = `
CREATE TABLE IF NOT EXISTS native_execution_receipt (
  receipt_id TEXT PRIMARY KEY,
  tool_call_id TEXT NOT NULL UNIQUE,
  engagement_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  target TEXT NOT NULL,
  parameters_digest TEXT NOT NULL,
  result_digest TEXT NOT NULL,
  exit_code INTEGER,
  recorded_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS native_receipt_no_update BEFORE UPDATE ON native_execution_receipt
BEGIN SELECT RAISE(ABORT, 'native receipts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS native_receipt_no_delete BEFORE DELETE ON native_execution_receipt
BEGIN SELECT RAISE(ABORT, 'native receipts are immutable'); END;
`

const canonical = (value) => {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}'
}
export function receiptDigest(value) {
  const text = JSON.stringify(value)
  if (text === undefined || Buffer.byteLength(text) > 8 * 1024 * 1024) throw new Error('receipt value is unavailable or too large')
  return createHash('sha256').update(canonical(JSON.parse(text))).digest('hex')
}
export function receiptTarget(parameters = {}) {
  for (const key of ['target', 'url', 'host', 'cwd', 'workdir', 'path']) {
    if (typeof parameters[key] === 'string' && parameters[key].trim()) return parameters[key].trim()
  }
  return 'local'
}
function identity(row) {
  return { tool_call_id: row.tool_call_id, engagement_id: row.engagement_id,
    operation: row.operation, target: row.target, parameters_digest: row.parameters_digest,
    result_digest: row.result_digest, exit_code: row.exit_code }
}
export function recordNativeReceipt(db, input) {
  for (const key of ['tool_call_id', 'engagement_id', 'operation']) {
    if (typeof input[key] !== 'string' || !input[key].trim() || input[key].length > 1024) throw new Error('receipt ' + key + ' required')
  }
  const row = {
    tool_call_id: input.tool_call_id, engagement_id: input.engagement_id, operation: input.operation,
    target: receiptTarget(input.parameters), parameters_digest: receiptDigest(input.parameters ?? {}),
    result_digest: receiptDigest(input.result),
    exit_code: Number.isSafeInteger(input.exit_code) ? input.exit_code : null,
  }
  if (input.target !== undefined && input.target !== row.target) throw new Error('receipt target mismatch')
  const receipt_id = 'nr_' + receiptDigest(identity(row))
  db.exec(NATIVE_RECEIPT_DDL)
  const previous = db.prepare('SELECT * FROM native_execution_receipt WHERE tool_call_id = ?').get(row.tool_call_id)
  if (previous) {
    if (previous.receipt_id === receipt_id) return { receipt_id, duplicate: true }
    throw new Error('native tool call already has a different receipt')
  }
  db.prepare(`INSERT INTO native_execution_receipt
    (receipt_id,tool_call_id,engagement_id,operation,target,parameters_digest,result_digest,exit_code,recorded_at)
    VALUES(?,?,?,?,?,?,?,?,?)`).run(receipt_id, row.tool_call_id, row.engagement_id, row.operation,
      row.target, row.parameters_digest, row.result_digest, row.exit_code, new Date().toISOString())
  return { receipt_id, duplicate: false }
}
export function matchingNativeReceipt(db, receipt_id, evidence, verified_result) {
  if (typeof receipt_id !== 'string' || !/^nr_[a-f0-9]{64}$/.test(receipt_id)) throw new Error('native receipt_id required')
  const row = db.prepare('SELECT * FROM native_execution_receipt WHERE receipt_id = ?').get(receipt_id)
  if (!row || row.receipt_id !== 'nr_' + receiptDigest(identity(row))) throw new Error('native receipt missing or invalid')
  if (row.engagement_id !== evidence.engagement_id || row.operation !== evidence.operation
      || row.target !== receiptTarget(evidence.parameters)
      || row.parameters_digest !== receiptDigest(evidence.parameters)
      || row.result_digest !== receiptDigest(evidence.result)
      || (verified_result !== undefined && row.result_digest !== receiptDigest(verified_result))) {
    throw new Error('native receipt does not match engagement, operation, target, parameters and result')
  }
  return row
}
export function listNativeReceipts(db, engagement_id, limit = 50) {
  const size = Math.max(1, Math.min(100, Number.isSafeInteger(limit) ? limit : 50))
  return db.prepare(`SELECT receipt_id,tool_call_id,operation,target,parameters_digest,result_digest,exit_code,recorded_at
    FROM native_execution_receipt WHERE engagement_id = ? ORDER BY recorded_at DESC,receipt_id LIMIT ?`).all(engagement_id, size)
}

export function installNativeEvidenceObserver(ctx, store, boundEngagement) {
  const native = new Set(['bash', 'read', 'glob', 'grep', 'write', 'edit', 'working_directory']);
  const off = ctx.on('tools/result', (exec, result) => {
    if (!native.has(exec?.name) || result?.isError || result?.value === undefined) return;
    const value = result.value;
    const exit = value?.exitCode ?? value?.exit_code;
    if (Number.isInteger(exit) && exit !== 0) return;
    try {
      const engagement_id = boundEngagement(exec);
      if (!engagement_id || !exec?.callId) return;
      recordNativeReceipt(store.db(engagement_id), { tool_call_id: String(exec.callId),
        engagement_id, operation: exec.name, parameters: exec.arguments ?? {}, result: value,
        exit_code: exit });
    } catch { ctx.logger?.warn?.('Native evidence receipt unavailable; no observed evidence was minted.'); }
  }, { global: true });
  ctx.effect(() => () => off?.());
}
