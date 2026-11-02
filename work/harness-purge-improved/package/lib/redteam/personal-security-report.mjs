import {subjectLabel,literalSecurityText} from './personal-security-identity.mjs';
const findingStates={unverified:'待验证',confirmed:'已确认','false-positive':'误报',fixed:'已记录修复','retest-passed':'复测通过',reopened:'再次出现',other:'其他或未识别'};
const severities={critical:'critical',high:'high',medium:'medium',low:'low',info:'info',other:'其他或未识别'};
const runStates={running:'运行中',completed:'已完成',partial:'覆盖不完整',failed:'失败',cancelled:'已取消',interrupted:'中断',other:'其他或未识别'};
function grouped(db,sql,labels){
 const counts=Object.fromEntries(Object.keys(labels).map(key=>[key,0]));
 for(const row of db.prepare(sql).all())counts[Object.hasOwn(counts,row.value)?row.value:'other']+=row.n;
 return counts;
}
export function securityReportSummary(db){
 const byStatus=grouped(db,'SELECT status AS value,COUNT(*) AS n FROM security_finding GROUP BY status',findingStates);
 const bySeverity=grouped(db,'SELECT severity AS value,COUNT(*) AS n FROM security_finding GROUP BY severity',severities);
 const byState=grouped(db,'SELECT state AS value,COUNT(*) AS n FROM security_run GROUP BY state',runStates);
 const total=counts=>Object.values(counts).reduce((sum,n)=>sum+n,0);
 return{findings:{total:total(byStatus),byStatus,bySeverity},runs:{total:total(byState),byState,notComplete:db.prepare("SELECT COUNT(*) AS n FROM security_run WHERE state!='completed' OR complete!=1").get().n}};
}
const record=value=>value&&typeof value==='object'&&!Array.isArray(value)?value:{};
export function formatSecurityReport(value,clean){
 // Dynamic values stay literal, single-line text; only this formatter adds Markdown structure.
 const text=value=>literalSecurityText(clean(value===null||value===undefined||value===''?'未记录':value,2000));
 const field=(name,value)=>'- '+name+'：'+text(value);
 const table=(labels,counts)=>['| 分类 | 记录数 |','| --- | ---: |',...Object.entries(labels).map(([key,label])=>'| '+label+' | '+counts[key]+' |'),''];
 const scope=(profile,revision,missing)=>{
  if(!profile||typeof profile!=='object'||Array.isArray(profile))return[missing,''];
  return[field('范围版本',revision),field('仓库',profile.repoRoot),field('本地网址',profile.url===null?'未配置':profile.url),field('ZAP 私有会话配置名',profile.authProfile||'匿名检查'),field('允许工具',Array.isArray(profile.tools)?profile.tools.join(', '):null),field('授权到期',profile.expiresAt),''];
 };
 const summary=value.summary;
 const lines=['# 安全审计报告','',`项目：${text(value.engagement)}`,`生成：${text(value.generatedAt)}`,`收录：${value.findings.length}/${value.totalFindings}条发现；${value.runs.length}/${value.totalRuns}次任务。${value.exportComplete?'完整导出':'导出达到20000条上限，请分段整理；此报告仅含部分记录'}`,'',
  '扫描命中须经人工验证；未完成任务不代表安全。通用Shell与原版能力不受新增扫描范围限制。','',
  '## 发现状态汇总','','汇总依据全部记录，不受本报告明细上限影响。按发现记录计数，不等于已确认漏洞数；同一问题不同位置可能产生多条记录。','',...table(findingStates,summary.findings.byStatus),
  '## 严重性分布','','包含待验证、误报和已记录修复等所有状态，不能当作当前未修复漏洞数量。','',...table(severities,summary.findings.bySeverity),
  '## 任务状态汇总','',...table(runStates,summary.runs.byState),`未完整结束的任务：${summary.runs.notComplete}。只有completed且complete=1计为完整结束；完整结束仅代表当时工具与覆盖。`,...(summary.runs.total?[]:['尚无任务，不能据此判定项目安全。']),'',
  '## 当前保存范围','','这是当前配置，不是历史任务的统一范围；历史范围以各任务保存的资料为准。','',...scope(value.profile,value.profile?.revision,'未保存范围。'),
  '## 审查覆盖清单','','以下是最近同范围版本的工具观察；人工项未验证，不构成ASVS合规声明。','',...(value.review?.checks??[]).map(c=>'- '+text(c.label)+'：'+text(({observed:'有完整工具观察',partial:'覆盖不完整',running:'运行中',unverified:'未验证',manual:'待人工验证'})[c.state]||'未确认')),'',
  '## 发现明细',''];
 if(value.findings.some(item=>item.tool==='trivy'&&item.identityVersion===0))lines.push('本报告包含未区分依赖包身份的旧Trivy记录；历史可能已合并，保留原状态，请重新扫描并人工核对。','');
 for(const item of value.findings)lines.push('### '+text(item.title),'',field('状态',item.status),field('严重性',item.severity),field('规则',item.tool+' / '+item.rule),field('位置',item.location),field('依赖包',subjectLabel(item.subject)||'非包发现或未记录'),field('证据',item.evidence),field('验证/修复',item.note),field('来源任务',item.first_run),field('最近任务',item.last_run),'');
 lines.push('## 任务覆盖','','以下版本与范围来自任务记录，不用当前运行资源补填历史。提交号不证明未提交修改已被固定或复现。','');
 for(const run of value.runs){
  const details=record(run.details),runtime=record(details.runtime),rules=record(runtime.rules),database=record(runtime.database);
  lines.push('### '+text(run.id),'',field('工具',run.tool),field('状态',run.state),field('完整',run.state==='completed'&&run.complete===1?'是':'否'),field('开始',run.started_at),field('结束',run.finished_at),field('工具版本',details.version),field('规则',typeof rules.version==='string'&&Number.isSafeInteger(rules.count)?rules.version+' / '+rules.count+'条':null),field('漏洞库更新时间',database.updatedAt),field('运行资源核对',runtime.checkedAt),field('覆盖文件数',Number.isSafeInteger(details.coveredFiles)&&details.coveredFiles>=0?details.coveredFiles:null),field('覆盖策略标识',run.coverage_key),field('记录的提交',run.revision_ref),field('失败或中断说明',run.error_code),...(details.supplemental?[field('有限文本补查',details.supplemental.checkedFiles+'/'+details.supplemental.candidateFiles+' 个候选文件；跳过 '+details.supplemental.skippedFiles+'；提示 '+details.supplemental.hints+(details.supplemental.truncated?'；窗口已截断':'')),'仅对解析失败文件做固定字样匹配，注释或字符串也可能命中；原语义解析缺口仍保留，不计完整覆盖。']:[]),...(details.authentication?[field('认证前后核对',details.authentication.state==='verified'?'控制器与 ZAP 前后均通过':'未确认；不计完整认证扫描'),field('私有会话配置名',details.authentication.profile),'认证仅核对扫描前后，不保证全程持续登录；报告不包含会话凭据。']:[]),field('扫描诊断条数',details.diagnostics?.total),...(Array.isArray(details.diagnostics?.items)?details.diagnostics.items.map(d=>field('覆盖诊断',d.code+' · '+d.path+(d.line?':'+d.line:''))):[]),...(details.diagnostics?.truncated?['诊断仅保留前20项，条数包含全部。']:[]),'',...scope(details.profile,run.profile_revision,'历史范围未记录。'));
 }
 return lines.join('\n');
}
