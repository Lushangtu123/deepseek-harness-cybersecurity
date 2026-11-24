import {createHash} from 'node:crypto';
import {workspaceModePolicy,assessWorkspaceBudget} from './personal-workspace-policy.mjs';

// P0 contracts only. No process, network, persistence or permission changes.
// A preview never authorizes execution; production admission belongs to P1.
const AXES={
 execution:{pending:'待运行',running:'运行中',ended:'步骤已结束',partial:'部分失败',failed:'失败',cancelled:'已取消',interrupted:'中断','stop-unconfirmed':'停止未确认'},
 ingestion:{recorded:'已收录',partial:'部分收录',unknown:'未知'},
 coverage:{checked:'声明范围内已核对',incomplete:'覆盖不完整',unknown:'覆盖未知','not-applicable':'不适用'},
 cleanup:{pending:'待核对',confirmed:'已确认',unconfirmed:'未确认','not-applicable':'不适用'},
};
const DETECTION=['present','not-detected','uncovered'];
const DISPOSITION=['unhandled','confirmed','false-positive','not-affected','accepted-risk'];
const REMEDIATION=['unfixed','registered-fixed','retest-passed','retest-failed'];
const HASH=/^[a-f0-9]{64}$/;
const SOURCE=/\.(?:php|py|js|mjs|cjs|jsx|ts|tsx|java|c|cc|cpp|cxx|h|hpp)$/i;
const DEPENDENCY=/(?:^|\/)(?:composer\.lock|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|requirements[^/]*\.txt|pom\.xml|gradle\.lockfile)$/;
const CONFIGURATION=/(?:^|\/)(?:\.?env(?:\.[^/]+)?|Dockerfile(?:\.[^/]+)?|Containerfile|(?:docker-)?compose\.ya?ml)$|\.(?:ya?ml|toml|ini|conf|tf|tfvars)$/i;
const fail=()=>{throw Error('安全工作区合同无效')};
function object(value,allowed){
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!allowed.includes(key)))fail();
 return value;
}
function member(value,allowed){if(!allowed.includes(value))fail();return value}

export function describeTaskDimensions(value){
 object(value,Object.keys(AXES));
 return Object.fromEntries(Object.entries(AXES).map(([axis,labels])=>[axis,labels[member(value[axis],Object.keys(labels))]]));
}

export function findingView(value){
 object(value,['detection','disposition','remediation','recurrence','dispositionValid','detectionReason']);
 const detection=member(value.detection,DETECTION),original=member(value.disposition,DISPOSITION),remediation=member(value.remediation,REMEDIATION);
 if(typeof value.recurrence!=='boolean'||value.dispositionValid!==undefined&&typeof value.dispositionValid!=='boolean')fail();
 if(value.detectionReason!==undefined&&value.detectionReason!==null)member(value.detectionReason,['advisory-withdrawn']);
 // Validity is established by the backend against current inputs and expiry.
 const disposition=['false-positive','not-affected','accepted-risk'].includes(original)&&value.dispositionValid!==true?'unhandled':original;
 const queued=['present','uncovered'].includes(detection)&&['unhandled','confirmed'].includes(disposition)&&remediation!=='registered-fixed';
 let label;
 if(['false-positive','not-affected','accepted-risk'].includes(disposition))label={'false-positive':'误报','not-affected':'不受影响','accepted-risk':'已接受风险'}[disposition];
 else if(remediation==='retest-passed'&&detection==='not-detected')label='已修复';
 else if(value.recurrence&&detection==='present')label='再次出现';
 else if(remediation==='retest-failed')label='修复未生效';
 else if(remediation==='registered-fixed')label='修复待复查';
 else if(detection==='not-detected')label=value.detectionReason==='advisory-withdrawn'?'公告已撤回':'疑似已消失';
 else if(detection==='uncovered')label='无法判断';
 else label=disposition==='confirmed'?'已确认，待修复':'待处理';
 return {label,queued};
}

export function previewWorkspacePlan(value,inventory={}){
 object(value,['mode','scopeRevision','inputIdentity','files','banditCoverageDelta','budget']);
 member(value.mode,['ordinary','deep']);
 const policy=workspaceModePolicy(value.mode);
 if(!Number.isSafeInteger(value.scopeRevision)||value.scopeRevision<1||!HASH.test(value.inputIdentity))fail();
 if(!Array.isArray(value.files)||!value.files.length||value.files.length>20000)fail();
 for(const file of value.files){
  if(typeof file!=='string'||file.length>800||/[\\\x00-\x1f]/.test(file)||file.split('/').some(part=>!part||part==='.'||part==='..'))fail();
 }
 if(value.banditCoverageDelta!==undefined&&(!Array.isArray(value.banditCoverageDelta)||value.banditCoverageDelta.length>100||value.banditCoverageDelta.some(x=>typeof x!=='string'||!/^CWE-[1-9]\d{0,5}$/.test(x))))fail();
 if(!inventory||typeof inventory!=='object'||Array.isArray(inventory))fail();
 const files=[...new Set(value.files)].sort(),source=files.some(file=>SOURCE.test(file)),dependencies=files.some(file=>DEPENDENCY.test(file)),configuration=files.some(file=>CONFIGURATION.test(file));
 const selected=[];
 if(source)selected.push(['semgrep','按项目语言检查代码',['native-results','diagnostics','coverage-records']]);
 if(source||dependencies||configuration)selected.push(['trivy',dependencies?'检查依赖、配置与凭据痕迹':'检查配置与凭据痕迹',['native-results','component-identities','diagnostics']]);
 if(files.some(file=>file.endsWith('.py'))&&value.banditCoverageDelta?.length)selected.push(['bandit','补充已登记的 Python 检查差异：'+[...new Set(value.banditCoverageDelta)].sort().join('、'),['native-results','diagnostics','coverage-records']]);
 const requiredLevel=policy.minimumToolLevel;
 const steps=selected.map(([tool,reason,expectedEvidence])=>{
  const capability=inventory[tool];
  // Supplied metadata is a preview input, never a fresh runtime attestation.
  const sandboxReady=capability?.sandbox==='S1'&&Number.isInteger(capability.sandboxLevel)&&capability.sandboxLevel>=requiredLevel&&capability.sandboxLevel<=3;
  const imageId=/^sha256:[a-f0-9]{64}$/.test(capability?.imageId||'')?capability.imageId:null,policyIdentity=HASH.test(capability?.policyIdentity||'')?capability.policyIdentity:null;
  const toolReady=Number.isInteger(capability?.level)&&capability.level>=requiredLevel&&capability.level<=3&&imageId!==null&&policyIdentity!==null;
  return {tool,purpose:reason,reason,inputIdentity:value.inputIdentity,toolIdentity:{imageId,policyIdentity},permission:'L0',sandboxProfile:'S1',expectedEvidence,resultDestination:'workspace-observations',state:sandboxReady&&toolReady?'eligible-preview':'unavailable',unavailableReason:!sandboxReady?'sandbox_unavailable':!toolReady?'tool_not_qualified':null,coverage:'incomplete'};
 });
 let budgetAssessment={state:'unavailable',reasons:['budget-not-declared'],executionEnforced:false,currencyHardLimit:false,previewOnly:true};
 if(value.budget!==undefined){
  object(value.budget,['task','steps','nowMs','scopeExpiresAtMs']);
  if(!Array.isArray(value.budget.steps)||value.budget.steps.length!==steps.length||steps.some(step=>value.budget.steps.filter(row=>row?.id===step.tool).length!==1))fail();
  budgetAssessment=assessWorkspaceBudget({...value.budget,mode:value.mode});
 }
 const body={contractVersion:1,mode:value.mode,scopeRevision:value.scopeRevision,inputIdentity:value.inputIdentity,files,steps,gaps:steps.length?[]:['no-supported-static-input'],policy,budgetAssessment};
 const planIdentity=createHash('sha256').update(JSON.stringify(body)).digest('hex');
 return {...body,planIdentity,previewOnly:true,executable:false,limitation:'P0静态计划与候选预算预览；不启动工具。运行限额、动态工具及生产准入仍待后续阶段。'};
}
