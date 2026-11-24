/** Shared trusted session resolution for tools and role prompt assembly. */
export function sessionInfoOf(exec) {
  const agent = exec && exec.agent
  const session = agent && agent.session
  if (session === undefined || session === null) return {}
  const id = session.id === undefined ? undefined : String(session.id)
  let parentId
  try {
    const header = session.header
    parentId = header && header.parentSession !== undefined && header.parentSession !== null
      ? String(header.parentSession)
      : undefined
  } catch { parentId = undefined }
  return { id: id, parentId: parentId, session: session }
}

/** 会话 id（兼容旧调用点）。 */
function sessionOf(exec) {
  return sessionInfoOf(exec).id
}

/**
 * 解析"根会话"：一路沿 parentSession 走到最顶层的会话 id。
 * 主会话派出的子智能体因此共享同一个绑定键，而**不同主会话之间天然隔离**。
 * 顺手把沿途会话 id 都返回，便于把绑定缓存到子会话上。
 */
function resolveRootSession(session, store, remember) {
  const chain = []
  let cur = session
  let guard = 0
  while (cur !== undefined && cur !== null && guard < 64) {
    const info = sessionInfoOf({ agent: { session: cur } })
    if (info.id === undefined) break
    if (chain.includes(info.id)) throw new Error('会话父链存在循环，拒绝自动绑定')
    chain.push(info.id)
    if (info.parentId === undefined || info.parentId === '') break
    let parent
    try {
      parent = store?.sessionLookup?.(info.parentId)
    } catch { throw new Error('无法读取受信会话父链，请重新打开根会话') }
    if (parent === undefined || parent === null) {
      const ancestors = store.sessionBindings.lineageOf(info.parentId)
      if (ancestors.some(id => chain.includes(id)) || chain.length + ancestors.length > 64) throw new Error('会话父链存在循环或过深')
      const complete = chain.concat(ancestors)
      if (remember) store.sessionBindings.rememberChain(complete)
      return { rootId: complete[complete.length - 1], chain: complete }
    }
    cur = parent
    guard += 1
  }
  if (guard >= 64) throw new Error('会话父链过深，拒绝自动绑定')
  if (remember && chain.length) store.sessionBindings.rememberChain(chain)
  return { rootId: chain.length > 0 ? chain[chain.length - 1] : undefined, chain: chain }
}

/** 绑定键 + 会话链。 */
export function bindingKeyOf(exec, store, { remember = true } = {}) {
  const info = sessionInfoOf(exec)
  if (info.id === undefined) return { rootId: undefined, sessionId: undefined, chain: [] }
  const resolved = resolveRootSession(info.session, store, remember)
  const rootId = resolved.rootId === undefined ? info.id : resolved.rootId
  return { rootId, sessionId: info.id, chain: resolved.chain }
}

/**
 * 解析本次调用应作用在哪个靶标上（会话隔离版）。
 *
 * 顺序：① 显式传入 → ② 本会话及完整父链持久绑定；缺失或冲突时拒绝。
 *
 * 抛错而不是"随便挑一个"是刻意的：多会话并行时挑错靶标 = 把 A 单位的成果写进
 * B 单位的库、A 的报告里出现 B 的数据（这正是要多会话隔离的原因）。
 */
export function resolveEngagement(store, exec, explicit) {
  if (typeof explicit === 'string' && explicit.length > 0) return store.sessionBindings.validateTarget(explicit)
  const { rootId, sessionId, chain } = bindingKeyOf(exec, store)
  const keys = Array.from(new Set([rootId, sessionId, ...chain].filter(Boolean)))
  const id = store.sessionBindings.resolve(keys)
  store.sessionBindings.bind(keys, id, rootId) // preserve trusted inheritance across restarts
  return id
}

