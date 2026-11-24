"""Check parent reservation after a cleaned preparation's stage reappears."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import contextlib,importlib.util,io,json,sys,tempfile
P=Path(sys.argv[1]).resolve();R=Path(__file__).resolve().parent;sys.path.insert(0,str(P/'tools'))
spec=importlib.util.spec_from_file_location('reappeared_association',P/'tools/experiment_runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='association-recheck-',dir=R) as td:
 root=Path(td)
 for n in ['state','prepare','runs']:(root/n).mkdir()
 def recover(**kwargs):
  with contextlib.redirect_stdout(io.StringIO()) as out,contextlib.redirect_stderr(io.StringIO()) as err:
   try:code=m.command_recover(**kwargs)
   except SystemExit as e:code=e.code
   finally:m.release_batch_lock()
  return code,out.getvalue(),err.getvalue()
 with patch.multiple(m,ROOT=root,STATE=root/'state',PREPARE=root/'prepare',RUNS=root/'runs'),patch.object(m.guard,'docker',side_effect=AssertionError('real Docker forbidden')),patch.object(m.guard,'stop_group',side_effect=AssertionError('real signals forbidden')):
  h='a'*64;plan=json.loads((P/'experiment-plan.json').read_bytes())
  with patch.object(m,'preflight_context',return_value={'bufferParserSha256':h,'bufferTemplateSha256':h,'frozenTemplateSha256':h}):record=m.reserve_attempt(plan,h,1,{'allowedAttempts':[1]})
  m.release_batch_lock();tag='5'*16;role='compile-0001-'+tag[:8];stage=root/'prepare'/('stage-compile-0001-'+tag)
  pid,child=m.write_lifecycle_plan(role,stage,tag,m.container_name(role,tag),attempt=1)
  m.update_lifecycle_plan(pid,parentAttempt=1,associationState='linked');m.associate_preparation(1,pid)
  with patch.object(m,'remove_plan_container',return_value={'removed':True,'state':'absent','queries':{'id':{'state':'absent'},'name':{'state':'absent'},'tag':{'state':'absent'}}}):
   first=recover(number=1);before=json.loads(m.attempt_path(1).read_bytes());assert first[0]==0 and before['reservationHeld'] is False
   stage.mkdir();(stage/'SIMULATED.txt').write_text('benign reappeared temporary stage')
   second=recover(prepare_id=pid);after=json.loads(m.attempt_path(1).read_bytes());child_after=json.loads(m.lifecycle_plan_path(pid).read_bytes())
  reproduced=second[0]==3 and after['reservationHeld'] is False and after['settled'] is True and child_after['reservationHeld'] is True and stage.is_dir()
  v={'kind':'codex-direct-child-recovery-counterexample','candidateManifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'runnerSha256':sha256((P/'tools/experiment_runner.py').read_bytes()).hexdigest(),'confirmedBlockers':['B9-direct-child-recovery-leaves-parent-stale'] if reproduced else [],'reproduced':reproduced,'firstRecoverExit':first[0],'firstParentResourcePhase':before.get('resourceProof',{}).get('phase'),'secondRecoverExit':second[0],'secondDiagnostic':second[2],'parentReservationHeld':after['reservationHeld'],'parentSettled':after['settled'],'parentCleanupConfirmed':after.get('cleanup',{}).get('confirmed'),'associatedPreparationReservationHeld':child_after['reservationHeld'],'stageRetained':stage.is_dir(),'targetCounter':json.loads(m.counter_path().read_bytes()),'realResources':0,'newSelfchecks':0,'formalTargets':'0/16','r3':'blocked','scope':'Private synthetic files plus pure real task-state functions and resource stubs; original candidate unchanged.'}
print(json.dumps(v,indent=2))
