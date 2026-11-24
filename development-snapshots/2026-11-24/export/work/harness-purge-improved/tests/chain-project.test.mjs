import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
const source=fs.readFileSync(new URL('../package/lib/redteam/client.js',import.meta.url),'utf8'),fixture=fs.readFileSync(new URL('./ui-regression.test.mjs',import.meta.url),'utf8'),scope={source,vm,assert,console,AbortController,Event,setTimeout,clearTimeout,setInterval,clearInterval,Date,performance};vm.runInNewContext(fixture.slice(fixture.indexOf('function host('),fixture.indexOf("test('API rejects")).replace('api, FindingsTab','api, ChainTab, FindingsTab'),scope);
const {host,text,button}=scope,flush=async()=>{for(let i=0;i<32;i++)await Promise.resolve()},response=points=>({ok:true,status:200,json:async()=>({ok:true,stages:[],summary:{points}})});
test('Chain project B ignores a late A response',async()=>{const pending=[],h=host((_u,o)=>new Promise(resolve=>pending.push({q:JSON.parse(o.body),resolve})));try{h.mount('ChainTab',{engagement:'A'});h.render({engagement:'B'});await flush();pending[1].resolve(response(222));await flush();assert.match(text(h.render()),/总分 222 分/);pending[0].resolve(response(111));await flush();assert.match(text(h.render()),/总分 222 分/);assert.doesNotMatch(text(h.render()),/总分 111 分/)}finally{pending.forEach(p=>p.resolve(response(0)));await flush();h.unmount()}});
test('Chain hides A immediately, rejects an old refresh callback and keeps newest A after A-B-A',async()=>{const pending=[],h=host((_u,o)=>new Promise(resolve=>pending.push({q:JSON.parse(o.body),resolve})));try{h.mount('ChainTab',{engagement:'A'});await flush();pending[0].resolve(response(111));await flush();const old=button(h.render(),'刷新');assert.doesNotMatch(text(h.preview({engagement:'B'})),/111/);h.render({engagement:'B'});old.props.onClick();h.render({engagement:'A'});await flush();assert.equal(pending.length,3);pending[2].resolve(response(333));await flush();pending[1].resolve(response(222));await flush();assert.match(text(h.render()),/总分 333 分/);assert.doesNotMatch(text(h.render()),/总分 222 分/)}finally{pending.forEach(p=>p.resolve(response(0)));await flush();h.unmount()}});
test('Chain failed current read stays unknown instead of retaining the previous score',async()=>{let reads=0;const h=host(async()=>++reads===1?response(111):({ok:true,status:200,json:async()=>({ok:false})}));try{h.mount('ChainTab',{engagement:'A'});await flush();button(h.render(),'刷新').props.onClick();await flush();const tree=h.render();assert.match(text(tree),/未确认/);assert.doesNotMatch(text(tree),/总分 111|还没有得分记录/)}finally{h.unmount()}});

const paged = (offset, total = 501) => {
  const returnedHits = Math.min(500, Math.max(0, total - offset))
  return {
    ok: true,
    status: 200,
    json: async () => ({
      ok: true, stages: [], summary: { points: total, hits: total },
      coverage: {
        totalHits: total, returnedHits, offset, limit: 500,
        nextOffset: offset + returnedHits < total ? offset + returnedHits : null,
        complete: offset === 0 && returnedHits === total,
        returnedPoints: returnedHits, returnedCountedHits: returnedHits,
        totalsScope: 'project', stagesScope: 'window',
      },
    }),
  }
}

test('Chain shows the project total and current detail window, then resets the window for another project', async () => {
  const requests = []
  const ui = host(async (_url, opts) => {
    const request = JSON.parse(opts.body)
    requests.push(request)
    return paged(request.offset)
  })
  try {
    ui.mount('ChainTab', { engagement: 'A' })
    await flush()
    const first = ui.render()
    assert.match(text(first), /项目总分 501 分/)
    assert.match(text(first), /第 1–500 条.*共 501 条/)
    assert.match(text(first), /当前页.*500 分/)
    const staleNext = button(first, '下一页')
    assert.equal(staleNext.props.disabled, false)
    staleNext.props.onClick()
    ui.render()
    await flush()
    const last = ui.render()
    assert.match(text(last), /第 501–501 条/)
    assert.match(text(last), /项目总分 501 分/)
    assert.equal(button(last, '下一页').props.disabled, true)
    ui.render({ engagement: 'B' })
    staleNext.props.onClick()
    await flush()
    assert.deepEqual(requests.map(r => [r.engagement, r.offset]), [['A', 0], ['A', 500], ['B', 0]])
  } finally {
    ui.unmount()
  }
})

test('Chain preserves a usable previous-page control when loading the next window fails', async () => {
  const ui = host(async (_url, opts) => JSON.parse(opts.body).offset === 0
    ? paged(0)
    : { ok: true, status: 200, json: async () => ({ ok: false }) })
  try {
    ui.mount('ChainTab', { engagement: 'A' })
    await flush()
    button(ui.render(), '下一页').props.onClick()
    ui.render()
    await flush()
    const failed = ui.render()
    assert.match(text(failed), /未确认/)
    assert.equal(button(failed, '上一页').props.disabled, false)
    button(failed, '上一页').props.onClick()
    ui.render()
    await flush()
    assert.match(text(ui.render()), /第 1–500 条/)
  } finally {
    ui.unmount()
  }
})

test('Chain labels self-created and disabled hits, including legacy item fields', async () => {
  const items = [
    { id: 1, point_name: 'inert own', counted: false, exclusion_reason: 'self_created' },
    { id: 2, point_name: 'inert disabled', counted: false, enabled: 0 },
    { id: 3, point_name: 'inert zero', counted: true, points: 0 },
  ]
  const stages = [
    { code: 'recon', name: 'recon', hits: 1, points: 0, cumulative: 0, assets: [],
      items: [{ id: 4, point_name: 'inert missing point', counted: false, exclusion_reason: 'missing_point' }] },
    { code: 'internet', name: 'internet', hits: 3, points: 0, cumulative: 0, items, assets: [] },
  ]
  const ui = host(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, stages, summary: { points: 0 } }) }))
  try {
    ui.mount('ChainTab', { engagement: 'A' })
    await flush()
    const tree = ui.render()
    assert.match(text(tree), /自建 · 不计分/)
    assert.match(text(tree), /得分点已停用 · 不计分/)
    assert.match(text(tree), /得分点缺失 · 不计分/)
    assert.equal((text(tree).match(/不计分/g) || []).length, 3)
    button(tree, '链路 B').props.onClick()
    assert.match(text(ui.render()), /自建 · 不计分/)
    assert.match(text(ui.render()), /得分点已停用 · 不计分/)
  } finally {
    ui.unmount()
  }
})
