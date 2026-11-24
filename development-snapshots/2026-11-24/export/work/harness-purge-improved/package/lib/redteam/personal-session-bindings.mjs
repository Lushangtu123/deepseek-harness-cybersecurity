import { DatabaseSync } from 'node:sqlite'
import { chmodSync, existsSync, lstatSync } from 'node:fs'

/** One durable index per RedteamStore; no global-current fallback or model state. */
export class SessionBindings {
  constructor(file, targetExists) {
    if (existsSync(file) && lstatSync(file).isSymbolicLink()) throw new Error('Binding database cannot be a symlink')
    this.targetExists = targetExists
    this.db = new DatabaseSync(file)
    chmodSync(file, 0o600)
    this.db.exec(`PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS session_binding (
        session_id TEXT PRIMARY KEY, engagement_id TEXT NOT NULL, updated_at TEXT NOT NULL, root_session TEXT
      )`)
    this.db.exec('CREATE TABLE IF NOT EXISTS session_lineage (session_id TEXT PRIMARY KEY, parent_session TEXT)')
    if (!this.db.prepare('PRAGMA table_info(session_binding)').all().some(row => row.name === 'root_session')) this.db.exec('ALTER TABLE session_binding ADD COLUMN root_session TEXT')
    this.db.exec('CREATE INDEX IF NOT EXISTS session_binding_project_root ON session_binding(engagement_id,COALESCE(root_session,session_id))')
    this.db.exec('CREATE TABLE IF NOT EXISTS root_archive (engagement_id TEXT NOT NULL, root_session TEXT NOT NULL, archived INTEGER NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(engagement_id,root_session))')
  }
  validateTarget(id) {
    if (typeof id !== 'string' || !id || id.length > 512 || id === '.' || id === '..' || /[\\/\0]/.test(id) || !this.targetExists(id)) {
      throw new Error('绑定目标不存在或已失效 / binding target missing')
    }
    return id
  }
  keys(input) {
    if (!Array.isArray(input) || !input.length || input.some(key => typeof key !== 'string' || !key.trim() || key.length > 1024)) {
      throw new Error('Valid session binding keys required')
    }
    return [...new Set(input)]
  }
  bind(input, id, root = input?.[0]) {
    const keys = this.keys(input)
    this.keys([root])
    this.validateTarget(id)
    this.db.exec('BEGIN IMMEDIATE')
    try {
      const put = this.db.prepare('INSERT INTO session_binding (session_id,engagement_id,updated_at,root_session) VALUES (?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET engagement_id=excluded.engagement_id, updated_at=excluded.updated_at, root_session=excluded.root_session')
      for (const key of keys) put.run(key, id, new Date().toISOString(), root)
      this.db.exec('COMMIT')
    } catch (error) { this.db.exec('ROLLBACK'); throw error }
  }
  find(input) {
    const keys = this.keys(input), found = new Set()
    const get = this.db.prepare('SELECT engagement_id FROM session_binding WHERE session_id=?')
    for (const key of keys) {
      const row = get.get(key)
      if (row) found.add(this.validateTarget(row.engagement_id))
    }
    if (found.size > 1) throw new Error('会话与父会话绑定冲突 / binding conflict; explicitly rebind')
    return [...found][0]
  }
  resolve(input) {
    const id = this.find(input)
    if (!id) throw new Error('本会话尚未绑定项目；请使用 redteam_session_bind 或 redteam_engagement_open')
    return id
  }
  rootOf(key) {
    this.keys([key])
    return this.db.prepare('SELECT root_session FROM session_binding WHERE session_id=?').get(key)?.root_session
  }
  rememberChain(input) {
    const chain = this.keys(input)
    if (chain.length !== input.length || chain.length > 64) throw new Error('Invalid session ancestry')
    this.db.exec('BEGIN IMMEDIATE')
    try {
      const get = this.db.prepare('SELECT parent_session FROM session_lineage WHERE session_id=?')
      for (let i = 0; i < chain.length; i++) {
        const row = get.get(chain[i])
        if (row && row.parent_session !== (chain[i + 1] ?? null)) throw new Error('会话父链身份冲突 / ancestry conflict')
      }
      const put = this.db.prepare('INSERT OR IGNORE INTO session_lineage VALUES (?,?)')
      for (let i = 0; i < chain.length; i++) put.run(chain[i], chain[i + 1] ?? null)
      this.db.exec('COMMIT')
    } catch (error) { this.db.exec('ROLLBACK'); throw error }
  }
  lineageOf(key) {
    this.keys([key])
    const chain = [], get = this.db.prepare('SELECT parent_session FROM session_lineage WHERE session_id=?')
    while (key !== null) {
      if (chain.length >= 64 || chain.includes(key)) throw new Error('会话父链无效 / invalid ancestry')
      const row = get.get(key)
      if (!row) throw new Error('父会话缺少完整持久父链，请重新打开根会话')
      chain.push(key); key = row.parent_session
    }
    return chain
  }
  entries() {
    return this.db.prepare('SELECT session_id,engagement_id FROM session_binding ORDER BY updated_at DESC LIMIT 500').all()
      .map(row => [row.session_id, row.engagement_id])
  }
  rootPageFor(id, { after = '', limit = 32, onlyUnarchived = false } = {}) {
    this.validateTarget(id)
    if (typeof after !== 'string' || after.length > 1024 || !Number.isInteger(limit) || limit < 1 || limit > 64 || typeof onlyUnarchived !== 'boolean') throw new Error('Invalid binding page')
    const rows = this.db.prepare(`WITH roots AS (SELECT COALESCE(root_session,session_id) AS rootSession,
      COUNT(*) AS bindingCount, MAX(updated_at) AS updatedAt FROM session_binding
      WHERE engagement_id=? GROUP BY COALESCE(root_session,session_id))
      SELECT roots.*, COALESCE(a.archived,0) AS archived FROM roots
      LEFT JOIN root_archive a ON a.engagement_id=? AND a.root_session=roots.rootSession
      WHERE roots.rootSession>? AND (?=0 OR COALESCE(a.archived,0)=0)
      ORDER BY roots.rootSession LIMIT ?`).all(id, id, after, Number(onlyUnarchived), limit + 1)
    const items = rows.slice(0, limit).map(row => ({ ...row, archived: !!row.archived }))
    return { items, next: rows.length > limit ? items[items.length - 1].rootSession : null }
  }
  setRootArchived(id, rootSession, archived) {
    this.validateTarget(id); this.keys([rootSession])
    if (typeof archived !== 'boolean') throw new Error('归档状态必须是布尔值')
    this.db.exec('BEGIN IMMEDIATE')
    try {
      const hit = this.db.prepare('SELECT 1 FROM session_binding WHERE engagement_id=? AND COALESCE(root_session,session_id)=? LIMIT 1').get(id, rootSession)
      if (!hit) throw new Error('本项目不存在该根会话绑定')
      this.db.prepare(`INSERT INTO root_archive VALUES (?,?,?,?) ON CONFLICT(engagement_id,root_session)
        DO UPDATE SET archived=excluded.archived,updated_at=excluded.updated_at`).run(id, rootSession, Number(archived), new Date().toISOString())
      this.db.exec('COMMIT'); return { rootSession, archived }
    } catch (error) { this.db.exec('ROLLBACK'); throw error }
  }
  rootsFor(id) {
    const roots = []
    this.db.exec('BEGIN')
    try {
      let after = ''
      do {
        const page = this.rootPageFor(id, { after, limit: 64 })
        roots.push(...page.items.map(row => row.rootSession)); after = page.next
      } while (after !== null)
      this.db.exec('COMMIT'); return roots
    } catch (error) { this.db.exec('ROLLBACK'); throw error }
  }
  close() { if (this.db) { this.db.close(); this.db = null } }
}
