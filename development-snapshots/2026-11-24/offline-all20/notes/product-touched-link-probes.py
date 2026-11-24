"""Existing pure scenarios with resource doubles; deny all subprocess starts."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import contextlib,importlib.util,io,json,os,sys,tempfile,traceback
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'candidate/checks'));sys.path.insert(0,str(R/'candidate/tools'))
import regression_lib as lib

def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
c=load('probe_consumers',R/'candidate/checks/run_consumer_closure_checks.py');u=c.U;w=load('probe_recovery',R/'candidate/checks/run_recovery_close_checks.py');v=load('probe_rev8',R/'candidate/checks/run_rev8_checks.py');support=sys.modules['rev8_support'];rows=[]
cases=[(c,'settlement_child_variants'),(c,'reservation_blocked'),(u,'b8_directory_symlink'),(w,'b1_stage_paths'),(w,'b2_identity_journal'),(v,'test_final_symlink_blocked'),(v,'test_intermediate_symlink_blocked')]
for module,name in cases:
 root=Path(tempfile.mkdtemp(prefix='product-link-probe-',dir=R/'checks/tmp'));tmp=root/'candidate/checks/tmp';tmp.mkdir(parents=True);(root/'.sampling.lock').write_bytes(b'');(root/'evidence').mkdir();buf=io.StringIO();row={'function':name,'moduleSha256':sha256(Path(module.__file__).read_bytes()).hexdigest(),'scratch':str(root)}
 try:
  with contextlib.ExitStack() as st:
   for m in [c,u,w,v,support]:st.enter_context(patch.object(m,'TMP',tmp))
   st.enter_context(patch.object(lib,'ROOT',root/'candidate'));st.enter_context(patch.dict(os.environ,{'HARNESS_SAMPLING_LOCK':str(root/'.sampling.lock')}));st.enter_context(contextlib.redirect_stdout(buf))
   st.enter_context(patch('subprocess.run',side_effect=AssertionError('subprocess prohibited in pure probe')));st.enter_context(patch('subprocess.Popen',side_effect=AssertionError('Popen prohibited in pure probe')))
   if module is v:answer=getattr(module,name)();passed=answer.get('passed') is True
   else:
    runner=u.load_runner(R/'candidate/tools');answer=getattr(module,name)(runner,runner.guard);passed=answer[0] is True
  row.update(assertionsPassed=passed,result=answer)
 except Exception as error:row.update(assertionsPassed=False,errorType=type(error).__name__,reason=str(error),traceback=traceback.format_exc())
 links=[]
 for current,dirs,files in os.walk(root,followlinks=False):
  for n in dirs+files:
   p=Path(current)/n
   if p.is_symlink():links.append(str(p.relative_to(root)))
 row.update(remainingLinks=links,stdout=buf.getvalue());rows.append(row)
report={'kind':'actual-existing-product-touched-fixture-probes','unitOnly':True,'platform':sys.platform,'subprocessStartsDenied':True,'managedLockFileActuallyCreatedForUnit':True,'VMSubmissions':0,'targetExecutions':0,'allPassed':all(x['assertionsPassed'] and not x['remainingLinks'] for x in rows),'rows':rows}
(R/'evidence/product-touched-link-probes.json').write_text(json.dumps(report,indent=2,default=str)+'\n');print(json.dumps({'allPassed':report['allPassed'],'rows':[(x['function'],x['assertionsPassed'],len(x['remainingLinks']),x.get('reason')) for x in rows]}));raise SystemExit(0 if report['allPassed'] else 3)
