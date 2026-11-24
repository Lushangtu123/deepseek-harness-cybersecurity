import {findingView} from './personal-workspace-contract.mjs';
import {createHash} from 'node:crypto';

const VERSION='workspace-risk-p0-1';
const PRIORITIES=['immediate','soon','planned','observe'];
const SEVERITIES=['critical','high','medium','low','info','unknown'];
const CONFIDENCE=['high','medium','low','not-provided'];
const MALWARE_STRONG=['calibrated-signature','exact-malicious-package','high-confidence-rule'];
const LABELS={immediate:'立即处理',soon:'尽快处理',planned:'计划处理',observe:'观察'};
const fail=()=>{throw Error('工作区风险合同无效')};
function object(v,keys){if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).some(k=>!keys.includes(k)))fail()}
function member(v,values){if(!values.includes(v))fail();return v}
function integer(v){if(!Number.isSafeInteger(v)||v<0)fail();return v}
function optional(v,values,fallback='unknown'){return v===undefined?fallback:member(v,values)}
const rank=p=>PRIORITIES.indexOf(p);

// These functions consume backend-normalized facts, never model authority.
// Classification fidelity is tested with synthetic rules, not a detection benchmark.
export function rankWorkspaceFinding(value){
 object(value,['id','firstSeenAtMs','detection','disposition','remediation','recurrence','dispositionValid','detectionReason','category','severity','confidence','dependencyScope','reachability','exposure','kev','kevExactMatch','kevObservedAtMs','epssSignal','credentialExposure','malwareEvidence','upstreamMatch','weakHeuristic','independentEvidence','observationCount','previousPriority']);
 if(typeof value.id!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.id))fail();
 if(value.firstSeenAtMs!==undefined&&value.firstSeenAtMs!==null)integer(value.firstSeenAtMs);
 if(value.kevObservedAtMs!==undefined&&value.kevObservedAtMs!==null)integer(value.kevObservedAtMs);
 const category=member(value.category,['dependency','code','configuration','credential','malware']),severity=member(value.severity,SEVERITIES),confidence=member(value.confidence,CONFIDENCE);
 for(const key of ['weakHeuristic','independentEvidence','kevExactMatch'])if(value[key]!==undefined&&typeof value[key]!=='boolean')fail();
 if(value.observationCount!==undefined&&(!Number.isSafeInteger(value.observationCount)||value.observationCount<1))fail();
 if(value.previousPriority!==undefined&&value.previousPriority!==null)member(value.previousPriority,PRIORITIES);
 const scope=optional(value.dependencyScope,['runtime','development','unknown']),reach=optional(value.reachability,['reproduced','reachable','unreachable','unknown']);
 const exposure=optional(value.exposure,['public','internal','unknown']),kev=optional(value.kev,['listed','not-listed','unknown','not-applicable']);
 const credentials=optional(value.credentialExposure,['remote','local-commit','uncommitted','ignored','unknown']);
 const malware=optional(value.malwareEvidence,[...MALWARE_STRONG,'heuristic','unknown']),upstream=optional(value.upstreamMatch,['yes','no','unknown']);
 let epss={band:'unknown',sourceState:'unknown'};
 if(value.epssSignal!==undefined&&value.epssSignal!==null){
  object(value.epssSignal,['band','sourceState','lastObservedAtMs','lastScore','recoveryStartedAtMs','configurationIdentity']);
  member(value.epssSignal.band,['high','low','unknown']);member(value.epssSignal.sourceState,['current','stale','unknown','not-applicable','out-of-order','future']);
  epss=value.epssSignal;
 }
 const facts=structuredClone(value),view=findingView(Object.fromEntries(['detection','disposition','remediation','recurrence','dispositionValid','detectionReason'].map(key=>[key,value[key]])));
 if(!view.queued)return {queued:false,priority:null,label:'不排队',rule:null,ruleVersion:VERSION,assessmentState:'not-applicable',missingInputs:[],provisional:false,adjustments:['not-queued'],rankingInputs:null,facts};
 const missing=new Set(),adjustments=[],environmental=['dependency','code','configuration'].includes(category);
 if(confidence==='not-provided')missing.add('confidence');
 if(environmental){if(severity==='unknown')missing.add('severity');if(exposure==='unknown')missing.add('exposure');if(reach==='unknown')missing.add('reachability')}
 if(category==='dependency'){
  if(scope==='unknown')missing.add('dependency-scope');
  if(kev==='unknown')missing.add('kev');if(kev==='listed'&&value.kevExactMatch!==true)missing.add('kev-applicability');
  if(epss.sourceState!=='not-applicable'&&(epss.sourceState!=='current'||epss.band==='unknown'))missing.add('epss');
 }
 if(category==='credential'&&credentials==='unknown')missing.add('credential-exposure');
 if(category==='malware'){if(malware==='unknown')missing.add('malware-evidence');if(malware==='heuristic'&&upstream==='unknown')missing.add('upstream-match')}
 if(value.detection==='uncovered')missing.add('current-coverage');
 const rankingInputs={severity:severity==='unknown'?'high':severity,exposure:exposure==='unknown'?'public':exposure,dependencyScope:scope==='unknown'?'runtime':scope,reachability:reach,credentialExposure:credentials==='unknown'?'remote':credentials,upstreamMatch:upstream==='unknown'?'no':upstream};
 const severe=['critical','high'].includes(rankingInputs.severity),exactKev=category==='dependency'&&kev==='listed'&&value.kevExactMatch===true,strongMalware=category==='malware'&&MALWARE_STRONG.includes(malware);
 const weakOnly=value.weakHeuristic===true&&confidence==='low'&&value.observationCount===1&&value.independentEvidence!==true&&!exactKev&&!(environmental&&reach==='reproduced')&&!strongMalware;
 if(weakOnly)missing.add('independent-evidence');
 let rule,priority;
 if(category==='dependency'){
  if(exactKev&&rankingInputs.dependencyScope==='runtime'&&reach!=='unreachable'){rule='DEP-1';priority='immediate'}
  else if(reach==='reproduced'&&severe){rule='DEP-2';priority='immediate'}
  else if(exactKev||epss.band==='high'&&epss.sourceState!=='not-applicable'){rule='DEP-3';priority='soon'}
  else if(severe&&rankingInputs.dependencyScope==='runtime'&&rankingInputs.exposure==='public'&&reach!=='unreachable'){rule='DEP-4';priority='soon'}
  else if(['critical','high','medium'].includes(rankingInputs.severity)){rule='DEP-5';priority='planned'}
  else{rule='DEP-6';priority='observe'}
 }else if(['code','configuration'].includes(category)){
  if(reach==='reproduced'&&severe){rule='CODE-1';priority='immediate'}
  else if(severe&&rankingInputs.exposure==='public'&&reach!=='unreachable'){rule='CODE-2';priority='soon'}
  else if(['critical','high','medium'].includes(rankingInputs.severity)){rule='CODE-3';priority='planned'}
  else{rule='CODE-4';priority='observe'}
 }else if(category==='credential'){
  const index=['remote','local-commit','uncommitted','ignored'].indexOf(rankingInputs.credentialExposure);rule='CRED-'+(index+1);priority=PRIORITIES[index];
 }else{
  if(MALWARE_STRONG.includes(malware)){rule='MW-1';priority='immediate'}
  else if(confidence==='medium'){rule='MW-2';priority='soon'}
  else if(malware==='heuristic'&&rankingInputs.upstreamMatch==='no'){rule='MW-3';priority='planned'}
  else if(malware==='heuristic'){rule='MW-4';priority='observe'}
  else{rule='MW-UNKNOWN';priority='planned'}
 }
 if(missing.size&&rank(priority)>rank('planned')){priority='planned';adjustments.push('missing-input-floor')}
 if(missing.size&&environmental&&rankingInputs.exposure==='public'&&rank(priority)>rank('soon')){priority='soon';adjustments.push('public-unknown-input-floor')}
 if(weakOnly&&rank(priority)<rank('planned')){priority='planned';adjustments.push('single-weak-heuristic-cap')}
 if(value.detection==='uncovered'&&value.previousPriority&&rank(value.previousPriority)<rank(priority)){priority=value.previousPriority;adjustments.push('uncovered-priority-retained')}
 const provisional=missing.size>0;
 return {queued:true,priority,label:provisional&&priority==='soon'?'尽快核对 · 临时':LABELS[priority],rule,ruleVersion:VERSION,assessmentState:provisional?'pending':'sufficient',missingInputs:[...missing].sort(),provisional,adjustments,rankingInputs,facts};
}

export function compareWorkspaceRisks(a,b){
 const priority=row=>row.priority===null?4:rank(member(row.priority,PRIORITIES));
 return priority(a)-priority(b)||SEVERITIES.indexOf(a.rankingInputs?.severity??'unknown')-SEVERITIES.indexOf(b.rankingInputs?.severity??'unknown')||CONFIDENCE.indexOf(a.facts.confidence)-CONFIDENCE.indexOf(b.facts.confidence)||(a.facts.firstSeenAtMs??Infinity)-(b.facts.firstSeenAtMs??Infinity)||(a.facts.id<b.facts.id?-1:a.facts.id>b.facts.id?1:0);
}

// No product-wide EPSS thresholds are invented here. Callers must provide
// explicit, versioned/calibrated parameters; missing days never advance recovery.
export function updateEpssBand(previous,sample,config,nowMs){
 object(config,['high','low','windowMs','maxAgeMs','maxGapMs']);
 if(typeof config.high!=='number'||!Number.isFinite(config.high)||config.high<=0||config.high>1||typeof config.low!=='number'||!Number.isFinite(config.low)||config.low<0||config.low>=config.high)fail();
 for(const key of ['windowMs','maxAgeMs','maxGapMs'])if(integer(config[key])===0)fail();integer(nowMs);
 const configurationIdentity=createHash('sha256').update(JSON.stringify({ruleVersion:VERSION,parameters:Object.fromEntries(['high','low','windowMs','maxAgeMs','maxGapMs'].map(key=>[key,config[key]]))})).digest('hex');
 const prior=structuredClone(previous??{band:'unknown',sourceState:'unknown',lastObservedAtMs:null,lastScore:null,recoveryStartedAtMs:null});
 object(prior,['band','sourceState','lastObservedAtMs','lastScore','recoveryStartedAtMs','configurationIdentity']);member(prior.band,['high','low','unknown']);
 if(prior.configurationIdentity!==undefined&&!/^[a-f0-9]{64}$/.test(prior.configurationIdentity))fail();
 const sameConfiguration=prior.configurationIdentity===configurationIdentity;
 if(!sameConfiguration)prior.recoveryStartedAtMs=null;
 for(const key of ['lastObservedAtMs','recoveryStartedAtMs'])if(prior[key]!==null)integer(prior[key]);
 if(prior.lastScore!==null&&(typeof prior.lastScore!=='number'||!Number.isFinite(prior.lastScore)||prior.lastScore<0||prior.lastScore>1))fail();
 const unavailable=sourceState=>({...structuredClone(prior),sourceState,recoveryStartedAtMs:null});
 if(sample===null)return unavailable('unknown');
 object(sample,['score','observedAtMs']);integer(sample.observedAtMs);
 if(typeof sample.score!=='number'||!Number.isFinite(sample.score)||sample.score<0||sample.score>1)fail();
 if(sample.observedAtMs>nowMs)return unavailable('future');
 if(nowMs-sample.observedAtMs>config.maxAgeMs)return unavailable('stale');
 if(prior.lastObservedAtMs!==null&&sample.observedAtMs<prior.lastObservedAtMs)return {...structuredClone(prior),sourceState:'out-of-order'};
 if(sameConfiguration&&sample.observedAtMs===prior.lastObservedAtMs){if(sample.score!==prior.lastScore)fail();return {...structuredClone(prior),sourceState:'current'}}
 const next={band:prior.band,sourceState:'current',lastObservedAtMs:sample.observedAtMs,lastScore:sample.score,recoveryStartedAtMs:null,configurationIdentity};
 if(sample.score>=config.high){next.band='high';return next}
 if(prior.band!=='high'){next.band='low';return next}
 if(sample.score>config.low)return next;
 const continuous=prior.recoveryStartedAtMs!==null&&prior.lastObservedAtMs!==null&&sample.observedAtMs-prior.lastObservedAtMs<=config.maxGapMs;
 next.recoveryStartedAtMs=continuous?prior.recoveryStartedAtMs:sample.observedAtMs;
 if(sample.observedAtMs-next.recoveryStartedAtMs>=config.windowMs){next.band='low';next.recoveryStartedAtMs=null}
 return next;
}
