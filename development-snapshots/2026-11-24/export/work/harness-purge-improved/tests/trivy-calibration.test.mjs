import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
const url=new URL('../../../scripts/trivy_calibration.mjs',import.meta.url);
async function api(){assert.ok(existsSync(url),'Trivy calibration evaluator is missing');return import(url)}
const item=(changes={})=>({id:'jinja-positive',category:'dependency',expected:'present',target:'requirements.txt',rule:'CVE-2024-56326',package:'jinja2',version:'3.1.4',...changes});
const report=(changes={})=>({Results:[{Target:'/src/jinja-positive/requirements.txt',Packages:[{Name:'jinja2',Version:'3.1.4'}],Vulnerabilities:[{VulnerabilityID:'CVE-2024-56326',PkgName:'jinja2',InstalledVersion:'3.1.4',FixedVersion:'3.1.5'}],...changes}]});
test('Fixed advisory matching requires the declared component, version and ID and keeps findings unverified',async()=>{
 const {evaluateTrivyCalibration}=await api(),value=evaluateTrivyCalibration({version:1,cases:[item()]},report());
 assert.equal(value.cases[0].expectationSatisfied,true);assert.equal(value.cases[0].componentIdentity,'observed');assert.equal(value.r3Qualified,false);assert.equal(value.findingStatus,'unverified');
 assert.equal(evaluateTrivyCalibration({version:1,cases:[item()]},report({Packages:[],Vulnerabilities:[{VulnerabilityID:'CVE-2024-56326',PkgName:'other',InstalledVersion:'3.1.4'}]})).cases[0].expectationSatisfied,null);
});
test('Patched-version control can exclude one CVE while retaining other advisory observations',async()=>{
 const {evaluateTrivyCalibration}=await api(),value=evaluateTrivyCalibration({version:1,cases:[item({expected:'absent',version:'3.1.5'})]},report({Packages:[{Name:'jinja2',Version:'3.1.5'}],Vulnerabilities:[{VulnerabilityID:'CVE-OTHER',PkgName:'jinja2',InstalledVersion:'3.1.5'}]}));
 assert.equal(value.cases[0].expectationSatisfied,true);assert.equal(value.cases[0].otherObservations,1);assert.equal(value.projectSafe,false);
});
test('Unpinned versions and absent component evidence do not become true negatives',async()=>{
 const {evaluateTrivyCalibration}=await api();
 for(const [fixture,native] of [[item({expected:'unresolved',version:null}),report({Packages:[],Vulnerabilities:[]})],[item({expected:'absent'}),report({Packages:[],Vulnerabilities:[]})]]){
  const value=evaluateTrivyCalibration({version:1,cases:[fixture]},native);assert.equal(value.cases[0].expectationSatisfied,null);assert.equal(value.totals.unknown,1);
 }
});
test('Config PASS observations and absent secret targets are not reported as failures or proven coverage',async()=>{
 const {evaluateTrivyCalibration}=await api(),dataset={version:1,cases:[item({id:'docker-control',category:'configuration',target:'Dockerfile',rule:'AVD-DS-0002',expected:'absent'}),item({id:'secret-control',category:'secret',target:'settings.txt',rule:'github-pat',expected:'absent'})]};
 const value=evaluateTrivyCalibration(dataset,{Results:[{Target:'docker-control/Dockerfile',Misconfigurations:[{ID:'DS002',AVDID:'AVD-DS-0002',Status:'PASS'}]}]});
 assert.equal(value.cases[0].expectationSatisfied,true);assert.equal(value.cases[1].expectationSatisfied,null);assert.equal(value.cases[1].coverage,'unknown');
});
test('Foreign targets and duplicate or unsafe fixture identities are rejected',async()=>{
 const {evaluateTrivyCalibration}=await api();
 assert.throws(()=>evaluateTrivyCalibration({version:1,cases:[item(),item()]},report()));
 assert.throws(()=>evaluateTrivyCalibration({version:1,cases:[item({target:'../outside'})]},report()));
 assert.throws(()=>evaluateTrivyCalibration({version:1,cases:[item()]},{Results:[{Target:'foreign/requirements.txt'}]}));
});
test('The pinned Trivy DS-0002 identifier maps only to its explicit AVD rule identity',async()=>{
 const {evaluateTrivyCalibration}=await api(),dataset={version:1,cases:[item({id:'docker-control',category:'configuration',target:'Dockerfile',rule:'AVD-DS-0002'})]};
 assert.equal(evaluateTrivyCalibration(dataset,{Results:[{Target:'docker-control/Dockerfile',Misconfigurations:[{ID:'DS-0002',Status:'FAIL'}]}]}).cases[0].expectationSatisfied,true);
 assert.equal(evaluateTrivyCalibration(dataset,{Results:[{Target:'docker-control/Dockerfile',Misconfigurations:[{ID:'FOREIGN-DS-0002',Status:'FAIL'}]}]}).cases[0].expectationSatisfied,false);
});
test('Target failures or another scanner category cannot establish an expected absence',async()=>{
 const {evaluateTrivyCalibration}=await api();
 for(const error of [{Error:'scan incomplete'},{Errors:['analyzer failed']}]){
  const value=evaluateTrivyCalibration({version:1,cases:[item({expected:'absent'})]},report({Vulnerabilities:[],...error}));
  assert.equal(value.cases[0].expectationSatisfied,null);assert.equal(value.cases[0].observation,'target-incomplete');
 }
 const fixture=item({id:'docker-control',category:'configuration',target:'Dockerfile',rule:'AVD-DS-0002',expected:'absent'});
 const value=evaluateTrivyCalibration({version:1,cases:[fixture]},{Results:[{Target:'docker-control/Dockerfile',Class:'secret',Secrets:[]}]});
 assert.equal(value.cases[0].expectationSatisfied,null);assert.equal(value.cases[0].coverage,'unknown');
});
