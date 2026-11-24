import {createHash} from 'node:crypto';

const tools=['semgrep','trivy','zap'];
const states=['running','completed','partial','failed','cancelled','interrupted'];
const statuses=['unverified','confirmed','false-positive','fixed','retest-passed','reopened'];
const severities=['critical','high','medium','low','info','unknown'];
const fail=()=>{throw Error('审计分页参数或游标无效，请刷新后重试')};
function object(value,keys){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!keys.includes(key)))fail();return value}
function selection(value,allowed){if(value===undefined||value==='')return '';if(typeof value!=='string'||!allowed.includes(value))fail();return value}

// UI pages use an insertion ceiling so new scans do not displace the next
// page. Model report pages retain their separate, revision-bound contract.
export function readSecurityPages(db,engagement,pages){
 object(pages,['runs','findings']);const result={pagination:{}};
 for(const collection of ['runs','findings']){
  const isRun=collection==='runs',raw=object(pages[collection]??{},isRun?['limit','cursor','tool','state']:['limit','cursor','tool','status','severity','search']);
  const limit=raw.limit??(isRun?10:50);if(!Number.isSafeInteger(limit)||limit<1||limit>(isRun?30:100))fail();
  const filters={tool:selection(raw.tool,tools),...(isRun?{state:selection(raw.state,states)}:{status:selection(raw.status,statuses),severity:selection(raw.severity,severities),search:raw.search??''})};
  if(!isRun&&(typeof filters.search!=='string'||filters.search.length>160||/[\x00-\x1f]/.test(filters.search)))fail();
  if(!isRun)filters.search=filters.search.trim();
  const table=isRun?'security_run':'security_finding',key=createHash('sha256').update(JSON.stringify({engagement,collection,limit,filters})).digest('hex');
  let ceiling=db.prepare('SELECT COALESCE(MAX(rowid),0) AS n FROM '+table).get().n,after=null;
  const cursor=raw.cursor??null;
  if(cursor!==null){
   if(typeof cursor!=='string'||cursor.length>512||!cursor||!/^[A-Za-z0-9_-]+$/.test(cursor))fail();
   let value;try{value=JSON.parse(Buffer.from(cursor,'base64url').toString('utf8'));if(Buffer.from(JSON.stringify(value)).toString('base64url')!==cursor)fail()}catch{fail()}
   object(value,['v','key','ceiling','after']);if(value.v!==1||value.key!==key||!Number.isSafeInteger(value.ceiling)||value.ceiling<0||!Number.isSafeInteger(value.after)||value.after<1||value.after>value.ceiling)fail();
   ceiling=value.ceiling;after=value.after;
  }
  if(!Number.isSafeInteger(ceiling)||ceiling<0)fail();
  const clauses=['rowid <= ?'],params=[ceiling];
  for(const [column,value] of Object.entries(filters)){
   if(!value)continue;
   if(column==='search'){
    const literal='%'+value.replace(/[\\%_]/g,character=>'\\'+character)+'%';
    clauses.push("(title LIKE ? ESCAPE '\\' OR rule LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\')");params.push(literal,literal,literal);
   }else{clauses.push(column+' = ?');params.push(value)}
  }
  const where=clauses.join(' AND '),total=db.prepare('SELECT COUNT(*) AS n FROM '+table+' WHERE '+where).get(...params).n;
  const rows=db.prepare('SELECT rowid AS page_id,* FROM '+table+' WHERE '+where+(after===null?'':' AND rowid < ?')+' ORDER BY rowid DESC LIMIT ?').all(...params,...(after===null?[]:[after]),limit+1);
  const hasMore=rows.length>limit,items=rows.slice(0,limit),nextCursor=hasMore?Buffer.from(JSON.stringify({v:1,key,ceiling,after:items.at(-1).page_id})).toString('base64url'):null;
  result[collection]=items.map(({page_id,...row})=>row);
  result.pagination[collection]={cursor,limit,total,hasMore,nextCursor,filters};
 }
 return result;
}
