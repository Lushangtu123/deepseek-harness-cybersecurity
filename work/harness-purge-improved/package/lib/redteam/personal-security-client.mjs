// Self-contained factories, embedded by scripts/build-client.mjs; no import-time I/O.
export function createRuntimePanel(React,api,{storage=()=>globalThis.localStorage,exclusive=async(_eng,fn)=>fn()}={}){
 const h=React.createElement,labels={none:'尚无应用',preparing:'准备中',ready:'已就绪',stopping:'停止中',closed:'已停止 · 清理已确认',cancelled:'已取消 · 未执行',failed:'启动失败 · 清理已确认',unconfirmed:'结果待核对'};
 const identifier=()=>globalThis.crypto?.randomUUID?.()||'runtime-'+Date.now()+'-'+Math.random().toString(36).slice(2);
 return function RuntimePanel({engagement,profile,blocked=false}){
  const [entry,setEntry]=React.useState('app.py'),[seconds,setSeconds]=React.useState('360'),[preview,setPreview]=React.useState(null),[consent,setConsent]=React.useState(false),[stopConsent,setStopConsent]=React.useState(false),[status,setStatus]=React.useState(null),[pending,setPending]=React.useState(null),[busy,setBusy]=React.useState(false),[error,setError]=React.useState(''),[clock,setClock]=React.useState(Date.now()),alive=React.useRef(true),requesting=React.useRef(false),generation=React.useRef(0);
  const signature=JSON.stringify([engagement,profile?.revision,profile?.repoRoot,profile?.url,profile?.expiresAt,entry,seconds]),current=React.useRef(signature);current.current=signature;
  const key='dsh-runtime-request-v1:'+encodeURIComponent(engagement);
  const saved=()=>{const raw=storage().getItem(key);if(!raw)return null;const v=JSON.parse(raw);if(v.engagement!==engagement||typeof v.requestId!=='string'||!/^[-A-Za-z0-9_]{8,100}$/.test(v.requestId))throw Error('原应用请求提示无效，请核对后台状态');return v};
  const parsed=v=>{if(v?.ok!==true||v.engagement!==engagement)throw Error(v?.error||'应用回执与当前项目不匹配');return v};
  const accept=(v,original)=>{parsed(v);if(!alive.current)return;const actual=saved();if(JSON.stringify(actual)!==JSON.stringify(original??null)){setPending(actual);return}if(!Object.hasOwn(labels,v.phase)||typeof v.cleanupVerified!=='boolean'||original&&v.requestId!==original.requestId)throw Error('原应用状态未确认');if(!alive.current)return;setStatus(v);if(v.cleanupVerified){storage().removeItem(key);setPending(null);setStopConsent(false)}else setPending(original??(v.requestId?{engagement,requestId:v.requestId}:null))};
  const perform=async action=>{if(requesting.current)return;requesting.current=true;if(alive.current){setBusy(true);setError('')}try{await action()}catch(e){if(alive.current)setError(e?.message||'应用结果待核对')}finally{requesting.current=false;if(alive.current)setBusy(false)}};
  const refresh=()=>perform(async()=>{const original=saved();if(alive.current)setPending(original);const value=await api({op:'securityRuntime',engagement,action:'status',...(original?{requestId:original.requestId}:{})});await exclusive(engagement,()=>accept(value,original))});
  React.useEffect(()=>{alive.current=true;refresh();const timer=setInterval(()=>{if(globalThis.document?.visibilityState==='visible')refresh()},5000),ticker=setInterval(()=>setClock(Date.now()),1000);return()=>{alive.current=false;clearInterval(timer);clearInterval(ticker)}},[]);
  React.useEffect(()=>{if(blocked){generation.current++;setPreview(null);setConsent(false)}},[blocked]);
  React.useEffect(()=>{generation.current++;setPreview(null);setConsent(false);setStopConsent(false)},[profile?.revision,profile?.repoRoot,profile?.url,profile?.expiresAt]);
  const edit=(setter,value)=>{generation.current++;setPreview(null);setConsent(false);setter(value)};
  const prepare=()=>perform(async()=>{const version=++generation.current,sig=signature;setPreview(null);setConsent(false);const v=parsed(await api({op:'securityRuntime',engagement,action:'preview',profileRevision:profile.revision,entry,seconds:Number(seconds)})),p=v.preview;if(!p||p.profileRevision!==profile.revision||p.entry!==entry||p.seconds!==Number(seconds)||p.origin!==profile.url||!/^[a-f0-9]{64}$/.test(p.copySha256)||!Number.isFinite(Date.parse(p.expiresAt)))throw Error('执行副本预览无效');if(alive.current&&version===generation.current&&sig===current.current)setPreview({...p,signature:sig})});
  const validPreview=preview&&preview.signature===signature&&Date.parse(preview.expiresAt)>clock;
  const start=()=>perform(()=>exclusive(engagement,async()=>{if(blocked||!consent||!validPreview||saved())throw Error('请先核对范围、原请求并明确确认执行副本');const original={engagement,requestId:identifier(),previewId:preview.id,profileRevision:profile.revision};storage().setItem(key,JSON.stringify(original));if(alive.current){setPending(original);setConsent(false);setPreview(null)}const v=parsed(await api({op:'securityRuntime',action:'start',...original,confirm:true}));if(v.requestId!==original.requestId||v.requestState!=='accepted')throw Error('启动回执未确认，请查询原请求');if(alive.current)setStatus({phase:'preparing',requestId:original.requestId,runtime:null,cleanupVerified:false})}));
  const stop=()=>perform(()=>exclusive(engagement,async()=>{if(!stopConsent)throw Error('请明确确认停止原应用');const original=saved()??pending??(status?.requestId?{engagement,requestId:status.requestId}:null);if(!original)throw Error('没有可核对的原请求');const requestId=original.stopRequestId||identifier(),next={...original,stopRequestId:requestId};storage().setItem(key,JSON.stringify(next));setPending(next);setStopConsent(false);parsed(await api({op:'securityRuntime',engagement,action:'stop',requestId,startRequestId:original.requestId,...(status?.runtime?.id?{runtimeId:status.runtime.id}:{}),...(original.previewId?{previewId:original.previewId,profileRevision:original.profileRevision}:{}),confirm:true}));accept(await api({op:'securityRuntime',engagement,action:'status',requestId:original.requestId}),next)}));
  const active=!!pending||status&&!status.cleanupVerified&&status.requestId,source=validPreview?preview:status?.runtime,remaining=source?.expiresAt?Math.max(0,Math.ceil((Date.parse(source.expiresAt)-clock)/1000)):null;
  const button=(label,fn,disabled=false)=>h('button',{type:'button',className:'rt-btn',onClick:fn,disabled:busy||disabled},label),fact=(label,value)=>h('div',{className:'rts-field'},h('span',null,label),h('span',{style:{overflowWrap:'anywhere'}},value));
  return h('section',{className:'rt-card','aria-label':'运行应用'},h('div',{className:'rts-head'},h('h4',null,'运行应用'),h('span',{className:'rts-state',role:'status'},labels[status?.phase??'none'])),
   h('p',{className:'rts-meta'},'仅执行 VM 内已确认的 Python 标准库应用副本；不安装依赖。运行入口、容器与独立期限由既有受管运行器维护。'),
   h('div',{className:'rts-grid'},h('label',{className:'rts-field'},'Python入口',h('input',{className:'rt-input','aria-label':'Python入口',value:entry,disabled:!!active,onChange:e=>edit(setEntry,e.target.value)})),h('label',{className:'rts-field'},'运行时限（秒）',h('input',{className:'rt-input','aria-label':'运行时限',type:'number',min:30,max:900,value:active&&status?.runtime?.seconds?String(status.runtime.seconds):seconds,disabled:!!active,onChange:e=>edit(setSeconds,e.target.value)}))),
   h('div',{className:'rts-actions'},button('核对执行副本',prepare,blocked||!!active),button('核对原应用',refresh)),
   source&&h('div',null,h('div',{className:'rts-grid'},fact('项目副本',source.repoRoot),fact('VM 本地网址',source.origin),fact('入口与文件',source.entry+' · '+source.files+' 文件'),fact('独立运行期限',validPreview?source.seconds+' 秒上限（同时受项目授权到期限制）':status?.cleanupVerified?'已结束，清理已确认':remaining===null?'尚未启动':remaining>0?'约 '+remaining+' 秒':'期限已到，等待核对清理')),
    h('p',{className:'rts-meta',style:{fontFamily:'monospace',overflowWrap:'anywhere'}},'副本 SHA-256 · '+source.copySha256),validPreview&&h('p',{className:'rts-meta'},'复制 '+source.bytes+' 字节 · 排除 '+source.excluded+' 项 · 脱敏 '+source.redactedFiles+' 文件。预览有效至 '+new Date(source.expiresAt).toLocaleTimeString()),
    !validPreview&&h('p',{className:'rts-meta'},'当前完整性：'+({verified:'本次核对通过',unconfirmed:'待核对','not-checked':'尚未核对'}[source.integrity]??'尚未核对')+' · 扫描版本关联：'+(source.association?.state==='managed-source-copy-matched'?'ZAP 前后均匹配原副本':'尚无前后匹配证据'))),
   validPreview&&h('label',null,h('input',{type:'checkbox','aria-label':'确认执行此源码副本',checked:consent,disabled:busy||blocked,onChange:e=>setConsent(e.target.checked)}),' 我确认执行上述副本及本地网址，按所示期限运行。'),
   h('div',{className:'rts-actions'},button('确认启动应用',start,blocked||!!active||!validPreview||!consent)),
   active&&h('div',null,h('p',{className:'rts-meta',style:{overflowWrap:'anywhere'}},'原请求 · '+(pending?.requestId||status.requestId)),h('label',null,h('input',{type:'checkbox','aria-label':'确认停止原应用',checked:stopConsent,disabled:busy,onChange:e=>setStopConsent(e.target.checked)}),' 我确认停止或取消此原请求。'),h('div',{className:'rts-actions'},button('确认停止或核对清理',stop,!stopConsent)),h('p',{className:'rts-meta'},'回执丢失时只查询原请求；不会自动重发启动。倒计时为估算，清理以后台核对为准。')),
   (error||status?.problem)&&h('p',{className:'rts-alert',role:'alert'},error||status.problem));
 };
}

export function createJointPanel(React,api,{storage=()=>globalThis.localStorage,exclusive=async(_eng,fn)=>fn()}={}){
 const h=React.createElement,states={running:'运行中',completed:'所选步骤已结束',partial:'覆盖不完整',failed:'失败',cancelled:'已取消',interrupted:'中断',unconfirmed:'停止或结果未确认','timed-out':'预算到期',unavailable:'工具不可用','not-run':'未运行',pending:'待运行'};
 const validTask=(v,eng)=>v===null||v&&typeof v.id==='string'&&v.engagement===eng&&Object.hasOwn(states,v.state)&&Number.isSafeInteger(v.scopeRevision)&&Array.isArray(v.steps)&&v.steps.length<=6&&v.steps.every(s=>s&&['semgrep','trivy','zap','kali','rea','pentagi'].includes(s.tool)&&Object.hasOwn(states,s.state))&&Number.isSafeInteger(v.findings)&&typeof v.cleanupVerified==='boolean';
 const parse=(v,eng)=>{if(v?.ok!==true||v.engagement!==eng)throw Error(typeof v?.error==='string'?v.error:'联合回执未确认');return v};
 return function JointPanel({engagement,profile}){
  const [plan,setPlan]=React.useState(null),[task,setTask]=React.useState(null),[selected,setSelected]=React.useState([]),[busy,setBusy]=React.useState(false),[error,setError]=React.useState(''),[pending,setPending]=React.useState(false),alive=React.useRef(true),requesting=React.useRef(false);
  React.useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
  const key='dsh-joint-request-v1:'+encodeURIComponent(engagement);
  const saved=()=>{const raw=storage().getItem(key);if(!raw)return null;const v=JSON.parse(raw);if(v?.engagement!==engagement||typeof v.requestId!=='string'||!/^[A-Za-z0-9_-]{8,100}$/.test(v.requestId))throw Error('联合恢复提示无效，请核对后台原任务');return v};
  const accept=v=>{parse(v,engagement);if(!validTask(v.task,engagement))throw Error('联合任务回执与项目不匹配');if(alive.current)setTask(v.task);return v.task};
  const perform=async operation=>{
   if(requesting.current)return;requesting.current=true;if(alive.current){setBusy(true);setError('')}
   try{await operation()}catch(e){if(alive.current)setError(String(e?.message||'联合结果未确认'))}finally{requesting.current=false;if(alive.current)setBusy(false)}
  };
  const refresh=()=>perform(async()=>{
   const next=parse(await api({op:'securityJoint',engagement,action:'plan'}),engagement);
   if(!Number.isSafeInteger(next.profileRevision)||!Array.isArray(next.availableSteps)||next.availableSteps.some(s=>!['semgrep','trivy','zap'].includes(s))||typeof next.kaliAllowed!=='boolean')throw Error('联合范围资料无效');
   if(alive.current){setPlan(next);setSelected([...next.availableSteps.filter(s=>s!=='zap'),...(next.kaliAllowed?['kali']:[])])}
   const original=saved(),result=await api({op:'securityJoint',engagement,action:'status',...(original?{requestId:original.requestId}:{})}),current=accept(result);
   if(original&&(current||result.requestState==='rejected'))storage().removeItem(key);if(alive.current){setPending(!!original&&!current&&result.requestState!=='rejected');if(result.requestState==='rejected')setError('原启动请求未受理：'+String(result.rejection??'请核对范围后重新提交'))}
  });
  const start=()=>perform(()=>exclusive(engagement,async()=>{
   if(saved()){if(alive.current)setPending(true);throw Error('已有启动请求待核对，请先查询原任务，不重发启动')}
   const request={op:'securityJoint',engagement,action:'start',profileRevision:profile.revision,steps:selected,budgetSeconds:360,requestId:globalThis.crypto?.randomUUID?.()||'joint-'+Date.now()+'-'+Math.random().toString(36).slice(2)};
   storage().setItem(key,JSON.stringify(request));if(alive.current)setPending(true);
   const current=accept(await api(request));if(!current)throw Error('启动未返回任务ID');storage().removeItem(key);if(alive.current)setPending(false);
  }));
  const update=action=>perform(async()=>accept(await api({op:'securityJoint',engagement,action,id:task.id,...(action==='wait'?{waitSeconds:15}:{})})));
  const download=()=>perform(async()=>{
   const report={version:1,engagement,task:null,findings:[],files:[],exclusions:[],diagnostics:[],artifacts:[]};
   for(const section of ['findings','files','exclusions','diagnostics','artifacts']){
    let cursor;for(let n=0;n<1001;n++){
     const result=parse(await api({op:'securityJoint',engagement,action:'report',id:task.id,section,limit:10,...(cursor?{cursor}:{})}),engagement),page=result.page;
     if(!validTask(result.task,engagement)||result.task.id!==task.id||!page||page.section!==section||!Array.isArray(page.items)||typeof page.complete!=='boolean'||!Number.isSafeInteger(page.total))throw Error('报告分页未确认');
     if(report.task&&report.task.snapshot?.id!==result.task.snapshot?.id)throw Error('报告副本已变化');report.task=result.task;report[section].push(...page.items);
     if(page.complete){if(report[section].length!==page.total)throw Error('报告明细不完整');break}
     if(typeof page.nextCursor!=='string'||page.nextCursor===cursor||n===1000)throw Error('报告续读未完成');cursor=page.nextCursor;
    }
   }
   if(!alive.current)return;const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='joint-review-'+task.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  const inProgress=task&&['running','cancelling'].includes(task.state),ready=plan&&plan.profileRevision===profile?.revision&&Date.parse(profile.expiresAt)>Date.now();
  const button=(label,fn,disabled=false)=>h('button',{type:'button',className:'rt-btn',onClick:fn,disabled:busy||disabled},label);
  return h('section',{className:'rt-card','aria-label':'联合安全审查'},h('div',{className:'rts-head'},h('h4',null,'联合安全审查'),h('span',{className:'rts-state'},'VM · 受管工具')),
   h('p',null,'源码副本 / 本地HTTP → 选择静态检查 / ZAP / Kali / REA / PentAGI → 统一证据报告'),h('p',{className:'rts-meta'},'Kali离线Python检查；REA＋reverse-skill静态JavaScript图。PentAGI子任务在禁网工作容器内读取副本，模型通过既有DeepSeek账号调用：最多16次请求、每次2048输出tokens，不是货币金额上限。默认360秒，聊天费用另计。'),
   plan?.webTarget&&h('p',{className:'rts-meta'},'ZAP目标：'+plan.webTarget.origin+' · 会发送本地请求；版本关联以本次扫描前后核对为准，刷新不默认勾选。'),button('核对联合范围与原任务',refresh),plan&&h('div',{className:'rts-tools'},...['semgrep','trivy','zap','kali','rea','pentagi'].map(tool=>{const allowed={kali:plan.kaliAllowed,rea:plan.reaAllowed,pentagi:plan.pentagiAllowed}[tool]??plan.availableSteps.includes(tool);return h('label',{key:tool},h('input',{type:'checkbox',checked:selected.includes(tool),disabled:busy||!allowed,onChange:e=>setSelected(old=>e.target.checked?[...old,tool]:old.filter(s=>s!==tool))}),' '+tool+(allowed?'':' · 未授权或未就绪'))})),
   plan&&!plan.kaliAllowed&&h('p',{className:'rts-meta'},'Kali副本交接尚未授权；可在上方项目范围勾选并确认保存。'),
   h('div',{className:'rts-actions'},button('启动联合审查',start,!ready||!selected.length||pending||inProgress),task&&button('等待原联合任务',()=>update('wait'),!inProgress),task&&button('取消或核对停止',()=>update('cancel'),!inProgress&&task.cleanupVerified),task&&button('下载联合报告 JSON',download,inProgress)),
   pending&&h('p',{className:'rts-alert'},'启动请求已保留；回执未确认时先核对原任务，不自动重发。'),error&&h('p',{className:'rts-alert',role:'alert'},error),
   task&&h('div',null,task.webTarget&&h('p',{className:'rts-meta'},'运行版本关联：'+(task.webTarget.appRevision==='managed-source-copy-matched'?'受管源码副本前后匹配；依赖及内存行为未证明':'未证明；请查看报告artifacts中的运行身份核对')) ,h('p',null,'任务：'+task.id+' · '+(states[task.state]||task.state)),h('p',null,'工具命中 '+task.findings+' 条 · 子任务模型请求 '+(task.modelCalls??0)+' 次 · 停止核对：'+(task.cleanupVerified?'已确认':'未确认')),task.snapshot&&h('p',{className:'rts-meta'},'副本 '+task.snapshot.id+' · '+task.snapshot.files+' 文件 · 排除路径 '+task.snapshot.excluded+' · 脱敏文件 '+task.snapshot.redactedFiles),...task.steps.map(s=>h('p',{key:s.tool},s.tool+'：'+(states[s.state]||s.state)+(s.id?' · '+s.id:''))),h('p',{className:'rts-meta'},'工具命中待验证；登录、越权、业务逻辑、架构、未选工具与排除内容仍未覆盖。')));
 };
}
export function createSecurityTab(React,api,options={}){
 const h=React.createElement;
 const documentState=Object.hasOwn(options,'document')?options.document:globalThis.document,timers=options.timers??globalThis,now=options.now??Date.now;
 const visible=()=>documentState?.visibilityState!=='hidden';
 const toolNames={semgrep:'Semgrep · 代码检查',trivy:'Trivy · 依赖与配置',zap:'ZAP · 本地网页基线'};
 const statusNames={unverified:'待验证',confirmed:'已确认','false-positive':'误报',fixed:'已记录修复','retest-passed':'复测通过',reopened:'再次出现',running:'运行中',completed:'已完成',partial:'覆盖不完整',failed:'失败',cancelled:'已取消',interrupted:'中断'};
 const label=(labels,key,fallback=key)=>Object.hasOwn(labels,key)?labels[key]:fallback;
 const maintenanceNames={current:'已与官方版本核对',updated:'已更新','rolled-back':'已恢复原库'};
 const comparisonLabels={added:'新增命中位置',persisting:'仍存在的命中位置',notSeen:'已覆盖文件中未再次命中',uncovered:'覆盖未证实'};
 const comparisonValid=(value,request)=>value?.ok===true&&value.engagement===request.engagement&&value.baseRunId===request.baseRunId&&value.currentRunId===request.currentRunId&&typeof value.available==='boolean'&&(value.available?typeof value.notice==='string'&&typeof value.markdown==='string'&&typeof value.truncated==='boolean'&&Object.keys(comparisonLabels).every(key=>Number.isSafeInteger(value.summary?.[key])&&value.summary[key]>=0&&Array.isArray(value.items?.[key])&&value.items[key].length<=100&&value.items[key].every(item=>item&&['rule','title','severity','location'].every(field=>typeof item[field]==='string')&&validSubject(item.subject))):typeof value.reason==='string');
 const id=()=>globalThis.crypto?.randomUUID?.()||'request-'+Date.now()+'-'+Math.random().toString(36).slice(2);
 const record=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
 const string=(value,max=8192)=>typeof value==='string'&&value.length<=max;
 const optionalString=value=>value==null||string(value);
 const positive=value=>Number.isSafeInteger(value)&&value>0;
 const nonnegative=value=>Number.isSafeInteger(value)&&value>=0;
 const validSubject=value=>value==null||(record(value)&&value.kind==='package'&&[['name',240],['version',240],['path',800],['purl',1200],['key',64],['family',64]].every(([key,max])=>string(value[key],max))&&!!value.name&&/^[a-f0-9]{64}$/.test(value.key)&&/^[a-f0-9]{64}$/.test(value.family));
 const subjectText=value=>value.name+'@'+(value.version||'版本未记录')+(value.path?' · '+value.path:'');
 const date=value=>string(value,64)&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
 const isTool=value=>typeof value==='string'&&Object.hasOwn(toolNames,value);
 const reviewStates={observed:'已有完整工具观察',partial:'覆盖不完整',running:'运行中',unverified:'未验证',manual:'待人工验证'};
 const validReview=(v,data)=>record(v)&&v.version===1&&v.engagement===engagementAt(data)&&v.scopeRevision===(data.profile?.revision??0)&&v.complianceClaim===false&&Array.isArray(v.blockers)&&v.blockers.length<=10&&v.blockers.every(x=>string(x,240))&&Array.isArray(v.canStartTools)&&v.canStartTools.length<=3&&v.canStartTools.every(isTool)&&Array.isArray(v.checks)&&v.checks.length<=8&&new Set(v.checks.map(x=>x?.id)).size===v.checks.length&&v.checks.every(c=>record(c)&&['code','dependencies','secrets','web','authentication','authorization','business','architecture'].includes(c.id)&&string(c.label,80)&&Object.hasOwn(reviewStates,c.state)&&(c.tool===null||isTool(c.tool))&&(c.runId===null||string(c.runId,100)))&&string(v.notice,400);
 const engagementAt=data=>data.engagement;
 const toolList=value=>Array.isArray(value)&&value.length>0&&value.length<=3&&new Set(value).size===value.length&&value.every(isTool);
 const scopePath=value=>{if(!string(value)||!value.startsWith('/'))return null;const parts=[];for(const part of value.split('/')){if(part==='..')parts.pop();else if(part&&part!=='.')parts.push(part)}return'/'+parts.join('/')};
 const storage=()=>Object.hasOwn(options,'storage')?options.storage:globalThis.localStorage;
 const receiptKey=eng=>{if(!string(eng,240)||!eng||/[\x00-\x1f]/.test(eng))throw Error('项目标识无效');return'dsh-security-request-v1:'+encodeURIComponent(eng)};
 const locks=()=>Object.hasOwn(options,'locks')?options.locks:globalThis.navigator?.locks;
 const coordinated=()=>{try{return typeof locks()?.request==='function'}catch{return false}};
 const exclusive=async(eng,action)=>{
  let entered=false,callbackError;
  try{
   const manager=locks();if(typeof manager?.request!=='function')throw Error();
   await manager.request(receiptKey(eng),{mode:'exclusive',ifAvailable:true},async lock=>{
    if(!lock)return;entered=true;
    try{return await action()}catch(error){callbackError=error;throw error}
   });
  }catch{if(callbackError)throw callbackError;throw Error('多窗口协调不可用；请刷新核对，不会自动重发操作。')}
  if(!entered)throw Error('另一窗口正在处理本项目操作；请稍后刷新核对，不会排队或自动重发。');
 };
 const validRequest=(value,eng)=>{
  if(!record(value)||value.engagement!==eng||!string(value.requestId,100)||!/^[A-Za-z0-9_-]{8,100}$/.test(value.requestId))return false;
  const keys={securityScopeSave:['confirm','expiresAt','repoRoot','revision','tools','url'],securityStart:['profileRevision','tool'],securityReview:['id','revision','status','note']};
  if(typeof value.op!=='string'||!Object.hasOwn(keys,value.op))return false;
  const expected=['op','engagement','requestId',...keys[value.op],...(value.op==='securityStart'&&Object.hasOwn(value,'retestFindingId')?['retestFindingId']:[]),...(value.op==='securityScopeSave'&&Object.hasOwn(value,'authProfile')?['authProfile']:[]),...(value.op==='securityScopeSave'?['jointKali','jointRea','jointPentagi'].filter(k=>Object.hasOwn(value,k)):[])];
  if(Object.keys(value).sort().join(',')!==expected.sort().join(','))return false;
  if(value.op==='securityScopeSave')return value.confirm===true&&nonnegative(value.revision)&&string(value.repoRoot)&&!!value.repoRoot&&optionalString(value.url)&&date(value.expiresAt)&&toolList(value.tools)&&authName(value.authProfile)&&(!value.authProfile||!!value.url&&value.tools.includes('zap'))&&['jointKali','jointRea','jointPentagi'].every(k=>value[k]===undefined||typeof value[k]==='boolean');
  if(value.op==='securityStart')return positive(value.profileRevision)&&isTool(value.tool)&&(!Object.hasOwn(value,'retestFindingId')||positive(value.retestFindingId));
  return positive(value.id)&&positive(value.revision)&&['confirmed','false-positive','fixed'].includes(value.status)&&string(value.note,2000)&&value.note.trim().length>=5;
 };
 const readReceipt=eng=>{
  let raw;
  try{
   raw=storage().getItem(receiptKey(eng));if(raw===null)return{owner:eng,raw,request:null,error:''};
   if(typeof raw!=='string'||raw.length>16384)throw Error();const value=JSON.parse(raw);
   if(!record(value)||Object.keys(value).sort().join(',')!=='createdAt,request,version'||value.version!==1||!positive(value.createdAt)||value.createdAt>Date.now()+60000||!validRequest(value.request,eng))throw Error();
   return{owner:eng,raw,request:value.request,error:''};
  }catch{return{owner:eng,raw,request:null,error:'浏览器恢复记录无法读取或无效；写入已暂停，请核对已保存任务与记录。'}}
 };
 const persistReceipt=request=>{
  const current=readReceipt(request.engagement);if(current.error)throw Error(current.error);
  if(!validRequest(request,request.engagement))throw Error('恢复记录无法保存：请求内容无效。');
  if(current.request){if(JSON.stringify(current.request)!==JSON.stringify(request))throw Error('已有另一操作等待核对，请先处理恢复记录。');return current.request}
  const raw=JSON.stringify({version:1,createdAt:Date.now(),request});if(raw.length>16384)throw Error('恢复记录无法保存：请求内容过长。');
  try{const target=storage();target.setItem(receiptKey(request.engagement),raw);if(target.getItem(receiptKey(request.engagement))!==raw)throw Error()}catch{throw Error('浏览器恢复记录无法保存；操作未发送，请恢复浏览器存储后重新读取。')}
  return JSON.parse(raw).request;
 };
 const releaseReceipt=request=>{
  const current=readReceipt(request.engagement);if(current.error)throw Error(current.error);
  if(current.request&&JSON.stringify(current.request)===JSON.stringify(request))storage().removeItem(receiptKey(request.engagement));
 };
 const authName=value=>value==null||value===''||typeof value==='string'&&/^[a-z][a-z0-9_-]{0,47}$/.test(value);
 const validAuthentication=value=>{
  if(!record(value)||Object.keys(value).sort().join(',')!==['version','profile','revision','state','verification','before','after','scannerBefore','scannerAfter','checkedRequests'].sort().join(',')||value.version!==1||!authName(value.profile)||!value.profile||!['verified','unconfirmed'].includes(value.state)||value.verification!=='controller-and-zap-before-after'||!['before','after','scannerBefore','scannerAfter'].every(key=>typeof value[key]==='boolean')||![0,2].includes(value.checkedRequests)||!(value.revision===null||typeof value.revision==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value.revision)))return false;
  return value.state!=='verified'||!!value.revision&&value.checkedRequests===2&&value.before&&value.after&&value.scannerBefore&&value.scannerAfter;
 };
 const validProfile=value=>value===null||(record(value)&&positive(value.revision)&&string(value.repoRoot)&&value.repoRoot.length>0&&optionalString(value.url)&&date(value.expiresAt)&&toolList(value.tools)&&authName(value.authProfile)&&(!value.authProfile||!!value.url&&value.tools.includes('zap'))&&['jointKali','jointRea','jointPentagi'].every(k=>value[k]===undefined||typeof value[k]==='boolean'));
 const validSession=(value,profile)=>{
  if(!record(value)||Object.keys(value).sort().join(',')!==['version','profile','revision','state','expiresAt','checkedAt'].sort().join(',')||value.version!==1||value.profile!==profile||!date(value.checkedAt)||!['ready','expiring','expired','unavailable'].includes(value.state))return false;
  if(value.state==='unavailable')return value.revision===null&&value.expiresAt===null;
  if(typeof value.revision!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value.revision)||!date(value.expiresAt))return false;
  const remaining=Date.parse(value.expiresAt)-Date.parse(value.checkedAt);return value.state==='expired'?remaining<=0:value.state==='expiring'?remaining>0&&remaining<=300000:remaining>300000&&remaining<=31*86400000;
 };
 const validRuntime=value=>{
  if(!record(value)||typeof value.ready!=='boolean'||!(value.ready?string(value.version,128)&&value.version.length>0:optionalString(value.version))||!optionalString(value.reason)||!optionalString(value.warning)||(value.checkedAt!=null&&!date(value.checkedAt))||(value.cached!==undefined&&typeof value.cached!=='boolean'))return false;
  if(value.rules!=null&&(!record(value.rules)||!string(value.rules.version,128)||!positive(value.rules.count)||value.rules.count>1000||!Array.isArray(value.rules.languages)||!value.rules.languages.length||value.rules.languages.length>100||!value.rules.languages.every(language=>string(language,128)&&language.length>0)))return false;
  if(value.database!=null&&(!record(value.database)||(value.database.updatedAt!=null&&(!date(value.database.updatedAt)||!nonnegative(value.database.ageDays)))))return false;
  return value.lastUpdate==null||(record(value.lastUpdate)&&string(value.lastUpdate.state,128)&&date(value.lastUpdate.checkedAt));
 };
 const validSupplement=s=>record(s)&&Object.keys(s).sort().join(',')===['version','policy','candidateFiles','checkedFiles','skippedFiles','hints','truncated'].sort().join(',')&&s.version===1&&s.policy==='parser-text-1'&&['candidateFiles','checkedFiles','skippedFiles','hints'].every(k=>nonnegative(s[k]))&&s.candidateFiles<=20000&&s.checkedFiles<=20&&s.checkedFiles+s.skippedFiles===s.candidateFiles&&s.hints<=s.checkedFiles*3&&typeof s.truncated==='boolean';
 const validRun=value=>{
  if(!record(value)||!string(value.id,100)||!value.id||!isTool(value.tool)||!string(value.state,128)||!value.state||![0,1].includes(value.complete)||!date(value.started_at)||!optionalString(value.revision_ref)||!optionalString(value.error_code)||(value.details!==undefined&&!record(value.details)))return false;
  if(value.details?.authentication!==undefined&&(!validAuthentication(value.details.authentication)||value.tool!=='zap'||value.details.authentication.state==='unconfirmed'&&value.complete===1))return false;
  if(value.details?.supplemental!==undefined&&(!validSupplement(value.details.supplemental)||value.tool!=='semgrep'||value.complete===1))return false;
  const diagnostics=value.details?.diagnostics;
  if(diagnostics!=null&&(!record(diagnostics)||!nonnegative(diagnostics.total)||!Array.isArray(diagnostics.items)||diagnostics.items.length>20||diagnostics.items.length>diagnostics.total||typeof diagnostics.truncated!=='boolean'||diagnostics.items.some(d=>!record(d)||!string(d.code,80)||!string(d.path,400)||!(d.line===null||positive(d.line)))))return false;
  const snapshot=value.details?.comparisonSnapshot;
  return snapshot==null||(record(snapshot)&&typeof snapshot.available==='boolean'&&optionalString(snapshot.reason));
 };
 const validFinding=value=>record(value)&&positive(value.id)&&positive(value.revision)&&isTool(value.tool)&&['title','rule','location','evidence','note','severity','status'].every(key=>string(value[key]))&&!!value.status&&!!value.rule&&!!value.location&&validSubject(value.subject)&&(value.identityVersion===undefined||[0,1].includes(value.identityVersion))&&(value.subject==null||value.identityVersion===1);
 const confirmedMutation=(value,request)=>{
  if(value?.ok!==true)return false;
  if(request.op==='securityStart')return record(value.run)&&string(value.run.id,100)&&!!value.run.id&&['running','completed','partial','failed','cancelled','interrupted'].includes(value.run.state);
  if(request.op==='securityScopeSave')return validProfile(value.profile)&&value.profile!==null&&value.profile.revision===request.revision+1&&value.profile.repoRoot===scopePath(request.repoRoot)&&(value.profile.url??'')===(request.url?new URL(request.url).origin:'')&&Date.parse(value.profile.expiresAt)===Date.parse(request.expiresAt)&&JSON.stringify(value.profile.tools)===JSON.stringify(request.tools)&&(value.profile.authProfile??'')===(request.authProfile??'')&&['jointKali','jointRea','jointPentagi'].every(k=>(value.profile[k]??false)===(request[k]??false));
  return request.op==='securityReview'&&validFinding(value.finding)&&value.finding.id===request.id&&value.finding.revision===request.revision+1&&value.finding.status===request.status;
 };
 const definiteRejection=(value,request)=>{
  const d=value.diagnostic;
  return d===undefined||record(d)&&Object.keys(d).sort().join(',')==='code,elapsedMs,operation,requestId,stage'&&string(d.requestId,36)&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(d.requestId)&&d.operation===request.op&&d.stage==='dispatch'&&d.code==='RPC_REJECTED'&&nonnegative(d.elapsedMs)&&d.elapsedMs<=86400000;
 };
 const freshPages=owner=>({owner,runs:{cursor:null,limit:10,history:[],tool:'',state:''},findings:{cursor:null,limit:50,history:[],tool:'',status:'',severity:'',search:''}});
 const requestPages=value=>Object.fromEntries(['runs','findings'].map(key=>{const {history,...query}=value[key];return[key,query]}));
 const validPage=(page,query,rows,collection)=>{
  if(!record(page)||!positive(page.limit)||page.limit!==(query.limit??(collection==='runs'?10:50))||page.cursor!==(query.cursor??null)||!nonnegative(page.total)||page.total<rows.length||rows.length>page.limit||typeof page.hasMore!=='boolean'||!record(page.filters))return false;
  const keys=collection==='runs'?['tool','state']:['tool','status','severity','search'];
  if(Object.keys(page.filters).sort().join(',')!==keys.slice().sort().join(',')||keys.some(key=>page.filters[key]!==((query[key]??'').trim())))return false;
  if(page.cursor===null&&rows.length!==Math.min(page.limit,page.total))return false;
  return page.hasMore?rows.length===page.limit&&page.total>rows.length&&string(page.nextCursor,512)&&/^[A-Za-z0-9_-]+$/.test(page.nextCursor):page.nextCursor===null;
 };
 const valid=(v,eng,query)=>{
  if(!record(v)||v.ok!==true||v.engagement!==eng||!validProfile(v.profile)||!record(v.tools)||!Object.keys(toolNames).every(tool=>validRuntime(v.tools[tool]))||!date(v.observedAt))return false;
  if(Object.hasOwn(v,'authSession')&&(v.profile?.authProfile?!validSession(v.authSession,v.profile.authProfile):v.authSession!==null))return false;
  if(v.pagination!==undefined){
   if(!record(v.pagination)||!nonnegative(v.totalRuns)||!nonnegative(v.totalFindings)||!(v.activeRun===null||validRun(v.activeRun)&&v.activeRun.state==='running')||!Array.isArray(v.comparisonRuns)||v.comparisonRuns.length>30||v.comparisonRuns.some(row=>!validRun(row)||row.state!=='completed'||row.complete!==1)||new Set(v.comparisonRuns.map(row=>row.id)).size!==v.comparisonRuns.length)return false;
   return [['runs',v.totalRuns,validRun],['findings',v.totalFindings,validFinding]].every(([key,total,check])=>Array.isArray(v[key])&&v[key].every(check)&&new Set(v[key].map(row=>row.id)).size===v[key].length&&validPage(v.pagination[key],query[key],v[key],key)&&v.pagination[key].total<=total);
  }
  return [['runs',30,'totalRuns',validRun],['findings',500,'totalFindings',validFinding]].every(([key,limit,total,check])=>Array.isArray(v[key])&&v[key].length<=limit&&v[key].every(check)&&new Set(v[key].map(row=>row.id)).size===v[key].length&&(v[total]===undefined||(nonnegative(v[total])&&v[key].length===Math.min(limit,v[total]))));
 };
 const JointPanel=createJointPanel(React,api,{storage,exclusive}),RuntimePanel=createRuntimePanel(React,api,{storage,exclusive});
 return function SecurityTab({engagement,refreshKey}){
  const [data,setData]=React.useState(null),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false),[loading,setLoading]=React.useState(true),[draft,setDraft]=React.useState(null),[notes,setNotes]=React.useState({}),[updateGuide,setUpdateGuide]=React.useState(false),[comparison,setComparison]=React.useState({owner:engagement,base:'',current:'',result:null,error:'',loading:false});
  const [exporting,setExporting]=React.useState(false),[unconfirmed,setUnconfirmed]=React.useState(false),[searchDraft,setSearchDraft]=React.useState(''),[storageError,setStorageError]=React.useState(''),[discardAck,setDiscardAck]=React.useState(false),[authGuide,setAuthGuide]=React.useState(false);
  const guard=React.useRef({alive:true,sequence:0,writing:false,owner:engagement,context:0,read:null,confirmed:false,recover:false,authSelected:false}),dirty=React.useRef(false),writeReceipt=React.useRef(null),journal=React.useRef(null),discardApproval=React.useRef(null),compareGuard=React.useRef(0),exportGuard=React.useRef(null),pageQuery=React.useRef(freshPages(engagement));
  if(guard.current.owner!==engagement){guard.current.read?.abort();guard.current.read=null;guard.current.confirmed=false;guard.current.owner=engagement;guard.current.context++;writeReceipt.current=null;dirty.current=false;journal.current=null}
  const contextAtRender=guard.current.context;
  const restoreReceipt=()=>{const value=readReceipt(engagement);journal.current=value;writeReceipt.current=value.request;setStorageError(value.error);discardApproval.current=null;setDiscardAck(false)};
  const viewGeneration=guard.current.sequence;
  const discardRaw=journal.current?.owner===engagement?journal.current.raw:undefined;
  const load=async({refreshRuntime=false,targetPages=null,resetPages=false,automatic=false}={})=>{
   if(!guard.current.alive||guard.current.owner!==engagement||guard.current.context!==contextAtRender)return;
   if(automatic&&(!visible()||guard.current.read||guard.current.writing))return;
   guard.current.read?.abort();const controller=new AbortController();guard.current.read=controller;guard.current.confirmed=false;
   const source=(targetPages??pageQuery.current).owner===engagement?(targetPages??pageQuery.current):freshPages(engagement);
   const target=resetPages?{...source,runs:{...source.runs,cursor:null,history:[]},findings:{...source.findings,cursor:null,history:[]}}:source,pages=requestPages(target);
   const token=++guard.current.sequence;restoreReceipt();setLoading(true);exportGuard.current=null;setExporting(false);compareGuard.current++;setComparison(old=>old.owner===engagement?{...old,result:null,error:'',loading:false}:{owner:engagement,base:'',current:'',result:null,error:'',loading:false});
   try{const next=await api({op:'securityStatus',engagement,pages,...(refreshRuntime?{refreshRuntime:true}:{})},{signal:controller.signal});if(!guard.current.alive||token!==guard.current.sequence)return;if(!valid(next,engagement,pages))throw Error(next?.ok===false&&typeof next.error==='string'?next.error:'安全审计资料无效，当前结果未确认');pageQuery.current=target;guard.current.confirmed=true;guard.current.recover=false;guard.current.authSelected=!!next.profile?.authProfile;setData(next);setError('');setUnconfirmed(false);setDraft(old=>{if(dirty.current&&old)return old;const p=next.profile;return p?{...p,confirm:false}:{repoRoot:'',url:'',expiresAt:new Date(Date.now()+86400000).toISOString(),tools:['semgrep','trivy'],revision:0,confirm:false}})}
   catch(e){if(guard.current.alive&&token===guard.current.sequence){guard.current.recover=true;setError(e.message||'读取失败');setUnconfirmed(true)}}
   finally{if(guard.current.alive&&token===guard.current.sequence){guard.current.read=null;setLoading(false)}}
  };
  React.useEffect(()=>{guard.current.alive=true;if(pageQuery.current.owner!==engagement)setSearchDraft('');load({resetPages:true});return()=>{guard.current.alive=false;guard.current.sequence++;guard.current.read?.abort();guard.current.read=null;guard.current.confirmed=false}},[engagement,refreshKey]);
  React.useEffect(()=>{
   const target=Object.hasOwn(options,'events')?options.events:globalThis;
   let last=now();
   const current=()=>guard.current.alive&&guard.current.owner===engagement&&guard.current.context===contextAtRender;
   const invalidate=()=>{guard.current.read?.abort();guard.current.read=null;guard.current.sequence++;guard.current.confirmed=false;guard.current.recover=true;exportGuard.current=null;compareGuard.current++;setUnconfirmed(true);setLoading(false);setExporting(false)};
   const sync=()=>{if(!current())return;invalidate();if(visible()&&!guard.current.writing)load()};
   const changed=event=>{if(event.key!==null&&event.key!==receiptKey(engagement))return;try{if(event.storageArea&&event.storageArea!==storage())return}catch{}sync()};
   const visibility=()=>{if(!current())return;last=now();if(visible())sync();else invalidate()};
   const heartbeat=()=>{if(!current())return;const currentTime=now(),gap=currentTime-last;last=currentTime;if(!visible())return;if(gap>60000||gap<0){sync();return}if(guard.current.recover||guard.current.authSelected)load({automatic:true})};
   target?.addEventListener?.('storage',changed);target?.addEventListener?.('focus',sync);target?.addEventListener?.('pageshow',sync);documentState?.addEventListener?.('visibilitychange',visibility);
   const timer=timers.setInterval(heartbeat,30000);timer?.unref?.();
   return()=>{timers.clearInterval(timer);target?.removeEventListener?.('storage',changed);target?.removeEventListener?.('focus',sync);target?.removeEventListener?.('pageshow',sync);documentState?.removeEventListener?.('visibilitychange',visibility)};
  },[engagement,refreshKey]);
  const running=data?.activeRun??data?.runs?.find(row=>row.state==='running');
  React.useEffect(()=>{if(!running)return;const timer=timers.setInterval(()=>load({automatic:true}),2500);timer?.unref?.();return()=>timers.clearInterval(timer)},[running?.id,engagement,refreshKey]);
  const mutate=async(request,{receipt=false}={})=>{
   if(!guard.current.confirmed||viewGeneration!==guard.current.sequence||guard.current.writing||!guard.current.alive||guard.current.context!==contextAtRender||guard.current.owner!==engagement||request?.engagement!==engagement)return;
   const context=guard.current.context,current=()=>guard.current.alive&&context===guard.current.context;
   guard.current.writing=true;setBusy(true);setError('');
   try{
    await exclusive(engagement,async()=>{
    if(!current()||!guard.current.confirmed||viewGeneration!==guard.current.sequence)return;
    if(receipt){try{request=persistReceipt(request);restoreReceipt()}catch(error){setStorageError(error.message);throw error}}
    const result=await api(request);
    if(receipt&&(confirmedMutation(result,request)||result?.ok===false&&definiteRejection(result,request)))releaseReceipt(request);
    if(!current())return;
    if(receipt)restoreReceipt();
    if(result?.ok===false)throw Error(result.error||'操作已拒绝');if(result?.ok!==true||receipt&&!confirmedMutation(result,request))throw Error('操作回执无效，结果未确认');
    if(request.op==='securityScopeSave'&&(!dirty.current||['revision','repoRoot','url','expiresAt','tools','confirm','authProfile','jointKali','jointRea','jointPentagi'].every(key=>JSON.stringify(draft?.[key])===JSON.stringify(request[key])))){dirty.current=false;setDraft(old=>({...old,...result.profile,confirm:false}))}await load({resetPages:true});
    });
   }
   catch(e){if(current())setError((e.message||'操作失败')+(receipt?'；可刷新查询结果。若重试，将复用同一请求号。':''))}
   finally{guard.current.writing=false;if(guard.current.alive)setBusy(false);if(current()&&guard.current.recover&&visible())load({automatic:true})}
  };
  const choices=data?.engagement===engagement?(data.comparisonRuns??data.runs.filter(run=>run.state==='completed'&&run.complete===1)):[],ownedComparison=comparison.owner===engagement?comparison:null;
  const currentId=ownedComparison?.current||choices[0]?.id||'',baseId=ownedComparison?.base||choices[1]?.id||'';
  const selectComparison=(key,value)=>{compareGuard.current++;setComparison({owner:engagement,base:baseId,current:currentId,[key]:value,result:null,error:'',loading:false})};
  const compareSelected=async()=>{
   if(!guard.current.confirmed||viewGeneration!==guard.current.sequence||ownedComparison?.loading||!baseId||!currentId||baseId===currentId||!guard.current.alive)return;
   const request={op:'securityCompare',engagement,baseRunId:baseId,currentRunId:currentId},token=++compareGuard.current;
   setComparison({owner:engagement,base:baseId,current:currentId,result:null,error:'',loading:true});
   try{const value=await api(request);if(!guard.current.alive||token!==compareGuard.current)return;if(!comparisonValid(value,request))throw Error(value?.error||'对比结果未确认');setComparison({owner:engagement,base:baseId,current:currentId,result:value,error:'',loading:false})}
   catch(error){if(guard.current.alive&&token===compareGuard.current)setComparison({owner:engagement,base:baseId,current:currentId,result:null,error:error.message||'对比读取失败',loading:false})}
  };
  const comparisonValue=ownedComparison?.result?.baseRunId===baseId&&ownedComparison?.result?.currentRunId===currentId?ownedComparison.result:null,comparisonGeneration=compareGuard.current;
  const downloadComparison=()=>{if(!guard.current.alive||comparisonGeneration!==compareGuard.current||!comparisonValue?.available)return;const url=URL.createObjectURL(new Blob([comparisonValue.markdown],{type:'text/markdown;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='security-comparison-'+engagement+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
  const change=(key,value)=>{if(!guard.current.alive||guard.current.context!==contextAtRender||writeReceipt.current||storageError)return;dirty.current=true;setDraft(old=>({...old,[key]:value}))};
  const discardReceipt=async()=>{
   const allowed=()=>guard.current.alive&&discardAck&&!busy&&!loading&&!unconfirmed&&guard.current.sequence===viewGeneration&&guard.current.context===contextAtRender&&guard.current.owner===engagement&&journal.current?.owner===engagement&&discardApproval.current?.raw===discardRaw&&discardApproval.current?.generation===viewGeneration;
   if(guard.current.writing||!allowed())return;
   guard.current.writing=true;setBusy(true);
   try{await exclusive(engagement,async()=>{if(!allowed())return;const target=storage(),key=receiptKey(engagement);if(discardRaw===undefined||journal.current.raw!==discardRaw||target.getItem(key)!==discardRaw)throw Error();target.removeItem(key);restoreReceipt();await load({resetPages:true})})}
   catch{if(guard.current.alive&&guard.current.context===contextAtRender){restoreReceipt();setError('恢复记录已变化、另一窗口正在处理或多窗口协调不可用；请重新读取后核对。')}}
   finally{guard.current.writing=false;if(guard.current.alive)setBusy(false)}
  };
  const save=()=>mutate({op:'securityScopeSave',engagement,requestId:id(),...draft},{receipt:true});
  const start=(tool,finding)=>{if(tool==='zap'&&data?.profile?.authProfile&&!['ready','expiring'].includes(data?.authSession?.state))return;return mutate({op:'securityStart',engagement,requestId:id(),profileRevision:data.profile.revision,tool,...(finding?{retestFindingId:finding.id}:{})},{receipt:true})};
  const review=(finding,status)=>mutate({op:'securityReview',engagement,requestId:id(),id:finding.id,revision:finding.revision,status,note:notes[finding.id]||''},{receipt:true});
  const download=async()=>{
   if(!guard.current.confirmed||!guard.current.alive||viewGeneration!==guard.current.sequence||exportGuard.current||loading||error||data?.engagement!==engagement)return;
   const token={generation:viewGeneration};exportGuard.current=token;setExporting(true);
   const current=()=>guard.current.alive&&viewGeneration===guard.current.sequence&&exportGuard.current===token;
   try{
    const report=await api({op:'securityReport',engagement});if(!current())return;
    if(report?.ok!==true||report.engagement!==engagement||typeof report.markdown!=='string')throw Error('报告未确认，请刷新后重试');
    const url=URL.createObjectURL(new Blob([report.markdown],{type:'text/markdown;charset=utf-8'}));
    try{const a=document.createElement('a');a.href=url;a.download='security-audit-'+engagement+'.md';a.click()}finally{setTimeout(()=>URL.revokeObjectURL(url),1000)}
   }catch(e){if(current())setError(e.message||'报告下载失败')}
   finally{if(current()){exportGuard.current=null;setExporting(false)}}
  };
  const button=(label,onClick,disabled=false)=>h('button',{type:'button',className:'rt-btn',onClick,disabled:busy||disabled},label);
  const field=(label,key,type='text')=>h('label',{className:'rts-field'},h('span',null,label),h('input',{className:'rt-input',type,value:draft?.[key]||'',disabled:busy||!!writeReceipt.current||!!storageError,onChange:e=>change(key,e.target.value)}));
  const actionable=data&&data.engagement===engagement&&!error&&!loading&&!busy&&!running&&!writeReceipt.current&&!storageError&&coordinated();
  const pageDisabled=loading||busy||!!error||data?.engagement!==engagement;
  const movePage=(collection,forward)=>{
   if(pageDisabled)return;const current=pageQuery.current[collection],meta=data?.pagination?.[collection];if(!meta||forward&&!meta.hasMore||!forward&&!current.history.length)return;
   const next=forward?{...current,cursor:meta.nextCursor,history:[...current.history,current.cursor]}:{...current,cursor:current.history.at(-1),history:current.history.slice(0,-1)};
   return load({targetPages:{...pageQuery.current,[collection]:next}});
  };
  const filterPage=(collection,key,value)=>{if(pageDisabled)return;return load({targetPages:{...pageQuery.current,[collection]:{...pageQuery.current[collection],[key]:value,cursor:null,history:[]}}})};
  const pageTitle=collection=>{const meta=data?.pagination?.[collection],current=pageQuery.current[collection];return meta?'第'+(current.history.length+1)+'页 · 本页 '+data[collection].length+' · 匹配 '+meta.total+' / 全部 '+data[collection==='runs'?'totalRuns':'totalFindings']:null};
  const pendingRequest=writeReceipt.current;
  const pageControls=collection=>{
   const meta=data?.pagination?.[collection];if(!meta)return null;const name=collection==='runs'?'任务':'发现',current=pageQuery.current[collection];
   const select=(key,title,values)=>h('label',{className:'rts-field'},title,h('select',{'aria-label':title,className:'rt-input',value:current[key],disabled:pageDisabled,onChange:e=>filterPage(collection,key,e.target.value)},h('option',{value:''},'全部'),...values.map(value=>h('option',{key:value,value},key==='tool'?label(toolNames,value):label(statusNames,value,value)))));
   return h('div',null,h('div',{className:'rts-grid'},select('tool',name+'工具',Object.keys(toolNames)),...(collection==='runs'?[select('state','任务状态',['running','completed','partial','failed','cancelled','interrupted'])]:[select('status','发现状态',['unverified','confirmed','false-positive','fixed','retest-passed','reopened']),select('severity','发现严重性',['critical','high','medium','low','info','unknown']),h('label',{className:'rts-field'},'标题、规则或位置',h('input',{'aria-label':'发现搜索',className:'rt-input',value:searchDraft,maxLength:160,disabled:pageDisabled,onChange:e=>setSearchDraft(e.target.value),onKeyDown:e=>{if(e.key==='Enter')filterPage('findings','search',searchDraft.trim())}}))])),h('nav',{'aria-label':name+'分页',className:'rts-actions'},button(name+'上一页',()=>movePage(collection,false),pageDisabled||!current.history.length),button(name+'下一页',()=>movePage(collection,true),pageDisabled||!meta.hasMore),collection==='findings'&&button('搜索发现',()=>filterPage('findings','search',searchDraft.trim()),pageDisabled)),h('p',{className:'rts-meta'},'筛选仅影响列表；报告仍按项目全部记录生成。'));
  };
  const expired=!data?.profile||Date.parse(data.profile.expiresAt)<=Date.now();
  const comparisonFields=[['基线任务','base',baseId],['本次任务','current',currentId]].map(([label,key,value])=>{
   const options=choices.map(run=>h('option',{key:run.id,value:run.id},run.tool.toUpperCase()+' · '+run.started_at+' · '+run.id.slice(0,8)+(run.details?.comparisonSnapshot?.available?'':' · 无完整快照')));
   return h('label',{key,className:'rts-field'},label,h('select',{className:'rt-input',value,disabled:loading||busy,onChange:e=>selectComparison(key,e.target.value)},h('option',{value:''},'选择任务'),...options));
  });
  const comparisonGroups=comparisonValue?.available?Object.entries(comparisonLabels).map(([key,label])=>{
   const rows=comparisonValue.items[key].map((item,index)=>h('li',{key:index},item.rule+' · '+item.location+(item.subject?' · '+subjectText(item.subject):'')+' · '+item.title));
   return h('details',{key},h('summary',null,label+' · '+comparisonValue.summary[key]),h('ul',null,...rows));
  }):[];
  return h('div',{className:'rt-pane rt-security'},
   h('style',null,'.rt-security{display:flex;flex-direction:column;gap:14px}.rts-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.rts-head h3{margin:0}.rts-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px}.rts-field{display:flex;flex-direction:column;gap:5px;font-size:13px}.rt-security .rt-card{margin:0;padding:16px}.rt-security .rt-input{box-sizing:border-box;width:100%}.rts-tools{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}.rts-meta{font-size:12px;opacity:.8;overflow-wrap:anywhere}.rts-findings{display:flex;flex-direction:column;gap:10px}.rts-findings h4{margin:0 0 6px}.rts-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.rts-state{display:inline-block;border:1px solid currentColor;border-radius:12px;padding:2px 9px;font-size:12px}.rts-alert{border-left:3px solid #b7791f;padding:8px 12px;background:rgba(183,121,31,.07)}.rt-security button:disabled{opacity:.5;cursor:default}.rts-run{padding:8px 0;border-bottom:1px solid var(--dsw-alias-border-primary,#ddd)}'),
   h('div',{className:'rts-head'},h('div',null,h('h3',null,'安全审计'),h('p',{className:'rts-meta'},'确认项目范围 → 运行检查 → 验证发现 → 记录修复 → 复测')),h('div',{className:'rts-actions'},button(loading?'读取中…':'刷新',()=>load({resetPages:true}),loading),button('重新核对运行资源',()=>load({refreshRuntime:true,resetPages:true}),loading),button('漏洞库更新',()=>setUpdateGuide(value=>!value)),button(exporting?'正在导出…':'导出报告',download,!data||data.engagement!==engagement||!!error||loading||exporting))),
   h('div',{className:'rts-alert'},'扫描命中先进入“待验证”，复测通过仅代表所选规则与本次覆盖。新增范围限制覆盖本页和对应审计工具；通用 Shell、浏览器和原版能力沿用原权限。'),
   updateGuide&&h('section',{className:'rt-card','aria-label':'漏洞库更新说明'},h('h4',null,'在 Mac 上更新漏洞库'),h('p',null,'打开 Harness.command，选择选项 9。先检查版本；结束任务后选择更新并确认。下载及校验完成后会短暂重启 Harness，保留原库备份，不更换扫描器镜像。'),h('p',null,'若更新中断，请先选择检查；如提示维护未完成，再选择恢复。请勿重复提交更新。'),button('收起说明',()=>setUpdateGuide(false))),
   h('p',{className:'rts-meta'},'任务由 VM 独立后台持有，关闭网页或结束会话后继续运行。回来后刷新查看原任务；VM 关机或后台服务停止仍会中断，不会自动重跑。'),
   error&&h('div',{className:'rt-err',role:'alert'},error),
   !coordinated()&&h('p',{className:'rts-alert'},'本浏览器的多窗口协调不可用，审计写入和清除恢复记录已暂停；请使用支持 Web Locks 的同源浏览器页面。'),
   data&&unconfirmed&&h('p',{className:'rts-alert'},'当前资料未确认，以下为上次成功读取结果；写入和导出已暂停，请刷新核对。'),
   running&&!data.runs.some(row=>row.id===running.id)&&h('div',{className:'rts-alert'},'当前运行任务：'+running.id,button('取消当前任务',()=>mutate({op:'securityCancel',engagement,id:running.id}),loading||unconfirmed)),
   (pendingRequest||storageError)&&h('section',{className:'rts-alert','aria-label':'恢复未确认操作'},h('h4',null,'恢复未确认操作'),h('p',null,storageError||'发现本浏览器保存的未确认操作；不会自动重发。请先核对已保存任务与以下原始请求内容。'),pendingRequest&&h('pre',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},JSON.stringify(pendingRequest,null,2)),pendingRequest&&button('重试同一请求',()=>mutate(pendingRequest,{receipt:true}),loading||unconfirmed||!!storageError||!coordinated()),button('重新读取恢复记录',()=>load({resetPages:true}),loading),journal.current?.raw!==undefined&&journal.current?.raw!==null&&h('div',null,h('label',null,h('input',{type:'checkbox','aria-label':'确认清除恢复提示',checked:discardAck,disabled:busy||loading||unconfirmed,onChange:e=>{if(guard.current.context!==contextAtRender||guard.current.sequence!==viewGeneration||journal.current?.raw!==discardRaw)return;discardApproval.current=e.target.checked?{raw:discardRaw,generation:viewGeneration}:null;setDiscardAck(e.target.checked)}}),' 我已核对记录；清除此提示不会取消、撤销或证明原操作未执行。'),button('仅清除恢复提示',discardReceipt,!discardAck||loading||unconfirmed||!coordinated()))),
   !data&&!error&&h('p',null,'正在读取项目配置…'),
   data&&draft&&h('section',{className:'rt-card','aria-label':'项目审计范围'},h('h4',null,'项目审计范围'),h('p',{className:'rts-meta'},'仅扫描 /home/purge/workspace 下的所选目录；ZAP 第一期仅接入 VM 内 127.0.0.1 的明确端口。'),
    h('div',{className:'rts-grid'},field('仓库绝对路径','repoRoot'),field('VM 本地网址（ZAP 必填）','url','url'),field('授权到期时间（ISO 8601）','expiresAt'),field('ZAP 会话配置名（可选）','authProfile')),
    h('p',{className:'rts-meta'},'仅填写 VM 私有会话配置名；请在 Shell 工作台导入私有配置，勿把 Cookie 或令牌填入网页或聊天。会话需自行续期；认证仅核对扫描前后状态，不保证全程持续登录。'),
    h('div',{className:'rts-tools'},...Object.keys(toolNames).map(tool=>h('label',{key:tool},h('input',{type:'checkbox',checked:draft.tools.includes(tool),disabled:busy,onChange:e=>change('tools',e.target.checked?[...draft.tools,tool]:draft.tools.filter(v=>v!==tool))}),' '+tool.toUpperCase()))),
    ...['jointRea','jointPentagi'].map(key=>h('label',{key},h('input',{type:'checkbox',checked:!!draft[key],disabled:busy,onChange:e=>change(key,e.target.checked)}),key==='jointRea'?' 允许REA＋reverse-skill分析本项目脱敏JavaScript副本（固定静态图，不执行源码）':' 允许PentAGI向现有DeepSeek服务发送脱敏副本进行隔离静态审查（至多16次请求，每次2048输出tokens，无货币金额硬上限）')),
    h('label',null,h('input',{type:'checkbox',checked:!!draft.jointKali,disabled:busy,onChange:e=>change('jointKali',e.target.checked)}),' 允许联合审查向专用Kali交接本项目脱敏Python副本并执行固定离线Bandit检查'),
    h('label',null,h('input',{type:'checkbox',checked:!!draft.confirm,disabled:busy,onChange:e=>change('confirm',e.target.checked)}),' 我确认上述目录和本地网址可进行所选检查'),
    h('div',{className:'rts-actions'},button('保存范围',save,!actionable||!draft.confirm||!draft.repoRoot||!draft.tools.length),draft.revision!==(data.profile?.revision||0)&&button('采用最新范围（丢弃本地草稿）',()=>{dirty.current=false;setDraft({...data.profile,confirm:false})},!!running||!!writeReceipt.current||!!storageError),h('span',{className:'rts-meta'},'当前版本 '+(data.profile?.revision||0)+(expired?' · 未配置或已过期':'')))),
   data?.profile?.authProfile&&h('section',{className:'rt-card','aria-label':'私有会话配置状态'},h('h4',null,({ready:'会话配置有效',expiring:'会话配置即将到期',expired:'会话配置已过期',unavailable:'会话配置不可用'})[data.authSession?.state]||'会话配置状态未提供'),h('p',null,'当前已保存会话：'+data.profile.authProfile),data.authSession?.expiresAt&&h('p',null,'配置到期：'+data.authSession.expiresAt),data.authSession?.checkedAt&&h('p',{className:'rts-meta'},'配置核对：'+data.authSession.checkedAt),h('p',{className:'rts-meta'},'仅核对私有文件格式与有效期，未探测当前登录；开始扫描时仍会验证登录标记。网页不接收 Cookie 或令牌。'),button('重新导入说明',()=>setAuthGuide(value=>!value)),authGuide&&h('div',null,h('p',null,'原配置保留。先在 VM 私有文件中准备新的 value 与 expiresAt，再用新名称导入；在本页填写新名称并确认保存后才切换。'),data.authSession?.revision&&h('pre',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},'python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-local-lab.py renew-session '+data.profile.authProfile+' new-session --origin '+data.profile.url+' --expected-revision '+data.authSession.revision+' --confirm < /home/purge/downloads/private-renewal.json'),h('p',null,'原配置不可读取时，使用 import-session 导入完整的新配置。真实登录、MFA 与续期需自行完成，勿把私有值粘贴到网页或聊天。'))),
   data?.profile&&h(RuntimePanel,{key:'runtime-'+engagement,engagement,profile:data.profile,blocked:!actionable||expired||dirty.current}),
   data?.profile&&h(JointPanel,{key:'joint-'+engagement,engagement,profile:data.profile}),
   data?.review&&h('section',{className:'rt-card','aria-label':'审查预检与覆盖清单'},h('h4',null,'审查预检与覆盖清单'),validReview(data.review,data)?h('div',null,h('p',{className:'rts-meta'},'范围版本 '+data.review.scopeRevision+' · 只读清单 · '+(unconfirmed||loading?'当前资料未确认':'最近成功读取')),data.review.blockers.length>0&&h('p',{className:'rts-alert'},data.review.blockers.join('；')),h('p',null,'当前可提交的受管工具：'+(data.review.canStartTools.join(' / ')||'无，请核对范围和运行资源')),h('div',{className:'rts-grid'},...data.review.checks.map(c=>h('div',{key:c.id,className:'rts-run'},h('strong',null,c.label),h('p',null,reviewStates[c.state]),c.runId&&h('small',{className:'rts-meta'},'依据任务：'+c.runId)))),h('p',{className:'rts-meta'},data.review.notice),h('p',{className:'rts-meta'},'新聊天可选择“安全审查 · 受限工具”预设；保留现有原版模式。Kali合成验收可在聊天调用 kali_check，或在VM Shell按文档使用固定脚本。')):h('p',{className:'rts-alert'},'审查清单与当前项目不匹配或结构无效，资料未确认。')),
   data&&h('div',{className:'rts-grid'},...Object.keys(toolNames).map(tool=>h('section',{key:tool,className:'rt-card'},h('h4',null,toolNames[tool]),h('div',{className:'rts-meta'},data.tools[tool]?.ready?'已就绪 · '+data.tools[tool].version:(data.tools[tool]?.reason||'工具或离线数据库未就绪')),data.tools[tool]?.rules&&h('p',{className:'rts-meta'},'本地规则：'+data.tools[tool].rules.version+' · '+data.tools[tool].rules.count+' 条 · '+data.tools[tool].rules.languages.join(' / ')),data.tools[tool]?.checkedAt&&h('p',{className:'rts-meta'},'资源核对：'+data.tools[tool].checkedAt+(data.tools[tool].cached?' · 30秒内缓存':'')),data.tools[tool]?.database?.updatedAt&&h('p',{className:'rts-meta'},'漏洞库更新：'+data.tools[tool].database.updatedAt+' · '+data.tools[tool].database.ageDays+'天'),data.tools[tool]?.lastUpdate&&h('p',{className:'rts-meta'},'上次维护：'+label(maintenanceNames,data.tools[tool].lastUpdate.state,'未确认')+' · '+data.tools[tool].lastUpdate.checkedAt),data.tools[tool]?.warning&&h('p',{className:'rts-alert'},data.tools[tool].warning),h('p',{className:'rts-meta'},tool==='semgrep'?'本地启发式规则；需人工复核，不代表完整覆盖；不上传源码':tool==='trivy'?'离线数据库；检查依赖、配置和凭据痕迹':'被动检查与短时爬取；会向所选本地应用发送请求'),button('开始检查',()=>start(tool),!actionable||expired||!data.profile?.tools.includes(tool)||!data.tools[tool]?.ready||tool==='zap'&&!!data.profile?.authProfile&&!['ready','expiring'].includes(data.authSession?.state)||dirty.current)))),
   data&&h('section',{className:'rt-card','aria-label':'审计任务'},h('h4',null,'审计任务 · '+(pageTitle('runs')??('最近 '+data.runs.length+(data.totalRuns===undefined?'':' / '+data.totalRuns)))),pageControls('runs'),!data.runs.length&&h('p',null,data.pagination?'当前筛选没有匹配任务':'尚未运行检查'),...data.runs.map(run=>h('div',{key:run.id,className:'rts-run'},h('div',null,run.tool.toUpperCase()+' · '+label(statusNames,run.state)+' · '+run.started_at),h('div',{className:'rts-meta'},run.id+' · '+(run.revision_ref||'工作区扫描')+(run.error_code?' · '+run.error_code:'')),run.details?.supplemental&&h('p',{className:'rts-alert'},'有限文本补查 '+run.details.supplemental.checkedFiles+'/'+run.details.supplemental.candidateFiles+' 个候选文件；跳过 '+run.details.supplemental.skippedFiles+'；提示 '+run.details.supplemental.hints+(run.details.supplemental.truncated?'；窗口已截断':'')+'。仅匹配固定字样，注释或字符串也可能命中；语义解析缺口仍保留，不计完整覆盖。'),run.details?.authentication&&h('p',{className:'rts-meta'},'认证 '+(run.details.authentication.state==='verified'?'前后核对通过':'未确认')+' · '+run.details.authentication.profile+'；仅核对扫描前后，不保证持续登录。'),run.details?.diagnostics&&h('div',{className:'rts-alert'},'扫描诊断 '+run.details.diagnostics.total+' 项'+(run.details.diagnostics.truncated?' · 显示前20项':''),...run.details.diagnostics.items.map((d,index)=>h('p',{key:index},d.code+' · '+d.path+(d.line?':'+d.line:'')))),run.state==='partial'&&!run.details?.diagnostics&&h('p',{className:'rts-meta'},'旧任务未保存具体覆盖诊断；保持覆盖不完整，请重新检查后核对。'),run.state==='running'&&button('取消任务',()=>mutate({op:'securityCancel',engagement,id:run.id}),loading||unconfirmed)))),
   data&&h('section',{className:'rt-card','aria-label':'扫描结果对比'},
    h('h4',null,'扫描结果对比'),h('p',{className:'rts-meta'},'选择最近30次任务中的两个完整任务。新任务保存观察快照，旧任务缺少快照时无法推断；对比不会修改发现状态。'),
    h('div',{className:'rts-grid'},...comparisonFields),
    h('div',{className:'rts-actions'},button(ownedComparison?.loading?'正在对比…':'对比所选任务',compareSelected,!actionable||!!ownedComparison?.loading||!baseId||!currentId||baseId===currentId),comparisonValue?.available&&button('下载对比报告',downloadComparison)),
    ownedComparison?.error&&h('p',{className:'rt-err',role:'alert'},ownedComparison.error),
    comparisonValue&&!comparisonValue.available&&h('p',{className:'rts-alert'},comparisonValue.reason),
    comparisonValue?.available&&h('div',null,
     h('p',{className:'rts-alert'},comparisonValue.notice),
     h('div',{className:'rts-grid'},...Object.entries(comparisonLabels).map(([key,label])=>h('div',{key},label+'：'+comparisonValue.summary[key]))),
     comparisonValue.truncated&&h('p',{className:'rts-alert'},'每类仅展示前100条，统计来自完整已保存快照；对比报告也包含此截断说明。'),
     ...comparisonGroups)),
   data&&h('section',{className:'rt-card','aria-label':'审计发现'},h('h4',null,'发现 · '+(pageTitle('findings')??('显示 '+data.findings.length+(data.totalFindings===undefined?'':' / '+data.totalFindings)))),pageControls('findings'),!data.findings.length&&h('p',null,data.pagination?'当前筛选没有匹配发现；请结合任务覆盖判断。':data.runs.length?'当前没有已收录发现，请结合任务完成状态判断覆盖。':'运行检查后在此验证发现。'),h('div',{className:'rts-findings'},...data.findings.map(f=>h('article',{key:f.id,className:'rt-card'},h('h4',null,f.title),h('span',{className:'rts-state'},label(statusNames,f.status)),h('p',{className:'rts-meta'},f.severity+' · '+f.tool+' / '+f.rule+' · '+f.location),h('p',null,f.evidence),f.subject&&h('p',{className:'rts-meta'},'依赖包：'+subjectText(f.subject)),f.tool==='trivy'&&f.identityVersion!==1&&h('p',{className:'rts-alert'},'旧记录未区分依赖包身份，历史可能已合并；请重新扫描并人工核对。'),f.note&&h('p',{className:'rts-meta'},'上次说明：'+f.note),h('label',{className:'rts-field'},'验证或修复说明（至少 5 字）',h('textarea',{className:'rt-input',value:notes[f.id]||'',disabled:busy,onChange:e=>{const note=e.target.value;setNotes(old=>({...old,[f.id]:note}))}})),h('div',{className:'rts-actions'},...(['unverified','reopened','false-positive','retest-passed','fixed'].includes(f.status)?[button('确认发现',()=>review(f,'confirmed'),!actionable||(notes[f.id]||'').trim().length<5)]:[]),...(['unverified','reopened','confirmed'].includes(f.status)?[button('标记误报',()=>review(f,'false-positive'),!actionable||(notes[f.id]||'').trim().length<5)]:[]),f.status==='confirmed'&&button('记录修复',()=>review(f,'fixed'),!actionable||(notes[f.id]||'').trim().length<5),f.status==='fixed'&&button('复测此发现',()=>start(f.tool,f),!actionable||expired||dirty.current||!data.profile?.tools.includes(f.tool)||!data.tools[f.tool]?.ready)))))),
   data&&h('p',{className:'rts-meta'},'资料读取时间：'+data.observedAt));
 };
}
