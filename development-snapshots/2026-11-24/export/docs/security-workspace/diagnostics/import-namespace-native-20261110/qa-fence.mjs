// Acceptance-only instrumentation; no message text or credentials are logged.
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {isAgentLoopRequest} from '/home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh-llm/lib/index.js';
export const inject=['tools','redteam','llm'];
export function apply(ctx,config) {
  if(ctx.redteam.root!=='/home/purge/.dsh-improved/redteam') throw Error('Unexpected native store');
  const allowed=new Set(['redteam_session_bind','redteam_session_info','redteam_joint_review']);
  let calls=0,modelCalls=0;
  const log=value=>fs.appendFileSync(config.root+'/native-events.jsonl',JSON.stringify({at:new Date().toISOString(),...value})+'\n',{mode:0o600});
  const reject=exec=> {
    if(!allowed.has(exec.name)) return 'Only isolated managed review tools';
    const args=exec.arguments??{};
    if(args.engagement!==undefined && args.engagement!==config.engagement) return 'Wrong isolated engagement';
    if(exec.name==='redteam_session_bind' && args.engagement!==config.engagement) return 'Exact project required';
    if(exec.name==='redteam_joint_review' && !['plan','start','status','wait','report'].includes(args.action)) return 'Operation unavailable';
    if(calls>=48) return 'Native tool budget exhausted';
  };
  const guard=ctx.tools.guard(reject);
  const pre=ctx.on('tools/pre-execute',async(exec,next)=>{
    const reason=reject(exec);if(reason){log({kind:'blocked-tool',name:exec.name,reason});return {kind:'deny',reason}}
    return next();
  },{global:true});
  const execute=ctx.on('tools/execute',async(exec,next)=>{
    const reason=reject(exec);if(reason)throw Error(reason);
    calls++;log({kind:'accepted-tool',name:exec.name,arguments:exec.arguments,callId:exec.callId});return next();
  });
  const observe=ctx.on('session/event',(session,event)=>{
    const item={kind:'session-event',sessionId:session.id,type:event.type,seq:event.seq};
    if(event.type==='tool/result') {
      item.isError=event.data?.message?.isError===true;
      item.resultSha256=createHash('sha256').update(JSON.stringify(event.data)).digest('hex');
    }
    if(event.type==='assistant/message') {
      const source=event.data?.message?.source;
      item.source={provider:source?.provider,model:source?.model};
    }
    if(event.type==='turn/end') item.reasonKind=event.data?.reason?.kind;
    log(item);
  });
  const model=ctx.on('llm/stream',(options,next)=>{
    const id=++modelCalls,main=isAgentLoopRequest(options);
    if(id>40)throw Error('Isolated model dispatch budget exhausted');
    log({kind:'model-dispatch',id,main,provider:options.provider,model:options.model,
      reasoningEffort:typeof options.reasoningEffort==='string'?options.reasoningEffort:undefined});
    return (async function*(){
      try {
        for await(const chunk of await next()) {
          if(chunk.type==='finish') log({kind:'model-finish',id,reasonKind:chunk.reason?.kind,
            adapterReplayModel:chunk.replayState?.response?.model,failureCode:chunk.reason?.failure?.code});
          yield chunk;
        }
      } finally { log({kind:'model-stream-closed',id}) }
    })();
  },{global:true,prepend:true});
  ctx.effect(()=>()=>{guard?.();pre?.();execute?.();observe?.();model?.()});
  fs.writeFileSync(config.root+'/fence-ready.json',JSON.stringify({guardInstalled:true,storeMatches:true,
    allowed:[...allowed],modelObserver:true,maxTools:48,maxModelDispatches:40}),{mode:0o600});
}
