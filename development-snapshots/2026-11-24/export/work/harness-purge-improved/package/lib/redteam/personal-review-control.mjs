import {spawn} from 'node:child_process';
import {setImmediate as yieldLoop} from 'node:timers/promises';

const failure=(code,message)=>Object.assign(Error(message),{code});
export function reviewCheckpoint({signal,deadline=Infinity}={}){
 if(signal?.aborted)throw failure('REVIEW_CANCELLED','项目副本已取消');
 if(deadline!==Infinity&&!Number.isFinite(deadline))throw failure('REVIEW_DEADLINE','项目副本期限无效');
 if(performance.now()>=deadline)throw failure('REVIEW_DEADLINE','项目副本预算期限已到');
}
export async function reviewYield(control){reviewCheckpoint(control);await yieldLoop();reviewCheckpoint(control)}

// Only trusted fixed parser/check commands call this helper. Project bytes are
// stdin data. Rejection happens after close, never merely after sending a kill.
export function runReviewParser(command,args,input,{signal,deadline=Infinity,maxBuffer=8388608}={}){
 reviewCheckpoint({signal,deadline});
 return new Promise((resolve,reject)=>{
  let child,error,timer,used=0,stderrUsed=0;const stdout=[],stderr=[];
  const stop=reason=>{error??=reason;try{child?.kill('SIGKILL')}catch{}};
  const abort=()=>stop(failure('REVIEW_CANCELLED','项目副本已取消'));
  try{child=spawn(command,args,{env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'},stdio:['pipe','pipe','pipe']})}catch(cause){reject(cause);return}
  child.on('error',cause=>{error??=cause});
  child.stdin.on('error',cause=>{error??=cause});
  child.stdout.on('data',chunk=>{used+=chunk.length;if(used>maxBuffer)stop(failure('REVIEW_PARSE_LIMIT','源码解析输出超出上限'));else stdout.push(chunk)});
  child.stderr.on('data',chunk=>{stderrUsed+=chunk.length;if(stderrUsed>65536)stop(failure('REVIEW_PARSE_LIMIT','源码解析错误输出超出上限'));else stderr.push(chunk)});
  child.once('close',code=>{
   clearTimeout(timer);signal?.removeEventListener('abort',abort);
   if(error){reject(error);return}
   try{reviewCheckpoint({signal,deadline});resolve({code,stdout:Buffer.concat(stdout).toString('utf8'),stderr:Buffer.concat(stderr).toString('utf8')})}catch(cause){reject(cause)}
  });
  const remaining=deadline-performance.now(),milliseconds=Math.max(1,Math.min(5000,remaining));
  timer=setTimeout(()=>stop(failure(remaining<=5000?'REVIEW_DEADLINE':'REVIEW_PARSE_TIMEOUT',remaining<=5000?'项目副本预算期限已到':'源码解析超时')),milliseconds);
  signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted)abort();
  child.stdin.end(input);
 });
}
