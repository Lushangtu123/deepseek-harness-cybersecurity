"""Independent pure safety assertions for B5–B7, no target/resource execution."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import contextlib,importlib.util,io,json,sys,tempfile
P=Path(sys.argv[1]).resolve();R=Path(__file__).resolve().parent;sys.path.insert(0,str(P/'tools'))
spec=importlib.util.spec_from_file_location('independent_association',P/'tools/experiment_runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rows=[]
def check(name,fn):
 try:
  details=fn();rows.append({'id':name,'passed':True,'details':details})
 except BaseException as e:
  rows.append({'id':name,'passed':False,'error':type(e).__name__+':'+str(e)})
def reserve():
 h='a'*64
 with patch.object(m,'preflight_context',return_value={'bufferParserSha256':h,'bufferTemplateSha256':h,'frozenTemplateSha256':h}):v=m.reserve_attempt(json.loads((P/'experiment-plan.json').read_bytes()),h,1,{'allowedAttempts':[1]})
 m.release_batch_lock();return v
def recover(**kw):
 with contextlib.redirect_stdout(io.StringIO()) as out,contextlib.redirect_stderr(io.StringIO()) as err:
  try:code=m.command_recover(**kw)
  except SystemExit as e:code=e.code
  finally:m.release_batch_lock()
 return code,out.getvalue(),err.getvalue()
def parent():return json.loads(m.attempt_path(1).read_bytes())
def child(root,unknown=False):
 tag='6'*16;role='compile-0001-'+tag[:8];stage=root/'prepare'/('stage-compile-0001-'+tag)
 pid,c=m.write_lifecycle_plan(role,stage,tag,m.container_name(role,tag),attempt=1)
 if unknown:
  stage.mkdir();(stage/'SIMULATED.txt').write_text('benign original stage')
  m.update_lifecycle_plan(pid,stageState='created',stageIdentity=m.guard.stage_identity(stage),processes={'client':{'spawnState':'unknown','reason':'independent unconfirmed original identity'}})
 return pid,stage
@contextlib.contextmanager
def sandbox():
 with tempfile.TemporaryDirectory(prefix='codex-association-',dir=R) as td:
  root=Path(td)
  for n in ['state','prepare','runs']:(root/n).mkdir()
  with patch.multiple(m,ROOT=root,STATE=root/'state',PREPARE=root/'prepare',RUNS=root/'runs'),patch.object(m.guard,'docker',side_effect=AssertionError('real Docker forbidden')),patch.object(m.guard,'stop_group',side_effect=AssertionError('real signals forbidden')):
   yield root
  m.release_batch_lock()
def held():
 a=parent();assert a['reservationHeld'] is True and a.get('settled') is not True,a
 assert json.loads(m.counter_path().read_bytes())['used']==[1]
 return a
def reappearance():
 with sandbox() as root:
  reserve();pid,stage=child(root);m.update_lifecycle_plan(pid,parentAttempt=1,associationState='linked');getattr(m,'associate_preparation',getattr(m,'associate_prepare_plan',None))(1,pid)
  absent={'removed':True,'state':'absent','queries':{'id':{'state':'absent'},'name':{'state':'absent'},'tag':{'state':'absent'}}}
  with patch.object(m,'remove_plan_container',return_value=absent):
   first=recover(number=1);assert first[0]==0,first
   stage.mkdir();(stage/'SIMULATED.txt').write_text('benign reappearance')
   second=recover(number=1);a=parent();c=json.loads(m.lifecycle_plan_path(pid).read_bytes())
   assert second[0]==3,second
   held();assert a.get('cleanup',{}).get('confirmed') is not True and c['reservationHeld'] is True and stage.is_dir()
   repeat=recover(number=1);assert repeat[0]==3,repeat;held()
   (stage/'SIMULATED.txt').unlink();stage.rmdir()
   third=recover(number=1);assert third[0]==0,third
   final=parent();assert final['reservationHeld'] is False and final['settled'] is True
  return {'initial':first[0],'reappeared':second[0],'repeated':repeat[0],'normalAgain':third[0],'used':[1]}
def interrupted(boundary):
 with sandbox() as root:
  pid,stage=child(root,True);reserve();calls=[];original_parent=m.update_attempt;original_child=m.update_lifecycle_plan
  def wrap_parent(number,**fields):
   if any('associat' in k.lower() for k in fields):
    calls.append('parent')
    if len(calls)==boundary:raise OSError('independent association write '+str(boundary))
   return original_parent(number,**fields)
  def wrap_child(selector,**fields):
   if any('associat' in k.lower() or k=='parentAttempt' for k in fields):
    calls.append('child')
    if len(calls)==boundary:raise OSError('independent association write '+str(boundary))
   return original_child(selector,**fields)
  raised=False
  with patch.object(m,'update_attempt',side_effect=wrap_parent),patch.object(m,'update_lifecycle_plan',side_effect=wrap_child):
   try:m.associate_existing_preparations(1)
   except (OSError,RuntimeError,SystemExit):raised=True
  assert len(calls)>=boundary,{'boundaryNotReached':boundary,'calls':calls}
  code,out,err=recover(number=1);assert code==3,(code,out,err)
  held();assert stage.is_dir();assert json.loads(m.lifecycle_plan_path(pid).read_bytes())['reservationHeld'] is True
  repeat=recover(number=1);assert repeat[0]==3,repeat;held()
  return {'writeOrder':calls,'failureObserved':raised,'recoverExit':code,'repeatExit':repeat[0],'stageRetained':True}
def reverse_only():
 with sandbox() as root:
  pid,stage=child(root,True);reserve();m.update_lifecycle_plan(pid,parentAttempt=1,associationState='linked')
  assert parent().get('associatedPrepareIds')==[]
  code,out,err=recover(number=1);assert code==3,(code,out,err);held();assert stage.is_dir()
  return {'recoverExit':code,'stageRetained':True}
def bad_plan(mode):
 with sandbox() as root:
  reserve();pid='7'*32;m.update_attempt(1,prepareId=pid);path=m.lifecycle_plan_path(pid);path.parent.mkdir(parents=True,exist_ok=True)
  if mode=='malformed':path.write_bytes(b'{bad-json')
  if mode in ('permission','io'):
   path.write_bytes(b'{}');orig=m.read_json
   def read(p):
    if Path(p)==path:raise PermissionError('independent denied') if mode=='permission' else OSError('independent IO')
    return orig(p)
   cm=patch.object(m,'read_json',side_effect=read)
  else:cm=contextlib.nullcontext()
  with cm:code,out,err=recover(prepare_id=pid)
  assert code==3,(code,out,err);held();return {'recoverExit':code,'diagnostic':err}
def unreadable_reverse(mode):
 with sandbox() as root:
  pid,stage=child(root,True);reserve();m.update_lifecycle_plan(pid,parentAttempt=1,associationState='linked');path=m.lifecycle_plan_path(pid)
  if mode=='malformed':path.write_bytes(b'{bad-json');cm=contextlib.nullcontext()
  else:
   orig=m.read_json
   def read(p):
    if Path(p)==path:raise PermissionError('independent reverse unreadable')
    return orig(p)
   cm=patch.object(m,'read_json',side_effect=read)
  with cm:code,out,err=recover(number=1)
  assert code==3,(code,out,err);held();assert stage.is_dir();return {'recoverExit':code,'stageRetained':True}
def guard_before_operations():
 with sandbox() as root:
  reserve();pid,stage=child(root);m.update_lifecycle_plan(pid,parentAttempt=1,associationState='linked');getattr(m,'associate_preparation',getattr(m,'associate_prepare_plan',None))(1,pid)
  absent={'removed':True,'state':'absent','queries':{'id':{'state':'absent'},'name':{'state':'absent'},'tag':{'state':'absent'}}}
  with patch.object(m,'remove_plan_container',return_value=absent):assert recover(number=1)[0]==0
  seen=[]
  def remove(p):
   a=parent();seen.append(a);assert a.get('reservationHeld') is True and a.get('settled') is not True and a.get('cleanup',{}).get('confirmed') is not True,a
   return absent
  with patch.object(m,'remove_plan_container',side_effect=remove):code,out,err=recover(number=1)
  assert code==0 and seen,(code,err,len(seen));return {'resourceQueries':len(seen),'parentHeldBeforeQueries':True}
def initial_journal_failure():
 with sandbox() as root:
  reserve();pid,stage=child(root);m.update_lifecycle_plan(pid,parentAttempt=1,associationState='linked');getattr(m,'associate_preparation',getattr(m,'associate_prepare_plan',None))(1,pid)
  operations=[]
  with patch.object(m,'update_attempt',side_effect=OSError('independent cannot persist cleanup checking')),patch.object(m,'remove_plan_container',side_effect=lambda p:operations.append(p) or {'removed':True,'state':'absent'}):code,out,err=recover(number=1)
  assert code==3 and operations==[],(code,err,len(operations));return {'exitCode':code,'resourceOperations':len(operations)}
check('B5-parent-held-before-resource-queries',guard_before_operations)
check('B5-initial-journal-failure-has-zero-resource-operations',initial_journal_failure)
check('B5-reappeared-child-parent-current-reservation',reappearance)
for n in [1,2,3]:check('B6-association-write-boundary-'+str(n),lambda n=n:interrupted(n))
check('B6-reverse-child-cannot-be-ignored',reverse_only)
for mode in ['missing','malformed','permission','io']:check('B7-direct-'+mode,lambda mode=mode:bad_plan(mode))
for mode in ['permission','malformed']:check('B6-reverse-log-'+mode,lambda mode=mode:unreadable_reverse(mode))
v={'kind':'codex-independent-association-safety','candidateManifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'runnerSha256':sha256((P/'tools/experiment_runner.py').read_bytes()).hexdigest(),'passed':sum(x['passed'] for x in rows),'total':len(rows),'allPassed':all(x['passed'] for x in rows),'checks':rows,'realResources':0,'formalTargets':'0/16','r3':'blocked'}
print(json.dumps(v,indent=2));raise SystemExit(0 if v['allPassed'] else 1)
