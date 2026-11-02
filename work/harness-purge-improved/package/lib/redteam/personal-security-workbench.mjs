import {buildReviewPreflight,reviewScopePathReady,readReviewSource,runKaliReviewCheck} from './personal-security-review.mjs';
import {createHash,randomUUID} from 'node:crypto';
import {existsSync,readFileSync,realpathSync,mkdirSync,writeFileSync,lstatSync,openSync,closeSync,constants,unlinkSync} from 'node:fs';
import {join,resolve,relative,sep} from 'node:path';
import {spawn,execFileSync} from 'node:child_process';
import {homedir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {createScanSnapshot,compareScanSnapshots} from './personal-security-comparison.mjs';
import {modelSecurityResult} from './personal-security-model.mjs';
import {securityReportSummary,formatSecurityReport} from './personal-security-report.mjs';
import {packageSubject,normalizeSubject,decorateFinding} from './personal-security-identity.mjs';
import {redactDisplay,redactText} from './personal-evidence-redaction.mjs';
import {createRuntimeInspector,readRuntimeManifest} from './personal-security-runtime.mjs';
import {requestSecurityService} from './personal-security-service.mjs';
import {readSecurityPages} from './personal-security-pages.mjs';
import {supplementParserGaps,validParserTextSummary} from './personal-security-parser-text.mjs';
import {readZapAuthProfile,readZapAuthStatus,verifyZapSession} from './personal-security-auth.mjs';

const TOOLS=['semgrep','trivy','zap'],ROOT='/home/purge/tools/security-workbench';
const digest=value=>createHash('sha256').update(typeof value==='string'?value:JSON.stringify(value)).digest('hex');
const clean=(value,max=1200)=>redactText(String(value??'')).replace(/\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})\b/g,'[REDACTED]').slice(0,max);
const fail=message=>{throw Error(message)};
const requestId=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{8,100}$/.test(value)?value:fail('请求编号无效');
const numeric=value=>Number.isSafeInteger(value)&&value>0?value:fail('记录编号无效');
const only=(value,keys)=>{if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!keys.includes(key)))fail('请求字段无效')};
const stamp=()=>new Date().toISOString();
const schema=`CREATE TABLE IF NOT EXISTS security_scope(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL, request_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_run(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,request_hash TEXT NOT NULL,tool TEXT NOT NULL,profile_revision INTEGER NOT NULL,state TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,complete INTEGER NOT NULL DEFAULT 0,coverage_key TEXT,revision_ref TEXT,error_code TEXT,details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_finding(id INTEGER PRIMARY KEY AUTOINCREMENT,fingerprint TEXT UNIQUE NOT NULL,tool TEXT NOT NULL,rule TEXT NOT NULL,title TEXT NOT NULL,severity TEXT NOT NULL,location TEXT NOT NULL,evidence TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,first_run TEXT NOT NULL,last_run TEXT NOT NULL,coverage_key TEXT NOT NULL,note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS security_run_snapshot(run_id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_finding_subject(finding_id INTEGER PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_event(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,record_id TEXT NOT NULL,at TEXT NOT NULL,data TEXT NOT NULL);`;

export function parseScanOutput(tool,value,secrets=[]){
 value=redactDisplay(value,secrets);
 if(!value||typeof value!=='object'||Array.isArray(value))fail('扫描响应结构无效');
 const findings=[],coverageFiles=[],diagnosticItems=[];let diagnosticTotal=0,complete=true;
 const diagnostic=(code,path='',line=null)=>{diagnosticTotal++;if(diagnosticItems.length<20)diagnosticItems.push({code:typeof code==='string'&&/^[A-Za-z][A-Za-z0-9 _-]{0,79}$/.test(code)?code:'scanner-error',path:clean(path,400).replace(/^\/src\//,''),line:Number.isSafeInteger(line)&&line>0?line:null})};
 const finding=(rule,title,severity,location,evidence,subject=null)=>{
  const sev=String(severity||'info').toLowerCase(),map={error:'high',warning:'medium',note:'low',unknown:'info'};
  findings.push({rule:clean(rule,240),title:clean(title,400),severity:['critical','high','medium','low','info'].includes(sev)?sev:map[sev]||'info',location:clean(location,800).replace(/^\/src\//,''),evidence:clean(evidence,1800),subject});
 };
 if(tool==='semgrep'){
  if(!Array.isArray(value.results)||!Array.isArray(value.errors))fail('Semgrep响应结构无效');
  complete=value.errors.length===0&&Array.isArray(value.paths?.scanned)&&value.paths.scanned.length>0;
  for(const e of value.errors){const locations=Array.isArray(e?.type)?e.type[1]:null;for(const location of Array.isArray(locations)&&locations.length?locations:[null])diagnostic(Array.isArray(e?.type)?e.type[0]:e?.type,location?.path||e?.path||'',location?.start?.line)}
  if(!value.paths?.scanned?.length)diagnostic('coverage-unrecorded');
  for(const file of value.paths?.scanned||[])if(typeof file==='string')coverageFiles.push(clean(file,800).replace(/^\/src\//,''));
  for(const row of value.results){if(!row||typeof row.check_id!=='string'||typeof row.path!=='string'||!Number.isInteger(row.start?.line)||typeof row.extra?.message!=='string')fail('Semgrep记录结构无效');finding(row.check_id,row.extra.message,row.extra.severity,row.path+':'+row.start.line,'规则命中；源码片段未收录');}
 }else if(tool==='trivy'){
  if(!Array.isArray(value.Results))fail('Trivy响应结构无效');
  complete=value.Results.length>0;if(!complete)diagnostic('coverage-unrecorded');
  for(const result of value.Results){if(!result||typeof result.Target!=='string')fail('Trivy目标结构无效');coverageFiles.push(clean(result.Target,800).replace(/^\/src\//,''));
   for(const key of ['Vulnerabilities','Misconfigurations','Secrets']){
    if(result[key]!==undefined&&!Array.isArray(result[key]))fail('Trivy记录结构无效');
    for(const row of result[key]||[]){if(!row||typeof (row.VulnerabilityID||row.ID||row.RuleID)!=='string')fail('Trivy记录结构无效');
     finding(row.VulnerabilityID||row.ID||row.RuleID,row.Title||row.Description||key,row.Severity,result.Target+(row.StartLine?':'+row.StartLine:''),row.PkgName?`包 ${row.PkgName}；安装 ${row.InstalledVersion||'未知'}；修复版本 ${row.FixedVersion||'未知'}`:'检查命中；原始敏感值未收录',key==='Vulnerabilities'?packageSubject(row,clean):null);}
   }
   if(result.Error||result.Errors?.length){complete=false;diagnostic('target-incomplete',result.Target)}
  }
 }else if(tool==='zap'){
  if(!Array.isArray(value.site)||!value.site.length)fail('ZAP响应结构无效');
  for(const site of value.site){if(!Array.isArray(site.alerts))fail('ZAP告警结构无效');for(const row of site.alerts){if(!row||!Array.isArray(row.instances)||!row.pluginid)fail('ZAP告警结构无效');for(const instance of row.instances)finding(String(row.pluginid),row.name||row.alert,['info','low','medium','high'][Number(row.riskcode)]||'info',instance.uri||site['@name'],`被动检查；CWE ${row.cweid||'未分类'}；${instance.method||'HTTP'}`);}}
 }else fail('扫描器无效');
 if(findings.length>2000){complete=false;diagnostic('finding-limit-2000')}
 return{complete,findings:findings.slice(0,2000),coverageFiles:[...new Set(coverageFiles)],diagnostics:{total:diagnosticTotal,items:diagnosticItems,truncated:diagnosticTotal>diagnosticItems.length}};
}

export function buildScanPlan(tool,profile,runDir,manifest,authPolicy=null){
 if(!TOOLS.includes(tool))fail('扫描器无效');
 const installed=manifest?.tools?.find(row=>row.tool===tool);if(!/^sha256:[a-f0-9]{64}$/.test(installed?.imageId||''))fail('扫描器尚未安装或摘要未确认');
 const args=['-n','/usr/bin/docker','run','--rm','--pull','never','--log-driver','none','--name','dsh-sec-'+runDir.split('/').pop(),'--label','personal.harness.security=true','--cpus','1','--memory',tool==='zap'?'1100m':'768m','--pids-limit','160','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--tmpfs','/tmp:rw,nosuid,size=268435456','--user','1000:1000','--mount','type=bind,src='+profile.repoRoot+',dst=/src,readonly','--mount','type=bind,src='+runDir+',dst=/input,readonly','--mount','type=bind,src='+fileURLToPath(new URL('../../scripts/security-output.sh',import.meta.url))+',dst=/policy-output.sh,readonly'];
 let command;
 if(tool==='semgrep'){
  args.push('--network','none','--mount','type=bind,src='+join(ROOT,'rules.json')+',dst=/policy/rules.json,readonly','--env','SEMGREP_SEND_METRICS=off','--env','SEMGREP_ENABLE_VERSION_CHECK=0','--env','HOME=/tmp');
  command=['semgrep','scan','--config','/policy/rules.json','--json','--output','/out/result.json','--metrics=off','--disable-version-check','--jobs','1','--timeout','5','--max-target-bytes','1000000','/src'];
 }else if(tool==='trivy'){
  args.push('--network','none','--mount','type=bind,src='+join(ROOT,'cache/db')+',dst=/tmp/trivy/db,readonly',);
  command=['trivy','filesystem','--cache-dir','/tmp/trivy','--cache-backend','memory','--skip-db-update','--skip-java-db-update','--skip-check-update','--offline-scan','--scanners','vuln,misconfig,secret','--format','json','--output','/out/result.json','/src'];
 }else{
  if(!profile.url)fail('请先配置已授权的VM本地URL');args.push('--network','host','--workdir','/zap/wrk','--tmpfs','/home/zap/.ZAP:rw,uid=1000,gid=1000,size=67108864','--env','HOME=/tmp','--env','JAVA_OPTS=-Xmx640m');
  command=['zap-baseline.py','--autooff','--hook','/input/loopback-hook.py','-t',profile.url,'-n','/input/scope.context','-m','1','-T','3','-P','49090','-J','result.json','-z','-silent -Xmx640m -dir /tmp/zap -host 127.0.0.1 -config autoupdate.checkOnStart=false'];
 }
 const output=tool==='zap'?'/zap/wrk':'/out';args.push('--tmpfs',output+':rw,nosuid,nodev,noexec,size=67108864,uid=1000,gid=1000,mode=0700','--entrypoint','/bin/sh',installed.imageId,'/policy-output.sh',output,...command);return{outputQuotaBytes:67108864,executable:'/usr/bin/sudo',args,outputFile:join(runDir,'result.json'),containerName:'dsh-sec-'+runDir.split('/').pop(),version:installed.version||'未确认',coverageKey:digest([tool,installed.imageId,manifest.rulesSha256,manifest.database?.digest||null,profile.repoRoot,tool==='zap'?profile.url:null,...(tool==='semgrep'?['parser-text-1']:[]),...(tool==='trivy'?['package-identity-1']:[]),...(tool==='zap'?['pinned-addons-1']:[]),...(tool==='zap'&&profile.authProfile?['private-session-1',profile.authProfile,authPolicy?.revision||'unverified']:[])])};
}

function manifestOf(){try{return readRuntimeManifest(ROOT)}catch{return{tools:[]}}}
const runtimeInspector=createRuntimeInspector();
export function installedSecurityTools(options){return runtimeInspector.read(options)}

export function buildZapContext(url,excludePaths=[]){
 const value=new URL(url);if(value.origin!==url||value.hostname!=='127.0.0.1'||value.protocol!=='http:'||!value.port)fail('ZAP范围无效');
 if(!Array.isArray(excludePaths)||excludePaths.length>10||excludePaths.some(path=>typeof path!=='string'||!/^\/[A-Za-z0-9._~/-]{1,299}$/.test(path)||path.includes('//')||path.split('/').some(part=>part==='.'||part==='..')))fail('ZAP排除路径无效');
 const escape=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),escaped=escape(url);
 const excluded=excludePaths.map(path=>'<excregexes>^'+escaped+escape(path.replace(/\/+$/,''))+'(?:[/?].*)?$</excregexes>').join('');
 return '<?xml version="1.0"?><configuration><context><name>Harness explicit local scope</name><inscope>true</inscope><incregexes>^'+escaped+'(?:/.*)?$</incregexes>'+excluded+'</context></configuration>';
}
export function buildZapHook(authenticated=false){
 const base=`# Fixed Harness hook: the upstream CLI currently honors its first -host option.
import zap_common
def start_zap(port, extra_zap_params):
    original = zap_common.create_start_options
    def local_options(mode, actual_port, extra):
        args = original(mode, actual_port, extra)
        hosts = [i for i, value in enumerate(args) if value == "-host"]
        if not hosts:
            raise RuntimeError("ZAP listener arguments unavailable")
        for i in hosts:
            if i + 1 >= len(args):
                raise RuntimeError("ZAP listener argument invalid")
            args[i + 1] = "127.0.0.1"
        return args
    zap_common.create_start_options = local_options
    return port, extra_zap_params
`;
 return base+(authenticated?String.raw`
import json, re, os, time, datetime
from pathlib import Path
_auth_state = {'version': 1, 'revision': None, 'before': False, 'after': False, 'checkedRequests': 0}
# The pinned CLI loads ModuleType through SourceFileLoader without __file__.
# Fixed writable working directory is bounded container tmpfs; private input is read-only.
_auth_directory = Path.cwd()
def _auth_config():
    with open(Path('/input') / '.session.json', 'rb') as source:
        raw = source.read(8193)
    if len(raw) > 8192:
        raise RuntimeError('HARNESS_AUTH_CONFIG_INVALID')
    auth = json.loads(raw)
    if datetime.datetime.fromisoformat(auth['expiresAt'].replace('Z', '+00:00')).timestamp() <= time.time():
        raise RuntimeError('HARNESS_AUTH_EXPIRED')
    return auth
def _auth_probe(zap, auth, phase):
    request = 'GET '+auth['origin']+auth['verifyPath']+' HTTP/1.1\r\nHost: '+auth['origin'].split('://', 1)[1]+'\r\nConnection: close\r\n\r\n'
    messages = zap.core.send_request(request, followredirects='false')
    if not isinstance(messages, list) or len(messages) != 1:
        raise RuntimeError('HARNESS_AUTH_CHECK_FAILED')
    message = messages[0]
    body = message.get('responseBody', '')
    if not re.match(r'^HTTP/[0-9.]+ 200(?:\s|$)', message.get('responseHeader', '')) or not isinstance(body, str) or len(body.encode('utf-8')) > 65536 or auth['loggedInMarker'] not in body:
        raise RuntimeError('HARNESS_AUTH_CHECK_FAILED')
    if _auth_state['revision'] not in (None, auth['revision']):
        raise RuntimeError('HARNESS_AUTH_CONFIG_CHANGED')
    _auth_state['revision'] = auth['revision']
    _auth_state[phase] = True
    _auth_state['checkedRequests'] += 1
    _auth_save()
def _auth_save():
    descriptor = os.open(_auth_directory / 'auth-check.json', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(_auth_state, output)
def zap_tuned(zap):
    try:
        auth = _auth_config()
        _auth_state['revision'] = auth['revision']
        _auth_save()
        result = zap.replacer.add_rule('harness-private-session', 'true', 'REQ_HEADER', 'false', auth['header'], auth['value'], url='^'+re.escape(auth['origin'])+r'(?:/.*)?$')
        if result != 'OK':
            raise RuntimeError('HARNESS_AUTH_SETUP_FAILED')
        zap.spider.set_option_process_form('false')
        zap.spider.set_option_post_form('false')
        _auth_probe(zap, auth, 'before')
    except Exception:
        raise RuntimeError('HARNESS_AUTH_SETUP_UNCONFIRMED') from None
def zap_pre_shutdown(zap):
    try:
        if not _auth_state['before']:
            raise RuntimeError('HARNESS_AUTH_SETUP_UNCONFIRMED')
        _auth_probe(zap, _auth_config(), 'after')
    except Exception:
        _auth_state['after'] = False
        _auth_save()
`: '');
}
async function runScanner(tool,profile,{signal,runDir}){
 const rootIdentity=lstatSync(profile.repoRoot);if(!rootIdentity.isDirectory()||rootIdentity.isSymbolicLink()||realpathSync(profile.repoRoot)!==profile.repoRoot)throw Object.assign(Error('仓库目录已变化'),{code:'SCAN_SCOPE_CHANGED'});
 const deadline=performance.now()+240000,auth=tool==='zap'&&profile.authProfile?readZapAuthProfile(profile.authProfile,profile.url):null;
 const before=auth?await verifyZapSession(auth,{signal,timeoutMs:Math.min(3000,deadline-performance.now())}):null;
 mkdirSync(runDir,{recursive:true,mode:0o700});const manifest=manifestOf(),plan=buildScanPlan(tool,profile,runDir,manifest,auth);
 const sessionPath=join(runDir,'.session.json');let privateCopy=false;
 let termination;
 const stopContainer=()=>termination||(termination=new Promise(resolveStop=>{
  const child=spawn('/usr/bin/sudo',['-n','/usr/bin/docker','stop','--time','3',plan.containerName],{stdio:'ignore'});
  const timer=setTimeout(()=>{child.kill('SIGKILL');resolveStop(false)},8000);
  child.once('error',()=>{clearTimeout(timer);resolveStop(false)});
  child.once('close',code=>{clearTimeout(timer);resolveStop(code===0)});
 }));
 let bytes=0,timedOut=false,overflow=false,exit,chunks=[],envelope;
 try{
  if(tool==='zap'){
   writeFileSync(join(runDir,'scope.context'),buildZapContext(profile.url,auth?.excludePaths??[]),{mode:0o600});
   writeFileSync(join(runDir,'loopback-hook.py'),buildZapHook(!!auth),{mode:0o600});
   if(auth){
    const {secretValues,...config}=auth,fd=openSync(sessionPath,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600);privateCopy=true;
    try{writeFileSync(fd,JSON.stringify(config))}finally{closeSync(fd)}
   }
  }
  exit=await new Promise((done,reject)=>{
   const child=spawn(plan.executable,plan.args,{stdio:['ignore','pipe','pipe'],env:{PATH:'/usr/bin:/bin',HOME:'/home/purge',LANG:'C.UTF-8'}});
   const terminate=()=>{stopContainer();child.kill('SIGTERM')};
   const timer=setTimeout(()=>{timedOut=true;terminate()},Math.max(1,deadline-performance.now()));
   const abort=()=>terminate();signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
   const cleanup=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort)};
   const consume=chunk=>{bytes+=chunk.length;if(bytes>8*1024*1024+65536&&!overflow){overflow=true;terminate()}};
   child.stdout.on('data',chunk=>{consume(chunk);if(!overflow)chunks.push(chunk)});child.stderr.on('data',consume);
   child.once('error',()=>{cleanup();reject(Object.assign(Error('扫描进程未能启动'),{code:'SCAN_SPAWN'}))});
   child.once('close',async code=>{cleanup();if(termination&&!await termination)reject(Object.assign(Error('容器停止未确认，请先检查VM运行状态'),{code:'STOP_UNCONFIRMED'}));else done(code)});
  });
  if(signal.aborted)throw Error('已取消');if(timedOut)throw Object.assign(Error('扫描超时'),{code:'SCAN_TIMEOUT'});if(overflow)throw Object.assign(Error('输出超出上限'),{code:'SCAN_OUTPUT_LIMIT'});
  if(exit===137)throw Object.assign(Error('扫描被内存上限终止'),{code:'SCAN_MEMORY_LIMIT'});
  try{envelope=JSON.parse(Buffer.concat(chunks).toString('utf8'))}catch{if(exit===73)throw Object.assign(Error('结果超出上限'),{code:'SCAN_OUTPUT_LIMIT'});throw Object.assign(Error('扫描结果未确认'),{code:'SCAN_OUTPUT_INVALID'})}
  const accepted=tool==='zap'?[0,1,2]:[0];if(auth&&!accepted.includes(exit)&&!envelope?.authentication?.before)throw Object.assign(Error('认证扫描未确认'),{code:'AUTH_VERIFY'});if(!accepted.includes(exit))throw Object.assign(Error('扫描未完成'),{code:exit===137?'SCAN_MEMORY_LIMIT':'SCAN_EXIT_FAILURE'});
  if(!envelope?.result||typeof envelope.result!=='object'||Array.isArray(envelope.result)||Object.keys(envelope).sort().join(',')!=='authentication,result')throw Error('结果文件无效');
  const raw=envelope.result,parsed=parseScanOutput(tool,raw,auth?.secretValues??[]);
  if(tool==='semgrep'&&!parsed.complete){
   const supplement=supplementParserGaps(profile.repoRoot,raw.errors,{signal,deadline,identity:rootIdentity});parsed.supplemental=supplement.summary;parsed.findings.push(...supplement.findings);
   if(parsed.findings.length>2000){parsed.findings=parsed.findings.slice(0,2000);const d=parsed.diagnostics;d.total++;d.items=[{code:'finding-limit-2000',path:'',line:null},...d.items].slice(0,20);d.truncated=d.total>d.items.length}
  }
  if(auth){
   let after=null;try{after=await verifyZapSession(auth,{signal,timeoutMs:Math.min(3000,deadline-performance.now())})}catch(error){if(signal.aborted)throw error}
   const proof=envelope.authentication,matched=proof?.version===1&&proof?.revision===auth.revision;
   parsed.authentication={version:1,profile:profile.authProfile,revision:auth.revision,before:before?.verified===true,after:after?.verified===true,scannerBefore:matched&&proof.before===true,scannerAfter:matched&&proof.after===true,checkedRequests:matched&&proof.checkedRequests===2?2:0};
  }
  let revisionRef='工作区未确认';try{revisionRef=execFileSync('/usr/bin/git',['-C',profile.repoRoot,'rev-parse','HEAD'],{timeout:3000,encoding:'utf8'}).trim()}catch{}
  return{...parsed,coverageKey:plan.coverageKey,version:plan.version,revisionRef};
 }finally{
  try{if(termination)await termination}
  finally{if(privateCopy)try{unlinkSync(sessionPath)}catch(error){if(error.code!=='ENOENT')throw Object.assign(Error('私有会话副本清理未确认'),{code:'AUTH_CLEANUP'})}}
 }
}

function authenticatedResult(profile,result){
 const value=result.authentication,revision=typeof value?.revision==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value.revision)?value.revision:null;
 const flags=Object.fromEntries(['before','after','scannerBefore','scannerAfter'].map(key=>[key,value?.[key]===true]));
 const verified=value?.version===1&&value?.profile===profile.authProfile&&revision!==null&&value?.checkedRequests===2&&Object.values(flags).every(Boolean);
 const authentication={version:1,profile:profile.authProfile,revision,state:verified?'verified':'unconfirmed',verification:'controller-and-zap-before-after',...flags,checkedRequests:value?.checkedRequests===2?2:0};
 if(verified)return{...result,authentication};
 const diagnostic=result.diagnostics??{total:0,items:[],truncated:false},items=[{code:'authentication-unconfirmed',path:'',line:null},...diagnostic.items].slice(0,20);
 return{...result,authentication,complete:false,diagnostics:{total:diagnostic.total+1,items,truncated:diagnostic.truncated||diagnostic.total+1>items.length}};
}

export class SecurityWorkbench{
 constructor(store,{workspaceRoot='/home/purge/workspace',runner=runScanner,toolStatus=installedSecurityTools,authStatus=readZapAuthStatus}={}){this.store=store;this.workspaceRoot=resolve(workspaceRoot);this.runner=runner;this.toolStatus=toolStatus;this.authStatus=authStatus;this.initialized=new Set();this.active=null;this.disposed=false}
 db(eng){
  if(this.disposed)fail('工作台正在关闭');
  this.store.sessionBindings.validateTarget(eng);
  const db=this.store.db(eng);if(!this.initialized.has(eng)){db.exec(schema);db.prepare("UPDATE security_run SET state='interrupted',finished_at=?,error_code='入口已重启，结果未确认' WHERE state='running'").run(stamp());this.initialized.add(eng)}return db;
 }
 profile(db){const row=db.prepare('SELECT revision,data FROM security_scope WHERE id=1').get();return row?{...JSON.parse(row.data),revision:row.revision}:null}
 read(eng,runtimeOptions={},pages=null){
  const db=this.db(eng),profile=this.profile(db),runView=row=>({...row,details:JSON.parse(row.details)});
  const lists=pages===null?{runs:db.prepare('SELECT * FROM security_run ORDER BY started_at DESC,id DESC LIMIT 30').all(),findings:db.prepare('SELECT * FROM security_finding ORDER BY id DESC LIMIT 500').all()}:readSecurityPages(db,eng,pages);
  const runtime=this.toolStatus(runtimeOptions),authSession=profile?.authProfile?this.authStatus(profile.authProfile,profile.url):null;
  const review=buildReviewPreflight({engagement:eng,profile,authSession,tools:runtime,runs:db.prepare('SELECT * FROM security_run ORDER BY started_at DESC,id DESC LIMIT 30').all()},{scopePathReady:reviewScopePathReady(profile)});
  const extra=pages===null?{}:{activeRun:(row=>row?runView(row):null)(db.prepare("SELECT * FROM security_run WHERE state='running' ORDER BY rowid DESC LIMIT 1").get()),comparisonRuns:db.prepare("SELECT * FROM security_run WHERE state='completed' AND complete=1 ORDER BY rowid DESC LIMIT 30").all().map(runView)};
  return{review,ok:true,engagement:eng,totalFindings:db.prepare('SELECT COUNT(*) AS n FROM security_finding').get().n,totalRuns:db.prepare('SELECT COUNT(*) AS n FROM security_run').get().n,profile,tools:runtime,authSession,...lists,runs:lists.runs.map(runView),findings:lists.findings.map(row=>decorateFinding(db,row)),...extra,scopeCoverage:'新增扫描入口；通用Shell、浏览器和原版能力沿用原权限',observedAt:stamp()};
 }
 preflight(eng,input={}){only(input,[]);const value=this.read(eng,{force:true});return{ok:true,engagement:eng,review:value.review}}
 source(eng,input){return this.store.redactResult(eng,{engagement:eng,...readReviewSource(this.profile(this.db(eng)),input,value=>this.store.redactResult(eng,{text:value}).text)})}
 async kaliCheck(eng,input){const p=this.profile(this.db(eng));if(!p||Date.parse(p.expiresAt)<=Date.now())fail('请先保存有效项目范围');if(this.rehearsalActive)fail('Kali合成验收正在运行，请核对原请求');this.rehearsalActive=true;try{return await runKaliReviewCheck(eng,input)}finally{this.rehearsalActive=false}}
 async wait(eng,input){
  only(input,['id','waitSeconds']);const id=requestId(input.id),seconds=input.waitSeconds??15;if(!Number.isSafeInteger(seconds)||seconds<0||seconds>30)fail('waitSeconds必须是0–30的整数');
  const db=this.db(eng),get=()=>{const row=db.prepare('SELECT * FROM security_run WHERE id=?').get(id);if(!row)fail('本项目不存在该任务');return{...row,details:JSON.parse(row.details)}};
  const initial=get();if(initial.state==='running'&&seconds>0){const active=this.active;let timer;try{await Promise.race([active?.id===id&&active.eng===eng?active.promise:new Promise(()=>{}),new Promise(resolve=>{timer=setTimeout(resolve,seconds*1000)})])}finally{clearTimeout(timer)}}
  const run=get();return{ok:true,engagement:eng,run,timedOut:run.state==='running'};
 }
 saveScope(eng,input){
  only(input,['requestId','revision','repoRoot','tools','url','expiresAt','confirm','authProfile']);const id=requestId(input.requestId),db=this.db(eng),hash=digest(input);
  const existing=db.prepare('SELECT data FROM security_event WHERE request_id=?').get(id);if(existing){const value=JSON.parse(existing.data);if(value.hash!==hash)fail('重复请求内容不同');return value.result}
  if(this.active)fail('任务正在运行，暂不能修改范围');const previous=this.profile(db);if(input.revision!==(previous?.revision||0))fail('范围已变化，请刷新后重试');
  if(input.confirm!==true||!Array.isArray(input.tools)||!input.tools.length||input.tools.some(tool=>!TOOLS.includes(tool))||new Set(input.tools).size!==input.tools.length)fail('请明确确认允许的扫描器');
  const root=resolve(String(input.repoRoot||''));if(!root.startsWith(this.workspaceRoot+sep)||root!==realpathSync(root)||!lstatSync(root).isDirectory())fail('仓库必须是VM工作区内的普通目录，不能跨越链接');
  if(/[\x00-\x1f,]/.test(root))fail('仓库路径包含不支持的字符');
  const expiry=Date.parse(input.expiresAt);if(!Number.isFinite(expiry)||expiry<=Date.now()||expiry>Date.now()+31*86400000)fail('授权期限必须在未来31天以内');
  let url=null;if(input.url){const parsed=new URL(input.url);if(parsed.protocol!=='http:'||parsed.hostname!=='127.0.0.1'||!parsed.port||Number(parsed.port)<1024||[3080,18443,49222,49223,49224,49226,49090].includes(Number(parsed.port))||parsed.username||parsed.password||parsed.search||parsed.hash||parsed.pathname!=='/')fail('仅允许VM内明确端口的127.0.0.1 HTTP根地址，不接受管理端口');url=parsed.origin}
  const authProfile=input.authProfile??'';if(typeof authProfile!=='string'||authProfile!==''&&(!/^[a-z][a-z0-9_-]{0,47}$/.test(authProfile)||!url||!input.tools.includes('zap')))fail('认证配置名无效或未允许ZAP本地网址');
  const data={repoRoot:root,tools:input.tools,url,expiresAt:new Date(expiry).toISOString(),...(authProfile?{authProfile}:{})},result={...data,revision:(previous?.revision||0)+1};
  db.exec('SAVEPOINT security_scope_save');try{db.prepare('INSERT INTO security_scope VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,data=excluded.data,request_id=excluded.request_id').run(result.revision,JSON.stringify(data),id);this.event(db,id,'scope','1',{hash,result});db.exec('RELEASE security_scope_save')}catch(error){db.exec('ROLLBACK TO security_scope_save;RELEASE security_scope_save');throw error}return result;
 }
 event(db,id,kind,record,data){db.prepare('INSERT INTO security_event(request_id,kind,record_id,at,data) VALUES(?,?,?,?,?)').run(id,kind,String(record),stamp(),JSON.stringify(redactDisplay(data)))}
 start(eng,input){
  only(input,['requestId','profileRevision','tool','retestFindingId']);const db=this.db(eng),id=requestId(input.requestId),hash=digest(input),previous=db.prepare('SELECT * FROM security_run WHERE request_id=?').get(id);if(previous){if(previous.request_hash!==hash)fail('重复请求内容不同');return{id:previous.id,state:previous.state}}
  if(this.disposed)fail('工作台正在关闭');if(this.blocked)fail('上次容器停止未确认，请检查VM运行状态后重启入口');if(this.active)fail('任务正在运行，请等待或取消');const profile=this.profile(db);
  if(!profile||profile.revision!==input.profileRevision||Date.parse(profile.expiresAt)<=Date.now()||!profile.tools.includes(input.tool))fail('项目范围未授权、已过期或已变化');
  const runtime=this.toolStatus({force:true})[input.tool];if(!runtime?.ready)fail(runtime?.reason||'扫描器或数据库未就绪');if(realpathSync(profile.repoRoot)!==profile.repoRoot)fail('仓库路径已变化');if(input.tool==='zap'&&!profile.url)fail('请先配置VM本地URL');
  if(input.retestFindingId){const finding=db.prepare('SELECT * FROM security_finding WHERE id=?').get(numeric(input.retestFindingId));if(!finding||finding.tool!==input.tool||finding.status!=='fixed')fail('仅可复测本项目已记录修复的同类发现')}
  const runId=randomUUID(),details={profile,version:runtime.version,runtime:{checkedAt:runtime.checkedAt||null,database:runtime.database||null,rules:runtime.rules||null,warning:runtime.warning||null},retestFindingId:input.retestFindingId||null};
  db.prepare('INSERT INTO security_run(id,request_id,request_hash,tool,profile_revision,state,started_at,details) VALUES(?,?,?,?,?,?,?,?)').run(runId,id,hash,input.tool,profile.revision,'running',stamp(),JSON.stringify(details));
  const controller=new AbortController();this.active={id:runId,eng,controller};
  const promise=Promise.resolve().then(()=>this.disposed?null:this.runner(input.tool,profile,{signal:controller.signal,runDir:join(this.store.dirOf(eng),'runs','security',runId)})).then(result=>{
   if(this.disposed)return;
   if(controller.signal.aborted){db.prepare("UPDATE security_run SET state='cancelled',finished_at=? WHERE id=?").run(stamp(),runId);return}
   if(!result||!Array.isArray(result.findings)||typeof result.complete!=='boolean'||typeof result.coverageKey!=='string')fail('扫描回执无效');
   if(input.tool==='zap'&&profile.authProfile){result=authenticatedResult(profile,result);details.authentication=result.authentication}
   if(result.supplemental!==undefined){if(input.tool!=='semgrep'||result.complete||!validParserTextSummary(result.supplemental))fail('文本补查回执无效');details.supplemental={...result.supplemental}}
   db.exec('SAVEPOINT security_results');try{
    const seen=new Set(),normalized=[];for(const raw of result.findings){const item={rule:clean(raw.rule,240),title:clean(raw.title,400),severity:clean(raw.severity,20),location:clean(raw.location,800),evidence:clean(raw.evidence),subject:normalizeSubject(raw.subject)};if(!item.rule||!item.location)fail('发现记录无效');normalized.push({rule:item.rule,title:item.title,severity:item.severity,location:item.location,subject:item.subject});const fingerprint=digest([input.tool,profile.repoRoot,input.tool==='zap'?profile.url:null,item.rule,item.location,...(item.subject?['package-identity-1',item.subject.key]:[])]);seen.add(fingerprint);const old=db.prepare('SELECT * FROM security_finding WHERE fingerprint=?').get(fingerprint);
     if(old){const status=['fixed','retest-passed'].includes(old.status)?'reopened':old.status;db.prepare('UPDATE security_finding SET title=?,severity=?,evidence=?,status=?,last_run=?,coverage_key=?,revision=revision+1 WHERE id=?').run(item.title,item.severity,item.evidence,status,runId,result.coverageKey,old.id);if(status!==old.status)this.event(db,'reopen-'+randomUUID(),'finding',old.id,{from:old.status,to:status,runId})}
     else db.prepare('INSERT INTO security_finding(fingerprint,tool,rule,title,severity,location,evidence,status,first_run,last_run,coverage_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)').run(fingerprint,input.tool,item.rule,item.title,item.severity,item.location,item.evidence,'unverified',runId,runId,result.coverageKey);
     const storedId=old?.id??db.prepare('SELECT id FROM security_finding WHERE fingerprint=?').get(fingerprint).id;
     db.prepare('INSERT INTO security_finding_subject(finding_id,data) VALUES(?,?) ON CONFLICT(finding_id) DO UPDATE SET data=excluded.data').run(storedId,JSON.stringify(item.subject));
    }
    if(input.retestFindingId){
     const rawOld=db.prepare('SELECT * FROM security_finding WHERE id=?').get(input.retestFindingId),old=rawOld&&decorateFinding(db,rawOld),fileOf=value=>value.replace(/:\d+$/,'');
     const identified=old&&(old.tool!=='trivy'||old.identityVersion===1);
     const present=old&&normalized.some(item=>item.rule===old.rule&&fileOf(item.location)===fileOf(old.location)&&(old.subject?item.subject?.family===old.subject.family:!item.subject));
     const covered=old&&Array.isArray(result.coverageFiles)&&result.coverageFiles.includes(fileOf(old.location));
     const next=old?.status==='fixed'&&identified?(present?'reopened':result.complete&&covered&&old.coverage_key===result.coverageKey?'retest-passed':null):null;
     if(next){db.prepare('UPDATE security_finding SET status=?,revision=revision+1,last_run=? WHERE id=?').run(next,runId,old.id);this.event(db,'retest-'+randomUUID(),'finding',old.id,{from:old.status,to:next,runId})}
     details.retestOutcome=next||(!identified?'旧Trivy记录缺少依赖包身份，不能自动推断复测结论，保留原状态':'尚未证明原位置已被完整复测，保留原状态');
    }
    const snapshot=result.complete?createScanSnapshot(normalized,Array.isArray(result.coverageFiles)?result.coverageFiles.map(file=>clean(file,800)):undefined):null;
    details.comparisonSnapshot={available:snapshot!==null,reason:snapshot===null?'未提供完整、有界的扫描快照':null};
    if(snapshot!==null)db.prepare('INSERT INTO security_run_snapshot(run_id,data) VALUES(?,?)').run(runId,snapshot);
    details.coveredFiles=Array.isArray(result.coverageFiles)?result.coverageFiles.length:0;
    if(result.diagnostics){const d=result.diagnostics;if(!Number.isSafeInteger(d.total)||d.total<0||!Array.isArray(d.items)||d.items.length>20||d.items.length>d.total||typeof d.truncated!=='boolean'||d.items.some(v=>!v||typeof v.code!=='string'||!/^([A-Za-z][A-Za-z0-9 _-]{0,79})$/.test(v.code)||typeof v.path!=='string'||v.path.length>400||!(v.line===null||Number.isSafeInteger(v.line)&&v.line>0)))fail('扫描诊断结构无效');details.diagnostics={total:d.total,items:d.items.map(v=>({code:v.code,path:clean(v.path,400),line:v.line})),truncated:d.truncated}}
    db.prepare('UPDATE security_run SET details=? WHERE id=?').run(JSON.stringify(details),runId);
    db.prepare('UPDATE security_run SET state=?,finished_at=?,complete=?,coverage_key=?,revision_ref=? WHERE id=?').run(result.complete?'completed':'partial',stamp(),Number(result.complete),result.coverageKey,clean(result.revisionRef||'未记录',100),runId);db.exec('RELEASE security_results');
   }catch(error){db.exec('ROLLBACK TO security_results;RELEASE security_results');throw error}
  }).catch(error=>{
   if(error?.code==='STOP_UNCONFIRMED')this.blocked=true;
   const messages={SCAN_SCOPE_CHANGED:'仓库目录已变化；请重新核对项目范围',AUTH_PROFILE:'私有认证配置不可用、已过期或与本地范围不匹配',AUTH_VERIFY:'认证状态未确认，扫描未完成',AUTH_CLEANUP:'私有会话副本清理未确认，请检查VM运行目录',STOP_UNCONFIRMED:'容器停止未确认，请检查VM运行状态',SCAN_SPAWN:'扫描进程未能启动',SCAN_TIMEOUT:'扫描达到4分钟上限',SCAN_OUTPUT_LIMIT:'扫描结果超过8MiB读取上限或输出空间限制',SCAN_MEMORY_LIMIT:'扫描被内存上限终止',SCAN_EXIT_FAILURE:'扫描器返回失败，请检查VM本地运行记录'};
   if(!this.disposed)db.prepare('UPDATE security_run SET state=?,finished_at=?,error_code=? WHERE id=?').run(controller.signal.aborted&&!this.blocked?'cancelled':'failed',stamp(),this.blocked?messages.STOP_UNCONFIRMED:controller.signal.aborted?'任务已取消':messages[error?.code]||'扫描结果未完成或格式无效',runId)
  }).finally(()=>{if(this.active?.id===runId)this.active=null});
  this.active.promise=promise;return{id:runId,state:'running'};
 }
 review(eng,input){
  only(input,['id','revision','status','note','requestId']);const db=this.db(eng),rid=requestId(input.requestId),hash=digest(input),event=db.prepare('SELECT data FROM security_event WHERE request_id=?').get(rid);if(event){const old=JSON.parse(event.data);if(old.hash!==hash)fail('重复请求内容不同');return old.result}
  if(this.active)fail('任务正在运行，请在结束后核对发现');const old=db.prepare('SELECT * FROM security_finding WHERE id=?').get(numeric(input.id));if(!old||old.revision!==input.revision)fail('发现记录已变化，请刷新');
  const transitions={unverified:['confirmed','false-positive'],reopened:['confirmed','false-positive'],confirmed:['fixed','false-positive'],fixed:['confirmed'], 'false-positive':['confirmed'],'retest-passed':['confirmed']};
  if(!transitions[old.status]?.includes(input.status)||typeof input.note!=='string'||input.note.trim().length<5||input.note.length>2000)fail('状态转换或验证/修复说明无效');
  const result={...old,status:input.status,note:clean(input.note,2000),revision:old.revision+1};db.exec('SAVEPOINT security_review');try{db.prepare('UPDATE security_finding SET status=?,note=?,revision=? WHERE id=?').run(result.status,result.note,result.revision,result.id);this.event(db,rid,'review',old.id,{hash,result});db.exec('RELEASE security_review')}catch(error){db.exec('ROLLBACK TO security_review;RELEASE security_review');throw error}return result;
 }
 async cancel(eng,id){const db=this.db(eng);if(!this.active||this.active.id!==id||this.active.eng!==eng)fail('本项目没有该运行中任务');this.active.controller.abort();await this.active.promise;return db.prepare('SELECT id,state FROM security_run WHERE id=?').get(id)}
 report(eng){
  const db=this.db(eng);db.exec('SAVEPOINT security_report_read');
  try{
   const value=this.read(eng);
   value.findings=db.prepare('SELECT * FROM security_finding ORDER BY id DESC LIMIT 20000').all().map(row=>decorateFinding(db,row));
   value.runs=db.prepare('SELECT * FROM security_run ORDER BY started_at DESC,id DESC LIMIT 20000').all().map(row=>({...row,details:JSON.parse(row.details)}));
   value.exportComplete=value.findings.length===value.totalFindings&&value.runs.length===value.totalRuns;
   value.summary=securityReportSummary(db);value.generatedAt=stamp();
   const result={...value,markdown:formatSecurityReport(value,clean)};
   db.exec('RELEASE security_report_read');return result;
  }catch(error){db.exec('ROLLBACK TO security_report_read;RELEASE security_report_read');throw error}
 }

 compare(eng,input){
  only(input,['baseRunId','currentRunId']);const baseId=requestId(input.baseRunId),currentId=requestId(input.currentRunId),db=this.db(eng);if(baseId===currentId)fail('请选择两次不同任务');
  const find=id=>db.prepare('SELECT * FROM security_run WHERE id=?').get(id),base=find(baseId),current=find(currentId);if(!base||!current)fail('本项目没有所选任务');
  const snapshot=id=>db.prepare('SELECT data FROM security_run_snapshot WHERE run_id=?').get(id)?.data;
  return{ok:true,engagement:eng,baseRunId:baseId,currentRunId:currentId,...compareScanSnapshots(base,current,snapshot(baseId),snapshot(currentId))};
 }
 async dispose(){if(this.disposed)return;const active=this.active;if(active)this.db(active.eng).prepare("UPDATE security_run SET state='interrupted',finished_at=?,error_code='服务关闭，结果未确认' WHERE id=?").run(stamp(),active.id);this.disposed=true;if(active){active.controller.abort();await active.promise}}
}

const benches=new WeakMap();
export function securityFor(store){let value=benches.get(store);if(!value){value=new SecurityWorkbench(store);benches.set(store,value)}return value}
export function disposeSecurity(store){return benches.get(store)?.dispose()}
export async function handleSecurityOp(store,request,{model=false}={}){
 if(!['securityStatus','securityScopeSave','securityStart','securityCancel','securityReview','securityReport','securityCompare','securityWait','securityPreflight','securitySource','securityKaliCheck'].includes(request?.op))return undefined;
 if(process.platform!=='linux'||homedir()!=='/home/purge'||process.env.DSH_HOME!=='/home/purge/.dsh-improved')return{ok:false,error:'安全审计仅在专用VM改进版可用'};
 if(store.root!=='/home/purge/.dsh-improved/redteam')return{ok:false,error:'安全审计后台目录未确认'};
 try{return await requestSecurityService(request,{model})}catch(error){return{ok:false,error:clean(error.message,300),...(error.diagnostic?{diagnostic:error.diagnostic}:{})}}
}
export async function executeSecurityOp(store,request,{model=false}={}){
 if(!['securityStatus','securityScopeSave','securityStart','securityCancel','securityReview','securityReport','securityCompare','securityWait','securityPreflight','securitySource','securityKaliCheck'].includes(request?.op))return undefined;
 try{
 const {op,engagement,...input}=request,bench=securityFor(store);
 if(model){if(['securityScopeSave','securityReview'].includes(op))return{ok:false,error:'请在安全审计页明确确认范围或验证结论'};return await modelSecurityResult(bench,engagement,{op,...input})}
 if(op==='securityPreflight')return bench.preflight(engagement,input);
 if(op==='securitySource')return bench.source(engagement,input);
 if(op==='securityKaliCheck')return await bench.kaliCheck(engagement,input);
 if(op==='securityWait')return bench.wait(engagement,input);
 if(op==='securityStatus'){only(input,['refreshRuntime','pages']);if(input.refreshRuntime!==undefined&&typeof input.refreshRuntime!=='boolean')fail('资源核对参数无效');if(Object.hasOwn(input,'pages')&&input.pages===null)fail('审计分页参数无效');return bench.read(engagement,{force:input.refreshRuntime===true},input.pages??null)}if(op==='securityReport')return{ok:true,...bench.report(engagement)};
 if(model&&['securityScopeSave','securityReview'].includes(op))return{ok:false,error:'请在安全审计页明确确认范围或验证结论'};
 if(op==='securityCompare')return bench.compare(engagement,input);
 if(op==='securityScopeSave')return{ok:true,profile:bench.saveScope(engagement,input)};
 if(op==='securityStart')return{ok:true,run:bench.start(engagement,input)};
 if(op==='securityCancel'){only(input,['id']);return{ok:true,run:await bench.cancel(engagement,input.id)}}
 return{ok:true,finding:bench.review(engagement,input)};
 }catch(error){return{ok:false,error:clean(error?.message||'安全审计操作已拒绝',300)}}
}
