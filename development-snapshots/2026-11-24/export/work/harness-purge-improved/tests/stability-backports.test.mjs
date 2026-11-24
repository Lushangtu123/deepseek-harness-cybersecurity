import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import {extractZipBuffer} from '../package/lib/zip-extract.js';
import {importFromPath} from '../package/lib/skills.js';
import * as presets from '../package/lib/preset-default.js';

function folder(t) {
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'dsh-stability-')));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return root;
}
function zip(entries) {
 let offset=0;const locals=[],centrals=[];
 for(const [name,data=''] of entries){
  const n=Buffer.from(name),body=Buffer.from(data),crc=zlib.crc32(body)>>>0;
  const l=Buffer.alloc(30+n.length);l.writeUInt32LE(0x04034b50);l.writeUInt16LE(20,4);l.writeUInt32LE(crc,14);l.writeUInt32LE(body.length,18);l.writeUInt32LE(body.length,22);l.writeUInt16LE(n.length,26);n.copy(l,30);
  const c=Buffer.alloc(46+n.length);c.writeUInt32LE(0x02014b50);c.writeUInt16LE(20,4);c.writeUInt16LE(20,6);c.writeUInt32LE(crc,16);c.writeUInt32LE(body.length,20);c.writeUInt32LE(body.length,24);c.writeUInt16LE(n.length,28);c.writeUInt32LE(offset,42);n.copy(c,46);
  locals.push(l,body);centrals.push(c);offset+=l.length+body.length;
 }
 const central=Buffer.concat(centrals),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(entries.length,8);end.writeUInt16LE(entries.length,10);end.writeUInt32LE(central.length,12);end.writeUInt32LE(offset,16);
 return Buffer.concat([...locals,central,end]);
}

test('explicit and empty ZIP directories are directories, including backslash entries',t=>{
 const dest=folder(t);extractZipBuffer(zip([['root/'],['root/empty/'],['root\\nested\\'],['root/nested/file.txt','complete']]),dest);
 assert.ok(fs.statSync(path.join(dest,'root/empty')).isDirectory());assert.equal(fs.readFileSync(path.join(dest,'root/nested/file.txt'),'utf8'),'complete');
});
test('ZIP directory entries still reject traversal',t=>{
 const root=folder(t);assert.throws(()=>extractZipBuffer(zip([['../outside/']]),path.join(root,'dest')),/Invalid zip path/);assert.equal(fs.existsSync(path.join(root,'outside')),false);
});
test('skills import refuses a symlink into its own skill tree before changing files',async t=>{
 const root=folder(t),home=path.join(root,'home'),skill=path.join(home,'skills/demo-skill');fs.mkdirSync(skill,{recursive:true});
 const doc='---\nname: demo-skill\ndescription: local fixture\n---\nKEEP_ORIGINAL\n';fs.writeFileSync(path.join(skill,'SKILL.md'),doc);const link=path.join(root,'external-link');fs.symlinkSync(path.join(home,'skills'),link);
 await assert.rejects(importFromPath(home,link),/Cannot import from/);assert.equal(fs.readFileSync(path.join(skill,'SKILL.md'),'utf8'),doc);assert.equal(fs.existsSync(path.join(home,'dsh-purge-backups')),false);
});
test('preset cleanup covers cordis.yml but preserves custom preset ids and symlink targets',t=>{
 const home=folder(t),profile=path.join(home,'profiles/web');fs.mkdirSync(profile,{recursive:true});
 const file=path.join(profile,'cordis.yml');fs.writeFileSync(file,'- id: agent-preset-registry\n  config:\n    selectedDefault: redteam\n', {mode:0o600});
 const custom=path.join(profile,'cordis.patch.yml');fs.writeFileSync(custom,'selectedDefault: redteam-custom\n');
 presets.clearOwnedSelectedDefault({dshHome:home});assert.match(fs.readFileSync(file,'utf8'),/selectedDefault: standard/);assert.equal(fs.statSync(file).mode&0o777,0o600);assert.equal(fs.readFileSync(custom,'utf8'),'selectedDefault: redteam-custom\n');
 const external=path.join(home,'external.yml');fs.writeFileSync(external,'selectedDefault: redteam\n');fs.unlinkSync(custom);fs.symlinkSync(external,custom);presets.clearOwnedSelectedDefault({dshHome:home});assert.equal(fs.readFileSync(external,'utf8'),'selectedDefault: redteam\n');
});
test('hot reload cancels delayed preset cleanup; switching original capabilities off does not dispose the plugin',t=>{
 assert.equal(typeof presets.installPresetDefaultCleanup,'function');t.mock.timers.enable({apis:['setTimeout']});
 const home=folder(t),profile=path.join(home,'profiles/web');fs.mkdirSync(profile,{recursive:true});const file=path.join(profile,'cordis.patch.yml');fs.writeFileSync(file,'selectedDefault: redteam\n');
 fs.writeFileSync(path.join(profile,'package.json'),JSON.stringify({name:'dsh-profile-web',dependencies:{}}));
 let dispose;const ctx={effect(factory){dispose=factory();}};
 presets.installPresetDefaultCleanup(ctx,true,home);assert.equal(fs.readFileSync(file,'utf8'),'selectedDefault: redteam\n');dispose();presets.installPresetDefaultCleanup(ctx,true,home);t.mock.timers.tick(1000);assert.equal(fs.readFileSync(file,'utf8'),'selectedDefault: redteam\n');
 dispose();t.mock.timers.tick(1000);assert.equal(fs.readFileSync(file,'utf8'),'selectedDefault: standard\n');
});
test('service restart does not clear a preset while the profile still references the plugin',t=>{
 t.mock.timers.enable({apis:['setTimeout']});const home=folder(t),profile=path.join(home,'profiles/web');fs.mkdirSync(profile,{recursive:true});const file=path.join(profile,'cordis.patch.yml');fs.writeFileSync(file,'selectedDefault: redteam\n');fs.writeFileSync(path.join(profile,'package.json'),JSON.stringify({name:'dsh-profile-web',dependencies:{'dsh-purge':'file:/fixture'}}));
 let dispose;presets.installPresetDefaultCleanup({effect(factory){dispose=factory();}},true,home);dispose();t.mock.timers.tick(1000);assert.equal(fs.readFileSync(file,'utf8'),'selectedDefault: redteam\n');
});
