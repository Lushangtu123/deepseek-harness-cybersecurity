import fs, { promises as fsp } from "node:fs";
import path from "node:path";
import {randomUUID} from "node:crypto";
import {DatabaseSync} from "node:sqlite";
import {
  findDshHome,
  defaultOverrideText,
  hangOperatorPrompt,
  hungOperatorPrompt,
  normalizeOverride,
  peekCommittedOverride,
  readPromptInjectFileSync,
  hashOverride,
  defaultOverrideHash,
  atomicWriteFile,
  atomicCopyFile,
} from "./core.js";

const RULE_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/;
const MAX_RULE_BYTES = 256 * 1024;
const MAX_NAME_LENGTH = 64;
export const RULE_TARGETS = ["AGENTS.md", "CLAUDE.md"];
const BACKUP_SUFFIX = ".dsh-purge-rule.bak";
const ruleMutations = new Map();
const JOURNAL_LIMIT = 12 * 1024 * 1024;
const journalPath = home => path.join(rulesDir(home), ".transaction.json");
const recoveryError = () => Object.assign(new Error("规则事务未确认，请先恢复上次规则事务再继续。"), { code: "RULE_RECOVERY_REQUIRED" });
function serializeRules(home, action) {
  const key = path.resolve(home), previous = ruleMutations.get(key) || Promise.resolve();
  const result = previous.then(action, action), tail = result.catch(() => {});
  ruleMutations.set(key, tail);
  tail.then(() => { if (ruleMutations.get(key) === tail) ruleMutations.delete(key); });
  return result;
}
function lockedRules(home, action) {
  return serializeRules(home, async () => {
    await fsp.mkdir(rulesDir(home), { recursive: true });
    const file = path.join(rulesDir(home), ".transaction-lock.db");
    const fd = fs.openSync(file, fs.constants.O_CREAT | fs.constants.O_RDWR | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK, 0o600);
    try { const st = fs.fstatSync(fd); if (!st.isFile() || st.nlink !== 1 || st.mode & 0o077 || st.uid !== process.getuid()) throw recoveryError(); }
    finally { fs.closeSync(fd); }
    const lock = new DatabaseSync(file);
    try {
      try { lock.exec("PRAGMA busy_timeout=0;BEGIN IMMEDIATE"); }
      catch { throw Object.assign(new Error("规则事务正在由其他进程处理或锁不可用，请稍后核对。"), { code: "RULE_TRANSACTION_BUSY" }); }
      return await action();
    } finally { try { lock.exec("ROLLBACK"); } catch {} lock.close(); }
  });
}
function transactionNames(id) {
  return [...RULE_TARGETS.flatMap(name => [name, name + BACKUP_SUFFIX]),
    ...(id === null ? [] : [`rules/${id}.md`, `rules/${id}.json`]), "rules/state.json"];
}
async function beforeFile(file, limit = 1048576) {
  let handle;
  try {
    handle = await fsp.open(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
    const stat = await handle.stat();
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > limit) throw recoveryError();
    const bytes = await handle.readFile();
    if (bytes.length !== stat.size || bytes.length > limit) throw recoveryError();
    return { bytes: bytes.toString("base64"), mode: stat.mode & 0o777 };
  } catch (error) { if (error.code === "ENOENT") return null; throw error; }
  finally { await handle?.close(); }
}
async function readJournal(home) {
  const file = await beforeFile(journalPath(home), JOURNAL_LIMIT);
  if (!file) return null;
  let journal; try { journal = JSON.parse(Buffer.from(file.bytes, "base64").toString("utf8")); } catch { throw recoveryError(); }
  if (!journal || journal.version !== 1 || !["capturing", "prepared"].includes(journal.phase)
      || !Number.isSafeInteger(journal.pid) || journal.pid < 1
      || typeof journal.transactionId !== "string" || !/^[a-f0-9-]{36}$/.test(journal.transactionId)
      || journal.id !== null && !validRuleId(journal.id)) throw recoveryError();
  if (journal.phase === "prepared") {
    const names = transactionNames(journal.id);
    if (!Array.isArray(journal.files) || journal.files.length !== names.length) throw recoveryError();
    for (let i = 0; i < names.length; i++) {
      const item = journal.files[i];
      if (!item || item.path !== names[i]) throw recoveryError();
      const old = item.before;
      if (old !== null && (!old || typeof old.bytes !== "string" || !Number.isInteger(old.mode) || old.mode < 0 || old.mode > 0o777
          || Buffer.from(old.bytes, "base64").length > 1048576 || Buffer.from(old.bytes, "base64").toString("base64") !== old.bytes)) throw recoveryError();
    }
  }
  return journal;
}
async function restoreJournal(home, journal) {
  let failed = false;
  for (const item of journal.files) {
    const file = path.join(home, item.path);
    try {
      if (item.before === null) { try { await fsp.unlink(file); } catch (error) { if (error.code !== "ENOENT") throw error; } }
      else { await atomicWriteFile(file, Buffer.from(item.before.bytes, "base64")); await fsp.chmod(file, item.before.mode); }
    } catch { failed = true; }
  }
  if (failed) throw recoveryError();
}
function withRuleTransaction(home, id, action) {
  return lockedRules(home, async () => {
    if (id !== null && !validRuleId(id)) throw new Error(`invalid rule id: ${id}`);
    await fsp.mkdir(rulesDir(home), { recursive: true });
    const journal = { version: 1, phase: "capturing", id, transactionId: randomUUID(), pid: process.pid };
    try { await fsp.writeFile(journalPath(home), JSON.stringify(journal), { flag: "wx", mode: 0o600 }); }
    catch (error) { if (error.code === "EEXIST") throw recoveryError(); throw error; }
    let prepared = false;
    try {
      journal.files = [];
      for (const name of transactionNames(id)) journal.files.push({ path: name, before: await beforeFile(path.join(home, name)) });
      journal.phase = "prepared";
      await atomicWriteFile(journalPath(home), JSON.stringify(journal)); prepared = true;
      const result = await action();
      await fsp.unlink(journalPath(home));
      return result;
    } catch (error) {
      if (prepared) { try { await restoreJournal(home, journal); } catch { throw recoveryError(); } }
      try { await fsp.unlink(journalPath(home)); } catch { throw recoveryError(); }
      throw error;
    }
  });
}
export function recoverRuleTransaction(home, expectedId) {
  return lockedRules(home, async () => {
    const journal = await readJournal(home);
    if (!journal) return { recovered: false };
    if (expectedId !== undefined && expectedId !== journal.transactionId) throw recoveryError();
    if (journal.phase === "prepared") await restoreJournal(home, journal);
    await fsp.unlink(journalPath(home));
    return { recovered: true };
  });
}

// CWD 规则:扫 cwd → projectRoot 范围内的工作区指令文件,给 UI 展示并允许勾选参与注入。
// 命中与 @deepseek-ai/dsh-agent-instructions 的默认候选保持一致。
const CWD_CANDIDATE_FILES = ["AGENTS.md", "CLAUDE.md", "AGENTS.local.md", "CLAUDE.local.md"];
const PROJECT_ROOT_MARKERS = [".git", ".hg", ".svn"];
export const WORKSPACE_POLICIES = ["fallback", "strict", "always"];
const DEFAULT_WORKSPACE_POLICY = "fallback";
const MAX_CWD_WALK_DEPTH = 32;
const MAX_LOCAL_INJECT_BYTES = 512 * 1024;

export { findDshHome };

function purgeStateDir(dshHome) {
  return path.join(dshHome, "dsh-purge");
}

function cwdSelectionsPath(dshHome) {
  return path.join(purgeStateDir(dshHome), "cwd-selections.json");
}

function workspacePolicyPath(dshHome) {
  return path.join(purgeStateDir(dshHome), "workspace-policy.json");
}

function lastCwdPath(dshHome) {
  return path.join(purgeStateDir(dshHome), "last-cwd.txt");
}

export function rulesDir(dshHome) {
  return path.join(dshHome, "rules");
}

export function stateFile(dshHome) {
  return path.join(rulesDir(dshHome), "state.json");
}

export function rulePath(dshHome, id) {
  return path.join(rulesDir(dshHome), id + ".md");
}

export function ruleMetaPath(dshHome, id) {
  return path.join(rulesDir(dshHome), id + ".json");
}

export function validRuleId(id) {
  return typeof id === "string" && RULE_ID_RE.test(id);
}

export function validTarget(target) {
  return typeof target === "string" && RULE_TARGETS.includes(target);
}

export function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  return `${kb >= 100 ? Math.round(kb) : kb.toFixed(1)} KB`;
}

export function targetPath(dshHome, target) {
  if (!validTarget(target)) throw new Error(`invalid target: ${target}`);
  return path.join(dshHome, target);
}

export function normalizeMeta(id, meta) {
  const name =
    typeof meta?.name === "string" && meta.name.trim()
      ? meta.name.trim().slice(0, MAX_NAME_LENGTH)
      : id;
  const target = validTarget(meta?.target) ? meta.target : "AGENTS.md";
  return { name, target };
}

export async function readRuleMeta(dshHome, id) {
  try {
    const parsed = JSON.parse(await fsp.readFile(ruleMetaPath(dshHome, id), "utf8"));
    return normalizeMeta(id, parsed);
  } catch {
    return normalizeMeta(id, null);
  }
}

async function writeRuleMetaBody(dshHome, id, meta) {
  if (!validRuleId(id)) throw new Error(`invalid rule id: ${id}`);
  await fsp.mkdir(rulesDir(dshHome), { recursive: true });
  await atomicWriteFile(ruleMetaPath(dshHome, id), JSON.stringify(normalizeMeta(id, meta), null, 2));
}

function readRuleContentSync(dshHome, id) {
  try {
    return fs.readFileSync(rulePath(dshHome, id), "utf8");
  } catch {
    return null;
  }
}

async function collectRuleContents(dshHome) {
  const listed = await listRules(dshHome);
  const contents = new Set();
  for (const r of listed) {
    const c = readRuleContentSync(dshHome, r.id);
    if (c !== null) contents.add(c);
  }
  return contents;
}

export async function listRules(dshHome) {
  const dir = rulesDir(dshHome);
  const out = [];
  try {
    const entries = await fsp.readdir(dir, { withFileTypes: true });
    for (const e of entries) {
      if (!e.isFile() || !e.name.endsWith(".md")) continue;
      const id = e.name.slice(0, -3);
      if (!validRuleId(id)) continue;
      let size = 0;
      try {
        size = (await fsp.stat(path.join(dir, e.name))).size;
      } catch {
      }
      const meta = await readRuleMeta(dshHome, id);
      out.push({ id, name: meta.name, target: meta.target, size });
    }
  } catch {
    // rules 目录不存在时按空列表返回
  }
  out.sort((a, b) => a.id.localeCompare(b.id));
  return out;
}

export async function readRule(dshHome, id) {
  if (!validRuleId(id)) throw new Error(`invalid rule id: ${id}`);
  try {
    return await fsp.readFile(rulePath(dshHome, id), "utf8");
  } catch {
    return null;
  }
}

export async function saveRule(dshHome, id, content, meta) {
  if (!validRuleId(id)) throw new Error(`invalid rule id: ${id}`);
  if (Buffer.byteLength(content, "utf8") > MAX_RULE_BYTES) throw new Error("rule too large (max 256KB)");
  return withRuleTransaction(dshHome, id, async () => {
    await atomicWriteFile(rulePath(dshHome, id), content);
    await writeRuleMetaBody(dshHome, id, meta);
    if ((await readActive(dshHome)) === id) await activateRuleBody(dshHome, id);
  });
}

export function writeRuleMeta(dshHome, id, meta) {
  return withRuleTransaction(dshHome, id, () => writeRuleMetaBody(dshHome, id, meta));
}

async function deleteRuleBody(dshHome, id) {
  if (!validRuleId(id)) throw new Error(`invalid rule id: ${id}`);
  try {
    await fsp.unlink(rulePath(dshHome, id));
  } catch (e) {
    if (e.code !== "ENOENT") throw e;
  }
  try {
    await fsp.unlink(ruleMetaPath(dshHome, id));
  } catch (e) {
    if (e.code !== "ENOENT") throw e;
  }
  if ((await readActive(dshHome)) === id) {
    try {
      await fsp.unlink(stateFile(dshHome));
    } catch (error) { if (error.code !== "ENOENT") throw error;
    }
  }
}

export async function readActive(dshHome) {
  try {
    const parsed = JSON.parse(await fsp.readFile(stateFile(dshHome), "utf8"));
    return typeof parsed?.active === "string" && validRuleId(parsed.active) ? parsed.active : null;
  } catch {
    return null;
  }
}

async function setActiveBody(dshHome, id) {
  if (!validRuleId(id)) throw new Error(`invalid rule id: ${id}`);
  await fsp.mkdir(rulesDir(dshHome), { recursive: true });
  await atomicWriteFile(stateFile(dshHome), JSON.stringify({ active: id }, null, 2));
}

/**
 * 本进程框内提交 > $DSH_HOME/prompt-inject.md > 加密槽。
 * 规则集只改 agents 目标文件，不参与 system 注入链（#74 磁盘与 UI/注入一致）。
 */
export function resolveInjectText(dshHome) {
  const home = path.normalize(String(dshHome || findDshHome() || ""));
  const pinned = peekCommittedOverride(home);
  if (typeof pinned === "string" && normalizeOverride(pinned)) {
    return { text: normalizeOverride(pinned), source: "prompt", ruleId: null };
  }
  const diskNorm = normalizeOverride(readPromptInjectFileSync(home));
  if (diskNorm) {
    const source = hashOverride(diskNorm) === defaultOverrideHash() ? "default" : "prompt";
    return { text: diskNorm, source, ruleId: null };
  }
  const bundled = normalizeOverride(defaultOverrideText());
  if (bundled) return { text: bundled, source: "default", ruleId: null };
  return { text: "", source: "none", ruleId: null };
}

/** 组装前挂上操作者正文（prompt-inject.md / 框内提交 / 加密槽）。 */
export function ensureOperatorBody(dshHome) {
  const resolved = resolveInjectText(dshHome);
  if (resolved.text) hangOperatorPrompt(resolved.text);
  return resolved.text || normalizeOverride(hungOperatorPrompt()) || "";
}

async function activateRuleBody(dshHome, id) {
  const content = await readRule(dshHome, id);
  if (content === null) throw new Error(`rule not found: ${id}`);
  const meta = await readRuleMeta(dshHome, id);
  const target = targetPath(dshHome, meta.target);
  const backup = `${target}${BACKUP_SUFFIX}`;
  if (!fs.existsSync(backup)) {
    try {
      const existing = await fsp.readFile(target, "utf8");
      const ruleContents = await collectRuleContents(dshHome);
      if (!ruleContents.has(existing)) {
        await atomicCopyFile(target, backup);
      }
    } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  await atomicWriteFile(target, content);
  await setActiveBody(dshHome, id);
  return meta;
}

export function activateRule(dshHome, id) { return withRuleTransaction(dshHome, id, () => activateRuleBody(dshHome, id)); }
export function setActive(dshHome, id) { return withRuleTransaction(dshHome, id, () => setActiveBody(dshHome, id)); }
export function deleteRule(dshHome, id) { return withRuleTransaction(dshHome, id, () => deleteRuleBody(dshHome, id)); }
export function resetToOriginal(dshHome) { return withRuleTransaction(dshHome, null, () => resetToOriginalBody(dshHome)); }

export async function ensureInitialState(dshHome) {
  if (await readJournal(dshHome)) throw recoveryError();
  const listed = await listRules(dshHome);
  let active = await readActive(dshHome);
  if (active !== null && !listed.some((r) => r.id === active)) {
    try {
      await fsp.unlink(stateFile(dshHome));
    } catch {
    }
    active = null;
  }
  return { active };
}

async function resetToOriginalBody(dshHome) {
  const active = await readActive(dshHome);
  const removed = [];
  const skipped = [];
  const restored = [];

  for (const target of RULE_TARGETS) {
    const fp = targetPath(dshHome, target);
    const bak = `${fp}${BACKUP_SUFFIX}`;
    if (!fs.existsSync(bak)) continue;
    try {
      await atomicCopyFile(bak, fp);
      await fsp.unlink(bak);
      restored.push(fp);
    } catch (error) { throw error; }
  }

  if (active !== null) {
    const meta = await readRuleMeta(dshHome, active);
    const fp = targetPath(dshHome, meta.target);
    if (!restored.includes(fp)) {
      const ruleContent = await readRule(dshHome, active);
      try {
        const fileContent = await fsp.readFile(fp, "utf8");
        if (ruleContent !== null && fileContent === ruleContent) {
          await fsp.unlink(fp);
          removed.push(fp);
        } else {
          skipped.push(fp);
        }
      } catch (error) { if (error.code !== "ENOENT") throw error; }
    }
  }
  try {
    await fsp.unlink(stateFile(dshHome));
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  return { removed, skipped, restored };
}

export async function rulesStatus(dshHome, cwdHint) {
  const listed = await listRules(dshHome);
  const active = await readActive(dshHome);
  let active_target = null;
  let agents_exists = false;
  let agents_synced = false;
  let agents_path = targetPath(dshHome, "AGENTS.md");
  if (active !== null) {
    const meta = await readRuleMeta(dshHome, active);
    active_target = meta.target;
    agents_path = targetPath(dshHome, meta.target);
    try {
      const content = await fsp.readFile(agents_path, "utf8");
      agents_exists = true;
      const ruleContent = await readRule(dshHome, active);
      agents_synced = ruleContent !== null && ruleContent === content;
    } catch {
    }
  }
  const inject = resolveInjectText(dshHome);
  const cwd = pickCwd(dshHome, cwdHint);
  const cwdCandidates = cwd ? scanCwdInstructions(cwd) : [];
  const selections = readCwdSelections(dshHome);
  const workspacePolicy = readWorkspacePolicy(dshHome);
  let recoveryRequired = false, recoveryId = null;
  try { const journal = await readJournal(dshHome); recoveryRequired = journal !== null; recoveryId = journal?.transactionId ?? null; } catch { recoveryRequired = true; }
  if (recoveryRequired) agents_synced = false;
  return {
    recoveryRequired,
    recoveryId,
    rules: listed,
    active,
    injectSource: inject.source,
    injectRuleId: inject.ruleId,
    active_target,
    agents_exists,
    agents_synced,
    agents_path,
    rules_dir: rulesDir(dshHome),
    cwd,
    cwd_candidates: cwdCandidates.map((item) => ({
      ...item,
      selected: selections.includes(item.path),
    })),
    cwd_selections: selections,
    workspace_policy: workspacePolicy,
    workspace_policies: [...WORKSPACE_POLICIES],
  };
}

function pickCwd(dshHome, cwdHint) {
  const hint = typeof cwdHint === "string" ? cwdHint.trim() : "";
  if (hint) return path.resolve(hint);
  const last = readLastCwd(dshHome);
  return last ? path.resolve(last) : "";
}

/**
 * 向上走若干层,把 cwd 自身也算一层;遇到 .git/.hg/.svn 这类根标记就停住。
 * dsh-agent-instructions 的 findProjectRoot 用类似做法。没找到 root 就只扫 cwd 这一层。
 */
export function ancestorChainForCwd(cwd) {
  if (!cwd) return [];
  const normalized = path.resolve(cwd);
  let root = null;
  let cur = normalized;
  for (let i = 0; i < MAX_CWD_WALK_DEPTH; i += 1) {
    for (const marker of PROJECT_ROOT_MARKERS) {
      try {
        if (fs.existsSync(path.join(cur, marker))) { root = cur; break; }
      } catch { /* ignore */ }
    }
    if (root) break;
    const parent = path.dirname(cur);
    if (!parent || parent === cur) break;
    cur = parent;
  }
  const chain = [];
  const pushed = new Set();
  const stopAt = root ? path.resolve(root) : normalized;
  let walker = normalized;
  for (let i = 0; i < MAX_CWD_WALK_DEPTH; i += 1) {
    if (!pushed.has(walker)) { chain.push(walker); pushed.add(walker); }
    if (walker === stopAt) break;
    const parent = path.dirname(walker);
    if (!parent || parent === walker) break;
    walker = parent;
  }
  return chain.reverse();
}

export function scanCwdInstructions(cwd) {
  const out = [];
  if (!cwd) return out;
  const chain = ancestorChainForCwd(cwd);
  const seen = new Set();
  const leaf = path.resolve(cwd);
  for (const dir of chain) {
    for (const name of CWD_CANDIDATE_FILES) {
      const fp = path.join(dir, name);
      if (seen.has(fp)) continue;
      let stat = null;
      try { stat = fs.statSync(fp); } catch { continue; }
      if (!stat.isFile()) continue;
      seen.add(fp);
      let preview = "";
      try {
        const raw = fs.readFileSync(fp, "utf8");
        preview = raw.replace(/\s+/g, " ").trim().slice(0, 160);
      } catch { /* ignore */ }
      const scope = dir === leaf ? "cwd" : (dir === chain[0] ? "root" : "ancestor");
      out.push({
        path: fp,
        name,
        dir,
        scope,
        size: stat.size,
        mtime: stat.mtimeMs || stat.mtime?.getTime?.() || 0,
        preview,
      });
    }
  }
  return out;
}

export function readWorkspacePolicy(dshHome) {
  try {
    const parsed = JSON.parse(fs.readFileSync(workspacePolicyPath(dshHome), "utf8"));
    const policy = parsed?.policy;
    if (typeof policy === "string" && WORKSPACE_POLICIES.includes(policy)) return policy;
  } catch { /* ignore */ }
  return DEFAULT_WORKSPACE_POLICY;
}

export async function writeWorkspacePolicy(dshHome, policy) {
  if (!WORKSPACE_POLICIES.includes(policy)) {
    throw new Error(`invalid workspace policy: ${policy}`);
  }
  const fp = workspacePolicyPath(dshHome);
  await fsp.mkdir(path.dirname(fp), { recursive: true });
  await atomicWriteFile(fp, JSON.stringify({ policy }, null, 2));
  return policy;
}

function normalizeSelectionList(input) {
  const out = [];
  const seen = new Set();
  for (const raw of Array.isArray(input) ? input : []) {
    if (typeof raw !== "string") continue;
    const trimmed = raw.trim();
    if (!trimmed) continue;
    const abs = path.resolve(trimmed);
    if (seen.has(abs)) continue;
    seen.add(abs);
    out.push(abs);
  }
  return out;
}

export function readCwdSelections(dshHome) {
  try {
    const parsed = JSON.parse(fs.readFileSync(cwdSelectionsPath(dshHome), "utf8"));
    return normalizeSelectionList(parsed?.paths);
  } catch { return []; }
}

export async function writeCwdSelections(dshHome, paths) {
  const unique = normalizeSelectionList(paths);
  const fp = cwdSelectionsPath(dshHome);
  await fsp.mkdir(path.dirname(fp), { recursive: true });
  await atomicWriteFile(fp, JSON.stringify({ paths: unique }, null, 2));
  return unique;
}

export async function toggleCwdSelection(dshHome, filePath, enabled) {
  if (typeof filePath !== "string" || !filePath.trim()) throw new Error("invalid file path");
  const abs = path.resolve(filePath.trim());
  const current = readCwdSelections(dshHome);
  const set = new Set(current);
  if (enabled) set.add(abs); else set.delete(abs);
  return writeCwdSelections(dshHome, Array.from(set));
}

export function readLastCwd(dshHome) {
  try {
    const txt = fs.readFileSync(lastCwdPath(dshHome), "utf8").trim();
    return txt || "";
  } catch { return ""; }
}

export function writeLastCwd(dshHome, cwd) {
  if (typeof cwd !== "string" || !cwd.trim()) return;
  try {
    const fp = lastCwdPath(dshHome);
    fs.mkdirSync(path.dirname(fp), { recursive: true });
    fs.writeFileSync(fp, cwd.trim(), "utf8");
  } catch { /* ignore */ }
}

/**
 * 返回勾选的本地指令文件拼接内容。仅当文件仍在当前 cwd 的扫描结果里才会被用上,
 * 避免切换目录后旧勾选跨目录穿越注入;超出 512KB 的内容会被截断。
 */
export function readSelectedCwdInject(dshHome, cwd) {
  const selections = readCwdSelections(dshHome);
  if (selections.length === 0) return "";
  const candidates = cwd ? scanCwdInstructions(cwd) : [];
  const candidateSet = new Set(candidates.map((c) => c.path));
  const chosen = selections.filter((p) => candidateSet.has(p));
  if (chosen.length === 0) return "";
  const parts = [];
  let total = 0;
  for (const fp of chosen) {
    let text = "";
    try {
      text = fs.readFileSync(fp, "utf8").trim();
    } catch { continue; }
    if (!text) continue;
    const header = `<!-- dsh-purge:cwd-rule ${path.basename(fp)} -->`;
    const block = `${header}\n${text}`;
    total += Buffer.byteLength(block, "utf8");
    if (total > MAX_LOCAL_INJECT_BYTES) break;
    parts.push(block);
  }
  return parts.join("\n\n---\n\n");
}
