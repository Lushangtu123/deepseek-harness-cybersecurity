import fs from 'node:fs';import assert from 'node:assert/strict';import {join} from 'node:path';import {createHash} from 'node:crypto';import {execFile} from 'node:child_process';
import {createReviewSnapshot} from './work/harness-purge-improved/package/lib/redteam/personal-review-snapshot.mjs';
import {bindSemgrepSourceLocations} from './work/harness-purge-improved/package/lib/redteam/personal-security-source-location.mjs';
import {RedteamStore} from './work/harness-purge-improved/package/lib/redteam/store-core.js';
import {SecurityWorkbench} from './work/harness-purge-improved/package/lib/redteam/personal-security-workbench.mjs';
import {parseScanOutput} from './work/harness-purge-improved/package/lib/redteam/personal-security-workbench.mjs';
import {buildNamespaceInput,collectNamespaceEvidence} from './work/harness-purge-improved/package/lib/redteam/personal-namespace-evidence.mjs';
import {runNamespaceSandbox} from './work/harness-purge-improved/package/lib/redteam/personal-namespace-sandbox.mjs';
const data=JSON.parse(fs.readFileSync('replay-input.json')),phase=data.phases.arity17,root=process.cwd(),project=join(root,'native-project');fs.mkdirSync(project);
for(const c of phase.cases){assert.equal(createHash('sha256').update(c.source).digest('hex'),c.sha256);fs.writeFileSync(join(project,c.file),c.source)}
const snapshot=createReviewSnapshot({repoRoot:project,revision:1},join(root,'native-snapshot')),parsed=parseScanOutput('semgrep',phase.scan),bound=bindSemgrepSourceLocations(snapshot,parsed.findings),before=JSON.stringify(bound.findings);
const store=new RedteamStore(join(root,'automatic-state')),eng=store.openEngagement('automatic namespace native').id;
const bench=new SecurityWorkbench(store,{workspaceRoot:root,toolStatus:()=>({semgrep:{ready:true,version:'replayed-actual-scanner-fixture',admissionIdentity:'b'.repeat(64)}})});bench.pythonEvidence=()=>null;let scannerFixtureCalls=0;
bench.runner=async()=>{scannerFixtureCalls++;return{...parseScanOutput('semgrep',structuredClone(phase.scan)),coverageKey:'replayed17-only'}};
bench.saveScope(eng,{requestId:'native-namespace-scope',revision:0,repoRoot:project,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});
const job=bench.joint.start(eng,{mode:'deep',requestId:'native-namespace-start',profileRevision:1,steps:['semgrep'],budgetSeconds:30});await bench.joint.wait(eng,{id:job.id,waitSeconds:30});
const task=bench.joint.status(eng,{id:job.id}).task;assert.equal(task.state,'completed');assert.equal(scannerFixtureCalls,1);const sections={};
for(const section of ['findings','files','exclusions','diagnostics','artifacts']){sections[section]=[];let cursor;do{const page=bench.joint.report(eng,{id:job.id,section,limit:10,...(cursor?{cursor}:{})});sections[section].push(...page.page.items);cursor=page.page.nextCursor;if(page.page.complete)assert.equal(sections[section].length,page.page.total)}while(cursor)}
const result={summary:task.steps[0].namespaceReview,artifacts:sections.artifacts};assert.equal(result.summary.state,'completed',JSON.stringify(result.summary));assert.equal(result.summary.checked,19);assert.equal(result.artifacts.length,19);assert.equal(result.artifacts.filter(a=>a.constraintState==='fixed-set-guard-observed').length,2);assert.ok(result.artifacts.every(a=>a.status==='unverified'&&a.builtinIdentity==='unverified'&&a.externalControl==='unverified'&&a.sourceTask===task.steps[0].id&&a.snapshotId===task.snapshot.id));assert.ok(result.artifacts.every(a=>!Object.hasOwn(a,'literalSetSha256')));assert.equal(result.summary.execution.pythonVersion,'3.12.15');assert.equal(sections.findings.length,21);assert.equal(bench.db(eng).prepare('SELECT COUNT(*) n FROM security_finding').get().n,0);
await bench.dispose();await store.close();
const input=buildNamespaceInput(snapshot,bound.findings).request,bad=structuredClone(input);Object.values(bad.files)[0].sha256='0'.repeat(64);
await assert.rejects(runNamespaceSandbox(bad,{deadline:performance.now()+20000}));
const controller=new AbortController(),commands=[],inspected=[];
const docker=(args,{input='',signal,timeout=2000,maxBuffer=131072}={})=>new Promise((resolve,reject)=>{
 commands.push(args);const child=execFile('/usr/bin/sudo',['-n','/usr/bin/docker',...args],{encoding:'utf8',signal,timeout,killSignal:'SIGTERM',maxBuffer},(error,stdout,stderr)=>{if(error){error.stdout=stdout;error.stderr=stderr;reject(error)}else {if(args[0]==='inspect'){const rows=JSON.parse(stdout);if(rows[0]?.Config)inspected.push({stdin:{open:rows[0].Config.OpenStdin,attach:rows[0].Config.AttachStdin,once:rows[0].Config.StdinOnce},autoRemove:rows[0].HostConfig.AutoRemove})}resolve(stdout)}});child.stdin.on('error',()=>{});child.stdin.end(input);if(args[0]==='start')setTimeout(()=>controller.abort(),5);
});
await assert.rejects(runNamespaceSandbox(input,{deadline:performance.now()+20000,signal:controller.signal,docker}));assert.equal(commands.filter(a=>a[0]==='start').length,1);assert.ok(commands.some(a=>a[0]==='rm'));
const skipped=await collectNamespaceEvidence(snapshot,bound.findings.map(f=>({...f,rule:'policy.harness.python.eval'})),{deadline:performance.now()+20000,run:()=>{throw Error('Must not launch')}});assert.equal(skipped.summary.state,'not-applicable');
console.log(JSON.stringify({ok:true,scope:'prior real scanner bytes, authored development controls; no new scan or qualification',warningsRetained:bound.findings.length,summary:result.summary,artifacts:result.artifacts,automaticJoint:{task,sections,scannerFixtureCalls,ordinaryFindingRows:0},conditionalObservations:2,ordinary16NotApplicable:true,invalidDigestWorkerFailureCleaned:true,realCancelledWorkerCleaned:true,inspected,realReviewerContainerStarts:3,newScannerInvocations:0,modelCalls:0,r3Qualified:false}));
