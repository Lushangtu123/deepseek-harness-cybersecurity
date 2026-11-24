import {deepSemgrepProfile,validDeepSemgrepProfile} from './personal-semgrep-profile.mjs';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {constants,openSync,closeSync,readSync,writeFileSync,unlinkSync,linkSync,mkdirSync,rmdirSync,lstatSync,fstatSync,realpathSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {execFileSync} from 'node:child_process';

export const SECURITY_RUNTIME_ROOT='/home/purge/tools/security-workbench';
const TOOLS=['semgrep','trivy','zap'];
const HASH=/^[a-f0-9]{64}$/;
const IMAGE=/^sha256:[a-f0-9]{64}$/;
const RULE_ID=/^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$/;
const VERSION=/^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/;

function ordinary(root,name,maxBytes){
 const file=join(root,name);
 if(realpathSync(root)!==root||realpathSync(file)!==file)throw Error('unsafe runtime path');
 const info=lstatSync(file);
 if(!info.isFile()||info.isSymbolicLink()||info.size<1||info.size>maxBytes)throw Error('invalid runtime file');
 return{file,info};
}
function small(root,name,maxBytes){
 const {file}=ordinary(root,name,maxBytes),fd=openSync(file,constants.O_RDONLY|constants.O_NOFOLLOW);
 try{
  if(fstatSync(fd).size>maxBytes)throw Error('runtime file changed');
  const raw=Buffer.alloc(maxBytes+1);let used=0;
  while(used<raw.length){const count=readSync(fd,raw,used,raw.length-used,null);if(count===0)break;used+=count}
  if(used>maxBytes)throw Error('runtime file changed');
  return raw.subarray(0,used);
 }finally{closeSync(fd)}
}
function verifiedRules(root,expected){
 const raw=small(root,'rules.json',1024*1024);
 if(createHash('sha256').update(raw).digest('hex')!==expected)throw Error('rules changed');
 return raw;
}

const DEEP_RULES_ROOT=dirname(fileURLToPath(new URL('../../scripts/semgrep-deep17.json',import.meta.url)));
export function readDeepSemgrepBundle(bundleRoot=DEEP_RULES_ROOT){
 const raw=small(bundleRoot,'semgrep-deep17.json',1024*1024),profile=deepSemgrepProfile();
 if(createHash('sha256').update(raw).digest('hex')!==profile.rulesSha256)throw Error('deep rules changed');
 const rules=JSON.parse(raw).rules;
 if(!Array.isArray(rules)||rules.length!==profile.ruleCount||new Set(rules.map(r=>r?.id)).size!==rules.length||rules.some(r=>!r||typeof r.id!=='string'||!RULE_ID.test(r.id)||!Array.isArray(r.languages)||!r.languages.length||r.languages.some(l=>!['python','javascript','typescript'].includes(l))))throw Error('invalid deep rule bundle');
 return raw;
}
export function selectSemgrepManifest(manifest,mode,ruleProfile){
 if(mode===undefined&&ruleProfile===undefined)return manifest;
 if(mode!=='deep'||!validDeepSemgrepProfile(ruleProfile)||manifest.rulesSha256!==ruleProfile.baseRulesSha256)
  throw Object.assign(Error('深度 Semgrep 规则、模式或基线身份未确认'),{code:'SCAN_S1_IDENTITY'});
 return {...manifest,rulesSha256:ruleProfile.rulesSha256};
}
export function stageSemgrepRules(runtimeRoot,runDir,expected,ruleProfile,bundleRoot=DEEP_RULES_ROOT){
 const file=join(runDir,'semgrep-rules.json');let fd;
 try{
  let raw;
  if(ruleProfile!==undefined){
   if(!validDeepSemgrepProfile(ruleProfile)||expected!==ruleProfile.rulesSha256)throw Error('invalid deep profile');
   verifiedRules(runtimeRoot,ruleProfile.baseRulesSha256);
   raw=readDeepSemgrepBundle(bundleRoot);
  }else raw=verifiedRules(runtimeRoot,expected);
  if(realpathSync(runDir)!==runDir||(lstatSync(runDir).mode&0o077)!==0)throw Error('unsafe run directory');
  fd=openSync(file,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o400);
  try{writeFileSync(fd,raw)}finally{closeSync(fd)}
  return{file,sha256:createHash('sha256').update(raw).digest('hex'),count:JSON.parse(raw).rules.length};
 }catch{
  if(fd!==undefined)try{unlinkSync(file)}catch{}
  throw Object.assign(Error('未能固定 Semgrep 规则'),{code:'SCAN_S1_IDENTITY'});
 }
}

export function readRuntimeManifest(root=SECURITY_RUNTIME_ROOT){
 const value=JSON.parse(small(resolve(root),'images.json',128*1024));
 if(value?.schemaVersion!==1||!Array.isArray(value.tools)||value.tools.length!==3)throw Error('invalid manifest');
 if(!HASH.test(value.rulesSha256||''))throw Error('invalid rules identity');
 for(const tool of TOOLS){
  const rows=value.tools.filter(row=>row?.tool===tool),row=rows[0];
  if(rows.length!==1||!IMAGE.test(row.imageId||'')||row.imageRef!=='personal-security/'+tool+'@'+row.imageId||!VERSION.test(row.version||''))throw Error('invalid pinned image');
 }
 return value;
}
function sameTrivyMetadata(observed,expected){
 return expected&&['Version','UpdatedAt','NextUpdate'].every(key=>observed?.[key]===expected[key]);
}

function unlinkIfPresent(file){
 try{unlinkSync(file)}catch(error){if(error.code!=='ENOENT')throw error}
}

function clearTrivyStage(dir){
 try{lstatSync(dir)}catch(error){if(error.code==='ENOENT')return;throw error}
 if(realpathSync(dir)!==dir||!lstatSync(dir).isDirectory())throw Error('unsafe database staging path');
 unlinkIfPresent(join(dir,'metadata.json'));
 unlinkIfPresent(join(dir,'trivy.db'));
 rmdirSync(dir);
}

export function clearStaticScanInputs(runDir){
 try{lstatSync(runDir)}catch(error){if(error.code==='ENOENT')return;throw error}
 if(realpathSync(runDir)!==runDir||!lstatSync(runDir).isDirectory())throw Error('unsafe run directory');
 unlinkIfPresent(join(runDir,'semgrep-rules.json'));
 clearTrivyStage(join(runDir,'trivy-db'));
}

export function stageTrivyDatabase(runtimeRoot,runDir,expected){
 const dir=join(runDir,'trivy-db');let created=false;
 try{
  if(realpathSync(runDir)!==runDir||(lstatSync(runDir).mode&0o077)!==0)throw Error('unsafe run directory');
  const {file}=ordinary(runtimeRoot,'cache/db/trivy.db',2*1024**3);
  const metadata=small(runtimeRoot,'cache/db/metadata.json',16384);
  if(!sameTrivyMetadata(JSON.parse(metadata),expected?.metadata))throw Error('database metadata changed');
  mkdirSync(dir,{mode:0o700});created=true;
  linkSync(file,join(dir,'trivy.db'));
  hashDatabase(dir,expected,'trivy.db',true);
  writeFileSync(join(dir,'metadata.json'),metadata,{flag:'wx',mode:0o400});
  return dir;
 }catch{
  if(created)try{clearTrivyStage(dir)}catch{}
  throw Object.assign(Error('未能固定 Trivy 数据库'),{code:'SCAN_S1_IDENTITY'});
 }
}

function hashDatabase(root,expected,name='cache/db/trivy.db',requireReadOnly=false){
 if(!HASH.test(expected?.fileSha256||'')||!Number.isSafeInteger(expected.fileBytes)||expected.fileBytes<4096||expected.fileBytes>2*1024**3)throw Error('数据库完整性摘要未登记');
 const {file,info}=ordinary(root,name,2*1024**3);
 if(info.size!==expected.fileBytes)throw Error('漏洞数据库大小不匹配');
 const fd=openSync(file,constants.O_RDONLY|constants.O_NOFOLLOW),hash=createHash('sha256'),buffer=Buffer.alloc(512*1024),deadline=performance.now()+8000;
 try{
  const before=fstatSync(fd);if(requireReadOnly&&(before.mode&0o222)!==0)throw Error('数据库不是只读文件');let bytes=0,count;
  while((count=readSync(fd,buffer,0,buffer.length,null))>0){bytes+=count;hash.update(buffer.subarray(0,count));if(performance.now()>deadline||bytes>expected.fileBytes)throw Error('漏洞数据库校验未完成')}
  const after=fstatSync(fd);
  if(bytes!==expected.fileBytes||after.size!==before.size||after.mtimeMs!==before.mtimeMs||after.ctimeMs!==before.ctimeMs||hash.digest('hex')!==expected.fileSha256)throw Error('漏洞数据库摘要不匹配');
 }finally{closeSync(fd)}
}
export function inspectLocalImages(refs){
 const args=['-n','/usr/bin/docker','image','inspect','--format','{{.Id}} {{.Architecture}} {{.Os}}',...refs];let output;
 try{output=execFileSync('/usr/bin/sudo',args,{encoding:'utf8',timeout:2500,maxBuffer:64*1024,stdio:['ignore','pipe','pipe']})}
 catch(error){if(error.status!==1||!error.stdout)return{available:false,images:[]};output=String(error.stdout)}
 const images=output.trim().split('\n').filter(Boolean).map(line=>{const [id,architecture,os,...extra]=line.trim().split(/\s+/);if(!IMAGE.test(id)||extra.length)throw Error('invalid Docker reply');return{id,architecture,os}});
 return{available:true,images};
}
function scanDocker(args){
 return execFileSync('/usr/bin/sudo',['-n','/usr/bin/docker',...args],
  {encoding:'utf8',timeout:8000,killSignal:'SIGKILL',maxBuffer:65536,stdio:['ignore','pipe','pipe']});
}

export function reconcileScanContainers(docker=scanDocker){
 const list=['ps','--all','--no-trunc','--filter','label=personal.harness.security=true','--format','{{.ID}} {{.Names}}'];
 const observed=docker(list).trim().split('\n').filter(Boolean);
 const ids=observed.map(line=>{
  const match=/^([a-f0-9]{64}) dsh-sec-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.exec(line);
  if(!match)throw Error('扫描容器归属未确认，入口未启动');
  return match[1];
 });
 for(const id of ids)try{docker(['rm','--force',id])}catch{/* Auto-remove may already be in progress. */}
 if(docker(list).trim())throw Error('扫描容器清理未确认，入口未启动');
}

export function staticScannerIdentity(manifest,tool){
 const pin=manifest?.tools?.find(row=>row.tool===tool);
 if(!pin||!['semgrep','trivy'].includes(tool))return null;
 const resources=tool==='semgrep'?manifest.rulesSha256:manifest.database;
 return createHash('sha256').update(JSON.stringify([tool,pin.imageId,pin.version,resources])).digest('hex');
}

function inspectStaticSandbox(){
 const format='[{{json .SecurityOptions}},{{json .CgroupVersion}},{{json .MemoryLimit}},{{json .SwapLimit}},{{json .CPUCfsQuota}},{{json .PidsLimit}}]';
 const output=execFileSync('/usr/bin/sudo',['-n','/usr/bin/docker','info','--format',format],
  {encoding:'utf8',timeout:2500,maxBuffer:16384,stdio:['ignore','pipe','pipe']});
 const [security,cgroup,memory,swap,cpu,pids]=JSON.parse(output);
 return{security,cgroup,memory,swap,cpu,pids};
}

export function assertStaticAdmission(tool,manifest,acceptedIdentity,fresh,inspect=inspectStaticSandbox){
 const identity=staticScannerIdentity(manifest,tool);
 if(!identity||!fresh?.ready||identity!==acceptedIdentity||identity!==fresh.admissionIdentity)
  throw Object.assign(Error('静态扫描器或资源身份未确认'),{code:'SCAN_S1_IDENTITY'});
 let controls;try{controls=inspect()}catch{}
 if(controls?.cgroup!=='2'||!Array.isArray(controls.security)||!controls.security.includes('name=seccomp,profile=builtin')||
  !['memory','swap','cpu','pids'].every(key=>controls[key]===true))
  throw Object.assign(Error('S1 隔离条件未确认'),{code:'SCAN_S1_UNAVAILABLE'});
}

function identity(root,ruleBundleRoot){
 return ['images.json','rules.json','cache/db/trivy.db','cache/db/metadata.json','last-db-update.json'].map(name=>{
  try{const {info}=ordinary(root,name,2*1024**3);return[name,info.ino,info.size,info.mtimeMs,info.ctimeMs]}
  catch{return[name,'unavailable']}
 }).concat([(()=>{try{const {info}=ordinary(ruleBundleRoot,'semgrep-deep17.json',1024*1024);return['deep-bundle',info.ino,info.size,info.mtimeMs,info.ctimeMs]}catch{return['deep-bundle','unavailable']}})()]).map(row=>row.join(':')).join('|');
}
function timestamp(value){
 if(typeof value!=='string')return NaN;
 const parts=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/.exec(value);
 if(!parts)return NaN;
 const [,year,month,day,hour,minute,second,zone]=parts,n=Number;
 const calendar=new Date(0);calendar.setUTCFullYear(n(year),n(month),0);
 if(n(month)<1||n(month)>12||n(day)<1||n(day)>calendar.getUTCDate()||n(hour)>23||n(minute)>59||n(second)>59||(zone!=='Z'&&(n(zone.slice(1,3))>23||n(zone.slice(4))>59)))return NaN;
 return Date.parse(value);
}
export function createRuntimeInspector({root=SECURITY_RUNTIME_ROOT,ruleBundleRoot=DEEP_RULES_ROOT,now=Date.now,inspectImages=inspectLocalImages}={}){
 root=resolve(root);let last;
 return{read({force=false,maintenanceValidation=false}={}){
  // Read this before the cache: an interrupted update must never inherit ready evidence.
  let maintenance=false;
  try{lstatSync(join(root,'maintenance.json'));maintenance=true}catch(error){maintenance=error.code!=='ENOENT'}
  if(maintenance&&!maintenanceValidation){const checkedAt=new Date(now()).toISOString();return Object.fromEntries(TOOLS.map(tool=>[tool,{ready:false,version:null,reason:'漏洞库维护尚未完成，请从Mac启动器检查或恢复',warning:null,checkedAt,cached:false}]))}
  const at=now(),key=identity(root,ruleBundleRoot);
  if(!force&&last&&last.key===key&&at>=last.at&&at-last.at<30000)return Object.fromEntries(TOOLS.map(tool=>[tool,{...last.value[tool],cached:true}]));
  const checkedAt=new Date(at).toISOString(),value=Object.fromEntries(TOOLS.map(tool=>[tool,{ready:false,version:null,reason:'运行清单缺失、结构无效或路径不安全',warning:null,checkedAt,cached:false}]));
  let manifest;
  try{manifest=readRuntimeManifest(root)}catch{return value}
  let observed;
  try{observed=inspectImages(manifest.tools.map(row=>row.imageId));if(!observed||!Array.isArray(observed.images))throw Error('invalid inspector reply')}
  catch{observed={available:false,images:[]}}
  for(const tool of TOOLS){
   const pin=manifest.tools.find(row=>row.tool===tool),image=observed.images.find(row=>row.id===pin.imageId),entry=value[tool];entry.version=pin.version;
   entry.ready=observed.available===true&&image?.architecture==='arm64'&&image.os==='linux';
   entry.reason=entry.ready?null:observed.available?'本地镜像未找到、架构或摘要不匹配':'Docker状态未确认，未验证本地镜像';
  }
  try{
   const raw=verifiedRules(root,manifest.rulesSha256);
   const rules=JSON.parse(raw).rules,ids=new Set(),languages=new Set();
   if(!Array.isArray(rules)||rules.length<1||rules.length>1000)throw Error('invalid rule list');
   for(const rule of rules){if(!rule||typeof rule.id!=='string'||!RULE_ID.test(rule.id)||ids.has(rule.id)||!Array.isArray(rule.languages)||!rule.languages.length||rule.languages.some(language=>!['python','javascript','typescript'].includes(language)))throw Error('invalid rule identity');ids.add(rule.id);rule.languages.forEach(language=>languages.add(language))}
   value.semgrep.rules={sha256:manifest.rulesSha256,version:typeof manifest.rulesVersion==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(manifest.rulesVersion)?manifest.rulesVersion:'未登记',count:rules.length,languages:[...languages].sort()};
  }
  catch{value.semgrep.ready=false;value.semgrep.reason='本地规则缺失、不安全或摘要不匹配'}
  value.semgrep.deepRules={ready:false,reason:'深度规则包或基线尚未核对'};
  if(value.semgrep.ready&&manifest.rulesSha256===deepSemgrepProfile().baseRulesSha256)try{readDeepSemgrepBundle(ruleBundleRoot);value.semgrep.deepRules={ready:true,profile:deepSemgrepProfile()}}catch{}
  const trivy=value.trivy;trivy.database={state:'unknown',updatedAt:null,nextUpdate:null,ageDays:null};
  try{const update=JSON.parse(small(root,'last-db-update.json',16384));if(['current','updated','rolled-back'].includes(update.state)&&Number.isFinite(timestamp(update.checkedAt)))trivy.lastUpdate={state:update.state,checkedAt:update.checkedAt}}catch{}
  try{
   const metadata=JSON.parse(small(root,'cache/db/metadata.json',16384)),expected=manifest.database?.metadata,updated=timestamp(metadata.UpdatedAt),next=timestamp(metadata.NextUpdate);
   if(metadata.Version!==2||!Number.isFinite(updated)||!Number.isFinite(next)||next<=updated||updated>at+300000||!expected||['Version','UpdatedAt','NextUpdate'].some(key=>expected[key]!==metadata[key]))throw Error('漏洞库元数据无效、不一致或时间超前');
   const ageDays=Math.floor(Math.max(0,at-updated)/86400000),state=at-updated>7*86400000?'stale':'fresh';
   trivy.database={state,updatedAt:new Date(updated).toISOString(),nextUpdate:new Date(next).toISOString(),ageDays};
   hashDatabase(root,manifest.database);
   if(state==='stale')trivy.warning='漏洞库已超过7天，结果不包含之后的漏洞信息；建议更新';
  }catch(error){trivy.ready=false;trivy.reason=/^(?:漏洞|数据库)/.test(error.message)?error.message:'漏洞数据库缺失、路径不安全或未能完成校验';trivy.database.state='unknown'}
  for(const tool of ['semgrep','trivy'])if(value[tool].ready)value[tool].admissionIdentity=staticScannerIdentity(manifest,tool);
  last={at,key,value};return value;
 }};
}
