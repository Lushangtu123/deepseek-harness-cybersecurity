import test from 'node:test';import assert from 'node:assert/strict';import {JointReview} from '../package/lib/redteam/personal-joint-review.mjs';
const view=steps=>JointReview.prototype.view({id:'fixture',steps,findings:[],cleanupVerified:true});
test('Missing or legacy model counts never turn into verified zero',()=>{
 for(const step of [{tool:'pentagi'},{tool:'pentagi',modelCalls:0}]){const v=view([step]);assert.equal(v.modelCalls,null);assert.notEqual(v.steps[0].modelCallsState,'verified')}
});
test('Unknown step leaves total unknown while preserving verified subtotal',()=>{
 const v=view([{tool:'pentagi',modelCalls:2,modelCallsState:'verified',modelCallsProtocol:1},{tool:'rea',modelCallsState:'unknown'}]);assert.equal(v.modelCalls,null);assert.equal(v.knownModelCalls,2);
});
test('Only all-verified counts produce a known task total',()=>{
 const v=view([{tool:'pentagi',modelCalls:2,modelCallsState:'verified',modelCallsProtocol:1},{tool:'rea',modelCalls:0,modelCallsState:'verified',modelCallsProtocol:1}]);assert.equal(v.modelCalls,2);assert.equal(v.knownModelCalls,2);
});
test('Adapter missing counts remain unknown; invalid counts cannot enter state',()=>{
 const base={id:'fixture-step',snapshotId:'a'.repeat(64),state:'completed',cleanupVerified:true,checkedFiles:0,artifacts:[]};
 const data={snapshot:{id:base.snapshotId,files:[]}},step={tool:'pentagi',id:base.id};JointReview.prototype.adapterResult(data,step,base);assert.equal(step.modelCalls,null);
 for(const invalid of [-1,17,true,'0'])assert.throws(()=>JointReview.prototype.adapterResult(data,step,{...base,modelCalls:invalid,modelCallsState:'verified',modelCallsProtocol:1}));
});

test('A verified assertion without count protocol is not a verified count',()=>{const v=view([{tool:'pentagi',modelCalls:0,modelCallsState:'verified'}]);assert.equal(v.modelCalls,null)});
test('Malformed unknown-zero response renders unknown rather than zero',async()=>{const m=await import('../package/lib/redteam/personal-security-client.mjs');assert.match(m.modelRequestCountText({modelCalls:0,modelCallsState:'unknown'}),/未知/)});
