import http from 'node:http';
import assert from 'node:assert/strict';
import {absenceReply} from './container-absence.mjs';
import {AttemptLedger,validateLive,collectPages,validateAcceptance} from './proof-contract.mjs';
import fs from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {execFile,execFileSync} from 'node:child_process';
import {promisify} from 'node:util';
import {RedteamStore} from './package/lib/redteam/store-core.js';
import {securityFor,executeSecurityOp} from './package/lib/redteam/personal-security-workbench.mjs';
import {createSecurityServer,requestSecurityService} from './package/lib/redteam/personal-security-service.mjs';

const root=fileURLToPath(new URL('.',import.meta.url)),workspace=join(root,'workspace'),project=join(workspace,'synthetic'),sha=v=>createHash('sha256').update(v).digest('hex');
assert.ok(!fs.existsSync(workspace)&&!fs.existsSync(join(root,'state')),'Fresh acceptance state required');
fs.mkdirSync(project,{recursive:true,mode:0o700});
const canary='LIVE_LOCATION_SYNTHETIC_'+'Z'.repeat(50);
const fixture={
 'same_line.py':'# 中文位置对照🙂\n"中文🙂"; label="'+canary+'"; eval(input()); eval(input())\n',
 'crlf_tabs.py':'def run(value):\r\n\teval(value)\r\n\texec(value)\r\n',
 'extra.py':'def run(value):\n    eval(value)\n    exec(value)\n',
 'helper.py':'def run(value):\n    return eval(value)\n',
 'constant.py':'def fixed():\n    return eval("6*7")\n',
};
for(const [name,text] of Object.entries(fixture))fs.writeFileSync(join(project,name),text,{mode:0o600});
const ledger=new AttemptLedger(),proofs=ledger.attempts,events=[];let store,bench,rpc,ui,timer,evidence;
const activeContainers=()=>execFileSync('/usr/bin/sudo',['-n','/usr/bin/docker','ps','-aq','--filter','label=personal.harness.security=true'],{encoding:'utf8',timeout:8000}).trim().split('\n').filter(Boolean).sort();
const containersBefore=activeContainers();
try{
store=new RedteamStore(join(root,'state'));const eng=store.openEngagement('Isolated source location live').id;bench=securityFor(store);
bench.workspaceRoot=workspace;store.addCredential(eng,{host:'synthetic.invalid',secret_type:'api',secret_value:canary});
const socket=join(root,'review.sock');rpc=createSecurityServer({dispatch:(request,options)=>executeSecurityOp(store,request,options)});
await new Promise(resolve=>rpc.listen(socket,resolve));fs.chmodSync(socket,0o600);
const call=input=>requestSecurityService({engagement:eng,...input},{socketPath:socket,timeoutMs:40000});
const expiresAt=new Date(Date.now()+1200000).toISOString();
const saved=await call({op:'securityScopeSave',requestId:'source-live-scope-001',revision:0,repoRoot:project,tools:['semgrep'],expiresAt,confirm:true});
if(!saved.ok)throw Error(saved.error);
const originalRunner=bench.runner,execAsync=promisify(execFile);
const manifest=JSON.parse(fs.readFileSync('/home/purge/tools/security-workbench/images.json','utf8'));
const protectedBefore=JSON.parse(fs.readFileSync(join(root,'protected-before.json'),'utf8'));
assert.equal(sha(fs.readFileSync('/home/purge/tools/security-workbench/images.json')),protectedBefore.pins['images.json']);
const image=manifest.tools.find(t=>t.tool==='semgrep').imageId,rules=protectedBefore.pins['rules.json'];
bench.runner=async(tool,profile,options)=>{
 const proof=ledger.reserve('dsh-sec-'+options.runDir.split('/').pop());
 let timer,pending=Promise.resolve(),checking=false,violation;
 try{
  assert.equal(tool,'semgrep');const snapshot=bench.joint.active.data.snapshot;
  assert.equal(profile.repoRoot,snapshot.sourceRoot);
  const expected={sourceRoot:snapshot.sourceRoot,project,stateRoot:join(root,'state'),image,rules,containerName:proof.containerName,ruleFile:join(options.runDir,'semgrep-rules.json'),outputScript:join(root,'package/scripts/security-output.sh')};
  assert.equal(bench.active?.id,options.runDir.split('/').pop());assert.ok(bench.active.controller instanceof AbortController);
  const inventory=()=>{const actual=[];const walk=dir=>{for(const name of fs.readdirSync(dir)){const p=join(dir,name),st=fs.lstatSync(p);assert.ok(!st.isSymbolicLink());if(st.isDirectory())walk(p);else{assert.ok(st.isFile()&&st.nlink===1);actual.push(p.slice(profile.repoRoot.length+1))}}};walk(profile.repoRoot);assert.deepEqual(actual.sort(),snapshot.files.map(f=>f.path).sort());return Object.fromEntries(snapshot.files.map(f=>{const bytes=fs.readFileSync(join(profile.repoRoot,f.path));assert.ok(!bytes.includes(Buffer.from(canary)),'Synthetic secret remained in scanner copy');return[f.path,sha(bytes)]}))};
  Object.assign(proof,{tool,snapshotId:snapshot.id,admissionIdentity:options.admissionIdentity,sourceRoot:profile.repoRoot,expected,before:inventory()});
  assert.ok(snapshot.files.every(f=>proof.before[f.path]===f.sha256));
  const inspect=()=>{
   if(proof.observed||checking||violation)return;checking=true;
   pending=execAsync('/usr/bin/sudo',['-n','/usr/bin/docker','inspect',proof.containerName],{encoding:'utf8',timeout:2000,maxBuffer:256*1024}).then(({stdout})=>{
    try{
     const v=JSON.parse(stdout)[0];if(!v?.State?.Running)return;
     const mount=v.Mounts.find(m=>m.Destination==='/src'),policy=v.Mounts.find(m=>m.Destination==='/policy/rules.json');
     const observed={containerName:v.Name,containerId:v.Id,capAdd:v.HostConfig.CapAdd,devices:v.HostConfig.Devices,deviceRequests:v.HostConfig.DeviceRequests,pidMode:v.HostConfig.PidMode,ipcMode:v.HostConfig.IpcMode,utsMode:v.HostConfig.UTSMode,entrypoint:v.Config.Entrypoint,mounts:v.Mounts.map(m=>({type:m.Type,source:m.Source,destination:m.Destination,rw:m.RW})),tmpfs:v.HostConfig.Tmpfs,imageId:v.Image,running:true,sourceMount:{source:mount?.Source,readonly:mount?.RW===false},ruleSha256:policy&&policy.RW===false?sha(fs.readFileSync(policy.Source)):null,user:v.Config.User,network:v.HostConfig.NetworkMode,readonlyRoot:v.HostConfig.ReadonlyRootfs,privileged:v.HostConfig.Privileged,capDrop:v.HostConfig.CapDrop,securityOpt:v.HostConfig.SecurityOpt,memory:v.HostConfig.Memory,memorySwap:v.HostConfig.MemorySwap,pids:v.HostConfig.PidsLimit,nanoCpus:v.HostConfig.NanoCpus,command:v.Config.Cmd};
     proof.observed=observed;validateLive(observed,expected);
    }catch(error){violation=String(error.message);proof.violation=violation;bench.active?.controller?.abort()}
   },error=>{if(proof.observerErrors.length<8)proof.observerErrors.push(String(error.message).slice(0,500))}).finally(()=>{checking=false});
  };
  timer=setInterval(inspect,40);inspect();
  const result=await originalRunner(tool,profile,options);clearInterval(timer);await pending;
  if(violation)throw Error(violation);validateLive(proof.observed,expected);
  proof.after=inventory();assert.deepEqual(proof.after,proof.before);proof.sourceHashesMatch=true;proof.manifestHashesMatch=true;proof.copyCanaryAbsent=true;
  Object.assign(proof,{outcome:'passed',findings:result.findings.length,declaredSpans:result.findings.map(f=>({rule:f.rule,location:f.location,scannerSpan:f.scannerSpan})),complete:result.complete,version:result.version});return result;
 }catch(error){proof.outcome='failed';proof.error=String(error.message);throw error}
 finally{if(timer)clearInterval(timer);await pending}
};
const profile={revision:1,expiresAt},assets=new Map([
 ['/',['text/html',fs.readFileSync(join(root,'index.html'),'utf8').replace('__FIXTURE__',()=>JSON.stringify([eng,profile]).replace(/</g,'\\u003c'))]],
 ['/react.js',['text/javascript',fs.readFileSync(join(root,'react.production.min.js'))]],
 ['/react-dom.js',['text/javascript',fs.readFileSync(join(root,'react-dom.production.min.js'))]],
 ['/client.mjs',['text/javascript',fs.readFileSync(join(root,'package/lib/redteam/personal-security-client.mjs'))]],
 ['/base.css',['text/css',fs.readFileSync(join(root,'base.css'))]],
]);
let finish,startRequest=null,jointId=null;const done=new Promise(resolve=>finish=resolve);
async function collect(){
 const report={version:1,engagement:eng,task:null,findings:[],files:[],exclusions:[],diagnostics:[],artifacts:[]};
 if(jointId){
  const status=await call({op:'securityJoint',action:'status',id:jointId});assert.ok(status.ok&&status.task.id===jointId);const snapshotId=status.task.snapshot.id;
  for(const section of ['findings','files','exclusions','diagnostics','artifacts']){
   const result=await collectPages(cursor=>call({op:'securityJoint',action:'report',id:jointId,section,limit:5,...(cursor?{cursor}:{})}),jointId,snapshotId,100,section);
   report.task=result.task;report[section]=result.items;
  }
 }
 let proofValid=false,rangeOracle=null;const acceptanceErrors=[];try{validateAcceptance({jointId,requests:ledger.requests,proofs,report});rangeOracle=verifyRanges(report,proofs[0].sourceRoot);proofValid=true}catch(error){acceptanceErrors.push(String(error.message))}
 const runs=bench.db(eng).prepare('SELECT * FROM security_run').all(),facts=bench.db(eng).prepare('SELECT COUNT(*) n FROM security_finding').get().n;
 return{ok:true,engagement:eng,jointId,startRequest,events,proofs,report,runs:runs.map(r=>({...r,details:JSON.parse(r.details)})),ordinaryFindingRows:facts,
  fixtureSourceHashes:Object.fromEntries(Object.entries(fixture).map(([n,s])=>[n,sha(s)])),newScannerCalls:proofs.length,modelCalls:Number.isSafeInteger(report.task?.modelCalls)?report.task.modelCalls:null,proofValid,acceptanceErrors,rangeOracle,runnerRequests:ledger.requests};
}
function verifyRanges(report,sourceRoot){
 const rows=[],copies={};for(const file of report.files){const bytes=fs.readFileSync(join(sourceRoot,file.path));assert.equal(sha(bytes),file.sha256);assert.ok(!bytes.includes(Buffer.from(canary)));copies[file.path]={sha256:sha(bytes),base64:bytes.toString('base64')}}
 for(const f of report.findings){const l=f.sourceLocation,raw=Buffer.from(copies[l.path].base64,'base64');assert.equal(sha(raw),l.sourceSha256);assert.equal(raw.length,l.byteLength);
  for(const which of ['start','end']){const p=l[which],prefix=raw.subarray(0,p.offset);new TextDecoder('utf8',{fatal:true}).decode(prefix);assert.equal(prefix.reduce((n,b)=>n+(b===10),0),p.line-1);assert.equal(prefix.length-prefix.lastIndexOf(10),p.col)}
  const slice=raw.subarray(l.start.offset,l.end.offset).toString('utf8');assert.ok(/^(eval|exec)\(/.test(slice));if(l.path==='same_line.py'){assert.ok(raw.includes(Buffer.from('中文🙂')));const prefix=raw.subarray(0,l.start.offset);assert.notEqual([...prefix.subarray(prefix.lastIndexOf(10)+1).toString('utf8')].length+1,l.start.col)}
  rows.push({path:l.path,start:l.start,end:l.end,slice});
 }
 const same=rows.filter(r=>r.path==='same_line.py');assert.equal(same.length,2);assert.notEqual(same[0].start.offset,same[1].start.offset);return{ok:true,matchedRanges:rows.length,unicodeSameLineByteUnitsProven:true,rows,copies};
}
ui=http.createServer(async(req,res)=>{
 const send=(status,value)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value))};
 try{
  const host=req.headers.host;
  if(!/^127\.0\.0\.1:\d+$/.test(host))return send(403,{ok:false});
  if(req.method==='GET'&&assets.has(req.url)){const [type,body]=assets.get(req.url);res.writeHead(200,{'Content-Type':type+'; charset=utf-8','Cache-Control':'no-store'});return res.end(body)}
  if(req.method==='GET'&&req.url==='/health')return send(200,{ok:true,engagement:eng});
  if(req.method!=='POST'||req.headers.origin!=='http://'+host)return send(404,{ok:false});
  if(req.url==='/__collect')return send(200,await collect());
  if(req.url==='/__stop'){res.once('finish',finish);const value=await collect();send(200,value);return}
  if(req.url!=='/api')return send(404,{ok:false});
  let body='';for await(const chunk of req){body+=chunk;if(body.length>32768)return send(413,{ok:false})}
  const input=JSON.parse(body);
  if(input.engagement!==eng||input.op!=='securityJoint'||!['plan','start','status','wait','report','cancel'].includes(input.action))return send(403,{ok:false});
  if(input.id&&input.id!==jointId)return send(403,{ok:false});
  if(input.action==='start'){
   if(input.mode!=='deep'||JSON.stringify(input.steps)!=='["semgrep"]'||typeof input.requestId!=='string'||startRequest!==null)return send(403,{ok:false,error:'Only one owned synthetic scan is allowed'});
   startRequest=input.requestId;
  }
  const event={action:input.action,section:input.section??null,requestId:input.requestId??null,id:input.id??null,cursorUsed:!!input.cursor,outcome:'pending'};events.push(event);
  let result;try{result=await call(input);event.outcome=result.ok?'returned-ok':'returned-error'}catch(error){event.outcome='threw';event.error=String(error.message);throw error}
  if(input.action==='start'&&result.ok){assert.equal(jointId,null);jointId=result.task.id}
  send(200,result);
 }catch(error){send(500,{ok:false,error:String(error.message)})}
});
 await new Promise((resolve,reject)=>{ui.once('error',reject);ui.listen(0,'127.0.0.1',resolve)});
 console.log(JSON.stringify({browserReady:true,port:ui.address().port,engagement:eng,fixtureFiles:Object.keys(fixture).length}));
 timer=setTimeout(finish,1200000);await done;evidence=await collect();
}finally{
 if(timer)clearTimeout(timer);
 if(ui?.listening){ui.closeAllConnections();await new Promise(resolve=>ui.close(resolve))}
 const cleanupErrors=[];
 for(const [name,fn] of [['rpc',()=>rpc?.shutdown()],['bench',()=>bench?.dispose()],['store',()=>store?.close()]])try{await fn()}catch(error){cleanupErrors.push(name+': '+String(error.message))}
 for(const proof of proofs)try{
  const id=proof.observed?.containerId;assert.ok(id,'Container identity was not positively observed');
  try{execFileSync('/usr/bin/sudo',['-n','/usr/bin/docker','inspect',id],{encoding:'utf8',timeout:8000,stdio:['ignore','pipe','pipe']});throw Error('Owned scanner remains')}
  catch(error){assert.ok(absenceReply(error,id),'Container absence not proven')}
  execFileSync('/usr/bin/sudo',['-n','/usr/bin/docker','image','inspect',proof.expected.image],{encoding:'utf8',timeout:8000,stdio:['ignore','pipe','pipe']});proof.containerAbsent=true;
 }catch(error){cleanupErrors.push(String(error.message))}
 try{assert.deepEqual(activeContainers(),containersBefore)}catch(error){cleanupErrors.push('Labeled container baseline mismatch')}
 evidence??={ok:false,error:'Final report collection failed',proofs,events};evidence.cleanupErrors=cleanupErrors;
 fs.writeFileSync(join(root,'final-evidence.json'),JSON.stringify(evidence));
 console.log(JSON.stringify({stopped:true,containersAbsent:proofs.filter(p=>p.containerAbsent).length,cleanupErrors}));
}
