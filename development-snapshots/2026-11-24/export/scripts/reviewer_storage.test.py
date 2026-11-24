"""Synthetic private-cache storage tests. No VM daemon, network or host permission changes."""
import importlib.util,json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

class CapacityTest(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('snapshot',HERE/'reviewer_snapshot.py');self.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.api)
        self.storage=self.api.storage_module(sha256((HERE/'reviewer_storage.py').read_bytes()).hexdigest())
        self.assertTrue(callable(getattr(self.storage,'policy_for',None)),'Storage capacity API missing')
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve();self.cache=self.root/'attempts'
        self.policy=self.storage.policy_for(self.cache,{'minFreeBytes':0})

    def test_reservation_precedes_cache_creation_and_duplicate_is_idempotent(self):
        one=self.storage.reserve(self.policy,'a'*32,123,self.api)
        two=self.storage.reserve(self.policy,'a'*32,123,self.api)
        self.assertEqual(one,two);self.assertFalse(self.cache.exists())
        self.assertEqual(one['bytes'],123+96*1024*1024)
        self.assertNotIn(Path(self.policy['controlRoot']),list(self.cache.parents))
        state=self.storage.reconcile(self.policy,self.api)
        self.assertEqual(state['reservedBytes'],one['bytes']);self.assertEqual(len(state['retained']),1)

    def test_admission_counts_concurrent_reservations(self):
        self.storage.reserve(self.policy,'a'*32,0,self.api);self.storage.reserve(self.policy,'b'*32,0,self.api)
        with self.assertRaises(self.storage.StorageError) as caught:self.storage.reserve(self.policy,'c'*32,0,self.api)
        self.assertEqual(caught.exception.code,'cache-budget-exceeded');self.assertFalse(self.cache.exists())
        self.assertEqual(len(self.storage.reconcile(self.policy,self.api)['retained']),2)

    def test_disk_safety_denies_without_creating_task(self):
        policy=self.storage.policy_for(self.cache,{'minFreeBytes':512*1024*1024})
        with patch.object(self.storage.shutil,'disk_usage',return_value=type('Usage',(),{'free':1000})()):
            with self.assertRaises(self.storage.StorageError) as caught:self.storage.reserve(policy,'a'*32,0,self.api)
        self.assertEqual(caught.exception.code,'filesystem-space-insufficient');self.assertFalse(self.cache.exists())

    def test_unknown_reservation_is_not_expired_by_age(self):
        reservation=self.storage.reserve(self.policy,'a'*32,0,self.api)
        path=Path(self.policy['controlRoot'])/'ledger.json';ledger=self.storage.read_json(path)
        ledger['active']['a'*32]['createdAt']='2000-01-01T00:00:00+00:00';self.storage.atomic(path,ledger)
        state=self.storage.reconcile(self.policy,self.api)
        self.assertEqual(state['reservedBytes'],reservation['bytes']);self.assertEqual(state['retained'][0]['id'],'a'*32)
        self.assertFalse(self.storage.settle(self.policy,'a'*32,self.api))

    def test_cancel_known_preparation_failure_releases_without_forging_job(self):
        self.storage.reserve(self.policy,'a'*32,0,self.api)
        self.storage.cancel_preparation(self.policy,'a'*32)
        state=self.storage.reconcile(self.policy,self.api)
        self.assertEqual(state['reservedBytes'],0);self.assertFalse(self.cache.exists())

    def test_policy_is_private_fixed_and_rejects_bad_shapes(self):
        for bad in [{'budgetBytes':True},{'minFreeBytes':-1},{'unknown':1}]:
            with self.assertRaises(ValueError):self.storage.policy_for(self.cache,bad)
        self.storage.reserve(self.policy,'a'*32,0,self.api)
        control=Path(self.policy['controlRoot']);self.assertEqual(control.stat().st_mode&0o777,0o700)
        for p in control.rglob('*'):
            if p.is_file():self.assertEqual(p.stat().st_mode&0o777,0o600)
        different=self.storage.policy_for(self.cache,{'minFreeBytes':1})
        with self.assertRaises(self.storage.StorageError):self.storage.reserve(different,'b'*32,0,self.api)

    def test_active_capacity_lock_returns_retryable_busy(self):
        with self.storage.capacity_lock(self.policy):
            with self.assertRaises(self.storage.StorageError) as caught:self.storage.reserve(self.policy,'a'*32,0,self.api)
        self.assertEqual(caught.exception.code,'storage-busy');self.assertTrue(caught.exception.retryable)

    def test_disk_check_accounts_for_other_outstanding_reservations(self):
        with patch.object(self.storage.shutil,'disk_usage',return_value=type('Usage',(),{'free':150*1024*1024})()):
            self.storage.reserve(self.policy,'a'*32,0,self.api)
            with self.assertRaises(self.storage.StorageError) as caught:self.storage.reserve(self.policy,'b'*32,0,self.api)
        self.assertEqual(caught.exception.code,'filesystem-space-insufficient')

    def fixture(self):
        import shutil
        spec=importlib.util.spec_from_file_location('fixtures',HERE/'reviewer_snapshot.test.py');fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        source=HERE.parent/'work/harness-purge-improved/package/scripts';bundle=self.root/'bundle'
        snapshot=self.api.freeze(source,bundle,'sha256:'+'a'*64)
        project=self.root/'project';project.mkdir();(project/'safe.py').write_text('value=7\n')
        scan=self.root/'scan.json';scan.write_text('{"results":[]}');manifest=self.root/'manifest.json'
        manifest.write_text(json.dumps({'files':{'safe.py':sha256((project/'safe.py').read_bytes()).hexdigest()},'scanSha256':sha256(scan.read_bytes()).hexdigest()}))
        return (bundle,self.api.digest(snapshot),project,manifest,scan,'d'*64,'e'*64),fixtures.Backend

    def test_execute_refuses_budget_before_cache_and_engine(self):
        args,backend_class=self.fixture();backend=backend_class();policy=self.storage.policy_for(self.cache,{'budgetBytes':1,'minFreeBytes':0})
        try:
            with self.assertRaises(self.storage.StorageError) as caught:self.api.execute(*args,attempts_root=self.cache,storage_policy=policy,_engine_factory=backend.factory)
        except TypeError:self.fail('Capacity admission is not integrated with execute')
        self.assertEqual(caught.exception.code,'cache-budget-exceeded');self.assertEqual(backend.calls,[]);self.assertFalse(self.cache.exists())

    def test_execute_settles_only_confirmed_attempt_without_changing_result(self):
        args,backend_class=self.fixture();backend=backend_class()
        try:result=self.api.execute(*args,attempts_root=self.cache,storage_policy=self.policy,_engine_factory=backend.factory)
        except TypeError:self.fail('Capacity admission is not integrated with execute')
        record=self.api.status(result['attemptDirectory'])
        self.assertEqual(record['result'],result);self.assertIn('storageReservation',record)
        self.assertEqual(self.storage.reconcile(self.policy,self.api)['reservedBytes'],0)

    def test_unknown_execute_retains_then_successful_recovery_settles(self):
        args,backend_class=self.fixture();backend=backend_class('create-unknown')
        try:
            with self.assertRaises(self.api.ReviewAttemptError) as caught:self.api.execute(*args,attempts_root=self.cache,storage_policy=self.policy,_engine_factory=backend.factory)
        except TypeError:self.fail('Capacity admission is not integrated with execute')
        self.assertGreater(self.storage.reconcile(self.policy,self.api)['reservedBytes'],0)
        backend.complete_create();record=self.api.recover(caught.exception.attempt_directory,_engine_factory=backend.factory)
        self.assertEqual(record['state'],'recovered');self.assertNotIn('result',record)
        self.assertEqual(self.storage.reconcile(self.policy,self.api)['reservedBytes'],0)

    def test_cli_storage_block_explains_reason_without_attempt(self):
        import io,contextlib
        out=io.StringIO();error=self.storage.StorageError('cache-budget-exceeded',details={'budgetBytes':1})
        argv=['snapshot','run','/bundle','a'*64,'/project','/manifest','/scan','d'*64,'e'*64]
        with patch.object(self.api.sys,'argv',argv),patch.object(self.api,'execute',side_effect=error),contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:self.api.main()
        self.assertEqual(stopped.exception.code,4)
        self.assertEqual(json.loads(out.getvalue())['reason'],'cache-budget-exceeded')

    def test_cli_reconcile_reports_original_pending_reservation(self):
        import io,contextlib
        self.storage.reserve(self.policy,'a'*32,0,self.api);out=io.StringIO()
        with patch.object(self.api.sys,'argv',['snapshot','storage-reconcile',str(self.cache)]),contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            try:self.api.main()
            except SystemExit:self.fail('storage-reconcile CLI missing')
        self.assertEqual(json.loads(out.getvalue())['retained'][0]['id'],'a'*32)

    def test_reservation_limit_cannot_write_an_unreadable_ledger(self):
        policy=self.storage.policy_for(self.cache,{'minFreeBytes':0,'budgetBytes':200*1024**3})
        with self.storage.capacity_lock(policy):
            ledger=self.storage.state_locked(policy)
            for i in range(1000):
                identity=f'{i:032x}';ledger['active'][identity]={'id':identity,'inputBytes':0,'bytes':96*1024**2,
                    'directory':str(self.cache/('review-'+identity)),'policySha256':self.storage.digest(policy)}
            self.storage.atomic(Path(policy['controlRoot'])/'ledger.json',ledger)
        with patch.object(self.storage.shutil,'disk_usage',return_value=type('Usage',(),{'free':2**60})()):
            with self.assertRaises(self.storage.StorageError) as caught:self.storage.reserve(policy,'f'*32,0,self.api)
        self.assertEqual(caught.exception.code,'reservation-limit')

    def test_persisted_versions_and_policy_numbers_require_integers(self):
        for mutate in [{'version':True},{'minimumAgeDays':30.0},{'cacheRoot':[]}]:
            with self.assertRaises(ValueError):self.storage.validate_policy({**self.policy,**mutate})
        with self.storage.capacity_lock(self.policy):self.storage.state_locked(self.policy)
        for version in [True,1.0]:
            self.storage.atomic(Path(self.policy['controlRoot'])/'ledger.json',{'version':version,'active':{}})
            with self.storage.capacity_lock(self.policy):
                with self.assertRaises(ValueError):self.storage.state_locked(self.policy)

    def test_existing_policy_cannot_redirect_to_another_cache(self):
        self.storage.reserve(self.policy,'a'*32,0,self.api)
        other=self.storage.policy_for(self.root/'another-cache',{'minFreeBytes':0})
        self.storage.atomic(Path(self.policy['controlRoot'])/'policy.json',other)
        with self.assertRaises(ValueError):self.storage.existing_policy(self.cache)

    def test_failed_settlement_save_keeps_pending_in_reconcile_response(self):
        args,backend_class=self.fixture()
        with patch.object(self.storage,'settle',return_value=False):
            result=self.api.execute(*args,attempts_root=self.cache,storage_policy=self.policy,_engine_factory=backend_class().factory)
        record=self.api.status(result['attemptDirectory']);identity=record['storageReservation']['id'];original=self.storage.atomic
        def full(path,value):
            if Path(path).name=='ledger.json':raise OSError('synthetic settlement save failure')
            return original(path,value)
        with patch.object(self.storage,'atomic',full):state=self.storage.reconcile(self.policy,self.api)
        self.assertGreater(state['reservedBytes'],0);self.assertEqual(state['retained'][0]['id'],identity)
        self.assertIn(identity,self.storage.read_json(Path(self.policy['controlRoot'])/'ledger.json')['active'])
        self.assertEqual(self.storage.reconcile(self.policy,self.api)['reservedBytes'],0)
        self.assertEqual(self.api.status(result['attemptDirectory'])['result'],result)

    def test_first_run_creates_missing_cache_parents_without_task(self):
        cache=self.root/'new-user'/'cache'/'attempts';policy=self.storage.policy_for(cache,{'minFreeBytes':0})
        self.storage.reserve(policy,'a'*32,0,self.api)
        self.assertFalse(cache.exists());self.assertTrue(cache.parent.exists())

    def test_non_value_settlement_error_keeps_original_result(self):
        args,backend_class=self.fixture()
        with patch.object(self.storage,'settle',side_effect=AttributeError('synthetic')):
            result=self.api.execute(*args,attempts_root=self.cache,storage_policy=self.policy,_engine_factory=backend_class().factory)
        self.assertEqual(self.api.status(result['attemptDirectory'])['result'],result)

    def test_proven_preparation_residue_is_retained_and_counted(self):
        identity='a'*32;self.storage.reserve(self.policy,identity,0,self.api)
        path=self.cache/('review-'+identity);path.mkdir(mode=0o700,parents=True);self.cache.chmod(0o700)
        (path/'stage').mkdir(mode=0o700);(path/'stage'/'part').write_bytes(b'partial')
        self.storage.cancel_preparation(self.policy,identity)
        self.storage.reserve(self.policy,'b'*32,0,self.api)
        self.assertTrue((path/'stage'/'part').exists())

    def test_malformed_reservation_keeps_original_pending(self):
        args,backend_class=self.fixture()
        with patch.object(self.storage,'settle',return_value=False):
            result=self.api.execute(*args,attempts_root=self.cache,storage_policy=self.policy,_engine_factory=backend_class().factory)
        path=Path(result['attemptDirectory'])/'attempt.json';job=self.storage.read_json(path);job['storageReservation']=[];self.storage.atomic(path,job)
        state=self.storage.reconcile(self.policy,self.api);self.assertGreater(state['reservedBytes'],0)

    def test_three_processes_cannot_over_reserve(self):
        import subprocess,sys
        script='''import importlib.util,sys,time,json
from pathlib import Path
p=Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('storage',p);s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
policy=s.policy_for(Path(sys.argv[2]),{'minFreeBytes':0});deadline=time.monotonic()+10
while not Path(sys.argv[3]).exists():
 if time.monotonic()>deadline:raise RuntimeError('barrier timeout')
 time.sleep(.01)
while True:
 try:s.reserve(policy,sys.argv[4],0,None);print('reserved');break
 except s.StorageError as e:
  if e.retryable and time.monotonic()<deadline:time.sleep(.01);continue
  print(e.code);break
'''
        start=self.root/'start';children=[]
        for identity in ['a'*32,'b'*32,'c'*32]:
            children.append(subprocess.Popen([sys.executable,'-I','-B','-c',script,str(HERE/'reviewer_storage.py'),str(self.cache),str(start),identity],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
        start.touch();out=[]
        for child in children:
            stdout,stderr=child.communicate(timeout=15);self.assertEqual(child.returncode,0,stderr);out.append(stdout.strip())
        self.assertEqual(sorted(out),['cache-budget-exceeded','reserved','reserved'])
        self.assertEqual(len(self.storage.reconcile(self.policy,self.api)['retained']),2)

    def test_busy_preparation_release_can_be_reconciled_without_retrying_analysis(self):
        identity='a'*32;self.storage.reserve(self.policy,identity,0,self.api)
        with self.storage.capacity_lock(self.policy):
            with self.assertRaises(self.storage.StorageError):self.storage.cancel_preparation(self.policy,identity)
        self.assertEqual(self.storage.reconcile(self.policy,self.api)['reservedBytes'],0)

    def test_missing_record_reconciliation_never_competes_for_initial_task_lock(self):
        identity='a'*32;self.storage.reserve(self.policy,identity,0,self.api)
        path=self.cache/('review-'+identity);path.mkdir(mode=0o700,parents=True);self.cache.chmod(0o700)
        with patch.object(self.storage,'task_lock',side_effect=AssertionError('must not acquire initial lock')):
            self.assertGreater(self.storage.reconcile(self.policy,self.api)['reservedBytes'],0)

    def test_preparation_proof_fences_duplicate_reservation(self):
        identity='a'*32;self.storage.reserve(self.policy,identity,0,self.api)
        with self.storage.capacity_lock(self.policy):
            with self.assertRaises(self.storage.StorageError):self.storage.cancel_preparation(self.policy,identity)
        with self.assertRaises(self.storage.StorageError):self.storage.reserve(self.policy,identity,0,self.api)

    def test_cancel_rejects_traversal_identity_before_any_write(self):
        self.storage.reserve(self.policy,'a'*32,0,self.api)
        ledger=Path(self.policy['controlRoot'])/'ledger.json';original=ledger.read_bytes()
        with self.assertRaises(ValueError):self.storage.cancel_preparation(self.policy,'../ledger')
        self.assertEqual(ledger.read_bytes(),original)

    def test_ledger_requires_exact_input_plus_overhead(self):
        self.storage.reserve(self.policy,'a'*32,0,self.api)
        path=Path(self.policy['controlRoot'])/'ledger.json';ledger=self.storage.read_json(path)
        ledger['active']['a'*32]['inputBytes']=100*1024**2;self.storage.atomic(path,ledger)
        with self.assertRaises(ValueError):self.storage.reserve(self.policy,'a'*32,100*1024**2,self.api)

    def test_private_create_rejects_link_inserted_during_mkdir(self):
        target=self.root/'target';target.mkdir(mode=0o700);alias=self.root/'alias';original=Path.mkdir
        def swapped(path,*args,**kwargs):
            if path==alias:alias.symlink_to(target);return
            return original(path,*args,**kwargs)
        with patch.object(Path,'mkdir',swapped):
            with self.assertRaises(ValueError):self.storage.private(alias,True)

    def test_post_commit_error_never_resurrects_settled_row_on_admission(self):
        args,backend_class=self.fixture()
        with patch.object(self.storage,'settle',return_value=False):
            result=self.api.execute(*args,attempts_root=self.cache,storage_policy=self.policy,_engine_factory=backend_class().factory)
        identity=Path(result['attemptDirectory']).name[7:];original=self.storage.atomic;failed=[]
        def committed_error(path,value):
            original(path,value)
            if Path(path).name=='ledger.json' and identity not in value['active'] and not failed:
                failed.append(True);raise OSError('synthetic directory fsync after rename')
        with patch.object(self.storage,'atomic',committed_error):self.storage.reserve(self.policy,'b'*32,0,self.api)
        ledger=self.storage.read_json(Path(self.policy['controlRoot'])/'ledger.json')
        self.assertNotIn(identity,ledger['active']);self.assertIn('b'*32,ledger['active'])

if __name__=='__main__':unittest.main()
