// Normalized observations only: never derive scan history from mutable finding rows.
import {normalizeSubject,subjectKey,subjectLabel,validSubject,literalSecurityText} from './personal-security-identity.mjs';
const LIMIT=4*1024*1024;
const key=item=>JSON.stringify([item.rule,item.location,subjectKey(item.subject)]);
const bad=()=>{throw Error('扫描快照缺失、结构无效或超出限制')};
const text=(value,max)=>typeof value==='string'&&value.length<=max&&!/[\x00-\x1f]/.test(value);
function validate(value){
 if(!value||![1,2].includes(value.schemaVersion)||!Array.isArray(value.findings)||value.findings.length>2000||!Array.isArray(value.coverageFiles)||value.coverageFiles.length>20000)bad();
 const keys=new Set();
 for(const item of value.findings){if(!item||!text(item.rule,240)||!item.rule||!text(item.location,800)||!item.location||!text(item.title,400)||!text(item.severity,20)||(value.schemaVersion===2?!validSubject(item.subject):item.subject!==undefined)||keys.has(key(item)))bad();keys.add(key(item))}
 if(value.coverageFiles.some(file=>!text(file,800)||!file))bad();return value;
}
export function createScanSnapshot(findings,coverageFiles){
 if(!Array.isArray(coverageFiles)||coverageFiles.length>20000||findings.length>2000)return null;
 const value={schemaVersion:2,findings:[...new Map(findings.map(({rule,title,severity,location,subject})=>{const item={rule,title,severity,location,subject:normalizeSubject(subject)};return[key(item),item]})).values()],coverageFiles:[...new Set(coverageFiles)]};
 try{validate(value)}catch{return null}
 const raw=JSON.stringify(value);return Buffer.byteLength(raw)<=LIMIT?raw:null;
}
export function parseScanSnapshot(raw){if(typeof raw!=='string'||Buffer.byteLength(raw)>LIMIT)bad();let value;try{value=JSON.parse(raw)}catch{bad()}return validate(value)}
export function compareScanSnapshots(baseRun,currentRun,baseRaw,currentRaw){
 const unavailable=reason=>({available:false,reason});
 if(baseRun.tool!==currentRun.tool)return unavailable('两次任务的扫描器不同，不能对比');
 if([baseRun,currentRun].some(run=>run.state!=='completed'||run.complete!==1))return unavailable('需要两次完整完成的任务；失败或覆盖不完整不能比较');
 if(!baseRun.coverage_key||baseRun.coverage_key!==currentRun.coverage_key)return unavailable('规则、镜像、数据库或项目范围策略不同，不能比较');
 if(baseRaw===undefined||currentRaw===undefined)return unavailable('旧任务没有完整扫描快照，无法推断历史命中集合');
 const base=parseScanSnapshot(baseRaw),current=parseScanSnapshot(currentRaw);
 if(baseRun.tool==='trivy'&&(base.schemaVersion!==2||current.schemaVersion!==2))return unavailable('旧Trivy快照没有依赖包身份，无法可靠比较');
 const old=new Map(base.findings.map(item=>[key(item),item])),now=new Map(current.findings.map(item=>[key(item),item])),covered=new Set(current.coverageFiles),all={added:[],persisting:[],notSeen:[],uncovered:[]};
 for(const [id,item] of now)(old.has(id)?all.persisting:all.added).push(item);
 for(const [id,item] of old)if(!now.has(id)){const file=item.location.replace(/:\d+$/,'');(baseRun.tool!=='zap'&&covered.has(file)?all.notSeen:all.uncovered).push(item)}
 const summary=Object.fromEntries(Object.entries(all).map(([name,items])=>[name,items.length])),items=Object.fromEntries(Object.entries(all).map(([name,rows])=>[name,rows.slice(0,100)])),truncated=Object.values(all).some(rows=>rows.length>100);
 const notice='按规则、完整位置及已记录的依赖包身份精确匹配；代码移行或包版本变化可能表现为新增与未再次命中。未再次命中不等于已修复；覆盖未证实的记录保留为未知，不修改发现状态。';
 const labels={added:'新增命中位置',persisting:'仍存在的命中位置',notSeen:'已覆盖文件中未再次命中',uncovered:'覆盖未证实'};
 const safe=literalSecurityText;
 const markdown=['# 扫描结果对比','',`基线：${safe(baseRun.id)} · ${safe(baseRun.tool)} · ${safe(baseRun.started_at)}`,`本次：${safe(currentRun.id)} · ${safe(currentRun.tool)} · ${safe(currentRun.started_at)}`,'',notice,'','每类最多展示100条；数量来自完整已保存快照。'+(truncated?' 本报告明细已截断。':''),'',...Object.entries(items).flatMap(([name,rows])=>[`## ${labels[name]} · ${summary[name]}`,'',...rows.map(item=>'- '+[item.rule,item.location,...(item.subject?[subjectLabel(item.subject)]:[]),item.title].map(safe).join(' · ')),''])].join('\n');
 return{available:true,tool:baseRun.tool,summary,items,truncated,notice,markdown};
}
