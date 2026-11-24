// Acceptance activation wrapper: unchanged candidate default tools, no global reconciliation.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {execFile,execFileSync} from 'node:child_process';
import {promisify} from 'node:util';
import {AttemptLedger,validateLive} from './proof-contract.mjs';
import {NativeGate} from './native-contract.mjs';
import {RedteamStore} from './package/lib/redteam/store-core.js';
import {securityFor,executeSecurityOp} from './package/lib/redteam/personal-security-workbench.mjs';
import {createSecurityServer} from './package/lib/redteam/personal-security-service.mjs';
const root=process.argv[2],settings=JSON.parse(fs.readFileSync(join(root,'stage.json')));
assert.equal(process.getuid(),1000);assert.equal(process.env.LISTEN_PID,String(process.pid));assert.equal(process.env.LISTEN_FDS,'1');
const workspace=join(root,'workspace'),project=join(workspace,'synthetic-project'),eng=settings.engagement;
const sha=value=>createHash('sha256').update(value).digest('hex');
const store=new RedteamStore(join(root,'state')),bench=securityFor(store);bench.workspaceRoot=workspace;
const gate=new NativeGate(eng);
const originalRunner=bench.runner,execAsync=promisify(execFile),ledger=new AttemptLedger(),proofs=ledger.attempts;
const manifest=JSON.parse(fs.readFileSync('/home/purge/tools/security-workbench/images.json','utf8'));
const protectedBefore=JSON.parse(fs.readFileSync(join(root,'protected.json'),'utf8'));
assert.equal(sha(fs.readFileSync('/home/purge/tools/security-workbench/images.json')),protectedBefore.pins['images.json']);
const image=manifest.tools.find(t=>t.tool==='semgrep').imageId,rules=JSON.parse(fs.readFileSync(join(root,'package/scripts/semgrep-deep17.json'),'utf8'));
const ruleBytesSha=sha(fs.readFileSync(join(root,'package/scripts/semgrep-deep17.json')));
bench.runner=async(tool,profile,options)=>{
 const proof=ledger.reserve('dsh-sec-'+options.runDir.split('/').pop());
 let timer,pending=Promise.resolve(),checking=false,violation;
 try{
  assert.equal(tool,'semgrep');const snapshot=bench.joint.active.data.snapshot;
  assert.equal(profile.repoRoot,snapshot.sourceRoot);
  const expected={sourceRoot:snapshot.sourceRoot,project,stateRoot:join(root,'state'),image,rules:ruleBytesSha};
  assert.equal(options.ruleProfile.rulesSha256,ruleBytesSha);assert.equal(rules.rules.length,17);
  const inventory=()=>Object.fromEntries(snapshot.files.map(f=>{const bytes=fs.readFileSync(join(profile.repoRoot,f.path));return[f.path,sha(bytes)]}));
  Object.assign(proof,{tool,snapshotId:snapshot.id,admissionIdentity:options.admissionIdentity,sourceRoot:profile.repoRoot,expected,before:inventory()});
  assert.ok(snapshot.files.every(f=>proof.before[f.path]===f.sha256));
  const inspect=()=>{
   if(proof.observed||checking||violation)return;checking=true;
   pending=execAsync('/usr/bin/sudo',['-n','/usr/bin/docker','inspect',proof.containerName],{encoding:'utf8',timeout:2000,maxBuffer:256*1024}).then(({stdout})=>{
    try{
     const v=JSON.parse(stdout)[0];if(!v?.State?.Running)return;
     const mount=v.Mounts.find(m=>m.Destination==='/src'),policy=v.Mounts.find(m=>m.Destination==='/policy/rules.json');
     const observed={imageId:v.Image,running:true,sourceMount:{source:mount?.Source,readonly:mount?.RW===false},ruleSha256:policy&&policy.RW===false?sha(fs.readFileSync(policy.Source)):null,user:v.Config.User,network:v.HostConfig.NetworkMode,readonlyRoot:v.HostConfig.ReadonlyRootfs,privileged:v.HostConfig.Privileged,capDrop:v.HostConfig.CapDrop,securityOpt:v.HostConfig.SecurityOpt,memory:v.HostConfig.Memory,memorySwap:v.HostConfig.MemorySwap,pids:v.HostConfig.PidsLimit,nanoCpus:v.HostConfig.NanoCpus,command:v.Config.Cmd};
     proof.observed=observed;validateLive(observed,expected);
    }catch(error){violation=String(error.message);proof.violation=violation;bench.active?.controller?.abort()}
   },error=>{if(proof.observerErrors.length<8)proof.observerErrors.push(String(error.message).slice(0,500))}).finally(()=>{checking=false});
  };
  timer=setInterval(inspect,40);inspect();
  const result=await originalRunner(tool,profile,options);clearInterval(timer);await pending;
  if(violation)throw Error(violation);validateLive(proof.observed,expected);
  proof.after=inventory();assert.deepEqual(proof.after,proof.before);proof.sourceHashesMatch=true;proof.manifestHashesMatch=true;
  Object.assign(proof,{outcome:'passed',findings:result.findings.length,declaredSpans:result.findings.map(f=>({rule:f.rule,location:f.location,scannerSpan:f.scannerSpan})),complete:result.complete,version:result.version,executedRules:result.executedRules,ruleProfile:result.ruleProfile,coverageKey:result.coverageKey});return result;
 }catch(error){proof.outcome='failed';proof.error=String(error.message);throw error}
 finally{if(timer)clearInterval(timer);await pending}
};

const events=[];
const server=createSecurityServer({dispatch:async(request,options)=>{
 const reason=gate.deny(request),event={at:new Date().toISOString(),request,model:options.model,allowed:!reason};events.push(event);
 if(reason){fs.appendFileSync(join(root,'rpc-events.jsonl'),JSON.stringify({...event,error:reason})+'\n');return{ok:false,error:reason}}
 const result=await executeSecurityOp(store,request,options);gate.remember(request,result);
 event.ok=result.ok;event.taskId=result.task?.id;event.taskState=result.task?.state;
 if(result.page)event.page={section:result.page.section,count:result.page.items.length,total:result.page.total,complete:result.page.complete,nextCursor:result.page.nextCursor};
 fs.appendFileSync(join(root,'rpc-events.jsonl'),JSON.stringify(event)+'\n');
 fs.writeFileSync(join(root,'scanner-proofs.json'),JSON.stringify(proofs));return result;
}});
server.listen({fd:3});
let stopped=false;
async function stop(){if(stopped)return;stopped=true;await server.shutdown();await bench.dispose();await store.close();
 const cleanupErrors=[];for(const proof of proofs){try{const x=execFileSync('/usr/bin/sudo',['-n','/usr/bin/docker','ps','-aq','--filter','name=^'+proof.containerName+'$'],{encoding:'utf8',timeout:8000}).trim();proof.containerAbsent=!x;if(x)cleanupErrors.push(proof.containerName)}catch{cleanupErrors.push(proof.containerName)}}
 fs.writeFileSync(join(root,'backend-stopped.json'),JSON.stringify({proofs,cleanupErrors,taskId:gate.task,events}));}
process.once('SIGTERM',()=>stop());process.once('SIGINT',()=>stop());
