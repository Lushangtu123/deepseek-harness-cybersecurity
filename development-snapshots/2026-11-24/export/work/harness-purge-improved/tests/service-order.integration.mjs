// Run against the installed VM Cordis runtime and plugin, with no model/network calls.
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
const {Context}=await import(process.env.DSH_CORDIS_TEST_MODULE);
if(process.env.DSH_HOST_TEST_BIN)process.argv[1]=process.env.DSH_HOST_TEST_BIN;
const tools=await import(process.env.DSH_TOOLS_TEST_MODULE);
const {RedteamStore}=await import(process.env.DSH_STORE_TEST_MODULE);
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-service-order-'));
const ctx=new Context(),registered=new Map(),session={id:'order-root',header:{}};let store;
try{
 ctx.provide('sessions',{get:id=>id===session.id?session:undefined});
 ctx.provide('tools',{register:tool=>registered.set(tool.name,tool)});
 ctx.plugin(tools);
 await new Promise(resolve=>setImmediate(resolve));
 console.log(JSON.stringify({stage:'before-store',registered:registered.size}));
 assert.equal(registered.size,0,'Tools must wait for their asset store instead of capturing an empty fallback');
 store=new RedteamStore(root);const id=store.openEngagement('order-project',[],{bindCurrent:false}).id;
 ctx.provide('redteam',store);await new Promise(resolve=>setImmediate(resolve));
 const tool=registered.get('redteam_session_bind');assert.ok(tool,'Tool must activate after store becomes ready');
 const result=JSON.parse(await tool.execute({engagement:id},{agent:{session}}));
 assert.equal(result.ok,true);assert.equal(store.sessionBindings.resolve([session.id]),id);
 console.log(JSON.stringify({stage:'after-store',bindingSucceeded:true,registered:registered.size}));
}finally{if(typeof ctx.dispose==='function')await ctx.dispose();if(store)await store.close();fs.rmSync(root,{recursive:true,force:true})}
