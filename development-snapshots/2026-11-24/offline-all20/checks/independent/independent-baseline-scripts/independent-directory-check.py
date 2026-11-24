"""Actual private directory read-denial, no resource/target operations."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import contextlib,importlib.util,io,json,sys,tempfile
P=Path(sys.argv[1]).resolve();R=Path(__file__).resolve().parent;sys.path.insert(0,str(P/'tools'));s=importlib.util.spec_from_file_location('directory_counter',P/'tools/experiment_runner.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='directory-read-check-',dir=R) as td:
 root=Path(td)
 for n in ['state','prepare','runs']:(root/n).mkdir()
 with patch.multiple(m,ROOT=root,STATE=root/'state',PREPARE=root/'prepare',RUNS=root/'runs'),patch.object(m.guard,'docker',side_effect=AssertionError('real Docker forbidden')),patch.object(m.guard,'stop_group',side_effect=AssertionError('real signals forbidden')):
  tag='9'*16;role='compile-0001-'+tag[:8];stage=root/'prepare'/('stage-compile-0001-'+tag)
  pid,c=m.write_lifecycle_plan(role,stage,tag,m.container_name(role,tag),attempt=1);stage.mkdir();(stage/'SIMULATED.txt').write_text('retained private stage')
  m.update_lifecycle_plan(pid,parentAttempt=1,stageState='created',stageIdentity=m.guard.stage_identity(stage),processes={'client':{'spawnState':'unknown','reason':'unconfirmed independent resource'}})
  h='a'*64
  with patch.object(m,'preflight_context',return_value={'bufferParserSha256':h,'bufferTemplateSha256':h,'frozenTemplateSha256':h}):m.reserve_attempt(json.loads((P/'experiment-plan.json').read_bytes()),h,1,{'allowedAttempts':[1]})
  m.release_batch_lock();directory=m.plans_dir();before=json.loads(m.attempt_path(1).read_bytes());directory.chmod(0)
  try:
   try:list(directory.iterdir());listing_denied=False
   except PermissionError:listing_denied=True
   with contextlib.redirect_stdout(io.StringIO()) as out,contextlib.redirect_stderr(io.StringIO()) as err:
    try:rc=m.command_recover(number=1)
    except SystemExit as e:rc=e.code
    finally:m.release_batch_lock()
   after=json.loads(m.attempt_path(1).read_bytes())
  finally:directory.chmod(0o700)
  child=json.loads(m.lifecycle_plan_path(pid).read_bytes());reproduced=listing_denied and rc==0 and after.get('settled') is True and after['reservationHeld'] is False and child['reservationHeld'] is True and stage.is_dir()
  result={'kind':'codex-private-directory-read-counterexample','manifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'listingPermissionDenied':listing_denied,'recoverExitCode':rc,'stderr':err.getvalue(),'parentAssociatedIds':before['associatedPrepareIds'],'reverseChildParent':child['parentAttempt'],'parentSettled':after.get('settled'),'parentReservationHeld':after.get('reservationHeld'),'childReservationHeld':child['reservationHeld'],'childStageRetained':stage.is_dir(),'counterUsed':json.loads(m.counter_path().read_bytes())['used'],'reproduced':reproduced,'confirmedBlockers':['B8-unreadable-association-directory-can-settle-parent'] if reproduced else [],'realResources':0,'formalTargets':'0/16','r3':'blocked'}
print(json.dumps(result,indent=2))
