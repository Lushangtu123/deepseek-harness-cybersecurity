// Maintainer evaluation of labelled, non-executed synthetic fixtures.
const invalid=()=>{throw Error('Calibration dataset or scanner result is invalid')};
const fileName=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(value)?value:invalid();
const scannerPath=value=>fileName(typeof value==='string'&&value.startsWith('/src/')?value.slice(5):value);
const RULE_ALIASES={'harness.python.yaml-load':'harness.python.unsafe-yaml','harness.javascript.eval':'harness.javascript.dynamic-eval'};
const canonicalRule=value=>{const local=value.startsWith('policy.')?value.slice(7):value;return RULE_ALIASES[local]??local};
const metrics=rows=>{
 const result={total:rows.length,tp:0,fp:0,tn:0,fn:0,uncovered:0};
 for(const row of rows)result[row.outcome]++;
 return{...result,precision:result.tp+result.fp?result.tp/(result.tp+result.fp):null,recall:result.tp+result.fn?result.tp/(result.tp+result.fn):null};
};
export function evaluateCalibration(dataset,output){
 if(dataset?.version!==1||!Array.isArray(dataset.cases)||!dataset.cases.length||dataset.cases.length>1000)invalid();
 const names=new Map(),ids=new Set();
 for(const row of dataset.cases){
  if(!row||typeof row.id!=='string'||!/^[a-z0-9-]{1,120}$/.test(row.id)||ids.has(row.id)||names.has(row.file)||!['safe','vulnerable'].includes(row.label)||!['development','holdout'].includes(row.split)||!['python','php','javascript','typescript'].includes(row.language)||!/^CWE-[1-9][0-9]{0,5}$/.test(row.category??'')||!/^harness\.[a-z0-9.-]{1,100}$/.test(row.rule??'')||typeof row.source!=='string'||Buffer.byteLength(row.source)>1048576||!Number.isSafeInteger(row.line)||row.line<1||row.line>row.source.trimEnd().split('\n').length)invalid();
  fileName(row.file);names.set(row.file,row);ids.add(row.id);
 }
 if(!Array.isArray(output?.results)||output.results.length>20000||!Array.isArray(output?.errors)||!Array.isArray(output?.paths?.scanned))invalid();
 const scanned=new Set(output.paths.scanned.map(scannerPath));for(const name of scanned)if(!names.has(name))invalid();
 const hits=new Map();let unexpectedFindings=0;
 for(const hit of output.results){
  const name=scannerPath(hit?.path),row=names.get(name);
  if(!row||!scanned.has(name)||typeof hit.check_id!=='string'||!Number.isSafeInteger(hit.start?.line)||hit.start.line<1)invalid();
  const expectedRule=canonicalRule(hit.check_id)===canonicalRule(row.rule);
  if(!expectedRule||row.label==='vulnerable'&&hit.start.line!==row.line)unexpectedFindings++;
  const list=hits.get(name)??[];list.push({rule:hit.check_id,line:hit.start.line,expected:expectedRule&&hit.start.line===row.line});hits.set(name,list);
 }
 const cases=dataset.cases.map(row=>{
  const findings=hits.get(row.file)??[],outcome=!scanned.has(row.file)?'uncovered':row.label==='safe'?(findings.length?'fp':'tn'):findings.some(hit=>hit.expected)?'tp':'fn';
  return{id:row.id,file:row.file,language:row.language,category:row.category,split:row.split,label:row.label,outcome,findings};
 });
 const group=key=>Object.fromEntries([...new Set(cases.map(row=>row[key]))].sort().map(value=>[value,metrics(cases.filter(row=>row[key]===value))]));
 return{version:1,scope:'labelled static rule expectations only; not verified vulnerabilities or population accuracy',r3Qualified:false,findingStatus:'unverified',parserErrors:output.errors.length,unexpectedFindings,totals:metrics(cases),byLanguage:group('language'),byCategory:group('category'),bySplit:group('split'),cases};
}
