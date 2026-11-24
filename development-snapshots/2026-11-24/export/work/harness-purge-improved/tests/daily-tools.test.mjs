import test from 'node:test';
import assert from 'node:assert/strict';
const mod=await import('../package/lib/personal-daily.js').catch(()=>({}));
const filter=await import('../package/lib/personal-daily-filter.js').catch(()=>({}));
test('Daily preset preserves the native standard composition and adds scoped filtering',()=>{
 assert.equal(typeof mod.dailyDefinition,'function','Missing daily preset builder');
 const standard={id:'standard',plugins:[{id:'tool-bash',name:'@deepseek-ai/dsh-tool-bash'},{id:'persona',name:'@deepseek-ai/dsh-persona',config:{prefix:'native'}}]};
 const before=JSON.stringify(standard),daily=mod.dailyDefinition(standard);
 assert.equal(JSON.stringify(standard),before);assert.equal(daily.id,'personal-daily');assert.equal(daily.plugins[0].name,standard.plugins[0].name);
 assert.equal(daily.plugins.at(-1).name,'dsh-purge/personal-daily-filter');
});
test('Only heavy professional namespaces are filtered; CLI, skills and CodeGraph stay',()=>{
 assert.equal(typeof mod.professionalToolNames,'function');
 const names=['bash','skill','mcp__codegraph__query','mcp__rea__binary_session','redteam_assets','redteam_evidence_list','mcp__rea_fake'];
 assert.deepEqual(mod.professionalToolNames(names.map(name=>({name}))),['mcp__rea__binary_session','redteam_assets','redteam_evidence_list']);
});
test('Late registration and removal refresh only this scope without recursive change loops',()=>{
 assert.equal(typeof filter.apply,'function');
 let names=['bash'],handler,cleanup,restrictions=0;const active=new Set();
 const ctx={root:{tools:{schemas:()=>names.map(name=>({name}))}},on(name,fn){assert.equal(name,'tools/change');handler=fn},effect(fn){cleanup=fn()},tools:{restrict({deny}){restrictions++;assert.ok(restrictions<8,'Recursive tools/change loop');const mask=new Set(deny);active.add(mask);handler();return()=>{active.delete(mask);handler()}}}};
 filter.apply(ctx);assert.equal(active.size,0);
 names.push('mcp__rea__binary_session');handler();assert.equal(active.size,1);
 names.push('redteam_assets');handler();assert.equal(active.size,1);
 assert.deepEqual([...active][0],new Set(['mcp__rea__binary_session','redteam_assets']));
 names=['bash'];handler();assert.equal(active.size,0);
 names.push('mcp__rea__binary_session');handler();cleanup();assert.equal(active.size,0);
 handler();assert.equal(active.size,0);
});
