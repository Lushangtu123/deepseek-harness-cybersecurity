import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../package/lib/index.js', import.meta.url), 'utf8');

function bootHooks() {
  const names = [];
  const tools = [];
  const ctx = { get: () => null, tools: { register: (spec) => tools.push(spec) },
    effect: () => {}, on: () => () => {} };
  const scope = { core: { ALL_PATCHES: [], pinDshHome: () => '/synthetic', findDshHome: () => '/synthetic' },
    refreshHungOperator() {}, installIdentityOverride() { names.push('identity-override'); },
    installRegionGate() {}, installFreshFullAccess() { names.push('automatic-full-access'); },
    installRewindDeriveFilter() {}, installCwdCapture() {}, installMnemonMessageStrip() {},
    registerPromptSections() { names.push('unbounded-prompt'); },
    installPersonalControls() { names.push('personal-controls'); },
    continueRetry: { loadSettings: () => ({}), installContinueRetry: () => ({}) },
    installWebServer() {}, ctx, cfg: {}, result: null };
  const start = source.indexOf('function applyHostHooks(');
  const end = source.indexOf('\nfunction headerOf(', start);
  assert.ok(start >= 0 && end > start);
  vm.runInNewContext(source.slice(start, end) + '\napplyHostHooks(ctx,cfg);', scope);
  return { names, tools };
}

test('improved boot does not install automatic full access or override host authority', () => {
  const { names } = bootHooks();
  assert.ok(!names.includes('automatic-full-access'));
  assert.ok(!names.includes('identity-override'));
  assert.ok(!names.includes('unbounded-prompt'));
});

test('improved boot mounts personal authorization controls', () => {
  assert.ok(bootHooks().names.includes('personal-controls'));
});

test('protected operations ask with target and never approval fails closed', async () => {
  const { personalDecision, protectedTool } = await import('../package/lib/personal-controls.mjs');
  assert.equal(protectedTool('read'), false);
  assert.equal(protectedTool('bash'), true);
  assert.equal(protectedTool('redteam_evidence_upgrade'), true);
  const exec = { name: 'bash', arguments: { cwd: '/synthetic/project', command: 'touch example' }, agent: { session: {} } };
  const decision = personalDecision(exec, { effectivePolicy: () => 'ask' });
  assert.equal(decision.kind, 'ask');
  assert.match(decision.reason, /\/synthetic\/project/);
  assert.equal(personalDecision(exec, { effectivePolicy: () => 'never' }).kind, 'deny');
  assert.equal(personalDecision(exec, null).kind, 'deny');
});

test('VM autonomy requires explicit deployment config and the dedicated Linux home', async()=>{
 const { vmAutonomyEnabled }=await import('../package/lib/personal-controls.mjs');
 const runtime={platform:'linux',home:'/home/purge',dshHome:'/home/purge/.dsh-improved'};
 assert.equal(vmAutonomyEnabled({executionMode:'vm-autonomous'},runtime),true);
 assert.equal(vmAutonomyEnabled({},runtime),false);
 for(const changed of [{platform:'darwin'},{home:'/Users/LOCAL_USER'},{dshHome:'/home/purge/.dsh'}]) {
  assert.equal(vmAutonomyEnabled({executionMode:'vm-autonomous'},{...runtime,...changed}),false);
 }
});

test('authorized VM full-access sessions execute automatically while other never sessions stay denied',async()=>{
 const {personalDecision}=await import('../package/lib/personal-controls.mjs');
 const exec={name:'bash',arguments:{command:'printf VM_AUTO_OK'},agent:{session:{}}};
 const approval={effectivePolicy:()=> 'never'};
 const deployment={vmAutonomous:true,permissionState:{preset:'danger-full-access',sandbox:'danger-full-access',approval:'never'}};
 assert.equal(personalDecision(exec,approval,deployment).kind,'allow');
 assert.equal(personalDecision(exec,approval,{...deployment,vmAutonomous:false}).kind,'deny');
 assert.equal(personalDecision(exec,approval,{...deployment,permissionState:{...deployment.permissionState,sandbox:'workspace-write'}}).kind,'deny');
 assert.equal(personalDecision(exec,approval,{vmAutonomous:true}).kind,'deny');
 assert.equal(personalDecision(exec,{effectivePolicy:()=> 'ask'},deployment).kind,'ask');
});
