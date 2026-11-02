import {execFile} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {verifyReviewSnapshot} from './personal-review-snapshot.mjs';
export async function requestKaliProject(mode,id,{snapshot,seconds}={}){
 if(!['run','status','cancel'].includes(mode)||!/^joint-[a-f0-9]{40}$/.test(id))throw Error('Kali固定适配器参数无效');
 let payload;
 if(mode==='run'){
  verifyReviewSnapshot(snapshot);const files=snapshot.files.filter(f=>f.path.endsWith('.py'));
  if(!files.length)return{id,snapshotId:snapshot.id,state:'unavailable',cleanupVerified:true,checkedFiles:0,findings:[],problem:'没有可交接的Python文件，Kali Bandit未运行'};
  payload=JSON.stringify({snapshotId:snapshot.id,seconds,files:files.map(f=>({path:f.path,sha256:f.sha256,content:readFileSync(join(snapshot.sourceRoot,f.path)).toString('base64')}))});
 }
 return await new Promise((resolve,reject)=>{
  const child=execFile('/usr/bin/python3',['-B',fileURLToPath(new URL('../../scripts/security-kali-project.py',import.meta.url)),mode,id],{timeout:15000,maxBuffer:2097152,env:{PATH:'/usr/bin:/bin',HOME:'/home/purge',LANG:'C.UTF-8'}},(error,stdout)=>{
   if(error){reject(Error('Kali回执未确认；必须查询原任务ID或取消，不能重发run'));return}
   try{const value=JSON.parse(stdout);if(value.id!==id)throw Error();resolve(value)}catch{reject(Error('Kali返回无效回执'))}
  });child.stdin.on('error',()=>{});child.stdin.end(payload);
 });
}
