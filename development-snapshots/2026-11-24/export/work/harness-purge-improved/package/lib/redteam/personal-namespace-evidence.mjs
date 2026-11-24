import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {isDeepStrictEqual} from 'node:util';
import {bindSemgrepSourceLocations} from './personal-security-source-location.mjs';
import {readReviewFile} from './personal-review-snapshot.mjs';
import {runNamespaceSandbox} from './personal-namespace-sandbox.mjs';

const RULE='policy.harness.python.dynamic-code-namespace';
const hash=v=>createHash('sha256').update(v).digest('hex');
const key=(path,a)=>JSON.stringify([path,a.line,a.col,a.endLine,a.endCol,a.offset,a.endOffset]);
const anchor=l=>({line:l.start.line,col:l.start.col,endLine:l.end.line,endCol:l.end.col,offset:l.start.offset,endOffset:l.end.offset});
const summary=(state,eligible,extra={})=>({version:1,state,eligible,checked:0,observations:0,unmatched:0,retained:0,cleanupVerified:true,...extra});

export function buildNamespaceInput(snapshot,findings){
 if(!Array.isArray(findings)||findings.length>2000)return{state:'unavailable',eligible:0};
 const hits=findings.filter(f=>f?.rule===RULE),eligible=hits.length;
 if(!eligible)return{state:'not-applicable',eligible};
 try{
  const rebound=bindSemgrepSourceLocations(snapshot,hits.map(f=>({...f,scannerSpan:f.sourceLocation}))).findings;
  if(rebound.some((f,i)=>f.sourceLocation.state!=='bound'||!isDeepStrictEqual(f.sourceLocation,hits[i].sourceLocation)))throw Error();
  const files={},results=[],locations=new Map();let bytes=0;
  for(const f of hits){
   const l=f.sourceLocation;if(!l.path.endsWith('.py'))throw Error();
   if(!Object.hasOwn(files,l.path)){
    const raw=readReviewFile(join(snapshot.sourceRoot,l.path),l.byteLength);bytes+=raw.length;
    if(raw.length!==l.byteLength||hash(raw)!==l.sourceSha256||bytes>8388608||Object.keys(files).length>=64)throw Error();
    files[l.path]={base64:raw.toString('base64'),sha256:l.sourceSha256};
   }
   const a=anchor(l),k=key(l.path,a);if(locations.has(k))continue;
   if(results.length>=64)throw Error();locations.set(k,l);
   results.push({check_id:RULE,path:l.path,start:{...l.start},end:{...l.end}});
  }
  return{state:'ready',eligible,request:{files,results},locations};
 }catch{return{state:'unavailable',eligible}}
}

function projectReport(report,input){
 const execution=report?.execution;if(execution?.profile!=='namespace-ast-1'||execution.cleanupVerified!==true||!/^sha256:[a-f0-9]{64}$/.test(execution.imageId)||!/^[a-f0-9]{64}$/.test(execution.workerSha256))throw Error('Missing sandbox execution identity');
 if(report?.version!==2||!['completed','partial'].includes(report.state)||report.changesFindingDisposition!==false||report.r3Qualified!==false||
  report.checks!==input.locations.size||!Array.isArray(report.observations)||!Array.isArray(report.unmatchedAnchors)||report.observations.length+report.unmatchedAnchors.length!==report.checks)throw Error('Invalid structural report');
 if(!report.ignoredHits||Object.values(report.ignoredHits).some(v=>v!==0))throw Error('Unexpected ignored inputs');
 const seen=new Set(),artifacts=[];
 for(const [unmatched,rows] of [[false,report.observations],[true,report.unmatchedAnchors]])for(const row of rows){
  const k=key(row.file,row.anchor),l=input.locations.get(k);
  if(!l||seen.has(k)||row.rule!==RULE||row.sourceSha256!==l.sourceSha256)throw Error('Structural identity mismatch');seen.add(k);
  if(unmatched){if(row.reason!=='no-exact-supported-call')throw Error('Unknown unmatched reason');continue}
  if(row.version!==2||row.observation!=='namespace-call-structure-observed'||row.disposition!=='unverified'||!['eval','exec'].includes(row.sink)||![2,3].includes(row.argumentCount)||
   !['no-direct-conflict-observed','namespace-effects-observed','scope-effects-unresolved','local-binding-conflict-observed','module-binding-conflict-observed','unsupported-scope'].includes(row.callee?.staticBinding)||row.callee.builtinIdentity!=='unverified'||row.source?.externalControl!=='unverified'||
   !['expression-unresolved','literal-expression-observed','parameter-name-observed','local-name-unresolved','local-reassignment-observed','local-binding-observed'].includes(row.source.kind)||!Array.isArray(row.source.assignmentLines)||row.source.assignmentLines.length>64||row.source.assignmentLines.some(n=>!Number.isSafeInteger(n)||n<1||n>row.anchor.line))throw Error('Invalid structural observation');
  const c=row.constraint;if(!['unresolved','fixed-set-guard-observed'].includes(c?.state))throw Error('Invalid constraint');
  const fixed=c.state==='fixed-set-guard-observed';
  if(fixed&&(!Number.isSafeInteger(c.guardLine)||c.guardLine<1||c.guardLine>=row.anchor.line||!Number.isSafeInteger(c.literalCount)||c.literalCount<1||c.literalCount>16||!/^[a-f0-9]{64}$/.test(c.literalSetSha256)||c.runtimeStringSemantics!=='unverified'||c.fixedValuesMayExecuteCode!==true))throw Error('Invalid guard');
  artifacts.push({tool:'semgrep',evidenceKind:'python-namespace-structure',path:l.path,line:l.start.line,rule:RULE,status:'unverified',sourceLocation:l,
   sink:row.sink,argumentCount:row.argumentCount,bindingHint:row.callee.staticBinding,builtinIdentity:'unverified',sourceKind:row.source.kind,externalControl:'unverified',assignmentLines:[...row.source.assignmentLines],
   constraintState:c.state,...(fixed?{guardLine:c.guardLine,literalCount:c.literalCount,runtimeStringSemantics:'unverified',fixedValuesMayExecuteCode:true}:{})});
 }
 if(seen.size!==input.locations.size||report.state!==(report.unmatchedAnchors.length?'partial':'completed'))throw Error('Incomplete structural accounting');
 return{summary:summary(artifacts.length>20?'truncated':report.state,input.eligible,{checked:report.checks,observations:artifacts.length,unmatched:report.unmatchedAnchors.length,retained:Math.min(20,artifacts.length),execution:{profile:execution.profile,imageId:execution.imageId,workerSha256:execution.workerSha256,...(execution.pythonVersion?{pythonVersion:execution.pythonVersion}:{}),cleanupVerified:true}}),artifacts:artifacts.slice(0,20)};
}

export async function collectNamespaceEvidence(snapshot,findings,{deadline,signal,run=runNamespaceSandbox}={}){
 const input=buildNamespaceInput(snapshot,findings);
 if(input.state!=='ready')return{summary:summary(input.state,input.eligible),artifacts:[]};
 if(signal?.aborted||!Number.isFinite(deadline)||deadline-performance.now()<7000)return{summary:summary('unavailable',input.eligible),artifacts:[]};
 try{
  const report=await run(input.request,{deadline,signal});
  const repeated=buildNamespaceInput(snapshot,findings);
  if(repeated.state!=='ready'||!isDeepStrictEqual(input.request,repeated.request))throw Error('Snapshot changed during review');
  return projectReport(report,input);
 }catch(error){if(error.code==='STOP_UNCONFIRMED')throw error;return{summary:summary('unavailable',input.eligible),artifacts:[]}}
}
