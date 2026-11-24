/**
 * 插件级设置（零依赖）：目前只有一项 —— **并发执行智能体上限**。
 *
 * 为什么不用环境变量：`REDTEAM_MAX_AGENTS` 只能启动前设，改完得重启 dsh web；
 * 而"同时派几个执行智能体"是使用中最常调的一项，面板上应该能直接改。
 * 所以落一份 JSON 到事实库根目录：`$DSH_HOME/redteam/settings.json`。
 *
 * 生效顺序：settings.json → 环境变量 `REDTEAM_MAX_AGENTS` → 默认 3。
 * 工具侧（redteam_agent_slot 闸门）与面板侧（「智能体」页）读的是同一份，避免两处口径漂移。
 */
import { mkdirSync, readFileSync, writeFileSync, openSync, closeSync, fsyncSync, renameSync, unlinkSync, lstatSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { join } from 'node:path'

/** 默认并发上限（用户口径：整个项目默认 3 个执行智能体）。 */
export const DEFAULT_MAX_AGENTS = 3

/** 硬上限：再多也不会更快 —— 同一个 API Key 的并发/速率限制会先到，反而扰动测试。 */
export const MAX_AGENTS_LIMIT = 10

/** 设置文件路径（跟事实库同一个根，随事实库一起备份/迁移）。 */
export function settingsPathOf(root) {
  return join(String(root || '.'), 'settings.json')
}

export function configuredLimit(raw) {
  const value = typeof raw === 'number' || (typeof raw === 'string' && /^(?:[1-9]|10)$/.test(raw)) ? Number(raw) : NaN
  if (!Number.isInteger(value) || value < 1 || value > MAX_AGENTS_LIMIT) {
    const error = new Error('并发上限必须是1到10的整数；不接受数组、布尔值或其它类型。')
    error.code = 'redteam/settings'; throw error
  }
  return value
}

/** 读全部设置（未配置才使用默认；损坏或不可读必须明确报错）。 */
export function readSettings(root) {
  try {
    let info
    try { info = lstatSync(settingsPathOf(root)) } catch (error) { if (error.code === 'ENOENT') return {}; throw error }
    if (!info.isFile() || info.isSymbolicLink()) throw new Error('设置必须是普通文件')
    const parsed = JSON.parse(readFileSync(settingsPathOf(root), 'utf8'))
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('配置应为对象')
    if (Object.hasOwn(parsed, 'maxAgents')) configuredLimit(parsed.maxAgents)
    return parsed
  } catch (cause) {
    const error = new Error('并发设置不可用：请修复 ' + settingsPathOf(root) + ' 或从备份恢复后重试。', { cause })
    error.code = 'redteam/settings'
    throw error
  }
}

/** 合并写入若干项设置，返回写入后的完整设置。 */
export function writeSettings(root, patch) {
  const next = Object.assign({}, readSettings(root), patch)
  if (Object.hasOwn(next, 'maxAgents')) configuredLimit(next.maxAgents)
  mkdirSync(String(root || '.'), { recursive: true })
  const file = settingsPathOf(root), temporary = file + '.' + randomUUID() + '.tmp'
  let created = false
  try {
    const fd = openSync(temporary, 'wx', 0o600); created = true
    try { writeFileSync(fd, JSON.stringify(next, null, 2) + '\n', 'utf8'); fsyncSync(fd) }
    finally { closeSync(fd) }
    renameSync(temporary, file)
  } finally {
    try { if (created) unlinkSync(temporary) } catch (error) { if (error.code !== 'ENOENT') throw error }
  }
  return next
}

/** 把任意输入收敛到 [1, MAX_AGENTS_LIMIT] 的整数。 */
export function clampMaxAgents(value) {
  const n = Math.floor(Number(value))
  if (!Number.isFinite(n)) return DEFAULT_MAX_AGENTS
  return Math.min(Math.max(n, 1), MAX_AGENTS_LIMIT)
}

/**
 * 当前生效的并发上限。
 * @param root - 事实库根目录（`ctx.redteam.root`）。
 * @param env - 环境变量表（便于测试注入）。
 * @returns 生效的整数上限。
 */
export function maxAgentsOf(root, env = process.env) {
  const fromFile = Number(readSettings(root).maxAgents)
  if (Number.isFinite(fromFile) && fromFile > 0) return clampMaxAgents(fromFile)
  const fromEnv = Number(env && env.REDTEAM_MAX_AGENTS)
  if (Number.isFinite(fromEnv) && fromEnv > 0) return clampMaxAgents(fromEnv)
  return DEFAULT_MAX_AGENTS
}

/** 保存并发上限，返回实际生效值。 */
export function saveMaxAgents(root, value) {
  const applied = configuredLimit(value)
  writeSettings(root, { maxAgents: applied })
  return applied
}

/** 当前设置是从哪来的（面板上要如实说明，避免"我改了没生效"的错觉）。 */
export function maxAgentsSourceOf(root, env = process.env) {
  const fromFile = Number(readSettings(root).maxAgents)
  if (Number.isFinite(fromFile) && fromFile > 0) return 'settings'
  const fromEnv = Number(env && env.REDTEAM_MAX_AGENTS)
  if (Number.isFinite(fromEnv) && fromEnv > 0) return 'env'
  return 'default'
}
