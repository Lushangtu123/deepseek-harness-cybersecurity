#!/usr/bin/env node
import {readRuntimeManifest} from '../lib/redteam/personal-security-runtime.mjs';
import {runManagedRuntime,readManagedRuntime,stopManagedRuntime,readRuntimeProject} from '../lib/redteam/personal-runtime-source.mjs';
if(process.platform!=='linux'||process.getuid()!==1000||process.env.DSH_HOME!=='/home/purge/.dsh-improved')throw Error('Dedicated VM only');
const args=process.argv.slice(2),flags={};for(let i=0;i<args.length;i++){const k=args[i];if(!['--engagement','--entry','--seconds','--origin','--confirm-execute','--confirm-stop','--stop'].includes(k)||Object.hasOwn(flags,k))throw Error('参数无效');flags[k]=['--confirm-execute','--confirm-stop','--stop'].includes(k)?true:args[++i]}
try{
 if(flags['--stop']){if(!flags['--confirm-stop']||!flags['--origin'])throw Error('停止需要确认与原网址');const r=readManagedRuntime(flags['--origin']);if(!r)console.log(JSON.stringify({ok:true,state:'not-registered'}));else console.log(JSON.stringify(await stopManagedRuntime(r)))}
 else{
  if(!flags['--confirm-execute']||!flags['--engagement']||!flags['--entry'])throw Error('需要明确确认执行、已授权项目及Python入口');
  const {profile,sanitize}=readRuntimeProject(flags['--engagement']),controller=new AbortController();for(const sig of ['SIGINT','SIGTERM','SIGHUP'])process.once(sig,()=>controller.abort());
  await runManagedRuntime(flags['--engagement'],profile,{entry:flags['--entry'],seconds:Number(flags['--seconds']??360),imageId:readRuntimeManifest().tools.find(t=>t.tool==='semgrep').imageId,sanitize,signal:controller.signal,onReady:value=>console.log(JSON.stringify(value))});
 }
}catch{console.error('运行入口未完成；请核对已保存范围、原网址与私有记录。若启动回执丢失，先按原网址 --stop --confirm-stop 核对清理，不要重复启动。');process.exitCode=1}
