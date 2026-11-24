import {createHash} from 'node:crypto';
import {lstatSync,opendirSync,realpathSync} from 'node:fs';
import {join} from 'node:path';
import {readReviewFile,reviewInputIdentity,safeSnapshotName} from './personal-review-snapshot.mjs';
import {workspaceModePolicy} from './personal-workspace-policy.mjs';
import {previewWorkspacePlan} from './personal-workspace-contract.mjs';
const hash=value=>createHash('sha256').update(value).digest('hex');
const changed=()=>{throw Error('普通检查输入在只读核对期间变化，请重新生成计划')};
const directoryIdentity=path=>{const st=lstatSync(path);if(!st.isDirectory()||realpathSync(path)!==path)changed();return[st.dev,st.ino,st.mtimeMs,st.ctimeMs]};

// Metadata only: no snapshot directory, project hooks, scanner or Git process.
export function ordinaryWorkspacePlan(profile,runtime,{engagement,budgetSeconds=workspaceModePolicy('ordinary').budgetCeilings.wallSeconds}={}){
 const {wallSeconds}=workspaceModePolicy('ordinary').budgetCeilings;
 if(!Number.isSafeInteger(budgetSeconds)||budgetSeconds<30||budgetSeconds>wallSeconds)throw Error('普通检查的任务时限无效');
 if(!profile||!Number.isSafeInteger(profile.revision)||profile.revision<1||!(Date.parse(profile.expiresAt)>Date.now()))throw Error('普通检查需要有效项目范围');
 const root=profile.repoRoot,directories=[],files=[];let excluded=0,seen=0,bytes=0,readBytes=0;
 const visit=(dir,prefix='',depth=0)=>{
  if(depth>20)throw Error('普通检查目录深度超出上限');
  directories.push({path:dir,identity:directoryIdentity(dir)});
  const handle=opendirSync(dir,{bufferSize:32}),entries=[];
  try{let entry;while((entry=handle.readSync())!==null){if(++seen>10000)throw Error('普通检查输入超过10000项上限');entries.push(entry)}}finally{handle.closeSync()}
  for(const entry of entries.sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0)){
   const name=prefix+entry.name,path=join(dir,entry.name);
   if(entry.name.startsWith('.')||['node_modules','vendor','__pycache__','dist','build'].includes(entry.name)){excluded++;continue}
   const st=lstatSync(path);
   if(st.isDirectory()){visit(path,name+'/',depth+1);continue}
   if(!safeSnapshotName(name)||!st.isFile()||st.nlink!==1||st.size>1048576){excluded++;continue}
   if(st.size>8388608-readBytes)throw Error('普通检查首轮读取超过8MiB上限');
   let raw;try{raw=readReviewFile(path,Math.min(1048576,8388608-readBytes))}catch{throw Error('普通检查文件读取或身份未确认，请重新生成计划')}
   readBytes+=raw.length;let text;try{if(raw.includes(0))throw Error();text=new TextDecoder('utf-8',{fatal:true}).decode(raw)}catch{excluded++;continue}
   if(/-----BEGIN [^\r\n]{0,48}PRIVATE KEY|AWS_SECRET_ACCESS_KEY\s*[:=]/i.test(text)){excluded++;continue}
   bytes+=raw.length;if(files.length>=1000||bytes>8388608)throw Error('普通检查输入超过1000文件或8MiB上限');
   files.push({path:name,sha256:hash(raw),bytes:raw.length});
  }
 };
 visit(root);
 for(const dir of directories)if(JSON.stringify(directoryIdentity(dir.path))!==JSON.stringify(dir.identity))changed();
 for(const file of files)if(hash(readReviewFile(join(root,file.path),file.bytes))!==file.sha256)changed();
 const inputIdentity=reviewInputIdentity(profile.revision,files,excluded);
 const preview=files.length?previewWorkspacePlan({mode:'ordinary',scopeRevision:profile.revision,inputIdentity,files:files.map(file=>file.path)}):null;
 const toolIdentities=Object.fromEntries(['semgrep','trivy'].map(tool=>[tool,/^[a-f0-9]{64}$/.test(runtime[tool]?.admissionIdentity??'')&&runtime[tool]?.ready===true?runtime[tool].admissionIdentity:null]));
 const selectedSteps=(preview?.steps??[]).map(step=>({tool:step.tool,purpose:step.purpose,state:'unavailable',reason:'r3-qualification-missing'}));
 const gaps=[...(preview?.gaps??['no-supported-static-input']),...(excluded?['excluded-inputs']:[])];
 const body={version:'ordinary-plan-candidate-3',mode:'ordinary',engagement,budgetSeconds,scopeRevision:profile.revision,inputIdentity,toolIdentities,selectedSteps,inventory:{scope:'managed-visible-text-candidate',files:files.length,bytes,excluded},gaps,executable:false};
 return{...body,planIdentity:hash(JSON.stringify(body))};
}
