import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {webcrypto} from 'node:crypto'
const url = new URL('../package/lib/personal-startup-recovery.mjs', import.meta.url)
const recovery = fs.existsSync(url) ? await import(url) : { installStartupRecovery() {} }

function fixture(mounted = false,options={}) {
  let hook
  recovery.installStartupRecovery({ on(name, handler) { assert.equal(name, 'webserver/index-inject'); hook = handler } })
  assert.equal(typeof hook, 'function', 'Startup recovery must register an index injection')
  const table = [{ kind: 'script', text: 'main module' }]
  hook(table)
  assert.equal(table[0].placement, 'head')
  const listeners = {}, timers = [], elements = [], requests=[]
  let reloads = 0
  function element(tag) {
    return { tagName: tag.toUpperCase(), style: {}, children: [],
      setAttribute(name, value) { this[name] = value },
      appendChild(child) { this.children.push(child); elements.push(child) },
      addEventListener(name, fn) { this[name] = fn },
      remove() { elements.splice(elements.indexOf(this), 1) } }
  }
  const root = { childElementCount: mounted ? 1 : 0 }
  const document = {
    readyState: 'complete', body: element('body'), createElement: element,
    getElementById: id => id === 'root' ? root : elements.find(e => e.id === id),
    addEventListener(name, fn) { listeners[name] = fn },
  }
  const window = { location: { origin: 'http://127.0.0.1:49226', reload() { reloads++ } },
    addEventListener(name, fn) { listeners[name] = fn } }
  window.crypto=webcrypto;window.sessionStorage=options.storage;window.fetch=async(url,request)=>{requests.push({url,...request});if(options.fetch)return options.fetch(request);if(options.rejectFetch)throw Error('offline');return{ok:true,json:async()=>({ok:true})}};
  const observers=[];
  vm.runInNewContext(table[0].text, { window, document, URL, TextEncoder, performance,AbortController, MutationObserver:class{constructor(fn){this.fn=fn;observers.push(this)}observe(){}disconnect(){}},setTimeout: (fn,ms) => {if(ms===5000)return setTimeout(fn,ms);timers.push(fn);return timers.length },clearTimeout })
  return { listeners, timers, elements, root, document, requests, observers, reloads: () => reloads }
}

test('An empty startup shows an accessible manual recovery action after its deadline', () => {
  const h = fixture()
  h.timers.forEach(fn => fn())
  const alert = h.elements.find(e => e.role === 'alert')
  assert.ok(alert)
  const button = h.elements.find(e => e.tagName === 'BUTTON' && /重新加载/.test(e.textContent))
  assert.ok(button)
  assert.equal(h.reloads(), 0, 'Never automatically reload or replay user work')
  button.click()
  assert.equal(h.reloads(), 1)
  assert.ok(h.elements.some(e => e.tagName === 'A' && e.href === '/__harness/health'), 'The VM recovery warning should link to local connection diagnostics')
})

test('A successful mount and an unrelated image error do not create recovery warnings', () => {
  const h = fixture(true)
  h.timers.forEach(fn => fn())
  h.listeners.error({ target: { tagName: 'IMG', src: 'http://127.0.0.1:49226/image.png' } })
  assert.equal(h.elements.length, 0)
})

test('A failed local stylesheet shows one warning without exposing its URL or query', () => {
  const h = fixture(true)
  const event = { target: { tagName: 'LINK', rel: 'stylesheet', href: 'http://127.0.0.1:49226/assets/main.css?token=never-show-this' } }
  h.listeners.error(event); h.listeners.error(event)
  assert.equal(h.elements.filter(e => e.role === 'alert').length, 1)
  assert.ok(!h.elements.some(e => String(e.textContent).includes('never-show-this')))
})

test('A delayed DOMContentLoaded rechecks the root before showing an empty-root timeout',()=>{
 const h=fixture();h.document.readyState='loading';h.timers[0]();h.root.childElementCount=1;h.document.readyState='complete';h.listeners.DOMContentLoaded();
 assert.equal(h.elements.filter(e=>e.role==='alert').length,0,'An already mounted interface cannot be reported as an empty root');
});
test('Startup distinguishes resource errors from empty-root deadlines and only sends sanitized event identities',async()=>{
 const h=fixture(true);h.listeners.error({target:{tagName:'SCRIPT',src:'http://127.0.0.1:49226/assets/main.js?token=SECRET_CANARY'}});await new Promise(r=>setTimeout(r,30));
 const events=h.requests.map(r=>JSON.parse(r.body));assert.ok(events.some(e=>e.code==='script-error'));assert.doesNotMatch(JSON.stringify(h.requests),/SECRET_CANARY|main\.js/);assert.ok(events.find(e=>e.code==='script-error').resource.hash.match(/^[a-f0-9]{64}$/));assert.ok(h.elements.some(e=>e.tagName==='A'&&e.href==='/dsh-purge/startup-diagnostics'));
 const slow=fixture();slow.timers[0]();await new Promise(setImmediate);assert.ok(slow.requests.some(r=>JSON.parse(r.body).code==='empty-root'));slow.root.childElementCount=1;slow.observers.forEach(o=>o.fn());await new Promise(setImmediate);assert.ok(slow.requests.some(r=>JSON.parse(r.body).code==='mounted'));assert.equal(slow.elements.filter(e=>e.role==='alert').length,0);
});
test('An offline diagnostic event survives reload and is resent with the same idempotency identity',async()=>{
 const map=new Map(),storage={getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v)};const first=fixture(false,{storage,rejectFetch:true});first.timers[0]();await new Promise(setImmediate);const saved=JSON.parse(map.get('dsh-startup-pending-v1'));assert.equal(saved[0].code,'empty-root');const second=fixture(true,{storage});await new Promise(setImmediate);assert.ok(second.requests.some(r=>JSON.parse(r.body).page===saved[0].page&&JSON.parse(r.body).sequence===saved[0].sequence));assert.deepEqual(JSON.parse(map.get('dsh-startup-pending-v1')),[]);
});
test('Diagnostic delivery has a bounded abort deadline and cannot stall startup',async()=>{
 const h=fixture(true);await new Promise(setImmediate);assert.ok(h.requests[0].signal instanceof AbortSignal);assert.equal(h.requests[0].signal.aborted,false);
});
test('A generic fetch rejection stays unclassified while a module-specific rejection identifies an import failure',async()=>{
 for(const [message,code] of [['Failed to fetch','rejection'],['Failed to fetch dynamically imported module: SECRET_CANARY','module-error']]){const h=fixture();h.listeners.unhandledrejection({reason:new TypeError(message)});await new Promise(setImmediate);assert.equal(JSON.parse(h.requests[0].body).code,code);assert.doesNotMatch(JSON.stringify(h.requests),/SECRET_CANARY/)}
});
test('Offline queue overflow retains the first failure even when earlier events are successful mounts',async()=>{
 const saved=Array.from({length:24},(_,n)=>({page:n.toString(16).padStart(32,'0'),sequence:1,code:n===1?'script-error':'mounted',elapsedMs:1,ready:'complete',visible:true,rootChildren:0,resource:null})),map=new Map([['dsh-startup-pending-v1',JSON.stringify(saved)]]),storage={getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v)};
 fixture(true,{storage,rejectFetch:true});await new Promise(setImmediate);const queued=JSON.parse(map.get('dsh-startup-pending-v1'));assert.equal(queued.length,24);assert.ok(queued.some(e=>e.page===saved[1].page&&e.code==='script-error'));
});
test('Acknowledging an evicted in-flight success cannot remove an unsent failure',async()=>{
 const saved=Array.from({length:24},(_,n)=>({page:n.toString(16).padStart(32,'0'),sequence:1,code:n===1?'script-error':'mounted',elapsedMs:1,ready:'complete',visible:true,rootChildren:0,resource:null})),map=new Map([['dsh-startup-pending-v1',JSON.stringify(saved)]]),storage={getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v)};let release,calls=0;
 const h=fixture(false,{storage,fetch:async()=>{if(calls++===0)await new Promise(r=>release=r);return{ok:true,json:async()=>({ok:true})}}});h.listeners.error({target:{},message:'synthetic runtime failure'});release();await new Promise(setImmediate);assert.ok(h.requests.some(r=>JSON.parse(r.body).page===saved[1].page&&JSON.parse(r.body).code==='script-error'),'The unsent failure must be delivered, not dropped by another event acknowledgment');
});
