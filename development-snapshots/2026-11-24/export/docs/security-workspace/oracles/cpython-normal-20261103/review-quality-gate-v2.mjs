// Offline candidate measurement. This module cannot authorize scans or promote R3.
import {createHash} from 'node:crypto';
import {openSync,readSync,closeSync,fstatSync,constants} from 'node:fs';
import {pathToFileURL} from 'node:url';

const hashPattern=/^[a-f0-9]{64}$/;
const record=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const invalid=()=>{throw Error('Invalid layered review evaluation input')};
function requireValue(condition){if(!condition)invalid()}
function canonical(value){
 if(Array.isArray(value))return value.map(canonical);
 if(record(value))return Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])]));
 return value;
}
export const digest=value=>createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
const rate=(numerator,denominator)=>denominator?numerator/denominator:null;
const timestamp=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
const identityValid=value=>record(value)&&Object.keys(value).sort().join(',')==='reviewer,rules,scanner'&&
 Object.values(value).every(value=>typeof value==='string'&&hashPattern.test(value));
const categoryOf=row=>row.language+'/'+row.cwe;
const rateKeys=['minimumRawRecall','maximumReviewedFalsePositiveRate','maximumFalseExclusionRate','maximumUnknownRate','minimumConfirmedRecall'];
function validatePolicy(policy){
 requireValue(policy?.version===2&&policy.role==='candidate-evaluation'&&record(policy.categories));
 requireValue(Object.keys(policy.categories).length>0&&Object.keys(policy.categories).length<=50);
 for(const [category,limits] of Object.entries(policy.categories)){
  requireValue(/^(python|php|javascript|typescript|java|cpp)\/CWE-[1-9][0-9]{0,5}$/.test(category));
  requireValue(record(limits)&&Object.keys(limits).length===7);
  for(const key of ['minimumPositive','minimumNegative'])requireValue(Number.isSafeInteger(limits[key])&&limits[key]>=1&&limits[key]<=1000);
  for(const key of rateKeys)requireValue(typeof limits[key]==='number'&&Number.isFinite(limits[key])&&limits[key]>=0&&limits[key]<=1);
 }
}
function validateDataset(dataset){
 requireValue(dataset?.version===2&&Array.isArray(dataset.cases)&&dataset.cases.length>0&&dataset.cases.length<=1000);
 const ids=new Set(),locations=new Set();
 for(const row of dataset.cases){
  requireValue(record(row)&&typeof row.id==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(row.id)&&!ids.has(row.id));
  ids.add(row.id);
  requireValue(['python','php','javascript','typescript','java','cpp'].includes(row.language)&&/^CWE-[1-9][0-9]{0,5}$/.test(row.cwe));
  requireValue(['positive','negative'].includes(row.truth)&&hashPattern.test(row.sourceSha256??''));
  requireValue(record(row.location)&&['line','column'].every(key=>Number.isSafeInteger(row.location[key])&&row.location[key]>=1&&row.location[key]<=1000000));
  const location=[row.sourceSha256,row.language,row.cwe,row.location.line].join(':');
  requireValue(!locations.has(location));locations.add(location);
  requireValue(record(row.oracle)&&typeof row.oracle.reference==='string'&&row.oracle.reference.length>0&&row.oracle.reference.length<=1200);
 }
}
function validDecisionEvidence(row,output){
 return Array.isArray(output.evidence)&&output.evidence.length>0&&output.evidence.length<=20&&output.evidence.every(item=>
  record(item)&&['human-review','sandbox-verification'].includes(item.kind)&&
  item.caseId===row.id&&item.decision===output.decision&&item.inputSha256===row.sourceSha256&&hashPattern.test(item.artifactSha256??''));
}
function countsFor(rows){
 const raw={positiveHit:0,positiveMiss:0,negativeHit:0,negativeNoHit:0,unknown:0};
 const reviewed={truePositive:0,falsePositive:0,trueNegative:0,falseNegative:0,falseExclusion:0,unknown:0,unknownPositive:0,unknownNegative:0};
 let positive=0,negative=0,evidenceOnly=0;
 for(const {row,output,decision} of rows){
  const isPositive=row.truth==='positive';
  if(isPositive)positive++;else negative++;
  if(output.raw==='unknown')raw.unknown++;
  else if(isPositive)raw[output.raw==='hit'?'positiveHit':'positiveMiss']++;
  else raw[output.raw==='hit'?'negativeHit':'negativeNoHit']++;
  if(output.raw==='unknown'||output.raw==='hit'&&decision==='unknown'){
   reviewed.unknown++;reviewed[isPositive?'unknownPositive':'unknownNegative']++;
  }
  else if(output.raw==='no-hit')reviewed[isPositive?'falseNegative':'trueNegative']++;
  else if(decision==='confirmed')reviewed[isPositive?'truePositive':'falsePositive']++;
  else{
   reviewed[isPositive?'falseNegative':'trueNegative']++;
   if(isPositive)reviewed.falseExclusion++;
  }
  if(decision==='unknown'&&output.evidence?.length)evidenceOnly++;
 }
 const total=rows.length;
 return{
  total,positive,negative,evidenceOnly,
  raw:{...raw,falsePositiveRate:rate(raw.negativeHit,raw.negativeHit+raw.negativeNoHit),
   recall:rate(raw.positiveHit,positive),unknownRate:rate(raw.unknown,total)},
  reviewed:{...reviewed,falsePositiveRate:rate(reviewed.falsePositive,reviewed.falsePositive+reviewed.trueNegative),
   falsePositiveRateUpperBound:rate(reviewed.falsePositive+reviewed.unknownNegative,negative),
   falseNegativeRate:rate(reviewed.falseNegative,reviewed.truePositive+reviewed.falseNegative),
   falseExclusionRate:rate(reviewed.falseExclusion,positive),confirmedRecall:rate(reviewed.truePositive,positive),
   unknownRate:rate(reviewed.unknown,total),resolvedCases:total-reviewed.unknown},
 };
}

function validateLedger(ledger){
 requireValue(ledger?.version===1&&Array.isArray(ledger.sources)&&ledger.sources.length<=20000);
 requireValue(ledger.sources.every(row=>record(row)&&typeof row.sha256==='string'&&hashPattern.test(row.sha256)));
 return [...new Set(ledger.sources.map(row=>row.sha256))].sort();
}
const usageRequired=dataset=>({datasetSha256:digest(dataset),sourceSha256:[...new Set(dataset.cases.map(row=>row.sourceSha256))].sort(),
 action:'Record every acceptance attempt, including failure, in the usage ledger before any further freeze; this offline tool does not write the ledger'});

export function freezeReviewInputs(dataset,policy,identity,ledger){
 validateDataset(dataset);
 validatePolicy(policy);
 requireValue(identityValid(identity));
 const used=validateLedger(ledger);
 const usedSet=new Set(used);
 if(dataset.cases.some(row=>usedSet.has(row.sourceSha256)))throw Error('Acceptance source already used in the sample ledger');
 return{version:2,createdAt:new Date().toISOString(),datasetSha256:digest(dataset),policySha256:digest(policy),ledgerSha256:digest(ledger),
  identity:{...identity},developmentSourceSha256:used,usageRequired:usageRequired(dataset)};
}

export function evaluateReviewQuality(dataset,run,freeze,policy,ledger){
 validateDataset(dataset);
 validatePolicy(policy);
 const used=validateLedger(ledger);
 requireValue(run?.version===2&&identityValid(run.identity)&&timestamp(run.startedAt)&&hashPattern.test(run.datasetSha256??'')&&hashPattern.test(run.freezeSha256??''));
 requireValue(freeze?.version===2&&identityValid(freeze.identity)&&timestamp(freeze.createdAt));
 requireValue(Array.isArray(freeze.developmentSourceSha256)&&freeze.developmentSourceSha256.length<=20000&&
  freeze.developmentSourceSha256.every(value=>typeof value==='string'&&hashPattern.test(value)));
 requireValue(Array.isArray(run.outputs)&&run.outputs.length<=dataset.cases.length);
 const blockers=new Set(),overlap=[],records=new Map(),caseBlockers=[],artifactCases=new Map(),decisionBindings=new Map();
 const ids=new Set(dataset.cases.map(row=>row.id));
 for(const output of run.outputs){
  requireValue(record(output)&&ids.has(output.id)&&!records.has(output.id)&&['hit','no-hit','unknown'].includes(output.raw)&&
   ['confirmed','excluded','unknown','not-required'].includes(output.decision));
  requireValue(output.raw==='hit'?output.decision!=='not-required':output.raw==='no-hit'?output.decision==='not-required':output.decision==='unknown');
  requireValue(Array.isArray(output.evidence)&&output.evidence.length<=20&&output.evidence.every(item=>record(item)&&typeof item.kind==='string'&&item.kind.length>0&&item.kind.length<=80));
  for(const item of output.evidence)if(hashPattern.test(item.artifactSha256??'')){
   const cases=artifactCases.get(item.artifactSha256)??new Set();cases.add(output.id);artifactCases.set(item.artifactSha256,cases);
  }
  records.set(output.id,output);
 }
 for(const row of dataset.cases){
  const output=records.get(row.id);
  if(!output||!['confirmed','excluded'].includes(output.decision)||!validDecisionEvidence(row,output))continue;
  for(const item of output.evidence){
   const bindings=decisionBindings.get(item.artifactSha256)??new Set();
   bindings.add(row.sourceSha256+':'+output.decision);decisionBindings.set(item.artifactSha256,bindings);
  }
 }
 const conflicts=new Set([...decisionBindings].filter(([,bindings])=>bindings.size>1).map(([hash])=>hash));
 if(freeze.datasetSha256!==digest(dataset))blockers.add('dataset-changed-after-freeze');
 if(freeze.policySha256!==digest(policy))blockers.add('thresholds-changed-after-freeze');
 if(digest(freeze.identity)!==digest(run.identity))blockers.add('candidate-identity-changed');
 if(run.datasetSha256!==digest(dataset))blockers.add('run-dataset-mismatch');
 if(run.freezeSha256!==digest(freeze))blockers.add('run-freeze-mismatch');
 if(freeze.ledgerSha256!==digest(ledger)||digest([...new Set(freeze.developmentSourceSha256)].sort())!==digest(used))blockers.add('ledger-history-mismatch');
 if(Date.parse(freeze.createdAt)>=Date.parse(run.startedAt))blockers.add('freeze-not-before-run');
 const development=new Set([...used,...freeze.developmentSourceSha256]);
 const groups=new Map();
 for(const row of dataset.cases){
  const reasons=[];
  if(development.has(row.sourceSha256)){overlap.push(row.id);blockers.add('development-sample-reused')}
  if(row.oracle.kind!=='independent-vulnerability'||row.oracle.positionVerified!==true||row.oracle.conditionsVerified!==true)
   {blockers.add('vulnerability-oracle-incomplete');reasons.push('vulnerability-oracle-incomplete')}
  let output=records.get(row.id)??{id:row.id,raw:'unknown',decision:'unknown',evidence:[]};
  if(output.raw==='hit'&&(output.location?.line!==row.location.line||output.location?.sourceSha256!==row.sourceSha256||
     output.language!==row.language||output.cwe!==row.cwe)){
   output={...output,raw:'unknown',decision:'unknown'};blockers.add('scan-location-mismatch');reasons.push('scan-location-mismatch');
  }
  let decision=output.decision;
  if(['confirmed','excluded'].includes(decision)&&output.evidence.some(item=>conflicts.has(item.artifactSha256))){
   decision='unknown';blockers.add('artifact-binding-conflict');reasons.push('artifact-binding-conflict');
  }
  if(['confirmed','excluded'].includes(decision)&&!validDecisionEvidence(row,output)){
   decision='unknown';blockers.add('unsupported-review-evidence');reasons.push('unsupported-review-evidence');
  }
  if(reasons.length)caseBlockers.push({id:row.id,reasons});
  const category=categoryOf(row),group=groups.get(category)??[];
  group.push({row,output,decision});groups.set(category,group);
 }
 const categories={};
 for(const category of new Set([...Object.keys(policy.categories),...groups.keys()])){
  const summary=countsFor(groups.get(category)??[]),limits=policy.categories[category],reasons=[];
  if(!limits)reasons.push('category-thresholds-missing');
  else{
   if(summary.positive<limits.minimumPositive||summary.negative<limits.minimumNegative)reasons.push('insufficient-labelled-cases');
   if(summary.raw.unknown>0)reasons.push('scanner-coverage-unknown');
   if(summary.raw.recall===null||summary.raw.recall<limits.minimumRawRecall)reasons.push('raw-recall-below-threshold');
   if(summary.reviewed.falsePositiveRate===null||summary.reviewed.falsePositiveRate>limits.maximumReviewedFalsePositiveRate)
    reasons.push('reviewed-false-positive-rate-unqualified');
   if(summary.reviewed.falsePositiveRateUpperBound===null||summary.reviewed.falsePositiveRateUpperBound>limits.maximumReviewedFalsePositiveRate)
    reasons.push('reviewed-false-positive-bound-unqualified');
   if(summary.reviewed.falseExclusionRate===null||summary.reviewed.falseExclusionRate>limits.maximumFalseExclusionRate)
    reasons.push('false-exclusion-rate-unqualified');
   if(summary.reviewed.unknownRate===null||summary.reviewed.unknownRate>limits.maximumUnknownRate)reasons.push('review-unknown-rate-unqualified');
   if(summary.reviewed.confirmedRecall===null||summary.reviewed.confirmedRecall<limits.minimumConfirmedRecall)
    reasons.push('confirmed-recall-below-threshold');
  }
  for(const reason of reasons)blockers.add(category+':'+reason);
  categories[category]={...summary,thresholds:limits??null,blockers:reasons};
 }
 return{version:2,state:blockers.size?'blocked':'eligible-for-release-review',r3Qualified:false,executionEnabled:false,
  categories,blockers:[...blockers],caseBlockers,developmentOverlap:overlap,usageRequired:usageRequired(dataset),freezeTrust:'self-attested; digest and attempt-consumption ledger need an independent release-review check',
  artifactReuse:[...artifactCases].filter(([,cases])=>cases.size>1).map(([sha256,cases])=>({sha256,caseIds:[...cases]})),
  definitions:{
   rawFalsePositiveRate:'negative hits / observed negative cases',
   reviewedFalsePositiveRate:'negative confirmations / resolved negative cases',
   reviewedFalsePositiveRateUpperBound:'negative confirmations plus unknown negatives / all labelled negatives',
   reviewedFalseNegativeRate:'missed or wrongly excluded positives / resolved positive cases',
   confirmedRecall:'confirmed positives / all labelled positives',
   unknownRate:'unresolved cases / all labelled cases',
   evidenceOnly:'unknown decisions carrying evidence references; not verified exclusions',
   evidenceValidation:'declared evidence kind, input binding and artifact digest structure; evidence meaning requires independent review',
  }};
}

function readInput(path){
 const limit=2*1024*1024,fd=openSync(path,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
 try{
  if(!fstatSync(fd).isFile())throw Error('Evaluation input must be an ordinary file');
  const buffer=Buffer.alloc(limit+1);
  let used=0;
  while(used<buffer.length){
   const count=readSync(fd,buffer,used,buffer.length-used,null);
   if(count===0)break;
   used+=count;
  }
  if(used>limit)throw Error('Evaluation file exceeds 2 MiB');
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(buffer.subarray(0,used)));
 }finally{closeSync(fd)}
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 try{
  if(process.argv[2]==='--freeze'){
   if(process.argv.length!==7)throw Error('Usage: review_quality_gate.mjs --freeze DATASET POLICY IDENTITY LEDGER');
   console.log(JSON.stringify(freezeReviewInputs(...process.argv.slice(3).map(readInput)),null,2));
  }else{
   if(process.argv.length!==7)throw Error('Usage: review_quality_gate.mjs DATASET RUN FREEZE POLICY LEDGER');
   const result=evaluateReviewQuality(...process.argv.slice(2).map(readInput));
   console.log(JSON.stringify(result,null,2));
   if(result.state==='blocked')process.exitCode=2;
  }
 }catch(error){console.error(error.message);process.exitCode=1}
}
