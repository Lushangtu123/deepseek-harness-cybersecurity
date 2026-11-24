import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const fsp = fs.promises;
const MAX_TREE_FILES = 20000;
const MAX_TREE_BYTES = 256 * 1024 * 1024;

async function noSymlinkAncestors(fp) {
  const absolute = path.resolve(fp);
  let current = path.parse(absolute).root;
  for (const part of absolute.slice(current.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    if ((await fsp.lstat(current)).isSymbolicLink()) {
      throw new Error(`Package update refuses symlink path: ${current}`);
    }
  }
  return absolute;
}

async function treeDigest(root) {
  const hash = createHash('sha256');
  let files = 0, bytes = 0;
  async function visit(fp, rel) {
    const st = await fsp.lstat(fp);
    if (st.isSymbolicLink()) throw new Error(`Package update refuses symlink entry: ${fp}`);
    if (++files > MAX_TREE_FILES) throw new Error('Package update tree has too many entries');
    hash.update(JSON.stringify([rel, st.mode & 0o777, st.isDirectory()]));
    if (st.isDirectory()) {
      for (const name of (await fsp.readdir(fp)).sort()) await visit(path.join(fp, name), path.join(rel, name));
    } else if (st.isFile()) {
      bytes += st.size;
      if (bytes > MAX_TREE_BYTES) throw new Error('Package update tree is too large');
      hash.update(await fsp.readFile(fp));
    } else {
      throw new Error(`Package update refuses special entry: ${fp}`);
    }
  }
  await visit(root, '');
  return hash.digest('hex');
}

function overlaps(a, b) {
  const relative = path.relative(a, b);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}

/**
 * Stage every package before changing any installed tree. Directory renames
 * expose whole versions (with a short missing-path window), never rm/cp overlays.
 * Keep the previous trees until the caller's runtime check accepts the update.
 * A process crash retains sibling backups for manual recovery; this is not a
 * crash-atomic filesystem transaction or rollback of host files patched later.
 */
export async function beginPackageUpdate(sourceRoot, destinations, names, options = {}) {
  if (!Array.isArray(names) || !names.length || names.some((n) => (
    typeof n !== 'string' || !n || n === '.' || n === '..' || path.basename(n) !== n || /[\\/]/.test(n)
  ))) throw new Error('Package update requires direct child entry names');
  const selected = [...new Set(names)];
  const source = await noSymlinkAncestors(sourceRoot);
  await treeDigest(source);
  const sourcePackage = JSON.parse(await fsp.readFile(path.join(source, 'package.json'), 'utf8'));
  if (!sourcePackage.name || !sourcePackage.version) throw new Error('Invalid update package manifest');
  if (!Array.isArray(destinations) || !destinations.length) throw new Error('No update destination');
  const targets = [];
  for (const input of destinations) {
    const dest = await noSymlinkAncestors(input);
    if (dest === path.parse(dest).root || overlaps(source, dest) || overlaps(dest, source)
        || targets.some((p) => overlaps(p, dest) || overlaps(dest, p))) {
      throw new Error('Package update source/destination overlap');
    }
    if (!(await fsp.lstat(dest)).isDirectory()) throw new Error('Update destination must be a directory');
    targets.push(dest);
  }
  const entries = [];
  const checkpoint = options.checkpoint || (async () => {});
  let closed = false;

  async function clean(entry) {
    if (entry.work) await fsp.rm(entry.work, { recursive: true, force: true });
    if (entry.locked) { await fsp.rmdir(entry.lock); entry.locked = false; }
  }

  async function rollback() {
    if (closed) return;
    const errors = [];
    for (const entry of [...entries].reverse()) {
      try {
        await noSymlinkAncestors(path.dirname(entry.dest));
        if (entry.installed) {
          await noSymlinkAncestors(entry.dest);
          await fsp.rename(entry.dest, path.join(entry.work, 'rejected'));
          entry.installed = false;
        }
        if (entry.backedUp) {
          await fsp.rename(entry.backup, entry.dest);
          entry.backedUp = false;
        }
        await clean(entry);
      } catch (error) { errors.push(error); }
    }
    if (errors.length) {
      const error = new AggregateError(errors, 'Package update rollback incomplete; preserved recovery directories');
      error.recoveryDirectories = entries.filter((p) => p.backedUp).map((p) => p.work);
      throw error;
    }
    closed = true;
  }

  try {
    for (const dest of [...targets].sort()) {
      const lock = path.join(path.dirname(dest), `.${path.basename(dest)}.personal-update.lock`);
      const entry = { dest, lock, locked: false, work: null, backedUp: false, installed: false };
      entries.push(entry);
      try { await fsp.mkdir(lock, { mode: 0o700 }); entry.locked = true; }
      catch (e) {
        if (e.code === 'EEXIST') throw new Error('Package update lock already exists; update in progress or recovery required');
        throw e;
      }
      entry.before = await treeDigest(dest);
      entry.work = await fsp.mkdtemp(path.join(path.dirname(dest), `.${path.basename(dest)}.personal-update-`));
      entry.next = path.join(entry.work, 'next');
      entry.backup = path.join(entry.work, 'previous');
      await fsp.cp(dest, entry.next, { recursive: true, dereference: false, preserveTimestamps: true });
      for (const name of selected) {
        const from = path.join(source, name), to = path.join(entry.next, name);
        try { await fsp.lstat(from); } catch (e) { if (e.code === 'ENOENT') continue; throw e; }
        await fsp.rm(to, { recursive: true, force: true });
        await fsp.cp(from, to, { recursive: true, dereference: false, preserveTimestamps: true });
      }
      await treeDigest(entry.next);
      await checkpoint({ phase: 'staged', destination: dest });
    }
    for (const entry of entries) {
      await checkpoint({ phase: 'before-backup', destination: entry.dest });
      await noSymlinkAncestors(entry.dest);
      if (await treeDigest(entry.dest) !== entry.before) throw new Error('Installed package changed during update staging');
      await fsp.rename(entry.dest, entry.backup);
      entry.backedUp = true;
      await checkpoint({ phase: 'backup-created', destination: entry.dest });
      await fsp.rename(entry.next, entry.dest);
      entry.installed = true;
      await checkpoint({ phase: 'installed', destination: entry.dest });
    }
  } catch (error) {
    try { await rollback(); } catch (recoveryError) { throw new AggregateError([error, recoveryError], recoveryError.message); }
    throw error;
  }

  return {
    rollback,
    async finalize() {
      if (closed) return { cleanupWarnings: [] };
      // Once old backups are being removed rollback is no longer safe. Cleanup
      // failure leaves the accepted new package intact and is reported separately.
      closed = true;
      const cleanupWarnings = [];
      for (const entry of entries) {
        try { await clean(entry); }
        catch (e) { cleanupWarnings.push(String(e.message || e)); }
      }
      return { cleanupWarnings };
    },
  };
}
