#!/usr/bin/env node
/**
 * Export only the report's registered attachments into a new private bundle.
 * --out is a parent directory; existing files and bundles are never replaced.
 * node scripts/export-engagement-report.mjs --engagement <id> --out ~/交付
 */
import * as fs from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { RedteamStore } from '../lib/redteam/store-core.js';

const digest = data => createHash('sha256').update(data).digest('hex');
const within = (a, b) => { const p = relative(a, b); return p === '' || (p !== '..' && !p.startsWith('..' + sep) && !p.startsWith(sep)); };
function directory(path) {
  const stat = fs.lstatSync(path);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('需要真实目录：' + path);
}
function canonicalDestination(path) {
  let parent = resolve(path); const tail = [];
  while (!fs.existsSync(parent)) {
    // A dangling symlink is not a missing directory that we may create.
    try { fs.lstatSync(parent); throw new Error('输出目录含无效链接'); } catch (e) { if (e.code !== 'ENOENT') throw e; }
    tail.unshift(basename(parent)); parent = dirname(parent);
  }
  return resolve(fs.realpathSync(parent), ...tail);
}
function writeChecked(path, data) {
  const fd = fs.openSync(path, 'wx', 0o600);
  try { fs.writeFileSync(fd, data); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  const bytes = Buffer.from(data);
  if (digest(fs.readFileSync(path)) !== digest(bytes)) throw new Error('交付文件写入校验失败：' + basename(path));
  return { bytes: bytes.length, sha256: digest(bytes) };
}
function syncDirectory(path) {
  const fd = fs.openSync(path, 'r'); try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}
function readAttachment(project, attachment) {
  const parts = String(attachment.path || '').split('/');
  if (parts.length !== 2 || parts[0] !== 'shots' || !parts[1] || /^[.]{1,2}$/.test(parts[1]) || /[\\\x00-\x1f\x7f]/.test(parts[1])) throw new Error('报告附件路径无效');
  if (!Number.isSafeInteger(attachment.bytes) || attachment.bytes < 0 || !/^[a-f0-9]{64}$/.test(attachment.sha256 || '')) throw new Error('附件缺少有效的登记摘要，请重新登记证据：' + parts[1]);
  directory(join(project, 'shots'));
  // Nonblocking open lets fstat reject named pipes without waiting for a writer.
  const fd = fs.openSync(join(project, ...parts), fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  let data;
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile()) throw new Error('附件不是普通文件：' + parts[1]);
    if (stat.size !== attachment.bytes) throw new Error('附件大小与登记记录不符：' + parts[1]);
    data = fs.readFileSync(fd);
  } finally { fs.closeSync(fd); }
  if (data.length !== attachment.bytes || digest(data) !== attachment.sha256) throw new Error('附件 SHA256 与登记记录不符：' + parts[1]);
  return data;
}

export function exportReport({ root, engagement, out = process.cwd() }) {
  root = fs.realpathSync(resolve(root)); directory(root);
  const destination = canonicalDestination(out);
  if (within(root, destination) || within(destination, root)) throw new Error('输出目录不能与 Redteam 数据目录相同、包含它或位于其中');
  let store, container, published = false;
  try {
    directory(join(root, 'engagements'));
    store = new RedteamStore(root);
    const id = engagement || store.activeEngagementId();
    if (!id || id === '.' || id === '..' || /[/\\\x00-\x1f\x7f]/.test(id)) throw new Error('请用 --engagement 指定有效项目');
    const project = join(root, 'engagements', id); directory(project);
    const db = fs.lstatSync(join(project, 'assets.db'));
    if (!db.isFile() || db.isSymbolicLink()) throw new Error('项目证据数据库无效');
    const report = store.scoreReport(id, { shotRef: 'relative' });
    if (!Array.isArray(report.attachments) || report.coverage?.markdownComplete !== true) throw new Error('报告附件清单不完整');
    const attachments = new Map();
    for (const item of report.attachments) {
      const old = attachments.get(item.path);
      if (old && (old.bytes !== item.bytes || old.sha256 !== item.sha256)) throw new Error('同名附件登记冲突：' + item.path);
      attachments.set(item.path, item);
    }
    fs.mkdirSync(destination, { recursive: true }); directory(destination);
    // mkdtemp exclusively owns this container. Publication never targets an old bundle.
    container = fs.mkdtempSync(join(destination, 'report-')); fs.chmodSync(container, 0o700);
    const stage = join(container, '.staging'), bundle = join(container, 'bundle');
    fs.mkdirSync(stage, { mode: 0o700 });
    const manifest = { schemaVersion: 1, engagement: id, createdAt: new Date().toISOString(), report: { path: 'report.md' }, attachments: [] };
    if (attachments.size) fs.mkdirSync(join(stage, 'shots'), { mode: 0o700 });
    for (const item of attachments.values()) {
      const data = readAttachment(project, item);
      const checked = writeChecked(join(stage, item.path), data);
      manifest.attachments.push({ id: item.id, path: item.path, ...checked });
    }
    Object.assign(manifest.report, writeChecked(join(stage, 'report.md'), report.markdown));
    writeChecked(join(stage, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
    if (attachments.size) syncDirectory(join(stage, 'shots'));
    syncDirectory(stage);
    fs.renameSync(stage, bundle); published = true;
    syncDirectory(container); syncDirectory(destination);
    return { bundle, manifest, summary: report.summary };
  } catch (error) {
    if (container && !published) fs.rmSync(container, { recursive: true, force: true });
    if (published) error.message += '；交付包已发布，请检查现有包后再操作：' + join(container, 'bundle');
    throw error;
  } finally { store?.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const argv = process.argv.slice(2);
  const arg = (name, fallback) => { const i = argv.indexOf('--' + name); if (i === -1) return fallback; if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error('--' + name + ' 需要参数'); return argv[i + 1]; };
  try {
    const result = exportReport({ root: process.env.REDTEAM_HOME || join(process.env.DSH_HOME || join(homedir(), '.dsh'), 'redteam'), engagement: arg('engagement'), out: arg('out', process.cwd()) });
    console.log('✓ 报告：' + join(result.bundle, 'report.md'));
    console.log('  合计 ' + result.summary.points + ' 分 · 引用附件 ' + result.manifest.attachments.length + ' 个 · 校验清单：' + join(result.bundle, 'manifest.json'));
  } catch (error) { console.error('导出失败：' + error.message); process.exitCode = 1; }
}
