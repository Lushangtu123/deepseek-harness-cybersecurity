import {randomUUID} from 'node:crypto';
import {request as httpRequest} from 'node:http';
import {constants,openSync,closeSync,fstatSync,readSync,lstatSync,realpathSync,writeFileSync,fsyncSync,unlinkSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {homedir} from 'node:os';

const ROOT=join(homedir(),'.dsh-improved','security-auth');
const rejected=()=>Object.assign(Error('私有认证配置不可用、已过期或与当前本地范围不匹配'),{code:'AUTH_PROFILE'});
const slug=value=>typeof value==='string'&&/^[a-z][a-z0-9_-]{0,47}$/.test(value);
const localOrigin=value=>{
 try{const url=new URL(value);return url.origin===value&&url.hostname==='127.0.0.1'&&url.protocol==='http:'&&Number(url.port)>=1024&&![3080,18443,49222,49223,49224,49226,49090].includes(Number(url.port))}catch{return false}
};
const localPath=value=>typeof value==='string'&&/^\/[A-Za-z0-9._~/-]{0,299}$/.test(value)&&!value.includes('//')&&!value.split('/').some(part=>part==='.'||part==='..');
const record=value=>value&&typeof value==='object'&&!Array.isArray(value);

function validateProfile(value,origin,current,allowExpired=false){
  const keys=['version','revision','origin','header','value','verifyPath','loggedInMarker','excludePaths','expiresAt'];
  if(!record(value)||Object.keys(value).sort().join(',')!==keys.sort().join(',')||value.version!==1||typeof value.revision!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value.revision)||value.origin!==origin)throw rejected();
  if(!['Cookie','Authorization'].includes(value.header)||typeof value.value!=='string'||value.value.length>4096)throw rejected();
  const credential=value.header==='Cookie'?value.value.match(/^[!#$%&'*+.^_`|~0-9A-Za-z-]+=([A-Za-z0-9._~+/=-]{16,4096})$/):value.value.match(/^Bearer ([A-Za-z0-9._~+/=-]{16,4096})$/);
  if(!credential||!localPath(value.verifyPath)||typeof value.loggedInMarker!=='string'||!value.loggedInMarker.length||value.loggedInMarker.length>128||/[\x00-\x1f\x7f]/.test(value.loggedInMarker)||!Array.isArray(value.excludePaths)||value.excludePaths.length>10||value.excludePaths.some(path=>!localPath(path)||path==='/'||value.verifyPath===path.replace(/\/+$/,'')||value.verifyPath.startsWith(path.replace(/\/+$/,'')+'/')))throw rejected();
  const expiry=Date.parse(value.expiresAt);if(typeof value.expiresAt!=='string'||!Number.isFinite(expiry)||!Number.isFinite(current)||!allowExpired&&expiry<=current||expiry>current+31*86400000)throw rejected();
  return{...value,expiresAt:new Date(expiry).toISOString(),excludePaths:value.excludePaths.map(path=>path.replace(/\/+$/,'')),secretValues:[value.value,credential[1]]};
}

function readProfile(reference,origin,{root,now,allowExpired=false}){
 let fd;
 try{
  if(!slug(reference)||!localOrigin(origin))throw rejected();
  const directory=resolve(root),parent=lstatSync(directory);
  if(!parent.isDirectory()||parent.isSymbolicLink()||parent.uid!==process.getuid()||parent.mode&0o077||realpathSync(directory)!==directory)throw rejected();
  fd=openSync(join(directory,reference+'.json'),constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
  const info=fstatSync(fd);if(!info.isFile()||info.uid!==process.getuid()||info.mode&0o077||info.nlink!==1||info.size>8192)throw rejected();
  const buffer=Buffer.alloc(8193),length=readSync(fd,buffer,0,buffer.length,0);if(!length||length>8192)throw rejected();
  const value=JSON.parse(buffer.subarray(0,length).toString('utf8'));
  return validateProfile(value,origin,now(),allowExpired);
 }catch{throw rejected()}
 finally{if(fd!==undefined)closeSync(fd)}
}

export function readZapAuthProfile(reference,origin,{root=ROOT,now=Date.now}={}){
 return readProfile(reference,origin,{root,now});
}
export function readZapAuthStatus(reference,origin,{root=ROOT,now=Date.now}={}){
 const current=now(),checkedAt=new Date(Number.isFinite(current)?current:Date.now()).toISOString();
 try{
  const auth=readProfile(reference,origin,{root,now:()=>current,allowExpired:true}),remaining=Date.parse(auth.expiresAt)-current;
  return{version:1,profile:reference,revision:auth.revision,state:remaining<=0?'expired':remaining<=300000?'expiring':'ready',expiresAt:auth.expiresAt,checkedAt};
 }catch{return{version:1,profile:slug(reference)?reference:null,revision:null,state:'unavailable',expiresAt:null,checkedAt}}
}

const renewalRejected=()=>Object.assign(Error('重新导入未完成；请核对原配置版本、确认项和未使用的新名称'),{code:'AUTH_RENEW'});
export function renewZapAuthProfile(request,input,{root=ROOT,now=Date.now}={}){
 let fd,path,created;
 try{
  if(!record(request)||Object.keys(request).sort().join(',')!==['from','to','origin','expectedRevision','confirm'].sort().join(',')||!slug(request.from)||!slug(request.to)||request.from===request.to||request.confirm!==true||!record(input)||Object.keys(input).sort().join(',')!=='expiresAt,value')throw renewalRejected();
  const current=now(),original=readProfile(request.from,request.origin,{root,now:()=>current,allowExpired:true});
  if(request.expectedRevision!==original.revision)throw renewalRejected();
  if(original.header==='Cookie'&&(typeof input.value!=='string'||input.value.split('=',1)[0]!==original.value.split('=',1)[0]))throw renewalRejected();
  const {secretValues,...policy}=original,updated=validateProfile({...policy,revision:randomUUID(),value:input.value,expiresAt:input.expiresAt},request.origin,current);
  const {secretValues:ignored,...config}=updated,raw=JSON.stringify(config);if(Buffer.byteLength(raw)>8192)throw renewalRejected();
  const directory=resolve(root),info=lstatSync(directory);if(!info.isDirectory()||info.isSymbolicLink()||info.uid!==process.getuid()||info.mode&0o077||realpathSync(directory)!==directory)throw renewalRejected();
  path=join(directory,request.to+'.json');fd=openSync(path,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600);created=fstatSync(fd);writeFileSync(fd,raw);fsyncSync(fd);closeSync(fd);fd=undefined;
  return{version:1,profile:request.to,revision:config.revision,state:Date.parse(config.expiresAt)-current<=300000?'expiring':'ready',expiresAt:config.expiresAt,checkedAt:new Date(current).toISOString()};
 }catch{
  if(created)try{const info=lstatSync(path);if(!info.isSymbolicLink()&&info.dev===created.dev&&info.ino===created.ino)unlinkSync(path)}catch{}
  throw renewalRejected();
 }finally{if(fd!==undefined)closeSync(fd)}
}

const verificationFailed=()=>Object.assign(Error('登录状态未确认；检查私有会话、校验页面及到期时间'),{code:'AUTH_VERIFY'});
function probeSession(auth,authenticated,{signal,deadline}){
 return new Promise((resolveProbe,reject)=>{
  let req,timer,settled=false;
  const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);if(error){req?.destroy();reject(error)}else resolveProbe(value)};
  const abort=()=>finish(Object.assign(Error('认证核对已取消'),{name:'AbortError'}));
  if(signal?.aborted){abort();return}
  const remaining=deadline-performance.now();if(remaining<=0){finish(verificationFailed());return}
  timer=setTimeout(()=>finish(verificationFailed()),remaining);signal?.addEventListener('abort',abort,{once:true});
  try{
   const url=new URL(auth.origin),headers={Accept:'text/html,text/plain',Connection:'close',...(authenticated?{[auth.header]:auth.value}:{})};
   req=httpRequest({hostname:'127.0.0.1',port:Number(url.port),path:auth.verifyPath,method:'GET',agent:false,headers},response=>{
    let bytes=0,chunks=[];
    response.on('data',chunk=>{bytes+=chunk.length;if(bytes>65536){finish(verificationFailed());response.destroy()}else chunks.push(chunk)});
    response.once('error',()=>finish(verificationFailed()));
    response.once('end',()=>finish(null,response.statusCode===200&&Buffer.concat(chunks).toString('utf8').includes(auth.loggedInMarker)));
   });
   req.once('error',()=>finish(verificationFailed()));req.end();
  }catch{finish(verificationFailed())}
 });
}
export async function verifyZapSession(auth,{signal,timeoutMs=3000}={}){
 if(!auth||!localOrigin(auth.origin)||!localPath(auth.verifyPath)||!['Cookie','Authorization'].includes(auth.header)||typeof auth.value!=='string'||/[\r\n]/.test(auth.value)||typeof auth.loggedInMarker!=='string'||!auth.loggedInMarker||!Number.isFinite(Date.parse(auth.expiresAt))||Date.parse(auth.expiresAt)<=Date.now())throw rejected();
 if(!Number.isFinite(timeoutMs)||timeoutMs<=0||timeoutMs>3000)throw verificationFailed();
 const options={signal,deadline:performance.now()+timeoutMs};
 if(await probeSession(auth,false,options))throw verificationFailed();
 if(Date.parse(auth.expiresAt)<=Date.now()||!await probeSession(auth,true,options))throw verificationFailed();
 return{verified:true,revision:auth.revision,origin:auth.origin,verifyPath:auth.verifyPath,checkedAt:new Date().toISOString()};
}
