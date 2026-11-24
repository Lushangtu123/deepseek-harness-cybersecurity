import http from 'node:http';
import assert from 'node:assert/strict';
import {AttemptLedger,validateLive,collectPages} from './proof-contract.mjs';
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
const fixture=JSON.parse(fs.readFileSync(join(root,'controls.json'),'utf8')).fixture;
for(const [name,text] of Object.entries(fixture)){fs.mkdirSync(join(project,name,'..'),{recursive:true});fs.writeFileSync(join(project,name),text,{mode:0o600})}
const store=new RedteamStore(join(root,'state')),eng=store.openEngagement('Isolated import namespace live').id,bench=securityFor(store);
bench.workspaceRoot=workspace;
const socket=join(root,'review.sock'),rpc=createSecurityServer({dispatch:(request,options)=>executeSecurityOp(store,request,options)});
await new Promise(resolve=>rpc.listen(socket,resolve));fs.chmodSync(socket,0o600);
const call=input=>requestSecurityService({engagement:eng,...input},{socketPath:socket,timeoutMs:40000});
const expiresAt=new Date(Date.now()+1200000).toISOString();
const saved=await call({op:'securityScopeSave',requestId:'import-namespace-live-scope-001',revision:0,repoRoot:project,tools:['semgrep'],expiresAt,confirm:true});
if(!saved.ok)throw Error(saved.error);
const originalRunner=bench.runner,execAsync=promisify(execFile),ledger=new AttemptLedger(),proofs=ledger.attempts;
const manifest=JSON.parse(fs.readFileSync('/home/purge/tools/security-workbench/images.json','utf8'));
const protectedBefore=JSON.parse(fs.readFileSync(join(root,'protected-before.json'),'utf8'));
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
const profile={revision:1,expiresAt},assets=new Map([
 ['/',['text/html',fs.readFileSync(join(root,'index.html'),'utf8').replace('__FIXTURE__',()=>JSON.stringify([eng,profile]).replace(/</g,'\\u003c'))]],
 ['/react.js',['text/javascript',fs.readFileSync(join(root,'react.production.min.js'))]],
 ['/react-dom.js',['text/javascript',fs.readFileSync(join(root,'react-dom.production.min.js'))]],
 ['/client.mjs',['text/javascript',fs.readFileSync(join(root,'package/lib/redteam/personal-security-client.mjs'))]],
 ['/base.css',['text/css',fs.readFileSync(join(root,'base.css'))]],
 ...['personal-semgrep-profile.mjs','personal-security-observation.mjs'].map(name=>['/'+name,['text/javascript',fs.readFileSync(join(root,'package/lib/redteam',name))]]),
]);
let finish,startRequest=null,jointId=null;const done=new Promise(resolve=>finish=resolve),events=[];
async function collect(){
 const report={version:1,engagement:eng,task:null,findings:[],files:[],exclusions:[],diagnostics:[],artifacts:[]};
 if(jointId){
  const status=await call({op:'securityJoint',action:'status',id:jointId});assert.ok(status.ok&&status.task.id===jointId);const snapshotId=status.task.snapshot.id;
  for(const section of ['findings','files','exclusions','diagnostics','artifacts']){
   const result=await collectPages(cursor=>call({op:'securityJoint',action:'report',id:jointId,section,limit:5,...(cursor?{cursor}:{})}),jointId,snapshotId);
   report.task=result.task;report[section]=result.items;
  }
 }
 const runs=bench.db(eng).prepare('SELECT * FROM security_run').all(),facts=bench.db(eng).prepare('SELECT COUNT(*) n FROM security_finding').get().n;
 return{ok:true,engagement:eng,jointId,startRequest,events,proofs,report,runs:runs.map(r=>({...r,details:JSON.parse(r.details)})),ordinaryFindingRows:facts,
  fixtureSourceHashes:Object.fromEntries(Object.entries(fixture).map(([n,s])=>[n,sha(s)])),newScannerCalls:proofs.length,modelCalls:Number.isSafeInteger(report.task?.modelCalls)?report.task.modelCalls:null,proofValid:proofs.length===1&&proofs.every(p=>p.outcome==='passed')};
}
const ui=http.createServer(async(req,res)=>{
 const send=(status,value)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value))};
 try{
  const host=req.headers.host;
  if(!/^127\.0\.0\.1:\d+$/.test(host))return send(403,{ok:false});
  if(req.method==='GET'&&assets.has(req.url)){const [type,body]=assets.get(req.url);res.writeHead(200,{'Content-Type':type+'; charset=utf-8','Cache-Control':'no-store'});return res.end(body)}
  if(req.method==='GET'&&req.url==='/health')return send(200,{ok:true,engagement:eng});
  if(req.method!=='POST'||req.headers.origin!=='http://'+host)return send(404,{ok:false});
  if(req.url==='/__collect')return send(200,await collect());
  if(req.url==='/__stop'){const value=await collect();res.once('finish',finish);send(200,value);return}
  if(req.url!=='/api')return send(404,{ok:false});
  let body='';for await(const chunk of req){body+=chunk;if(body.length>32768)return send(413,{ok:false})}
  const input=JSON.parse(body);
  if(input.engagement!==eng||input.op!=='securityJoint'||!['plan','start','status','wait','report','cancel'].includes(input.action))return send(403,{ok:false});
  if(input.id&&input.id!==jointId)return send(403,{ok:false});
  if(input.action==='start'){
   if(input.mode!=='deep'||JSON.stringify(input.steps)!=='["semgrep"]'||typeof input.requestId!=='string'||startRequest&&startRequest!==input.requestId)return send(403,{ok:false,error:'Only one owned synthetic scan is allowed'});
   startRequest=input.requestId;
  }
  const event={action:input.action,section:input.section??null,requestId:input.requestId??null,id:input.id??null,cursorUsed:!!input.cursor,outcome:'pending'};events.push(event);
  let result;try{result=await call(input);event.outcome=result.ok?'returned-ok':'returned-error'}catch(error){event.outcome='threw';event.error=String(error.message);throw error}
  if(input.action==='start'&&result.ok)jointId=result.task.id;
  send(200,result);
 }catch(error){send(500,{ok:false,error:String(error.message)})}
});
let timer,evidence;
try{
 await new Promise((resolve,reject)=>{ui.once('error',reject);ui.listen(0,'127.0.0.1',resolve)});
 console.log(JSON.stringify({browserReady:true,port:ui.address().port,engagement:eng,fixtureFiles:Object.keys(fixture).length}));
 timer=setTimeout(finish,1200000);await done;evidence=await collect();
}finally{
 if(timer)clearTimeout(timer);
 if(ui.listening){ui.closeAllConnections();await new Promise(resolve=>ui.close(resolve))}
 const cleanupErrors=[];
 for(const [name,fn] of [['rpc',()=>rpc.shutdown()],['bench',()=>bench.dispose()],['store',()=>store.close()]])try{await fn()}catch(error){cleanupErrors.push(name+': '+String(error.message))}
 for(const proof of proofs)try{
  const remain=execFileSync('/usr/bin/sudo',['-n','/usr/bin/docker','ps','-aq','--filter','name=^'+proof.containerName+'$'],{encoding:'utf8',timeout:8000}).trim();
  proof.containerAbsent=!remain;if(remain)cleanupErrors.push('Owned scanner remains: '+proof.containerName);
 }catch(error){cleanupErrors.push('Container status unknown: '+proof.containerName)}
 evidence??={ok:false,error:'Final report collection failed',proofs,events};evidence.cleanupErrors=cleanupErrors;
 fs.writeFileSync(join(root,'final-evidence.json'),JSON.stringify(evidence));
 console.log(JSON.stringify({stopped:true,containersAbsent:proofs.filter(p=>p.containerAbsent).length,cleanupErrors}));
}
