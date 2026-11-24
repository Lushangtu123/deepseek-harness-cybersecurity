// Browser-only helper, inlined by build-client.mjs and tested without React.
export function createBindingMonitor({ getSessionId, read, publish, now = Date.now }) {
  let selected, generation = 0, controller, latest, checkedAt, disposed = false
  const check = (force = false) => {
    if (disposed) return
    let id
    try { id = String(getSessionId?.() || '') }
    catch { publish({ state: 'unavailable', error: '无法读取当前会话' }); return }
    if (id === selected && !force) {
      if (latest && latest.state !== 'stale' && (now() - checkedAt >= 60000 || now() < checkedAt)) {
        latest = { ...latest, state: 'stale' }; publish(latest)
      }
      return
    }
    selected = id; const token = ++generation
    controller?.abort(); controller = new AbortController(); latest = undefined
    if (!id) { publish({ state: 'no-session' }); return }
    publish({ state: 'checking', sessionId: id })
    let request
    try { request = read(id, controller.signal) } catch (error) { request = Promise.reject(error) }
    Promise.resolve(request).then(result => {
      if (disposed || token !== generation || getSessionId?.() !== id) return
      if (result?.sessionId !== id || !['bound', 'unbound', 'unavailable'].includes(result?.state) || (result.state === 'bound' && (typeof result.engagement !== 'string' || !result.engagement))) throw new Error('绑定结果与当前聊天不匹配')
      checkedAt = now(); latest = { ...result, checkedAt }; publish(latest)
    }).catch(error => {
      if (!disposed && token === generation) publish({ state: 'unavailable', sessionId: id, error: error.message })
    })
  }
  return { check, dispose() { disposed = true; generation++; controller?.abort() } }
}
