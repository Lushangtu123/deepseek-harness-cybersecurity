import fs from 'node:fs';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
import {RedteamStore} from '/home/purge/tools/dsh-purge-personal-1.1.77-personal.1/lib/redteam/store-core.js';
import {requestSecurityService} from '/home/purge/tools/dsh-purge-personal-1.1.77-personal.1/lib/redteam/personal-security-service.mjs';
const project='/home/purge/workspace/harness-acceptance/namespace-managed-release-20261103';assert.ok(!fs.existsSync(project));fs.mkdirSync(project,{recursive:true,mode:0o700});
const canary='LIVE_LOCATION_SYNTHETIC_'+'Z'.repeat(50);const files={
'same_line.py':'# 中文位置对照🙂\n"中文🙂"; label="'+canary+'"; eval(input()); eval(input())\n',
'crlf_tabs.py':'def run(value):\r\n\teval(value)\r\n\texec(value)\r\n',
'extra.py':'def run(value):\n    eval(value)\n    exec(value)\n',
'helper.py':'def run(value):\n    return eval(value)\n',
'constant.py':'def fixed():\n    return eval("6*7")\n'};
for(const[n,s]of Object.entries(files))fs.writeFileSync(project+'/'+n,s,{mode:0o600});
const store=new RedteamStore('/home/purge/.dsh-improved/redteam'),previous=store.activeEngagementId();assert.ok(!store.listEngagements().some(e=>e.name==='VM namespace managed release 20261103'));
const eng=store.openEngagement('VM namespace managed release 20261103',[],{bindCurrent:false});store.addCredential(eng.id,{host:'synthetic.invalid',secret_type:'api',secret_value:canary});await store.close();
const result=await requestSecurityService({op:'securityScopeSave',engagement:eng.id,requestId:'namespace-managed-release-scope-20261103',revision:0,repoRoot:project,tools:['semgrep'],expiresAt:new Date(Date.now()+2*3600000).toISOString(),confirm:true});assert.equal(result.ok,true,JSON.stringify(result));
console.log(JSON.stringify({engagement:eng.id,previous,project,profile:result.profile,sourceHashes:Object.fromEntries(Object.entries(files).map(([n,s])=>[n,createHash('sha256').update(s).digest('hex')])),syntheticCredentialOnly:true}));
