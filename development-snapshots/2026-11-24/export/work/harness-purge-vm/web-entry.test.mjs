import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import vm from 'node:vm'
const file = new URL('./web-entry.mjs', import.meta.url)
const module = fs.existsSync(file) ? await import(file) : {}
async function fixture(handler, options = {}) {
  assert.equal(typeof module.createWebEntry, 'function', 'A stable local web entry must exist')
  const upstream = http.createServer(handler)
  const peers = new Set()
  upstream.on('connection', socket => { peers.add(socket); socket.on('close', () => peers.delete(socket)) })
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve))
  const entry = module.createWebEntry({ upstreamPort: upstream.address().port, ...options })
  await new Promise(resolve => entry.listen(0, '127.0.0.1', resolve))
  return { upstream, entry, port: entry.address().port, async close() { entry.shutdown(); for (const socket of peers) socket.destroy(); await new Promise(resolve => upstream.close(resolve)) } }
}
function request(port, method = 'GET', headers = {}, path = '/') {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path, method, headers: { host: '127.0.0.1:' + port, ...headers } }, res => {
      const body = []
      res.on('data', item => body.push(item)); res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(body).toString(), headers: res.headers }))
    })
    req.on('error', reject); req.end()
  })
}
test('Both VM versions receive a runtime banner without changing JSON or static responses',async()=>{
 const f=await fixture((req,res)=>{res.setHeader('content-type',req.url==='/'?'text/html':'application/json');res.end(req.url==='/'?'<html><head></head><body>original VM</body></html>':'{"ok":true}')})
 try{
  const page=await request(f.port);assert.match(page.body,/__harness\/banner.js/);assert.match(page.body,/original VM/)
  const api=await request(f.port,'GET',{},'/data');assert.equal(api.body,'{"ok":true}')
  const js=await request(f.port,'GET',{},'/__harness/banner.js');assert.equal(js.status,200);assert.match(js.body,/VM/)
 }finally{await f.close()}
})
test('Environment metadata is read-only, same-origin guarded and never proxies a user command',async()=>{
 let calls=0
 const f=await fixture((_req,res)=>res.end('upstream'),{environmentReader:async()=>{calls++;return{mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'older'}}}})
 try{
  assert.equal((await request(f.port,'POST',{'x-harness-local':'1'},'/__harness/environment')).status,405)
  assert.equal((await request(f.port,'GET',{},'/__harness/environment')).status,403)
  assert.equal((await request(f.port,'GET',{'x-harness-local':'1',origin:'https://outside.invalid'},'/__harness/environment')).status,403)
  assert.equal((await request(f.port,'GET',{'x-harness-local':'1','sec-fetch-site':'cross-site'},'/__harness/environment')).status,403)
  const result=await request(f.port,'GET',{'x-harness-local':'1'},'/__harness/environment');assert.equal(result.status,200);assert.equal(JSON.parse(result.body).mode,'improved');assert.equal(calls,1)
 }finally{await f.close()}
})
test('Runtime reader coalesces requests, expires metadata, and excludes arbitrary private fields',async()=>{
 let calls=0,time=0,complete
 const reader=module.createEnvironmentReader({now:()=>time,run:()=>{calls++;return new Promise(resolve=>{complete=resolve})}})
 const first=reader(),second=reader();await Promise.resolve();assert.equal(calls,1)
 complete({stdout:JSON.stringify({mode:'original',configDir:'/home/purge/.dsh',observedAt:'2026-10-26T00:00:00Z',secret:'PRIVATE_CANARY',recovery:{state:'older',name:'ready-improved-20261026',secret:'PRIVATE_CANARY'}})})
 assert.deepEqual(await first,await second);assert.ok(!JSON.stringify(await reader()).includes('PRIVATE_CANARY'));assert.equal(calls,1)
 time=5001;const renewed=reader();await Promise.resolve();assert.equal(calls,2);complete({stdout:'invalid json'});await assert.rejects(renewed)
})
test('The default environment cache expires by elapsed time even after the host clock moves backwards',async()=>{
 let wall=10000000,mono=1000,calls=0;
 const create=vm.runInNewContext('('+module.createEnvironmentReader.toString().replaceAll('import.meta.url','"file:///synthetic/web-entry.mjs"')+')',{Date:{now:()=>wall},performance:{now:()=>mono}});
 const reader=create({run:async()=>{calls++;return{stdout:JSON.stringify({mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'matches'},observedAt:'synthetic-observation-'+calls})}}});
 await reader();wall-=3600000;mono+=6000;await reader();assert.equal(calls,2,'Wall-clock rollback must not extend the five-second cache');
})
test('The environment cache expires after sleep even when the monotonic clock pauses or wall time moves backwards',async()=>{
 for(const wallChange of [121000,-3600000]){
  let wall=10000000,mono=1000,calls=0;
  const create=vm.runInNewContext('('+module.createEnvironmentReader.toString().replaceAll('import.meta.url','"file:///synthetic/web-entry.mjs"')+')',{Date:{now:()=>wall},performance:{now:()=>mono}});
  const reader=create({run:async()=>{calls++;return{stdout:JSON.stringify({mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'matches'}})}}});
  await reader();mono+=1000;wall+=wallChange;await reader();assert.equal(calls,2,'A paused monotonic clock must not preserve a pre-sleep observation');
 }
})
test('Runtime metadata preserves scoped recovery groups and only approved uncovered paths',async()=>{
 const reader=module.createEnvironmentReader({run:async()=>({stdout:JSON.stringify({mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'older',name:'ready-workbench-v3-20261026',groups:{program:{state:'matches',filesChecked:108},tools:{state:'older',filesChecked:0,secret:'PRIVATE_CANARY'},config:{state:'older',filesChecked:5}},uncoveredFiles:['.local/bin/toolchain-versions','/private/PRIVATE_CANARY'],secret:'PRIVATE_CANARY'}})})});
 const data=await reader();assert.equal(data.recovery.scope,'improved-program-tools-config');assert.equal(data.recovery.groups.tools.state,'older');assert.deepEqual(data.recovery.uncoveredFiles,['.local/bin/toolchain-versions']);assert.ok(!JSON.stringify(data).includes('PRIVATE_CANARY'));
})
test('A failed runtime probe never exposes its internal error or claims an available status',async()=>{
 const f=await fixture((_req,res)=>res.end('upstream'),{environmentReader:async()=>{throw Error('PRIVATE_CANARY')}})
 try{const result=await request(f.port,'GET',{'x-harness-local':'1'},'/__harness/environment');assert.equal(result.status,503);assert.ok(!result.body.includes('PRIVATE_CANARY'))}finally{await f.close()}
})
test('Recovery differences include approved program, tool, config and launch paths without arbitrary input',async()=>{
 const changed=['tools/dsh-purge-personal-1.1.77-personal.1/client.js','.dsh-improved/cordis.patch.yml','host-launch-agents/com.personal.harness-purge-original-web-entry.plist'];
 const privatePaths=['/private/SECRET_CANARY','tools/dsh-purge-personal-1.1.77-personal.1/../private','tools/dsh-purge-personal-1.1.77-personal.1/.credentials.yaml','host-launch-agents/other.plist'];
 const reader=module.createEnvironmentReader({run:async()=>({stdout:JSON.stringify({mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'older',name:'ready-workbench-v4-20261026',launchAgentsMatch:false,groups:{program:{state:'older',filesChecked:108,differentFiles:[changed[0],...privatePaths]},config:{state:'older',filesChecked:7,differentFiles:changed.slice(1)}},uncoveredFiles:[]}})})});
 const recovery=(await reader()).recovery;assert.deepEqual(recovery.differentFiles,changed);assert.equal(recovery.launchAgentsMatch,false);assert.equal(recovery.differentFileCount,3);assert.ok(!JSON.stringify(recovery).includes('SECRET_CANARY'));assert.ok(!JSON.stringify(recovery).includes('.credentials'));
})
test('Host helper differences expose only the five fixed public names',async()=>{
 const changed=['manage.py','egress_proxy.py','qemu-image.py','web-entry.mjs','web-health.mjs'].map(name=>'host-tools/'+name);
 const privatePaths=['host-tools/secret.txt','host-tools/../providers.yml','/Users/PRIVATE_CANARY/config'];
 const value={mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'older',helpersMatch:false,groups:{tools:{state:'older',filesChecked:10,differentFiles:[...changed,...privatePaths]}}}};
 const data=await module.createEnvironmentReader({run:async()=>({stdout:JSON.stringify(value)})})();
 assert.deepEqual(data.recovery.differentFiles,changed);assert.equal(data.recovery.helpersMatch,false);assert.equal(data.recovery.groups.tools.filesChecked,10);assert.ok(!JSON.stringify(data).includes('PRIVATE_CANARY'));assert.ok(!JSON.stringify(data).includes('secret.txt'));
})
test('Truncated recovery difference lists retain their full approved count',async()=>{
 const changed=Array.from({length:100},(_,i)=>'tools/dsh-purge-personal-1.1.77-personal.1/lib/module-'+i+'.js');
 const reader=module.createEnvironmentReader({run:async()=>({stdout:JSON.stringify({mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'older',groups:{program:{state:'older',filesChecked:100,differentFiles:changed}}}})})});
 const data=(await reader()).recovery;assert.equal(data.differentFiles.length,80);assert.equal(data.differentFileCount,100);assert.equal(data.differenceDetailsTruncated,true);assert.equal(data.groups.program.differentFiles.length,80);
})
test('Runtime coverage preserves only fixed core paths and a bounded package-version label',async()=>{
 const core='tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh-tools/lib/index.js';
 const value={mode:'improved',configDir:'/home/purge/.dsh-improved',runtimePackageVersion:'0.2.1-rc.3',recovery:{state:'older',groups:{runtime:{state:'uncovered',filesChecked:0,differentFiles:[core,'tools/harness-improved-runtime/node_modules/private-token.yml']}},uncoveredFiles:[core,'tools/harness-improved-runtime/node_modules/private-token.yml']}};
 const data=await module.createEnvironmentReader({run:async()=>({stdout:JSON.stringify(value)})})();
 assert.equal(data.runtimePackageVersion,'0.2.1-rc.3');assert.equal(data.recovery.groups.runtime.state,'uncovered');assert.deepEqual(data.recovery.uncoveredFiles,[core]);assert.deepEqual(data.recovery.differentFiles,[core]);assert.ok(!JSON.stringify(data).includes('private-token'));
 value.runtimePackageVersion='PRIVATE_CANARY '+ 'a'.repeat(100);
 const invalid=await module.createEnvironmentReader({run:async()=>({stdout:JSON.stringify(value)})})();assert.equal(invalid.runtimePackageVersion,null);assert.ok(!JSON.stringify(invalid).includes('PRIVATE_CANARY'));
})
test('Concurrent browser requests reuse one upstream connection without losing responses', async () => {
  let connections = 0
  const f = await fixture((_req, res) => res.end('asset-ready'))
  f.upstream.on('connection', () => connections++)
  try {
    const results = await Promise.all(Array.from({ length: 32 }, () => request(f.port)))
    assert.ok(results.every(item => item.status === 200 && item.body === 'asset-ready'))
    assert.equal(connections, 1)
  } finally { await f.close() }
})
test('Only failed static reads retry; POST and unknown GET routes are never replayed', async () => {
  let gets = 0, posts = 0
  const f = await fixture((req, res) => {
    if (req.method === 'POST') { posts++; req.socket.destroy(); return }
    if (++gets === 1) { req.socket.destroy(); return }
    res.end('read-recovered')
  })
  try {
    assert.equal((await request(f.port, 'GET', {}, '/assets/main.js')).body, 'read-recovered'); assert.equal(gets, 2)
    assert.equal((await request(f.port, 'POST')).status, 502); assert.equal(posts, 1)
  } finally { await f.close() }
})
test('An unavailable upstream has a bounded retry and a visible HTTP failure', async () => {
  let calls = 0
  const f = await fixture(req => { calls++; req.socket.destroy() })
  try {
    assert.equal((await request(f.port, 'GET', {}, '/assets/main.js')).status, 502); assert.equal(calls, 2)
    calls = 0
    assert.equal((await request(f.port, 'GET', {}, '/unknown-action')).status, 502); assert.equal(calls, 1)
  }
  finally { await f.close() }
})
test('A nonresponding POST expires without replay and releases the next request', async () => {
  let calls = 0
  const f = await fixture((req, res) => { if (req.url === '/stall') calls++; else res.end('queue-recovered') }, { responseTimeoutMs: 40 })
  let watchdog
  try {
    const result = await Promise.race([request(f.port, 'POST', {}, '/stall'), new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error('Stalled request did not expire')), 500) })])
    assert.equal(result.status, 502); assert.equal(calls, 1)
    assert.equal((await request(f.port)).body, 'queue-recovered')
  } finally { clearTimeout(watchdog); await f.close() }
})
test('The plugin SSE subscription stays open without blocking subsequent data loads', async () => {
  const f = await fixture((req, res) => {
    if (req.url === '/plugins/events') {
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      res.write(': stream-ready\n\n')
    } else res.end('data-while-streaming')
  })
  let stream, watchdog
  try {
    await new Promise((resolve, reject) => {
      const req = http.get({ host: '127.0.0.1', port: f.port, path: '/plugins/events' }, response => {
        stream = response; response.on('error', () => {}); response.once('data', resolve)
      })
      req.on('error', reject)
    })
    const result = await Promise.race([request(f.port), new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error('SSE blocked normal HTTP requests')), 500) })])
    assert.equal(result.body, 'data-while-streaming')
    assert.equal(stream.destroyed, false, 'Do not truncate the subscription to free the queue')
    let data = JSON.parse((await request(f.port, 'GET', {}, '/__harness/diagnostics')).body)
    assert.equal(data.layers.sse.state, 'connected')
    stream.destroy()
    for (let attempt = 0; attempt < 20; attempt++) {
      data = JSON.parse((await request(f.port, 'GET', {}, '/__harness/diagnostics')).body)
      if (data.active.sse === 0) break
      await new Promise(resolve => setTimeout(resolve, 5))
    }
    assert.equal(data.layers.sse.state, 'closed')
  } finally { clearTimeout(watchdog); stream?.destroy(); await f.close() }
})
test('A queued POST deadline responds promptly without ever sending that POST upstream', async () => {
  let posts = 0, stream, watchdog, busy
  const f = await fixture((req, res) => {
    if (req.method === 'POST') { posts++; res.end('unexpected') }
    else if (req.url === '/sentinel') res.end('queue-drained')
    else { busy = res; res.writeHead(200, { 'content-type': 'application/octet-stream' }); res.write('busy') }
  }, { responseTimeoutMs: 40 })
  try {
    await new Promise((resolve, reject) => {
      http.get({ host: '127.0.0.1', port: f.port }, response => {
        stream = response; response.on('error', () => {}); response.once('data', resolve)
      }).on('error', reject)
    })
    const result = await Promise.race([request(f.port, 'POST'), new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error('Queued request deadline did not respond')), 500) })])
    assert.equal(result.status, 502); assert.equal(posts, 0)
    const ended = new Promise(resolve => stream.once('end', resolve))
    stream.resume(); busy.end(); await ended
    assert.equal((await request(f.port, 'GET', {}, '/sentinel')).body, 'queue-drained')
    assert.equal(posts, 0, 'A timed-out queued write must stay cancelled after the pool is released')
  } finally { clearTimeout(watchdog); stream?.destroy(); await f.close() }
})
test('The stable entry maps only its own origin to the fixed trusted VM authority', async () => {
  const f = await fixture((req, res) => {
    res.setHeader('Location', 'http://127.0.0.1:49224/next')
    res.end(JSON.stringify({ host: req.headers.host, origin: req.headers.origin }))
  })
  try {
    const result = await request(f.port, 'GET', { origin: 'http://127.0.0.1:' + f.port })
    const own = JSON.parse(result.body)
    assert.equal(own.host, '127.0.0.1:49224'); assert.equal(own.origin, 'http://127.0.0.1:49224')
    assert.equal(result.headers.location, 'http://127.0.0.1:' + f.port + '/next')
    for (const origin of ['https://outside.invalid', 'null', 'http://127.0.0.1:49224']) {
      assert.equal((await request(f.port, 'GET', { origin })).status, 403)
    }
  } finally { await f.close() }
})
test('The entry rejects unexpected Host and absolute proxy targets', async () => {
  let calls = 0
  const f = await fixture((_req, res) => { calls++; res.end('unexpected') })
  try {
    assert.equal((await request(f.port, 'GET', { host: 'outside.invalid' })).status, 421)
    assert.equal((await request(f.port, 'GET', {}, 'http://outside.invalid/')).status, 400)
    assert.equal(calls, 0)
  } finally { await f.close() }
})
test('Local diagnostics show response layers and never retain query strings, headers or bodies', async () => {
  const f = await fixture((_req, res) => res.end('PRIVATE_RESPONSE_CANARY'))
  try {
    await request(f.port, 'GET', { cookie: 'PRIVATE_COOKIE_CANARY' }, '/assets/main.js?token=PRIVATE_QUERY_CANARY')
    const r = await request(f.port, 'GET', {}, '/__harness/diagnostics')
    assert.equal(r.status, 200)
    const data = JSON.parse(r.body)
    assert.equal(data.layers.assets.state, 'ok')
    assert.ok(data.recent.some(item => item.category === 'assets' && item.status === 200))
    assert.doesNotMatch(r.body, /PRIVATE_|token=|main\.js/)
    assert.match((await request(f.port, 'GET', {}, '/__harness/health')).body, /连接状态|链路状态/)
  } finally { await f.close() }
})
test('Diagnostics distinguish authentication rejection from a lost VM connection', async () => {
  const f = await fixture((req, res) => {
    if (req.url === '/api/denied') { res.writeHead(401); res.end('unauthorized') }
    else req.socket.destroy()
  })
  try {
    await request(f.port, 'POST', {}, '/api/denied')
    let data = JSON.parse((await request(f.port, 'GET', {}, '/__harness/diagnostics')).body)
    assert.equal(data.layers.api.state, 'auth-required')
    await request(f.port, 'POST', {}, '/redteam/api')
    data = JSON.parse((await request(f.port, 'GET', {}, '/__harness/diagnostics')).body)
    assert.equal(data.layers.redteam.state, 'connection-error')
    assert.ok(data.recent.some(item => item.error === 'connection-reset'))
  } finally { await f.close() }
})
test('WebSocket upgrades and bytes pass through while subsequent HTTP still works', async () => {
  const f = await fixture((_req, res) => res.end('http-after-upgrade'))
  let receivedHeaders
  f.upstream.on('upgrade', (req, socket) => {
    receivedHeaders = req.headers
    socket.write('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n')
    socket.on('data', data => socket.write(data))
  })
  const socket = net.connect(f.port, '127.0.0.1')
  try {
    let phase = 0
    const echoed = new Promise((resolve, reject) => {
      socket.setTimeout(3000, () => reject(new Error('Upgrade did not complete')))
      socket.on('error', reject)
      socket.on('data', data => {
        if (phase === 0) { assert.match(data.toString(), /101 Switching Protocols/); phase++; socket.write('echo-canary') }
        else { assert.equal(data.toString(), 'echo-canary'); resolve() }
      })
    })
    socket.write('GET /socket HTTP/1.1\r\nHost: 127.0.0.1:' + f.port + '\r\nOrigin: http://127.0.0.1:' + f.port + '\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n')
    await echoed
    const observed = JSON.parse((await request(f.port, 'GET', {}, '/__harness/diagnostics')).body)
    assert.equal(observed.layers.websocket.state, 'connected')
    assert.equal(receivedHeaders.host, '127.0.0.1:49224')
    assert.equal(receivedHeaders.origin, 'http://127.0.0.1:49224')
    assert.equal((await request(f.port)).body, 'http-after-upgrade')
  } finally { socket.destroy(); await f.close() }
})
