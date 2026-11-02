import {bindingKeyOf} from './redteam/personal-session-resolution.mjs';
const ALLOW=new Set(['redteam_security_audit','redteam_session_info','redteam_session_bind']);
const ACTIONS=new Set(['status','preflight','source','kali_check','start','cancel','wait','report','compare']);
export function reviewToolDenial(exec,{bound=null,targets=[],unavailable=false}={}){
 if(!ALLOW.has(exec.name))return '安全审查预设禁止此工具；请使用受管审计入口';
 if(!exec.agent?.session||unavailable)return '审查会话绑定未确认，拒绝执行';
 const args=exec.arguments??{};
 if(exec.name==='redteam_session_info')return;
 if(exec.name==='redteam_session_bind'){
  if(bound)return '安全审查会话已锁定项目，不能切换绑定；请新建会话';
  if(typeof args.engagement!=='string'||!targets.some(t=>t.id===args.engagement||t.name===args.engagement))return '首次绑定必须提供用户指定的精确现有项目名或ID';
  return;
 }
 if(!bound||args.engagement!==undefined&&args.engagement!==bound)return '审查只允许当前绑定项目';
 if(!ACTIONS.has(args.action))return '不支持此审查操作';
}
export const inject=['tools','redteam'];
export function apply(ctx){
 if(typeof ctx.tools?.guard!=='function'||typeof ctx.tools?.restrict!=='function'||typeof ctx.tools?.presentAs!=='function')throw Error('Native execution guard unavailable');
 let signature,release,disposed=false;const reserved=new Map(),definitions=new Map();const presentation=ctx.tools.presentAs('native');
 const identity=exec=>{const expected=definitions.get(exec.name);return expected&&typeof ctx.root.tools.get==='function'&&ctx.root.tools.get(exec.name,exec.agent)===expected};
 const sync=()=>{if(disposed)return;for(const name of ALLOW){const definition=ctx.root.tools.get?.(name);if(definition&&!definitions.has(name))definitions.set(name,definition)}const allow=ctx.root.tools.schemas().map(x=>x.name).filter(x=>ALLOW.has(x));const key=allow.sort().join('\n');if(key===signature)return;signature=key;const previous=release;release=ctx.tools.restrict({allow});previous?.()};
 const guard=ctx.tools.guard(exec=>{
  if(!ALLOW.has(exec.name))return reviewToolDenial(exec);
  if(!identity(exec))return '审查工具身份未确认或已被同名工具覆盖';
  try{const {chain,rootId}=bindingKeyOf(exec,ctx.redteam,{remember:false});if(!chain.length||!rootId)throw Error();const bound=ctx.redteam.sessionBindings.find(chain)??null,targets=exec.name==='redteam_session_bind'?ctx.redteam.listEngagements():[];const denial=reviewToolDenial(exec,{bound,targets});if(denial)return denial;const target=exec.name==='redteam_session_bind'?(targets.find(t=>t.id===exec.arguments.engagement)??targets.find(t=>t.name===exec.arguments.engagement))?.id:bound;const pin=reserved.get(rootId);if(pin&&target&&pin!==target)return '审查会话的首次项目已预留，拒绝并发绑定或切换';if(target&&!pin)reserved.set(rootId,target);return;}
  catch{return reviewToolDenial(exec,{unavailable:true})}
 });
 ctx.on('tools/execute',async(exec,next)=>{if(!ALLOW.has(exec.name)||!identity(exec))throw Error('审查工具身份在执行前变化，拒绝调用');return next()});
 ctx.on('tools/change',sync);ctx.effect(()=>()=>{disposed=true;release?.();guard?.();presentation?.()},'personal-review.tool-filter');sync();
}
