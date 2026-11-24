"""Exercise existing pure filesystem scenarios, not the Linux suites or targets."""
from pathlib import Path
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch
import contextlib,importlib.util,io,json,os,sys,tempfile
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'candidate/checks'));sys.path.insert(0,str(R/'candidate/tools'));import regression_lib as lib
phase=sys.argv[1];out=R/'evidence'/('legacy-links-'+phase+'.json');assert not out.exists()
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
batch=load('probe_batch',R/'operator/full20_batch.py');rows=[]
for file,fn in [('run_regressions.py','scenario_stage_identity'),('run_rev6_checks.py','test_recover_stage_link_and_identity')]:
 root=Path(tempfile.mkdtemp(prefix='legacy-'+phase+'-',dir=R/'checks/tmp'));tmp=root/'candidate/checks/tmp';tmp.mkdir(parents=True);(root/'evidence').mkdir();source=R/'candidate/checks'/file;mod=load('probe_'+fn+phase,source);buf=io.StringIO()
 with patch.object(mod,'TMP',tmp),patch.object(lib,'ROOT',root/'candidate'),patch.object(lib,'_validate_managed_lock',return_value=None),patch.dict(os.environ,{'HARNESS_SAMPLING_LOCK':str(root/'.sampling.lock')}),contextlib.redirect_stdout(buf):result=getattr(mod,fn)()
 links=[]
 for current,dirs,files in os.walk(root,followlinks=False):
  for name in dirs+files:
   p=Path(current)/name
   if p.is_symlink():links.append(str(p.relative_to(root)))
 with patch.object(batch,'_load_guard',return_value=SimpleNamespace()):ok,detail=batch._actual_process_quiescence(root,{},[],[])
 rows.append({'file':'candidate/checks/'+file,'function':fn,'sourceSha256':sha256(source.read_bytes()).hexdigest(),'nativeScenarioAssertion':result.get('passed'),'stdout':buf.getvalue(),'remainingLinks':links,'resourceConfirmed':ok,'resourceDetail':detail,'scratch':str(root)})
report={'kind':'actual-pure-filesystem-fixture-probes','phase':phase,'unitOnly':True,'VMSubmissions':0,'targetExecutions':0,'managedLockValidatorReplacedForUnitOnly':True,'rows':rows};out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'phase':phase,'results':[(x['file'],x['nativeScenarioAssertion'],len(x['remainingLinks']),x['resourceConfirmed']) for x in rows]}))
