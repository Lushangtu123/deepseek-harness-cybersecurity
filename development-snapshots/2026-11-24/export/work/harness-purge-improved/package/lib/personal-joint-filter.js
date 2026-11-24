import {applyManagedReviewFilter,reviewToolDenial} from './personal-review-filter.js';
const allow=new Set(['redteam_joint_review','redteam_session_info','redteam_session_bind']);
export function jointToolDenial(exec,context={}){
 if(!allow.has(exec.name))return '联合审查仅允许受管调度与项目绑定入口';
 if(exec.name!=='redteam_joint_review')return reviewToolDenial(exec,context);
 if(!['plan','start','status','wait','cancel','report'].includes(exec.arguments?.action))return '联合审查操作无效';
 return reviewToolDenial({...exec,name:'redteam_security_audit',arguments:{...exec.arguments,action:exec.arguments.action==='plan'?'preflight':exec.arguments.action}},context);
}
export const inject=['tools','redteam'];
export function apply(ctx){return applyManagedReviewFilter(ctx,{allow,denial:jointToolDenial,scope:'personal-joint.tool-filter'})}
