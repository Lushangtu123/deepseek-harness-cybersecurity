import {execFile} from 'node:child_process';
import {readFileSync} from 'node:fs';import {join} from 'node:path';import {fileURLToPath} from 'node:url';
import {verifyReviewSnapshot} from './personal-review-snapshot.mjs';
export async function requestManagedAdapter(tool,mode,id,{snapshot,seconds}={}){
 if(!['rea','pentagi'].includes(tool)||!['run','status','cancel'].includes(mode)||!/^joint-[a-f0-9]{40}$/.test(id))throw Error('受管工具参数无效');
 let payload;if(mode==='run'){
  verifyReviewSnapshot(snapshot);const files=tool==='rea'?snapshot.files.filter(f=>/\.(?:js|mjs|cjs|jsx|ts|tsx)$/.test(f.path)):snapshot.files;
  if(!files.length)return{id,snapshotId:snapshot.id,state:'unavailable',cleanupVerified:true,checkedFiles:0,artifacts:[],findings:[],problem:'没有可交接的JavaScript/TypeScript文件'};
  payload=JSON.stringify({snapshotId:snapshot.id,seconds,files:files.map(f=>({path:f.path,sha256:f.sha256,content:readFileSync(join(snapshot.sourceRoot,f.path)).toString('base64')}))});
 }
 return await new Promise((resolve,reject)=>{
  const child=execFile('/usr/bin/python3',['-B',fileURLToPath(new URL('../../scripts/security-joint-adapter.py',import.meta.url)),tool,mode,id],{timeout:40000,maxBuffer:2097152,env:{PATH:'/usr/bin:/bin',HOME:'/home/purge',LANG:'C.UTF-8'}},(error,stdout)=>{
   if(error)return reject(Error('受管工具回执未确认；查询或取消原任务ID，不能重发run'));
   try{const value=JSON.parse(stdout);if(value.id!==id)throw Error();resolve(value)}catch{reject(Error('受管工具回执无效'))}
  });child.stdin.on('error',()=>{});child.stdin.end(payload);
 });
}
