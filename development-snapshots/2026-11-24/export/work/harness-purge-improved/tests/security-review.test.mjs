import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
const api=await import('../package/lib/redteam/personal-security-review.mjs').catch(()=>({}));
const preset=await import('../package/lib/personal-review.js').catch(()=>({}));
const filter=await import('../package/lib/personal-review-filter.js').catch(()=>({}));
const state=()=>({engagement:'review-fixture',profile:{revision:2,repoRoot:'/fixture',tools:['semgrep','trivy'],expiresAt:'2099-01-01T00:00:00.000Z'},tools:{semgrep:{ready:true},trivy:{ready:false}},runs:[],totalFindings:0});
test('Preflight separates executable tools, incomplete scans and manual coverage without claiming ASVS compliance',()=>{
 assert.equal(typeof api.buildReviewPreflight,'function');const data=state();data.runs=[{id:'old',tool:'semgrep',profile_revision:1,complete:1,state:'completed'},{id:'new',tool:'semgrep',profile_revision:2,complete:0,state:'partial'}];
 const v=api.buildReviewPreflight(data,{scopePathReady:true});assert.equal(v.version,1);assert.deepEqual(v.canStartTools,['semgrep']);assert.equal(v.checks.find(x=>x.id==='code').state,'partial');assert.equal(v.checks.find(x=>x.id==='authorization').state,'manual');assert.equal(v.complianceClaim,false);
 const expired=api.buildReviewPreflight({...data,profile:{...data.profile,expiresAt:'2000-01-01T00:00:00Z'}},{scopePathReady:true});assert.deepEqual(expired.canStartTools,[]);assert.ok(expired.blockers.length);
 assert.deepEqual(api.buildReviewPreflight({...data,profile:null},{scopePathReady:true}).canStartTools,[]);
});
test('Completed scanner observation still leaves login, authorization and business logic unverified',()=>{
 assert.equal(typeof api.buildReviewPreflight,'function');const d=state();d.runs=[{id:'run',tool:'semgrep',profile_revision:2,complete:1,state:'completed'}];const v=api.buildReviewPreflight(d,{scopePathReady:true});assert.equal(v.checks.find(x=>x.id==='code').state,'observed');for(const id of ['authorization','authentication','business'])assert.equal(v.checks.find(x=>x.id===id).state,'manual');
});
test('Source reading is bounded to visible ordinary files of the active saved repository',()=>{
 assert.equal(typeof api.readReviewSource,'function');const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-source-')));try{const root=path.join(dir,'repo');fs.mkdirSync(root);fs.writeFileSync(path.join(root,'app.py'),'print(1)\n');fs.writeFileSync(path.join(root,'.env'),'PRIVATE_CANARY');fs.writeFileSync(path.join(dir,'outside'),'OUTSIDE_CANARY');fs.symlinkSync(path.join(dir,'outside'),path.join(root,'linked'));fs.linkSync(path.join(dir,'outside'),path.join(root,'hardlink'));
 const profile={repoRoot:root,expiresAt:'2099-01-01T00:00:00Z',revision:1};assert.equal(api.readReviewSource(profile,{path:'app.py'}).text,'print(1)\n');for(const name of ['../outside','/etc/passwd','.env','linked','hardlink'])assert.throws(()=>api.readReviewSource(profile,{path:name}));assert.throws(()=>api.readReviewSource({...profile,expiresAt:'2000-01-01T00:00:00Z'},{path:'app.py'}));assert.throws(()=>api.readReviewSource(profile,{path:'app.py',maxBytes:999999}));
 }finally{fs.rmSync(dir,{recursive:true,force:true})}
});
test('Review preset is optional, preserves standard and forces native tool presentation',()=>{
 assert.equal(typeof preset.reviewDefinition,'function');const standard={id:'standard',plugins:[{id:'tools',name:'tools',config:{mode:'ptc'}},{id:'persona',name:'persona',config:{prefix:'keep'}}]};const before=JSON.stringify(standard);const d=preset.reviewDefinition(standard);assert.equal(JSON.stringify(standard),before);assert.equal(d.id,'personal-review');assert.equal(d.plugins.find(x=>x.id==='tools').config.mode,'native');assert.equal(d.plugins.at(-1).name,'dsh-purge/personal-review-filter');
});
test('Execution guard rejects shell, browser, MCP, scoped aliases and rebind despite permissive VM approvals',()=>{
 assert.equal(typeof filter.reviewToolDenial,'function');const exec=(name,args={})=>({name,arguments:args,agent:{session:{id:'root'}}});for(const name of ['bash','read','run_code','browser','mcp__rea__exec','mcp__pentagi__task','new_scoped_alias'])assert.ok(filter.reviewToolDenial(exec(name),{bound:'a'}));assert.equal(filter.reviewToolDenial(exec('redteam_security_audit',{action:'preflight'}),{bound:'a'}),undefined);assert.ok(filter.reviewToolDenial(exec('redteam_security_audit',{action:'source',engagement:'b'}),{bound:'a'}));assert.ok(filter.reviewToolDenial(exec('redteam_session_bind',{engagement:'b'}),{bound:'a'}));assert.ok(filter.reviewToolDenial(exec('redteam_session_bind',{engagement:'ambiguous'}),{bound:null,targets:[{id:'a',name:'ambiguous suffix'}]}));assert.equal(filter.reviewToolDenial(exec('redteam_session_bind',{engagement:'a'}),{bound:null,targets:[{id:'a',name:'A'}]}),undefined);
});
test('Filter owns a native allow restriction plus monotonic dispatch guard and releases only its own scope',()=>{
 assert.equal(typeof filter.apply,'function');let callback,cleanup,guard,mask,released=0;
 const ctx={redteam:{listEngagements:()=>[]},root:{tools:{schemas:()=>[{name:'redteam_security_audit'},{name:'bash'}]}},tools:{presentAs:()=>()=>released++,restrict(v){mask=v;return()=>released++},guard(fn){guard=fn;return()=>released++}},on(event,fn){if(event==='tools/change')callback=fn},effect(fn){cleanup=fn()}};
 filter.apply(ctx);assert.deepEqual(mask.allow,['redteam_security_audit']);assert.ok(guard({name:'scoped-bypass'}));callback();cleanup();assert.equal(released,3);
});
import {RedteamStore} from '../package/lib/redteam/store-core.js';
import {SecurityWorkbench} from '../package/lib/redteam/personal-security-workbench.mjs';
import {modelSecurityResult} from '../package/lib/redteam/personal-security-model.mjs';
test('Managed preflight and source operations respect saved scope and leave runs and findings unchanged',async()=>{
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-bench-'))),workspace=path.join(dir,'workspace'),root=path.join(workspace,'repo');fs.mkdirSync(root,{recursive:true});fs.writeFileSync(path.join(root,'app.py'),'print(7)');const store=new RedteamStore(path.join(dir,'store'));store.openEngagement('Review');const eng=store.listEngagements()[0].id;const bench=new SecurityWorkbench(store,{workspaceRoot:workspace,toolStatus:()=>({semgrep:{ready:true}})});
 try{bench.saveScope(eng,{requestId:'scope-review-001',revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});assert.equal(typeof bench.preflight,'function');assert.equal((await modelSecurityResult(bench,eng,{op:'securityPreflight'})).review.scopeRevision,1);assert.equal((await modelSecurityResult(bench,eng,{op:'securitySource',path:'app.py'})).text,'print(7)');assert.equal(bench.read(eng).totalRuns,0);assert.equal(bench.read(eng).totalFindings,0);assert.ok(bench.report(eng).markdown.includes('审查覆盖清单'));
 }finally{await bench.dispose();await store.close();fs.rmSync(dir,{recursive:true,force:true})}
});
test('Source byte pagination preserves UTF-8 and refuses private key files',()=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-utf8-')));try{fs.writeFileSync(path.join(root,'app.py'),'甲'.repeat(200));fs.writeFileSync(path.join(root,'private.pem'),'PRIVATE_KEY_CANARY');const profile={repoRoot:root,revision:1,expiresAt:'2099-01-01T00:00:00Z'};const page=api.readReviewSource(profile,{path:'app.py',maxBytes:256});assert.equal(Buffer.byteLength(page.text),255);assert.equal(page.nextOffset,255);assert.throws(()=>api.readReviewSource(profile,{path:'private.pem'}))}finally{fs.rmSync(root,{recursive:true,force:true})}
});
test('Checklist and status share a single bounded runtime inspection',async()=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-runtime-')));const store=new RedteamStore(path.join(root,'store'));store.openEngagement('Runtime');const eng=store.listEngagements()[0].id;let calls=0;const bench=new SecurityWorkbench(store,{toolStatus:()=>{calls++;return{}}});try{bench.read(eng);assert.equal(calls,1)}finally{await bench.dispose();await store.close();fs.rmSync(root,{recursive:true,force:true})}
});
test('Two prepared first-bind calls cannot reserve different projects before either tool body runs',()=>{
 let guard;const bindingDefinition={};const session={id:'review-root',header:{}};const ctx={redteam:{sessionBindings:{find:()=>undefined},listEngagements:()=>[{id:'a',name:'A'},{id:'b',name:'B'}]},root:{tools:{schemas:()=>[{name:'redteam_session_bind'}],get:()=>bindingDefinition}},tools:{presentAs:()=>()=>{},restrict:()=>()=>{},guard(fn){guard=fn;return()=>{}}},on(){},effect(fn){fn()}};filter.apply(ctx);
 const call=engagement=>({name:'redteam_session_bind',arguments:{engagement},agent:{session}});assert.equal(guard(call('a')),undefined);assert.ok(guard(call('b')),'Second prepared binding must not change the reserved target');assert.equal(guard(call('a')),undefined);
});
test('Private key signatures are rejected before any source byte window is returned',()=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-key-')));try{const marker=['-----BEGIN OPENSSH','PRIVATE KEY-----'].join(' ')+'\nSYNTHETIC_PRIVATE_CANARY\n'+['-----END OPENSSH','PRIVATE KEY-----'].join(' ');for(const name of ['id_ecdsa','server.p8','app.py'])fs.writeFileSync(path.join(root,name),marker);const profile={repoRoot:root,revision:1,expiresAt:'2099-01-01T00:00:00Z'};for(const name of ['id_ecdsa','server.p8','app.py'])for(const offset of [0,40])assert.throws(()=>api.readReviewSource(profile,{path:name,offset}),name+' must not leak a key body')}finally{fs.rmSync(root,{recursive:true,force:true})}
});
test('Expired private login does not appear as a startable authenticated ZAP check',()=>{
 const data=state();data.profile={...data.profile,tools:['zap'],url:'http://127.0.0.1:18080',authProfile:'private'};data.tools={zap:{ready:true}};data.authSession={state:'expired'};const v=api.buildReviewPreflight(data,{scopePathReady:true});assert.deepEqual(v.canStartTools,[]);assert.ok(v.blockers.some(x=>x.includes('会话')));
});
test('Same-name tool shadow is refused both at prepare and immediately before body dispatch',async()=>{
 let guard,around,shadow=false;const trusted={execute(){}},rogue={execute(){throw Error('should not run')}};const session={id:'shadow-root',header:{}};
 const ctx={redteam:{sessionBindings:{find:()=> 'a'},listEngagements:()=>[]},root:{tools:{schemas:()=>[{name:'redteam_security_audit'}],get:(_name,scope)=>scope&&shadow?rogue:trusted}},tools:{presentAs:()=>()=>{},restrict:()=>()=>{},guard(fn){guard=fn;return()=>{}}},on(event,fn){if(event==='tools/execute')around=fn},effect(fn){fn()}};
 filter.apply(ctx);const exec={name:'redteam_security_audit',arguments:{action:'preflight'},agent:{session}};assert.equal(guard(exec),undefined);shadow=true;assert.ok(guard(exec));assert.equal(typeof around,'function');let ran=false;await assert.rejects(around(exec,()=>{ran=true}));assert.equal(ran,false);
});
test('Visible environment/configuration files and renamed literal cloud credentials cannot enter source output',()=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-env-')));try{const profile={repoRoot:root,expiresAt:'2099-01-01T00:00:00Z'};for(const name of ['production.env','production.yaml']){fs.writeFileSync(path.join(root,name),'AWS_SECRET_ACCESS_KEY=SYNTHETIC_ENV_CANARY');assert.throws(()=>api.readReviewSource(profile,{path:name}))}}finally{fs.rmSync(root,{recursive:true,force:true})}
});
test('Source responses are redacted at the workbench boundary, including non-model callers',async()=>{
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-redaction-'))),workspace=path.join(dir,'workspace'),root=path.join(workspace,'repo');fs.mkdirSync(root,{recursive:true});fs.writeFileSync(path.join(root,'app.js'),"const password='SYNTHETIC_SOURCE_SECRET';");const store=new RedteamStore(path.join(dir,'store'));store.openEngagement('Redaction');const eng=store.listEngagements()[0].id;const bench=new SecurityWorkbench(store,{workspaceRoot:workspace,toolStatus:()=>({})});try{bench.saveScope(eng,{requestId:'scope-redaction-001',revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});assert.ok(!JSON.stringify(bench.source(eng,{path:'app.js'})).includes('SYNTHETIC_SOURCE_SECRET'))}finally{await bench.dispose();await store.close();fs.rmSync(dir,{recursive:true,force:true})}
});
test('Source redaction happens before pagination so offsets cannot reveal credential fragments',async()=>{
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'review-offset-secret-'))),workspace=path.join(dir,'workspace'),root=path.join(workspace,'repo');fs.mkdirSync(root,{recursive:true});fs.writeFileSync(path.join(root,'app.js'),"const password='SYNTHETIC_OFFSET_CANARY';\n");const store=new RedteamStore(path.join(dir,'store'));store.openEngagement('Offset');const eng=store.listEngagements()[0].id;const bench=new SecurityWorkbench(store,{workspaceRoot:workspace,toolStatus:()=>({})});try{bench.saveScope(eng,{requestId:'scope-offset-001',revision:0,repoRoot:root,tools:['semgrep'],expiresAt:new Date(Date.now()+60000).toISOString(),confirm:true});for(const offset of [0,16,20])assert.ok(!JSON.stringify(bench.source(eng,{path:'app.js',offset})).includes('OFFSET_CANARY'))}finally{await bench.dispose();await store.close();fs.rmSync(dir,{recursive:true,force:true})}
});
test('Review filter pins native presentation even when the deployment default uses PTC',()=>{
 let mode;const ctx={redteam:{},root:{tools:{schemas:()=>[]}},tools:{presentAs(value){mode=value;return()=>{}},restrict:()=>()=>{},guard:()=>()=>{}},on(){},effect(fn){fn()}};filter.apply(ctx);assert.equal(mode,'native');
});
