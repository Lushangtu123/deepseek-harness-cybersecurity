"""Controlled archive synthetic tests; no daemon, network or privilege escalation."""
import importlib.util,json,os,tarfile,shutil,io
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import unittest
HERE=Path(__file__).resolve().parent
class ArchiveTest(unittest.TestCase):
 def setUp(self):
  spec=importlib.util.spec_from_file_location('snapshot',HERE/'reviewer_snapshot.py');self.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.api)
  self.s=self.api.storage_module(sha256((HERE/'reviewer_storage.py').read_bytes()).hexdigest())
  self.assertTrue(callable(getattr(self.s,'archive_plan',None)),'archive API missing')
  tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve();self.cache=self.root/'attempts';self.cache.mkdir(mode=0o700)
  self.policy=self.s.policy_for(self.cache,{'minFreeBytes':0});self.calls=[]
 def job(self,identity='a'*32,**overrides):
  path=self.cache/('review-'+identity);path.mkdir(mode=0o700);(path/'docker-config').mkdir(mode=0o700)
  (path/'operation.lock').touch(mode=0o600)
  value={'version':1,'id':identity,'directory':str(path),'state':'recovered','name':'harness-review-'+identity,'imageId':'sha256:'+'a'*64,
   'snapshotSha256':'b'*64,'inputSha256':'c'*64,'datasetSha256':'d'*64,'freezeSha256':'e'*64,
   'creationAttempted':False,'createSucceeded':False,'containerObserved':False,'containerId':None,'clientCounter':0,'clients':[],
   'cleanup':{'confirmed':True,'idAbsent':True,'nameAbsent':True,'clientsStopped':True,'creationResolved':True,'errors':[]},
   'stageRemoved':True,'finishedAt':'2026-10-01T00:00:00+00:00',**overrides}
  self.s.atomic(path/'attempt.json',value);return path
 def probe(self,transaction,source,job):
  self.calls.append(str(source));return {'confirmed':True,'readOnly':True,'containerAbsent':True,'clientsStopped':True}
 def plan(self,ids=None):return self.s.archive_plan(self.policy,self.api,attempt_ids=ids)
 def apply(self,plan,**options):return self.s.archive_apply(self.policy,plan,self.api,probe=self.probe,**options)
 def test_plan_v2_is_readonly_bound_and_old_plan_not_executable(self):
  path=self.job();plan=self.plan();self.assertEqual(plan['version'],2);self.assertEqual(len(plan['entries']),1)
  self.assertFalse(Path(self.policy['controlRoot']).exists());self.assertIn('storageSha256',plan['producer'])
  self.assertEqual(plan['entries'][0]['source'],str(path));self.assertEqual(plan['policy']['recycleSeconds'],7*86400)
  with self.assertRaises(ValueError):self.apply({'version':1,'entries':[]})
 def test_archive_and_restore_preserve_exact_original_record(self):
  path=self.job();raw=(path/'attempt.json').read_bytes();plan=self.plan();result=self.apply(plan)
  row=result['entries'][0];self.assertEqual(row['state'],'committed');self.assertFalse(path.exists())
  recycle=Path(row['recycle']);archive=Path(row['archive']);self.assertEqual((recycle/'attempt.json').read_bytes(),raw)
  with tarfile.open(archive,'r:gz') as bundle:self.assertEqual(bundle.extractfile('attempt.json').read(),raw)
  self.assertEqual(self.api.status(path)['state'],'archived');self.assertEqual(self.api.recover(path)['recoveryAction'],'restore-required-no-analysis')
  restored=self.s.archive_restore(self.policy,result['id'],self.api)
  self.assertEqual(restored['entries'][0]['state'],'restored');self.assertEqual((path/'attempt.json').read_bytes(),raw)
  self.assertEqual(self.api.status(path)['state'],'recovered');self.assertEqual(len(self.calls),1)
 def test_tampered_expired_or_changed_fingerprint_does_not_move(self):
  path=self.job();plan=self.plan();bad=json.loads(json.dumps(plan));bad['uid']+=1
  with self.assertRaises(ValueError):self.apply(bad)
  future=datetime.now(timezone.utc)+timedelta(minutes=16)
  with self.assertRaises(ValueError):self.apply(plan,clock=future)
  (path/'attempt.json').write_bytes((path/'attempt.json').read_bytes()+b'\n')
  with self.assertRaises(ValueError):self.apply(plan)
  self.assertTrue(path.exists());self.assertEqual(self.calls,[])
 def test_unknown_linked_hardlinked_and_mismatched_cid_are_preserved(self):
  path=self.job(state='cleanup-unconfirmed');self.assertEqual(self.plan()['entries'],[])
  shutil.rmtree(path);path=self.job();(path/'container.cid').write_text('c'*64+'\n');(path/'container.cid').chmod(0o600)
  self.assertEqual(self.plan()['entries'],[])
  (path/'container.cid').unlink();os.link(path/'attempt.json',path/'client-1.stdout')
  self.assertEqual(self.plan()['entries'],[])
  (path/'client-1.stdout').unlink();(path/'bad').symlink_to('/missing')
  self.assertEqual(self.plan()['entries'],[])
 def test_batch_limit_and_no_plan_code_execution(self):
  for i in range(9):self.job(f'{i:032x}')
  plan=self.plan();self.assertEqual(len(plan['entries']),8)
  plan['module']='/arbitrary/project.py';plan['planSha256']=self.s.digest({k:v for k,v in plan.items() if k!='planSha256'})
  with self.assertRaises(ValueError):self.apply(plan)
 def test_active_task_lock_protected(self):
  path=self.job()
  with self.api.operation_lock(path):self.assertEqual(self.plan()['entries'],[])
 def test_fresh_resource_failure_never_moves_source(self):
  path=self.job();plan=self.plan()
  with self.assertRaises(ValueError):self.s.archive_apply(self.policy,plan,self.api,probe=lambda *args:{'confirmed':False})
  self.assertTrue(path.exists())
 def test_duplicate_apply_queries_original_transaction_without_probe(self):
  self.job();plan=self.plan();one=self.apply(plan);two=self.apply(plan)
  self.assertEqual(one['id'],two['id']);self.assertEqual(two['entries'][0]['state'],'committed');self.assertEqual(len(self.calls),1)
 def test_interrupt_before_and_after_move_queries_without_reexecution(self):
  for phase in ['verified','moved']:
   with self.subTest(phase=phase):
    identity=('b' if phase=='verified' else 'c')*32;path=self.job(identity);plan=self.plan([identity]);raw=(path/'attempt.json').read_bytes()
    def crash(event):
     if event==phase:raise SystemExit('synthetic crash')
    with self.assertRaises(SystemExit):self.apply(plan,fault=crash)
    result=self.s.archive_status(self.policy,plan['id'],self.api)
    row=result['entries'][0];self.assertEqual(row['state'],'not-moved' if phase=='verified' else 'committed')
    present=path if path.exists() else Path(row['recycle']);self.assertEqual((present/'attempt.json').read_bytes(),raw)
    count=len(self.calls);self.apply(plan);self.assertEqual(len(self.calls),count)
 def test_restore_refuses_existing_path_even_empty_and_idempotent(self):
  path=self.job();result=self.apply(self.plan());path.mkdir(mode=0o700)
  with self.assertRaises(ValueError):self.s.archive_restore(self.policy,result['id'],self.api)
  self.assertEqual(list(path.iterdir()),[]);path.rmdir();self.s.archive_restore(self.policy,result['id'],self.api)
  self.assertEqual(self.s.archive_restore(self.policy,result['id'],self.api)['entries'][0]['state'],'restored')
 def test_archive_corruption_refuses_restore_and_retains_recycle(self):
  self.job();result=self.apply(self.plan());row=result['entries'][0];Path(row['archive']).write_bytes(b'corrupt')
  with self.assertRaises(ValueError):self.s.archive_restore(self.policy,result['id'],self.api)
  self.assertTrue(Path(row['recycle']).exists())
 def test_retention_expiry_produces_list_never_deletes(self):
  self.job();result=self.apply(self.plan());row=result['entries'][0]
  report=self.s.reconcile(self.policy,self.api,clock=datetime.now(timezone.utc)+timedelta(days=8))
  self.assertEqual(report['cleanupCandidates'][0]['transactionId'],result['id']);self.assertFalse(report['deleteEnabled'])
  self.assertTrue(Path(row['recycle']).exists());self.assertTrue(Path(row['archive']).exists())
 def test_atomic_move_never_overwrites_existing_destination(self):
  source=self.root/'source';destination=self.root/'dest';source.mkdir();destination.mkdir()
  with self.assertRaises(OSError):self.s.rename_noreplace(source,destination)
  self.assertTrue(source.exists());self.assertTrue(destination.exists())
 def test_archive_only_restore_preserves_bytes_without_chown(self):
  path=self.job();raw=(path/'attempt.json').read_bytes();result=self.apply(self.plan());row=result['entries'][0]
  shutil.rmtree(row['recycle']) # Explicit synthetic operator cleanup, never product cleanup.
  restored=self.s.archive_restore(self.policy,result['id'],self.api)
  self.assertEqual((path/'attempt.json').read_bytes(),raw);self.assertEqual(restored['entries'][0]['restoreKind'],'archive-copy')
 def test_restore_interruption_finishes_original_request(self):
  path=self.job();result=self.apply(self.plan());raw=Path(result['entries'][0]['recycle'],'attempt.json').read_bytes()
  def crash(event):raise SystemExit('restore crash')
  with self.assertRaises(SystemExit):self.s.archive_restore(self.policy,result['id'],self.api,fault=crash)
  self.assertEqual((path/'attempt.json').read_bytes(),raw)
  self.assertEqual(self.s.archive_restore(self.policy,result['id'],self.api)['entries'][0]['state'],'restored')
 def test_log_manifest_and_cid_identity_are_checked(self):
  path=self.job(containerId='c'*64,creationAttempted=True,createSucceeded=True,containerObserved=True,
                clientCounter=1,clients=[{'index':1,'exitCode':0,'finishedAt':'2026-10-01T00:00:00+00:00'}])
  for name,body in [('container.cid',b'c'*64+b'\n'),('client-1.stdout',b'readonly log'),('client-1.stderr',b'')]:
   (path/name).write_bytes(body);(path/name).chmod(0o600)
  self.assertEqual(len(self.plan()['entries']),1)
  (path/'client-1.stderr').unlink();self.assertEqual(self.plan()['entries'],[])
 def test_plan_producer_uid_limits_and_file_tamper_are_rejected(self):
  self.job();plan=self.plan()
  for key,value in [('uid',os.geteuid()+1),('producer',{'version':'wrong'}),('scanLimits',{})]:
   bad={**plan,key:value};bad['planSha256']=self.s.digest({k:v for k,v in bad.items() if k!='planSha256'})
   with self.assertRaises(ValueError):self.apply(bad)
  self.assertEqual(self.calls,[])
 def test_apply_read_cap_and_disk_capacity_leave_source(self):
  path=self.job();plan=self.plan()
  with patch.object(self.s.shutil,'disk_usage',return_value=type('Usage',(),{'free':1})()):
   with self.assertRaises(self.s.StorageError):self.apply(plan)
  self.assertTrue(path.exists())
  budget=self.s.ReadBudget(1)
  with self.assertRaises(self.s.StorageError):self.s.source_snapshot(path,path,self.api,budget)
  self.assertLessEqual(budget.used,1)
 def test_cross_device_rename_is_rejected(self):
  source=self.root/'source';destination=self.root/'dest';source.mkdir();destination.mkdir()
  original=Path.stat
  def device(path,*args,**kwargs):
   info=original(path,*args,**kwargs)
   if path==destination: return type('Info',(),{'st_dev':info.st_dev+1})()
   return info
  with patch.object(Path,'stat',device):
   with self.assertRaises(ValueError):self.s.rename_noreplace(source/'x',destination/'y')
 def test_cli_plan_apply_status_and_restore_are_connected(self):
  import contextlib
  self.job();plan=self.plan();plan_path=self.root/'plan.json';plan_path.write_text(json.dumps(plan))
  def command(argv):
   out=io.StringIO()
   with patch.object(self.api.sys,'argv',['snapshot',*argv]),contextlib.redirect_stdout(out):self.api.main()
   return json.loads(out.getvalue())
  # Initialize the explicit synthetic minFree0 policy, not the CLI defaults.
  with self.s.capacity_lock(self.policy):self.s.state_locked(self.policy)
  with patch.object(self.api,'_archive_probe',side_effect=self.probe):result=command(['archive-apply',str(self.cache),str(plan_path)])
  self.assertEqual(command(['archive-status',str(self.cache),result['id']])['entries'][0]['state'],'committed')
  self.assertEqual(command(['archive-restore',str(self.cache),result['id']])['entries'][0]['state'],'restored')
  self.assertEqual(command(['archive-plan',str(self.cache)])['version'],2)
 def test_readonly_probe_never_calls_cleanup_or_writes_source(self):
  path=self.job();_,job=self.api._load_attempt(path);query=self.root/'query';query.mkdir(mode=0o700);raw=(path/'attempt.json').read_bytes();calls=[]
  class Engine:
   io_failed=False
   def __init__(self,*args):pass
   def invoke(self,args,*rest):
    calls.append(args);return {'exitCode':0,'stdout':b''}
   def _client(self,args,*rest):
    calls.append(args);return {'exitCode':0,'stdout':b'{"active":[],"readErrors":0}'}
  with patch.object(self.api,'DockerEngine',Engine),patch.object(self.api,'_cleanup',side_effect=AssertionError('forbidden cleanup')):
   proof=self.api._archive_probe(query,path,job)
  self.assertTrue(proof['confirmed']);self.assertEqual((path/'attempt.json').read_bytes(),raw)
  self.assertFalse(any('rm' in call or 'create' in call or 'start' in call for call in calls))
 def test_archive_budget_is_checked_before_opening_archive(self):
  self.job();tx=self.apply(self.plan());row=tx['entries'][0]
  with patch.object(self.s,'read_bytes',side_effect=AssertionError('must reject before read')):
   with self.assertRaises(self.s.StorageError):self.s.verify_archive(row,self.s.ReadBudget(1))
 def test_transaction_manifest_rejects_path_escape_even_with_rehashed_metadata(self):
  self.job();tx=self.apply(self.plan());row=tx['entries'][0];manifest=row['manifest']
  manifest['files']['../escape']=manifest['files'].pop('operation.lock');row['manifestSha256']=self.s.digest(manifest)
  self.s.save_transaction(self.policy,tx)
  with self.assertRaises(ValueError):self.s.load_transaction(self.policy,tx['id'])
 def test_missing_duplicate_and_truncated_client_records_are_retained(self):
  path=self.job(clientCounter=2,clients=[])
  for i in [1,2]:
   for extension in ['stdout','stderr']:(path/f'client-{i}.{extension}').touch(mode=0o600)
  self.assertEqual(self.plan()['entries'],[])
  job=self.s.read_json(path/'attempt.json');job['clients']=[{'index':1,'exitCode':0,'finishedAt':'done'}]*2;self.s.atomic(path/'attempt.json',job)
  self.assertEqual(self.plan()['entries'],[])
  job['clients']=[{'index':i,'exitCode':0,'finishedAt':'done'} for i in [1,2]];job['clientHistoryTruncated']=True;self.s.atomic(path/'attempt.json',job)
  self.assertEqual(self.plan()['entries'],[])
 def test_ancillary_plan_shapes_are_validated_before_action(self):
  self.job();plan=self.plan()
  for key,value in [('generatedAt',None),('scanned',10**9),('hashedBytes',-1),('cacheIdentity',None),('retained',[{}])]:
   bad={**plan,key:value};bad['planSha256']=self.s.digest({k:v for k,v in bad.items() if k!='planSha256'})
   with self.assertRaises(ValueError):self.apply(bad)
 def test_incomplete_transaction_is_reported_as_unknown_without_blocking_reconcile(self):
  with self.s.capacity_lock(self.policy):self.s.state_locked(self.policy)
  folder=Path(self.policy['controlRoot'])/'transactions'/('f'*32);folder.mkdir(mode=0o700)
  result=self.s.reconcile(self.policy,self.api)
  self.assertEqual(result['transactionUnknown'][0]['transactionId'],'f'*32);self.assertEqual(result['cleanupCandidates'],[])
 def test_original_recover_lock_busy_is_retryable_json(self):
  import contextlib
  path=self.job();out=io.StringIO()
  with self.api.operation_lock(path),patch.object(self.api.sys,'argv',['snapshot','recover',str(path)]),contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
   with self.assertRaises(SystemExit) as stopped:self.api.main()
  self.assertEqual(stopped.exception.code,4);value=json.loads(out.getvalue());self.assertEqual(value['reason'],'task-busy');self.assertTrue(value['retryable'])
if __name__=='__main__':unittest.main()
