import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../package/lib/redteam/client.js', import.meta.url), 'utf8')
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data })

// Execute the actual module factory with a minimal Hook host; no app entry, DOM,
// network or browser state is touched. Effects use real dependency/cleanup ordering.
function host(fetchImpl, timer = {}) {
  let index = 0, pending = [], cells = [], current, dirty = false, props, component, result
  const windowEvents = timer.windowEvents || new Map()
  const React = {
    Component: class {},
    createElement: (type, properties, ...children) => ({ type, props: properties || {}, children: children.flat(Infinity).filter(x => x !== null && x !== undefined && x !== false) }),
    useState: initial => {
      const n = index++
      if (!cells[n]) cells[n] = { value: typeof initial === 'function' ? initial() : initial }
      return [cells[n].value, value => { cells[n].value = typeof value === 'function' ? value(cells[n].value) : value; dirty = true }]
    },
    useRef: initial => {
      const n = index++
      if (!cells[n]) cells[n] = { current: initial }
      return cells[n]
    },
    useEffect: (effect, deps) => {
      const n = index++, previous = cells[n]
      if (!previous || deps.some((d, i) => d !== previous.deps[i])) pending.push(() => {
        previous?.cleanup?.()
        cells[n] = { deps, cleanup: effect() }
      })
    },
  }
  const context = {
    console, fetch: fetchImpl, AbortController, Event,
    CustomEvent: class extends Event { constructor(type, options = {}) { super(type); this.detail = options.detail } },
    Date: timer.Date || Date, performance: timer.performance || performance,
    document: { visibilityState: 'visible', addEventListener: timer.addDocumentListener || (() => {}), removeEventListener: () => {} },
    setInterval: timer.setInterval || ((...args) => { const id = setInterval(...args); id.unref(); return id }), clearInterval: timer.clearInterval || clearInterval,
    setTimeout: timer.setTimeout || setTimeout,
    clearTimeout: timer.clearTimeout || clearTimeout,
    window: {
      addEventListener: (name, fn) => { if (!windowEvents.has(name)) windowEvents.set(name, new Set()); windowEvents.get(name).add(fn); timer.addEventListener?.(name, fn) },
      removeEventListener: (name, fn) => { windowEvents.get(name)?.delete(fn) },
      dispatchEvent: event => { for (const fn of [...(windowEvents.get(event.type) || [])]) fn(event); return true },
      localStorage: { getItem: () => null, setItem: () => {} }, __ModuleLoader__: { load: spec => { current = spec.factory(() => React) } },
    },
    navigator: { clipboard: { writeText: async () => {} } },
  }
  const instrumented = source.replace('    return module.exports\n', '    module.exports.test = { api, FindingsTab, ReportTab, SessionTab, PromptsTab, AgentsTab, ConcurrencyCard, BindingHistoryCard: typeof BindingHistoryCard === "function" ? BindingHistoryCard : undefined }; return module.exports\n')
  vm.runInNewContext(instrumented, context, { filename: 'redteam-client.js' })
  function render(next = props) {
    props = next
    for (let turn = 0; turn < 10; turn++) {
      index = 0; dirty = false; result = current.test[component](props)
      const effects = pending; pending = []; effects.forEach(fn => fn())
      if (!dirty) return result
    }
    throw new Error('Hook fixture render did not settle')
  }
  return {
    api: current.test.api,
    preview: next => {
      props = next; index = 0
      const saved = pending; pending = []
      const tree = current.test[component](props)
      pending = saved; return tree
    },
    mount: (name, initial) => { component = name; return render(initial) },
    render,
    unmount: () => cells.forEach(x => x?.cleanup?.()),
  }
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return []
  return [tree, ...(tree.children || []).flatMap(nodes)]
}
function text(tree) { return typeof tree === 'string' || typeof tree === 'number' ? String(tree) : (tree?.children || []).map(text).join(' ') }
function button(tree, label) {
  const node = nodes(tree).find(n => n.type === 'button' && text(n) === label)
  assert.ok(node, `Missing button ${label}`)
  return node
}

test('API rejects an HTTP error even when it has a JSON body', async () => {
  const h = host(async () => response({ items: [] }, 503))
  await assert.rejects(h.api({ op: 'vulns' }), /503/)
})

test('Read-only data loads retry a transient connection failure at most twice', async () => {
  let calls = 0
  const h = host(async () => {
    if (++calls < 3) throw new TypeError('Failed to fetch')
    return response({ ok: true, items: ['ready'] })
  })
  assert.deepEqual(JSON.parse(JSON.stringify(await h.api({ op: 'vulns' }))), { ok: true, items: ['ready'] })
  assert.equal(calls, 3)
})

test('Writes, secret reveals, and unknown operations never retry', async () => {
  for (const op of ['addCredential', 'credentialReveal', 'openEngagement', 'execute', 'futureRead']) {
    let calls = 0
    const h = host(async () => { calls++; throw new TypeError('Failed to fetch') })
    await assert.rejects(h.api({ op }), /Failed to fetch/)
    assert.equal(calls, 1, op)
  }
})

test('Read retries stop on authentication failures, invalid JSON, and cancellation', async () => {
  for (const failure of [() => response({}, 401), () => ({ ok: true, json: async () => { throw new SyntaxError('invalid JSON') } })]) {
    let calls = 0
    const h = host(async () => { calls++; return failure() })
    await assert.rejects(h.api({ op: 'credentials' }))
    assert.equal(calls, 1)
  }
  let calls = 0
  const abort = new AbortController()
  abort.abort()
  const h = host(async () => { calls++; return response({ ok: true }) })
  await assert.rejects(h.api({ op: 'vulns' }, { signal: abort.signal }), /取消/)
  assert.equal(calls, 0)
})

test('API deadline aborts a stalled fetch and rejects visibly', async () => {
  let deadline, aborted = false
  const h = host((_url, opts) => new Promise((_resolve, reject) => {
    opts.signal?.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')) })
  }), { setTimeout: fn => { deadline = fn; return 1 }, clearTimeout: () => {} })
  const request = h.api({ op: 'vulns' })
  const rejected = assert.rejects(request, /超时/)
  await flush()
  assert.equal(typeof deadline, 'function', 'A bounded request deadline must be scheduled')
  deadline()
  await rejected
  assert.equal(aborted, true)
})

test('Findings keeps B after A returns late, including credentials', async () => {
  const pending = []
  const h = host((_url, opts) => new Promise(resolve => pending.push({ request: JSON.parse(opts.body), resolve })))
  h.mount('FindingsTab', { engagement: 'A' })
  h.render({ engagement: 'B' })
  await flush()
  for (const p of pending.filter(p => p.request.engagement === 'B')) p.resolve(response({ ok: true, total: 1, items: p.request.op === 'vulns' ? [{ id: 2, title: 'B finding', target: 'b.lab', severity: 'low' }] : [] }))
  await flush(); h.render()
  for (const p of pending.filter(p => p.request.engagement === 'A')) p.resolve(response({ ok: true, total: 1, items: p.request.op === 'vulns' ? [{ id: 1, title: 'A finding', target: 'a.lab', severity: 'low' }] : [] }))
  await flush()
  const tree = h.render()
  assert.equal(JSON.stringify(tree).includes('B finding'), true)
  assert.equal(JSON.stringify(tree).includes('A finding'), false)
  h.unmount()
})

test('Findings paginates 201 records with offset and resets page for a new project', async () => {
  const requests = []
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body); requests.push(req)
    if (req.op !== 'vulns') return response({ ok: true, items: [] })
    const offset = req.offset || 0
    const items = Array.from({ length: Math.min(200, 201 - offset) }, (_, i) => ({ id: offset + i + 1, title: 'finding-' + (offset + i + 1), target: 'lab', severity: 'low' }))
    return response({ ok: true, total: 201, items, next_offset: offset === 0 ? 200 : null })
  })
  h.mount('FindingsTab', { engagement: 'A' }); await flush()
  let tree = h.render()
  button(tree, '下一页').props.onClick(); h.render(); await flush(); tree = h.render()
  assert.equal(requests.filter(x => x.op === 'vulns').at(-1).offset, 200)
  assert.equal(JSON.stringify(tree).includes('finding-201'), true)
  assert.equal(button(tree, '下一页').props.disabled, true)
  h.render({ engagement: 'B' }); await flush(); h.render()
  assert.equal(requests.filter(x => x.op === 'vulns').at(-1).offset, 0)
  h.unmount()
})

test('Credentials never render legacy plaintext by default and reveal one item explicitly', async () => {
  const requests = []
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body); requests.push(req)
    if (req.op === 'credentials') return response({ ok: true, items: [{ id: 7, host: 'lab', has_secret: true, secret_value: 'legacy-secret-must-not-render' }] })
    if (req.op === 'credentialReveal') return response({ ok: true, item: { id: 7, secret_value: 'explicit-synthetic-secret' } })
    return response({ ok: true, items: [], total: 0 })
  })
  h.mount('FindingsTab', { engagement: 'A' }); await flush()
  let tree = h.render()
  nodes(tree).find(n => n.props?.['aria-label'] === '凭据（1）').props.onClick()
  tree = h.render()
  assert.equal(JSON.stringify(tree).includes('legacy-secret-must-not-render'), false)
  assert.equal(requests.some(x => x.op === 'credentialReveal'), false)
  button(tree, '显示').props.onClick({ stopPropagation() {} }); await flush(); tree = h.render()
  assert.equal(JSON.stringify(tree).includes('explicit-synthetic-secret'), true)
  assert.deepEqual(requests.find(x => x.op === 'credentialReveal'), { op: 'credentialReveal', engagement: 'A', id: 7 })
  button(tree, '隐藏').props.onClick({ stopPropagation() {} }); tree = h.render()
  assert.equal(JSON.stringify(tree).includes('explicit-synthetic-secret'), false)
  h.unmount()
})

test('Report ignores an old project response and displays a failed load as an error', async () => {
  const pending = []
  const h = host((_url, opts) => new Promise(resolve => pending.push({ request: JSON.parse(opts.body), resolve })))
  h.mount('ReportTab', { engagement: 'A' }); h.render({ engagement: 'B' }); await flush()
  pending.find(p => p.request.engagement === 'B').resolve(response({ ok: true, markdown: 'B-report', items: [], stages: [], summary: { points: 222, count: 0 } }))
  await flush(); h.render()
  pending.find(p => p.request.engagement === 'A').resolve(response({ ok: true, markdown: 'A-report', items: [], stages: [], summary: { points: 111, count: 0 } }))
  await flush(); let tree = h.render()
  assert.match(text(tree), /222 分/)
  assert.doesNotMatch(text(tree), /111 分/)
  h.render({ engagement: 'C' }); await flush()
  pending.find(p => p.request.engagement === 'C').resolve(response({}, 503))
  await flush(); tree = h.render()
  assert.match(text(tree), /503/)
  assert.doesNotMatch(text(tree), /加载中…/)
  h.unmount()
})

test('A late credential reveal cannot display its secret in the next project', async () => {
  let reveal
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body)
    if (req.op === 'credentialReveal') return new Promise(resolve => { reveal = resolve })
    if (req.op === 'credentials') return response({ ok: true, items: [{ id: 7, host: req.engagement, has_secret: true }] })
    return response({ ok: true, items: [], total: 0 })
  })
  h.mount('FindingsTab', { engagement: 'A' }); await flush()
  let tree = h.render()
  nodes(tree).find(n => n.props?.['aria-label'] === '凭据（1）').props.onClick()
  tree = h.render(); button(tree, '显示').props.onClick({ stopPropagation() {} }); await flush()
  h.render({ engagement: 'B' }); await flush()
  reveal(response({ ok: true, item: { id: 7, secret_value: 'A-only-late-secret' } }))
  await flush(); tree = h.render()
  assert.doesNotMatch(text(tree), /A-only-late-secret/)
  h.unmount()
})

test('Session and report views do not display a legacy raw connection password', async () => {
  const shell = { id: 2, shell_type: 'behinder', url: 'http://lab.local/', pass_key: 'synthetic-legacy-connection-secret' }
  const h = host(async () => response({ ok: true, webshells: [shell], tunnels: [], totals: {webshells:1,webshellsOnline:0,tunnels:0,tunnelsActive:0,tunnelsLegit:0,tunnelsSelfOnly:0,credentials:0,access:0} }))
  h.mount('SessionTab', { engagement: 'A' }); await flush()
  assert.doesNotMatch(text(h.render()), /synthetic-legacy-connection-secret/)
  h.unmount()
  const reportItem = { id: 2, seq: 1, points: 1, webshells: [shell], steps: [] }
  const r = host(async () => response({ ok: true, markdown: 'owned-report', summary: { count: 1, points: 1 }, items: [reportItem], stages: [{ code: 's', name: 'Stage', points: 1, cumulative: 1, color: '#111111', items: [reportItem] }] }))
  r.mount('ReportTab', { engagement: 'A' }); await flush()
  assert.match(text(r.render()), /Stage/)
  assert.doesNotMatch(text(r.render()), /synthetic-legacy-connection-secret/)
  r.unmount()
})


test('Prompt drafts cannot be saved into a different project while its read is pending', async () => {
  const pending = [], requests = []
  const h = host((_url, opts) => {
    const req = JSON.parse(opts.body); requests.push(req)
    if (req.op === 'savePrompt') return Promise.resolve(response({ ok: true }))
    return new Promise(resolve => pending.push({ req, resolve, signal: opts.signal }))
  })
  h.mount('PromptsTab', { engagement: 'A' })
  pending[0].resolve(response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: 'A_ONLY' }] }))
  await flush(); let tree = h.render()
  assert.equal(nodes(tree).find(n => n.type === 'textarea').props.value, 'A_ONLY')
  const oldSave = button(tree, '保存').props.onClick
  tree = h.render({ engagement: 'B' })
  assert.equal(button(tree, '保存').props.disabled, true, 'B must finish loading before saving')
  assert.notEqual(nodes(tree).find(n => n.type === 'textarea').props.value, 'A_ONLY')
  button(tree, '保存').props.onClick(); oldSave(); await flush()
  assert.equal(requests.filter(req => req.op === 'savePrompt').length, 0)
  pending[1].resolve(response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: 'B_ONLY' }] }))
  await flush(); tree = h.render()
  assert.equal(button(tree, '保存').props.disabled, false)
  button(tree, '保存').props.onClick(); await flush(); h.render()
  assert.deepEqual(requests.find(req => req.op === 'savePrompt'), { op: 'savePrompt', engagement: 'B', role: 'recon', content: 'B_ONLY' })
  h.unmount()
})


test('Quota display expires without background reads and focus refreshes the actual count', async () => {
  let wall = 100000, mono = 1000, interval, occupied = 0, reads = 0
  const events = {}
  class Clock extends Date { static now() { return wall } }
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body)
    if (req.op === 'agentsStatus') { reads++; return response({ ok: true, engagement: req.engagement, max: 3, used: occupied }) }
    return response({ ok: true, roles: [] })
  }, { Date: Clock, performance: { now: () => mono }, setInterval: callback => { interval = callback; return 1 }, clearInterval: () => {},
    addEventListener: (name, callback) => { events[name] = callback } })
  h.mount('AgentsTab', { engagement: 'A' }); await flush(); let tree = h.render()
  assert.match(text(tree), /上次核对/)
  assert.match(text(tree), /占用 0 \/ 剩余 3/)
  occupied = 3; wall += 61000; mono += 61000
  interval(); tree = h.render()
  assert.match(text(tree), /待核对|已过期/)
  assert.doesNotMatch(text(tree), /占用 0 \/ 剩余 3/)
  assert.equal(reads, 1, 'Aging must not issue background requests')
  events.focus(); await flush(); tree = h.render()
  assert.match(text(tree), /占用 3 \/ 剩余 0/)
  assert.equal(reads, 2)
  events.focus(); await flush(); h.render(); assert.equal(reads, 2, 'Focus refreshes are throttled')
  h.unmount()
})

test('A late prior-project prompt reply cannot replace the loaded current draft', async () => {
  const pending = []
  const h = host((_url, opts) => new Promise(resolve => pending.push({ req: JSON.parse(opts.body), resolve, signal: opts.signal })))
  h.mount('PromptsTab', { engagement: 'A' }); h.render({ engagement: 'B' })
  assert.equal(pending[0].signal.aborted, true)
  pending[1].resolve(response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: 'B_ONLY' }] }))
  await flush(); h.render()
  pending[0].resolve(response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: 'A_ONLY' }] }))
  await flush(); const tree = h.render()
  assert.equal(nodes(tree).find(n => n.type === 'textarea').props.value, 'B_ONLY')
  h.unmount()
})

test('Old prompt writes and resets cannot update the next project after completion', async () => {
  for (const action of ['保存', '恢复默认为当前']) {
    let finish, writes = 0
    const h = host(async (_url, opts) => {
      const req = JSON.parse(opts.body)
      if (req.op === 'prompts') return response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: req.engagement + '_ONLY' }] })
      writes++; return new Promise(resolve => { finish = resolve })
    })
    h.mount('PromptsTab', { engagement: 'A' }); await flush(); let tree = h.render()
    button(tree, action).props.onClick(); tree = h.render(); assert.equal(button(tree, '保存中…').props.disabled, true)
    h.render({ engagement: 'B' }); await flush(); h.render()
    finish(response({ ok: true, reset: ['recon'] })); await flush(); tree = h.render()
    assert.equal(nodes(tree).find(n => n.type === 'textarea').props.value, 'B_ONLY')
    assert.doesNotMatch(text(tree), /已保存|已恢复/)
    assert.equal(writes, 1)
    h.unmount()
  }
})

test('A failed prompt load keeps all writes disabled and never offers the prior draft', async () => {
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body)
    return req.engagement === 'B' ? response({}, 503) : response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: 'A_ONLY' }] })
  })
  h.mount('PromptsTab', { engagement: 'A' }); await flush(); h.render()
  h.render({ engagement: 'B' }); await flush(); const tree = h.render()
  assert.equal(nodes(tree).find(n => n.type === 'textarea').props.value, '')
  for (const name of ['保存', '恢复默认为当前', '全部恢复默认']) assert.equal(button(tree, name).props.disabled, true)
  assert.match(text(tree), /503/)
  h.unmount()
})

test('Quota clock rollback and failed refresh cannot present a current free count', async () => {
  let wall = 100000, mono = 1000, tick, offline = false
  class Clock extends Date { static now() { return wall } }
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body)
    if (offline) return response({}, 503)
    return response({ ok: true, engagement: req.engagement, max: 1, used: 0 })
  }, { Date: Clock, performance: { now: () => mono }, setInterval: callback => { tick = callback; return 1 }, clearInterval: () => {} })
  h.mount('AgentsTab', { engagement: 'A' }); await flush(); h.render()
  wall -= 1000; tick(); let tree = h.render()
  assert.match(text(tree), /待核对/); assert.doesNotMatch(text(tree), /占用 0 \/ 剩余 1/)
  offline = true; button(tree, '刷新').props.onClick(); await flush(); tree = h.render()
  assert.match(text(tree), /503/); assert.match(text(tree), /占用未知/)
  assert.doesNotMatch(text(tree), /并发上限 3/)
  h.unmount()
})


test('Quota never shows a previous project count on the first render before effects', async () => {
  const h = host(async (_url, opts) => response({ ok: true, engagement: JSON.parse(opts.body).engagement, max: 3, used: 0 }))
  h.mount('AgentsTab', { engagement: 'A' }); await flush(); h.render()
  const tree = h.preview({ engagement: 'B' })
  assert.doesNotMatch(text(tree), /占用 0 \/ 剩余 3/)
  h.unmount()
})

test('A callback from before a same-project refresh cannot save or reset an old draft', async () => {
  for (const label of ['保存', '恢复默认为当前']) {
    const pending = [], writes = []
    const h = host((_url, opts) => {
      const req = JSON.parse(opts.body)
      if (req.op !== 'prompts') { writes.push(req); return Promise.resolve(response({ ok: true, reset: ['recon'] })) }
      return new Promise(resolve => pending.push(resolve))
    })
    h.mount('PromptsTab', { engagement: 'A', refreshKey: 0 })
    pending[0](response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: 'OLD' }] }))
    await flush(); const old = button(h.render(), label).props.onClick
    const first = h.preview({ engagement: 'A', refreshKey: 1 })
    assert.equal(button(first, '保存').props.disabled, true)
    old(); await flush(); assert.equal(writes.length, 0)
    h.render(); pending[1](response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: 'NEW' }] }))
    await flush(); h.render(); h.unmount()
  }
})

test('Expired quota remains unverified when a rolled-back wall clock catches up', async () => {
  let wall = 100000, mono = 1000, tick, reads = 0
  class Clock extends Date { static now() { return wall } }
  const h = host(async (_url, opts) => { reads++; return response({ ok: true, engagement: JSON.parse(opts.body).engagement, max: 3, used: 0 }) },
    { Date: Clock, performance: { now: () => mono }, setInterval: fn => { tick = fn; return 1 }, clearInterval: () => {} })
  h.mount('AgentsTab', { engagement: 'A' }); await flush(); h.render()
  wall = 90000; tick(); assert.match(text(h.render()), /待核对/)
  wall = 100001; mono = 1001; tick(); const tree = h.render()
  assert.doesNotMatch(text(tree), /占用 0 \/ 剩余 3/); assert.equal(reads, 1)
  h.unmount()
})

test('A committed reset followed by a failed read locks the old draft until explicit reload', async () => {
  let reads = 0, saved = 0, restored = false, offline = true
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body)
    if (req.op === 'prompts') {
      if (++reads > 1 && offline) return response({}, 503)
      return response({ ok: true, roles: [{ role: 'recon', title: 'Recon', content: restored ? 'RESTORED' : 'OLD' }] })
    }
    if (req.op === 'resetPrompts') { restored = true; return response({ ok: true, reset: ['recon'] }) }
    if (req.op === 'savePrompt') { saved++; return response({ ok: true }) }
  })
  h.mount('PromptsTab', { engagement: 'A' }); await flush(); let tree = h.render()
  const oldSave = button(tree, '保存').props.onClick, oldReset = button(tree, '恢复默认为当前').props.onClick
  oldReset(); await flush(); await flush(); tree = h.render()
  assert.equal(restored, true)
  assert.equal(button(tree, '保存').props.disabled, true)
  assert.match(text(tree), /已提交|已恢复/)
  assert.notEqual(nodes(tree).find(n => n.type === 'textarea').props.value, 'OLD')
  button(tree, '保存').props.onClick(); oldSave(); oldReset(); await flush(); assert.equal(saved, 0)
  offline = false; button(tree, '重新核对角色稿').props.onClick(); h.render(); await flush(); tree = h.render()
  assert.equal(nodes(tree).find(n => n.type === 'textarea').props.value, 'RESTORED')
  assert.equal(button(tree, '保存').props.disabled, false)
  h.unmount()
})


test('Binding history opens on demand and archive is explicitly reversible', async () => {
  let archived = false, reads = 0; const writes = []
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body)
    if (req.op === 'bindingHistory') { reads++; return response({ ok: true, engagement: req.engagement, observedAt: '2026-10-28T02:00:00Z', items: [{ rootSession: 'A-root', bindingCount: 2, archived }], next: null }) }
    writes.push(req); archived = req.archived
    return response({ ok: true, engagement: req.engagement, rootSession: req.rootSession, archived })
  })
  let tree = h.mount('BindingHistoryCard', { engagement: 'A' }); assert.equal(reads, 0)
  button(tree, '查看会话绑定').props.onClick(); h.render(); await flush(); tree = h.render()
  assert.match(text(tree), /A-root/); assert.match(text(tree), /完整核查/)
  button(tree, '归档记录').props.onClick(); await flush(); h.render(); await flush(); tree = h.render()
  assert.equal(archived, true); assert.equal(writes.length, 1)
  button(tree, '恢复记录').props.onClick(); await flush(); h.render(); await flush(); tree = h.render()
  assert.equal(archived, false); assert.equal(writes.length, 2)
  assert.deepEqual(writes.map(req => req.op), ['setBindingArchived', 'setBindingArchived'])
  h.unmount()
})


test('A delayed global quota save rechecks the current project rather than the old one', async () => {
  const reads = []; let max = 3, finish, writes = 0;
  const parent = host(async (_url, opts) => {
    const req = JSON.parse(opts.body); reads.push(req.engagement);
    return response({ ok: true, engagement: req.engagement, max, used: req.engagement === 'A' ? 0 : 2 });
  });
  const child = host((_url, opts) => { assert.equal(JSON.parse(opts.body).op, 'setAgentsMax'); writes++; return new Promise(resolve => { finish = resolve; }); });
  const card = tree => nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'ConcurrencyCard');
  try {
    parent.mount('AgentsTab', { engagement: 'A' }); await flush(); let tree = parent.render();
    let editor = child.mount('ConcurrencyCard', card(tree).props);
    nodes(editor).find(node => node.type === 'input').props.onChange({ target: { value: '2' } }); editor = child.render();
    button(editor, '保存').props.onClick(); child.render();
    parent.render({ engagement: 'B' }); await flush(); tree = parent.render(); editor = child.render(card(tree).props);
    assert.match(text(tree), /占用 2 \/ 剩余 1/);
    max = 2; finish(response({ ok: true, max })); await flush(); child.render(); await flush(); tree = parent.render();
    assert.deepEqual(reads, ['A', 'B', 'B']); assert.equal(writes, 1);
    assert.match(text(tree), /占用 2 \/ 剩余 0/);
    assert.doesNotMatch(text(tree), /占用未知|名额待核对/);
  } finally { parent.unmount(); child.unmount(); }
});

test('An old quota refresh callback cannot clear the next project before effects run', async () => {
  const reads = [];
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body); reads.push(req.engagement);
    return response({ ok: true, engagement: req.engagement, max: 3, used: 0 });
  });
  try {
    h.mount('AgentsTab', { engagement: 'A' }); await flush(); const old = button(h.render(), '刷新').props.onClick;
    h.preview({ engagement: 'B' }); old(); await flush();
    assert.deepEqual(reads, ['A']);
    h.render(); await flush(); assert.match(text(h.render()), /占用 0 \/ 剩余 3/);
  } finally { h.unmount(); }
});

test('Page refresh rereads expanded binding history while retaining its cursor and filter', async () => {
  let count = 1; const reads = [];
  const parent = host(async (_url, opts) => response({ ok: true, engagement: JSON.parse(opts.body).engagement, max: 3, used: 0 }));
  const child = host(async (_url, opts) => {
    const req = JSON.parse(opts.body); assert.equal(req.op, 'bindingHistory'); reads.push(req);
    return response({ ok: true, engagement: req.engagement, observedAt: '2026-10-28T04:00:00Z',
      items: [{ rootSession: req.after ? 'root32' : 'root0', bindingCount: count, archived: false }], next: req.after ? null : 'root0' });
  });
  const card = tree => nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'BindingHistoryCard');
  try {
    parent.mount('AgentsTab', { engagement: 'A', refreshKey: 0 }); await flush(); let tree = parent.render();
    let history = child.mount('BindingHistoryCard', card(tree).props);
    button(history, '查看会话绑定').props.onClick(); child.render(); await flush(); history = child.render();
    button(history, '只看未归档').props.onClick(); child.render(); await flush(); history = child.render();
    button(history, '下一页').props.onClick(); child.render(); await flush(); history = child.render(); assert.equal(reads.length, 3);
    count = 2;
    parent.render({ engagement: 'A', refreshKey: 1 }); await flush(); tree = parent.render();
    child.render(card(tree).props); await flush(); history = child.render();
    assert.equal(reads.length, 4); assert.equal(reads[3].after, 'root0'); assert.equal(reads[3].onlyUnarchived, true);
    assert.match(text(history), /root32/); assert.match(text(history), /2 条绑定/);
    button(history, '收起会话绑定').props.onClick(); child.render();
    parent.render({ engagement: 'A', refreshKey: 2 }); await flush(); tree = parent.render(); child.render(card(tree).props); await flush(); child.render();
    assert.equal(reads.length, 4, 'Collapsed records must not issue background reads');
  } finally { parent.unmount(); child.unmount(); }
});

test('A global save finishing after tab remount notifies the currently mounted project', async () => {
  const windowEvents = new Map(), reads = []; let max = 3, finish, writes = 0;
  const fetchQuota = async (_url, opts) => {
    const req = JSON.parse(opts.body); reads.push(req.engagement);
    return response({ ok: true, engagement: req.engagement, max, used: req.engagement === 'A' ? 0 : 2 });
  };
  const oldParent = host(fetchQuota, { windowEvents }), currentParent = host(fetchQuota, { windowEvents });
  const child = host(() => { writes++; return new Promise(resolve => { finish = resolve; }); }, { windowEvents });
  const card = tree => nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'ConcurrencyCard');
  let oldClosed = false;
  try {
    oldParent.mount('AgentsTab', { engagement: 'A' }); await flush(); let tree = oldParent.render();
    const editor = child.mount('ConcurrencyCard', card(tree).props);
    button(editor, '保存').props.onClick(); child.render();
    child.unmount(); oldParent.unmount(); oldClosed = true;
    currentParent.mount('AgentsTab', { engagement: 'B' }); await flush(); tree = currentParent.render();
    assert.match(text(tree), /占用 2 \/ 剩余 1/);
    max = 2; finish(response({ ok: true, max })); await flush(); currentParent.render(); await flush(); tree = currentParent.render();
    assert.deepEqual(reads, ['A', 'B', 'B']); assert.equal(writes, 1);
    assert.match(text(tree), /占用 2 \/ 剩余 0/);
  } finally { if (!oldClosed) { child.unmount(); oldParent.unmount(); } currentParent.unmount(); }
});

test('An ambiguous global save invalidates old quota and reads current value without replay', async () => {
  let max = 3, reads = 0, writes = 0, finishRead;
  const parent = host((_url, opts) => {
    const req = JSON.parse(opts.body); reads++;
    const value = { ok: true, engagement: req.engagement, max, used: 0 };
    return reads === 1 ? Promise.resolve(response(value)) : new Promise(resolve => { finishRead = () => resolve(response(value)); });
  });
  const child = host(async (_url, opts) => { writes++; max = JSON.parse(opts.body).max; throw new TypeError('Response lost after commit'); });
  const card = tree => nodes(tree).find(node => typeof node.type === 'function' && node.type.name === 'ConcurrencyCard');
  try {
    parent.mount('AgentsTab', { engagement: 'A' }); await flush(); let tree = parent.render();
    let editor = child.mount('ConcurrencyCard', card(tree).props);
    nodes(editor).find(node => node.type === 'input').props.onChange({ target: { value: '2' } }); editor = child.render();
    button(editor, '保存').props.onClick(); await flush(); tree = parent.render(); editor = child.render(card(tree).props);
    assert.equal(writes, 1); assert.equal(reads, 2); assert.doesNotMatch(text(tree), /占用 0 \/ 剩余 3/);
    assert.match(text(editor), /结果.*未确认|结果.*未知/); assert.doesNotMatch(text(editor), /已保存/);
    finishRead(); await flush(); tree = parent.render(); editor = child.render(card(tree).props);
    assert.match(text(tree), /占用 0 \/ 剩余 2/); assert.match(text(editor), /结果.*未确认|结果.*未知/); assert.equal(writes, 1);
  } finally { parent.unmount(); child.unmount(); }
});

test('Quota rereads preserve a dirty draft, including same-project page refresh', async () => {
  let info = { ok: true, engagement: 'A', max: 3, used: 0 };
  const h = host(async () => { throw new Error('No write expected'); });
  try {
    let tree = h.mount('ConcurrencyCard', { engagement: 'A', refreshKey: 0, concurrency: info });
    nodes(tree).find(node => node.type === 'input').props.onChange({ target: { value: '2' } }); h.render();
    h.render({ engagement: 'A', refreshKey: 0, concurrency: null });
    tree = h.render({ engagement: 'A', refreshKey: 0, concurrency: info });
    assert.equal(nodes(tree).find(node => node.type === 'input').props.value, '2');
    info = { ...info, max: 4 }; tree = h.render({ engagement: 'A', refreshKey: 1, concurrency: info });
    assert.equal(nodes(tree).find(node => node.type === 'input').props.value, '2'); assert.match(text(tree), /保留.*输入|已修改/);
  } finally { h.unmount(); }
});

test('A confirmed save acknowledgement survives quota readback until explicitly dismissed', async () => {
  let notifications = 0;
  const h = host(async () => response({ ok: true, max: 3 }));
  try {
    let tree = h.mount('ConcurrencyCard', { engagement: 'A', concurrency: { max: 3 }, onSaved: () => notifications++ });
    button(tree, '保存').props.onClick(); await flush(); h.render();
    h.render({ engagement: 'A', concurrency: null });
    tree = h.render({ engagement: 'A', concurrency: { max: 3 } });
    assert.equal(notifications, 1); assert.match(text(tree), /已保存/);
    button(tree, '关闭保存提示').props.onClick(); tree = h.render(); assert.doesNotMatch(text(tree), /已保存/);
  } finally { h.unmount(); }
});

test('Quota failure diagnostics name the root and a recheck only reads status', async () => {
  const requests = []; let failed = true
  const h = host(async (_url, opts) => {
    const req = JSON.parse(opts.body); requests.push(req.op)
    return response({ ok: !failed, engagement: req.engagement, max: 3, used: failed ? null : 0,
      error: failed ? '子代理状态不完整' : undefined, quota_check: { observedAt: '2026-10-28T04:00:00Z',
        kind: failed ? 'incomplete-branch' : 'complete', completed: failed ? 2 : 3, total: 3,
        unconfirmed: failed ? 1 : 0, failed: failed ? [{ rootSession: 'root-b', kind: 'incomplete-branch' }] : [], pendingRoots: [] } })
  })
  try {
    h.mount('AgentsTab', { engagement: 'A' }); await flush(); let tree = h.render()
    assert.match(text(tree), /2 \/ 3/); assert.match(text(tree), /root-b/)
    failed = false; button(tree, '重新核查名额').props.onClick(); await flush(); tree = h.render()
    assert.match(text(tree), /3 \/ 3/); assert.doesNotMatch(text(tree), /root-b/)
    assert.deepEqual(requests, ['agentsStatus','agentsStatus'])
  } finally { h.unmount() }
})

test('An explicit pre-write rejection preserves its feedback without claiming an unknown save', async () => {
  let writes = 0, notifications = 0
  const h = host(async () => { writes++; return response({ ok: false, outcome: 'rejected', error: 'Rejected before write' }) })
  try {
    let tree = h.mount('ConcurrencyCard', { engagement: 'A', concurrency: { max: 3 }, onSaved: () => notifications++ })
    button(tree, '保存').props.onClick(); await flush(); tree = h.render()
    assert.equal(writes, 1); assert.equal(notifications, 0); assert.match(text(tree), /保存被拒绝/)
    h.render({ engagement: 'A', concurrency: null }); tree = h.render({ engagement: 'A', concurrency: { max: 3 } })
    assert.match(text(tree), /保存被拒绝/); assert.doesNotMatch(text(tree), /已保存|结果未确认/)
  } finally { h.unmount() }
})

test('A mismatched success payload is treated as unknown and never acknowledged as saved', async () => {
  let notifications = 0, writes = 0
  const h = host(async () => { writes++; return response({ ok: true, max: 9 }) })
  try {
    let tree = h.mount('ConcurrencyCard', { engagement: 'A', concurrency: { max: 3 }, onSaved: () => notifications++ })
    button(tree, '保存').props.onClick(); await flush(); tree = h.render()
    assert.equal(writes, 1); assert.equal(notifications, 1); assert.match(text(tree), /结果未确认/); assert.doesNotMatch(text(tree), /已保存/)
  } finally { h.unmount() }
})

test('Adopting the current readback value is an explicit local action without a write', () => {
  const h = host(() => { throw new Error('Adoption must not write') })
  try {
    let tree = h.mount('ConcurrencyCard', { engagement: 'A', concurrency: { max: 3 } })
    nodes(tree).find(n => n.type === 'input').props.onChange({ target: { value: '2' } }); h.render()
    tree = h.render({ engagement: 'A', concurrency: { max: 4 } })
    assert.equal(nodes(tree).find(n => n.type === 'input').props.value, '2')
    button(tree, '使用当前核对值').props.onClick(); tree = h.render()
    assert.equal(nodes(tree).find(n => n.type === 'input').props.value, '4'); assert.doesNotMatch(text(tree), /已修改/)
  } finally { h.unmount() }
})

test('Explicitly contradictory outcome receipts stay unknown despite matching max', async () => {
  for (const outcome of ['unknown','rejected']) {
    let notifications = 0
    const h = host(async () => response({ ok: true, max: 3, outcome }))
    try {
      let tree = h.mount('ConcurrencyCard', { engagement: 'A', concurrency: { max: 3 }, onSaved: () => notifications++ })
      button(tree, '保存').props.onClick(); await flush(); tree = h.render()
      assert.match(text(tree), /结果.*未确认/); assert.doesNotMatch(text(tree), /已保存/); assert.equal(notifications, 1)
    } finally { h.unmount() }
  }
})

test('An ambiguous old save informs a remounted editor without replay or a false acknowledgement', async () => {
  const windowEvents = new Map(), reads = []; let max = 3, rejectWrite, writes = 0
  const fetchQuota = async (_url, opts) => { const req = JSON.parse(opts.body); reads.push(req.engagement); return response({ ok: true, engagement: req.engagement, max, used: 0 }) }
  const oldParent = host(fetchQuota, { windowEvents }), currentParent = host(fetchQuota, { windowEvents })
  const oldChild = host(() => { writes++; return new Promise((_resolve, reject) => { rejectWrite = reject }) }, { windowEvents })
  const currentChild = host(() => { throw new Error('No second write expected') }, { windowEvents })
  const card = tree => nodes(tree).find(n => typeof n.type === 'function' && n.type.name === 'ConcurrencyCard')
  let oldClosed = false
  try {
    oldParent.mount('AgentsTab', { engagement: 'A' }); await flush(); let tree = oldParent.render()
    let editor = oldChild.mount('ConcurrencyCard', card(tree).props)
    nodes(editor).find(n => n.type === 'input').props.onChange({ target: { value: '2' } }); editor = oldChild.render()
    button(editor, '保存').props.onClick(); oldChild.render(); oldChild.unmount(); oldParent.unmount(); oldClosed = true
    currentParent.mount('AgentsTab', { engagement: 'A' }); await flush(); tree = currentParent.render(); currentChild.mount('ConcurrencyCard', card(tree).props)
    max = 2; rejectWrite(new TypeError('Response lost after commit')); await flush(); currentParent.render(); await flush(); tree = currentParent.render()
    currentChild.render(card(tree).props); await flush(); editor = currentChild.render()
    assert.deepEqual(reads, ['A','A','A']); assert.equal(writes, 1); assert.match(text(tree), /占用 0 \/ 剩余 2/)
    assert.match(text(editor), /结果.*未确认/); assert.doesNotMatch(text(editor), /已保存/)
  } finally { if (!oldClosed) { oldChild.unmount(); oldParent.unmount() } currentChild.unmount(); currentParent.unmount() }
})
