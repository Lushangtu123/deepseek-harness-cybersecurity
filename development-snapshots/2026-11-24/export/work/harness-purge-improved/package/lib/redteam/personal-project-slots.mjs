import { randomUUID } from 'node:crypto'
import { bindingKeyOf, resolveEngagement } from './personal-session-resolution.mjs'
import { maxAgentsOf } from './settings.js'

// One process-local coordinator per shared store, including preset tool mounts.
const coordinators = new WeakMap()
export function projectSlotsFor(store) {
  if (!coordinators.has(store)) coordinators.set(store, new ProjectSlots(store))
  return coordinators.get(store)
}

export function installProjectSlotLifecycle(ctx, store) {
  const slots = projectSlotsFor(store)
  const off = [ctx.on('subagent/start', info => slots.started(info), { global: true }),
    ctx.on('subagent/end', info => slots.ended(info), { global: true }),
    ctx.on('session/event', (session, event) => slots.cataloged(session, event), { global: true })]
  ctx.effect(() => () => { for (const dispose of off) dispose?.() })
}

class ProjectSlots {
  constructor(store) { this.store = store; this.records = new Map(); this.queues = new Map(); this.pendingStarts = new Map() }
  started(info, catalogSession) {
    if (!info?.id || !info?.runId) return
    const existing = [...this.records.values()].find(record => record.childId === info.id)
    if (existing) { existing.runId = info.runId; return }
    // Native lifecycle payloads contain no parent argument. Associate only by
    // the trusted parent's durable catalog, never a model-supplied parent ID.
    for (const record of this.records.values()) {
      if (record.childId || (catalogSession && record.parent !== catalogSession.id)) continue
      let session
      try { session = catalogSession || this.store.sessionLookup?.(record.parent) } catch { continue }
      const events = session?.ownEvents?.() || session?.snapshotEvents?.(session.inheritedEventCount || 0)
        || (session?.events || []).filter(event => (event.seq ?? 0) >= (session?.inheritedEventCount || 0))
      const catalog = [...events].reverse().find(event => event.type === 'subagent/catalog' && event.data?.childId === info.id)
      if (catalog?.data?.label !== record.label) continue
      record.childId = info.id; record.runId = info.runId
      this.pendingStarts.delete(info.id); return
    }
    if (this.pendingStarts.size < 1000) this.pendingStarts.set(info.id, info)
  }
  ended(info) {
    if (!info?.id || !info?.runId) return
    if (this.pendingStarts.get(info.id)?.runId === info.runId) this.pendingStarts.delete(info.id)
    for (const [key, record] of this.records) {
      if (record.childId === info.id && record.runId === info.runId) this.records.delete(key)
    }
  }
  cataloged(session, event) {
    if (event?.type !== 'subagent/catalog') return
    const pending = this.pendingStarts.get(event.data?.childId)
    if (pending) this.started(pending, session)
  }
  async locked(project, action) {
    const previous = this.queues.get(project) || Promise.resolve()
    let release
    const next = new Promise(resolve => { release = resolve })
    this.queues.set(project, next)
    await previous
    try { return await action() }
    finally { release(); if (this.queues.get(project) === next) this.queues.delete(project) }
  }
  async snapshot(ctx, project) {
    const controller = new AbortController(), active = new Set()
    let timer, total = null, completed = 0
    const messages = {
      'registry-unavailable': '子代理注册表不可用，无法核实项目并发状态',
      'bindings-unavailable': '项目绑定无法核查，当前占用未知',
      'registry-error': '根会话查询失败，当前占用未知',
      'incomplete-branch': '子代理状态不完整，无法核实项目并发',
      timeout: '并发状态核实超时，当前占用未知',
      'settings-unavailable': '并发设置不可用，请修复配置或从备份恢复后重试。',
    }
    const tagged = new WeakSet()
    const failure = (kind, rootSession) => {
      const error = Object.assign(new Error(messages[kind]), { quotaKind: kind, quotaRoot: rootSession })
      tagged.add(error); return error
    }
    const summary = (kind, rootSession) => ({
      observedAt: new Date().toISOString(), kind, total, completed,
      unconfirmed: total === null ? null : Math.max(total - completed, 0),
      failed: rootSession === undefined ? [] : [{ rootSession, kind }], pendingRoots: [...active],
    })
    try {
      const registry = ctx.get?.('subagents')
      if (typeof registry?.listDescendants !== 'function') throw failure('registry-unavailable')
      let roots
      try { roots = new Set(this.store.sessionBindings.rootsFor(project)) }
      catch { throw failure('bindings-unavailable') }
      for (const record of this.records.values()) if (record.project === project) roots.add(record.owner)
      const ids = [...roots]; total = ids.length
      let cursor = 0
      const read = async () => {
        const groups = []
        while (cursor < ids.length) {
          controller.signal.throwIfAborted()
          const id = ids[cursor++]; active.add(id)
          try {
            const rows = await registry.listDescendants(id, controller.signal)
            controller.signal.throwIfAborted()
            if (!Array.isArray(rows) || rows.some(row => row?.kind === 'diagnostic')) throw failure('incomplete-branch', id)
            groups.push(rows); completed++
          } catch (error) {
            if (controller.signal.aborted || tagged.has(error)) throw error
            throw failure('registry-error', id)
          } finally { active.delete(id) }
        }
        return groups
      }
      const groups = await Promise.race([
        Promise.all(Array.from({ length: Math.min(8, ids.length) }, read)).then(groups => groups.flat()),
        new Promise((_, reject) => { timer = setTimeout(() => reject(failure('timeout')), 5000) })
      ])
      const running = new Map()
      for (const rows of groups) {
        for (const row of rows) if (row?.kind === 'child' && row.activity === 'running') {
          const linked = [...this.records.values()].find(record => record.childId === row.id)
          if (!linked || linked.project === project) running.set(String(row.id), row)
        }
      }
      const records = [...this.records.values()].filter(record => record.project === project)
      const children = new Set([...running.keys(), ...records.filter(record => record.childId).map(record => record.childId)])
      const used = children.size + records.filter(record => !record.childId).length
      let max
      try { max = maxAgentsOf(this.store.root) } catch { throw failure('settings-unavailable') }
      return { ok: true, engagement: project, max, used, free: Math.max(max - used, 0), running_from_registry: running.size,
        roots_checked: ids.length, running: [...running.values()], reservations: records.map(record => ({ ...record })), registry_available: true,
        quota_check: summary('complete') }
    } catch (cause) {
      const recognized = tagged.has(cause), kind = recognized ? cause.quotaKind : 'unavailable'
      const error = new Error(recognized ? cause.message : '并发状态无法核实，当前占用未知')
      error.quotaCheck = summary(kind, recognized ? cause.quotaRoot : undefined); throw error
    } finally { clearTimeout(timer); controller.abort() }
  }
  async status(ctx, project) {
    try { return await this.locked(project, () => this.snapshot(ctx, project)) }
    catch (error) {
      let max = null
      try { max = maxAgentsOf(this.store.root) } catch { /* Invalid settings cannot widen the limit. */ }
      return { ok: false, engagement: project, registry_available: false, used: null, free: null, max, error: error.message, quota_check: error.quotaCheck }
    }
  }
  async execute(ctx, args, exec) {
    try {
      const project = resolveEngagement(this.store, exec)
      const { rootId: owner, sessionId: parent } = bindingKeyOf(exec, this.store)
      return await this.locked(project, async () => {
        if (args.action === 'release') {
          const record = this.records.get(args.key)
          if (!record || record.project !== project || record.owner !== owner) return { ok: false, error: '需要当前会话持有的明确占位 key；未释放其他名额' }
          if (record.childId) return { ok: false, error: '名额已关联子代理运行批次，结束事件到达前不能手动释放' }
          this.records.delete(args.key)
          return { ok: true, engagement: project, released: true, slot: args.key }
        }
        const view = await this.snapshot(ctx, project)
        if (args.action === 'status') return view
        if (args.action !== 'acquire') return { ok: false, error: '未知名额动作' }
        if (typeof args.label !== 'string' || !args.label.trim() || args.label.length > 240) return { ok: false, error: 'acquire 必须填写最多240字符的任务标签，并在子代理派发 description 中使用同一标签' }
        if (view.free <= 0 || this.records.size >= 1000) return { ...view, ok: false, error: '项目并发名额已满，请等待或释放已失败派发的明确占位' }
        const key = randomUUID(), label = args.label
        this.records.set(key, { key, project, owner, parent, label, at: Date.now() })
        return { ...view, slot: key, used: view.used + 1, free: view.free - 1, hint: '派发时请使用相同任务标签；派发失败时携带此 key 释放名额。' }
      })
    } catch (error) { return { ok: false, registry_available: false, error: '无法核实项目并发：' + error.message, quota_check: error.quotaCheck } }
  }
}
