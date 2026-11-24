import test from 'node:test';
import assert from 'node:assert/strict';
import {createJointPanel} from '../package/lib/redteam/personal-security-client.mjs';
const nodes=n=>Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.children??[])]:[];
const text=n=>Array.isArray(n)?n.map(text).join(''):typeof n==='string'?n:typeof n==='number'?String(n):text(n?.children??[]);
function fixture(){
 const cells=[];let index=0,phase='first',bad=false,rowMutator=()=>{},taskMutator=()=>{},replyOverride,namespaceArtifact;const stored=new Map();
 const calls=[],snapshot='a'.repeat(64),source='b'.repeat(64);
 const React={createElement:(type,props,...children)=>({type,props:props??{},children}),useState:v=>{const i=index++;if(!(i in cells))cells[i]=v;return[cells[i],n=>cells[i]=typeof n==='function'?n(cells[i]):n]},useRef:v=>({current:v}),useEffect:()=>{}};
 const task={id:'location-task-001',engagement:'fixture',state:'completed',scopeRevision:1,steps:[{tool:'semgrep',id:'scan-001',state:'completed',sourceLocations:{version:1,state:'completed',total:2,bound:2,unavailable:0}}],snapshot:{id:snapshot},findings:2,cleanupVerified:true};
 const row=col=>({tool:'semgrep',status:'unverified',sourceTask:'scan-001',snapshotId:snapshot,rule:'policy.harness.python.dynamic-code-namespace',location:'app.py:1',sourceLocation:{version:1,state:'bound',scope:'managed-source-copy',snapshotId:snapshot,path:'app.py',sourceSha256:source,byteLength:120,copyRedacted:true,start:{line:1,col,offset:col-1},end:{line:1,col:col+18,offset:col+17}}});
 const Component=createJointPanel(React,async r=>{
  calls.push(r);
  if(r.action==='plan')return{ok:true,engagement:'fixture',profileRevision:1,availableSteps:['semgrep'],kaliAllowed:false};
  if(r.action==='status'||r.action==='wait'||r.action==='cancel')return replyOverride??{ok:true,engagement:'fixture',task,requestState:'accepted'};
  if(r.section==='artifacts'&&namespaceArtifact)return{ok:true,engagement:'fixture',task,page:{section:'artifacts',items:[namespaceArtifact],total:1,complete:true,nextCursor:null}};
  const item=row(r.cursor?51:21);if(bad)item.sourceLocation.snapshotId='c'.repeat(64);
  if(phase==='unavailable')item.sourceLocation={version:1,state:'unavailable',reason:'missing-or-invalid-span'};
  rowMutator(item);const returned=structuredClone(task);taskMutator(returned);return{ok:true,engagement:'fixture',task:returned,page:{section:'findings',items:[item],total:2,complete:!!r.cursor,nextCursor:r.cursor?null:'positions-next'}};
 },{storage:()=>({getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)})});
 const render=()=>{index=0;return Component({engagement:'fixture',profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}})};
 const click=async name=>{const button=nodes(render()).find(n=>n.type==='button'&&text(n)===name);assert.ok(button,'Missing '+name);assert.notEqual(button.props.disabled,true,'Disabled '+name);await button.props.onClick()};
 return{render,click,calls,task,stored,setNamespaceArtifact(a){namespaceArtifact=a;task.steps[0].pythonEvidence='completed';task.steps[0].artifacts=1},mutateRow(fn){rowMutator=fn},mutateReplyTask(fn){taskMutator=fn},override(v){replyOverride=v},setBad(){bad=true},setUnavailable(){phase='unavailable';task.steps[0].sourceLocations={version:1,state:'unavailable',total:2,bound:0,unavailable:2}},setInvalidTask(){task.snapshot.id='invalid'},duplicateStep(){task.steps.push({...task.steps[0],id:'other-scan'})}};
}
test('Joint source positions page same-line sites separately with copy-only unverified language',async()=>{
 const f=fixture();await f.click('核对联合范围与原任务');assert.equal(f.calls.some(r=>r.action==='report'),false);
 await f.click('查看命中位置');let content=text(f.render());assert.match(content,/app.py:1:21/);assert.match(content,/待验证/);assert.match(content,/已脱敏/);assert.match(content,/不证明.*AST/);
 await f.click('下一页命中');assert.equal(f.calls.at(-1).cursor,'positions-next');content=text(f.render());assert.match(content,/app.py:1:51/);assert.doesNotMatch(content,/app.py:1:21/);
 assert.equal(f.calls.filter(r=>r.action==='start').length,0);
});
test('A mismatched snapshot cannot replace the already validated source-position page',async()=>{
 const f=fixture();await f.click('核对联合范围与原任务');await f.click('查看命中位置');f.setBad();await f.click('下一页命中');
 const content=text(f.render());assert.match(content,/命中位置.*不匹配/);assert.match(content,/app.py:1:21/);assert.doesNotMatch(content,/app.py:1:51/);
});
test('Unavailable source ranges keep the finding visible without invented coordinates',async()=>{
 const f=fixture();f.setUnavailable();await f.click('核对联合范围与原任务');await f.click('查看命中位置');
 const content=text(f.render());assert.match(content,/位置未关联/);assert.match(content,/待验证/);assert.doesNotMatch(content,/app.py:1:21/);
});
test('A source-location task needs a real snapshot digest before exposing its detail controls',async()=>{
 const f=fixture();f.setInvalidTask();await f.click('核对联合范围与原任务');
 assert.match(text(f.render()),/联合任务回执与项目不匹配/);
 assert.equal(nodes(f.render()).some(n=>n.type==='button'&&text(n)==='查看命中位置'),false);
});
test('Duplicate Semgrep steps are rejected rather than lending another step identity',async()=>{
 const f=fixture();f.duplicateStep();await f.click('核对联合范围与原任务');
 assert.match(text(f.render()),/联合任务回执与项目不匹配/);
});
test('Missing model counts stay unknown and byte-column units are explicit',async()=>{
 const f=fixture();await f.click('核对联合范围与原任务');
 assert.match(text(f.render()),/子任务模型请求 未知/);assert.doesNotMatch(text(f.render()),/子任务模型请求 0/);
 await f.click('查看命中位置');assert.match(text(f.render()),/列号.*UTF-8.*字节/);
});

for(const [name,change] of [
 ['wrong source task',r=>r.sourceTask='another-step'],['unavailable extra coordinates',r=>r.sourceLocation={version:1,state:'unavailable',reason:'source-unavailable',start:{offset:0}}],['empty range',r=>r.sourceLocation.end={...r.sourceLocation.start}],['wrong line label',r=>r.location='other.py:1']])test('Source page rejects '+name+' while retaining the valid page',async()=>{
 const f=fixture();await f.click('核对联合范围与原任务');await f.click('查看命中位置');f.mutateRow(change);await f.click('下一页命中');assert.match(text(f.render()),/不匹配/);assert.match(text(f.render()),/app.py:1:21/);
});
test('A page for a different parent task cannot replace existing positions',async()=>{const f=fixture();await f.click('核对联合范围与原任务');await f.click('查看命中位置');f.mutateReplyTask(t=>t.id='other-task');await f.click('下一页命中');assert.match(text(f.render()),/分页未确认/);assert.match(text(f.render()),/app.py:1:21/)});
for(const reply of [null,{id:'other-task',engagement:'fixture',state:'completed',scopeRevision:1,steps:[],findings:0,cleanupVerified:true}])test('Wait cannot replace the displayed task with '+(reply?'another task':'null'),async()=>{
 const f=fixture();f.task.state='running';f.task.cleanupVerified=false;await f.click('核对联合范围与原任务');f.override({ok:true,engagement:'fixture',task:reply});await f.click('等待原联合任务');assert.match(text(f.render()),/原任务.*不匹配/);assert.match(text(f.render()),/location-task-001/);
});
test('Python evidence independently requires both a concrete step id and snapshot SHA',async()=>{for(const invalidate of [f=>delete f.task.steps[0].id,f=>f.task.snapshot.id='invalid']){const f=fixture();delete f.task.steps[0].sourceLocations;f.task.steps[0].pythonEvidence='completed';f.task.steps[0].artifacts=1;invalidate(f);await f.click('核对联合范围与原任务');assert.match(text(f.render()),/回执与项目不匹配/)}});
test('A pending request is not cleared by an unrelated unacknowledged task',async()=>{const f=fixture();f.stored.set('dsh-joint-request-v1:fixture',JSON.stringify({engagement:'fixture',requestId:'pending-request-001'}));f.override({ok:true,engagement:'fixture',task:f.task,requestState:'unknown'});await f.click('核对联合范围与原任务');assert.equal(f.stored.size,1);assert.match(text(f.render()),/原启动请求.*未确认/)});
for(const value of ['0',-1,{}])test('Malformed model count is rejected: '+JSON.stringify(value),async()=>{const f=fixture();f.task.modelCalls=value;await f.click('核对联合范围与原任务');assert.match(text(f.render()),/回执与项目不匹配/)});
test('Cancelling state is visible while stop remains unconfirmed',async()=>{const f=fixture();f.task.state='cancelling';await f.click('核对联合范围与原任务');assert.match(text(f.render()),/取消中/);assert.doesNotMatch(text(f.render()),/回执与项目不匹配/)});

const nsSummary=(state='not-applicable')=>({version:1,state,eligible:0,checked:0,observations:0,unmatched:0,retained:0,cleanupVerified:true});
test('ordinary16 warning shows namespace reviewer not applicable without launching tools',async()=>{const f=fixture();f.task.steps[0].namespaceReview=nsSummary();await f.click('核对联合范围与原任务');assert.match(text(f.render()),/多参数结构复核/);assert.match(text(f.render()),/不适用/);assert.equal(f.calls.some(r=>r.action==='start'),false)});
test('namespace summary with impossible counts is rejected',async()=>{const f=fixture();f.task.steps[0].namespaceReview={...nsSummary('completed'),checked:3,eligible:1};await f.click('核对联合范围与原任务');assert.match(text(f.render()),/回执与项目不匹配/)});
test('namespace structural artifact renders unverified identities with a precise copy span',async()=>{const f=fixture();f.task.steps[0].namespaceReview={...nsSummary('completed'),eligible:1,checked:1,observations:1,retained:1};f.setNamespaceArtifact(nsArtifact());await f.click('核对联合范围与原任务');await f.click('查看 Python 证据');const content=text(f.render());assert.match(content,/多参数调用结构/);assert.match(content,/内建身份.*外部控制.*待核实/);assert.match(content,/app.py:1:1/)});

for(const summary of [
 {state:'completed',eligible:2,checked:2,observations:1,unmatched:1,retained:1},
 {state:'partial',eligible:1,checked:1,observations:1,unmatched:0,retained:1},
 {state:'truncated',eligible:1,checked:1,observations:1,unmatched:0,retained:1},
 {state:'unavailable',eligible:1,checked:1,observations:1,unmatched:0,retained:1},
 {state:'unavailable',eligible:1,checked:0,observations:0,unmatched:0,retained:0,cleanupVerified:false}
])test('inconsistent namespace summary does not become a completed-task statement: '+JSON.stringify(summary),async()=>{const f=fixture();f.task.steps[0].namespaceReview={...nsSummary(),...summary};await f.click('核对联合范围与原任务');assert.match(text(f.render()),/回执与项目不匹配/)});

const nsArtifact=()=>({tool:'semgrep',evidenceKind:'python-namespace-structure',sourceTask:'scan-001',snapshotId:'a'.repeat(64),status:'unverified',rule:'policy.harness.python.dynamic-code-namespace',path:'app.py',line:1,sink:'eval',argumentCount:2,bindingHint:'no-direct-conflict-observed',builtinIdentity:'unverified',sourceKind:'parameter-name-observed',externalControl:'unverified',assignmentLines:[],constraintState:'unresolved',sourceLocation:{version:1,state:'bound',scope:'managed-source-copy',snapshotId:'a'.repeat(64),path:'app.py',sourceSha256:'b'.repeat(64),byteLength:50,copyRedacted:false,start:{line:1,col:1,offset:0},end:{line:1,col:16,offset:15}}});

for(const [label,mutate] of [['missing summary',f=>delete f.task.steps[0].namespaceReview],['assignment after call',(f,a)=>a.assignmentLines=[2]],['guard after call',(f,a)=>Object.assign(a,{constraintState:'fixed-set-guard-observed',guardLine:2,literalCount:1,runtimeStringSemantics:'unverified',fixedValuesMayExecuteCode:true})]])test('namespace page rejects '+label,async()=>{const f=fixture(),a=nsArtifact();f.task.steps[0].namespaceReview={...nsSummary('completed'),eligible:1,checked:1,observations:1,retained:1};f.setNamespaceArtifact(a);mutate(f,a);await f.click('核对联合范围与原任务');await f.click('查看 Python 证据');assert.match(text(f.render()),/Python 证据.*不匹配/)});

test('fixed-set structure renders without exposing a guessable literal-set digest',async()=>{const f=fixture(),a=nsArtifact();f.task.steps[0].namespaceReview={...nsSummary('completed'),eligible:1,checked:1,observations:1,retained:1};Object.assign(a,{line:4,constraintState:'fixed-set-guard-observed',assignmentLines:[2],guardLine:3,literalCount:2,runtimeStringSemantics:'unverified',fixedValuesMayExecuteCode:true});a.sourceLocation.start.line=4;a.sourceLocation.end.line=4;f.setNamespaceArtifact(a);await f.click('核对联合范围与原任务');await f.click('查看 Python 证据');assert.doesNotMatch(text(f.render()),/不匹配/);assert.match(text(f.render()),/仍可能执行代码/);assert.equal(Object.hasOwn(a,'literalSetSha256'),false)});

const observationFacts=()=>({version:1,kind:'execution-point',confidence:'low',risk:'not-assessed',calleeIdentity:'unverified',inputControl:'unverified'});
test('execution-point observations display low confidence and unassessed risk separately from the scanner level',async()=>{const f=fixture();f.task.steps[0].observationSummary={version:1,total:2,executionPoints:1,other:1};f.mutateRow(r=>{r.observation=observationFacts();r.severity='medium'});await f.click('核对联合范围与原任务');await f.click('查看命中位置');const content=text(f.render());assert.match(content,/执行点观察 1/);assert.match(content,/执行点观察.*待核对/);assert.match(content,/低置信度/);assert.match(content,/风险尚未评估/);assert.match(content,/工具等级.*medium/);assert.doesNotMatch(content,/低风险/)});
for(const change of [r=>r.observation.risk='safe',r=>r.observation.confidence='high',r=>r.rule='another-rule'])test('source page rejects forged observation facts: '+change.toString(),async()=>{const f=fixture();f.task.steps[0].observationSummary={version:1,total:2,executionPoints:1,other:1};f.mutateRow(r=>{r.observation=observationFacts();change(r)});await f.click('核对联合范围与原任务');await f.click('查看命中位置');assert.match(text(f.render()),/命中位置.*不匹配/)});
for(const value of [{version:1,total:2,executionPoints:1,other:2},{version:1,total:1,executionPoints:1,other:0}])test('inconsistent observation summary is rejected: '+JSON.stringify(value),async()=>{const f=fixture();f.task.steps[0].observationSummary=value;await f.click('核对联合范围与原任务');assert.match(text(f.render()),/回执与项目不匹配/)});
test('historical tasks do not receive an invented execution-point count',async()=>{const f=fixture();await f.click('核对联合范围与原任务');const content=text(f.render());assert.match(content,/此任务未保存执行点分类/);assert.doesNotMatch(content,/执行点观察 0/)});
test('a classified exact-rule row cannot silently lose its observation label',async()=>{const f=fixture();f.task.steps[0].observationSummary={version:1,total:2,executionPoints:1,other:1};await f.click('核对联合范围与原任务');await f.click('查看命中位置');assert.match(text(f.render()),/命中位置.*不匹配/)});

test('namespace artifacts retain their separate evidence contract when the finding step is classified',async()=>{const f=fixture();f.task.steps[0].namespaceReview={...nsSummary('completed'),eligible:1,checked:1,observations:1,retained:1};f.task.steps[0].observationSummary={version:1,total:2,executionPoints:1,other:1};f.setNamespaceArtifact(nsArtifact());await f.click('核对联合范围与原任务');await f.click('查看 Python 证据');const content=text(f.render());assert.doesNotMatch(content,/不匹配/);assert.match(content,/多参数调用结构/);assert.match(content,/内建身份.*外部控制.*待核实/)});
for(const change of [a=>a.observation={...observationFacts(),risk:'safe'},a=>a.sourceLocation.snapshotId='c'.repeat(64)])test('classified-step artifacts still reject forged optional facts or source identity: '+change.toString(),async()=>{const f=fixture(),a=nsArtifact();f.task.steps[0].namespaceReview={...nsSummary('completed'),eligible:1,checked:1,observations:1,retained:1};f.task.steps[0].observationSummary={version:1,total:2,executionPoints:1,other:1};change(a);f.setNamespaceArtifact(a);await f.click('核对联合范围与原任务');await f.click('查看 Python 证据');assert.match(text(f.render()),/Python 证据.*不匹配/)});

test('deep task exposes the pinned17 rule contract without claiming R3 or confirmed vulnerabilities',async()=>{const f=fixture(),{deepSemgrepProfile}=await import('../package/lib/redteam/personal-semgrep-profile.mjs');f.task.workspace={version:'workspace-dispatch-s1-2',mode:'deep',selectedSteps:['semgrep'],ruleProfiles:{semgrep:deepSemgrepProfile()}};await f.click('核对联合范围与原任务');const content=text(f.render());assert.match(content,/本任务规则合同：17 条/);assert.match(content,new RegExp(deepSemgrepProfile().rulesSha256));assert.match(content,/普通检查R3尚未通过/)});
for(const mutate of [w=>w.ruleProfiles.semgrep.rulesSha256='f'.repeat(64),w=>delete w.ruleProfiles,w=>w.mode='ordinary'])test('new deep task rejects inconsistent rule contract: '+mutate.toString(),async()=>{const f=fixture(),{deepSemgrepProfile}=await import('../package/lib/redteam/personal-semgrep-profile.mjs');f.task.workspace={version:'workspace-dispatch-s1-2',mode:'deep',selectedSteps:['semgrep'],ruleProfiles:{semgrep:deepSemgrepProfile()}};mutate(f.task.workspace);await f.click('核对联合范围与原任务');assert.match(text(f.render()),/回执与原任务或项目不匹配|回执与项目不匹配/)});
test('legacy task with an explicit null workspace still renders without a deep rule claim',async()=>{const f=fixture();f.task.workspace=null;await f.click('核对联合范围与原任务');const content=text(f.render());assert.doesNotMatch(content,/不匹配|本任务规则合同/);assert.match(content,/所选步骤已结束/)});

test('Execution-point identity renders beside preserved scanner coordinates',async()=>{const f=fixture();f.mutateRow(row=>{const l=row.sourceLocation;row.pointId='c'.repeat(64);row.executionMapping={version:1,state:'bound',protocol:'python-sink-locations-1'};row.executionPoint={id:row.pointId,sourceSha256:l.sourceSha256,callee:'eval',call:{start:l.start,end:l.end},builtinIdentity:'unverified',argument:null}});await f.click('核对联合范围与原任务');await f.click('查看命中位置');const content=text(f.render());assert.match(content,/AST 执行点.*eval/);assert.match(content,/'?c{64}/);assert.match(content,/待验证/)});
for(const mutate of [r=>r.executionPoint.id='d'.repeat(64),r=>r.executionPoint.sourceSha256='d'.repeat(64),r=>r.executionMapping.state='confirmed'])test('Execution page rejects inconsistent metadata: '+mutate.toString(),async()=>{const f=fixture();f.mutateRow(row=>{const l=row.sourceLocation;row.pointId='c'.repeat(64);row.executionMapping={version:1,state:'bound',protocol:'python-sink-locations-1'};row.executionPoint={id:row.pointId,sourceSha256:l.sourceSha256,callee:'eval',call:{start:l.start,end:l.end},builtinIdentity:'unverified',argument:null};mutate(row)});await f.click('核对联合范围与原任务');await f.click('查看命中位置');assert.match(text(f.render()),/命中位置.*不匹配/)});

test('Unknown model total shows a verified subtotal and labels historical step values',async()=>{const f=fixture();Object.assign(f.task,{modelCalls:null,modelCallsState:'unknown',knownModelCalls:2});Object.assign(f.task.steps[0],{modelCalls:null,modelCallsState:'legacy',modelCallsRecorded:3});await f.click('核对联合范围与原任务');const content=text(f.render());assert.match(content,/模型请求 未知 次/);assert.match(content,/已核对 2 次/);assert.match(content,/原记录模型请求 3 次（未核对）/)});
