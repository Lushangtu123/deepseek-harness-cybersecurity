import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const moduleUrl=new URL('../package/lib/redteam/personal-security-workbench.mjs',import.meta.url);
async function api(){assert.ok(fs.existsSync(moduleUrl),'Security workbench module is missing');return import(moduleUrl)}
async function fixture(runner){
 const {SecurityWorkbench}=await api();const {RedteamStore}=await import('../package/lib/redteam/store-core.js');
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'security-workbench-'))),workspace=path.join(root,'workspace'),repo=path.join(workspace,'repo');fs.mkdirSync(repo,{recursive:true});fs.writeFileSync(path.join(repo,'app.py'),'print(1)\n');
 const store=new RedteamStore(path.join(root,'facts'));store.openEngagement('A');store.openEngagement('B');
 const bench=new SecurityWorkbench(store,{workspaceRoot:workspace,runner:runner||(async()=>({complete:true,findings:[],coverageKey:'fixed-policy'})),toolStatus:()=>({semgrep:{ready:true,version:'fixture'},trivy:{ready:true,version:'fixture'},zap:{ready:true,version:'fixture'}})});
 const scope=(changes={})=>({requestId:'scope-request-1',revision:0,repoRoot:repo,tools:['semgrep','trivy','zap'],url:'http://127.0.0.1:15000',expiresAt:new Date(Date.now()+3600000).toISOString(),confirm:true,...changes});
 return{bench,store,root,workspace,repo,scope,close:async()=>{await bench.dispose();store.close();fs.rmSync(root,{recursive:true,force:true})}};
}
const tick=()=>new Promise(setImmediate);
test('Every Semgrep partial-parse location remains visible with bounded diagnostics',async()=>{
 const {parseScanOutput}=await api();const locations=Array.from({length:23},(_,i)=>({path:'/src/gap'+i+'.mjs',start:{line:i+1}}));const r=parseScanOutput('semgrep',{results:[],errors:[{type:['PartialParsing',locations]}],paths:{scanned:locations.map(x=>x.path)}});
 assert.equal(r.complete,false);assert.equal(r.diagnostics.total,23);assert.equal(r.diagnostics.items.length,20);assert.equal(r.diagnostics.truncated,true);assert.deepEqual(r.diagnostics.items[1],{code:'PartialParsing',path:'gap1.mjs',line:2});
});
test('Project scope validates workspace boundaries, loopback targets, expiration and revision',async()=>{
 const f=await fixture();try{
  for(const change of [{repoRoot:f.root},{url:'https://outside.invalid'},{url:'http://127.0.0.1:49226'},{expiresAt:'2000-01-01T00:00:00Z'},{tools:['shell']},{confirm:false}])assert.throws(()=>f.bench.saveScope('a',f.scope(change)));
  const input=f.scope(),saved=f.bench.saveScope('a',input);assert.equal(saved.revision,1);assert.equal(f.bench.read('b').profile,null);
  assert.equal(f.bench.saveScope('a',input).revision,1,'Repeated same request is idempotent');
  assert.throws(()=>f.bench.saveScope('a',f.scope({requestId:'different',revision:0})),/范围已变化/);
  fs.symlinkSync(f.root,path.join(f.workspace,'escape'));assert.throws(()=>f.bench.saveScope('b',f.scope({repoRoot:path.join(f.workspace,'escape')})));
 }finally{await f.close()}
});
test('A durable run ID is reused for identical requests and only one worker runs',async()=>{
 let resolve,calls=0;const f=await fixture(async()=>{calls++;return new Promise(done=>{resolve=done})});try{
  f.bench.saveScope('a',f.scope());const req={requestId:'scan-request-1',profileRevision:1,tool:'semgrep'};
  const first=f.bench.start('a',req);const repeat=f.bench.start('a',req);assert.equal(first.id,repeat.id);await tick();assert.equal(calls,1);
  assert.throws(()=>f.bench.start('a',{...req,tool:'trivy'}));assert.throws(()=>f.bench.start('a',{...req,requestId:'scan-request-2'}),/任务正在运行/);
  resolve({complete:true,findings:[],coverageKey:'fixed-policy'});await tick();assert.equal(f.bench.read('a').runs[0].state,'completed');assert.equal(f.bench.read('b').runs.length,0);
 }finally{await f.close()}
});
test('Failed and partial workers never establish clean results or consume a retest',async()=>{
 const f=await fixture(async()=>{throw Error('private credential raw output')});try{
  f.bench.saveScope('a',f.scope());f.bench.start('a',{requestId:'scan-failure',profileRevision:1,tool:'semgrep'});await tick();const result=f.bench.read('a');assert.equal(result.runs[0].state,'failed');assert.ok(!JSON.stringify(result).includes('private credential'));
 }finally{await f.close()}
});
test('Findings require review and successful equivalent retest before closing; recurring hits reopen',async()=>{
 let answer={complete:true,coverageKey:'fixed-policy',findings:[{rule:'test.rule',title:'Synthetic issue',severity:'high',location:'app.py:1',evidence:'synthetic'}]};
 const f=await fixture(async()=>answer);try{
  f.bench.saveScope('a',f.scope());const run=async(id,extra={})=>{f.bench.start('a',{requestId:'scan-'+id,profileRevision:1,tool:'semgrep',...extra});await tick()};await run('initial');let finding=f.bench.read('a').findings[0];assert.equal(finding.status,'unverified');
  assert.throws(()=>f.bench.review('a',{id:finding.id,revision:finding.revision,status:'retest-passed',note:'trust me',requestId:'fake-review'}));
  finding=f.bench.review('a',{id:finding.id,revision:finding.revision,status:'confirmed',note:'Reviewed synthetic evidence',requestId:'confirm-1'});
  finding=f.bench.review('a',{id:finding.id,revision:finding.revision,status:'fixed',note:'Fix reference 1234567',requestId:'fix-request-1'});
  answer={complete:false,coverageKey:'fixed-policy',findings:[]};await run('partial',{retestFindingId:finding.id});assert.equal(f.bench.read('a').findings[0].status,'fixed');
  answer={complete:true,coverageKey:'different-policy',findings:[]};await run('different-policy',{retestFindingId:finding.id});assert.equal(f.bench.read('a').findings[0].status,'fixed');
  answer={complete:true,coverageKey:'fixed-policy',coverageFiles:['app.py'],findings:[]};await run('successful-retest',{retestFindingId:finding.id});assert.equal(f.bench.read('a').findings[0].status,'retest-passed');
  answer={complete:true,coverageKey:'fixed-policy',findings:[{rule:'test.rule',title:'Synthetic issue',severity:'high',location:'app.py:1',evidence:'synthetic'}]};await run('recurrence');assert.equal(f.bench.read('a').findings[0].status,'reopened');
  assert.ok(f.bench.report('a').markdown.includes('Synthetic issue'));
 }finally{await f.close()}
});
test('Retest requires original file coverage and moved-line hits reopen the original finding',async()=>{
 const hit={rule:'move.rule',title:'Moved issue',severity:'high',location:'app.py:1',evidence:'synthetic'};let answer={complete:true,coverageKey:'fixed-policy',coverageFiles:['app.py'],findings:[hit]};const f=await fixture(async()=>answer);
 try{f.bench.saveScope('a',f.scope());const run=async requestId=>{f.bench.start('a',{requestId,tool:'semgrep',profileRevision:1,...(finding?{retestFindingId:finding.id}:{})});await tick()};let finding;await run('initial-move');finding=f.bench.read('a').findings[0];finding=f.bench.review('a',{id:finding.id,revision:finding.revision,status:'confirmed',note:'Synthetic issue confirmed',requestId:'confirmed-move'});finding=f.bench.review('a',{id:finding.id,revision:finding.revision,status:'fixed',note:'Synthetic fix reference',requestId:'fixed-move'});
 answer={complete:true,coverageKey:'fixed-policy',coverageFiles:['other.py'],findings:[]};await run('skipped-original');assert.equal(f.bench.read('a').findings[0].status,'fixed');
 answer={complete:true,coverageKey:'fixed-policy',coverageFiles:['app.py'],findings:[{...hit,location:'app.py:8'}]};await run('moved-original');assert.equal(f.bench.read('a').findings.find(row=>row.id===finding.id).status,'reopened');
 }finally{await f.close()}
});
test('Unicode projects and reports with more records than the page limit remain usable',async()=>{
 const f=await fixture();try{const eng=f.store.openEngagement('安全审计验收').id;f.bench.saveScope(eng,f.scope());assert.equal(f.bench.read(eng).profile.revision,1);const db=f.bench.db(eng);const put=db.prepare("INSERT INTO security_finding(fingerprint,tool,rule,title,severity,location,evidence,status,first_run,last_run,coverage_key) VALUES(?,'semgrep','r',?,'high','app.py:1','fixture','unverified','first-run','last-run','policy')");for(let i=1;i<=501;i++)put.run('fingerprint-'+i,'entry-'+i);const page=f.bench.read(eng),report=f.bench.report(eng);assert.equal(page.findings.length,500);assert.equal(page.totalFindings,501);assert.equal(report.findings.length,501);assert.match(report.markdown,/entry-1\b/);assert.match(report.markdown,/entry-501\b/)}finally{await f.close()}
});
test('Cancellation and scope changes cannot silently race an in-flight worker',async()=>{
 const f=await fixture((_tool,_profile,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('cancelled')),{once:true})));try{
  f.bench.saveScope('a',f.scope());const run=f.bench.start('a',{requestId:'cancel-run',profileRevision:1,tool:'semgrep'});await tick();assert.throws(()=>f.bench.saveScope('a',f.scope({revision:1,requestId:'scope-request-2'})),/任务正在运行/);
  await f.bench.cancel('a',run.id);await tick();assert.equal(f.bench.read('a').runs[0].state,'cancelled');
 }finally{await f.close()}
});
test('Adapters parse structured output without retaining secrets and refuse malformed coverage',async()=>{
 const {parseScanOutput}=await api();
 const semgrep=parseScanOutput('semgrep',{results:[{check_id:'r',path:'/src/app.py',start:{line:1},extra:{message:'issue',severity:'ERROR',lines:'SECRET_SOURCE_CANARY'}}],errors:[],paths:{scanned:['app.py']}});assert.equal(semgrep.complete,true);assert.equal(semgrep.findings.length,1);assert.ok(!JSON.stringify(semgrep).includes('SECRET_SOURCE'));
 assert.equal(parseScanOutput('semgrep',{results:[],errors:[{message:'timeout'}],paths:{scanned:[]}}).complete,false);
 assert.throws(()=>parseScanOutput('semgrep',{results:{},errors:[]}));
 const trivy=parseScanOutput('trivy',{Results:[{Target:'requirements.txt',Secrets:[{RuleID:'secret',Title:'Secret',Severity:'HIGH',StartLine:1,Match:'PRIVATE_CANARY'}]}]});assert.ok(!JSON.stringify(trivy).includes('PRIVATE_CANARY'));
 assert.throws(()=>parseScanOutput('zap',{site:'wrong'}));
});
test('Container plans pin images, constrain resources and never accept arbitrary command arguments',async()=>{
 const {buildScanPlan}=await api();const profile={repoRoot:'/home/purge/workspace/repo',url:'http://127.0.0.1:15000'};const manifest={tools:['semgrep','trivy','zap'].map(tool=>({tool,imageId:'sha256:'+'a'.repeat(64),imageRef:'personal-security/'+tool+'@sha256:'+'a'.repeat(64),version:'fixture'}))};
 const plan=buildScanPlan('semgrep',profile,'/home/purge/workspace/runs/fixture',manifest);assert.equal(plan.executable,'/usr/bin/sudo');assert.ok(plan.args.includes('--read-only'));assert.ok(plan.args.includes('none'));assert.ok(plan.args.includes('sha256:'+'a'.repeat(64)));assert.ok(plan.args.includes('--metrics=off'));assert.ok(!plan.args.includes('--privileged'));
 assert.throws(()=>buildScanPlan('shell',profile,'/tmp/out',manifest));
});
test('ZAP XML scope matches the authorized origin and excludes similar hosts and ports',async()=>{
 const {buildZapContext}=await api();const xml=buildZapContext('http://127.0.0.1:49331'),expression=new RegExp(xml.match(/<incregexes>(.*?)<\/incregexes>/)[1]);assert.ok(expression.test('http://127.0.0.1:49331'));assert.ok(expression.test('http://127.0.0.1:49331/page'));assert.ok(!expression.test('http://127x0x0x1:49331/page'));assert.ok(!expression.test('http://127.0.0.1:49332/page'));
});
test('ZAP startup hook replaces every upstream listen host and fails closed if it cannot locate one',async()=>{
 const {buildZapHook}=await api();const code=`import types,sys\nm=types.ModuleType('zap_common')\nsys.modules['zap_common']=m\nm.create_start_options=lambda mode,port,extra:['zap.sh',mode,'-port',str(port),'-host','0.0.0.0',*extra]\nexec(${JSON.stringify(buildZapHook())})\nport,extra=start_zap(49090,['-host','192.0.2.1'])\nargs=m.create_start_options('-daemon',port,extra)\nassert [args[i+1] for i,x in enumerate(args) if x=='-host']==['127.0.0.1','127.0.0.1']\nassert args[args.index('-port')+1]=='49090'\nm.create_start_options=lambda *args:['zap.sh']\nstart_zap(49090,[])\ntry:m.create_start_options('-daemon',49090,[]);raise AssertionError('missing host accepted')\nexcept RuntimeError:pass\n`;const result=spawnSync('python3',['-c',code],{encoding:'utf8',timeout:5000});assert.equal(result.status,0,result.stderr);
});
test('Starting a scan obtains fresh runtime evidence and refuses missing resources before minting a run',async()=>{
 const f=await fixture();try{f.bench.saveScope('a',f.scope());const calls=[];f.bench.toolStatus=options=>{calls.push(options);return{semgrep:{ready:options?.force!==true,version:'fixture',reason:'本地镜像未找到或摘要不匹配'}}};assert.throws(()=>f.bench.start('a',{requestId:'fresh-check-start',profileRevision:1,tool:'semgrep'}),/镜像/);assert.equal(calls.at(-1).force,true);assert.equal(f.bench.read('a').runs.length,0)}finally{await f.close()}
});
test('Each run and its report preserve the actual verified rule policy',async()=>{
 const f=await fixture();try{
  const policy={version:'local-reviewed-2',count:16,languages:['javascript','python','typescript']};f.bench.toolStatus=()=>({semgrep:{ready:true,version:'fixture',rules:policy}});f.bench.saveScope('a',f.scope());f.bench.start('a',{requestId:'rule-policy-snapshot',profileRevision:1,tool:'semgrep'});await f.bench.active.promise;
  const result=f.bench.read('a');assert.deepEqual(result.runs[0].details.runtime.rules,policy);assert.match(f.bench.report('a').markdown,/local-reviewed-2/);assert.match(f.bench.report('a').markdown,/16条/);
 }finally{await f.close()}
});

test('A changed rule digest changes the scanner policy identity used by retests',async()=>{
 const {buildScanPlan}=await api();const imageId='sha256:'+'a'.repeat(64),manifest={tools:[{tool:'semgrep',imageId}],rulesSha256:'a'.repeat(64)},profile={repoRoot:'/home/purge/workspace/fixture'};
 assert.notEqual(buildScanPlan('semgrep',profile,'/tmp/run',manifest).coverageKey,buildScanPlan('semgrep',profile,'/tmp/run',{...manifest,rulesSha256:'b'.repeat(64)}).coverageKey);
});

test('Report summaries count every record even when exported details reach the 20000 limit',async()=>{
 const f=await fixture();try{
  const db=f.bench.db('a'),put=db.prepare("INSERT INTO security_finding(fingerprint,tool,rule,title,severity,location,evidence,status,first_run,last_run,coverage_key) VALUES(?,'semgrep','r',?,?,?,'fixture',?,'first','last','policy')");
  db.exec('BEGIN');try{for(let i=0;i<20001;i++)put.run('summary-'+i,'record-'+i,i===0?'critical':'high','app.py:'+i,i===0?'confirmed':'unverified');db.exec('COMMIT')}catch(e){db.exec('ROLLBACK');throw e}
  const report=f.bench.report('a');assert.equal(report.findings.length,20000);assert.equal(report.exportComplete,false);assert.equal(report.summary.findings.total,20001);assert.equal(report.summary.findings.byStatus.confirmed,1);assert.equal(report.summary.findings.byStatus.unverified,20000);assert.equal(report.summary.findings.bySeverity.critical,1);assert.equal(Object.values(report.summary.findings.byStatus).reduce((a,b)=>a+b,0),20001);assert.match(report.markdown,/汇总依据全部记录/);assert.match(report.markdown,/20000\/20001条发现/);assert.match(report.markdown,/此报告仅含部分记录/);assert.match(report.markdown,/待验证.*20000/);assert.match(report.markdown,/已确认.*1/)
 }finally{await f.close()}
});
test('Reports distinguish the current scope from recorded task scope and never replace historical runtime metadata',async()=>{
 const f=await fixture();try{
  f.bench.toolStatus=()=>({semgrep:{ready:true,version:'recorded-scanner',checkedAt:'2026-10-29T01:00:00Z',rules:{version:'recorded-rules',count:16,languages:['python']},database:{updatedAt:'2026-10-28T01:00:00Z'}}});f.bench.saveScope('a',f.scope());const run=f.bench.start('a',{requestId:'report-recorded-run',profileRevision:1,tool:'semgrep'});await f.bench.active.promise;
  const other=path.join(f.workspace,'later-repo');fs.mkdirSync(other);f.bench.saveScope('a',f.scope({revision:1,requestId:'report-new-scope',repoRoot:other}));f.bench.toolStatus=()=>({semgrep:{ready:true,version:'current-version-must-not-fill-history'}});
  const report=f.bench.report('a');assert.match(report.markdown,/当前保存范围/);assert.match(report.markdown,/不是历史任务的统一范围/);assert.ok(report.markdown.includes(other));assert.ok(report.markdown.includes(f.repo));assert.ok(report.markdown.includes(run.id));assert.match(report.markdown,/recorded-scanner/);assert.match(report.markdown,/recorded-rules/);assert.match(report.markdown,/2026-10-28T01:00:00Z/);assert.doesNotMatch(report.markdown,/current-version-must-not-fill-history/);assert.equal(report.summary.runs.notComplete,0)
 }finally{await f.close()}
});
const reportRun=(db,id,state,complete,details={})=>db.prepare('INSERT INTO security_run(id,request_id,request_hash,tool,profile_revision,state,started_at,complete,details) VALUES(?,?,?,?,?,?,?,?,?)').run(id,'request-'+id,'fixture','trivy',1,state,'2026-10-29T00:00:00Z',complete,JSON.stringify(details));
test('Empty reports and legacy or unfinished tasks expose uncertainty without inferring a clean result',async()=>{
 const f=await fixture();try{
  let report=f.bench.report('a');assert.equal(report.summary.findings.total,0);assert.equal(report.summary.runs.total,0);assert.match(report.markdown,/尚无任务/);assert.match(report.markdown,/未保存范围/);
  const db=f.bench.db('a');for(const [id,state,complete] of [['legacy','completed',1],['failed','failed',0],['partial','partial',0],['running','running',0],['future','future-state',1]])reportRun(db,id,state,complete);
  db.prepare("INSERT INTO security_finding(fingerprint,tool,rule,title,severity,location,evidence,status,first_run,last_run,coverage_key) VALUES('legacy-extra','trivy','legacy','Legacy','custom','old.py','fixture','future-status','legacy','legacy','key')").run();
  report=f.bench.report('a');assert.equal(report.summary.runs.total,5);assert.equal(report.summary.runs.notComplete,4);assert.equal(report.summary.runs.byState.other,1);assert.equal(report.summary.findings.byStatus.other,1);assert.equal(report.summary.findings.bySeverity.other,1);assert.match(report.markdown,/未完整结束的任务：4/);assert.match(report.markdown,/历史范围未记录/);assert.match(report.markdown,/工具版本：未记录/);assert.match(report.markdown,/未完成任务不代表安全/);assert.doesNotMatch(report.markdown,/工具版本：fixture/)
 }finally{await f.close()}
});
test('Report metadata remains literal Markdown and credential-like values are redacted again at export',async()=>{
 const f=await fixture();try{
  const db=f.bench.db('a'),secret='sk-'+'Z'.repeat(28);db.prepare("INSERT INTO security_finding(fingerprint,tool,rule,title,severity,location,evidence,status,first_run,last_run,coverage_key,note) VALUES('literal','semgrep','r',?,'high','app.py:1','fixture','unverified','first','last','key',?)").run('Issue\n## forged | <script>','password=REPORT_SECRET_CANARY '+secret);
  const report=f.bench.report('a');assert.doesNotMatch(report.markdown,/\n## forged|<script>|REPORT_SECRET_CANARY/);assert.ok(!report.markdown.includes(secret));assert.match(report.markdown,/\\\|/);assert.equal(f.bench.read('a').findings[0].note,'password=REPORT_SECRET_CANARY '+secret,'Export must not mutate stored findings')
 }finally{await f.close()}
});
test('A missing historical URL stays unknown while an explicit null URL is unconfigured',async()=>{
 const f=await fixture();try{
  const db=f.bench.db('a');reportRun(db,'missing-url','completed',1,{profile:{repoRoot:f.repo}});reportRun(db,'null-url','completed',1,{profile:{repoRoot:f.repo,url:null}});
  const markdown=f.bench.report('a').markdown,section=id=>markdown.split('### '+id+'\n')[1].split('\n### ')[0];
  assert.match(section('missing-url'),/本地网址：未记录/);assert.match(section('null-url'),/本地网址：未配置/)
 }finally{await f.close()}
});

test('ZAP scope stores only a named private authentication profile and rejects credential fields',async()=>{
 const f=await fixture();try{
  let saved;assert.doesNotThrow(()=>{saved=f.bench.saveScope('a',f.scope({authProfile:'local-login-lab'}))});
  assert.equal(saved.authProfile,'local-login-lab');assert.equal(f.bench.read('a').profile.authProfile,'local-login-lab');
  for(const extra of [{authProfile:'../escape'},{authProfile:'local-login-lab',url:null},{authProfile:'local-login-lab',tools:['semgrep']},{cookie:'PRIVATE_SESSION_VALUE'}])assert.throws(()=>f.bench.saveScope('b',f.scope(extra)));
 }finally{await f.close()}
});

test('Authenticated ZAP hook scopes the private header and verifies real sender responses without persisting it',async()=>{
 const {buildZapHook}=await api(),root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'zap-auth-hook-')));
 try{
  const config={version:1,revision:'879b1b08-0a7d-4f84-9f1d-d50cb7f94072',origin:'http://127.0.0.1:15000',header:'Cookie',value:'sid=HOOK_CANARY_'+ 'X'.repeat(32),verifyPath:'/account',loggedInMarker:'HARNESS_AUTHENTICATED',excludePaths:['/logout'],expiresAt:new Date(Date.now()+600000).toISOString()};fs.writeFileSync(path.join(root,'.session.json'),JSON.stringify(config),{mode:0o600});
  const code=`import types,sys,json,re\nfrom pathlib import Path\nm=types.ModuleType('zap_common');sys.modules['zap_common']=m\nfrom importlib.machinery import SourceFileLoader\nloader=SourceFileLoader('zap_hooks',${JSON.stringify(path.join(root,'loopback-hook.py'))})\nmodule=types.ModuleType(loader.name);loader.exec_module(module);namespace=module.__dict__\nassert '__file__' not in namespace, 'fixed upstream loader contract changed'\ndef private_input(name,mode):\n assert str(name)=='/input/.session.json' and mode=='rb'\n return open(Path.cwd()/'.session.json',mode)\nnamespace['open']=private_input\nassert callable(namespace.get('zap_tuned')), 'authenticated setup hook missing'\nrules=[];forms=[];sent=[]\ndef add_rule(*args,**kwargs):\n rules.append((args,kwargs));return 'OK'\ndef send(request,followredirects=None):\n assert followredirects=='false';assert 'Cookie' not in request;sent.append(request);return [{'responseHeader':'HTTP/1.1 200 OK\\r\\n','responseBody':'HARNESS_AUTHENTICATED'}]\nzap=types.SimpleNamespace(replacer=types.SimpleNamespace(add_rule=add_rule),spider=types.SimpleNamespace(set_option_process_form=lambda value:forms.append(value),set_option_post_form=lambda value:forms.append(value)),core=types.SimpleNamespace(send_request=send))\nnamespace['zap_tuned'](zap);namespace['zap_pre_shutdown'](zap)\nassert len(rules)==1 and len(sent)==2 and forms==['false','false']\nargs,kwargs=rules[0];assert args[2]=='REQ_HEADER' and args[4]=='Cookie' and args[5]==${JSON.stringify(config.value)}\nassert re.match(kwargs['url'],'http://127.0.0.1:15000/account')\nassert not re.match(kwargs['url'],'http://127.0.0.1:15001/account')\nassert not re.match(kwargs['url'],'http://127.0.0.1:150000/account')\nvalue=json.loads(Path(${JSON.stringify(path.join(root,'auth-check.json'))}).read_text());assert value['before'] is True and value['after'] is True and value['checkedRequests']==2\nassert 'HOOK_CANARY' not in json.dumps(value)\n`;
  fs.writeFileSync(path.join(root,'loopback-hook.py'),buildZapHook(true));const result=spawnSync('python3',['-c',code],{cwd:root,encoding:'utf8',timeout:5000});assert.equal(result.status,0,result.stderr);
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});

test('Authenticated runs cannot be completed without both controller and ZAP sender verification',async()=>{
 const f=await fixture(async()=>({complete:true,findings:[],coverageKey:'auth-fixture'}));try{
  f.bench.saveScope('a',f.scope({authProfile:'local-login-lab'}));f.bench.start('a',{requestId:'missing-auth-proof',profileRevision:1,tool:'zap'});await f.bench.active.promise;
  const run=f.bench.read('a').runs[0];assert.equal(run.state,'partial');assert.equal(run.complete,0);assert.equal(run.details.authentication.state,'unconfirmed');assert.ok(run.details.diagnostics.items.some(row=>row.code==='authentication-unconfirmed'));
 }finally{await f.close()}
});

test('Authenticated ZAP scope excludes logout and separates revisions in comparison policy',async()=>{
 const {buildZapContext,buildScanPlan}=await api(),url='http://127.0.0.1:15000';assert.match(buildZapContext(url,['/logout']),/<excregexes>/);
 const profile={repoRoot:'/home/purge/workspace/fixture',url,authProfile:'local-login'},manifest={tools:[{tool:'zap',imageId:'sha256:'+'a'.repeat(64)}]};
 const first=buildScanPlan('zap',profile,'/tmp/run',manifest,{revision:'879b1b08-0a7d-4f84-9f1d-d50cb7f94072'}),second=buildScanPlan('zap',profile,'/tmp/run',manifest,{revision:'729b1b08-0a7d-4f84-9f1d-d50cb7f94072'});assert.notEqual(first.coverageKey,second.coverageKey);
});

test('A missing private session fails the actual runner with an explicit authentication outcome',async()=>{
 const {SecurityWorkbench}=await api(),f=await fixture(),bench=new SecurityWorkbench(f.store,{workspaceRoot:f.workspace,toolStatus:()=>({zap:{ready:true,version:'fixture'}})});
 try{bench.saveScope('a',f.scope({authProfile:'nonexistent-qa-'+String(process.pid)}));bench.start('a',{requestId:'missing-session-qa',profileRevision:1,tool:'zap'});await bench.active.promise;const run=bench.read('a').runs[0];assert.equal(run.state,'failed');assert.match(run.error_code,/认证/);assert.equal(run.complete,0)}finally{await bench.dispose();await f.close()}
});

test('ZAP final authentication loss retains a negative receipt for partial-result handling',async()=>{
 const {buildZapHook}=await api(),root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'zap-auth-lost-')));
 try{
  fs.writeFileSync(path.join(root,'.session.json'),JSON.stringify({revision:'879b1b08-0a7d-4f84-9f1d-d50cb7f94072',origin:'http://127.0.0.1:15000',header:'Cookie',value:'sid=HOOK_CANARY_'+ 'X'.repeat(32),verifyPath:'/account',loggedInMarker:'HARNESS_AUTHENTICATED',expiresAt:new Date(Date.now()+600000).toISOString()}),{mode:0o600});
  const code=`import types,sys,json\nfrom pathlib import Path\nm=types.ModuleType('zap_common');sys.modules['zap_common']=m\nfrom importlib.machinery import SourceFileLoader\nloader=SourceFileLoader('zap_hooks',${JSON.stringify(path.join(root,'loopback-hook.py'))})\nmodule=types.ModuleType(loader.name);loader.exec_module(module);namespace=module.__dict__\nassert '__file__' not in namespace, 'fixed upstream loader contract changed'\ndef private_input(name,mode):\n assert str(name)=='/input/.session.json' and mode=='rb'\n return open(Path.cwd()/'.session.json',mode)\nnamespace['open']=private_input\ncore=types.SimpleNamespace(send_request=lambda *args,**kwargs:[{'responseHeader':'HTTP/1.1 200 OK\\r\\n','responseBody':'HARNESS_AUTHENTICATED'}])\nzap=types.SimpleNamespace(replacer=types.SimpleNamespace(add_rule=lambda *args,**kwargs:'OK'),spider=types.SimpleNamespace(set_option_process_form=lambda value:None,set_option_post_form=lambda value:None),core=core)\nnamespace['zap_tuned'](zap)\ncore.send_request=lambda *args,**kwargs:[{'responseHeader':'HTTP/1.1 401 Unauthorized\\r\\n','responseBody':'LOGIN_REQUIRED'}]\nnamespace['zap_pre_shutdown'](zap)\nvalue=json.loads(Path(${JSON.stringify(path.join(root,'auth-check.json'))}).read_text());assert value['before'] is True and value['after'] is False and value['checkedRequests']==1\n`;
  fs.writeFileSync(path.join(root,'loopback-hook.py'),buildZapHook(true));const result=spawnSync('python3',['-c',code],{cwd:root,encoding:'utf8',timeout:5000});assert.equal(result.status,0,result.stderr);
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});

test('Known session values are removed before ZAP field truncation can retain long credential prefixes',async()=>{
 const {parseScanOutput}=await api(),secret='SESSION_CANARY_'+ 'Z'.repeat(2200),value={site:[{'@name':'http://127.0.0.1:15000',alerts:[{pluginid:'10020',riskcode:'1',name:'Title '+secret,instances:[{uri:'http://127.0.0.1:15000/account?opaque='+encodeURIComponent(secret),method:'GET'}]}]}]};
 const result=parseScanOutput('zap',value,[secret]);assert.ok(!JSON.stringify(result).includes(secret.slice(0,80)));assert.match(result.findings[0].title,/REDACTED/);assert.match(result.findings[0].location,/REDACTED/);
});

test('Pinned ZAP scans suppress upstream addon downloads instead of changing scanner assets at runtime',async()=>{
 const {buildScanPlan}=await api(),plan=buildScanPlan('zap',{repoRoot:'/home/purge/workspace/fixture',url:'http://127.0.0.1:15000'},'/tmp/run',{tools:[{tool:'zap',imageId:'sha256:'+'a'.repeat(64)}]});
 assert.match(plan.args[plan.args.indexOf('-z')+1],/(?:^| )-silent(?: |$)/);
});

test('Public and model status expose only current private-session expiry metadata without creating audit work',async()=>{
 const {readZapAuthStatus}=await import('../package/lib/redteam/personal-security-auth.mjs'),{modelSecurityResult}=await import('../package/lib/redteam/personal-security-model.mjs'),f=await fixture();try{
  const directory=path.join(f.root,'private-auth');fs.mkdirSync(directory,{mode:0o700});const config={version:1,revision:'879b1b08-0a7d-4f84-9f1d-d50cb7f94072',origin:'http://127.0.0.1:15000',header:'Cookie',value:'sid=PRIVATE_STATUS_CANARY_123456789',verifyPath:'/account',loggedInMarker:'HARNESS_AUTHENTICATED',excludePaths:['/logout'],expiresAt:'2000-01-01T00:00:00Z'};fs.writeFileSync(path.join(directory,'local-login.json'),JSON.stringify(config),{mode:0o600});f.bench.authStatus=(name,origin)=>readZapAuthStatus(name,origin,{root:directory});f.bench.saveScope('a',f.scope({authProfile:'local-login'}));
  const value=f.bench.read('a');assert.equal(value.authSession?.state,'expired','Current status must include expiry metadata');assert.equal(value.authSession.profile,'local-login');assert.equal(value.totalRuns,0);assert.equal(f.bench.read('b').authSession,null);const model=await modelSecurityResult(f.bench,'a',{op:'securityStatus'});assert.equal(model.authSession.state,'expired');assert.ok(Buffer.byteLength(JSON.stringify(model))<=6000);for(const output of [value,model,f.bench.report('a')])assert.ok(!JSON.stringify(output).includes('PRIVATE_STATUS_CANARY'));assert.equal(f.bench.db('a').prepare('SELECT COUNT(*) n FROM security_event').get().n,1);
 }finally{await f.close()}
});
test('All scanner outputs use bounded ephemeral tmpfs and expose only read-only host inputs',async()=>{
 const {buildScanPlan}=await api(),manifest={tools:['semgrep','trivy','zap'].map(tool=>({tool,imageId:'sha256:'+'a'.repeat(64),version:'1.0.0'}))};
 for(const tool of ['semgrep','trivy','zap']){const p=buildScanPlan(tool,{repoRoot:'/home/purge/workspace/test',url:'http://127.0.0.1:18780'},'/home/purge/private-run',manifest);const out=tool==='zap'?'/zap/wrk':'/out';assert.ok(p.args.includes(out+':rw,nosuid,nodev,noexec,size=67108864,uid=1000,gid=1000,mode=0700'));assert.equal(p.args[p.args.indexOf('--log-driver')+1],'none');for(let i=0;i<p.args.length;i++)if(p.args[i]==='--mount')assert.ok(p.args[i+1].endsWith(',readonly'),p.args[i+1]);assert.equal(p.args[p.args.indexOf('--entrypoint')+1],'/bin/sh');assert.ok(p.args.includes('/policy-output.sh'));assert.equal(p.outputQuotaBytes,67108864)}
});
