// Adapted from YuJunZhiXue/dsh-purge 1.1.82 profile-insert.js (#180).
// Explicit maintenance only: no insert/config injection or build-approval escalation.
import fs from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';

const digest = value => createHash('sha256').update(value).digest('hex');
const owned = key => key === 'dsh-purge' || key.startsWith('dsh-purge@');

function entry(line) {
  const match=line.match(/^([ ]+)("(?:\\.|[^"\\])*"|'(?:''|[^'])*'|.+?)\s*:\s*(true|false)\s*(?:#.*)?$/);
  if (!match) throw Error('Unsupported allowBuilds entry; original retained');
  let key=match[2].trim();
  if(key.startsWith('"')) key=JSON.parse(key);
  else if(key.startsWith("'")) key=key.slice(1,-1).replace(/''/g,"'");
  return {key,value:match[3],indent:match[1]};
}

/** Only dsh-purge keys are repaired; explicit false always wins a duplicate. */
export function rewritePnpmAllowBuilds(raw,tarball='') {
  const eol=raw.includes('\r\n')?'\r\n':'\n',lines=raw.split(/\r?\n/),top=new Set();
  let start=-1,end=lines.length;
  for(let i=0;i<lines.length;i++) {
    const key=lines[i].match(/^([\w-]+)\s*:/);
    if(!key) continue;
    if(top.has(key[1])) throw Error('Duplicate top-level configuration; original retained');
    top.add(key[1]);
    if(key[1]==='allowBuilds') {
      if(!/^allowBuilds\s*:\s*(?:#.*)?$/.test(lines[i])) throw Error('Unsupported allowBuilds mapping');
      start=i;
    } else if(start>=0 && end===lines.length) end=i;
  }
  if(start<0) return raw;
  const rows=[];const unrelated=new Set();let indent;
  for(let i=start+1;i<end;i++) {
    if(!lines[i].trim() || lines[i].trimStart().startsWith('#')) continue;
    const row={...entry(lines[i]),index:i};
    if(indent && row.indent!==indent) throw Error('Nested allowBuilds mapping is not repaired');
    indent=row.indent;
    if(!owned(row.key)) {
      if(unrelated.has(row.key)) throw Error('Duplicate unrelated build entry; original retained');
      unrelated.add(row.key);
    }
    rows.push(row);
  }
  const purge=rows.filter(row=>owned(row.key));
  if(!purge.length) return raw;
  const desired=new Map();
  const bare=purge.filter(row=>row.key==='dsh-purge');
  if(bare.length) desired.set('dsh-purge',bare.some(row=>row.value==='false')?'false':'true');
  const urls=purge.filter(row=>row.key!=='dsh-purge');
  if(tarball && urls.length) desired.set('dsh-purge@'+tarball,urls.some(row=>row.value==='false')?'false':'true');
  if(purge.length===desired.size && purge.every(row=>desired.get(row.key)===row.value) && new Set(purge.map(row=>row.key)).size===purge.length) return raw;
  const indices=new Set(purge.map(row=>row.index)),replacement=[...desired].map(([key,value])=>`${indent||'  '}${key.includes('://')?JSON.stringify(key):key}: ${value}`);
  const next=[];
  for(let i=0;i<lines.length;i++) {
    if(i===purge[0].index) next.push(...replacement);
    if(!indices.has(i)) next.push(lines[i]);
  }
  return next.join(eol);
}

function safeFile(file) {
  const info=fs.lstatSync(file);
  if(!info.isFile() || info.nlink!==1 || fs.realpathSync(file)!==path.resolve(file)) throw Error('Unsafe or symbolic configuration path');
  if(info.size>2*1024*1024) throw Error('Configuration is too large');
  return info;
}

function tarballFor(profile,pkg) {
  const spec=pkg.dependencies?.['dsh-purge'];
  if(typeof spec!=='string') throw Error('Profile does not own dsh-purge');
  if(/^(?:file:|link:)/.test(spec)) return '';
  const lock=path.join(profile,'pnpm-lock.yaml');
  let raw='';
  try {safeFile(lock);raw=fs.readFileSync(lock,'utf8');} catch(error) {if(error.code!=='ENOENT') throw error;}
  const lines=raw.split(/\r?\n/);let inImporters=false;
  for(let i=0;i<lines.length;i++) {
    if(/^\S/.test(lines[i])) {if(inImporters) break;inImporters=/^importers\s*:/.test(lines[i]);}
    if(!inImporters) continue;
    const m=lines[i].match(/^(\s+)dsh-purge\s*:\s*$/);if(!m) continue;
    let version='',specifier='';
    for(let j=i+1;j<lines.length;j++) {
      if(lines[j].trim() && lines[j].search(/\S/)<=m[1].length) break;
      const part=lines[j].match(/^\s+(version|specifier)\s*:\s*(.*)$/);
      if(part) {if(part[1]==='version') version=part[2];else specifier=part[2];}
    }
    for(const value of [version,specifier]) {const url=value.match(/https?:\/\/[^\s'"()]+/);if(url) return url[0];}
    break;
  }
  return /^https?:\/\//.test(spec)?spec:'';
}

export function repairProfilePnpm(profileDir,{apply=false}={}) {
  if(typeof apply!=='boolean') throw Error('Explicit boolean apply required');
  const profile=path.resolve(profileDir);
  if(fs.lstatSync(profile).isSymbolicLink() || fs.realpathSync(profile)!==profile) throw Error('Unsafe or symbolic profile');
  const packageFile=path.join(profile,'package.json');safeFile(packageFile);
  const pkg=JSON.parse(fs.readFileSync(packageFile,'utf8'));
  if(pkg.name!=='dsh-profile-web') throw Error('Only the selected web profile can be repaired');
  const file=path.join(profile,'pnpm-workspace.yaml');
  const result={ok:true,profile:'web',changed:false,wrote:false,dryRun:!apply,beforeSha256:null,afterSha256:null};
  let info;
  try {info=safeFile(file);} catch(error) {if(error.code==='ENOENT') return {...result,reason:'missing'};throw error;}
  const raw=fs.readFileSync(file,'utf8'),next=rewritePnpmAllowBuilds(raw,tarballFor(profile,pkg));
  Object.assign(result,{changed:next!==raw,beforeSha256:digest(raw),afterSha256:digest(next)});
  if(!result.changed || !apply) return result;
  const stamp=randomUUID(),backup=path.join(profile,`.pnpm-workspace.before-dsh-purge.${stamp}.bak`),temporary=path.join(profile,`.pnpm-repair-${stamp}`);
  fs.writeFileSync(backup,raw,{encoding:'utf8',flag:'wx',mode:0o600});
  try {
    const fd=fs.openSync(temporary,'wx',info.mode&0o777);
    try {fs.fchmodSync(fd,info.mode&0o777);fs.writeFileSync(fd,next,'utf8');fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
    const latest=safeFile(file);
    if(latest.ino!==info.ino || latest.mtimeMs!==info.mtimeMs || digest(fs.readFileSync(file))!==result.beforeSha256) throw Error('Configuration changed during repair; original retained');
    fs.renameSync(temporary,file);
    if(digest(fs.readFileSync(file))!==result.afterSha256) throw Error('Repair result unconfirmed; backup retained');
  } finally {try {fs.unlinkSync(temporary);} catch(error) {if(error.code!=='ENOENT') throw error;}}
  return {...result,wrote:true,backup};
}
