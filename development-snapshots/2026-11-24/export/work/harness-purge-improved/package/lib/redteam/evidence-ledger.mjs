/**
 * 红队证据账本（活学活用 REA 的 Evidence 思想，不是照抄）
 *
 * rea 的 Evidence 是给"静态分析结论"做内容寻址的——observed/derived/inferred
 * 三档置信度，每条结论带 SHA-256 语义哈希。
 *
 * 这里改成红队语义：
 * · `claimed`   = 子智能体口头报告的"我拿到了"——红色词，指挥智能体绝不能直接信
 * · `observed`  = 实际工具回显/数据库记录证实的——指挥智能体核对后采信
 * · `derived`   = 从 observed 证据推理出来的
 * · `inferred`  = 子智能体/指挥智能体的推测，必须标注
 *
 * 每条 evidence 有 `ev_id = "ev_" + sha256(规范化语义)`——同一内容哈希必同，
 * 改一字哈希就变，落库时可验"子智能体说 A、库里记的是不是真的 A"。
 *
 * ResidualUnknown 从 rea 学来但改语义：rea 用来记"分析覆盖不到的未知"，
 * 这里记"红队作战里还**没打完、证据还不足**的问题"——比如"这台内网机器的
 * 22 端口可能是 SSH 但还没试出凭据"。
 *
 * 本模块零依赖，只依赖 Node 内建 crypto/sqlite。不依赖任何 Cordis 服务。
 */

import { createHash } from 'node:crypto'
import { DatabaseSync } from 'node:sqlite'
import { NATIVE_RECEIPT_DDL, matchingNativeReceipt } from './personal-evidence-receipts.mjs'

const NATIVE_VERIFIED = Symbol('native receipt verified')

/* ── 置信度与权威枚举 ─────────────────────────────────────────────────── */

export const EVIDENCE_CONFIDENCE = ['claimed', 'observed', 'derived', 'inferred']

export const EVIDENCE_AUTHORITY = [
  'tool-output',      // 直接工具回显（nmap/fscan/curl 原始输出）
  'database-record',  // 库里已有的行（SELECT 查出来的）
  'screenshot',       // 现场截图
  'request-replay',   // HTTP 原始请求重放成功
  'subagent-report',  // 子智能体回报（= claimed，必须核对）
  'operator-input',   // 用户/操作者提供
]

/** 子智能体回报必须经过核实才能从 claimed 升级为 observed */
export const CONFIDENCE_REQUIRES_VERIFICATION = new Set(['claimed', 'inferred', 'derived'])

/* ── 哈希工具 ─────────────────────────────────────────────────────────── */

/** 规范化 JSON：键按码点排序，确保语义相同哈希必同 */
const canonicalize = (value) => {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(',')}]`
  const keys = Object.keys(value).sort()
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalize(value[k])}`).join(',')}}`
}

/** 计算 evidence 的语义哈希，返回 "ev_" 前缀的 hex digest */
export const evidenceId = (semantic) => {
  const canonical = canonicalize(semantic)
  return 'ev_' + createHash('sha256').update(canonical, 'utf8').digest('hex')
}

/* ── Evidence DDL（独立的表，不动现有 schema）─────────────────────────── */

export const EVIDENCE_LEDGER_DDL = `
CREATE TABLE IF NOT EXISTS evidence (
  ev_id TEXT PRIMARY KEY,
  confidence TEXT NOT NULL CHECK(confidence IN ('claimed','observed','derived','inferred')),
  authority TEXT NOT NULL,
  operation TEXT NOT NULL,
  parameters TEXT NOT NULL DEFAULT '{}',
  result TEXT NOT NULL,
  raw_ref TEXT,
  limitations TEXT NOT NULL DEFAULT '[]',
  supporting_ev_ids TEXT NOT NULL DEFAULT '[]',
  recorded_by TEXT,
  recorded_at TEXT,
  source_agent TEXT,
  engagement_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_evidence_operation ON evidence(operation);
CREATE INDEX IF NOT EXISTS ix_evidence_confidence ON evidence(confidence);
CREATE INDEX IF NOT EXISTS ix_evidence_engagement ON evidence(engagement_id);

-- Supporting references describe context; only this native-written link closes a claim.
CREATE TABLE IF NOT EXISTS evidence_verification (
  observed_ev_id TEXT NOT NULL REFERENCES evidence(ev_id),
  claimed_ev_id TEXT NOT NULL REFERENCES evidence(ev_id),
  receipt_id TEXT NOT NULL REFERENCES native_execution_receipt(receipt_id),
  engagement_id TEXT NOT NULL,
  PRIMARY KEY (observed_ev_id, claimed_ev_id)
);
CREATE INDEX IF NOT EXISTS ix_evidence_verification_engagement ON evidence_verification(engagement_id);

CREATE TABLE IF NOT EXISTS residual_unknown (
  unk_id TEXT PRIMARY KEY,
  revision INTEGER NOT NULL DEFAULT 1,
  question TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open','investigating','blocked','contradicted','resolved')),
  severity TEXT NOT NULL DEFAULT 'medium'
    CHECK(severity IN ('low','medium','high','critical')),
  domain TEXT NOT NULL DEFAULT 'general',
  scope_digest TEXT,
  supporting_ev_ids TEXT NOT NULL DEFAULT '[]',
  contradicting_ev_ids TEXT NOT NULL DEFAULT '[]',
  required_authority TEXT,
  required_confidence TEXT,
  recommended_probe TEXT,
  resolution TEXT,
  recorded_by TEXT,
  recorded_at TEXT,
  resolved_at TEXT,
  engagement_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_unknown_status ON residual_unknown(status);
CREATE INDEX IF NOT EXISTS ix_unknown_engagement ON residual_unknown(engagement_id);
`

/* ── EvidenceLedger 类 ────────────────────────────────────────────────── */

/**
 * 挂载在某靶标 SQLite 句柄上的证据账本。
 *
 * 用法：
 *   import { EvidenceLedger, EVIDENCE_LEDGER_DDL } from './evidence-ledger.mjs'
 *   const ledger = new EvidenceLedger(db)   // db 是靶标数据库的 DatabaseSync 句柄
 *   ledger.record({ operation: 'nmap_scan', result: {...}, ... })
 *
 * 不自己 open/close 数据库，避免双重所有权；由 RedteamStore.db() 管理的句柄传入。
 */
export class EvidenceLedger {
  /** @param db DatabaseSync 句柄（已打开、已 migrate） */
  constructor(db) {
    this.db = db
    this.db.exec(EVIDENCE_LEDGER_DDL + NATIVE_RECEIPT_DDL)
  }

  /**
   * 记录一条 evidence。
   *
   * @param {object} input
   * @param {string} input.operation       操作名（如 "nmap_scan"、"suo5_tunnel_established"）
   * @param {object} input.parameters      调用参数（会规范化后参与哈希）
   * @param {object} input.result          规范化结果（会参与哈希）
   * @param {string} [input.confidence]    默认 'claimed'
   * @param {string} [input.authority]     默认 'operator-input'
   * @param {string[]} [input.limitations] 默认 []
   * @param {string[]} [input.supporting_ev_ids] 默认 []
   * @param {string} [input.recorded_by]   谁记的（指挥智能体/子角色名）
   * @param {string} [input.source_agent]  哪个子智能体产出的
   * @param {string} [input.engagement_id] 靶标 id
   *
   * @returns {{ok:true, ev_id:string, duplicate:boolean}|{ok:false, error:string}}
   */
  record(input, proof) {
    const {
      operation,
      parameters = {},
      result,
      confidence = 'claimed',
      authority = 'operator-input',
      limitations = [],
      supporting_ev_ids = [],
      recorded_by,
      source_agent,
      engagement_id,
      raw_ref,
    } = input

    if (!operation || typeof operation !== 'string') {
      return { ok: false, error: 'operation is required and must be a string' }
    }
    if (result === undefined || result === null) {
      return { ok: false, error: 'result is required' }
    }
    if (!EVIDENCE_CONFIDENCE.includes(confidence)) {
      return { ok: false, error: `confidence must be one of ${EVIDENCE_CONFIDENCE.join(',')}` }
    }
    if (!EVIDENCE_AUTHORITY.includes(authority)) {
      return { ok: false, error: `authority must be one of ${EVIDENCE_AUTHORITY.join(',')}` }
    }
    if ((confidence === 'observed' || !['operator-input', 'subagent-report'].includes(authority))
        && proof !== NATIVE_VERIFIED) {
      return { ok: false, error: 'authoritative evidence requires a matching native execution receipt' }
    }
    // New model input is bounded; a trusted exact upgrade must also replay old
    // rows written before these constraints without rewriting their hashes.
    if (proof !== NATIVE_VERIFIED && (!Array.isArray(supporting_ev_ids) || supporting_ev_ids.length > 64
        || supporting_ev_ids.some(id => typeof id !== 'string' || !/^ev_[a-f0-9]{64}$/.test(id))
        || new Set(supporting_ev_ids).size !== supporting_ev_ids.length)) {
      return { ok: false, error: 'supporting_ev_ids must contain at most 64 unique evidence IDs' }
    }
    if (confidence === 'derived') {
      try {
        if (!engagement_id || !supporting_ev_ids.length || supporting_ev_ids.some(id =>
          !this.db.prepare('SELECT * FROM evidence_verification WHERE observed_ev_id = ? AND engagement_id = ?')
            .all(id, engagement_id).some(link => this.matchesVerification(link, engagement_id)))) {
          return { ok: false, error: 'derived evidence requires native-verified observed support in the same engagement; the conclusion remains pending' }
        }
      } catch { return { ok: false, error: 'derived provenance unavailable' } }
    }

    const semantic = {
      operation,
      parameters: sanitizeForHash(parameters),
      result: sanitizeForHash(result),
      confidence,
      authority,
      limitations,
      supporting_ev_ids: [...supporting_ev_ids].sort(),
      engagement_id: engagement_id ?? null,
    }
    const ev_id = evidenceId(semantic)

    try {
      const existing = this.db
        .prepare('SELECT ev_id FROM evidence WHERE ev_id = ?')
        .get(ev_id)
      if (existing) return { ok: true, ev_id, duplicate: true }

      this.db
        .prepare(
          `INSERT INTO evidence
           (ev_id, confidence, authority, operation, parameters, result,
            raw_ref, limitations, supporting_ev_ids,
            recorded_by, recorded_at, source_agent, engagement_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
        )
        .run(
          ev_id,
          confidence,
          authority,
          operation,
          JSON.stringify(parameters),
          JSON.stringify(result),
          raw_ref ?? null,
          JSON.stringify(limitations),
          JSON.stringify(supporting_ev_ids),
          recorded_by ?? null,
          new Date().toISOString(),
          source_agent ?? null,
          engagement_id ?? null,
        )
      return { ok: true, ev_id, duplicate: false }
    } catch (err) {
      return { ok: false, error: String(err.message ?? err) }
    }
  }

  /** 按 ev_id 取一条 evidence（已解析 JSON 字段） */
  get(ev_id) {
    try {
      const row = this.db
        .prepare('SELECT * FROM evidence WHERE ev_id = ?')
        .get(ev_id)
      if (!row) return undefined
      return parseEvidenceRow(row)
    } catch {
      return undefined
    }
  }

  /**
   * 核对：子智能体说"我做了 X 得到 Y"，指挥智能体用此验证。
   * 返回 { matched: true } 或 { matched: false, expected_ev_id, actual_ev_id }
   */
  verify(input) {
    const { operation, parameters = {}, result, confidence = 'claimed', authority = 'operator-input', limitations = [], supporting_ev_ids = [], engagement_id } = input
    const semantic = {
      operation,
      parameters: sanitizeForHash(parameters),
      result: sanitizeForHash(result),
      confidence,
      authority,
      limitations,
      supporting_ev_ids: [...supporting_ev_ids].sort(),
      engagement_id: engagement_id ?? null,
    }
    const expected_ev_id = evidenceId(semantic)
    const found = this.get(expected_ev_id)
    return found && evidenceId({ ...semantic, result: sanitizeForHash(found.result), parameters: sanitizeForHash(found.parameters) }) === expected_ev_id
      ? { matched: true, ev_id: expected_ev_id }
      : { matched: false, expected_ev_id, actual_ev_id: null, note: 'no matching evidence in ledger' }
  }

  /**
   * 把 claimed / inferred / derived 升级为 observed。
   * 红队场景：子智能体回报 webshell 已上线（claimed），指挥智能体 curl 实测后升级。
   *
   * @returns {{ok:true, ev_id:string}|{ok:false, error:string}}
   */
  upgrade(input) {
    const { claimed_ev_id, verified_by, verified_result, receipt_id } = input
    const existing = this.get(claimed_ev_id)
    if (!existing) return { ok: false, error: `evidence not found: ${claimed_ev_id}` }
    try { matchingNativeReceipt(this.db, receipt_id, existing, verified_result) }
    catch (error) { return { ok: false, error: error.message } }
    if (existing.confidence === 'observed') return { ok: true, ev_id: claimed_ev_id }
    if (!CONFIDENCE_REQUIRES_VERIFICATION.has(existing.confidence)) {
      return { ok: false, error: `confidence '${existing.confidence}' does not require upgrade` }
    }

    // The row and its exact verification relationship commit together. Existing
    // evidence IDs and historical supporting references remain unchanged.
    try {
      this.db.exec('SAVEPOINT evidence_upgrade')
      const recorded = this.record({
      operation: existing.operation,
      parameters: existing.parameters,
      result: existing.result,
      confidence: 'observed',
      authority: 'tool-output',
      limitations: existing.limitations,
      supporting_ev_ids: [...existing.supporting_ev_ids, claimed_ev_id],
      recorded_by: verified_by ?? 'coordinator',
      source_agent: existing.source_agent,
      engagement_id: existing.engagement_id,
      raw_ref: 'native:' + receipt_id,
      }, NATIVE_VERIFIED)
      if (!recorded.ok) throw new Error(recorded.error)
      const observed = this.get(recorded.ev_id)
      const nativeId = observed?.raw_ref?.startsWith('native:') ? observed.raw_ref.slice(7) : null
      matchingNativeReceipt(this.db, nativeId, observed)
      matchingNativeReceipt(this.db, nativeId, existing)
      this.db.prepare(`INSERT OR IGNORE INTO evidence_verification
        (observed_ev_id,claimed_ev_id,receipt_id,engagement_id) VALUES(?,?,?,?)`)
        .run(recorded.ev_id, claimed_ev_id, nativeId, existing.engagement_id)
      this.db.exec('RELEASE evidence_upgrade')
      return recorded
    } catch (error) {
      try { this.db.exec('ROLLBACK TO evidence_upgrade; RELEASE evidence_upgrade') } catch {}
      return { ok: false, error: String(error.message ?? error) }
    }
  }

  matchesVerification(link, engagement_id) {
    const observed = this.get(link.observed_ev_id), claimed = this.get(link.claimed_ev_id)
    if (!observed || !claimed || observed.confidence !== 'observed' || observed.authority !== 'tool-output'
        || !CONFIDENCE_REQUIRES_VERIFICATION.has(claimed.confidence)
        || link.engagement_id !== engagement_id || observed.engagement_id !== engagement_id
        || claimed.engagement_id !== engagement_id || observed.raw_ref !== 'native:' + link.receipt_id) return false
    try {
      matchingNativeReceipt(this.db, link.receipt_id, observed)
      matchingNativeReceipt(this.db, link.receipt_id, claimed)
      return true
    } catch { return false }
  }

  /** 列出满足过滤条件的 evidence（分页） */
  list(filter = {}) {
    const { operation, confidence, engagement_id, limit = 50, offset = 0 } = filter
    const conditions = []
    const params = []
    if (operation) { conditions.push('operation = ?'); params.push(operation) }
    if (confidence) { conditions.push('confidence = ?'); params.push(confidence) }
    if (engagement_id) { conditions.push('engagement_id = ?'); params.push(engagement_id) }
    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
    try {
      const rows = this.db
        .prepare(`SELECT * FROM evidence ${where} ORDER BY recorded_at DESC LIMIT ? OFFSET ?`)
        .all(...params, limit, offset)
      return rows.map(parseEvidenceRow)
    } catch (err) {
      return { error: String(err.message ?? err) }
    }
  }

  /**
   * 账本里 claimed / inferred / derived 的**总条数**（含已核实闭环的）。
   * 审计与调试用；想知道"还有几条没核实"请用 countUnresolvedClaims。
   */
  countUnverified(engagement_id) {
    try {
      const row = this.db
        .prepare(
          `SELECT COUNT(*) AS n FROM evidence
           WHERE confidence IN ('claimed','inferred','derived') AND engagement_id = ?`,
        )
        .get(engagement_id)
      return row?.n ?? 0
    } catch {
      throw new Error('evidence count unavailable')
    }
  }

  /**
   * 只按精确、可重验的原生回执关系闭环。引用关系和模型推导本身不核实结论。
   * 旧记录不改写；没有显式关系的历史记录需重放匹配回执才会闭环。
   */
  countUnresolvedClaims(engagement_id) {
    try {
      const rows = this.db
        .prepare(
          `SELECT ev_id FROM evidence
           WHERE confidence IN ('claimed','inferred','derived') AND engagement_id = ?`,
        )
        .all(engagement_id)
      if (rows.length === 0) return 0
      const closed = new Set()
      const links = this.db.prepare('SELECT * FROM evidence_verification WHERE engagement_id = ?').all(engagement_id)
      for (const link of links) if (this.matchesVerification(link, engagement_id)) closed.add(link.claimed_ev_id)
      return rows.filter((r) => !closed.has(r.ev_id)).length
    } catch {
      throw new Error('evidence count unavailable')
    }
  }
}

/* ── ResidualUnknown（红队语义：未解决、证据还不足的作战问题）──────────── */

export class UnknownRegistry {
  constructor(db) {
    this.db = db
    this.db.exec(EVIDENCE_LEDGER_DDL) // 确保表存在（与 EvidenceLedger 共用 DDL）
  }

  /**
   * 记录一个"还没解决"的作战问题。
   *
   * 例：
   *   unk.record({
   *     question: '10.0.3.7:22 的 SSH 凭据是什么？',
   *     severity: 'high',
   *     domain: 'internal-recon',
   *     recommended_probe: 'hydra -l root -P /wordlists/ssh.txt 10.0.3.7 ssh',
   *   })
   */
  record(input) {
    const {
      question,
      severity = 'medium',
      domain = 'general',
      recommended_probe,
      supporting_ev_ids = [],
      engagement_id,
      recorded_by = 'coordinator',
    } = input

    if (!question || typeof question !== 'string') {
      return { ok: false, error: 'question is required' }
    }
    if (!['low', 'medium', 'high', 'critical'].includes(severity)) {
      return { ok: false, error: `severity must be low|medium|high|critical` }
    }

    const unk_id = 'unk_' + createHash('sha256')
      .update(canonicalize({ question: question.replace(/\s+/gu, ' ').trim(), domain }))
      .digest('hex')

    try {
      const existing = this.db
        .prepare('SELECT unk_id FROM residual_unknown WHERE unk_id = ?')
        .get(unk_id)
      if (existing) return { ok: true, unk_id, duplicate: true }

      this.db
        .prepare(
          `INSERT INTO residual_unknown
           (unk_id, revision, question, status, severity, domain,
            supporting_ev_ids, recommended_probe, recorded_by, recorded_at, engagement_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)`,
        )
        .run(
          unk_id,
          1,
          question.trim(),
          'open',
          severity,
          domain,
          JSON.stringify(supporting_ev_ids),
          recommended_probe ?? null,
          recorded_by,
          new Date().toISOString(),
          engagement_id ?? null,
        )
      return { ok: true, unk_id, duplicate: false }
    } catch (err) {
      return { ok: false, error: String(err.message ?? err) }
    }
  }

  /** 标记为 resolved（证据足够了）或 contradicted（发现是错的） */
  resolve(unk_id, disposition, resolution, resolved_by = 'coordinator') {
    if (!['resolved', 'contradicted', 'withdrawn'].includes(disposition)) {
      return { ok: false, error: 'disposition must be resolved|contradicted|withdrawn' }
    }
    try {
      this.db
        .prepare(
          `UPDATE residual_unknown
           SET status = ?, resolution = ?, resolved_at = ?
           WHERE unk_id = ?`,
        )
        .run(disposition, resolution ?? null, new Date().toISOString(), unk_id)
      return { ok: true, unk_id }
    } catch (err) {
      return { ok: false, error: String(err.message ?? err) }
    }
  }

  /** 列当前未解决的 unknowns（指挥智能体决定下一步派谁） */
  list(filter = {}) {
    const { status, severity, engagement_id, limit = 50, offset = 0 } = filter
    const conditions = []
    const params = []
    if (status) { conditions.push('status = ?'); params.push(status) }
    if (severity) { conditions.push('severity = ?'); params.push(severity) }
    if (engagement_id) { conditions.push('engagement_id = ?'); params.push(engagement_id) }
    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
    try {
      return this.db
        .prepare(`SELECT * FROM residual_unknown ${where} ORDER BY recorded_at DESC LIMIT ? OFFSET ?`)
        .all(...params, limit, offset)
        .map(parseUnknownRow)
    } catch (err) {
      return { error: String(err.message ?? err) }
    }
  }
}

/* ── 内部工具 ─────────────────────────────────────────────────────────── */

function parseEvidenceRow(row) {
  return {
    ...row,
    parameters: safeJsonParse(row.parameters, {}),
    result: safeJsonParse(row.result, null),
    limitations: safeJsonParse(row.limitations, []),
    supporting_ev_ids: safeJsonParse(row.supporting_ev_ids, []),
  }
}

function parseUnknownRow(row) {
  return {
    ...row,
    supporting_ev_ids: safeJsonParse(row.supporting_ev_ids, []),
    contradicting_ev_ids: safeJsonParse(row.contradicting_ev_ids, []),
  }
}

function safeJsonParse(text, fallback) {
  try {
    return JSON.parse(text)
  } catch {
    return fallback
  }
}

/** 参与哈希前去掉函数/undefined/BigInt 等 JSON 无法表达的值 */
function sanitizeForHash(value) {
  if (value === undefined) return null
  if (typeof value === 'bigint') return value.toString()
  if (typeof value === 'function') return '[function]'
  if (typeof value === 'symbol') return '[symbol]'
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(sanitizeForHash)
  const out = {}
  for (const [k, v] of Object.entries(value)) out[k] = sanitizeForHash(v)
  return out
}
