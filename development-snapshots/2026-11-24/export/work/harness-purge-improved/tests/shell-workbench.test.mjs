import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source = fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8')
function fixture(options={}) {
  const events=[], target={sessionId:'session-A',paneId:'pane-A'}, listeners=new Set(),closedTabs=new Set()
  let expanded=false,phase=options.phase||'connected',mounted='session-A',opened=false
  const view={state:{getSnapshot:()=>({phase}),subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)}},connect:()=>{events.push(['reconnect']);phase='connected'}}
  const sidebar={
    commandTarget:()=>options.noSession?undefined:target,
    isTargetCurrent:()=>!options.stale,
    mounted:{getSnapshot:()=>mounted},
    tabDomain:{occurrence:()=>({navigation:{getSnapshot:()=>({params:undefined})}})},
    openTabs:{getSnapshot:()=>[...(options.tabs||[]),...(opened?[{sessionId:'session-A',kind:'terminal',tabId:'new',contentId:'new-content'}]:[])]},
    isExpanded:()=>expanded,
    toggleExpanded:()=>{expanded=!expanded;events.push(['expand',expanded])},
    focus:id=>events.push(['focus',id]),
    active:()=>options.active?{id:options.active}:undefined,
    openTabFromTarget:(kind,captured)=>{if(options.fail)throw Error('Native terminal unavailable');events.push(['new',kind,captured.sessionId])},
  }
  const inventory=sidebar.openTabs.getSnapshot
  sidebar.openTabs.getSnapshot=()=>inventory().filter(tab=>!closedTabs.has(tab.tabId))
  const nativeOpen=sidebar.openTabFromTarget;sidebar.openTabFromTarget=(...args)=>{nativeOpen(...args);opened=true}
  let deadline
  const scope={vmShellRecent:new Map(),setTimeout:options.fakeDeadline?(fn=>{deadline=fn;return 1}):setTimeout,clearTimeout:options.fakeDeadline?(()=>{deadline=undefined}):clearTimeout,window:{location:{origin:'http://127.0.0.1:49226',hash:'#redteam-full',pathname:'/',search:''},history:{state:null,replaceState:(_state,_title,url)=>events.push(['url',url])}},
    setDock:patch=>events.push(['dock',patch.open]),__dshPurgeDrill:{setUI:patch=>events.push(['drill',patch.open])}}
  let start=source.indexOf('function openVmShellWorkbench(')
  assert.notEqual(start,-1,'The requested VM Shell workbench entry is missing')
  if(source.slice(start-6,start)==='async ')start-=6
  const end=source.indexOf('\n\t\tfunction ShellWorkbenchButton(',start)
  assert.ok(end>start,'Workbench helper must be independently testable')
  vm.runInNewContext(source.slice(start,end)+'\nopen=openVmShellWorkbench',scope)
  const host={get:name=>options.missing?undefined:name==='sidebarRight'?sidebar:{view:(_session,id)=>options.states?.[id]?{...view,state:{...view.state,getSnapshot:()=>options.states[id]}}:view}}
  return {events,open:async(signal,action)=>scope.open(host,signal,action),state:value=>{phase=value;for(const fn of listeners)fn()},switchSession:()=>{mounted='session-B'},listeners,expire:()=>deadline(),closeTab:()=>closedTabs.add('new')}
}
test('Shell workbench opens the official terminal in the on-screen Session before hiding the drill',async()=>{
  const f=fixture();await f.open()
  assert.deepEqual(f.events,[['new','terminal','session-A'],['url','/'],['drill',false],['dock',false]])
})
test('Workbench reuses this Session terminal and never reuses another Session terminal',async()=>{
  const f=fixture({tabs:[{sessionId:'session-B',kind:'terminal',tabId:'foreign'},{sessionId:'session-A',kind:'terminal',tabId:'own'}]})
  await f.open();await f.open()
  assert.equal(f.events.filter(e=>e[0]==='new').length,0)
  assert.equal(f.events.filter(e=>e[0]==='expand').length,1)
  assert.equal(f.events.filter(e=>e[0]==='focus'&&e[1]==='own').length,2)
  assert.equal(f.events.some(e=>e.includes('foreign')),false)
})
test('An inactive or changed Session cannot open a terminal or hide the drill',async()=>{
  for(const options of [{noSession:true},{stale:true},{missing:true}]) {
    const f=fixture(options);await assert.rejects(f.open(),/会话|终端/);assert.deepEqual(f.events,[])
  }
})
test('A native terminal failure leaves the current drill visible without a fallback shell',async()=>{
  const f=fixture({fail:true});await assert.rejects(f.open(),/Native terminal unavailable/);assert.deepEqual(f.events,[])
})
test('A tab opening does not hide the drill until the native PTY is connected',async()=>{
  const f=fixture({phase:'creating'}),pending=f.open();await Promise.resolve()
  assert.deepEqual(f.events,[['new','terminal','session-A']])
  f.state('connected');await pending
  assert.ok(f.events.some(e=>e[0]==='dock'));assert.equal(f.listeners.size,0)
})
test('Asynchronous PTY failure keeps the drill visible and releases its observer',async()=>{
  const f=fixture({phase:'creating'}),pending=f.open();await Promise.resolve();f.state('failed')
  await assert.rejects(pending,/终端/)
  assert.deepEqual(f.events,[['new','terminal','session-A']]);assert.equal(f.listeners.size,0)
})
test('Session changes while starting cannot dismiss the next Session interface',async()=>{
  const f=fixture({phase:'creating'}),pending=f.open();await Promise.resolve();f.switchSession();f.state('connected')
  await assert.rejects(pending,/会话/)
  assert.deepEqual(f.events,[['new','terminal','session-A']])
})
test('A missing renderer times out without hiding the drill or leaving an observer',async()=>{
  const f=fixture({phase:'idle',fakeDeadline:true}),pending=f.open();await Promise.resolve();f.expire()
  await assert.rejects(pending,/超时/);assert.equal(f.listeners.size,0)
  assert.deepEqual(f.events,[['new','terminal','session-A']])
})
test('Plugin disposal after a connected event cannot dismiss the current page',async()=>{
  const f=fixture({phase:'creating'}),controller=new AbortController(),pending=f.open(controller.signal)
  await Promise.resolve();f.state('connected');controller.abort()
  await assert.rejects(pending);assert.equal(f.listeners.size,0)
  assert.deepEqual(f.events,[['new','terminal','session-A']])
})
test('Closing the terminal after its connected event cannot dismiss the current drill',async()=>{
  const f=fixture({phase:'creating'}),pending=f.open()
  await Promise.resolve();f.state('connected');f.closeTab()
  await assert.rejects(pending,/终端/)
  assert.deepEqual(f.events,[['new','terminal','session-A']])
})
test('Another Session using the same local tabId cannot hide a newly opened terminal',async()=>{
  const f=fixture({tabs:[{sessionId:'session-B',kind:'files',tabId:'new',contentId:'foreign-content'}]})
  await f.open()
  assert.deepEqual(f.events,[['new','terminal','session-A'],['url','/'],['drill',false],['dock',false]])
})
test('A closed first tab cannot prevent choosing another healthy terminal',async()=>{
  const f=fixture({tabs:[{sessionId:'session-A',kind:'terminal',tabId:'dead',contentId:'dead-content'},{sessionId:'session-A',kind:'terminal',tabId:'ready',contentId:'ready-content'}],states:{dead:{phase:'closed'},ready:{phase:'connected',info:{state:'running'}}}})
  await f.open();assert.ok(f.events.some(e=>e[0]==='focus'&&e[1]==='ready'));assert.ok(!f.events.some(e=>e.includes('dead')))
})
test('The active healthy terminal is preferred and an exited shell is not reusable',async()=>{
  const f=fixture({active:'second',tabs:[{sessionId:'session-A',kind:'terminal',tabId:'first',contentId:'first-content'},{sessionId:'session-A',kind:'terminal',tabId:'second',contentId:'second-content'}],states:{first:{phase:'connected',info:{state:'exited'}},second:{phase:'connected',info:{state:'running'}}}})
  await f.open();assert.ok(f.events.some(e=>e[0]==='focus'&&e[1]==='second'))
})
test('Explicit new opens a separate terminal without terminating retained terminals',async()=>{
  const f=fixture({tabs:[{sessionId:'session-A',kind:'terminal',tabId:'retained',contentId:'retained-content'}]})
  await f.open(undefined,{action:'new'});assert.ok(f.events.some(e=>e[0]==='new'));assert.ok(!f.events.some(e=>e.includes('retained')))
})
test('Explicit reconnect reattaches the same process and never writes commands',async()=>{
  const f=fixture({phase:'disconnected',tabs:[{sessionId:'session-A',kind:'terminal',tabId:'own',contentId:'own-content'}]})
  await f.open(undefined,{action:'reconnect',tabId:'own'});assert.equal(f.events.filter(e=>e[0]==='reconnect').length,1);assert.ok(!f.events.some(e=>e[0]==='new'))
})
test('Explicit foreign or closed terminal selection cannot fall back to a different process',async()=>{
  for(const action of [{action:'select',tabId:'foreign'},{action:'select',tabId:'dead'}]){
    const f=fixture({tabs:[{sessionId:'session-B',kind:'terminal',tabId:'foreign',contentId:'foreign-content'},{sessionId:'session-A',kind:'terminal',tabId:'dead',contentId:'dead-content'}],states:{dead:{phase:'closed'}}})
    await assert.rejects(f.open(undefined,action),/终端/);assert.deepEqual(f.events,[])
  }
})
