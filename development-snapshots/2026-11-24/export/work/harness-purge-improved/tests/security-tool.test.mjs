import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import vm from 'node:vm';
import {RedteamStore} from '../package/lib/redteam/store-core.js';import {resolveEngagement} from '../package/lib/redteam/personal-session-resolution.mjs';
test('Native security tool requires the current session binding and rejects explicit cross-project overrides',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'security-tool-'));const store=new RedteamStore(root);try{
  const a=store.openEngagement('A').id,b=store.openEngagement('B').id;store.sessionBindings.bind(['root-a'],a);const session={id:'root-a',header:{}};store.sessionLookup=id=>id==='root-a'?session:undefined;
  const source=fs.readFileSync(new URL('../package/lib/redteam/tools.js',import.meta.url),'utf8'),at=source.indexOf("name: 'redteam_security_audit'"),begin=source.lastIndexOf('  ctx.tools.register(',at),end=source.indexOf('\n  ctx.tools.register(',at);let tool;
  vm.runInNewContext(source.slice(begin,end),{ctx:{tools:{register:value=>tool=value}},store,resolveEngagement,handleSecurityOp:async(_store,request)=>({ok:true,request}),defineTool:x=>x,reviewedTool:x=>x,text:x=>x});
  const exec={agent:{session}};assert.equal(JSON.parse(await tool.execute({action:'compare',baseRunId:'base-run-0001',currentRunId:'next-run-0002'},exec)).request.op,'securityCompare');assert.equal(JSON.parse(await tool.execute({action:'status'},exec)).request.engagement,a);assert.equal(JSON.parse(await tool.execute({action:'status',engagement:a},exec)).request.engagement,a);await assert.rejects(tool.execute({action:'start',engagement:b},exec),/必须与当前会话绑定一致/);await assert.rejects(tool.execute({action:'status',engagement:b},{agent:{session:{id:'unbound',header:{}}}}));
 }finally{await store.close();fs.rmSync(root,{recursive:true,force:true})}
});
