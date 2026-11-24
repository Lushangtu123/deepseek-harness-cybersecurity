"""Codex desired contract checks: private records/stubs, no real resources."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import contextlib,importlib.util,io,json,sys,tempfile,copy
P=Path(sys.argv[1]).resolve();R=Path(__file__).resolve().parent;sys.path.insert(0,str(P/'tools'));spec=importlib.util.spec_from_file_location('codex_validation',P/'tools/experiment_runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);rows=[]
def check(name,fn):
 try:details=fn();rows.append({'id':name,'passed':True,'details':details})
 except BaseException as e:rows.append({'id':name,'passed':False,'error':type(e).__name__+':'+str(e)[:1200]})
@contextlib.contextmanager
def sandbox():
 with tempfile.TemporaryDirectory(prefix='codex-validation-',dir=R) as td:
  root=Path(td)
  for n in ['state','prepare','runs']:(root/n).mkdir()
  with patch.multiple(m,ROOT=root,STATE=root/'state',PREPARE=root/'prepare',RUNS=root/'runs'),patch.object(m.guard,'docker',side_effect=AssertionError('real Docker forbidden')),patch.object(m.guard,'stop_group',side_effect=AssertionError('real signals forbidden')):yield root
  m.release_batch_lock()
def recover(**kw):
 with contextlib.redirect_stdout(io.StringIO()) as out,contextlib.redirect_stderr(io.StringIO()) as err:
  try:rc=m.command_recover(**kw)
  except SystemExit as e:rc=e.code
  finally:m.release_batch_lock()
 return rc,out.getvalue(),err.getvalue()
def reserve():
 h='a'*64
 with patch.object(m,'preflight_context',return_value={'bufferParserSha256':h,'bufferTemplateSha256':h,'frozenTemplateSha256':h}):m.reserve_attempt(json.loads((P/'experiment-plan.json').read_bytes()),h,1,{'allowedAttempts':[1]})
 m.release_batch_lock()
def make(root,kind,tag):
 role='run-0001' if kind=='run' else 'compile-0001-'+tag[:8];stage=root/'runs/0001'/('stage-'+tag) if kind=='run' else root/'prepare'/('stage-compile-0001-'+tag);pid,plan=m.write_lifecycle_plan(role,stage,tag,m.container_name(role,tag),attempt=1)
 if kind=='run':plan=m.update_lifecycle_plan(pid,processes={'client':{'spawnState':'not-started'},'observer':{'spawnState':'not-started'}})
 return pid,plan,stage
absent={'removed':True,'state':'absent','queries':{'id':{'state':'absent'},'name':{'state':'absent'},'tag':{'state':'absent'}}}
def setup(root):
 reserve();pid,p,stage=make(root,'run','4'*16);cid,c,cstage=make(root,'compile','5'*16);m.update_attempt(1,prepareId=pid,resourceIntent=dict(p),stageDir=str(stage),processes=p['processes']);m.associate_preparation(1,cid)
 with patch.object(m,'remove_plan_container',return_value=absent):res=recover(number=1)
 assert res[0]==0,('initial valid control',res)
 a=json.loads(m.attempt_path(1).read_bytes());c=json.loads(m.lifecycle_plan_path(cid).read_bytes());assert a['settled'] is True and c['reservationHeld'] is False;cstage.mkdir();(cstage/'SIMULATED.txt').write_text('private reappeared stage')
 return pid,cid,cstage

def views(obj):
 if isinstance(obj,dict):
  if 'effectiveReservationHeld' in obj:yield obj
  for v in obj.values():yield from views(v)
 elif isinstance(obj,list):
  for v in obj:yield from views(v)
def query_effective(number=None,pid=None):
 with contextlib.redirect_stdout(io.StringIO()) as out:
  try:rc=m.command_query(number=number,prepare_id=pid)
  except SystemExit as e:rc=e.code
 data=json.loads(out.getvalue());found=list(views(data));assert found,('query lacks additive effective state',data)
 assert any(x.get('recordState') in ['invalid','unreadable'] and x.get('effectiveReservationHeld') is True and x.get('effectiveCleanupConfirmed') is False and x.get('recordIssues') for x in found),data
 return rc

def invalid_case(field,value,location='parent'):
 with sandbox() as root:
  pid,cid,stage=setup(root);badpath=m.attempt_path(1) if location=='parent' else m.lifecycle_plan_path(cid);data=json.loads(badpath.read_bytes());data[field]=copy.deepcopy(value);m.write_json_document(badpath,data);original=badpath.read_bytes();ops=[]
  with patch.object(m,'remove_plan_container',side_effect=lambda p:ops.append(p) or absent):res=recover(number=1)
  assert res[0]==3,res;assert not ops,('resource calls before rejecting damaged record',len(ops));assert badpath.read_bytes()==original,('damaged original overwritten',field,location)
  if location=='parent':
   good=json.loads(m.lifecycle_plan_path(cid).read_bytes());assert good['reservationHeld'] is True and good['cleanup']['confirmed'] is False,good;query_effective(number=1)
  else:
   good=json.loads(m.attempt_path(1).read_bytes());assert good['reservationHeld'] is True and good['settled'] is False,good;query_effective(pid=cid)
  assert badpath.read_bytes()==original,'query mutated damaged original';assert stage.is_dir();assert json.loads(m.counter_path().read_bytes())['used']==[1]
  return {'exitCode':3,'originalBytesPreserved':True,'validRelatedRecordHeld':True,'effectiveUnknownHoldShown':True,'resourceCalls':0,'counterUsed':[1]}

def related_settlement(field,value):
 with sandbox() as root:
  pid,cid,stage=setup(root);bad=m.lifecycle_plan_path(cid);d=json.loads(bad.read_bytes());d[field]=value;m.write_json_document(bad,d);raw=bad.read_bytes();ops=[]
  with patch.object(m,'remove_plan_container',side_effect=lambda p:ops.append(p) or absent),contextlib.redirect_stderr(io.StringIO()):r=m.settle(1,True,'confirmed',False)
  assert r=='unknown' and not ops,('unsafe settlement',r,ops);assert bad.read_bytes()==raw
  good=json.loads(m.attempt_path(1).read_bytes());assert good['reservationHeld'] is True and good['settled'] is False,good
  assert json.loads(m.counter_path().read_bytes())['used']==[1]
  return {'decision':'unknown','parentHoldPersisted':True,'badBytesPreserved':True,'resourceCalls':0}
for field,value in [('cleanupReceipts','bad'),('resourceIntent',['bad']),('cleanup','bad')]:check('related-settlement-'+field,lambda field=field,value=value:related_settlement(field,value))
def semantic_unknown():
 with sandbox() as root:
  pid,cid,stage=setup(root);(stage/'SIMULATED.txt').unlink();stage.rmdir()
  with patch.object(m,'remove_plan_container',return_value=absent):r=recover(number=1)
  assert r[0]==0,r
  with contextlib.redirect_stderr(io.StringIO()):decision=m.settle(1,True,'unknown',False)
  d=json.loads(m.attempt_path(1).read_bytes());assert decision=='unknown' and d['reservationHeld'] is False and d['settled'] is True,d
  return {'decision':'unknown','resourceSettlementCompleted':True}
check('semantic-unknown-settles-after-cleanup-confirmed',semantic_unknown)
def separate_batch():
 with sandbox() as root:
  pid,cid,stage=setup(root);bad=m.lifecycle_plan_path(cid);d=json.loads(bad.read_bytes());d['cleanupReceipts']='bad';m.write_json_document(bad,d);raw=bad.read_bytes()
  other=root/'other-batch'
  for n in ['state','prepare','runs']:(other/n).mkdir(parents=True)
  with patch.multiple(m,ROOT=other,STATE=other/'state',PREPARE=other/'prepare',RUNS=other/'runs'):reserve();assert m.attempt_path(1).is_file()
  assert bad.read_bytes()==raw
  return {'otherBatchCanReserve':True,'originalBadBytesUnchanged':True}
check('damaged-batch-does-not-block-independent-batch',separate_batch)
v={'kind':'codex-independent-scope-settlement','candidateManifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'allPassed':all(x['passed'] for x in rows),'passed':sum(x['passed'] for x in rows),'total':len(rows),'checks':rows,'realResources':0,'formalTargets':'0/16','r3':'blocked'};print(json.dumps(v,indent=2));raise SystemExit(0 if v['allPassed'] else 1)
