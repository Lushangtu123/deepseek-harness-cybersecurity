/**
 * 红队平台适配配置（插件内，无 .ps1）
 *
 * 落盘：`$DSH_HOME/redteam/config.json`
 * 用途：
 *   · Windows / 非 Kali 机器上，由用户填写工具绝对路径或搜索目录；
 *   · preflight / 技能可用性 / nuclei 模板目录 统一走这里；
 *   · 不往官方 `$DSH_HOME/skills` 写任何东西。
 *
 * 借鉴 Z3r0：系统配置集中、可在 UI 里改（FOFA / 路径类），而不是只靠 shell 引导。
 */
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readSync, readdirSync, statSync, writeFileSync, lstatSync, mkdtempSync, fchmodSync, fsyncSync, renameSync, rmSync } from 'node:fs'
import { homedir, platform as osPlatform } from 'node:os'
import { kaliProbe, resolveKaliTool } from './personal-kali-environment.mjs'
import { delimiter, isAbsolute, join, resolve, sep } from 'node:path'

/** 配置文件路径。 */
export function configPathOf(root) {
  return join(root || redteamRoot(), 'config.json')
}

export function redteamRoot() {
  const home = process.env.DSH_HOME || join(homedir(), '.dsh')
  return join(home, 'redteam')
}

/** 默认工具箱目录。 */
export function defaultToolkitDir(root) {
  return join(root || redteamRoot(), 'toolkit')
}

/**
 * 内置工具清单：id → 可能的可执行名（含 Windows .exe）。
 * 用户可在 config.tools[id] 填绝对路径覆盖；也可在 binDirs 里放整包工具目录。
 */
export const TOOL_CATALOG = [
  { id: 'nmap', label: 'Nmap', names: ['nmap.exe', 'nmap'] },
  { id: 'nuclei', label: 'Nuclei', names: ['nuclei.exe', 'nuclei'] },
  { id: 'masscan', label: 'Masscan', names: ['masscan.exe', 'masscan'] },
  { id: 'fscan', label: 'fscan', names: ['fscan.exe', 'fscan'] },
  { id: 'gogo', label: 'gogo', names: ['gogo.exe', 'gogo'] },
  { id: 'suo5', label: 'suo5', names: ['suo5.exe', 'suo5-windows-amd64.exe', 'suo5-linux-amd64', 'suo5'] },
  { id: 'frpc', label: "frp client", names: ['frpc.exe', 'frpc'] },
  { id: 'frps', label: "frp server", names: ['frps.exe', 'frps'] },
  { id: 'chisel', label: 'chisel', names: ['chisel.exe', 'chisel'] },
  { id: 'ffuf', label: 'ffuf', names: ['ffuf.exe', 'ffuf'] },
  /* names 是候选文件名，不是某台机器的绝对路径。adapt 是发行版常见别名，目录里碰见才用。 */
  { id: 'httpx', label: 'httpx', names: ['httpx-toolkit', 'pd-httpx', 'httpx.exe', 'httpx'], rejectPython: true, adapt: [/^httpx-toolkit$/, /^pd-httpx$/, /^httpx$/] },
  { id: 'dnsx', label: 'dnsx', names: ['dnsx.exe', 'dnsx'] },
  { id: 'subfinder', label: 'subfinder', names: ['subfinder.exe', 'subfinder'] },
  { id: 'ksubdomain', label: 'ksubdomain', names: ['ksubdomain.exe', 'ksubdomain'] },
  { id: 'impacket', label: "impacket (folder or entrypoint)", names: ['impacket-secretsdump', 'impacket-secretsdump.exe', 'secretsdump.py', 'impacket'], adapt: [/^impacket-secretsdump$/, /^secretsdump\.py$/] },
  { id: 'curl', label: 'curl', names: ['curl'] },
  { id: 'wget', label: 'Wget', names: ['wget'] },
  { id: 'dig', label: 'DNS dig', names: ['dig'] },
  { id: 'openssl', label: 'OpenSSL', names: ['openssl'] },
  { id: 'tcpdump', label: 'tcpdump', names: ['tcpdump'] },
  { id: 'tshark', label: 'TShark', names: ['tshark'] },
  { id: 'whatweb', label: 'WhatWeb', names: ['whatweb'] },
  { id: 'nikto', label: 'Nikto', names: ['nikto'] },
  { id: 'sqlmap', label: 'sqlmap', names: ['sqlmap'] },
  { id: 'file', label: 'File type', names: ['file'] },
  { id: 'strings', label: 'Strings', names: ['strings'] },
]

const EMPTY = () => ({
  version: 1,
  /* auto | windows | linux —— auto 跟 Node process.platform */
  platform: 'auto',
  executionTarget: 'local',
  toolkitDir: '',
  nucleiTemplatesDir: '',
  /* 额外搜索目录：用户自己的 Kali 工具包 / 绿色版工具夹 */
  binDirs: [],
  /* id → 绝对路径；空字符串表示未指定 */
  tools: Object.fromEntries(TOOL_CATALOG.map((t) => [t.id, ''])),
  env: {
    FOFA_KEY: '',
    REDTEAM_VPS_HOST: '',
    REDTEAM_VPS_KEY: '',
  },
  notes: '',
  /* 用户确认「暂不配置工具」后允许正常对话 */
  envAdaptSkip: false,
  /* 用户在环境适配里保存/文件夹分配过一次 */
  envAdaptConfigured: false,
  updated_at: null,
})

function isWinLike(cfg) {
  const p = (cfg && cfg.platform) || 'auto'
  if (p === 'windows') return true
  if (p === 'linux') return false
  return osPlatform() === 'win32'
}

function validPlatformConfig(raw) {
  const record = v => v !== null && typeof v === 'object' && !Array.isArray(v)
  if (!record(raw) || (raw.executionTarget !== undefined && !['local','kali'].includes(raw.executionTarget)) || (raw.version != null && (!['number', 'string'].includes(typeof raw.version) || Number(raw.version) !== 1))
      || ['tools', 'env'].some(k => raw[k] != null && !record(raw[k]))
      || ['tools', 'env'].some(k => raw[k] != null && Object.values(raw[k]).some(v => v != null && typeof v !== 'string'))
      || (raw.binDirs != null && (!Array.isArray(raw.binDirs) || raw.binDirs.some(v => typeof v !== 'string')))
      || ['envAdaptSkip', 'envAdaptConfigured'].some(k => raw[k] != null && typeof raw[k] !== 'boolean')
      || ['toolkitDir', 'nucleiTemplatesDir', 'notes'].some(k => raw[k] != null && typeof raw[k] !== 'string')
      || (raw.platform != null && !['auto', 'windows', 'linux'].includes(raw.platform))) return false
  return true
}

export function loadPlatformConfig(root) {
  const base = EMPTY()
  const file = configPathOf(root)
  let observed = false
  try {
    const info = lstatSync(file)
    observed = true
    if (!info.isFile() || info.isSymbolicLink()) throw new Error('unsupported-config-file')
    const raw = JSON.parse(readFileSync(file, 'utf8'))
    if (!validPlatformConfig(raw)) throw new Error('invalid-config-shape')
    const tools = Object.assign({}, base.tools, raw.tools && typeof raw.tools === 'object' ? raw.tools : {})
    const env = Object.assign({}, base.env, raw.env && typeof raw.env === 'object' ? raw.env : {})
    const binDirs = Array.isArray(raw.binDirs)
      ? raw.binDirs.map((x) => String(x || '').trim()).filter(Boolean)
      : []
    return {
      version: Number(raw.version) || 1,
      platform: ['auto', 'windows', 'linux'].includes(raw.platform) ? raw.platform : 'auto',
      executionTarget: raw.executionTarget || 'local',
      toolkitDir: typeof raw.toolkitDir === 'string' ? raw.toolkitDir.trim() : '',
      nucleiTemplatesDir: typeof raw.nucleiTemplatesDir === 'string' ? raw.nucleiTemplatesDir.trim() : '',
      binDirs,
      tools,
      env,
      notes: typeof raw.notes === 'string' ? raw.notes : '',
      envAdaptSkip: !!raw.envAdaptSkip,
      envAdaptConfigured: !!raw.envAdaptConfigured,
      updated_at: raw.updated_at || null,
      path: file,
      exists: true,
      readState: 'ready',
    }
  } catch (error) {
    if (error?.code === 'ENOENT' && !observed) return { ...base, path: file, exists: false, readState: 'missing' }
    return { ...base, path: file, exists: true, readState: 'error', errorCode: 'platform-config-unavailable',
      error: '现有环境配置读取未确认，已暂停修改。请检查原文件或从备份恢复。' }

  }
}

export function savePlatformConfig(patch, root) {
  if (!validPlatformConfig(patch)) throw new Error('环境配置输入结构无效，未执行保存。')
  const dir = root || redteamRoot()
  mkdirSync(dir, { recursive: true })
  const prev = loadPlatformConfig(dir)
  if (prev.error) throw new Error(prev.error)
  const next = {
    version: 1,
    platform: ['auto', 'windows', 'linux'].includes(patch.platform) ? patch.platform : (prev.platform || 'auto'),
    executionTarget: patch.executionTarget || prev.executionTarget || 'local',
    toolkitDir: typeof patch.toolkitDir === 'string' ? patch.toolkitDir.trim() : (prev.toolkitDir || ''),
    nucleiTemplatesDir: typeof patch.nucleiTemplatesDir === 'string'
      ? patch.nucleiTemplatesDir.trim()
      : (prev.nucleiTemplatesDir || ''),
    binDirs: Array.isArray(patch.binDirs)
      ? patch.binDirs.map((x) => String(x || '').trim()).filter(Boolean)
      : (prev.binDirs || []),
    tools: Object.assign({}, prev.tools || {}, patch.tools && typeof patch.tools === 'object' ? patch.tools : {}),
    env: Object.assign({}, prev.env || {}, patch.env && typeof patch.env === 'object' ? patch.env : {}),
    notes: typeof patch.notes === 'string' ? patch.notes : (prev.notes || ''),
    envAdaptSkip: patch.envAdaptSkip !== undefined ? !!patch.envAdaptSkip : !!prev.envAdaptSkip,
    envAdaptConfigured: patch.envAdaptConfigured !== undefined
      ? !!patch.envAdaptConfigured
      : !!prev.envAdaptConfigured,
    updated_at: new Date().toISOString(),
  }
  /* 空 tools 键保留 catalog 全量，方便面板编辑 */
  for (const t of TOOL_CATALOG) {
    if (next.tools[t.id] === undefined || next.tools[t.id] === null) next.tools[t.id] = ''
    else next.tools[t.id] = String(next.tools[t.id]).trim()
  }
  if (!validPlatformConfig(next)) throw new Error('环境配置输入结构无效，未执行保存。')
  const file = configPathOf(dir)
  const raw = JSON.stringify(next, null, 2)
  const mode = prev.exists ? lstatSync(file).mode & 0o777 : 0o600
  const temporary = mkdtempSync(join(dir, '.config-save-'))
  const candidate = join(temporary, 'config.json')
  let fd
  try {
    fd = openSync(candidate, 'wx', 0o600)
    writeFileSync(fd, raw, 'utf8'); fchmodSync(fd, mode); fsyncSync(fd)
    if (readFileSync(candidate, 'utf8') !== raw) throw new Error('环境配置暂存核对失败；原文件保持。')
    JSON.parse(raw)
    closeSync(fd); fd = undefined
    renameSync(candidate, file)
    // The replacement is committed. A later sync/read failure is an unknown result,
    // never a reason to replay or replace the original file with guessed defaults.
    if (process.platform !== 'win32') {
      const parent = openSync(dir, 'r')
      try { fsyncSync(parent) } finally { closeSync(parent) }
    }
    if (readFileSync(file, 'utf8') !== raw) throw new Error('环境配置保存结果未确认，请只读核对。')
    const saved = loadPlatformConfig(dir)
    if (saved.error) throw new Error(saved.error)
    return saved
  } finally {
    try { if (fd !== undefined) closeSync(fd) }
    finally { rmSync(temporary, { recursive: true, force: true }) }
  }
}

/** Correlate a completed save without exposing input values in its receipt. */
export function platformSaveResult(request, root) {
  const id = request.operationId
  if (id !== undefined && (typeof id !== 'string' || !/^[A-Za-z0-9-]{1,100}$/.test(id))) throw new Error('环境配置请求标识无效，未执行保存。')
  const config = savePlatformConfig(request.config || {}, root)
  const summary = platformSummary(root)
  if (!summary.ok) return summary
  return { ...summary, config, ...(id === undefined ? {} : {
    writeReceipt: { operationId: id, op: 'platformConfigSave', state: 'committed' },
  }) }
}

/** 生效的工具箱根。 */
export function toolkitDirOf(cfg, root) {
  const c = cfg || loadPlatformConfig(root)
  if (c.toolkitDir) return resolve(c.toolkitDir)
  return defaultToolkitDir(root)
}

/** 生效的 nuclei 模板目录（可空）。 */
export function nucleiTemplatesDirOf(cfg, root) {
  const c = cfg || loadPlatformConfig(root)
  if (c.executionTarget === 'kali') return null
  if (c.nucleiTemplatesDir && existsSync(c.nucleiTemplatesDir)) return resolve(c.nucleiTemplatesDir)
  return null
}

/**
 * 在目录里找可执行名（浅扫一层 + 常见子目录 bin/）。
 */
function looksLikePythonCli(file) {
  let fd
  try {
    const buf = Buffer.alloc(96)
    fd = openSync(file, 'r')
    const n = readSync(fd, buf, 0, buf.length, 0)
    const head = buf.subarray(0, n).toString('utf8')
    return head.startsWith('#!') && /python/i.test(head)
  } catch {
    return false
  } finally {
    if (fd !== undefined) {
      try { closeSync(fd) } catch { /* ignore */ }
    }
  }
}

function findInDir(dir, names, options = {}) {
  if (!dir || !existsSync(dir)) return null
  const tryOne = (base) => {
    for (const name of names) {
      const p = join(base, name)
      if (existsSync(p)) {
        try {
          const st = statSync(p)
          if (!st.isFile()) continue
          if (options.rejectPython && looksLikePythonCli(p)) continue
          return p
        } catch { /* continue */ }
      }
    }
    return null
  }
  const hit = tryOne(dir) || adaptInDir(dir, options)
  if (hit) return hit
  for (const sub of ['bin', 'Bins', 'tools', 'Tools']) {
    const nested = tryOne(join(dir, sub)) || adaptInDir(join(dir, sub), options)
    if (nested) return nested
  }
  return null
}

/** 精确文件名没有时，用发行版别名在这一层目录里对。对上才算找到。 */
function adaptInDir(dir, options) {
  const patterns = options.adapt
  if (!dir || !Array.isArray(patterns) || patterns.length === 0 || !existsSync(dir)) return null
  let names
  try { names = readdirSync(dir) } catch { return null }
  for (const pattern of patterns) {
    for (const name of names) {
      if (!pattern.test(String(name).toLowerCase())) continue
      const file = join(dir, name)
      try {
        if (!statSync(file).isFile()) continue
        if (options.rejectPython && looksLikePythonCli(file)) continue
        return file
      } catch { /* continue */ }
    }
  }
  return null
}

/** PATH 上的 which（仅同步、不 spawn shell）。 */
function findOnPath(names, env = process.env, options = {}) {
  const pathVar = env.PATH || env.Path || ''
  const parts = pathVar.split(delimiter).filter(Boolean)
  for (const part of parts) {
    const hit = findInDir(part, names, options)
    if (hit) return hit
  }
  return null
}

/** dsh 的 PATH 经常比登录 shell 短。Linux 再补发行版和用户目录。 */
function linuxFallbackDirs(env = process.env) {
  const home = env.HOME || homedir()
  const dirs = ['/usr/local/sbin', '/usr/local/bin', '/usr/sbin', '/usr/bin', '/bin', '/snap/bin']
  if (home) {
    dirs.push(
      join(home, 'go', 'bin'),
      join(home, '.local', 'bin'),
      join(home, '.pdtm', 'go', 'bin'),
    )
  }
  return dirs
}

/**
 * 解析单个工具：用户指定路径 → toolkit → binDirs → PATH。
 * @returns `{ id, label, path, source: 'config'|'toolkit'|'binDir'|'path'|'missing', names }`
 */
export function resolveTool(id, options = {}) {
  const root = options.root || redteamRoot()
  const cfg = options.config || loadPlatformConfig(root)
  const env = options.env || process.env
  const def = TOOL_CATALOG.find((t) => t.id === id)
  if (!def) {
    return { id, label: id, path: null, source: 'missing', names: [] }
  }
  if (cfg.executionTarget === 'kali') return {id,label:def.label,names:def.names,...resolveKaliTool(id)}
  const configured = cfg.tools && typeof cfg.tools[id] === 'string' ? cfg.tools[id].trim() : ''
  if (configured) {
    const abs = isAbsolute(configured) ? configured : resolve(configured)
    if (existsSync(abs)) {
      return { id, label: def.label, path: abs, source: 'config', names: def.names }
    }
    return { id, label: def.label, path: null, source: 'missing', names: def.names, configured: abs, note: "Configured path not found: " + abs }
  }
  const findOpts = { rejectPython: !!def.rejectPython, adapt: def.adapt }
  const toolkit = toolkitDirOf(cfg, root)
  const fromToolkit = findInDir(toolkit, def.names, findOpts)
  if (fromToolkit) return { id, label: def.label, path: fromToolkit, source: 'toolkit', names: def.names }

  for (const dir of cfg.binDirs || []) {
    const hit = findInDir(dir, def.names, findOpts)
    if (hit) return { id, label: def.label, path: hit, source: 'binDir', names: def.names, binDir: dir }
  }

  const fromPath = findOnPath(def.names, env, findOpts)
  if (fromPath) return { id, label: def.label, path: fromPath, source: 'path', names: def.names }

  if (!isWinLike(cfg)) {
    for (const dir of linuxFallbackDirs(env)) {
      const hit = findInDir(dir, def.names, findOpts)
      if (hit) return { id, label: def.label, path: hit, source: 'path', names: def.names }
    }
  }

  return { id, label: def.label, path: null, source: 'missing', names: def.names }
}

export function resolveAllTools(options = {}) {
  return TOOL_CATALOG.map((t) => resolveTool(t.id, options))
}

/**
 * 把配置里的 env 合并进 effectiveEnv（进程 / .env 已有的优先，不覆盖）。
 */
export function mergeConfigEnv(effectiveEnv, cfg) {
  const out = Object.assign({}, effectiveEnv || {})
  const env = (cfg && cfg.env) || {}
  for (const [k, v] of Object.entries(env)) {
    if (typeof v !== 'string') continue
    const val = v.trim()
    if (val === '') continue
    if (out[k] === undefined || out[k] === '') out[k] = val
  }
  return out
}

export async function refreshPlatformSummary(root) {
  if (loadPlatformConfig(root).executionTarget === 'kali') await kaliProbe.refresh()
  return platformSummary(root)
}

/**
 * 平台摘要：给面板与 preflight 用。
 */
export function platformSummary(root) {
  const cfg = loadPlatformConfig(root)
  if (cfg.error) return { ok: false, code: cfg.errorCode, error: cfg.error, config: cfg }
  const win = isWinLike(cfg)
  const tools = resolveAllTools({ root, config: cfg })
  const found = tools.filter((t) => t.path)
  const missing = tools.filter((t) => !t.path)
  const toolkit = toolkitDirOf(cfg, root)
  const nuclei = cfg.executionTarget === 'kali' ? null : (nucleiTemplatesDirOf(cfg, root)
    || (existsSync(join(toolkit, 'nuclei-templates')) ? join(toolkit, 'nuclei-templates') : null))
  const adapt = envAdaptStatus(root)
  return {
    ok: true,
    config: cfg,
    runtime: {
      nodePlatform: osPlatform(),
      executionTarget: cfg.executionTarget || 'local',
      effective: win ? 'windows' : 'linux',
      windows: win,
      sep,
    },
    kali: kaliProbe.current(),
    toolkitDir: toolkit,
    toolkitExists: existsSync(toolkit),
    nucleiTemplatesDir: nuclei,
    tools: {
      total: tools.length,
      found: found.length,
      missing: missing.length,
      items: tools,
    },
    adapt,
    hint: cfg.executionTarget === 'kali' ? '当前工具在独立 Kali VM 中运行。下方路径是 Harness 内的 SSH 调用入口；缺少的工具不会回退到本机。本机路径配置保留，切回本机后生效。' : adapt.kali
      ? "Kali detected. System packages are recognized by their distro filenames: impacket-secretsdump, httpx-toolkit (the Python /usr/bin/httpx is not treated as a scanner). fscan, gogo, suo5, frp, chisel, dnsx, subfinder and ksubdomain are not shipped with Kali, so they show as not found unless they are in /usr/bin or ~/go/bin."
      : (win
        ? "Currently adapted for Windows: run in a Kali VM, or fill in tool paths / auto-assign a whole-folder toolkit on this page. For the egress proxy see \"Egress status\" below."
        : "Currently adapted for Linux: use setup.sh to install the toolkit, or fill paths in manually / auto-assign a whole-folder toolkit on this page. For the egress proxy see \"Egress status\" below."),
    egress: {
      http_proxy: process.env.HTTP_PROXY || process.env.http_proxy || '',
      https_proxy: process.env.HTTPS_PROXY || process.env.https_proxy || '',
      all_proxy: process.env.ALL_PROXY || process.env.all_proxy || '',
      no_proxy: process.env.NO_PROXY || process.env.no_proxy || '',
      note: "Read-only view of the process environment; changing the system/terminal proxy requires a host restart. For per-command proxies use the cn-proxy-pool skill — it does not change this machine's network config.",
    },
  }
}

/** 探测本机是否 Kali / 同系演练发行版。 */
export function detectKali() {
  if (osPlatform() !== 'linux') {
    return { kali: false, source: null, detail: "Not a Linux host" }
  }
  try {
    const text = readFileSync('/etc/os-release', 'utf8')
    if (/ID\s*=\s*"?kali"?/i.test(text) || /ID_LIKE\s*=[^\n]*kali/i.test(text) || /NAME\s*=\s*".*Kali/i.test(text)) {
      return { kali: true, source: 'os-release', detail: "os-release identifies Kali" }
    }
  } catch { /* ignore */ }
  const markers = [
    '/usr/share/kali-menu',
    '/etc/apt/sources.list.d/kali.list',
    '/usr/share/kali-defaults',
  ]
  for (const p of markers) {
    if (existsSync(p)) return { kali: true, source: 'paths', detail: p }
  }
  return { kali: false, source: null, detail: null }
}

const NAME_TO_IDS = (() => {
  const map = new Map()
  for (const t of TOOL_CATALOG) {
    for (const name of t.names) {
      const key = String(name).toLowerCase()
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(t.id)
    }
  }
  return map
})()

/**
 * 在文件夹内递归扫工具名（限深度），返回 id → 绝对路径。
 */
export function scanFolderForTools(dir, options = {}) {
  const maxDepth = Math.min(Math.max(Number(options.maxDepth) || 4, 1), 6)
  const maxFiles = Math.min(Math.max(Number(options.maxFiles) || 8000, 100), 20000)
  const root = resolve(String(dir || '').trim())
  const assigned = {}
  const hits = []
  if (!root || !existsSync(root)) {
    return { ok: false, error: "Folder not found: " + root, assigned, hits }
  }
  let st
  try { st = statSync(root) } catch {
    return { ok: false, error: "Cannot read folder: " + root, assigned, hits }
  }
  if (!st.isDirectory()) {
    return { ok: false, error: "Not a folder: " + root, assigned, hits }
  }

  let scanned = 0
  const ranks = {}
  const walk = (base, depth) => {
    if (scanned >= maxFiles || depth > maxDepth) return
    let entries
    try { entries = readdirSync(base, { withFileTypes: true }) } catch { return }
    for (const ent of entries) {
      if (scanned >= maxFiles) break
      const name = ent.name
      if (!name || name === '.' || name === '..') continue
      if (name.startsWith('.') || name === 'node_modules' || name === '.git') continue
      const full = join(base, name)
      let isDir = false
      let isFile = false
      try {
        if (typeof ent.isDirectory === 'function') {
          isDir = ent.isDirectory()
          isFile = ent.isFile()
        } else {
          const s = statSync(full)
          isDir = s.isDirectory()
          isFile = s.isFile()
        }
      } catch { continue }
      if (isDir) {
        walk(full, depth + 1)
        continue
      }
      if (!isFile) continue
      scanned += 1
      const key = name.toLowerCase()
      const ids = NAME_TO_IDS.get(key)
      if (!ids) continue
      for (const id of ids) {
        const def = TOOL_CATALOG.find((t) => t.id === id)
        if (def && def.rejectPython && looksLikePythonCli(full)) continue
        const rank = def ? def.names.findIndex((n) => n.toLowerCase() === key) : 99
        const prevRank = ranks[id] === undefined ? 99 : ranks[id]
        if (assigned[id] && rank >= prevRank) continue
        ranks[id] = rank < 0 ? 99 : rank
        assigned[id] = full
        hits.push({ id, path: full, name })
      }
    }
  }
  walk(root, 0)

  /* nuclei-templates 目录顺带认一下 */
  let nucleiTemplatesDir = ''
  const tryNuclei = [
    join(root, 'nuclei-templates'),
    join(root, 'nuclei', 'templates'),
  ]
  for (const p of tryNuclei) {
    if (existsSync(p)) {
      try {
        if (statSync(p).isDirectory()) { nucleiTemplatesDir = p; break }
      } catch { /* ignore */ }
    }
  }

  return {
    ok: true,
    dir: root,
    scanned,
    assigned,
    hits,
    nucleiTemplatesDir,
    assignedCount: Object.keys(assigned).length,
  }
}

/**
 * 把整包工具文件夹写入 config：toolkitDir + 匹配到的 tools 路径。
 */
export function assignToolkitFolder(dir, root) {
  const prev = loadPlatformConfig(root)
  if (prev.error) throw new Error(prev.error)
  const scan = scanFolderForTools(dir)
  if (!scan.ok) return Object.assign({ ok: false }, scan)
  const tools = Object.assign({}, prev.tools || {})
  for (const [id, path] of Object.entries(scan.assigned)) {
    tools[id] = path
  }
  const binDirs = Array.isArray(prev.binDirs) ? prev.binDirs.slice() : []
  if (!binDirs.includes(scan.dir)) binDirs.unshift(scan.dir)
  const patch = {
    toolkitDir: scan.dir,
    binDirs,
    tools,
    envAdaptConfigured: true,
    envAdaptSkip: false,
  }
  if (scan.nucleiTemplatesDir) patch.nucleiTemplatesDir = scan.nucleiTemplatesDir
  const cfg = savePlatformConfig(patch, root)
  const summary = platformSummary(root)
  return {
    ok: true,
    assigned: scan.assigned,
    assignedCount: scan.assignedCount,
    hits: scan.hits,
    scanned: scan.scanned,
    dir: scan.dir,
    nucleiTemplatesDir: scan.nucleiTemplatesDir || null,
    config: cfg,
    tools: summary.tools,
    adapt: summary.adapt,
  }
}

/**
 * 红队发送前环境门禁状态。
 * Kali → 直接就绪；否则需配置/已分配工具，或用户确认跳过。
 */
export function envAdaptStatus(root) {
  const cfg = loadPlatformConfig(root)
  if (cfg.error) return { ok: false, ready: false, reason: 'config-unavailable', message: cfg.error }
  const kaliInfo = detectKali()
  const tools = resolveAllTools({ root, config: cfg })
  const foundItems = tools.filter((t) => t.path)
  const missingItems = tools.filter((t) => !t.path)
  const found = foundItems.length
  const skipped = !!cfg.envAdaptSkip
  /* 只有记下的路径算已配置。单独的 envAdaptConfigured 可能是空的自动初始化。 */
  const savedPaths = !!(cfg.toolkitDir && String(cfg.toolkitDir).trim())
    || (cfg.binDirs && cfg.binDirs.length > 0)
    || TOOL_CATALOG.some((t) => cfg.tools && cfg.tools[t.id] && String(cfg.tools[t.id]).trim())

  let reason = 'need-config'
  let ready = false
  let message = ''

  if (cfg.executionTarget === 'kali') {
    const remote = kaliProbe.current()
    ready = remote.state === 'connected' && found > 0
    reason = ready ? 'kali-ssh' : 'kali-unavailable'
    message = ready ? '已连接远程 Kali ' + remote.version + '（' + remote.hostname + '，普通用户 UID ' + remote.uid + '）；找到 ' + found + '/' + tools.length + ' 个工具。缺少的工具仍不可用，不自动安装或提权。'
      : '远程 Kali 连接或工具未确认。请先启动 Kali VM，再点刷新核对；不会自动切回本机、清除主机公钥或重试执行命令。'
  } else if (kaliInfo.kali) {
    ready = true
    reason = 'kali'
    message = "Kali detected; by default the local tools are used directly (PATH / default lookup)."
  } else if (skipped) {
    ready = true
    reason = 'skipped'
    message = "You chose to skip tool setup for now; chat works normally (scanning skills may be unavailable)."
  } else if (savedPaths) {
    ready = true
    reason = 'configured'
    message = "Saved tool paths are still in place; updating the plugin will not ask you to reconfigure. Found " + found + '/' + tools.length + " tools so far."
  } else if (found >= 2) {
    ready = true
    reason = 'tools-found'
    message = "This machine already finds " + found + " tools, so it counts as ready."
  } else {
    ready = false
    reason = 'need-config'
    message = "Kali not detected and tools are not configured. Open dsh-purge → Environment setup and fill in paths or pick a whole-folder toolkit to auto-assign; you can also confirm skip-setup for now and keep chatting."
  }

  return {
    ok: true,
    ready,
    reason,
    message,
    executionTarget: cfg.executionTarget || 'local',
    kali: !!kaliInfo.kali,
    kaliSource: kaliInfo.source,
    kaliDetail: kaliInfo.detail,
    skipped,
    configured: savedPaths,
    found,
    missing: missingItems.length,
    total: tools.length,
    foundIds: foundItems.map((t) => t.id),
    missingIds: missingItems.map((t) => t.id),
  }
}

export function markEnvAdaptSkip(root, skip = true) {
  savePlatformConfig({ envAdaptSkip: !!skip }, root)
  return envAdaptStatus(root)
}

export default {
  TOOL_CATALOG,
  configPathOf,
  redteamRoot,
  loadPlatformConfig,
  savePlatformConfig,
  platformSaveResult,
  resolveTool,
  resolveAllTools,
  platformSummary,
  mergeConfigEnv,
  toolkitDirOf,
  nucleiTemplatesDirOf,
  detectKali,
  scanFolderForTools,
  assignToolkitFolder,
  envAdaptStatus,
  markEnvAdaptSkip,
}
