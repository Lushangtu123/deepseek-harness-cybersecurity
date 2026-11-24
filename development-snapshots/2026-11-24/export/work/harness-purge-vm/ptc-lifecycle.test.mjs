import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {spawnSync} from 'node:child_process'

// Exercise the shipped run_code execute body with an inert registry/runtime.
// The child process makes an unhandled rejection or a stuck drain a test failure.
const source = fs.readFileSync(new URL('../../runtime-overrides/@deepseek-ai/dsh-tools/lib/index.js', import.meta.url), 'utf8')
const a = source.indexOf('\n\t\tasync execute(args, exec) {', source.indexOf('programDescription:'))
const b = source.indexOf('\n\t\tpresentCall:', a)
assert.ok(a >= 0 && b > a)
const executeBody = source.slice(a, b)

function scenarioScript(failure) {
  return `
import assert from 'node:assert/strict';
import vm from 'node:vm';
const mode=${JSON.stringify(failure)},events=[],schedulerKey=Symbol('scheduler');
let phaseCalls=0,active=0,maxActive=0;
const fail=phase=>{if((mode===phase||mode==='undefined'&&phase==='prepare')&&phaseCalls++===0)throw mode==='undefined'?undefined:Error('synthetic '+phase+' failure')};
const scheduler={
 async prepare(input){fail('prepare');events.push('prepare:'+input.arguments.id);return{kind:'dispatch',exec:input}},
 dispatch(input){fail('dispatch-sync');active++;maxActive=Math.max(maxActive,active);return Promise.resolve().then(()=>{fail('dispatch');return{kind:'post-result',result:{isError:false,value:input.arguments.id,content:[]}}}).finally(()=>{active--})},
 async finalize(input,result){fail('commit');events.push('commit:'+input.arguments.id);return result},
 finish(input,result){return result},
};
const registry={schemas:()=>[{name:'fixture'}],executionMode:input=>{fail('classify');return{kind:input.arguments.exclusive?'exclusive':'parallel'}},[schedulerKey]:scheduler};
let observed=[],abortOuter;
const outer=new AbortController();
const runtime={resolve:x=>x,async run(spec){
 const call=spec.bindings[0].functions.fixture;
 const pending=[call({id:1}),call({id:2,exclusive:true}),call({id:3})];
 if(mode==='abort')outer.abort('synthetic cancellation');
 observed=await Promise.allSettled(pending);
 return{logs:[],value:'synthetic complete'};
}};
const agent={session:{id:'synthetic-session',append(kind){if(kind==='tool/ptc-dispatch-start')fail('start');if(kind==='tool/ptc-dispatch')fail('log')}},ctx:{effect(){}}};
const context={registry,TOOL_RUNTIME_SCHEDULER:schedulerKey,requireRuntime:()=>runtime,
 validateEscalationArgs(){},options:{resolveWorkingDirectory:async()=>undefined},maxParallel:2,
 AbortController,Promise,stateOwners:new WeakMap(),symbols:{original:Symbol('original')},
 jsonNormalizeArgs:raw=>({dispatched:raw,logged:raw}),brandString:x=>x,deepFreeze:x=>x,
 shapeDispatchLog:async({content})=>content,createUserMessage:x=>x,
 CodeRunFailedError:class extends Error{},calls:{},RUN_CODE_NAME:'run_code'};
vm.createContext(context);vm.runInContext('this.execute=({'+${JSON.stringify(executeBody)}+'}).execute',context);
let failure;
try{await context.execute({description:'synthetic lifecycle',code:'synthetic'}, {callId:'root',rootCallId:'root',token:null,signal:outer.signal,agent})}catch(error){failure=error}
if(mode==='normal'){
 assert.equal(failure,undefined);assert.deepEqual(observed.map(x=>x.status),['fulfilled','fulfilled','fulfilled']);
 assert.deepEqual(events.filter(x=>x.startsWith('commit:')),['commit:1','commit:2','commit:3']);assert.ok(maxActive<=2);
}else if(mode==='abort')assert.ok(observed.some(x=>x.status==='rejected'));
else{assert.ok(failure,'lifecycle exception must fail the enclosing run');assert.equal(observed.length,3);assert.ok(observed.some(x=>x.status==='rejected'))}
assert.equal(active,0);console.log(JSON.stringify({mode,settled:observed.length,active,events}));
`
}

for (const failure of ['normal', 'start', 'classify', 'prepare', 'dispatch-sync', 'dispatch', 'commit', 'log', 'abort', 'undefined']) {
  test('PTC ordered dispatch settles and drains: ' + failure, () => {
    const child = spawnSync(process.execPath, ['--unhandled-rejections=strict', '--input-type=module', '-'],
      {input: scenarioScript(failure), encoding: 'utf8', timeout: 3000})
    assert.equal(child.status, 0, failure + ': ' + (child.error?.code ?? '') + '\n' + child.stderr)
    assert.match(child.stdout, /"settled":3/)
    assert.match(child.stdout, /"active":0/)
  })
}
