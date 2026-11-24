// Offline candidate measurement. This module cannot authorize scans or promote R3.
import {createHash} from 'node:crypto';
import {openSync,readSync,closeSync,fstatSync,constants,readFileSync} from 'node:fs';
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
const reviewerFiles=['eval_evidence_batch.py','eval_guard_review.py','eval_import_review.py'];
function snapshotValid(value){
 return record(value)&&[1,2].includes(value.version)&&Object.keys(value).sort().join(',')===(value.version===2?'entrypoint,files,imageId,kind,launcherSha256,storageSha256,version':'entrypoint,files,imageId,kind,launcherSha256,version')&&
  (value.version!==2||typeof value.storageSha256==='string'&&hashPattern.test(value.storageSha256))&&
  value.kind==='python-evidence-reviewer'&&value.entrypoint===reviewerFiles[0]&&
  record(value.files)&&Object.keys(value.files).sort().join(',')===reviewerFiles.join(',')&&
  Object.values(value.files).every(hash=>typeof hash==='string'&&hashPattern.test(hash))&&
  typeof value.launcherSha256==='string'&&hashPattern.test(value.launcherSha256)&&
  typeof value.imageId==='string'&&/^sha256:[a-f0-9]{64}$/.test(value.imageId);
}
function executionValid(row,run,frozenSha256){
 return record(row)&&[1,2,3].includes(row.version)&&row.state==='completed'&&
   (run.version<3||row.version===3&&row.operation==='review')&&row.snapshotSha256===run.identity.reviewer&&row.datasetSha256===run.datasetSha256&&row.freezeSha256===frozenSha256&&
   ['inputSha256','reportSha256'].every(key=>typeof row[key]==='string'&&hashPattern.test(row[key]))&&
   timestamp(row.startedAt)&&timestamp(row.finishedAt)&&Date.parse(row.startedAt)>=Date.parse(run.startedAt)&&
   Date.parse(row.finishedAt)>=Date.parse(row.startedAt);
}
function executionsValid(run,frozenSha256){
 return Array.isArray(run.reviewerExecutions)&&run.reviewerExecutions.length>0&&run.reviewerExecutions.length<=1000&&
  run.reviewerExecutions.every(row=>executionValid(row,run,frozenSha256));
}
const sourceInputPattern=/^sources\/(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\/){0,12}[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\.py$/;
const sourceInputName=name=>name.endsWith('.py')&&sourceInputPattern.test(name);
function receiptInputsValid(row){
 if(![2,3].includes(row.version)||!record(row.inputFiles))return false;
 const names=Object.keys(row.inputFiles);
 return names.length>=3&&names.length<=66&&names.includes('manifest.json')&&names.includes('scan.json')&&
  names.every(name=>['manifest.json','scan.json'].includes(name)||sourceInputName(name))&&
  Object.values(row.inputFiles).every(value=>typeof value==='string'&&value.length===64&&hashPattern.test(value))&&
  row.scanSha256===row.inputFiles['scan.json']&&digest(row.inputFiles)===row.inputSha256;
}
function reviewerCoverage(dataset,run,frozenSha256){
 const receipts=Array.isArray(run.reviewerExecutions)?run.reviewerExecutions.slice(0,1000):[];
 const seen=new Set(),covered=new Set(),invalidReceiptIndices=[],duplicateReceiptIndices=[],legacyReceiptIndices=[];
 for(const [index,row] of receipts.entries()){
  if(record(row)&&(row.version===1||run.version>=3&&row.version!==3))legacyReceiptIndices.push(index);
  if(!executionValid(row,run,frozenSha256)||!receiptInputsValid(row)){invalidReceiptIndices.push(index);continue}
  if(seen.has(row.inputSha256)){duplicateReceiptIndices.push(index);continue}
  seen.add(row.inputSha256);
  for(const [name,hash] of Object.entries(row.inputFiles))if(sourceInputName(name))covered.add(hash);
 }
 return{receiptListValid:Array.isArray(run.reviewerExecutions)&&run.reviewerExecutions.length>0&&run.reviewerExecutions.length<=1000,
  requiredSourceSha256:[...new Set(dataset.cases.filter(row=>row.language==='python').map(row=>row.sourceSha256))].sort(),
  coveredSourceSha256:[...covered].sort(),coveredCaseIds:dataset.cases.filter(row=>row.language==='python'&&covered.has(row.sourceSha256)).map(row=>row.id),
  missingCaseIds:dataset.cases.filter(row=>row.language==='python'&&!covered.has(row.sourceSha256)).map(row=>row.id),
  unsupportedCaseIds:dataset.cases.filter(row=>row.language!=='python').map(row=>row.id),
  unsupportedLanguages:[...new Set(dataset.cases.filter(row=>row.language!=='python').map(row=>row.language))].sort(),
  uniqueReceiptCount:seen.size,invalidReceiptIndices,duplicateReceiptIndices,legacyReceiptIndices};
}
const categoryOf=row=>row.language+'/'+row.cwe;
const qualifyingOracle=row=>row.oracle.kind==='independent-vulnerability'&&row.oracle.positionVerified===true&&row.oracle.conditionsVerified===true;
function selectionIssue(row){
 const selection=row.selection;
 if(record(selection)&&(selection.qualificationEligible===false||selection.blind===false||
    selection.method==='curated-known-vulnerability-pair'))return 'sample-selection-ineligible';
 if(!record(selection)||typeof selection.method!=='string'||!selection.method.trim()||selection.method.length>120||
    selection.blind!==true||selection.qualificationEligible!==true||
    typeof selection.protocolSha256!=='string'||!hashPattern.test(selection.protocolSha256))return 'sample-selection-incomplete';
 return null;
}
const qualifyingSample=row=>qualifyingOracle(row)&&selectionIssue(row)===null;
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
 requireValue([2,3].includes(dataset?.version)&&Array.isArray(dataset.cases)&&dataset.cases.length>0&&dataset.cases.length<=1000);
 const ids=new Set(),locations=new Set();
 for(const row of dataset.cases){
  requireValue(record(row)&&typeof row.id==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(row.id)&&!ids.has(row.id));
  ids.add(row.id);
  requireValue(['python','php','javascript','typescript','java','cpp'].includes(row.language)&&/^CWE-[1-9][0-9]{0,5}$/.test(row.cwe));
  requireValue(['positive','negative'].includes(row.truth)&&hashPattern.test(row.sourceSha256??''));
  if(dataset.version===2||row.pointId!==null)requireValue(record(row.location)&&['line','column'].every(key=>Number.isSafeInteger(row.location[key])&&row.location[key]>=1&&row.location[key]<=1000000));
  if(dataset.version===3)requireValue(row.language==='python'&&sourceInputName('sources/'+row.path)&&(row.pointId===null?row.truth==='negative'&&row.location===null:hashPattern.test(row.pointId??'')));
  const location=dataset.version===3?(row.pointId??'file:'+row.sourceSha256):[row.sourceSha256,row.language,row.cwe,row.location.line].join(':');
  requireValue(!locations.has(location));locations.add(location);
  requireValue(record(row.oracle)&&typeof row.oracle.reference==='string'&&row.oracle.reference.length>0&&row.oracle.reference.length<=1200);
 }
}
function validDecisionEvidence(row,output){
 return Array.isArray(output.evidence)&&output.evidence.length>0&&output.evidence.length<=20&&output.evidence.every(item=>
  record(item)&&['human-review','sandbox-verification'].includes(item.kind)&&
  (row.pointId===undefined||item.pointId===row.pointId)&&item.caseId===row.id&&item.decision===output.decision&&item.inputSha256===row.sourceSha256&&hashPattern.test(item.artifactSha256??''));
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

export function freezeReviewInputs(dataset,policy,identity,ledger,reviewerSnapshot,locationExecutions,verificationPlan){
 validateDataset(dataset);
 validatePolicy(policy);
 requireValue(identityValid(identity));
 if(reviewerSnapshot!==undefined)requireValue(snapshotValid(reviewerSnapshot)&&reviewerSnapshot.version===2&&digest(reviewerSnapshot)===identity.reviewer);
 const locations=dataset.version===3?freezeLocations(dataset,identity,reviewerSnapshot,locationExecutions):undefined;
 if(verificationPlan!==undefined)requireValue(dataset.version===3&&validVerificationPlan(verificationPlan,dataset,reviewerSnapshot));
 const used=validateLedger(ledger);
 const usedSet=new Set(used);
 if(dataset.cases.some(row=>usedSet.has(row.sourceSha256)))throw Error('Acceptance source already used in the sample ledger');
 return{version:verificationPlan===undefined?dataset.version:4,...(verificationPlan===undefined?{}:{verificationPlan:structuredClone(verificationPlan),verificationPlanSha256:digest(verificationPlan)}), ...(locations?{locations,locationsSha256:digest(locations)}:{}),createdAt:new Date().toISOString(),datasetSha256:digest(dataset),policySha256:digest(policy),ledgerSha256:digest(ledger),
  identity:{...identity},...(reviewerSnapshot===undefined?{}:{reviewerSnapshot:structuredClone(reviewerSnapshot)}),
  developmentSourceSha256:used,usageRequired:usageRequired(dataset)};
}

export function evaluateReviewQuality(dataset,run,freeze,policy,ledger){
 validateDataset(dataset);
 validatePolicy(policy);
 const used=validateLedger(ledger);
 requireValue([2,3,4].includes(run?.version)&&identityValid(run.identity)&&timestamp(run.startedAt)&&hashPattern.test(run.datasetSha256??'')&&hashPattern.test(run.freezeSha256??''));
 requireValue([2,3,4].includes(freeze?.version)&&identityValid(freeze.identity)&&timestamp(freeze.createdAt));
 requireValue(Array.isArray(freeze.developmentSourceSha256)&&freeze.developmentSourceSha256.length<=20000&&
  freeze.developmentSourceSha256.every(value=>typeof value==='string'&&hashPattern.test(value)));
 requireValue(Array.isArray(run.outputs)&&run.outputs.length<=dataset.cases.length);
 const blockers=new Set(),overlap=[],records=new Map(),caseBlockers=[],artifactCases=new Map(),decisionBindings=new Map();
 const precise=dataset.version===3;
 if(run.version!==freeze.version||(dataset.version!==3&&run.version!==2)||(dataset.version===3&&run.version<3))blockers.add('location-schema-mismatch');
 const actual=precise?preciseArtifacts(dataset,run,freeze):null;
 if(actual)for(const issue of actual.issues)blockers.add(issue);
 const verified=run.version===4?verificationArtifacts(dataset,run,freeze):null;
 if(verified)for(const issue of verified.issues)blockers.add(issue);
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
 if(!snapshotValid(freeze.reviewerSnapshot))blockers.add('reviewer-snapshot-missing-or-invalid');
 else {
  if(freeze.reviewerSnapshot.version===1)blockers.add('reviewer-snapshot-legacy-storage-unbound');
  if(digest(freeze.reviewerSnapshot)!==freeze.identity.reviewer)blockers.add('reviewer-snapshot-identity-mismatch');
 }
 const frozenSha256=digest(freeze);
 if(!executionsValid(run,frozenSha256))blockers.add('reviewer-execution-missing-or-mismatched');
 const coverage=reviewerCoverage(dataset,run,frozenSha256),uncovered=new Set(coverage.missingCaseIds),unsupported=new Set(coverage.unsupportedCaseIds);
 if(!coverage.receiptListValid||coverage.invalidReceiptIndices.length)blockers.add('reviewer-execution-inputs-missing-or-invalid');
 if(coverage.missingCaseIds.length)blockers.add('reviewer-execution-coverage-incomplete');
 if(coverage.duplicateReceiptIndices.length)blockers.add('reviewer-execution-duplicate');
 if(coverage.legacyReceiptIndices.length)blockers.add('reviewer-execution-legacy-receipt');
 if(coverage.unsupportedCaseIds.length)blockers.add('reviewer-language-unsupported');
 if(freeze.datasetSha256!==digest(dataset))blockers.add('dataset-changed-after-freeze');
 if(freeze.policySha256!==digest(policy))blockers.add('thresholds-changed-after-freeze');
 if(digest(freeze.identity)!==digest(run.identity))blockers.add('candidate-identity-changed');
 if(run.datasetSha256!==digest(dataset))blockers.add('run-dataset-mismatch');
 if(run.freezeSha256!==frozenSha256)blockers.add('run-freeze-mismatch');
 if(freeze.ledgerSha256!==digest(ledger)||digest([...new Set(freeze.developmentSourceSha256)].sort())!==digest(used))blockers.add('ledger-history-mismatch');
 if(Date.parse(freeze.createdAt)>=Date.parse(run.startedAt))blockers.add('freeze-not-before-run');
 const development=new Set([...used,...freeze.developmentSourceSha256]);
 const groups=new Map();
 for(const row of dataset.cases){
  const reasons=[];
  if(uncovered.has(row.id))reasons.push('reviewer-execution-source-uncovered');
  if(unsupported.has(row.id))reasons.push('reviewer-language-unsupported');
  if(development.has(row.sourceSha256)){overlap.push(row.id);blockers.add('development-sample-reused')}
  if(!qualifyingOracle(row))
   {blockers.add('vulnerability-oracle-incomplete');reasons.push('vulnerability-oracle-incomplete')}
  const selection=selectionIssue(row);
  if(selection){blockers.add(selection);reasons.push(selection)}
  let output=records.get(row.id)??{id:row.id,raw:'unknown',decision:'unknown',evidence:[]};
  if(precise){
   const source=actual.cases.get(row.id);
   if(!source||source.raw!==output.raw||output.pointId!==row.pointId||output.location?.sourceSha256!==row.sourceSha256){
    output={...output,raw:'unknown',decision:'unknown'};blockers.add('execution-point-output-mismatch');reasons.push('execution-point-output-mismatch');
   }
  }
  if(output.raw==='hit'&&(output.location?.line!==row.location.line||output.location?.sourceSha256!==row.sourceSha256||
     output.language!==row.language||output.cwe!==row.cwe)){
   output={...output,raw:'unknown',decision:'unknown'};blockers.add('scan-location-mismatch');reasons.push('scan-location-mismatch');
  }
  let decision=output.decision;
  if(run.version===4&&['confirmed','excluded'].includes(decision)){
   const actualVerification=verified.cases.get(row.id);
   if(!actualVerification||actualVerification.decision!==decision||!output.evidence.every(e=>e.kind==='sandbox-verification'&&e.artifactSha256===actualVerification.artifactSha256)){
    decision='unknown';blockers.add('verification-evidence-unavailable-or-mismatched');reasons.push('verification-evidence-unavailable-or-mismatched');
   }
  }
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
  const rows=groups.get(category)??[],summary=countsFor(rows.filter(item=>qualifyingSample(item.row))),limits=policy.categories[category],reasons=[];
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
  categories[category]={...summary,diagnostic:countsFor(rows),excludedFromQualification:rows.filter(item=>!qualifyingSample(item.row)).map(item=>item.row.id),thresholds:limits??null,blockers:reasons};
 }
 return{version:8,legacyDiagnosticOnly:run.version!==4,state:blockers.size?'blocked':run.version===4?'eligible-for-release-review':'diagnostic-only',r3Qualified:false,executionEnabled:false,
  ...(verified?{verificationCoverage:{supportedCases:[...verified.cases.keys()],issues:verified.issues},humanSupplement:Array.isArray(run.humanSupplement)?run.humanSupplement.slice(0,1000):[]}:{}),reviewerCoverage:coverage,...(actual?{executionPoints:dataset.cases.map(row=>({id:row.id,path:row.path,sourceSha256:row.sourceSha256,pointId:row.pointId,location:row.location,actual:actual.cases.get(row.id)??{raw:'unknown'}}))}:{}),
  categories,blockers:[...blockers],caseBlockers,developmentOverlap:overlap,usageRequired:usageRequired(dataset),freezeTrust:'self-attested; digest and attempt-consumption ledger need an independent release-review check',
  artifactReuse:[...artifactCases].filter(([,cases])=>cases.size>1).map(([sha256,cases])=>({sha256,caseIds:[...cases]})),
  definitions:{
   qualificationScope:'category metrics and thresholds require a verified independent-vulnerability oracle and a complete eligible blind-selection declaration bound to a protocol digest; other cases remain diagnostic and block qualification',
   selectionValidation:'selection fields and protocol digest format are self-attested; selection protocol content, timing, representativeness and independence require release review',
   reviewerValidation:'supported three-module closure, launcher and immutable runtime image bind reviewer identity; execution receipts are self-attested and their original input/output artifacts, aggregation and external sealing require release review; Docker and VM kernel remain trusted',
   reviewerCoverage:'version 2 receipts bind a bounded ASCII input-file digest map and scan digest; only completed matching unique input batches cover supported Python source cases, including diagnostic cases; other languages are explicitly unsupported; membership is not proof of per-site review, original artifact authenticity or aggregation correctness',
   coverageMetrics:'source coverage and unsupported-language blockers do not reclassify declared decisions or category metrics; global state, blockers and per-case reasons must be checked before any qualification claim',
   diagnosticScope:'all declared cases, including authored controls; these counts never satisfy qualification thresholds',
   rawFalsePositiveRate:'negative hits / observed negative cases',
   reviewedFalsePositiveRate:'negative confirmations / resolved negative cases',
   reviewedFalsePositiveRateUpperBound:'negative confirmations plus unknown negatives / all labelled negatives; finite-sample worst-case accounting, not a population confidence interval',
   reviewedFalseNegativeRate:'missed or wrongly excluded positives / resolved positive cases',
   confirmedRecall:'confirmed positives / all labelled positives',
   unknownRate:'unresolved cases / all labelled cases',
   evidenceOnly:'unknown decisions carrying evidence references; not verified exclusions',
   evidenceValidation:'declared evidence kind, input binding and artifact digest structure; evidence meaning requires independent review',
  }};
}


// v3 point identities and frozen inventories bind actual scanner/reviewer artifacts.
const supportedRules=new Set(['policy.harness.python.eval','policy.harness.python.exec','policy.harness.python.request-to-dynamic-code']);
const position=p=>record(p)&&Object.keys(p).sort().join(',')==='col,line,offset'&&Number.isSafeInteger(p.line)&&p.line>=1&&Number.isSafeInteger(p.col)&&p.col>=1&&Number.isSafeInteger(p.offset)&&p.offset>=0&&p.offset<=1048576;
function pointValid(p,hash){
 return record(p)&&p.sourceSha256===hash&&hashPattern.test(hash??'')&&['eval','exec','builtins.eval','builtins.exec'].includes(p.callee)&&
 record(p.call)&&position(p.call.start)&&position(p.call.end)&&p.call.end.offset>p.call.start.offset&&
 (p.call.end.line>p.call.start.line||p.call.end.line===p.call.start.line&&p.call.end.col>p.call.start.col)&&
 p.id===digest({sourceSha256:p.sourceSha256,callee:p.callee,call:p.call})&&p.builtinIdentity==='unverified'&&
 (p.argument===null||record(p.argument)&&position(p.argument.start)&&position(p.argument.end)&&p.argument.start.offset>=p.call.start.offset&&p.argument.end.offset<=p.call.end.offset&&p.argument.end.offset>p.argument.start.offset);
}
function bindingValid(binding,snapshot,identity){
 if(!record(binding)||binding.version!==1||binding.snapshotSha256!==identity.reviewer||binding.imageId!==snapshot?.imageId||!Number.isSafeInteger(binding.uid)||binding.uid<=0)return false;
 const inv=binding.inventory;
 if(!record(inv)||inv.version!==1||inv.protocol!=='python-sink-locations-1'||!/^3\.\d+\.\d+$/.test(inv.runtimePython)||!record(inv.files))return false;
 const files=Object.entries(inv.files);if(files.length<1||files.length>64)return false;
 return files.every(([path,f])=>sourceInputName('sources/'+path)&&record(f)&&hashPattern.test(f.sha256??'')&&Number.isSafeInteger(f.bytes)&&f.bytes>=0&&f.bytes<=1048576&&
 ['completed','unavailable'].includes(f.state)&&Array.isArray(f.points)&&f.points.length<=64&&new Set(f.points.map(p=>p.id)).size===f.points.length&&
 f.points.every(p=>pointValid(p,f.sha256)&&p.call.end.offset<=f.bytes)&&(f.state!=='unavailable'||f.points.length===0));
}
function artifactBinding(value,snapshot,identity,operation){
 try{
  const r=value.reviewerExecution,b=value.locationBinding,report=JSON.parse(value.reportJson);
  if(!bindingValid(b,snapshot,identity)||r?.version!==3||r.state!=='completed'||r.operation!==operation||r.snapshotSha256!==identity.reviewer||
   r.locationBindingSha256!==digest(b)||createHash('sha256').update(value.reportJson).digest('hex')!==r.reportSha256||!receiptInputsValid(r)||
   report.version!==2||(report.operation??'review')!==operation||digest(report.locations)!==digest(b.inventory)||
   !timestamp(r.startedAt)||!timestamp(r.finishedAt)||Date.parse(r.finishedAt)<Date.parse(r.startedAt))return null;
  const files=Object.fromEntries(Object.entries(r.inputFiles).filter(([n])=>sourceInputName(n)).map(([n,h])=>[n.slice(8),h]));
  if(digest(files)!==digest(Object.fromEntries(Object.entries(b.inventory.files).map(([n,f])=>[n,f.sha256]))))return null;
  return{binding:b,receipt:r,report};
 }catch{return null}
}
function rowBound(row,bindings){
 const matches=bindings.flatMap(b=>{const f=b.inventory.files[row.path];return f&&f.sha256===row.sourceSha256?[f]:[]});
 if(matches.length!==1||matches[0].state!=='completed')return false;
 if(row.pointId===null)return matches[0].points.length===0;
 const points=matches[0].points.filter(p=>p.id===row.pointId);
 return points.length===1&&row.location.line===points[0].call.start.line&&row.location.column===points[0].call.start.col;
}
function freezeLocations(dataset,identity,snapshot,values){
 requireValue(snapshotValid(snapshot)&&Array.isArray(values)&&values.length>0&&values.length<=1000);
 const rows=values.map(v=>artifactBinding(v,snapshot,identity,'locations'));requireValue(rows.every(Boolean));
 const locations=values.map(v=>({reviewerExecution:structuredClone(v.reviewerExecution),locationBinding:structuredClone(v.locationBinding),reportJson:v.reportJson}));
 requireValue(dataset.cases.every(row=>rowBound(row,rows.map(r=>r.binding))));
 requireValue(rows.every(r=>Date.parse(r.receipt.finishedAt)<=Date.now()));
 return locations;
}
function preciseArtifacts(dataset,run,freeze){
 const issues=[],cases=new Map();let frozen;
 try{
  requireValue(Array.isArray(freeze.locations)&&freeze.locations.length>0&&freeze.locations.length<=1000&&digest(freeze.locations)===freeze.locationsSha256);
  frozen=freeze.locations.map(v=>artifactBinding(v,freeze.reviewerSnapshot,freeze.identity,'locations'));
  requireValue(frozen.every(r=>r&&Date.parse(r.receipt.finishedAt)<=Date.parse(freeze.createdAt)));
  requireValue(dataset.cases.every(row=>rowBound(row,frozen.map(r=>r.binding))));
 }catch{return{issues:['frozen-locations-invalid-or-changed'],cases}}
 if(!Array.isArray(run.reviewArtifacts)||run.reviewArtifacts.length!==run.reviewerExecutions?.length||run.reviewArtifacts.length>1000)return{issues:['review-artifacts-missing'],cases};
 const batches=[];
 for(const [i,value] of run.reviewArtifacts.entries()){
  try{
   const r=run.reviewerExecutions[i],a=artifactBinding({...value,reviewerExecution:r},freeze.reviewerSnapshot,run.identity,'review');
   requireValue(a&&frozen.some(f=>digest(f.binding)===digest(a.binding)));
   requireValue(createHash('sha256').update(value.scanJson).digest('hex')===r.scanSha256&&createHash('sha256').update(value.manifestJson).digest('hex')===r.inputFiles['manifest.json']);
   const manifest=JSON.parse(value.manifestJson),scan=JSON.parse(value.scanJson),maps=a.report.findingLocations;
   requireValue(digest(manifest.locationBinding)===digest(a.binding)&&manifest.scanSha256===r.scanSha256&&digest(manifest.files)===digest(Object.fromEntries(Object.entries(a.binding.inventory.files).map(([n,f])=>[n,f.sha256]))));
   requireValue(Array.isArray(scan.results)&&scan.results.length<=2000&&Array.isArray(maps)&&maps.length===scan.results.length);
   for(const [j,m] of maps.entries()){
    const hit=scan.results[j];requireValue(record(m)&&m.index===j&&['bound','unmatched','ignored'].includes(m.state));
    const path=typeof hit?.path==='string'?hit.path.replace(/^\/src\//,''):null,file=a.binding.inventory.files[path];
    const span={start:hit?.start,end:hit?.end},rangeValid=position(span.start)&&position(span.end)&&span.end.offset>span.start.offset&&span.end.offset<=(file?.bytes??-1);
    const expected={'policy.harness.python.eval':'eval','policy.harness.python.exec':'exec'}[hit?.check_id];
    const candidates=rangeValid&&file?.state==='completed'&&supportedRules.has(hit?.check_id)?file.points.filter(p=>span.start.offset<=p.call.start.offset&&p.call.end.offset<=span.end.offset||!expected&&p.argument!==null&&digest(p.argument)===digest(span)):[];
    const unique=candidates.length===1&&(!expected||candidates[0].callee.split('.').at(-1)===expected)?candidates[0]:null;
    if(m.state==='bound')requireValue(unique&&m.path===path&&m.rule===hit.check_id&&m.pointId===unique.id&&digest(m.point)===digest(unique)&&digest(m.scannerSpan)===digest(span));
    else requireValue(!unique);
   }
   batches.push({...a,scan,maps});
  }catch{issues.push('review-artifact-binding-invalid:'+i)}
 }
 for(const row of dataset.cases){
  const matches=batches.filter(b=>b.binding.inventory.files[row.path]?.sha256===row.sourceSha256);
  if(matches.length!==1)continue;
  const b=matches[0],scanned=b.scan.paths?.scanned;
  const covered=Array.isArray(b.scan.errors)&&b.scan.errors.length===0&&Array.isArray(scanned)&&scanned.includes('/src/'+row.path);
  const uncertain=b.maps.some(m=>m.path===row.path&&m.state==='unmatched'&&supportedRules.has(m.rule));
  const hits=b.maps.filter(m=>m.state==='bound'&&m.pointId===row.pointId);
  cases.set(row.id,{raw:!covered||uncertain?'unknown':hits.length?'hit':'no-hit',pointId:row.pointId,rawHits:hits.length});
 }
 return{issues,cases};
}

const verifierPolicy={version:1,maxInputs:4,inputSeconds:5,pointSeconds:30,memoryMiB:512,cpus:1,pids:64,tmpMiB:32,outputBytes:262144,network:'none',proof:'python-narrow-literal-1'};
const probeTemplates=['control-literal-v1','expression-with-frozen-random-challenge-v1','statement-with-frozen-random-challenge-v1','syntax-error-v1'];
const probeValues=c=>["'harness-control'",`str('${c}')#`,`__harness_probe__='${c}'`,"'"];
const bytesHash=s=>typeof s==='string'?createHash('sha256').update(s).digest('hex'):null;
function shippedVerifierHash(filename){
 const bytes=readFileSync(new URL(filename,import.meta.url));
 return createHash('sha256').update(bytes).digest('hex');
}
function validVerificationPlan(plan,dataset,staticSnapshot){
 try{
  const v=plan.snapshot;requireValue(plan.version===1&&record(v)&&v.version===1&&v.kind==='python-execution-verifier'&&v.pythonVersion==='3.12.15'&&v.imageId===staticSnapshot.imageId&&v.staticSha256===digest(staticSnapshot)&&digest(v.staticSnapshot)===digest(staticSnapshot));
  requireValue(digest(v.policy)===digest(verifierPolicy)&&digest(v.probes)===digest(probeTemplates)&&record(v.code)&&Object.keys(v.code).sort().join(',')==='eval_evidence_batch.py,eval_guard_review.py,eval_import_review.py,python_execution_verify.py'&&Object.values(v.code).every(h=>hashPattern.test(h)));
  requireValue(v.controllerSha256===staticSnapshot.launcherSha256&&v.storageSha256===staticSnapshot.storageSha256&&hashPattern.test(v.verifierControllerSha256??'')&&record(v.dependencies)&&Object.keys(v.dependencies).length<=1000&&Object.values(v.dependencies).every(h=>hashPattern.test(h)));
  requireValue(v.code['python_execution_verify.py']===shippedVerifierHash('./python_execution_verify.py')&&
   v.verifierControllerSha256===shippedVerifierHash('./verifier_snapshot.py'));
  const lock=JSON.parse(readFileSync(new URL('./verifier-dependencies.lock.json',import.meta.url),'utf8'));
  requireValue(digest(v.dependencies)===digest(lock.files)&&digest(v.dependencyPackages)===digest(lock.packages));
  requireValue(Array.isArray(v.sourceProfiles)&&v.sourceProfiles.length>0&&v.sourceProfiles.every(h=>hashPattern.test(h))&&record(v.recipes)&&Object.entries(v.recipes).every(([h,c])=>h===digest(c)&&c.version===1&&c.inputContract==='untrusted-data-only'));
  for(const n of reviewerFiles)requireValue(v.code[n]===staticSnapshot.files[n]);
  requireValue(Array.isArray(plan.requests)&&plan.requests.length===dataset.cases.filter(r=>r.pointId!==null).length&&plan.requests.length<=1000);
  const seen=new Set(),challenges=new Set();
  for(const r of plan.requests){
   const c=dataset.cases.find(c=>c.id===r.caseId);requireValue(c&&c.pointId!==null&&!seen.has(c.id)&&r.point.id===c.pointId&&r.point.sourceSha256===c.sourceSha256&&r.contract.path===c.path&&pointValid(r.point,c.sourceSha256)&&v.sourceProfiles.includes(c.sourceSha256)&&v.recipes[digest(r.contract)]&&digest(v.recipes[digest(r.contract)])===digest(r.contract)&&hashPattern.test(r.challenge??'')&&!challenges.has(r.challenge));
   seen.add(c.id);challenges.add(r.challenge);
  }
  return true;
 }catch{return false}
}
function observedDecision(report,request){
 const point=request.point,callee=point.callee.split('.').at(-1),probes=probeValues(request.challenge),calls=[];
 if(report.pointId!==point.id||report.sourceSha256!==point.sourceSha256||digest(report.point)!==digest(point)||report.contractSha256!==digest(request.contract)||report.challengeSha256!==bytesHash(request.challenge)||report.runtimePython!=='3.12.15'||report.probePolicySha256!==digest({policy:verifierPolicy,probes:probeTemplates})||!Array.isArray(report.runs)||report.runs.length!==4)return'unknown';
 let triggered=false;
 for(const [i,r] of report.runs.entries()){
  if(r.inputIndex!==i||r.probeSha256!==bytesHash(probes[i])||r.trace?.state!=='observed'||!Array.isArray(r.trace.calls)||!Array.isArray(r.trace.returns)||r.trace.calls.length>16||r.trace.returns.length>16)return'unknown';
  for(const c of r.trace.calls){if(c.pointId!==point.id||c.callee!==callee||c.exactStr!==true||typeof c.argument!=='string'||c.argumentSha256!==bytesHash(c.argument))return'unknown';calls.push(c)}
  if(r.trace.returns.some(v=>v.pointId!==point.id))return'unknown';
  const exact=r.trace.calls.some(c=>c.argument===probes[i]||(i===1&&c.argument.startsWith(probes[i])));
  const witnessed=r.trace.returns.some(v=>callee==='eval'?v.evalWitness===true&&v.returnValue===request.challenge:v.execWitness===true&&v.markerValue===request.challenge);
  if(((callee==='eval'&&i===1)||(callee==='exec'&&i===2))&&exact&&witnessed)triggered=true;
 }
 if(triggered)return'confirmed';
 const proof=report.proof,e=request.contract.entry;
 if(!calls.length||!record(proof)||proof.domain!=='exact-str'||proof.sinkLine!==point.call.start.line||!Number.isSafeInteger(proof.guardLine)||proof.guardLine>=proof.sinkLine||!(e.kind==='function'&&proof.function===e.name&&digest(proof.parameters)===digest([e.parameter])||e.kind==='flask'&&digest(proof.parameters)===digest([])))return'unknown';
 if(proof.kind==='single-quoted-string'&&calls.every(c=>c.argument.startsWith("'")&&c.argument.endsWith("'")&&!c.argument.slice(1,-1).includes("'")))return'excluded';
 const literal=t=>typeof t==='string'&&t.length<=256&&/^(?:None|True|False|\d+(?:\.\d+)?|'[^'\n\r]*'|"[^"\n\r]*")$/.test(t);
 if(proof.kind==='finite-literal-set'&&Array.isArray(proof.values)&&proof.values.length>0&&proof.values.length<=16&&proof.values.every(literal)&&calls.every(c=>proof.values.includes(c.argument)))return'excluded';
 return'unknown';
}
function verificationArtifacts(dataset,run,freeze){
 const cases=new Map(),issues=[];
 if(!validVerificationPlan(freeze.verificationPlan,dataset,freeze.reviewerSnapshot)||digest(freeze.verificationPlan)!==freeze.verificationPlanSha256)return{cases,issues:['verification-plan-missing-or-changed']};
 if(!Array.isArray(run.verifierExecutions)||!Array.isArray(run.verificationArtifacts)||run.verifierExecutions.length!==run.verificationArtifacts.length||run.verifierExecutions.length>1000)return{cases,issues:['verification-artifacts-missing']};
 const pin=digest(freeze.verificationPlan.snapshot),seen=new Set();
 for(const [i,r] of run.verifierExecutions.entries()){
  try{
   const a=run.verificationArtifacts[i],request=JSON.parse(a.requestJson),report=JSON.parse(a.reportJson),manifest=JSON.parse(a.manifestJson),planned=freeze.verificationPlan.requests.find(p=>p.point.id===request.point.id&&p.contract.path===request.contract.path);
   requireValue(planned&&!seen.has(planned.caseId)&&digest({version:1,point:planned.point,contract:planned.contract,challenge:planned.challenge})===digest(request));
   requireValue(r.version===1&&r.operation==='verify-execution'&&r.state==='completed'&&r.cleanupVerified===true&&r.verifierSha256===pin&&r.datasetSha256===run.datasetSha256&&r.freezeSha256===digest(freeze)&&r.policySha256===digest(verifierPolicy)&&Number.isSafeInteger(r.uid)&&r.uid>0&&timestamp(r.startedAt)&&timestamp(r.finishedAt)&&Date.parse(r.startedAt)>=Date.parse(run.startedAt)&&Date.parse(r.finishedAt)>=Date.parse(r.startedAt));
   requireValue(record(r.inputFiles)&&Object.keys(r.inputFiles).length<=1100&&digest(r.inputFiles)===r.inputSha256&&r.reportSha256===bytesHash(a.reportJson)&&r.requestSha256===bytesHash(a.requestJson)&&r.inputFiles['verification-request.json']===r.requestSha256&&r.inputFiles['manifest.json']===bytesHash(a.manifestJson)&&r.inputFiles['scan.json']===bytesHash(a.scanJson));
   requireValue(manifest.locationBinding?.snapshotSha256===run.identity.reviewer&&manifest.locationBinding.imageId===freeze.reviewerSnapshot.imageId&&manifest.locationBinding.uid===r.uid&&r.inputFiles['sources/'+planned.contract.path]===planned.point.sourceSha256);
   requireValue(Object.entries(manifest.files).every(([n,h])=>r.inputFiles['sources/'+n]===h&&freeze.verificationPlan.snapshot.sourceProfiles.includes(h)));
   requireValue(Object.entries(freeze.verificationPlan.snapshot.dependencies).every(([n,h])=>r.inputFiles['dependencies/'+n]===h));
   const decision=observedDecision(report,request);requireValue(report.decision===decision||report.decision==='unknown');
   seen.add(planned.caseId);cases.set(planned.caseId,{decision:report.decision==='unknown'?'unknown':decision,artifactSha256:r.reportSha256});
  }catch{issues.push('verification-artifact-invalid:'+i)}
 }
 for(const request of freeze.verificationPlan.requests){
  if(!seen.has(request.caseId))issues.push('verification-request-unobserved:'+request.caseId);
 }
 return{cases,issues};
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
   if(![7,8,9,10].includes(process.argv.length))throw Error('Usage: review_quality_gate.mjs --freeze DATASET POLICY IDENTITY LEDGER [REVIEWER_SNAPSHOT [LOCATION_EXECUTIONS [VERIFICATION_PLAN]]]');
   console.log(JSON.stringify(freezeReviewInputs(...process.argv.slice(3).map(readInput)),null,2));
  }else{
   if(process.argv.length!==7)throw Error('Usage: review_quality_gate.mjs DATASET RUN FREEZE POLICY LEDGER');
   const result=evaluateReviewQuality(...process.argv.slice(2).map(readInput));
   console.log(JSON.stringify(result,null,2));
   if(result.state==='blocked')process.exitCode=2;
  }
 }catch(error){console.error(error.message);process.exitCode=1}
}
