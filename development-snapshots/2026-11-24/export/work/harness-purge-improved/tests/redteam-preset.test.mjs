import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const mod=await import('../package/lib/personal-redteam.js').catch(()=>({}));
test('The improved bundle declares a separate redteam preset alongside existing tools',()=>{
 const patch=fs.readFileSync(new URL('../package/cordis.patch.yml',import.meta.url),'utf8');
 assert.match(patch,/name: dsh-purge\/personal-redteam/);
 for(const name of ['dsh-purge/redteam/store','dsh-purge/redteam/ui','dsh-purge/redteam/tools'])assert.ok(patch.includes(name));
});
test('Redteam keeps its own commander composition rather than renaming PTC',()=>{
 assert.equal(typeof mod.redteamDefinition,'function','Missing redteam declaration');
 const preset=mod.redteamDefinition();
 assert.equal(preset.id,'redteam');assert.equal(preset.name,'Red team mode');
 const persona=preset.plugins.find(row=>row.id==='persona');
 assert.match(persona.config.prefix,/指挥职责/);
 assert.ok(preset.plugins.some(row=>row.id==='delegation'));
 assert.ok(!preset.plugins.some(row=>['sandbox-policy','permission','approval'].includes(row.id)));
});
test('Preset declaration rejects unrelated homes before accessing registry services',async()=>{
 assert.equal(typeof mod.apply,'function');
 const saved=process.env.DSH_HOME;process.env.DSH_HOME='/tmp/unrelated-harness';
 try{await assert.rejects(mod.apply({}),/improved VM/)}finally{if(saved===undefined)delete process.env.DSH_HOME;else process.env.DSH_HOME=saved}
});
