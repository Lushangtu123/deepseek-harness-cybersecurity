/** Remote Kali discovery uses only the already provisioned fixed SSH client. */
import { execFile } from 'node:child_process'
import { lstatSync, realpathSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
export const KALI_TOOL_IDS = Object.freeze(['nmap', 'nuclei', 'masscan', 'fscan', 'gogo', 'suo5', 'frpc', 'frps', 'chisel', 'ffuf', 'httpx', 'dnsx', 'subfinder', 'ksubdomain', 'impacket', 'curl', 'wget', 'dig', 'openssl', 'tcpdump', 'tshark', 'whatweb', 'nikto', 'sqlmap', 'file', 'strings'])
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const short = value => typeof value === 'string' && value.length > 0 && value.length <= 160 && !/[\x00-\x1f\x7f]/.test(value)
export function validateKaliInventory(value) {
  if (!record(value) || value.uid !== 1000 || value.osId !== 'kali' || value.persistentInstall !== true
    || !short(value.hostname) || !short(value.kernel) || !short(value.version) || !record(value.tools)
    || Object.keys(value.tools).some(key => !KALI_TOOL_IDS.includes(key))
    || Object.values(value.tools).some(path => path !== null && (typeof path !== 'string' || !/^\/[A-Za-z0-9_./+-]{1,500}$/.test(path) || path.split('/').includes('..')))) throw new Error('invalid-kali-inventory')
  return { hostname:value.hostname, uid:1000, osId:'kali', kernel:value.kernel, version:value.version, persistentInstall:true,
    tools:Object.fromEntries(KALI_TOOL_IDS.map(id=>[id,value.tools[id] ?? null])) }
}
function executable(path) {
  try { const info=lstatSync(path);return info.isFile() && !info.isSymbolicLink() && realpathSync(path)===path && (info.mode&0o111)!==0 && (typeof process.getuid!=='function' || info.uid===process.getuid()) } catch { return false }
}
export function createKaliProbe({home=homedir(),execute=promisify(execFile),available=executable,now=Date.now}={}) {
  const client=join(home,'.local/bin/kali-vm');let snapshot={state:'not-checked',tools:{}},pending
  const current=()=>{
    if (snapshot.state==='connected' && (now()<snapshot.checkedAt || now()-snapshot.checkedAt>90000)) return {state:'stale',checkedAt:snapshot.checkedAt,tools:{}}
    return snapshot
  }
  const refresh=()=>{
    if (pending) return pending
    if (!available(client)) { snapshot={state:'not-configured',tools:{}};return Promise.resolve(snapshot) }
    const startedAt=now()
    pending=(async()=>{
      try {
        const result=await execute(client,['inventory'],{shell:false,timeout:12000,maxBuffer:65536,encoding:'utf8',killSignal:'SIGKILL'})
        const finishedAt=now()
        if (finishedAt<startedAt || finishedAt-startedAt>15000) throw new Error('probe-window-expired')
        snapshot={...validateKaliInventory(JSON.parse(result.stdout)),state:'connected',checkedAt:finishedAt}
      } catch { snapshot={state:'unavailable',checkedAt:now(),tools:{}} }
      return current()
    })().finally(()=>{pending=undefined})
    return pending
  }
  return {current,refresh,toolPath:id=>KALI_TOOL_IDS.includes(id)?join(home,'.local/lib/harness-kali-tools',id):null,available}
}
export const kaliProbe=createKaliProbe()
export function resolveKaliTool(id) {
  const snapshot=kaliProbe.current(),path=kaliProbe.toolPath(id)
  return {path:snapshot.state==='connected' && snapshot.tools[id] && path && kaliProbe.available(path)?path:null,
    source:'kali',remotePath:snapshot.state==='connected'?snapshot.tools[id] || null:null,
    note:snapshot.state==='connected'?'通过专用 SSH 在 Kali 执行；不自动 sudo':'Kali 连接未确认，请在环境适配刷新连接'}
}

export function kaliPreflight(platform) {
  const items=platform.tools.items,missing=items.filter(row=>!row.path)
  return {ok:platform.adapt.ready && missing.length===0,executionTarget:'kali',platform,checked:0,available:[],broken:[],
    availableTools:items.filter(row=>row.path).map(row=>row.id),missingTools:missing.map(row=>row.id),
    onboarding:{ready:platform.adapt.ready,missing:missing.map(row=>'Kali 工具：'+row.id)},
    skills_root_hint:'未检查远程技能、模板、词表、FOFA/VPS 或其凭据；本机文件与环境变量不会自动传到 Kali。',
    next:'使用 platform.tools.items 中的 SSH 工具入口；所有输入、输出文件和模板参数均为 Kali 内路径，stdout 和退出码返回 Harness。缺失工具仍不可用，不自动安装、扫描或 sudo。'}
}
