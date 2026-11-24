import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';
const url=new URL('../../../scripts/workspace_calibration.mjs',import.meta.url);
async function api(){assert.ok(existsSync(url),'Calibration evaluator is missing');return import(url)}
const row=(id,label='vulnerable',extra={})=>({id,file:id+'.py',language:'python',category:'CWE-95',label,split:'development',rule:'harness.python.eval',line:2,source:'def parse(raw):\n    return eval(raw)\n',...extra});
const output=(hits=[],paths=['risk.py','safe.py'])=>({version:'fixture',errors:[],paths:{scanned:paths.map(name=>'/src/'+name)},results:hits});
const hit=(name,extra={})=>({path:'/src/'+name+'.py',check_id:'policy.harness.python.eval',start:{line:2},...extra});
test('Calibration measures the explicit sample denominator without promoting R3 or confirming findings',async()=>{
 const {evaluateCalibration}=await api(),dataset={version:1,cases:[row('risk'),row('safe','safe')]};
 const result=evaluateCalibration(dataset,output([hit('risk')]));
 assert.deepEqual(result.totals,{total:2,tp:1,fp:0,tn:1,fn:0,uncovered:0,precision:1,recall:1});
 assert.equal(result.r3Qualified,false);assert.equal(result.findingStatus,'unverified');assert.equal(result.parserErrors,0);
});
test('Wrong lines, unexpected rules, false positives, misses and absent coverage remain distinguishable',async()=>{
 const {evaluateCalibration}=await api(),dataset={version:1,cases:[row('risk'),row('safe','safe'),row('gap')]};
 const result=evaluateCalibration(dataset,output([hit('risk',{start:{line:9}}),hit('safe')]));
 assert.equal(result.totals.fn,1);assert.equal(result.totals.fp,1);assert.equal(result.totals.uncovered,1);
 assert.equal(result.unexpectedFindings,1);assert.equal(result.cases.find(row=>row.id==='gap').outcome,'uncovered');
 const unknown=output([hit('risk',{check_id:'unrelated.rule'})]);assert.equal(evaluateCalibration(dataset,unknown).unexpectedFindings,1);
});
test('Metrics are split by language, category and development versus holdout without hiding parse errors',async()=>{
 const {evaluateCalibration}=await api(),dataset={version:1,cases:[row('risk'),row('safe','safe',{language:'php',split:'holdout',category:'CWE-502'})]},raw=output([hit('risk')]);
 raw.errors=[{type:'PartialParsing'}];const result=evaluateCalibration(dataset,raw);
 assert.equal(result.parserErrors,1);assert.equal(result.byLanguage.php.tn,1);assert.equal(result.byCategory['CWE-502'].tn,1);assert.equal(result.bySplit.holdout.total,1);
});
test('Explicit legacy rule aliases are compared as the same check without accepting arbitrary suffixes',async()=>{
 const {evaluateCalibration}=await api(),dataset={version:1,cases:[row('risk','vulnerable',{rule:'harness.python.unsafe-yaml'})]};
 const legacy=output([hit('risk',{check_id:'policy.harness.python.yaml-load'})],['risk.py']);
 assert.equal(evaluateCalibration(dataset,legacy).totals.tp,1);
 legacy.results[0].check_id='foreign.harness.python.yaml-load';
 assert.equal(evaluateCalibration(dataset,legacy).totals.fn,1);
});
test('Malformed labels, duplicate cases, unsupported paths and fabricated scanner files are rejected',async()=>{
 const {evaluateCalibration}=await api();
 for(const cases of [[row('risk'),row('risk')],[row('risk','probably')],[row('risk','safe',{file:'../risk.py'})],[row('risk','safe',{line:999})]])assert.throws(()=>evaluateCalibration({version:1,cases},output()));
 assert.throws(()=>evaluateCalibration({version:1,cases:[row('risk')]},output([hit('foreign')],['risk.py'])));
 assert.throws(()=>evaluateCalibration({version:1,cases:[row('risk')]},output([],['../risk.py'])));
});
test('Expanded labelled fixtures retain balanced development/holdout coverage before running any scanner',async()=>{
 const dataset=JSON.parse(readFileSync(new URL('../../../docs/security-workspace/ordinary-calibration-cases.json',import.meta.url)));
 assert.equal(dataset.cases.length,48);assert.equal(dataset.cases.filter(row=>row.split==='development').length,24);assert.equal(dataset.cases.filter(row=>row.split==='holdout').length,24);
 assert.deepEqual([...new Set(dataset.cases.map(row=>row.language))].sort(),['javascript','php','python','typescript']);
 const {evaluateCalibration}=await api(),result=evaluateCalibration(dataset,{version:'fixture',results:[],errors:[],paths:{scanned:[]}});
 assert.equal(result.totals.uncovered,48);assert.equal(result.totals.recall,null);
});
