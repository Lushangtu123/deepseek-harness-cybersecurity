import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const target=new URL('../package/lib/personal-pnpm-repair.mjs',import.meta.url);
async function api(){const mod=fs.existsSync(target)?await import(target.href):{};assert.equal(typeof mod.repairProfilePnpm,'function','Explicit pnpm repair API missing');return mod;}
function fixture(t,spec='file:/synthetic/personal-package'){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'dsh-pnpm-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const profile=path.join(root,'profiles/web');fs.mkdirSync(profile,{recursive:true});fs.writeFileSync(path.join(profile,'package.json'),JSON.stringify({name:'dsh-profile-web',dependencies:{'dsh-purge':spec}}));return {root,profile,file:path.join(profile,'pnpm-workspace.yaml')};
}
const url='https://codeload.github.com/YuJunZhiXue/dsh-purge/tar.gz/fixed-commit';
test('repairs truncated and stale URL keys using the resolved lock URL, retaining unrelated choices',async t=>{
 const mod=await api(),f=fixture(t,'github:YuJunZhiXue/dsh-purge#fixed-commit');fs.writeFileSync(path.join(f.profile,'pnpm-lock.yaml'),`importers:\n  .:\n    dependencies:\n      dsh-purge:\n        specifier: github:YuJunZhiXue/dsh-purge#fixed-commit\n        version: ${url}\n`);
 fs.writeFileSync(f.file,'allowBuilds:\n  dsh-purge: true\n  dsh-purge@https: true\n  dsh-purge@https://old.invalid/master: true\n  other-plugin: false\n', {mode:0o600});
 const before=fs.readFileSync(f.file,'utf8');const preview=mod.repairProfilePnpm(f.profile);assert.equal(preview.changed,true);assert.equal(preview.wrote,false);assert.equal(fs.readFileSync(f.file,'utf8'),before);
 const result=mod.repairProfilePnpm(f.profile,{apply:true});assert.equal(result.wrote,true);const after=fs.readFileSync(f.file,'utf8');assert.ok(after.includes(JSON.stringify('dsh-purge@'+url)));assert.match(after,/other-plugin: false/);assert.doesNotMatch(after,/old.invalid|dsh-purge@https: /);assert.equal(fs.statSync(f.file).mode&0o777,0o600);assert.equal(fs.readFileSync(result.backup,'utf8'),before);
 const st=fs.statSync(f.file);assert.equal(mod.repairProfilePnpm(f.profile,{apply:true}).wrote,false);assert.equal(fs.statSync(f.file).mtimeMs,st.mtimeMs);
});
test('local personal install never adds an upstream tarball build permission and retains explicit false',async t=>{
 const mod=await api(),f=fixture(t);fs.writeFileSync(f.file,'allowBuilds:\n  dsh-purge: false\n  dsh-purge@https: true\n');mod.repairProfilePnpm(f.profile,{apply:true});assert.equal(fs.readFileSync(f.file,'utf8'),'allowBuilds:\n  dsh-purge: false\n');
});
test('missing workspace is a no-op, without inventing configuration or build approval',async t=>{
 const mod=await api(),f=fixture(t);const result=mod.repairProfilePnpm(f.profile,{apply:true});assert.equal(result.wrote,false);assert.equal(result.changed,false);assert.equal(fs.existsSync(f.file),false);
});
test('healthy file and unrelated profile bytes remain untouched',async t=>{
 const mod=await api(),f=fixture(t);const text='packages:\n  - .\n\nallowBuilds:\n  dsh-purge: false\n  another: true\n';fs.writeFileSync(f.file,text);const unrelated=path.join(f.root,'other-profile');fs.mkdirSync(unrelated);fs.writeFileSync(path.join(unrelated,'pnpm-workspace.yaml'),'untouched');const st=fs.statSync(f.file);assert.equal(mod.repairProfilePnpm(f.profile,{apply:true}).wrote,false);assert.equal(fs.statSync(f.file).mtimeMs,st.mtimeMs);assert.equal(fs.readFileSync(f.file,'utf8'),text);assert.equal(fs.readFileSync(path.join(unrelated,'pnpm-workspace.yaml'),'utf8'),'untouched');
});
test('duplicate unrelated entries and ambiguous build permission fail without rewriting',async t=>{
 const mod=await api(),f=fixture(t);for(const raw of ['allowBuilds:\n  dsh-purge@https: true\n  other: true\n  other: false\n','allowBuilds:\n  dsh-purge: set this to true or false\n']){fs.writeFileSync(f.file,raw);assert.throws(()=>mod.repairProfilePnpm(f.profile,{apply:true}));assert.equal(fs.readFileSync(f.file,'utf8'),raw);}
});
test('symbolic profile and workspace paths are rejected without following them',async t=>{
 const mod=await api(),f=fixture(t);const external=path.join(f.root,'external');fs.writeFileSync(external,'allowBuilds:\n  dsh-purge@https: true\n');fs.symlinkSync(external,f.file);assert.throws(()=>mod.repairProfilePnpm(f.profile,{apply:true}),/symbolic|unsafe/i);assert.equal(fs.readFileSync(external,'utf8'),'allowBuilds:\n  dsh-purge@https: true\n');
});
