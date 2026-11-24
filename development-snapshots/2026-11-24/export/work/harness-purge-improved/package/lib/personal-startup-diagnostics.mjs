import fs from 'node:fs';import path from 'node:path';import {randomBytes} from 'node:crypto';import {homedir} from 'node:os';
import {authenticatedWebServer} from './personal-http-auth.mjs';
const codes=['script-error','style-error','module-error','runtime-error','rejection','empty-root','mounted'];
const keys=['page','sequence','code','elapsedMs','ready','visible','rootChildren','resource'];
function validEvent(e){
 if(!e||typeof e!=='object'||Array.isArray(e)||Object.keys(e).sort().join()!==keys.slice().sort().join()||typeof e.page!=='string'||!/^[a-f0-9]{32}$/.test(e.page)||!Number.isSafeInteger(e.sequence)||e.sequence<1||e.sequence>12||!codes.includes(e.code)||!Number.isSafeInteger(e.elapsedMs)||e.elapsedMs<0||e.elapsedMs>3600000||!['loading','interactive','complete'].includes(e.ready)||typeof e.visible!=='boolean'||![0,1].includes(e.rootChildren))throw Error('Invalid startup event');
 const r=e.resource;if(r!==null&&(!r||Object.keys(r).sort().join()!=='category,hash,status'||!['assets','plugins','other'].includes(r.category)||r.hash!==null&&(typeof r.hash!=='string'||!/^[a-f0-9]{64}$/.test(r.hash))||!Number.isSafeInteger(r.status)||r.status<0||r.status>599))throw Error('Invalid resource identity');return e;
}
export function createStartupJournal(root){
 const file=path.join(root,'startup.json'),empty=()=>({version:1,firstFailure:null,episodes:[],evictedEpisodes:0});
 const read=()=>{
  if(!fs.existsSync(file)){if(fs.lstatSync(path.dirname(root),{throwIfNoEntry:false})?.isSymbolicLink()||fs.lstatSync(root,{throwIfNoEntry:false})?.isSymbolicLink()||fs.lstatSync(file,{throwIfNoEntry:false}))throw Error('Startup path changed');return empty()}
  if(fs.realpathSync(file)!==file)throw Error('Startup path changed');const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  try{const st=fs.fstatSync(fd);if(!st.isFile()||st.nlink!==1||st.uid!==process.getuid()||st.mode&0o077||st.size>131072)throw Error('Startup storage changed');const v=JSON.parse(fs.readFileSync(fd,'utf8'));if(v.version!==1||!Array.isArray(v.episodes)||v.episodes.length>30||!Number.isSafeInteger(v.evictedEpisodes)||v.evictedEpisodes<0)throw Error('Invalid startup storage');
   const check=e=>{const {observedAt,...event}=e;validEvent(event);if(!/^\d{4}-\d{2}-\d{2}T[0-9:.]+Z$/.test(observedAt))throw Error('Invalid event time')};if(v.firstFailure)check(v.firstFailure);for(const p of v.episodes){if(!/^[a-f0-9]{32}$/.test(p.page)||!Array.isArray(p.events)||p.events.length>12)throw Error('Invalid startup episode');p.events.forEach(check)}return v;
  }finally{fs.closeSync(fd)}
 };
 return{snapshot:read,record(input){const e=validEvent(input),v=read();let p=v.episodes.find(p=>p.page===e.page);if(p?.events.some(x=>x.sequence===e.sequence))return{accepted:false};if(!p){p={page:e.page,events:[]};v.episodes.push(p)}const item={...e,observedAt:new Date().toISOString()};p.events.push(item);p.events.sort((a,b)=>a.sequence-b.sequence);if(p.events.length>12)p.events.splice(1,1);if(e.code!=='mounted'&&!v.firstFailure)v.firstFailure=item;
  while(v.episodes.length>30){v.episodes.splice(v.episodes[0].page===v.firstFailure?.page?1:0,1);v.evictedEpisodes++}
  fs.mkdirSync(root,{recursive:true,mode:0o700});if(fs.realpathSync(root)!==root)throw Error('Startup root changed');const raw=JSON.stringify(v);if(Buffer.byteLength(raw)>131072)throw Error('Startup journal full');const tmp=path.join(root,'.startup-'+randomBytes(8).toString('hex'));let fd;
  try{fd=fs.openSync(tmp,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);fs.writeFileSync(fd,raw);fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,file)}finally{if(fd!==undefined)fs.closeSync(fd);fs.rmSync(tmp,{force:true})}return{accepted:true};}};
}
export function installStartupDiagnostics(ctx,{root=path.join(homedir(),'.dsh-improved/diagnostics'),enabled=process.platform==='linux'&&homedir()==='/home/purge'&&process.env.DSH_HOME==='/home/purge/.dsh-improved'}={}){
 if(!enabled||typeof ctx.inject!=='function')return;
 ctx.inject(['webServer','connection'],host=>{const journal=createStartupJournal(root);return authenticatedWebServer(host,host.webServer).register({kind:'exact',path:'/dsh-purge/startup-diagnostics',handler:async(req,res)=>{
  const send=(status,value)=>{res.writeHead(status,{'cache-control':'no-store','content-type':'application/json; charset=utf-8'});res.end(JSON.stringify(value))};
  if(!['GET','POST'].includes(req.method)){send(405,{ok:false,error:'GET or POST required'});return}
  if(req.method==='POST'&&(req.headers['x-dsh-startup']!=='1'||req.headers['content-type']!=='application/json'||!req.headers.origin||req.headers.origin!=='http://'+req.headers.host)){send(403,{ok:false,error:'Same-origin diagnostic request required'});return}
  try{
   if(req.method==='GET'){send(200,{ok:true,...journal.snapshot(),scope:'Browser startup observations, not a complete HTTP trace; no URLs, messages, stack, tokens or source content retained'});return}
   let raw='';for await(const chunk of req){raw+=chunk.toString();if(Buffer.byteLength(raw)>2048){send(413,{ok:false,error:'Diagnostic event too large'});return}}send(200,{ok:true,...journal.record(JSON.parse(raw))});
  }catch{send(400,{ok:false,error:'Startup event or storage unavailable; no raw diagnostic data returned'})}
 }},'dsh-purge: private startup diagnostics')});
}
