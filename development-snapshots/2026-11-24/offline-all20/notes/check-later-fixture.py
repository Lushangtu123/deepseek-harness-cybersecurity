"""Independent local counterexample for a later suite; fake resources, no target."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util,json,os,sys,tempfile
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'candidate/checks'))
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('later_close_fixture',R/'candidate/checks/run_recovery_close_checks.py');b=load('later_guard',R/'operator/full20_batch.py')
root=Path(tempfile.mkdtemp(prefix='later-fixture-counterexample-',dir=R/'checks/tmp'));(root/'candidate/checks/tmp').mkdir(parents=True);(root/'evidence').mkdir()
runner=SimpleNamespace(ROOT=root,PREPARE=root,RUNS=root,STATE=root,_PREFLIGHT_RESULT=None,release_batch_lock=lambda:None)
with patch.object(f,'TMP',root/'candidate/checks/tmp'),patch.object(f.regression_lib,'ROOT',root/'candidate'),patch.object(f.regression_lib,'_validate_managed_lock',return_value=None),patch.dict(os.environ,{'HARNESS_SAMPLING_LOCK':str(root/'.sampling.lock')}):
 w=f.Workspace(runner,'later-link-');target=w.prepare/'original';target.mkdir();link=w.prepare/'link-stage';link.symlink_to(target,target_is_directory=True)
 strict=f.regression_lib._strict_sandbox_path(w.root);disposable=f.regression_lib._sandbox_is_disposable(w.root);assert strict is True and disposable is False
 w.close();retained=link.is_symlink();assert retained
with patch.object(b,'_load_guard',return_value=SimpleNamespace()):ok,detail=b._actual_process_quiescence(root,{},[],[])
result={'unitOnly':True,'targetExecutions':0,'VMSubmissions':0,'suite':'recovery-close-24','strictFixturePath':strict,'genericDisposalRefused':not disposable,'linkRetainedAfterClose':retained,'resourceConfirmed':ok,'detail':detail,'scratch':str(root),'candidateUnchanged':True,'diagnosis':'Same retained directory-link pattern exists in a later suite, outside the specifically approved B8 file repair.'}
assert ok is False and detail['reason']=='linked-directory'
(R/'evidence/later-fixture-counterexample.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
