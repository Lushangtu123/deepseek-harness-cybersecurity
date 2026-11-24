import {deepSemgrepProfile,validDeepSemgrepProfile} from './personal-semgrep-profile.mjs';
import {createHash} from 'node:crypto';

const VERSION='workspace-policy-p0-1';
const RESOURCES=['cpuMillis','memoryBytes','pids','tmpBytes','outputBytes'];
const BUDGET=['wallSeconds',...RESOURCES,'modelRequests','outputTokensPerCall'];
const fail=()=>{throw Error('工作区策略或预算合同无效')};
function object(value,keys){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!keys.includes(key)))fail()}
function integer(value,minimum=0){if(!Number.isSafeInteger(value)||value<minimum)fail();return value}
function add(a,b){return integer(a+b)}
function budget(value,task=false){
 object(value,[...BUDGET,...(task?['parallelism']:[])]);
 const normalized=Object.fromEntries([...BUDGET,...(task?['parallelism']:[])].map(key=>[key,integer(value[key],key==='memoryBytes'?16777216:['modelRequests','outputTokensPerCall'].includes(key)?0:1)]));
 if(normalized.wallSeconds>3600||normalized.pids>512||normalized.outputBytes>8388608||task&&normalized.parallelism>32)fail();
 return normalized;
}

export function workspaceModePolicy(mode){
 if(!['ordinary','deep'].includes(mode))fail();
 const ordinary=mode==='ordinary';
 return {version:VERSION,mode,planner:ordinary?'rules':'model-assisted',minimumToolLevel:ordinary?3:2,sandboxProfiles:ordinary?['S1']:['S1','S2','S3'],presetRecommendation:ordinary?'personal-review':'personal-joint',changesCurrentPreset:false,executionEnabled:false,currencyHardLimit:false,calibration:'candidate-not-benchmark-qualified',budgetCeilings:{wallSeconds:ordinary?360:900,maxSteps:ordinary?3:6,parallelism:1,modelRequests:ordinary?0:16,outputTokensPerCall:ordinary?0:2048,outputBytes:8388608}};
}

// First scheduler integration slice. R2 describes existing managed adapters,
// not benchmark qualification. No R3 promotion or S2/S3 fallback is implied.
export function workspaceDispatchPolicy(mode,runtime={}){
 const policy=workspaceModePolicy(mode),availableSteps=[],unavailableSteps=[];
 for(const tool of ['semgrep','trivy','zap','kali','rea','pentagi']){
  const reason=!['semgrep','trivy'].includes(tool)?'sandbox-qualification-missing'
   :policy.minimumToolLevel>2?'r3-qualification-missing'
   :runtime[tool]?.ready!==true?'runtime-not-ready'
   :!/^[a-f0-9]{64}$/.test(runtime[tool]?.admissionIdentity??'')?'runtime-identity-missing'
   :mode==='deep'&&tool==='semgrep'&&runtime[tool]?.rules?.sha256!==deepSemgrepProfile().baseRulesSha256?'deep-rule-base-mismatch'
   :mode==='deep'&&tool==='semgrep'&&(runtime[tool]?.deepRules?.ready!==true||!validDeepSemgrepProfile(runtime[tool]?.deepRules?.profile))?'deep-rule-bundle-unavailable':null;
  if(reason)unavailableSteps.push({tool,reason});else availableSteps.push(tool);
 }
 return{version:'workspace-dispatch-s1-2',mode,minimumToolLevel:policy.minimumToolLevel,
  sandboxProfiles:['S1'],availableSteps,unavailableSteps,maxSeconds:policy.budgetCeilings.wallSeconds,
  maxSteps:policy.budgetCeilings.maxSteps,modelRequests:0,fullWorkspaceReady:false,...(mode==='deep'&&availableSteps.includes('semgrep')?{ruleProfiles:{semgrep:deepSemgrepProfile()}}:{})};
}

export function workspaceDispatchContract(mode,steps,budgetSeconds,runtime){
 const policy=workspaceDispatchPolicy(mode,runtime);
 if(mode==='ordinary')throw Error('普通检查尚缺 R3 工具验收，不能启动；请等待验收完成，不自动切换模式或旧入口');
 if(!Array.isArray(steps)||!steps.length||steps.length>policy.maxSteps||new Set(steps).size!==steps.length||steps.some(tool=>!policy.availableSteps.includes(tool)))
  throw Error('所选步骤的 S1 适配、就绪状态或工具身份未确认；S2/S3 尚未接入，不回退到其他入口');
 if(!Number.isSafeInteger(budgetSeconds)||budgetSeconds<30||budgetSeconds>policy.maxSeconds)throw Error('检查模式的任务时限无效');
 return{version:policy.version,mode,sandboxProfile:'S1',selectedSteps:[...steps],
  toolIdentities:Object.fromEntries(steps.map(tool=>[tool,runtime[tool].admissionIdentity])),
  budgetSeconds,modelRequests:0,fullWorkspaceReady:false,...(steps.includes('semgrep')?{ruleProfiles:{semgrep:deepSemgrepProfile()}}:{})};
}

// Pure candidate validation. P1 must atomically persist reservations, account
// retries, constrain each process and revalidate clocks/scope before dispatch.
export function assessWorkspaceBudget(value){
 object(value,['mode','task','steps','nowMs','scopeExpiresAtMs']);
 const policy=workspaceModePolicy(value.mode),caps=policy.budgetCeilings,parent=budget(value.task,true);
 const nowMs=integer(value.nowMs),scopeExpiresAtMs=integer(value.scopeExpiresAtMs);
 if(!Array.isArray(value.steps)||!value.steps.length||value.steps.length>32)fail();
 const reasons=[],seen=new Set(),steps=[];let needsPrice=false;
 for(const key of ['wallSeconds','parallelism','modelRequests','outputTokensPerCall','outputBytes'])if(parent[key]>caps[key])reasons.push('task-ceiling-exceeded:'+key);
 if(parent.parallelism>caps.parallelism)reasons.push('parallelism-exceeded');
 if(value.steps.length>caps.maxSteps)reasons.push('step-count-exceeded');
 const totals={wallSeconds:0,outputBytes:0,modelRequests:0,maximumOutputTokens:0};
 for(const raw of value.steps){
  object(raw,['id','budget','priceState']);
  if(typeof raw.id!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/.test(raw.id)||!['known','unknown','not-applicable'].includes(raw.priceState))fail();
  if(seen.has(raw.id))reasons.push('duplicate-step');seen.add(raw.id);
  const child=budget(raw.budget);steps.push({id:raw.id,budget:child,priceState:raw.priceState});
  for(const key of RESOURCES)if(child[key]>parent[key])reasons.push('step-resource-exceeded:'+key);
  if(child.outputTokensPerCall>parent.outputTokensPerCall)reasons.push('step-output-token-limit');
  if(child.modelRequests>0&&child.outputTokensPerCall===0)reasons.push('model-output-limit-missing');
  for(const key of ['wallSeconds','outputBytes','modelRequests'])totals[key]=add(totals[key],child[key]);
  totals.maximumOutputTokens=add(totals.maximumOutputTokens,integer(child.modelRequests*child.outputTokensPerCall));
  if(raw.priceState==='unknown'||child.modelRequests>0&&raw.priceState!=='known'){needsPrice=true;reasons.push('price-unconfirmed:'+raw.id)}
 }
 const deadlineMs=Math.min(add(nowMs,integer(parent.wallSeconds*1000)),scopeExpiresAtMs),remainingSeconds=Math.max(0,Math.floor((deadlineMs-nowMs)/1000));
 if(scopeExpiresAtMs<=nowMs)reasons.push('scope-expired');
 if(totals.wallSeconds>remainingSeconds)reasons.push('wall-budget-exceeded');
 if(totals.outputBytes>parent.outputBytes)reasons.push('output-budget-exceeded');
 if(totals.modelRequests>parent.modelRequests)reasons.push('model-budget-exceeded');
 const unique=[...new Set(reasons)],blocked=unique.some(reason=>!reason.startsWith('price-unconfirmed:'));
 const identity=createHash('sha256').update(JSON.stringify({version:VERSION,mode:value.mode,parent,steps,nowMs,scopeExpiresAtMs})).digest('hex');
 return {state:blocked?'unavailable':needsPrice?'needs-decision':'eligible-preview',reasons:unique,identity,deadlineMs,totals,executionEnforced:false,currencyHardLimit:false,previewOnly:true,limitation:'P0候选预算检查；持久预留、运行限额和未知结果不退额度仍须P1执行器实现。'};
}
