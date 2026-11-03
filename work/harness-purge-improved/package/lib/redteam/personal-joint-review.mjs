import {createHash,randomUUID} from 'node:crypto';
import {mkdirSync,readdirSync} from 'node:fs';
import {join} from 'node:path';
import {createReviewSnapshot,verifyReviewSnapshot,safeSnapshotName} from './personal-review-snapshot.mjs';
import {redactText} from './personal-evidence-redaction.mjs';
import {inspectRuntimeSource,runtimeSourceSummary} from './personal-runtime-source.mjs';
import {reviewScopePathReady} from './personal-security-review.mjs';
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const text=(v,n=300)=>redactText(String(v??'')).slice(0,n);
const only=(v,keys)=>{if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).some(k=>!keys.includes(k)))throw Error('联合审查参数无效')};
const identifier=v=>{if(typeof v!=='string'||!/^[A-Za-z0-9_-]{8,100}$/.test(v))throw Error('联合任务编号无效');return v};
const terminal=v=>!['running','cancelling'].includes(v);
const stamp=()=>new Date().toISOString();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const adapters=['kali','rea','pentagi'];
const defaultAdapter=async(...args)=>(await import('./personal-joint-adapter.mjs')).requestManagedAdapter(...args);
const defaultKali=async(...args)=>(await import('./personal-joint-kali.mjs')).requestKaliProject(...args);
const schema=`CREATE TABLE IF NOT EXISTS security_joint(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,request_hash TEXT NOT NULL,state TEXT NOT NULL,started_at TEXT NOT NULL,data TEXT NOT NULL);CREATE TABLE IF NOT EXISTS security_joint_rejection(request_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,message TEXT NOT NULL);CREATE TABLE IF NOT EXISTS security_joint_pending(id TEXT PRIMARY KEY)`;
export function jointModelWire(original,safe){
 const control=value=>({engagement:value?.engagement,requestState:value?.requestState,profileRevision:value?.profileRevision,availableSteps:value?.availableSteps,webTarget:value?.webTarget,kaliAllowed:value?.kaliAllowed,reaAllowed:value?.reaAllowed,pentagiAllowed:value?.pentagiAllowed,task:value?.task&&{...value.task,notice:undefined,problem:undefined,steps:value.task.steps?.map(s=>({...s,problem:undefined}))},page:value?.page&&{...value.page,items:value.page.items?.map(f=>({path:f.path,sha256:f.sha256,originalSha256:f.originalSha256,sourceTask:f.sourceTask,snapshotId:f.snapshotId,status:f.status,tool:f.tool,rule:f.rule,location:f.location,code:f.code,line:f.line,evidenceKind:f.evidenceKind,repositorySnapshotId:f.repositorySnapshotId,targetOrigin:f.targetOrigin,appRevision:f.appRevision,runtimeSource:f.runtimeSource}))}});
 if(JSON.stringify(control(original))!==JSON.stringify(control(safe)))return JSON.stringify({ok:false,error:'项目脱敏规则遮蔽了联合任务、文件哈希或分页标识，请核对脱敏规则；不要猜测或改写控制标识。'});
 const wire=JSON.stringify(safe);return Buffer.byteLength(wire)<=6000?wire:JSON.stringify({ok:false,error:'项目脱敏后的联合结果超过6000字节，请减小limit后读取原任务。'});
}
export class JointReview{
 constructor(bench,{kali=defaultKali,adapter=defaultAdapter,runtimeSource=inspectRuntimeSource}={}){this.bench=bench;this.kali=kali;this.adapter=adapter;this.runtimeSource=runtimeSource;this.initialized=new Set();this.active=null;this.closed=false}
 db(eng){const db=this.bench.db(eng);if(!this.initialized.has(eng)){db.exec(schema);db.prepare("UPDATE security_joint SET state='interrupted' WHERE state IN ('running','cancelling')").run();this.initialized.add(eng)}return db}
 load(eng,id){identifier(id);const row=this.db(eng).prepare('SELECT * FROM security_joint WHERE id=?').get(id);if(!row)throw Error('当前项目没有该联合任务');return{...JSON.parse(row.data),state:row.state}}
 save(eng,data){const db=this.db(eng);db.exec('SAVEPOINT joint_save');try{db.prepare('UPDATE security_joint SET state=?,data=? WHERE id=?').run(data.state,JSON.stringify(data),data.id);if(data.steps.some(s=>adapters.includes(s.tool)&&s.id&&s.cleanupVerified!==true))db.prepare('INSERT OR IGNORE INTO security_joint_pending VALUES(?)').run(data.id);else db.prepare('DELETE FROM security_joint_pending WHERE id=?').run(data.id);db.exec('RELEASE joint_save')}catch(error){db.exec('ROLLBACK TO joint_save;RELEASE joint_save');throw error}}
 scope(eng,revision){const p=this.bench.profile(this.db(eng));if(!p||p.revision!==revision||Date.parse(p.expiresAt)<=Date.now())throw Error('项目范围未授权、已过期或已变化');return p}
 plan(eng,input={}){
  only(input,[]);const value=this.bench.read(eng,{force:true}),p=value.profile;
  const validScope=!!p&&Date.parse(p.expiresAt)>Date.now()&&reviewScopePathReady(p);
  let projectHints={rootFiles:[],truncated:false,scope:'visible-root-file-names-only'};try{const files=validScope?readdirSync(p.repoRoot,{withFileTypes:true}).filter(f=>f.isFile()&&safeSnapshotName(f.name)):[];projectHints={...projectHints,rootFiles:files.slice(0,20).map(f=>f.name.slice(0,120)),truncated:files.length>20}}catch{projectHints.unavailable=true}
  return{ok:true,engagement:eng,profileRevision:p?.revision??0,projectHints,availableSteps:validScope?['semgrep','trivy','zap'].filter(tool=>p.tools.includes(tool)&&value.tools[tool]?.ready&&(tool!=='zap'||!!p.url)):[],webTarget:validScope&&p.tools.includes('zap')&&p.url?{origin:p.url,mode:'loopback-baseline',appRevision:'not-proven',authenticated:!!p.authProfile}:null,kaliAllowed:validScope&&p.jointKali===true,reaAllowed:validScope&&p.jointRea===true,pentagiAllowed:validScope&&p.jointPentagi===true,optionalAdapters:{rea:'static-javascript',reverseSkill:'pinned-method-route',pentagi:'isolated-static-review'},limits:{maxSeconds:900,maxFiles:1000,maxBytes:8388608,modelCalls:16,maxOutputTokensPerCall:2048},notice:'源码、ZAP本地HTTP基线、Kali离线Bandit、REA静态JavaScript图及PentAGI隔离静态子任务。ZAP复用已保存工具和明确VM回环网址，发送请求但不启动项目；运行中应用版本与源码副本关系未证明。其他交接须分别保存授权；PentAGI至多16次请求、每次2048输出tokens，无货币金额硬上限。未选工具和人工项不代表已覆盖。'};
 }
 start(eng,input){
  const rid=identifier(input?.requestId),db=this.db(eng),requestHash=hash(input),rejected=db.prepare('SELECT * FROM security_joint_rejection WHERE request_id=?').get(rid);
  if(rejected)throw Error(rejected.request_hash===requestHash?rejected.message:'重复请求内容不同');
  try{return this.submit(eng,input)}catch(error){if(!db.prepare('SELECT id FROM security_joint WHERE request_id=?').get(rid))db.prepare('INSERT OR IGNORE INTO security_joint_rejection VALUES(?,?,?)').run(rid,requestHash,text(error?.message));throw error}
 }
 submit(eng,input){
  only(input,['requestId','profileRevision','steps','budgetSeconds']);const rid=identifier(input.requestId),db=this.db(eng),requestHash=hash(input),prior=db.prepare('SELECT id,request_hash FROM security_joint WHERE request_id=?').get(rid);
  if(prior){if(prior.request_hash!==requestHash)throw Error('重复请求内容不同');return this.view(this.load(eng,prior.id))}
  if(this.bench.runtimeUI?.transitionBusy())throw Error('应用启动或停止尚未确认，请先核对原请求');
  if(this.closed||this.bench.disposed||this.active||this.bench.active||this.bench.blocked)throw Error('工作台已有任务或停止状态未确认，请核对原任务');
  for(const project of this.bench.store.listEngagements()){
   if(this.db(project.id).prepare('SELECT id FROM security_joint_pending LIMIT 1').get())throw Error('已有受管子任务停止未确认；请查询或取消原任务，不启动新请求');
  }
  const profile=this.scope(eng,input.profileRevision),steps=input.steps,budget=input.budgetSeconds??360;
  if(!Array.isArray(steps)||!steps.length||steps.length>6||new Set(steps).size!==steps.length||steps.some(s=>!['semgrep','trivy','zap',...adapters].includes(s))||steps.includes('zap')&&!profile.url||!Number.isSafeInteger(budget)||budget<30||budget>900)throw Error('联合步骤、本地网址或30–900秒预算无效');
  const runtime=this.bench.toolStatus({force:true});for(const step of steps){if(adapters.includes(step)){const key={kali:'jointKali',rea:'jointRea',pentagi:'jointPentagi'}[step];if(profile[key]!==true)throw Error('请先在安全审计页保存该工具的副本交接授权')}else if(!profile.tools.includes(step)||!runtime[step]?.ready)throw Error('扫描器不在已授权范围或未就绪')}
  const id=randomUUID(),data={id,engagement:eng,scopeRevision:profile.revision,state:'running',startedAt:stamp(),finishedAt:null,deadline:new Date(Math.min(Date.now()+budget*1000,Date.parse(profile.expiresAt))).toISOString(),budgetSeconds:budget,steps:steps.map(tool=>({tool,state:'pending'})),webTarget:steps.includes('zap')?{origin:profile.url,mode:'loopback-baseline',appRevision:'not-proven',authenticated:!!profile.authProfile}:null,snapshot:null,findings:[],cleanupVerified:false,problem:null};
  db.prepare('INSERT INTO security_joint VALUES(?,?,?,?,?,?)').run(id,rid,requestHash,data.state,data.startedAt,JSON.stringify(data));
  const active={id,eng,controller:new AbortController(),data,profile,shutdown:false};this.active=active;
  active.promise=Promise.resolve().then(()=>this.execute(active));return this.view(data);
 }
 async execute(active){
  const {data,profile,eng,controller}=active;let timer;
  const check=()=>{if(controller.signal.aborted)throw Error('联合任务已取消或预算到期');this.scope(eng,data.scopeRevision);if(Date.now()>=Date.parse(data.deadline)){active.expired=true;controller.abort();throw Error('联合预算到期')}};
  try{
   timer=setTimeout(()=>{active.expired=true;controller.abort()},Math.max(1,Date.parse(data.deadline)-Date.now()));check();
   const parent=join(this.bench.store.dirOf(eng),'runs','joint');mkdirSync(parent,{recursive:true,mode:0o700});
   data.snapshot=createReviewSnapshot(profile,join(parent,data.id),{sanitize:value=>this.bench.store.redactResult(eng,{text:value}).text,sanitizeKnown:value=>this.bench.store.redactResult(eng,value,{knownOnly:true})});this.save(eng,data);
   for(const step of data.steps){
    check();verifyReviewSnapshot(data.snapshot);step.state='running';this.save(eng,data);
    if(step.tool==='kali')await this.runKali(active,step);
    else if(adapters.includes(step.tool))await this.runAdapter(active,step);
    else{
     const beforeRuntime=step.tool==='zap'?await this.runtimeSource(eng,profile,data.snapshot):null;check();
     const run=this.bench.start(eng,{requestId:'joint-'+data.id+'-'+step.tool,profileRevision:data.scopeRevision,tool:step.tool},active);step.id=run.id;this.save(eng,data);
     const child=this.bench.active,abort=()=>child?.controller.abort();controller.signal.addEventListener('abort',abort,{once:true});if(controller.signal.aborted)abort();
     try{await child?.promise}finally{controller.signal.removeEventListener('abort',abort)}
     const row=this.bench.db(eng).prepare('SELECT * FROM security_run WHERE id=?').get(run.id);step.state=row.state;step.complete=row.complete===1;step.details=JSON.parse(row.details);step.problem=row.error_code;
     const findings=this.bench.db(eng).prepare('SELECT data FROM security_joint_finding WHERE run_id=? ORDER BY ordinal').all(run.id).map(row=>JSON.parse(row.data));
     data.findings.push(...findings.map(f=>({...f,status:'unverified',sourceTask:run.id,snapshotId:step.tool==='zap'?null:data.snapshot.id,...(step.tool==='zap'?{evidenceKind:'live-http',repositorySnapshotId:data.snapshot.id,targetOrigin:profile.url}:{})})));
     if(step.tool==='zap'){const afterRuntime=await this.runtimeSource(eng,profile,data.snapshot),runtimeSource=runtimeSourceSummary(beforeRuntime,afterRuntime);if(!['completed','partial'].includes(row.state)&&runtimeSource.state==='managed-source-copy-matched')runtimeSource.state='unconfirmed';const appRevision=runtimeSource.state==='managed-source-copy-matched'?runtimeSource.state:'not-proven';data.webTarget.appRevision=appRevision;step.coverageScope='live-loopback-http-responses';step.artifacts=[{tool:'zap',evidenceKind:'live-http',targetOrigin:profile.url,repositorySnapshotId:data.snapshot.id,snapshotId:null,appRevision,runtimeSource,coverageKey:row.coverage_key,startedAt:row.started_at,finishedAt:row.finished_at,scanState:row.state,resultAvailable:['completed','partial'].includes(row.state),authentication:step.details.authentication??{state:profile.authProfile?'unconfirmed':'not-configured'},claim:['completed','partial'].includes(row.state)?(appRevision==='managed-source-copy-matched'?'本地HTTP基线；已核对受管源码副本前后身份，命中待验证，依赖及内存行为未证明。':'本地HTTP基线结果；运行版本与源码副本关系未证明，命中待验证。'):'未取得可用扫描结果；不能据此判断认证或HTTP安全。'}]}
    }
    verifyReviewSnapshot(data.snapshot);this.save(eng,data);
    if(this.bench.blocked)throw Error('子任务停止未确认');
   }
   check();data.cleanupVerified=data.steps.every(s=>!adapters.includes(s.tool)||s.cleanupVerified===true);data.state=!data.cleanupVerified?'unconfirmed':data.steps.every(s=>s.state==='completed')?'completed':'partial';
  }catch(error){
   const remote=data.steps.find(s=>adapters.includes(s.tool)&&s.id&&s.cleanupVerified!==true);
   if(remote){try{const result=await this.callAdapter(remote.tool,'cancel',remote.id,{});this.adapterResult(data,remote,result)}catch{remote.state='unconfirmed';remote.cleanupVerified=false}}
   data.cleanupVerified=!this.bench.blocked&&data.steps.every(s=>!adapters.includes(s.tool)||!s.id||s.cleanupVerified===true);
   data.state=active.shutdown?'interrupted':!data.cleanupVerified?'unconfirmed':active.expired?'timed-out':controller.signal.aborted?'cancelled':'failed';data.problem=text(error?.message);
  }finally{
   clearTimeout(timer);data.finishedAt=stamp();for(const step of data.steps)if(step.state==='pending')step.state='not-run';
   this.save(eng,data);if(this.active===active)this.active=null;
  }
 }
 async runKali(active,step){
  const {data,controller}=active;step.id='joint-'+hash([active.eng,data.id]).slice(0,40);this.save(active.eng,data);
  let result=await this.kali('run',step.id,{snapshot:data.snapshot,seconds:Math.max(1,Math.min(90,Math.floor((Date.parse(data.deadline)-Date.now())/1000)))});
  while(result.state==='running'){
   this.kaliResult(data,step,result);this.save(active.eng,data);
   if(controller.signal.aborted)throw Error('联合任务要求停止Kali子任务');
   await sleep(200);result=await this.kali('status',step.id,{});
  }
  this.kaliResult(data,step,result);if(step.state==='unconfirmed'||step.cleanupVerified!==true)throw Error('Kali状态或停止未确认，请核对同一任务，不能另发新任务');
 }
 callAdapter(tool,...args){return tool==='kali'?this.kali(...args):this.adapter(tool,...args)}
 async runAdapter(active,step){
  const {data,controller}=active;step.id='joint-'+hash([active.eng,data.id,step.tool]).slice(0,40);this.save(active.eng,data);
  let result=await this.adapter(step.tool,'run',step.id,{snapshot:data.snapshot,seconds:Math.max(1,Math.min(600,Math.floor((Date.parse(data.deadline)-Date.now())/1000)))});
  while(result.state==='running'){
   this.adapterResult(data,step,result);this.save(active.eng,data);if(controller.signal.aborted)throw Error('受管工具需要停止');await sleep(200);result=await this.adapter(step.tool,'status',step.id,{});
  }
  this.adapterResult(data,step,result);if(step.cleanupVerified!==true)throw Error('受管工具停止未确认');
 }
 adapterResult(data,step,result){
  if(step.tool==='kali')return this.kaliResult(data,step,result);
  if(!result||result.id!==step.id||result.snapshotId!==data.snapshot.id||!['running','completed','partial','cancelled','timed-out','interrupted','failed','unavailable','unconfirmed'].includes(result.state))throw Error('受管子任务回执不匹配');
  if(!Number.isSafeInteger(result.checkedFiles??0)||(result.checkedFiles??0)<0||(result.checkedFiles??0)>data.snapshot.files.length||!Number.isSafeInteger(result.modelCalls??0)||(result.modelCalls??0)>16||!Array.isArray(result.artifacts)||result.artifacts.length>20)throw Error('受管子任务证据无效');
  step.state=result.state;step.cleanupVerified=result.cleanupVerified===true;step.version=text(result.version,80);step.checkedFiles=result.checkedFiles??0;step.problem=text(result.problem);step.modelCalls=result.modelCalls??0;step.artifacts=result.artifacts;step.complete=false;step.coverageScope=step.tool==='rea'?'handed-off-javascript-static-graph':'model-review-coverage-unknown';
 }
 kaliResult(data,step,result){
  if(!result||result.id!==step.id||result.snapshotId!==data.snapshot.id||!['running','completed','partial','cancelled','timed-out','interrupted','failed','unavailable','unconfirmed'].includes(result.state))throw Error('Kali子任务回执不匹配');
  step.state=result.state;step.cleanupVerified=result.cleanupVerified===true;step.version=text(result.version,80);step.checkedFiles=result.checkedFiles??0;step.problem=text(result.problem);step.diagnostics={total:result.diagnosticsTotal??result.diagnostics?.length??0,items:result.diagnostics??[],truncated:result.diagnosticsTruncated===true};
  step.coverageScope='handed-off-python-files';step.eligibleFiles=data.snapshot.files.filter(f=>f.path.endsWith('.py')).length;step.complete=result.state==='completed'&&step.checkedFiles===step.eligibleFiles&&step.diagnostics.total===0;
  if(result.state==='completed'&&!step.complete){step.state='partial';step.problem='Kali回执未证明全部交接Python文件已检查'}
  if(!['running','unconfirmed'].includes(result.state)){
   if(!Array.isArray(result.findings)||result.findings.length>2000)throw Error('Kali发现回执无效');
   data.findings=data.findings.filter(f=>f.sourceTask!==step.id);const allowed=new Set(data.snapshot.files.map(f=>f.path));for(const f of result.findings){if(!allowed.has(f.path)||!Number.isSafeInteger(f.line)||f.line<1||!/^B[0-9]{3}$/.test(f.rule))throw Error('Kali发现超出交接范围');data.findings.push({tool:'kali-bandit',rule:f.rule,title:text(f.title,400),severity:text(f.severity,20),location:f.path+':'+f.line,evidence:'Kali离线静态命中，未执行项目代码',status:'unverified',sourceTask:step.id,snapshotId:data.snapshot.id})}
  }
 }
 view(data){
  const diagnosticSummary=s=>{const d=s.tool==='kali'?s.diagnostics:s.details?.diagnostics;return d?{total:d.total,retained:d.items.length,truncated:d.truncated}:null};
  return{id:data.id,engagement:data.engagement,state:data.state,scopeRevision:data.scopeRevision,startedAt:data.startedAt,finishedAt:data.finishedAt,deadline:data.deadline,budgetSeconds:data.budgetSeconds,modelCalls:data.steps.reduce((n,s)=>n+(s.modelCalls??0),0),cleanupVerified:data.cleanupVerified,problem:data.problem,webTarget:data.webTarget??null,
   snapshot:data.snapshot?{id:data.snapshot.id,files:data.snapshot.files.length,bytes:data.snapshot.bytes,git:data.snapshot.git,excluded:data.snapshot.excluded.total,exclusionsRetained:data.snapshot.excluded.items.length,exclusionsTruncated:data.snapshot.excluded.truncated,redactedFiles:data.snapshot.redactedFiles}:null,
   steps:data.steps.map(s=>({tool:s.tool,id:s.id??null,state:s.state,complete:s.complete??false,coverageScope:s.coverageScope??'scanner-reported-files',eligibleFiles:s.eligibleFiles??null,cleanupVerified:s.cleanupVerified??null,version:s.version??s.details?.version??null,checkedFiles:s.checkedFiles??s.details?.coveredFiles??0,problem:s.problem??null,diagnostics:diagnosticSummary(s),modelCalls:s.modelCalls??0,artifacts:s.artifacts?.length??0})),findings:data.findings.length,coverageComplete:false,manualChecks:['authentication','authorization','business-logic','architecture'],notice:'完成表示已选步骤结束；命中保持待验证。Git未提交状态未探测，按逐文件哈希固定实际内容。脱敏/排除文件、手工项与未选工具仍未覆盖；REA仅静态JavaScript图；PentAGI输出是未验证模型结论，调用次数预算不等同货币金额上限。'};
 }
 status(eng,input){only(input,['id','requestId']);if(input.id&&input.requestId)throw Error('只提供任务ID或请求号');const db=this.db(eng),data=input.id?this.load(eng,input.id):(()=>{const row=input.requestId?db.prepare('SELECT id FROM security_joint WHERE request_id=?').get(identifier(input.requestId)):db.prepare('SELECT id FROM security_joint ORDER BY rowid DESC LIMIT 1').get();return row?this.load(eng,row.id):null})(),rejected=!data&&input.requestId?db.prepare('SELECT message FROM security_joint_rejection WHERE request_id=?').get(input.requestId):null;return{ok:true,engagement:eng,task:data?this.view(data):null,requestState:data?'accepted':rejected?'rejected':'unknown',...(rejected?{rejection:rejected.message}:{})}}
 async wait(eng,input){
  only(input,['id','waitSeconds']);const seconds=input.waitSeconds??15;if(!Number.isSafeInteger(seconds)||seconds<0||seconds>30)throw Error('等待必须为0–30秒');const first=this.load(eng,input.id),active=this.active;let timer;
  try{if(!terminal(first.state)&&active?.id===input.id&&active.eng===eng&&seconds)await Promise.race([active.promise,new Promise(resolve=>{timer=setTimeout(resolve,seconds*1000)})])}finally{clearTimeout(timer)}
  const task=this.view(this.load(eng,input.id));return{ok:true,engagement:eng,task,stillRunning:!terminal(task.state)};
 }
 async cancel(eng,input){
  only(input,['id']);const data=this.load(eng,input.id),active=this.active;
  if(active?.id===input.id&&active.eng===eng){active.controller.abort();await active.promise;return this.status(eng,input)}
  // Restart never replays a child. An explicit cancellation may reconcile the original remote ID.
  for(const step of data.steps.filter(s=>adapters.includes(s.tool)&&s.id&&s.cleanupVerified!==true)){try{this.adapterResult(data,step,await this.callAdapter(step.tool,'cancel',step.id,{}));data.cleanupVerified=data.steps.every(s=>!adapters.includes(s.tool)||!s.id||s.cleanupVerified===true);data.state=data.cleanupVerified?'interrupted':'unconfirmed'}catch{data.cleanupVerified=false;data.state='unconfirmed'}this.save(eng,data)}
  return this.status(eng,input);
 }
 report(eng,input){
  only(input,['id','section','cursor','limit']);const data=this.load(eng,input.id),section=input.section??'findings',limit=input.limit??5;if(!['findings','files','exclusions','diagnostics','artifacts'].includes(section)||!Number.isSafeInteger(limit)||limit<1||limit>10)throw Error('报告分页参数无效');
  const diagnostics=data.steps.flatMap(s=>(s.tool==='kali'?s.diagnostics:s.details?.diagnostics)?.items?.map(d=>({...d,tool:s.tool,sourceTask:s.id}))??[]);
  const unique=[...new Map(data.findings.map(f=>[hash([f.tool,f.rule,f.location,f.sourceTask]),f])).values()],rows=section==='findings'?unique:section==='files'?data.snapshot?.files??[]:section==='diagnostics'?diagnostics:section==='artifacts'?data.steps.flatMap(s=>(s.artifacts??[]).map(a=>({...a,sourceTask:s.id,snapshotId:s.tool==='zap'?null:data.snapshot.id}))):data.snapshot?.excluded.items??[],version=hash([data.id,data.state,data.finishedAt,rows]);let after=0;
  if(input.cursor){let cursor;try{cursor=JSON.parse(Buffer.from(input.cursor,'base64url').toString())}catch{throw Error('报告cursor无效')}if(input.cursor.length>512||cursor.version!==version||!Number.isSafeInteger(cursor.after)||cursor.after<0||cursor.after>rows.length)throw Error('报告已变化或cursor不属于当前任务');after=cursor.after}
  let count=Math.min(limit,rows.length-after),singleItem;const make=()=>({ok:true,engagement:eng,task:this.view(data),page:{section,items:singleItem??rows.slice(after,after+count),total:rows.length,complete:after+count>=rows.length,nextCursor:after+count<rows.length?Buffer.from(JSON.stringify({version,after:after+count})).toString('base64url'):null},deduplication:'同工具、同规则、同位置、同来源任务去重；跨工具证据保留，不能自动合并为已确认漏洞。'});
  let result=make();const oversized=()=>Buffer.byteLength(JSON.stringify(result))>6000;
  while(oversized()&&count>1){count--;result=make()}
  if(oversized()&&count===1&&section==='artifacts'&&Array.isArray(rows[after]?.summaries)){
   // Fit the escaped JSON page, including task metadata, without changing raw evidence or cursors.
   const item=structuredClone(rows[after]);singleItem=[item];
   while(oversized()){
    const summary=item.summaries.filter(s=>typeof s.text==='string'&&s.text.length).sort((a,b)=>Buffer.byteLength(JSON.stringify(b.text))-Buffer.byteLength(JSON.stringify(a.text)))[0];if(!summary)break;
    summary.text=Array.from(summary.text).slice(0,Math.floor(Array.from(summary.text).length/2)).join('');summary.truncated=true;item.reportTruncated=true;result=make();
   }
  }
  if(oversized())throw Error('报告条目超出预算');return result;
 }
 async dispose(){this.closed=true;const active=this.active;if(active){active.shutdown=true;active.controller.abort();await active.promise}}
}
