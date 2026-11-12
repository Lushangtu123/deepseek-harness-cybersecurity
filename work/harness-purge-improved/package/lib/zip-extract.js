import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const HIDDEN = {
  encoding: "utf8",
  stdio: ["ignore", "pipe", "ignore"],
  windowsHide: true,
  timeout: 60000,
};

/** 各平台解压顺序。node 不调用外部命令，macOS / Linux / Windows 都能用。 */
export function unzipTools(platform = process.platform) {
  if (platform === "win32") return ["tar", "powershell", "node"];
  return ["tar", "unzip", "python3", "bsdtar", "node"];
}

function safeZipName(name) {
  const rel = String(name || "").replace(/\\/g, "/").replace(/^\.?\//, "").replace(/\/+$/, "");
  if (!rel) return "";
  if (rel.startsWith("/") || /^[A-Za-z]:/.test(rel)) throw new Error("Invalid zip path");
  const parts = rel.split("/");
  if (parts.some((part) => part === ".." || part === "")) throw new Error("Invalid zip path");
  return parts.join("/");
}

function findEocd(buf, strict = false) {
  const min = Math.max(0, buf.length - 22 - 65535);
  for (let i = buf.length - 22; i >= min; i -= 1) {
    if (buf.readUInt32LE(i) !== 0x06054b50) continue;
    if (!strict || i + 22 + buf.readUInt16LE(i + 20) === buf.length) return i;
  }
  throw new Error("Not a zip file");
}

function readZipEntries(buf, limits) {
  if (!Buffer.isBuffer(buf) || buf.length < 22) throw new Error("Not a zip file");
  const eocd = findEocd(buf, Boolean(limits));
  const total = buf.readUInt16LE(eocd + 10);
  let cursor = buf.readUInt32LE(eocd + 16);
  if (limits) {
    if (total > limits.maxEntries) throw new Error("Too many ZIP entries");
    const centralSize = buf.readUInt32LE(eocd + 12);
    if (buf.readUInt16LE(eocd + 4) || buf.readUInt16LE(eocd + 6)
        || buf.readUInt16LE(eocd + 8) !== total || cursor + centralSize !== eocd) {
      throw new Error("Corrupt or unsupported ZIP directory");
    }
  }
  const entries = [];
  for (let n = 0; n < total; n += 1) {
    if (cursor + 46 > buf.length || buf.readUInt32LE(cursor) !== 0x02014b50) {
      throw new Error("Corrupt zip central directory");
    }
    const method = buf.readUInt16LE(cursor + 10);
    const compSize = buf.readUInt32LE(cursor + 20);
    const nameLen = buf.readUInt16LE(cursor + 28);
    const extraLen = buf.readUInt16LE(cursor + 30);
    const commentLen = buf.readUInt16LE(cursor + 32);
    const localOffset = buf.readUInt32LE(cursor + 42);
    const name = buf.toString("utf8", cursor + 46, cursor + 46 + nameLen);
    const next = cursor + 46 + nameLen + extraLen + commentLen;
    if (limits && next > eocd) throw new Error("Truncated ZIP directory");
    entries.push({
      name, method, compSize, localOffset,
      flags: buf.readUInt16LE(cursor + 8),
      crc: buf.readUInt32LE(cursor + 16),
      size: buf.readUInt32LE(cursor + 24),
      type: (buf.readUInt32LE(cursor + 38) >>> 16) & 0o170000,
      rawName: buf.subarray(cursor + 46, cursor + 46 + nameLen),
    });
    cursor = next;
  }
  if (limits && cursor !== eocd) throw new Error("Corrupt ZIP directory size");
  return entries;
}

export function listZipEntries(buf) {
  return readZipEntries(buf).map((entry) => entry.name.replace(/\\/g, "/"));
}

export function listZipFile(zipPath) {
  return listZipEntries(fs.readFileSync(zipPath));
}

function localDataOffset(buf, localOffset) {
  if (localOffset + 30 > buf.length || buf.readUInt32LE(localOffset) !== 0x04034b50) {
    throw new Error("Corrupt zip local header");
  }
  const nameLen = buf.readUInt16LE(localOffset + 26);
  const extraLen = buf.readUInt16LE(localOffset + 28);
  return localOffset + 30 + nameLen + extraLen;
}

const crcTable = typeof zlib.crc32 === "function" ? null : Uint32Array.from({ length: 256 }, (_, index) => {
  let crc = index;
  for (let i = 0; i < 8; i += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  return crc;
});

function crc32(bytes) {
  if (crcTable === null) return zlib.crc32(bytes);
  let crc = 0xffffffff;
  for (const byte of bytes) crc = (crc >>> 8) ^ crcTable[(crc ^ byte) & 0xff];
  return (crc ^ 0xffffffff) >>> 0;
}

export function extractZipBuffer(buf, dest, limits) {
  fs.mkdirSync(dest, { recursive: true });
  const root = path.resolve(dest);
  const prefix = root.endsWith(path.sep) ? root : root + path.sep;
  const entries = readZipEntries(buf, limits);
  const centralStart = limits ? buf.readUInt32LE(findEocd(buf, true) + 16) : 0;
  let remaining = limits?.maxBytes;
  for (const entry of entries) {
    const directory = /[/\\]$/.test(entry.name);
    if (limits) {
      if (/^[\\/]|[:\x00-\x1f]/.test(entry.name)) throw new Error("Invalid ZIP path");
      if (entry.type && entry.type !== (directory ? 0o040000 : 0o100000)) {
        throw new Error("Unsupported ZIP entry type");
      }
      if (entry.flags & 1) throw new Error("Encrypted ZIP entries are unsupported");
    }
    const rel = safeZipName(entry.name);
    if (!rel) continue;
    const out = path.resolve(root, rel);
    if (out !== root && !out.startsWith(prefix)) throw new Error("Invalid zip path");
    if (directory && !limits) {
      fs.mkdirSync(out, { recursive: true });
      continue;
    }
    if (entry.compSize === 0xffffffff || entry.localOffset === 0xffffffff) {
      throw new Error("zip64 is not supported");
    }
    if (entry.method !== 0 && entry.method !== 8) {
      throw new Error(`Unsupported zip compression method ${entry.method}`);
    }
    const start = localDataOffset(buf, entry.localOffset);
    const end = start + entry.compSize;
    if (end > buf.length) throw new Error("Truncated zip data");
    if (limits) {
      const nameStart = entry.localOffset + 30;
      const localName = buf.subarray(nameStart, nameStart + buf.readUInt16LE(entry.localOffset + 26));
      if (end > centralStart || !localName.equals(entry.rawName)
          || buf.readUInt16LE(entry.localOffset + 6) !== entry.flags
          || buf.readUInt16LE(entry.localOffset + 8) !== entry.method) {
        throw new Error("ZIP local entry does not match its directory");
      }
      if (entry.size > remaining || (entry.method === 0 && entry.compSize > remaining)) {
        throw new Error("ZIP output exceeds size limit");
      }
    }
    const compressed = buf.subarray(start, end);
    let body = compressed;
    if (entry.method === 8) {
      try {
        body = zlib.inflateRawSync(compressed, limits ? { maxOutputLength: Math.max(1, remaining) } : undefined);
      } catch (error) {
        if (limits && error?.code === "ERR_BUFFER_TOO_LARGE") throw new Error("ZIP output exceeds size limit");
        throw error;
      }
    }
    if (limits) {
      if (body.length > remaining) throw new Error("ZIP output exceeds size limit");
      if (body.length !== entry.size || (directory && body.length)) throw new Error("Invalid ZIP entry size");
      if (crc32(body) !== entry.crc) throw new Error("ZIP CRC check failed");
      remaining -= body.length;
    }
    if (directory) fs.mkdirSync(out, { recursive: true });
    else {
      fs.mkdirSync(path.dirname(out), { recursive: true });
      fs.writeFileSync(out, body, limits ? { flag: "wx" } : undefined);
    }
  }
}

function attempt(file, args, extra = {}) {
  try {
    execFileSync(file, args, {
      ...HIDDEN,
      stdio: ["ignore", "pipe", "pipe"],
      ...extra,
    });
    return "";
  } catch (error) {
    const detail = String((error && (error.stderr || error.stdout || error.message)) || "")
      .trim()
      .split(/\r?\n/)
      .filter(Boolean)[0];
    return detail ? `${file}: ${detail}` : file;
  }
}

/** 按平台试外部工具，最后用 Node 解 zip。成功返回用到的方式。 */
export function extractZipArchive(zipPath, dest, tools = unzipTools()) {
  fs.mkdirSync(dest, { recursive: true });
  const notes = [];
  for (const tool of tools) {
    if (tool === "node") {
      try {
        extractZipBuffer(fs.readFileSync(zipPath), dest);
        return "node";
      } catch (error) {
        notes.push(`node: ${error && error.message ? error.message : error}`);
        break;
      }
    }
    if (tool === "tar" || tool === "bsdtar") {
      const note = attempt(tool, ["-xf", zipPath, "-C", dest]);
      if (!note) return tool;
      notes.push(note);
      continue;
    }
    if (tool === "unzip") {
      const note = attempt("unzip", ["-o", "-q", zipPath, "-d", dest]);
      if (!note) return "unzip";
      notes.push(note);
      continue;
    }
    if (tool === "python3") {
      const note = attempt("python3", ["-m", "zipfile", "-e", zipPath, dest]);
      if (!note) return "python3";
      notes.push(note);
      continue;
    }
    if (tool === "powershell") {
      const note = attempt(
        "powershell",
        ["-NoProfile", "-Command", "Expand-Archive -LiteralPath $env:DSH_UPD_ZIP -DestinationPath $env:DSH_UPD_DIR -Force"],
        { env: { ...process.env, DSH_UPD_ZIP: zipPath, DSH_UPD_DIR: dest } },
      );
      if (!note) return "powershell";
      notes.push(note);
    }
  }
  throw new Error(`Extraction failed: ${notes.join(" | ") || "no extractor available"}`);
}
