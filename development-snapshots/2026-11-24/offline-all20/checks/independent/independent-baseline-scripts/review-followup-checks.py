"""Validate the completed review's two bounded source findings; pure/stubs only."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import contextlib,importlib.util,io,json,sys,tempfile
P=Path(sys.argv[1]).resolve();R=Path(__file__).resolve().parent;sys.path.insert(0,str(P/'tools'));s=importlib.util.spec_from_file_location('review_followup',P/'tools/experiment_runner.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);rows=[]
@contextlib.contextmanager
def sandbox():
 with tempfile.TemporaryDirectory(prefix='review-followup-',dir=R) as td:
  root=Path(td)
  for n in ['state','prepare','runs']:(root/n).mkdir()
  with patch.multiple(m,ROOT=root,STATE=root/'state',PREPARE=root/'prepare',RUNS=root/'runs'),patch.object(m.guard,'docker',side_effect=AssertionError('real Docker forbidden')),patch.object(m.guard,'stop_group',side_effect=AssertionError('real signals forbidden')):
   yield root
  m.release_batch_lock()
def reserve():
 h='a'*64
 with patch.object(m,'preflight_context',return_value={'bufferParserSha256':h,'bufferTemplateSha256':h,'frozenTemplateSha256':h}):m.reserve_attempt(json.loads((P/'experiment-plan.json').read_bytes()),h,1,{'allowedAttempts':[1]})
 m.release_batch_lock()
def recover(**kw):
 exception=None
 with contextlib.redirect_stdout(io.StringIO()) as out,contextlib.redirect_stderr(io.StringIO()) as err:
  try:code=m.command_recover(**kw)
  except SystemExit as e:code=e.code
  except Exception as e:code=None;exception=type(e).__name__
  finally:m.release_batch_lock()
 return code,exception,out.getvalue(),err.getvalue()
def make(root,kind,tag):
 role='run-0001' if kind=='run' else 'compile-0001-'+tag[:8];stage=root/'runs/0001'/('stage-'+tag) if kind=='run' else root/'prepare'/('stage-compile-0001-'+tag)
 pid,plan=m.write_lifecycle_plan(role,stage,tag,m.container_name(role,tag),attempt=1)
 if kind=='run':plan=m.update_lifecycle_plan(pid,processes={'client':{'spawnState':'not-started'},'observer':{'spawnState':'not-started'}})
 return pid,plan,stage
absent={'removed':True,'state':'absent','queries':{'id':{'state':'absent'},'name':{'state':'absent'},'tag':{'state':'absent'}}}
for mode in ['missing','malformed','permission']:
 with sandbox() as root:
  reserve();pid,plan,stage=make(root,'run','4'*16);cid,child,cstage=make(root,'compile','5'*16)
  m.update_attempt(1,prepareId=pid,resourceIntent=dict(plan),stageDir=str(stage),processes=plan['processes']);m.associate_preparation(1,cid)
  with patch.object(m,'remove_plan_container',return_value=absent):first=recover(number=1)
  assert first[0]==0,first
  cstage.mkdir();(cstage/'SIMULATED.txt').write_text('reappeared associated private stage');path=m.lifecycle_plan_path(pid)
  if mode=='missing':path.unlink();cm=contextlib.nullcontext()
  elif mode=='malformed':path.write_bytes(b'{bad-json');cm=contextlib.nullcontext()
  else:
   original=m.read_json
   def read(p):
    if Path(p)==path:raise PermissionError('independent target-plan read denial')
    return original(p)
   cm=patch.object(m,'read_json',side_effect=read)
  operations=[]
  with cm,patch.object(m,'remove_plan_container',side_effect=lambda p:operations.append(p) or absent):second=recover(number=1)
  parent=json.loads(m.attempt_path(1).read_bytes());c=json.loads(m.lifecycle_plan_path(cid).read_bytes())
  reproduced=second[0]==3 and parent['reservationHeld'] is True and c['reservationHeld'] is False and c.get('cleanup',{}).get('confirmed') is True and cstage.is_dir()
  rows.append({'id':'B10-target-plan-unavailable-child-stale:'+mode,'reproduced':reproduced,'firstExit':first[0],'secondExit':second[0],'secondException':second[1],'parentReservationHeld':parent['reservationHeld'],'childReservationHeld':c['reservationHeld'],'childCleanupConfirmed':c.get('cleanup',{}).get('confirmed'),'childStageRetained':cstage.is_dir(),'secondResourceOperations':len(operations)})
for mode in ['malformed','permission','io']:
 with sandbox() as root:
  reserve();pid,plan,stage=make(root,'run','6'*16);m.update_attempt(1,prepareId=pid,resourceIntent=dict(plan),stageDir=str(stage),processes=plan['processes']);path=m.attempt_path(1)
  if mode=='malformed':path.write_bytes(b'{bad-json');cm=contextlib.nullcontext()
  else:
   original=m.read_json
   def read(p):
    if Path(p)==path:raise PermissionError('independent attempt denial') if mode=='permission' else OSError('independent attempt IO')
    return original(p)
   cm=patch.object(m,'read_json',side_effect=read)
  operations=[]
  with cm,patch.object(m,'remove_plan_container',side_effect=lambda p:operations.append(p) or absent):res=recover(prepare_id=pid)
  rows.append({'id':'D1-direct-run-attempt-read-classification:'+mode,'reproduced':res[0] is None and res[1] is not None,'exitCode':res[0],'uncaughtException':res[1],'expectedExit':3,'resourceOperations':len(operations),'classification':'non-destructive-interface-gap; B7 scope interpretation separated'})
v={'kind':'codex-review-findings-validation','manifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'checks':rows,'allReproduced':all(x['reproduced'] for x in rows),'confirmedBlockers':['B10-target-plan-unavailable-child-stale'] if all(x['reproduced'] for x in rows[:3]) else [],'diagnosticGaps':['D1-direct-run-attempt-read-classification'],'realResources':0,'formalTargets':'0/16','r3':'blocked'}
print(json.dumps(v,indent=2))
