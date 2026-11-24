// Check-specific observations from fixed Trivy reports, never exploit verdicts.
const fail=()=>{throw Error('Trivy calibration input is invalid')};
const name=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9._/-]{0,239}$/.test(value)&&value.split('/').every(part=>part&&part!=='.'&&part!=='..')?value:fail();
const target=value=>name(typeof value==='string'&&value.startsWith('/src/')?value.slice(5):value);
const version=value=>typeof value==='string'?value.replace(/^v/,''):'';
const canonical=value=>typeof value==='string'?value.toLowerCase():'';
const configRule=item=>item.AVDID||({'DS-0002':'AVD-DS-0002'}[item.ID]??item.ID);
const categoryMatch=(value,category)=>value.Class!==undefined?value.Class===({dependency:'lang-pkgs',configuration:'config',secret:'secret'}[category]):category==='dependency'?value.Packages!==undefined||value.Vulnerabilities!==undefined:category==='configuration'?value.Misconfigurations!==undefined:value.Secrets!==undefined;
const targetError=value=>!!value.Error||value.Errors!==undefined&&(!Array.isArray(value.Errors)||value.Errors.length>0);
export function evaluateTrivyCalibration(dataset,report){
 if(dataset?.version!==1||!Array.isArray(dataset.cases)||!dataset.cases.length||dataset.cases.length>1000||!Array.isArray(report?.Results)||report.Results.length>20000)fail();
 const cases=new Map(),targets=new Map();
 for(const row of dataset.cases){
  if(!row||typeof row.id!=='string'||!/^[a-z0-9-]{1,80}$/.test(row.id)||cases.has(row.id)||!['dependency','configuration','secret'].includes(row.category)||!['present','absent','unresolved'].includes(row.expected)||typeof row.rule!=='string'||row.rule.length>160)fail();
  const path=row.id+'/'+name(row.target);if(targets.has(path))fail();
  cases.set(row.id,row);targets.set(path,row);
 }
 const grouped=new Map();
 for(const result of report.Results){
  if(!result||typeof result.Target!=='string')fail();const path=target(result.Target);
  // Companion package manifests may be reported even when the evaluated target
  // is the lockfile. Only paths explicitly present in the fixture are accepted.
  const row=targets.get(path)??dataset.cases.find(item=>path.startsWith(item.id+'/')&&Object.hasOwn(item.files??{},path.slice(item.id.length+1)));
  if(!row)fail();
  for(const key of ['Packages','Vulnerabilities','Misconfigurations','Secrets'])if(result[key]!==undefined&&!Array.isArray(result[key]))fail();
  const values=grouped.get(path)??[];values.push(result);grouped.set(path,values);
 }
 const observations=[...cases.values()].map(row=>{
  const targetValues=grouped.get(row.id+'/'+row.target)??[],values=targetValues.filter(value=>categoryMatch(value,row.category)),vulns=values.flatMap(value=>value.Vulnerabilities??[]),configs=values.flatMap(value=>value.Misconfigurations??[]),secrets=values.flatMap(value=>value.Secrets??[]);
  let componentIdentity='not-applicable',hit=false,otherObservations=0;
  if(row.category==='dependency'){
   const same=item=>canonical(item.PkgName??item.Name)===canonical(row.package)&&version(item.InstalledVersion??item.Version)===version(row.version);
   const packages=values.flatMap(value=>value.Packages??[]);
   componentIdentity=row.version&&[...packages,...vulns].some(same)?'observed':'unproven';
   hit=vulns.some(item=>same(item)&&item.VulnerabilityID===row.rule);
   otherObservations=vulns.filter(item=>item.VulnerabilityID!==row.rule).length;
  }else if(row.category==='configuration'){
   const failures=configs.filter(item=>item.Status===undefined||item.Status==='FAIL');
   hit=failures.some(item=>configRule(item)===row.rule);otherObservations=failures.filter(item=>configRule(item)!==row.rule).length;
  }else{hit=secrets.some(item=>item.RuleID===row.rule);otherObservations=secrets.filter(item=>item.RuleID!==row.rule).length}
  const coverage=values.length?'target-reported':'unknown';let expectationSatisfied=null,observation;
  if(targetValues.some(targetError))observation='target-incomplete';
  else if(row.expected==='unresolved')observation='no-fixed-version';
  else if(row.category==='dependency'&&componentIdentity!=='observed')observation='component-identity-unproven';
  else if(!values.length)observation='target-coverage-unknown';
  else{expectationSatisfied=hit===(row.expected==='present');observation=hit?'expected-rule-reported':'no-expected-rule-reported'}
  return{id:row.id,category:row.category,rule:row.rule,expected:row.expected,expectationSatisfied,observation,coverage,componentIdentity,ruleReported:hit,otherObservations};
 });
 return{version:1,scope:'fixed advisory/rule observations only',r3Qualified:false,projectSafe:false,findingStatus:'unverified',totals:{cases:observations.length,matchedExpectations:observations.filter(row=>row.expectationSatisfied===true).length,mismatches:observations.filter(row=>row.expectationSatisfied===false).length,unknown:observations.filter(row=>row.expectationSatisfied===null).length},cases:observations};
}
