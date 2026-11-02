import {validParserTextSummary} from './personal-security-parser-text.mjs';
import {createHash} from 'node:crypto';
import {securityReportSummary} from './personal-security-report.mjs';
import {decorateFinding} from './personal-security-identity.mjs';
import {redactText} from './personal-evidence-redaction.mjs';
const text=(v,n=240)=>typeof v==='string'?redactText(v).slice(0,n):null;
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const keys=(v,allowed)=>{if(Object.keys(v).some(k=>!allowed.includes(k)))throw Error('此操作包含不支持的字段')};
const authView=value=>value?{profile:text(value.profile,48),state:value.state==='verified'?'verified':'unconfirmed',before:value.before===true,after:value.after===true,scannerBefore:value.scannerBefore===true,scannerAfter:value.scannerAfter===true,checkedRequests:value.checkedRequests===2?2:0,limitation:'仅核对扫描前后，不保证全程持续登录'}:null;
const runView=r=>({id:r.id,tool:r.tool,state:r.state,complete:r.complete,profileRevision:r.profile_revision,startedAt:r.started_at,finishedAt:r.finished_at,error:text(r.error_code,240),coveredFiles:r.details?.coveredFiles??null,authentication:authView(r.details?.authentication),supplemental:validParserTextSummary(r.details?.supplemental)?r.details.supplemental:null,diagnostics:r.details?.diagnostics?{total:r.details.diagnostics.total,items:r.details.diagnostics.items.slice(0,3).map(d=>({...d,path:text(d.path,160)})),truncated:r.details.diagnostics.truncated||r.details.diagnostics.items.length>3}:null});
const readRun=r=>runView({...r,details:JSON.parse(r.details)});
const findingView=f=>({id:f.id,revision:f.revision,status:f.status,severity:f.severity,tool:f.tool,rule:text(f.rule,180),title:text(f.title,160),location:text(f.location,300),subject:f.subject?{name:text(f.subject.name,120),version:text(f.subject.version,80),path:text(f.subject.path,180)}:null,identityVersion:f.identityVersion,fieldsShortened:true});
const budget=value=>{if(Buffer.byteLength(JSON.stringify(value),'utf8')>6000)throw Error('结果超过模型响应上限，请使用更小分页或界面导出');return value};
export function securityModelWire(original,safe){
 const controls=value=>({engagement:value?.engagement,pair:[value?.baseRunId,value?.currentRunId],allowedTools:value?.profile?.tools,cursor:value?.page?.nextCursor,section:value?.page?.section,run:value?.run&&[value.run.id,value.run.state,value.run.tool],runs:value?.runs?.map(r=>[r.id,r.state,r.tool]),items:value?.page?.items?.map(r=>[r.id,r.status??r.state,r.tool])});
 if(JSON.stringify(controls(original))!==JSON.stringify(controls(safe)))return JSON.stringify({ok:false,error:'项目脱敏规则遮蔽了任务或分页标识；请从安全审计页面核对并导出完整报告，不要猜测或重试改写标识。'});
 const wire=JSON.stringify(safe);
 return Buffer.byteLength(wire,'utf8')<=6000?wire:JSON.stringify({ok:false,error:'项目脱敏后的结果超过6000字节；请减小limit，或从安全审计页面导出完整报告。'});
}
export async function modelSecurityResult(bench,eng,input){
 const {op,...args}=input;
 if(op==='securityPreflight')return budget(bench.preflight(eng,args));
 if(op==='securitySource')return budget(bench.source(eng,args));
 if(op==='securityKaliCheck')return budget(await bench.kaliCheck(eng,args));
 if(op==='securityStart'||op==='securityCancel'){if(op==='securityCancel')keys(args,['id']);const value=op==='securityStart'?bench.start(eng,args):await bench.cancel(eng,args.id);return{ok:true,run:value,execution:'asynchronous',next:'使用wait和返回任务id等待；超时仍运行时继续同一id，不能重发start。VM独立后台持有任务，会话或headless退出不取消；VM关机或后台服务停止仍会中断。'}}
 if(op==='securityWait'){const result=await bench.wait(eng,args);return budget({...result,run:runView(result.run),next:result.timedOut?'同一任务仍由VM后台持有；可退出会话，随后用原id查询或继续wait，不能重发start。':'任务已到终态；partial不等于完整覆盖，可用report分页读取。'})}
 if(op==='securityCompare'){const value=bench.compare(eng,args);if(!value.available)return value;return budget({ok:true,engagement:eng,available:true,baseRunId:value.baseRunId,currentRunId:value.currentRunId,summary:value.summary,notice:text(value.notice,400),details:'对比明细和Markdown请在安全审计页面下载；统计来自完整已保存快照。'})}
 if(!['securityStatus','securityReport'].includes(op))throw Error('模型审计操作无效');
 keys(args,op==='securityStatus'?[]:['section','cursor','limit']);
 const db=bench.db(eng);db.exec('SAVEPOINT security_model_read');
 try{
  const totals=securityReportSummary(db),profile=bench.profile(db),summary={findings:totals.findings,runs:totals.runs},base={ok:true,engagement:eng,totalFindings:summary.findings.total,totalRuns:summary.runs.total,summary,observedAt:new Date().toISOString(),scopeCoverage:'仅当前绑定项目已授权扫描；命中须验证，部分覆盖或未命中均不表示安全。'};
  let result;
  if(op==='securityStatus'){
   const runtime=bench.toolStatus(),tools=Object.fromEntries(['semgrep','trivy','zap'].map(tool=>[tool,{ready:runtime[tool]?.ready===true,version:text(runtime[tool]?.version,80),reason:text(runtime[tool]?.reason,200)}]));
   result={...base,authSession:profile?.authProfile?bench.authStatus(profile.authProfile,profile.url):null,profile:profile?{...profile,repoRoot:text(profile.repoRoot,500),url:text(profile.url,300)}:null,tools,runs:db.prepare('SELECT * FROM security_run ORDER BY rowid DESC LIMIT 3').all().map(readRun),runsPreviewLimit:3,next:'长任务用wait(id,waitSeconds=30)；发现和更早任务用report(section=findings或runs,cursor)。完整Markdown在安全审计页导出。'};
   while(Buffer.byteLength(JSON.stringify(result))>6000&&result.runs.length)result.runs.pop();
  }else{
   const section=args.section??'findings',limit=args.limit??5;if(!['findings','runs'].includes(section)||!Number.isSafeInteger(limit)||limit<1||limit>10)throw Error('section须为findings或runs，limit须为1–10');
   const version=hash({eng,section,scope:profile?.revision??0,findings:db.prepare('SELECT COUNT(*) n,MAX(id) last,SUM(revision) revision FROM security_finding').get(),runs:db.prepare('SELECT state,COUNT(*) n,MAX(rowid) last,MAX(finished_at) finished FROM security_run GROUP BY state').all()});
   let after=0;if(args.cursor!==undefined){if(typeof args.cursor!=='string'||args.cursor.length>512||!/^[A-Za-z0-9_-]+$/.test(args.cursor))throw Error('分页cursor无效');let c;try{c=JSON.parse(Buffer.from(args.cursor,'base64url').toString())}catch{throw Error('分页cursor无效')}if(!c||typeof c!=='object'||Array.isArray(c)||!Number.isSafeInteger(c.after)||c.after<0||typeof c.version!=='string')throw Error('分页cursor无效');if(c.version!==version)throw Error('项目资料已变化或cursor不属于此页，请从无cursor的第一页重新读取');after=c.after}
   const rows=section==='findings'?db.prepare('SELECT * FROM security_finding WHERE id>? ORDER BY id LIMIT ?').all(after,limit+1):db.prepare('SELECT rowid AS page_id,* FROM security_run WHERE rowid>? ORDER BY rowid LIMIT ?').all(after,limit+1);
   let used=Math.min(limit,rows.length);const make=()=>({...base,page:{section,items:rows.slice(0,used).map(r=>section==='findings'?findingView(decorateFinding(db,r)):readRun(r)),nextCursor:rows.length>used?Buffer.from(JSON.stringify({after:section==='findings'?rows[used-1].id:rows[used-1].page_id,version})).toString('base64url'):null,complete:rows.length<=used,total:section==='findings'?base.totalFindings:base.totalRuns},reportFormat:'bounded structured pages; display fields may be shortened; full Markdown and evidence available via safety audit page export'});
   result=make();while(Buffer.byteLength(JSON.stringify(result))>6000&&used>1){used--;result=make()}
  }
  budget(result);db.exec('RELEASE security_model_read');return result;
 }catch(error){db.exec('ROLLBACK TO security_model_read;RELEASE security_model_read');throw error}
}
