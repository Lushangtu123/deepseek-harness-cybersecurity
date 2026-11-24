import test from 'node:test';
import assert from 'node:assert/strict';
import child from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {digest} from '../../../scripts/review_quality_gate.mjs';
const hash='a'.repeat(64),rule='policy.harness.python.eval';
const snapshot={sourceRoot:'/synthetic',files:[{path:'sample.py',sha256:hash}]};
const findings=[{rule,location:'sample.py:1',sourceLocation:{state:'bound',start:{line:1,col:1,offset:0},end:{line:1,col:8,offset:7}}}];
const report=()=>({version:2,guardEvidence:[],importEvidence:[],plainStringEvidence:[],findingLocations:[{index:0,state:'unmatched',reason:'missing-or-invalid-span'}]});
const point=()=>{const p={sourceSha256:hash,callee:'exec',call:{start:{line:1,col:1,offset:0},end:{line:1,col:8,offset:7}}};return{...p,id:digest(p)}};
const mapped=p=>({index:0,state:'bound',rule,path:'sample.py',scannerSpan:{start:findings[0].sourceLocation.start,end:findings[0].sourceLocation.end},pointId:p.id,point:p});
let output=report(),captured;
const original=child.execFileSync;
child.execFileSync=(file,args,options)=>{captured=JSON.parse(options.input);return JSON.stringify(output)};syncBuiltinESMExports();
const {collectPythonEvidence,bindPythonExecutionPoints}=await import('../package/lib/redteam/personal-python-evidence.mjs');
try{
 test('Managed mapping retains unmatched malformed locations and ignores null rows safely',()=>{
  output=report();const value=collectPythonEvidence(snapshot,[null,{rule,location:'broken'}],performance.now()+3000);
  assert.equal(value.state,'completed');assert.equal(value.findingLocations.length,1);assert.equal(captured.results[0].path,'');
 });
 test('No Python source still reports supported unmatched findings',()=>{
  const value=collectPythonEvidence({files:[]},findings,performance.now()+3000);assert.equal(value.state,'unavailable');assert.equal(value.findingLocations[0].reason,'source-not-in-inventory');
 });
 test('Import evidence requires both source-bound canonical point identities',()=>{
  const p=point();const evidence={observation:'direct-import-execution-flow-observed',callerFile:'sample.py',calleeFile:'sample.py',sink:'exec',sourceLine:1,importLine:1,callLine:1,definitionLine:1,sinkLine:1,callerLocation:p,sinkLocation:p};
  for(const mutate of [e=>delete e.callerLocation,e=>{e.callerLocation.id='f'.repeat(64)},e=>{e.sinkLocation.sourceSha256='f'.repeat(64)}]){
   output=report();const e=structuredClone(evidence);mutate(e);output.importEvidence=[e];assert.equal(collectPythonEvidence(snapshot,findings,performance.now()+3000).state,'unavailable');
  }
  output=report();output.importEvidence=[evidence];assert.equal(collectPythonEvidence(snapshot,findings,performance.now()+3000).artifacts.length,1);
 });
 test('Forged finding point identity is rejected instead of exposed',()=>{
  output=report();const p=point();p.id='f'.repeat(64);output.findingLocations=[mapped(p)];assert.equal(collectPythonEvidence(snapshot,findings,performance.now()+3000).state,'unavailable');
 });
 test('Indexed mapping cannot bind another file or an absent source digest',()=>{
  output=report();const p=point();output.findingLocations=[{...mapped(p),path:'other.py'}];
  assert.equal(collectPythonEvidence({...snapshot,files:[...snapshot.files,{path:'other.py',sha256:hash}]},findings,performance.now()+3000).state,'unavailable');
  output=report();const unbound=point();delete unbound.sourceSha256;const {id,...identity}=unbound;unbound.id=digest(identity);
  output.findingLocations=[mapped(unbound)];assert.equal(collectPythonEvidence(snapshot,findings,performance.now()+3000).state,'unavailable');
 });
 test('Guard and plain artifacts cannot discard forged finding IDs and complete',()=>{
  for(const kind of ['guardEvidence','plainStringEvidence']){
   output=report();const p=point();output.findingLocations=[mapped(p)];
   output[kind]=[{finding:{file:'sample.py',rule,line:1,pointId:'f'.repeat(64),executionPoint:p},evidence:{observation:kind==='guardEvidence'?'literal-identifier-guard-observed':'plain-string-guard-observed',sink:'eval',assignmentLine:1,guardLine:1,literalCount:1,evalLine:1,executionLine:1}}];
   assert.equal(collectPythonEvidence(snapshot,findings,performance.now()+3000).state,'unavailable');
  }
 });
 test('Missing scanner span becomes unavailable/unmatched instead of failing managed run',()=>{
  const p=point();output=report();output.findingLocations=[mapped(p)];delete output.findingLocations[0].scannerSpan;assert.equal(collectPythonEvidence(snapshot,findings,performance.now()+3000).state,'unavailable');
  const original={...findings[0],pointId:'f'.repeat(64),executionPoint:p,sourceLocation:{...findings[0].sourceLocation,path:'sample.py',sourceSha256:hash}};
  const value=bindPythonExecutionPoints([original],{findingLocations:output.findingLocations});assert.equal(value.findings[0].executionMapping.state,'unmatched');assert.equal(value.findings[0].pointId,undefined);assert.equal(value.summary.bound,0);
 });
 test('Binder preserves null/non-rule input and rejects out-of-order mapping index',()=>{
  assert.deepEqual(bindPythonExecutionPoints([null,{}],null).findings,[null,{}]);
  const p=point(),m=mapped(p);m.index=1;const row={...findings[0],sourceLocation:{...findings[0].sourceLocation,path:'sample.py',sourceSha256:hash}};
  const value=bindPythonExecutionPoints([row],{findingLocations:[m]});assert.equal(value.summary.bound,0);assert.equal(value.findings[0].pointId,undefined);
 });
}finally{process.on('exit',()=>{child.execFileSync=original;syncBuiltinESMExports()})}
