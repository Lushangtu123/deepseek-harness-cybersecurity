import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {spawnSync} from 'node:child_process';import {fileURLToPath} from 'node:url';import {createHash} from 'node:crypto'
import {RedteamStore} from '../package/lib/redteam/store-core.js'
const cli=fileURLToPath(new URL('../package/scripts/export-engagement-report.mjs',import.meta.url)),sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex')
function setup(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'safe-report-export-')),root=path.join(dir,'data'),store=new RedteamStore(root);t.after(()=>{store.close();fs.rmSync(dir,{recursive:true,force:true})});return{dir,root,store}}
function project(f,name='owned'){const id=f.store.openEngagement(name,[],{bindCurrent:false}).id,p=f.store.saveScorePoint(id,{code:'owned',name:'owned',points:1}),hit=f.store.addScoreHit(id,{point_id:p.id,target:'owned.invalid',evidence:'owned'}),shot=f.store.addShot(id,{point_id:p.id,hit_id:hit.id,file:'proof.png',data_base64:Buffer.from('OWNED_SYNTHETIC_'+name).toString('base64')});return{id,point:p,hit,shot,file:path.join(f.store.shotsDirOf(id),shot.file)}}
function run(f,id,out,timeout=20000){return spawnSync(process.execPath,[cli,'--engagement',id,'--out',out],{cwd:f.dir,env:{...process.env,REDTEAM_HOME:f.root,DSH_HOME:path.join(f.dir,'dsh')},encoding:'utf8',timeout})}
function bundles(parent){return fs.readdirSync(parent).filter(x=>fs.statSync(path.join(parent,x)).isDirectory()&&fs.existsSync(path.join(parent,x,'bundle/manifest.json'))).map(x=>path.join(parent,x,'bundle'))}
test('Repeated project exports keep prior packages and copy only referenced attachments',t=>{const f=setup(t),a=project(f,'A'),b=project(f,'B'),out=path.join(f.dir,'out');fs.mkdirSync(path.join(out,'shots'),{recursive:true});fs.writeFileSync(path.join(out,'shots/previous.png'),'OWNED_KEEP')
  fs.writeFileSync(path.join(f.store.shotsDirOf(a.id),'unregistered.png'),'OWNED_EXCLUDED')
  for(const p of [a,b])assert.equal(run(f,p.id,out).status,0)
  assert.equal(fs.readFileSync(path.join(out,'shots/previous.png'),'utf8'),'OWNED_KEEP')
  const all=bundles(out);assert.equal(all.length,2)
  for(const bundle of all){const m=JSON.parse(fs.readFileSync(path.join(bundle,'manifest.json'),'utf8'));assert.equal(m.attachments.length,1);assert.equal(sha(path.join(bundle,m.report.path)),m.report.sha256);const img=m.attachments[0];assert.equal(sha(path.join(bundle,img.path)),img.sha256);assert.deepEqual(fs.readdirSync(path.join(bundle,'shots')),['proof.png'])}
})
for(const kind of ['same','descendant','ancestor','symlink'])test('Export refuses '+kind+' overlap before touching source evidence',t=>{const f=setup(t),p=project(f),before=sha(p.file);let out=kind==='same'?f.store.dirOf(p.id):kind==='descendant'?path.join(f.store.dirOf(p.id),'export'):f.dir
 if(kind==='symlink'){out=path.join(f.dir,'alias');fs.symlinkSync(f.store.dirOf(p.id),out)}
 const r=run(f,p.id,out);assert.notEqual(r.status,0);assert.equal(sha(p.file),before);assert.doesNotMatch(r.stdout,/✓/)
})
for(const kind of ['missing','changed','symlink'])test('Referenced '+kind+' attachment prevents publication and preserves old output',t=>{const f=setup(t),p=project(f),out=path.join(f.dir,'out');fs.mkdirSync(out);fs.writeFileSync(path.join(out,'keep.txt'),'OWNED_KEEP')
 if(kind==='missing')fs.unlinkSync(p.file);if(kind==='changed')fs.appendFileSync(p.file,'OWNED_CHANGED');if(kind==='symlink'){const other=path.join(f.dir,'other');fs.copyFileSync(p.file,other);fs.unlinkSync(p.file);fs.symlinkSync(other,p.file)}
 const r=run(f,p.id,out);assert.notEqual(r.status,0);assert.doesNotMatch(r.stdout,/✓/);assert.deepEqual(fs.readdirSync(out),['keep.txt'])
})
test('Invalid project cannot modify an existing destination',t=>{const f=setup(t),out=path.join(f.dir,'out');fs.mkdirSync(path.join(out,'shots'),{recursive:true});fs.writeFileSync(path.join(out,'shots/keep'),'OWNED_KEEP');fs.mkdirSync(path.join(f.root,'engagements/invalid/shots'),{recursive:true});fs.writeFileSync(path.join(f.root,'engagements/invalid/shots/new'),'OWNED_NEW');assert.notEqual(run(f,'invalid',out).status,0);assert.deepEqual(fs.readdirSync(path.join(out,'shots')),['keep'])})
test('Structured report attachment list covers full Markdown even when details are paged',t=>{const f=setup(t),p=project(f);const report=f.store.scoreReport(p.id,{shotRef:'relative',limit:1,offset:1});assert.equal(report.items.length,0);assert.equal(report.attachments.length,1);assert.equal(report.attachments[0].sha256,p.shot.sha256);assert.equal(report.attachments[0].path,'shots/proof.png');assert.ok(report.markdown.includes('shots/proof.png'))})

// Exercise real failure points without adding test switches to the CLI.
const { exportReport } = await import('../package/scripts/export-engagement-report.mjs')
const { syncBuiltinESMExports } = await import('node:module')
for (const phase of ['write', 'rename', 'after-publication']) test('Export handles '+phase+' failure without replacing old deliveries', t => {
  const f=setup(t),p=project(f),out=path.join(f.dir,'out');fs.mkdirSync(out);fs.writeFileSync(path.join(out,'keep'),'OWNED_KEEP')
  const original={writeFileSync:fs.writeFileSync,renameSync:fs.renameSync,fsyncSync:fs.fsyncSync};let fired=false,published=false
  fs.writeFileSync=function(file,...args){if(phase==='write'&&typeof file==='number'&&!fired){fired=true;throw new Error('OWNED_INJECTED_WRITE')}return original.writeFileSync.call(fs,file,...args)}
  fs.renameSync=function(a,b){if(String(a).includes('.staging')){if(phase==='rename'){fired=true;throw new Error('OWNED_INJECTED_RENAME')}original.renameSync(a,b);published=true;return}return original.renameSync(a,b)}
  fs.fsyncSync=function(fd){if(phase==='after-publication'&&published){fired=true;throw new Error('OWNED_INJECTED_SYNC')}return original.fsyncSync(fd)}
  syncBuiltinESMExports()
  try{assert.throws(()=>exportReport({root:f.root,engagement:p.id,out}),/OWNED_INJECTED/)}finally{Object.assign(fs,original);syncBuiltinESMExports()}
  assert.equal(fired,true);assert.equal(fs.readFileSync(path.join(out,'keep'),'utf8'),'OWNED_KEEP')
  if(phase==='after-publication'){assert.equal(bundles(out).length,1);assert.equal(fs.existsSync(path.join(path.dirname(bundles(out)[0]),'.staging')),false)}else assert.deepEqual(fs.readdirSync(out),['keep'])
})
test('Attachment names with spaces and parentheses remain portable and unreferenced records stay out',t=>{
  const f=setup(t),p=project(f),name='owned ) proof.png';const sh=f.store.addShot(p.id,{point_id:p.point.id,hit_id:p.hit.id,file:name,data_base64:Buffer.from('OWNED_OTHER').toString('base64')})
  const disabled=f.store.saveScorePoint(p.id,{code:'disabled',name:'disabled',points:1,enabled:0});f.store.addShot(p.id,{point_id:disabled.id,file:'disabled.png',data_base64:Buffer.from('OWNED_DISABLED').toString('base64')})
  const out=path.join(f.dir,'out');assert.equal(run(f,p.id,out).status,0);const bundle=bundles(out)[0],m=JSON.parse(fs.readFileSync(path.join(bundle,'manifest.json'))),md=fs.readFileSync(path.join(bundle,'report.md'),'utf8')
  assert.equal(m.attachments.some(x=>x.path==='shots/'+sh.file),true);assert.equal(md.includes('shots/owned%20%29%20proof.png'),true);assert.equal(m.attachments.some(x=>x.path.includes('disabled')),false)
})
test('Missing registered hash and equal-length tampering both fail closed',t=>{
 const f=setup(t),p=project(f),out=path.join(f.dir,'out');fs.mkdirSync(out);const bytes=fs.readFileSync(p.file);bytes[0]^=1;fs.writeFileSync(p.file,bytes)
 assert.notEqual(run(f,p.id,out).status,0);fs.writeFileSync(p.file,Buffer.from('OWNED_SYNTHETIC_owned'));f.store.db(p.id).prepare('UPDATE shot SET sha256=? WHERE id=?').run('',p.shot.id)
 assert.notEqual(run(f,p.id,out).status,0);assert.deepEqual(fs.readdirSync(out),[])
})
test('A named pipe cannot stall attachment validation before its file-type check',t=>{
 const f=setup(t),p=project(f),out=path.join(f.dir,'out');fs.mkdirSync(out);fs.unlinkSync(p.file)
 const fifo=spawnSync('/usr/bin/mkfifo',[p.file],{encoding:'utf8'});assert.equal(fifo.status,0,fifo.stderr)
 const r=run(f,p.id,out,1500);assert.equal(r.error,undefined);assert.equal(r.signal,null);assert.notEqual(r.status,0);assert.doesNotMatch(r.stdout,/✓/);assert.deepEqual(fs.readdirSync(out),[])
})
