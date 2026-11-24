import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {createHash,randomUUID} from 'node:crypto';
import {readFileSync,realpathSync,lstatSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {readRuntimeManifest} from './personal-security-runtime.mjs';

const worker=fileURLToPath(new URL('../../scripts/python_namespace_review.py',import.meta.url));
export const NAMESPACE_WORKER_SHA256='6c8c7446b99a777e5f496c008c9eeebecebc15134a5aedb6c7be4a14144a6705';
const digest=v=>createHash('sha256').update(v).digest('hex');
const idPattern=/^dsh-sec-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
function docker(args,{input='',signal,timeout=2000,maxBuffer=131072}={}){
 return new Promise((resolve,reject)=>{
  const child=execFile('/usr/bin/sudo',['-n','/usr/bin/docker',...args],{encoding:'utf8',timeout,killSignal:'SIGTERM',maxBuffer,signal,env:{PATH:'/usr/bin:/bin',HOME:'/home/purge',LANG:'C.UTF-8'}},(error,stdout,stderr)=>{if(error){error.stdout=stdout;error.stderr=stderr;reject(error)}else resolve(stdout)});
  child.stdin.on('error',()=>{});child.stdin.end(input);
 });
}
export function namespaceSandboxPlan(image,script,name){
 assert.match(image,/^sha256:[a-f0-9]{64}$/);assert.match(name,idPattern);assert.ok(script.startsWith('/')&&!script.includes(',')&&!script.includes('\n'));
 return ['create','--rm','-i','--pull','never','--name',name,'--label','personal.harness.security=true','--label','personal.harness.namespace-review=1','--network','none','--user','65534:65534','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--ipc','private','--cpus','1','--memory','256m','--memory-swap','256m','--pids-limit','32','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16777216','--no-healthcheck','--mount','type=bind,src='+script+',dst=/review.py,readonly','--entrypoint','python3',image,'-I','-B','/review.py','--managed'];
}
function validateContainer(v,image,script,name){
 assert.equal(v.Name,'/'+name);assert.equal(v.Image,image);assert.equal(v.Config.Image,image);assert.equal(v.Config.User,'65534:65534');assert.deepEqual(v.Config.Entrypoint,['python3']);assert.deepEqual(v.Config.Cmd,['-I','-B','/review.py','--managed']);
 const c=v.HostConfig;assert.equal(c.NetworkMode,'none');assert.equal(c.ReadonlyRootfs,true);assert.equal(c.Privileged,false);assert.ok(!c.CapAdd?.length);assert.deepEqual(c.CapDrop,['ALL']);assert.deepEqual(c.SecurityOpt,['no-new-privileges']);assert.equal(c.IpcMode,'private');assert.ok(!c.PidMode&&!c.UTSMode&&!c.Devices?.length&&!c.DeviceRequests?.length);assert.equal(c.Memory,268435456);assert.equal(c.MemorySwap,268435456);assert.equal(c.NanoCpus,1000000000);assert.equal(c.PidsLimit,32);assert.deepEqual(c.Tmpfs,{'/tmp':'rw,nosuid,nodev,noexec,size=16777216'});
 const mounts=v.Mounts.filter(m=>m.Type==='bind');assert.equal(mounts.length,1);assert.equal(mounts[0].Source,script);assert.equal(mounts[0].Destination,'/review.py');assert.equal(mounts[0].RW,false);assert.ok(v.Mounts.every(m=>m.Type==='bind'||m.Type==='tmpfs'&&m.Destination==='/tmp'));assert.equal(v.State.Running,false);
}

export async function runNamespaceSandbox(request,{deadline,signal,docker:exec=docker,manifest}={}){
 const remaining=()=>Math.floor(deadline-performance.now());
 const timeout=(cap,reserve)=>{const ms=Math.floor(Math.min(cap,remaining()-reserve));assert.ok(ms>=1,'Review budget too short');return ms};
 assert.ok(Number.isFinite(deadline)&&remaining()>=7000);signal?.throwIfAborted();
 assert.equal(realpathSync(worker),worker);assert.ok(lstatSync(worker).isFile());
 const workerSha256=digest(readFileSync(worker));assert.equal(workerSha256,NAMESPACE_WORKER_SHA256,'Worker identity changed');const image=(manifest??readRuntimeManifest()).tools.find(t=>t.tool==='semgrep')?.imageId;
 const name='dsh-sec-'+randomUUID(),args=namespaceSandboxPlan(image,worker,name),input=JSON.stringify(request);assert.ok(Buffer.byteLength(input)<=12582912);
 let attempted=false,containerId,report,problem,cleanup=false;
 try{
  attempted=true;const id=(await exec(args,{timeout:timeout(2000,5000)})).trim();assert.match(id,/^[a-f0-9]{64}$/);containerId=id;
  const observed=JSON.parse(await exec(['inspect',id],{signal,timeout:timeout(1500,4500)}));assert.equal(observed.length,1);assert.equal(observed[0].Id,id);validateContainer(observed[0],image,worker,name);
  signal?.throwIfAborted();assert.ok(remaining()>=4500);
  report=JSON.parse(await exec(['start','--attach','--interactive',id],{input,signal,timeout:timeout(4500,2000)}));
  assert.equal(report.runtimePython,'3.12.15','Reviewer runtime needs requalification');assert.equal(digest(readFileSync(worker)),workerSha256);
 }catch(error){problem=error}
 finally{
  if(attempted){
   try{
    const target=containerId??name;
    try{await exec(['rm','--force',target],{timeout:2000})}catch{/* absence must be positively confirmed below */}
    try{await exec(['inspect',target],{timeout:2000});throw Error('Container remains')}
    catch(error){assert.equal(error.code,1);assert.equal(String(error.stdout).trim(),'[]');assert.equal(String(error.stderr).trim().toLowerCase(),'error: no such object: '+target)}
    assert.ok(containerId,'Create outcome was never confirmed');
    const value=JSON.parse(await exec(['image','inspect',image],{timeout:2000}));assert.equal(value[0].Id,image);cleanup=true;
   }catch{cleanup=false}
  }
 }
 if(!cleanup)throw Object.assign(Error('结构复核容器停止未确认'),{code:'STOP_UNCONFIRMED'});
 if(problem)throw problem;
 return{...report,execution:{profile:'namespace-ast-1',imageId:image,workerSha256,pythonVersion:report.runtimePython,cleanupVerified:true}};
}
