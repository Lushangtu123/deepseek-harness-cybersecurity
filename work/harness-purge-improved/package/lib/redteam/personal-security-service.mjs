import net from 'node:net';
import {lstatSync} from 'node:fs';
import {randomUUID} from 'node:crypto';

export const SECURITY_SOCKET='/run/user/1000/harness-security.sock';
const OPS=new Set(['securityStatus','securityScopeSave','securityStart','securityCancel','securityReview','securityReport','securityCompare','securityWait','securityPreflight','securitySource','securityKaliCheck','securityJoint']);
const MAX_REQUEST=65536,MAX_RESPONSE=32*1024*1024;
const unavailable=()=>Error('安全审计后台服务不可用或响应未确认；请重新读取状态，启动请求必须保留原requestId，不会自动重发');
const STAGES=new Set(['socket','encode','connect','wait','response','dispatch','complete']);
const CODES=new Set(['RPC_OK','RPC_SOCKET_INVALID','RPC_REQUEST_ENCODING','RPC_REQUEST_LIMIT','RPC_CONNECT_FAILED','RPC_TIMEOUT','RPC_CLOSED','RPC_INVALID_RESPONSE','RPC_RESPONSE_LIMIT','RPC_REJECTED','RPC_DISPATCH_FAILED','RPC_RESPONSE_ENCODING']);
const reference=value=>'；参考号 '+value.requestId+' · '+value.stage+' / '+value.code;
const trace=(requestId,operation,stage,code,started)=>({requestId,operation:OPS.has(operation)?operation:'unknown',stage,code,elapsedMs:Math.min(86400000,Math.max(0,Math.round(performance.now()-started)))});
const validTrace=value=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')==='code,elapsedMs,operation,requestId,stage'&&typeof value.requestId==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.requestId)&&(OPS.has(value.operation)||value.operation==='unknown')&&STAGES.has(value.stage)&&CODES.has(value.code)&&Number.isSafeInteger(value.elapsedMs)&&value.elapsedMs>=0&&value.elapsedMs<=86400000;

export function reconcileSecurityProjects(store,bench){
 const result={checkedProjects:0,failedProjects:0};
 let projects;try{projects=store.listEngagements()}catch{return{...result,listingUnavailable:true}}
 for(const project of projects){result.checkedProjects++;try{bench.db(project.id)}catch{result.failedProjects++}}
 return result;
}

export function requestSecurityService(request,{model=false,socketPath=SECURITY_SOCKET,timeoutMs=45000}={}){
 return new Promise((resolve,reject)=>{
  let client,timer,done=false,raw=Buffer.alloc(0),stage='socket';const id=randomUUID(),started=performance.now();
  const finish=(error,value)=>{if(done)return;done=true;clearTimeout(timer);client?.destroy();error?reject(error):resolve(value)};
  const failed=(at,code)=>{const diagnostic=trace(id,request?.op,at,code,started),error=unavailable();error.diagnostic=diagnostic;error.message+=reference(diagnostic);finish(error)};
  try{
   const info=lstatSync(socketPath);
   if(!info.isSocket()||info.isSymbolicLink()||info.uid!==process.getuid()||info.mode&0o077){failed('socket','RPC_SOCKET_INVALID');return}
   stage='encode';const payload=Buffer.from(JSON.stringify({id,request,model})+'\n');if(payload.length>MAX_REQUEST){failed('encode','RPC_REQUEST_LIMIT');return}
   stage='connect';client=net.createConnection(socketPath);timer=setTimeout(()=>failed('wait','RPC_TIMEOUT'),timeoutMs);
   client.once('connect',()=>{stage='wait';client.write(payload)});
   client.on('data',chunk=>{
    if(raw.length+chunk.length>MAX_RESPONSE){failed('response','RPC_RESPONSE_LIMIT');return}raw=Buffer.concat([raw,chunk]);
    const line=raw.indexOf(10);if(line<0)return;
    try{const envelope=JSON.parse(raw.subarray(0,line).toString());if(envelope?.id!==id||!envelope.result||typeof envelope.result!=='object'||typeof envelope.result.ok!=='boolean'||envelope.result.diagnostic!==undefined&&(!validTrace(envelope.result.diagnostic)||envelope.result.diagnostic.requestId!==id||envelope.result.diagnostic.operation!==request.op))throw unavailable();finish(null,envelope.result)}catch{failed('response','RPC_INVALID_RESPONSE')}
   });
   client.once('error',()=>failed(stage,stage==='connect'?'RPC_CONNECT_FAILED':'RPC_CLOSED'));client.once('close',()=>{if(!done)failed(stage,'RPC_CLOSED')});
  }catch{failed(stage,stage==='socket'?'RPC_SOCKET_INVALID':stage==='encode'?'RPC_REQUEST_ENCODING':'RPC_CONNECT_FAILED')}
 });
}

export function createSecurityServer({dispatch,observe=()=>{}}){
 const sockets=new Set();let stopping=false;
 const observed=value=>{try{observe(value)}catch{}};
 const server=net.createServer(client=>{
  sockets.add(client);client.once('close',()=>sockets.delete(client));client.on('error',()=>{});let raw=Buffer.alloc(0),accepted=false;
  const deadline=setTimeout(()=>client.destroy(),45000);client.once('close',()=>clearTimeout(deadline));client.setTimeout(5000,()=>{if(!accepted)client.destroy()});
  client.on('data',async chunk=>{
   if(accepted||stopping){client.destroy();return}
   if(raw.length+chunk.length>MAX_REQUEST){client.destroy();return}raw=Buffer.concat([raw,chunk]);const line=raw.indexOf(10);if(line<0)return;accepted=true;client.setTimeout(0);
   let envelope;
   try{envelope=JSON.parse(raw.subarray(0,line).toString());if(!envelope||Object.keys(envelope).sort().join(',')!=='id,model,request'||typeof envelope.id!=='string'||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(envelope.id)||typeof envelope.model!=='boolean'||!envelope.request||typeof envelope.request!=='object'||Array.isArray(envelope.request)||!OPS.has(envelope.request.op)||line!==raw.length-1)throw Error()}catch{client.destroy();return}
   const started=performance.now();let result,diagnostic;
   const rejected=(stage,code,message)=>{diagnostic=trace(envelope.id,envelope.request.op,stage,code,started);return{ok:false,error:message+reference(diagnostic),diagnostic}};
   try{result=await dispatch(envelope.request,{model:envelope.model});if(!result||typeof result.ok!=='boolean')throw Error();if(!result.ok)result={...result,...rejected('dispatch','RPC_REJECTED',typeof result.error==='string'?result.error.slice(0,300):'安全审计操作已拒绝')}}catch{result=rejected('dispatch','RPC_DISPATCH_FAILED','安全审计后台操作未完成，请核对任务状态')}
   let reply;
   try{reply=JSON.stringify({id:envelope.id,result})+'\n'}catch{result=rejected('encode','RPC_RESPONSE_ENCODING','后台回执无法编码，结果未确认，请核对任务状态');reply=JSON.stringify({id:envelope.id,result})+'\n'}
   if(Buffer.byteLength(reply)>MAX_RESPONSE){result=rejected('encode','RPC_RESPONSE_LIMIT','后台结果超过传输上限，请使用模型分页读取');reply=JSON.stringify({id:envelope.id,result})+'\n'}
   if(diagnostic||['securityStart','securityCancel','securityScopeSave','securityReview'].includes(envelope.request.op))observed(diagnostic??trace(envelope.id,envelope.request.op,'complete','RPC_OK',started));
   if(!client.destroyed)client.end(reply);
  });
 });
 server.maxConnections=16;
 server.shutdown=async()=>{stopping=true;for(const socket of sockets)socket.destroy();if(server.listening)await new Promise(resolve=>server.close(resolve))};
 return server;
}
