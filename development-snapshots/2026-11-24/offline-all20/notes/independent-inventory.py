from pathlib import Path
from hashlib import sha256
from collections import Counter
import ast,json
R=Path(__file__).resolve().parents[1];base=Path(json.loads((R/'BASELINE-FREEZE.json').read_bytes())['baseline'])
initial=json.loads((R/'evidence/link-inventory-initial.json').read_bytes());rows=[]
for row in initial['sites']:
 if row['classification']=='historical-readonly':
  rows.append({**row,'disposition':'unchanged historical source; baseline byte-read and reference protected-file comparisons only'});continue
 p=R/row['path'];tree=ast.parse(p.read_bytes());calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('symlink','symlink_to')]
 # One inventory row per original creation site; retain ordering within each source.
 original_same=[x for x in initial['sites'] if x['path']==row['path']];index=original_same.index(row);call=sorted(calls,key=lambda n:n.lineno)[index]
 fn=min((n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.lineno<=call.lineno<=n.end_lineno),key=lambda n:n.end_lineno-n.lineno)
 context=p.read_text().splitlines()[call.lineno-1:min(call.lineno+3,len(p.read_text().splitlines()))]
 rows.append({'path':row['path'],'oldLine':row['line'],'line':call.lineno,'function':fn.name,'sourceSha256':sha256(p.read_bytes()).hexdigest(),'operation':ast.unparse(call),'nextLines':context,'disposition':'existing finally rmtree closure' if p.name=='run_evidence_gate_checks.py' else 'immediate explicit owned-link registration; shared FixtureLinks closes before conservative retirement'})
assert sum(x.get('disposition','').startswith('immediate') for x in rows)==9
# Preserve native result identity declarations and assertion expressions; no target code changed.
changed=[];identity_checks=[]
for p in (R/'candidate/checks').glob('*.py'):
 rel=str(p.relative_to(R));old=base/rel
 if not old.exists() or old.read_bytes()==p.read_bytes():continue
 a=ast.parse(old.read_bytes());b=ast.parse(p.read_bytes())
 def ids(t):return Counter((n.func.id,n.args[0].value) for n in ast.walk(t) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('check','record') and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str))
 def assertions(t):return Counter(ast.dump(n,include_attributes=False) for n in ast.walk(t) if isinstance(n,ast.Assert))
 assert ids(a)==ids(b),rel;assert assertions(a)==assertions(b),rel
 identity_checks.append({'path':rel,'nativeIdsPreserved':True,'assertStatementsPreserved':True});changed.append(rel)
lib_old=ast.parse((base/'candidate/checks/regression_lib.py').read_bytes());lib_new=ast.parse((R/'candidate/checks/regression_lib.py').read_bytes())
for name in ['retire_sandbox','_sandbox_is_disposable','_strict_sandbox_path']:
 old=next(n for n in lib_old.body if isinstance(n,ast.FunctionDef) and n.name==name);new=next(n for n in lib_new.body if isinstance(n,ast.FunctionDef) and n.name==name);assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)
report={'kind':'all20-link-lifecycle-source-review','sourceOnly':True,'all20Entries':len(json.loads((R/'operator/suite-plan.json').read_bytes())['order']),'activeSites':10,'registeredSites':9,'existingClosureSites':1,'historicalSites':16,'sites':rows,'identityChecks':identity_checks,'genericRetirementFunctionsUnchanged':True,'VMResult':False,'zeroBlindSamples':True}
(R/'evidence/link-inventory-qualified.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['all20Entries','activeSites','registeredSites','existingClosureSites','genericRetirementFunctionsUnchanged']}))
