"""Desired-behavior regression for four recovery blockers; private temp/stubs only."""
from pathlib import Path
from unittest.mock import patch
from hashlib import sha256
import contextlib,importlib.util,io,json,sys,tempfile,traceback
P=Path(sys.argv[1]).resolve();R=Path(__file__).resolve().parent;sys.path.insert(0,str(P/'tools'))
spec=importlib.util.spec_from_file_location('codex_recovery_round',P/'tools/experiment_runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);results=[]
def must(v,detail):assert v,str(detail)
def run(name,function):
 with tempfile.TemporaryDirectory(prefix='recovery-check-',dir=R) as td:
  root=Path(td)
  for n in ['prepare','state','runs']:(root/n).mkdir()
  with patch.multiple(m,ROOT=root,PREPARE=root/'prepare',STATE=root/'state',RUNS=root/'runs'),patch.object(m.guard,'docker',side_effect=AssertionError('real Docker forbidden')),patch.object(m.guard,'stop_group',side_effect=AssertionError('real signals forbidden')):
   try:detail=function(root);results.append({'name':name,'passed':True,'detail':detail})
   except Exception as e:results.append({'name':name,'passed':False,'error':type(e).__name__+':'+str(e),'traceback':traceback.format_exc()[-1800:]})
   finally:m.release_batch_lock()
def call_recover(**kwargs):
 with contextlib.redirect_stdout(io.StringIO()) as stdout,contextlib.redirect_stderr(io.StringIO()) as stderr:
  try:code=m.command_recover(**kwargs)
  except SystemExit as e:code=e.code
  finally:m.release_batch_lock()
 return code,stdout.getvalue(),stderr.getvalue()
def plan(root,role='bind-all',attempt=None,tag='1'*16):
 is_bind=role=='bind-all'
 stage=root/'prepare'/('stage-bind-'+tag) if is_bind else (root/'runs/0001'/('stage-'+tag) if role=='run-0001' else root/'prepare'/('stage-compile-0001-'+tag))
 if is_bind:role='bind-'+tag[:8]
 pid,p=m.write_lifecycle_plan(role,stage,tag,m.container_name(role,tag),attempt=attempt)
 return pid,p,stage
def wrong_id(root):
 pid,p,stage=plan(root);stage.mkdir();p.update(stageState='created',stageIdentity=m.guard.stage_identity(stage));m.write_json_document(m.lifecycle_plan_path(pid),p)
 valid,_=m.read_lifecycle_plan(pid);must(valid['prepareId']==pid,'valid original plan control must load')
 selected='f'*32 if pid!='f'*32 else 'e'*32;m.write_json_document(m.lifecycle_plan_path(selected),p);calls=[]
 def remove(p):calls.append(p['prepareId']);return {'removed':True,'state':'absent'}
 with patch.object(m,'remove_plan_container',side_effect=remove):code,out,err=call_recover(prepare_id=selected)
 detail={'exitCode':code,'resourceOperations':len(calls),'otherStageRetained':stage.is_dir(),'stderr':err,'validOriginalControl':True};must(code==78 and 'selector' in err and not calls and stage.is_dir(),detail);return detail
run('B1-selector-content-ID-mismatch-before-resource-operations',wrong_id)
def invalid_plan(root):
 pid,p,stage=plan(root,role='run-0001',attempt=1,tag='2'*16);p['stageDir']=str(root/'runs/0001'/('stage-'+'2'*16));p['processes']={'client':{'spawnState':'not-started'},'observer':{'spawnState':'not-started'}}
 record={'attempt':1,'state':'planned','prepareId':pid,'resourceIntent':dict(p),'stageDir':p['stageDir'],'processes':p['processes'],'reservationHeld':True};m.write_json_document(m.attempt_path(1),record);p['imageId']='wrong-image';m.write_json_document(m.lifecycle_plan_path(pid),p);calls=[]
 with patch.object(m.guard,'remove_container_verified',side_effect=lambda value:calls.append(value) or {'removed':False,'state':'unknown'}):code,out,err=call_recover(number=1)
 detail={'exitCode':code,'fallbackOperations':len(calls),'stderr':err};must(code==78 and not calls,detail);return detail
run('B2-invalid-associated-plan-never-falls-back',invalid_plan)
def compile_recover(root):
 pid,p,stage=plan(root,role='compile-0001-33333333',attempt=1,tag='3'*16);calls=[]
 def remove(value):calls.append(value['prepareId']);return {'removed':True,'state':'absent','queries':{'id':{'state':'absent'},'name':{'state':'absent'},'tag':{'state':'absent'}}}
 with patch.object(m,'remove_plan_container',side_effect=remove):code,out,err=call_recover(prepare_id=pid)
 stored=json.loads(m.lifecycle_plan_path(pid).read_bytes());detail={'exitCode':code,'cleanupIds':calls,'reservationHeld':stored['reservationHeld'],'stderr':err,'noTargetRecord':not m.attempt_path(1).exists()};must(code==0 and calls==[pid] and stored['reservationHeld'] is False,detail);return detail
run('B3-compile-plan-recovers-without-target-attempt',compile_recover)
def pre_resource(root):
 p=json.loads((P/'experiment-plan.json').read_bytes());h='a'*64
 with patch.object(m,'preflight_context',return_value={'bufferParserSha256':h,'bufferTemplateSha256':h,'frozenTemplateSha256':h}):r=m.reserve_attempt(p,h,1,{'allowedAttempts':[1]})
 m.release_batch_lock();code,out,err=call_recover(number=1);stored=json.loads(m.attempt_path(1).read_bytes());counter=json.loads(m.counter_path().read_bytes());detail={'exitCode':code,'reservationHeld':stored['reservationHeld'],'counterUsed':counter['used'],'stderr':err};must(code==0 and stored['reservationHeld'] is False and counter['used']==[1],detail);return detail
run('B4-proven-pre-resource-failure-settles-without-refund',pre_resource)
def old_unknown(root):
 record={'version':1,'attempt':1,'state':'unknown','executionState':'not-started','goState':'not-attempted','prepareId':None,'resourceIntent':None,'resourceIdentity':None,'stageDir':None,'stageIdentity':None,'processes':{},'reservationHeld':True,'settled':False,'checkpoints':[]}
 m.write_json_document(m.attempt_path(1),record);code,out,err=call_recover(number=1);stored=json.loads(m.attempt_path(1).read_bytes());detail={'exitCode':code,'reservationHeld':stored['reservationHeld'],'stderr':err};must(code==3 and stored['reservationHeld'] is True,detail);return detail
run('legacy-missing-proof-stays-unconfirmed',old_unknown)
def unreadable(root):
 pid,p,stage=plan(root,role='run-0001',attempt=1,tag='4'*16);p['stageDir']=str(root/'runs/0001'/('stage-'+'4'*16));record={'attempt':1,'state':'planned','prepareId':pid,'resourceIntent':dict(p),'stageDir':p['stageDir'],'processes':{'client':{'spawnState':'not-started'},'observer':{'spawnState':'not-started'}},'reservationHeld':True};m.write_json_document(m.attempt_path(1),record)
 original=m.read_json;calls=[]
 def read(path):
  if Path(path)==m.lifecycle_plan_path(pid):raise PermissionError('synthetic inaccessible plan')
  return original(path)
 with patch.object(m,'read_json',side_effect=read),patch.object(m.guard,'remove_container_verified',side_effect=lambda value:calls.append(value) or {'removed':False,'state':'unknown'}):code,out,err=call_recover(number=1)
 stored=json.loads(m.attempt_path(1).read_bytes());detail={'exitCode':code,'fallbackOperations':len(calls),'reservationHeld':stored['reservationHeld'],'stderr':err};must(code==3 and not calls and stored['reservationHeld'] is True,detail);return detail
run('B2-unreadable-plan-stops-without-fallback',unreadable)
out={'kind':'codex-independent-recovery-desired-behavior','candidateManifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'runnerSha256':sha256((P/'tools/experiment_runner.py').read_bytes()).hexdigest(),'allPassed':all(x['passed'] for x in results),'passed':sum(x['passed'] for x in results),'total':len(results),'checks':results,'realResources':0,'newSelfchecks':0,'formalTargets':'0/16','r3':'blocked'}
print(json.dumps(out,indent=2));raise SystemExit(0 if out['allPassed'] else 1)
