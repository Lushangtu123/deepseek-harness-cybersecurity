"""Synthetic tests; do not run project code or contact a Docker daemon on Mac."""
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
IMAGE = 'sha256:' + 'a' * 64


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        script = HERE / 'reviewer_snapshot.py'
        self.assertTrue(script.exists(), 'Reviewer dependency snapshot mechanism is missing')
        spec = importlib.util.spec_from_file_location('snapshot', script)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.sources = self.root / 'sources'
        self.sources.mkdir()
        package = HERE.parent / 'work/harness-purge-improved/package/scripts'
        for name in self.api.FILES:
            shutil.copyfile(package / name, self.sources / name)
        self.bundle = self.root / 'bundle'

    def freeze(self):
        return self.api.freeze(self.sources, self.bundle, IMAGE)

    def test_snapshot_pins_entrypoint_transitive_modules_launcher_and_runtime(self):
        manifest = self.freeze()
        self.assertEqual(manifest['version'],2)
        self.assertEqual(manifest.get('storageSha256'),sha256((HERE/'reviewer_storage.py').read_bytes()).hexdigest())
        self.assertEqual((self.bundle/'reviewer_storage.py').read_bytes(),(HERE/'reviewer_storage.py').read_bytes())
        self.assertEqual(set(manifest['files']), set(self.api.FILES))
        for name in self.api.FILES:
            self.assertEqual(manifest['files'][name], sha256((self.sources / name).read_bytes()).hexdigest())
        self.assertEqual(manifest['imageId'], IMAGE)
        self.assertEqual(manifest['launcherSha256'], sha256((HERE / 'reviewer_snapshot.py').read_bytes()).hexdigest())
        self.assertEqual(self.api.verify(self.bundle, self.api.digest(manifest))[0], manifest)

    def test_source_edits_after_freeze_do_not_change_execution_snapshot(self):
        manifest = self.freeze()
        (self.sources / 'eval_guard_review.py').write_text('raise RuntimeError("changed")\n')
        self.assertEqual(self.api.verify(self.bundle, self.api.digest(manifest))[0], manifest)

    def test_every_dependency_drift_is_rejected(self):
        manifest = self.freeze()
        for name in self.api.FILES:
            path = self.bundle / name
            old = path.read_bytes()
            path.write_bytes(old + b'\n# changed\n')
            with self.assertRaisesRegex(ValueError, 'digest'):
                self.api.verify(self.bundle, self.api.digest(manifest))
            path.write_bytes(old)

    def test_manifest_runtime_or_external_pin_drift_is_rejected(self):
        manifest = self.freeze()
        expected = self.api.digest(manifest)
        manifest['imageId'] = 'sha256:' + 'b' * 64
        (self.bundle / 'snapshot.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            self.api.verify(self.bundle, expected)

    def test_unexpected_or_linked_files_are_rejected(self):
        manifest = self.freeze()
        extra = self.bundle / 'sitecustomize.py'
        extra.write_text('raise RuntimeError("unexpected")\n')
        with self.assertRaisesRegex(ValueError, 'contents'):
            self.api.verify(self.bundle, self.api.digest(manifest))
        extra.unlink()
        path = self.bundle / 'eval_import_review.py'
        path.unlink()
        path.symlink_to(self.sources / path.name)
        with self.assertRaisesRegex(ValueError, 'linked'):
            self.api.verify(self.bundle, self.api.digest(manifest))

    def test_new_static_or_dynamic_imports_require_explicit_dependency_review(self):
        for source in ['import another_helper\n', 'from importlib import import_module\n',
                       '__import__("another_helper")\n', 'import json.tool\n']:
            path = self.sources / 'eval_guard_review.py'
            old = path.read_bytes()
            path.write_bytes(old + source.encode())
            with self.assertRaisesRegex(ValueError, 'import'):
                self.freeze()
            self.assertFalse(self.bundle.exists())
            path.write_bytes(old)

    def test_launcher_drift_and_mutable_image_tags_are_rejected(self):
        for image in ['python:latest', 'python:3.12', 'sha256:123']:
            with self.assertRaisesRegex(ValueError, 'image'):
                self.api.freeze(self.sources, self.bundle, image)
        manifest = self.freeze()
        manifest['launcherSha256'] = 'f' * 64
        (self.bundle / 'snapshot.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'launcher'):
            self.api.verify(self.bundle, self.api.digest(manifest))

    def test_input_staging_rejects_source_mismatch_and_links(self):
        sources = self.root / 'project'
        sources.mkdir()
        source = sources / 'safe.py'
        source.write_text('value = 7\n')
        scan = self.root / 'scan.json'
        scan.write_text('{"results":[]}')
        manifest = self.root / 'manifest.json'
        request = {'files': {'safe.py': 'f' * 64}, 'scanSha256': sha256(scan.read_bytes()).hexdigest()}
        manifest.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError, 'source digest'):
            self.api.inputs(sources, manifest, scan)
        request['files']['safe.py'] = sha256(source.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(request))
        payload, fingerprint = self.api.inputs(sources, manifest, scan)
        self.assertEqual(payload['sources/safe.py'], source.read_bytes())
        self.assertEqual(len(fingerprint), 64)
        source.unlink()
        source.symlink_to(self.sources / 'eval_guard_review.py')
        with self.assertRaisesRegex(ValueError, 'linked'):
            self.api.inputs(sources, manifest, scan)

    def execution_fixture(self):
        snapshot = self.freeze()
        project = self.root / 'project'
        project.mkdir()
        (project / 'safe.py').write_text('value = 7\n')
        scan = self.root / 'scan.json'
        scan.write_text('{"results":[]}')
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'files': {'safe.py': sha256((project / 'safe.py').read_bytes()).hexdigest()},
                                       'scanSha256': sha256(scan.read_bytes()).hexdigest()}))
        return snapshot, project, manifest, scan

    def test_execution_binds_receipt_to_snapshot_inputs_and_quality_freeze(self):
        snapshot, project, manifest, scan = self.execution_fixture()
        backend = Backend()
        result = self.api.execute(self.bundle, self.api.digest(snapshot), project, manifest, scan, 'd'*64, 'e'*64,
                                  attempts_root=self.root/'attempts', _engine_factory=backend.factory)
        receipt = result['reviewerExecution']
        self.assertEqual(receipt['snapshotSha256'], self.api.digest(snapshot))
        self.assertEqual((receipt['datasetSha256'], receipt['freezeSha256']), ('d'*64, 'e'*64))
        self.assertEqual(receipt['reportSha256'], sha256(result['reportJson'].encode()).hexdigest())
        self.assertEqual(receipt['inputSha256'], self.api.digest(result['inputFiles']))
        self.assertEqual(receipt['version'], 2)
        self.assertEqual(receipt['inputFiles'], result['inputFiles'])
        self.assertEqual(receipt['scanSha256'], sha256(scan.read_bytes()).hexdigest())
        command = next(row for row in backend.calls if row[0]=='create')
        for option in ['--pull','never','--network','none','--read-only','--cap-drop','ALL','-I','-B','-S',IMAGE]:
            self.assertIn(option,command)
        self.assertTrue(result['temporaryRemoved'])
        self.assertTrue(result['cleanup']['confirmed'])

    def test_timeout_cleans_container_and_never_emits_completed_receipt(self):
        snapshot, project, manifest, scan = self.execution_fixture()
        backend = Backend('timeout')
        with self.assertRaises(self.api.ReviewAttemptError) as caught:
            self.api.execute(self.bundle, self.api.digest(snapshot), project, manifest, scan, 'd'*64, 'e'*64,
                             attempts_root=self.root/'attempts', _engine_factory=backend.factory)
        self.assertEqual(caught.exception.status['failure']['kind'],'timed-out')
        self.assertTrue(caught.exception.status['cleanup']['confirmed'])
        self.assertIsNone(backend.container)


class Backend:
    def __init__(self, scenario='ok'):
        self.scenario = scenario
        self.container = None
        self.calls = []
        self.create_args = None
        self.active = False

    def factory(self, root, job, save, cancel):
        backend = self

        class Engine:
            def invoke(self, args, seconds, phase, cancellable=True):
                backend.calls.append(list(args))
                result = {'exitCode': 0, 'stdout': b'', 'deadlineExceeded': False}
                if args[0] == 'create':
                    # Simulate the production contract: save create event before spawn.
                    job['createClient']={'phase':'create','index':1,'pid':12345}
                    job.setdefault('clients',[]).append(job['createClient'])
                    save()
                    backend.create_args = list(args)
                    if backend.scenario == 'create-unknown':
                        return {**result, 'exitCode': 124, 'deadlineExceeded': True}
                    backend.complete_create()
                    result['stdout'] = ('c'*64+'\n').encode()
                elif args[:2] == ['start', '--attach']:
                    if backend.scenario in ['timeout','timeout-remove-error']:
                        return {**result, 'exitCode': 124, 'deadlineExceeded': True}
                    if backend.scenario in ['term', 'int']:
                        import os, signal
                        os.kill(os.getpid(), signal.SIGTERM if backend.scenario == 'term' else signal.SIGINT)
                    if backend.scenario == 'start-error':
                        return {**result, 'exitCode': 2}
                    result['stdout'] = getattr(backend,'report',b'not-json' if backend.scenario == 'bad-json' else b'{"version":1,"guardChecks":0}')
                elif args[:2] == ['container', 'ls']:
                    if backend.container:
                        token = args[-1]
                        if token == 'id=' + backend.container['Id'] or token == 'name=^/' + backend.container['Name'].removeprefix('/') + '$':
                            result['stdout'] = (backend.container['Id']+'\n').encode()
                elif args[:2] == ['container', 'inspect']:
                    if not backend.container or args[-1] != backend.container['Id']:
                        return {**result, 'exitCode': 1}
                    if backend.scenario=='cancel-on-inspect':
                        import os,signal
                        os.kill(os.getpid(),signal.SIGTERM)
                    result['stdout'] = json.dumps([backend.container]).encode()
                elif args[:2] == ['rm', '-f']:
                    if backend.scenario in ['remove-error','timeout-remove-error']:
                        return {**result, 'exitCode': 1}
                    if backend.scenario != 'remove-lies':
                        backend.container = None
                else:
                    raise AssertionError(args)
                return result

            def clients_stopped(self):
                if getattr(backend,'probe_results',[]):
                    return backend.probe_results.pop(0)
                return not backend.active

        return Engine()

    def complete_create(self):
        args = self.create_args
        labels = {}
        for index, arg in enumerate(args):
            if arg == '--label':
                key, value = args[index+1].split('=', 1)
                labels[key] = value
        image = args[args.index('--entrypoint')+2]
        self.container = {'Id':'c'*64, 'Name':'/'+args[args.index('--name')+1], 'Image':image,
                          'Config':{'Labels':labels}, 'State':{'Running':False,'ExitCode':0,'OOMKilled':False}}
        if self.scenario == 'foreign':
            self.container['Config']['Labels'] = {}


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        SnapshotTest.setUp(self)
        self.assertTrue(hasattr(self.api, 'ReviewAttemptError'), 'Durable failure/recovery mechanism is missing')
        self.attempts = self.root / 'attempts'

    def freeze(self):
        return SnapshotTest.freeze(self)

    def execution_fixture(self):
        return SnapshotTest.execution_fixture(self)

    def run_case(self, backend):
        snapshot, project, manifest, scan = self.execution_fixture()
        return self.api.execute(self.bundle, self.api.digest(snapshot), project, manifest, scan, 'd'*64, 'e'*64,
                                attempts_root=self.attempts, timeout=1, _engine_factory=backend.factory)

    def failure(self, backend):
        with self.assertRaises(self.api.ReviewAttemptError) as caught:
            self.run_case(backend)
        return caught.exception

    def test_completed_run_requires_identity_and_post_remove_absence(self):
        backend = Backend()
        result = self.run_case(backend)
        self.assertIsNone(backend.container)
        self.assertTrue(result['cleanup']['confirmed'])
        self.assertTrue(result['cleanup']['idAbsent'])
        self.assertTrue(result['cleanup']['nameAbsent'])
        self.assertTrue(result['cleanup']['clientsStopped'])
        self.assertEqual(result['reviewerExecution']['state'], 'completed')
        create = next(row for row in backend.calls if row[0] == 'create')
        self.assertIn('--cidfile', create)
        self.assertIn('--network', create)
        self.assertIn('none', create)
        self.assertIn('--no-healthcheck', create)
        self.assertEqual(next(row for row in backend.calls if row[0] == 'start')[-1], 'c'*64)
        self.assertEqual(self.api.status(Path(result['attemptDirectory']))['state'], 'completed')

    def test_remove_success_without_absence_never_emits_completion(self):
        error = self.failure(Backend('remove-lies'))
        self.assertEqual(error.status['state'], 'cleanup-unconfirmed')
        self.assertFalse(error.status['cleanup']['confirmed'])
        self.assertTrue((Path(error.attempt_directory)/'stage').is_dir())
        self.assertNotIn('reviewerExecution', error.status)

    def test_timeout_keeps_original_cause_and_cleans_known_container(self):
        backend = Backend('timeout')
        error = self.failure(backend)
        self.assertEqual(error.status['failure']['kind'], 'timed-out')
        self.assertTrue(error.status['cleanup']['confirmed'])
        self.assertIsNone(backend.container)

    def test_cleanup_error_does_not_mask_primary_failure(self):
        backend = Backend('remove-error')
        error = self.failure(backend)
        self.assertEqual(error.status['failure']['kind'], 'cleanup-failed')
        self.assertFalse(error.status['cleanup']['confirmed'])
        self.assertTrue(error.status['cleanup']['errors'])

    def test_timeout_cause_survives_a_second_cleanup_failure(self):
        error = self.failure(Backend('timeout-remove-error'))
        self.assertEqual(error.status['failure']['kind'], 'timed-out')
        self.assertFalse(error.status['cleanup']['confirmed'])
        self.assertTrue(error.status['cleanup']['errors'])

    def test_recovery_refuses_an_active_operation_lock(self):
        backend = Backend('create-unknown')
        error = self.failure(backend)
        directory = Path(error.attempt_directory)
        count = len(backend.calls)
        with self.api.operation_lock(directory):
            with self.assertRaises(ValueError):
                self.api.recover(directory, _engine_factory=backend.factory)
        self.assertEqual(len(backend.calls), count)

    def test_bad_report_has_failed_record_and_no_completed_receipt(self):
        error = self.failure(Backend('bad-json'))
        self.assertEqual(error.status['failure']['kind'], 'report-invalid')
        self.assertTrue(error.status['cleanup']['confirmed'])
        self.assertNotIn('reviewerExecution', error.status)

    def test_signals_are_recorded_and_previous_handlers_restored(self):
        import signal
        for name, expected in [('term',signal.SIGTERM), ('int',signal.SIGINT)]:
            with self.subTest(name=name):
                # New private fixture per signal, avoiding bundle reuse.
                if self.bundle.exists():
                    shutil.rmtree(self.bundle)
                if (self.root/'project').exists():
                    shutil.rmtree(self.root/'project')
                old = signal.getsignal(expected)
                error = self.failure(Backend(name))
                self.assertEqual(error.status['failure']['kind'], 'interrupted')
                self.assertEqual(error.status['failure']['signal'], int(expected))
                self.assertIs(signal.getsignal(expected), old)
                self.assertTrue(error.status['cleanup']['confirmed'])

    def test_foreign_container_is_never_removed(self):
        backend = Backend('foreign')
        error = self.failure(backend)
        self.assertEqual(error.status['failure']['kind'], 'container-identity')
        self.assertFalse(any(row[:2] == ['rm','-f'] for row in backend.calls))
        self.assertFalse(error.status['cleanup']['confirmed'])

    def test_active_clients_prevent_completed_cleanup(self):
        backend = Backend()
        backend.active = True
        error = self.failure(backend)
        self.assertFalse(error.status['cleanup']['clientsStopped'])
        self.assertFalse(error.status['cleanup']['confirmed'])

    def test_unknown_create_absence_stays_unknown_then_recovers_same_object(self):
        backend = Backend('create-unknown')
        error = self.failure(backend)
        self.assertFalse(error.status['cleanup']['confirmed'])
        self.assertFalse(error.status['cleanup']['creationResolved'])
        directory = Path(error.attempt_directory)
        first = self.api.recover(directory, _engine_factory=backend.factory)
        self.assertEqual(first['state'], 'cleanup-unconfirmed')
        backend.complete_create()
        recovered = self.api.recover(directory, _engine_factory=backend.factory)
        self.assertEqual(recovered['state'], 'recovered')
        self.assertTrue(recovered['cleanup']['confirmed'])
        self.assertEqual(sum(row[0] == 'create' for row in backend.calls), 1)
        self.assertFalse(any(row[0] == 'start' for row in backend.calls))
        self.assertNotIn('reviewerExecution', recovered)
        self.assertFalse((directory/'stage').exists())

    def test_recovery_reloads_commit_after_acquiring_lock(self):
        backend = Backend()
        result = self.run_case(backend)
        directory = Path(result['attemptDirectory'])
        original = self.api._load_attempt
        count = [0]
        def stale_once(path):
            root, job = original(path)
            count[0] += 1
            if count[0] == 1:
                job = json.loads(json.dumps(job))
                job['state'] = 'waiting'
            return root, job
        actions = len(backend.calls)
        with patch.object(self.api, '_load_attempt', stale_once):
            value = self.api.recover(directory, _engine_factory=backend.factory)
        self.assertEqual(value['state'], 'completed')
        self.assertEqual(len(backend.calls), actions)
        self.assertEqual(self.api.status(directory)['state'], 'completed')

    def test_final_client_probe_may_resolve_an_initial_active_client(self):
        backend = Backend()
        backend.probe_results = [False, True]
        try:
            result = self.run_case(backend)
        except self.api.ReviewAttemptError:
            self.fail('Cleanup ignored the final client probe')
        self.assertTrue(result['cleanup']['confirmed'])
        self.assertFalse(result['cleanup']['clientsInitiallyStopped'])
        self.assertTrue(result['cleanup']['clientsStopped'])

    def test_stage_removal_failure_is_recorded_without_completed_receipt(self):
        backend = Backend()
        with patch.object(self.api, '_discard_stage', side_effect=PermissionError('synthetic deny')):
            try:
                self.run_case(backend)
            except Exception as error:
                self.assertIsInstance(error, self.api.ReviewAttemptError)
                self.assertEqual(error.status['failure']['kind'], 'stage-cleanup-failed')
                self.assertFalse(error.status['cleanup']['confirmed'])
                self.assertNotIn('reviewerExecution', error.status)
            else:
                self.fail('Stage removal failure was reported as completed')

    def test_late_signal_before_result_commit_does_not_emit_completion(self):
        import os,signal
        original=self.api._discard_stage
        def cancel_after_stage(directory):
            value=original(directory)
            os.kill(os.getpid(),signal.SIGTERM)
            return value
        with patch.object(self.api,'_discard_stage',cancel_after_stage):
            with self.assertRaises(self.api.ReviewAttemptError) as caught:
                self.run_case(Backend())
        self.assertEqual(caught.exception.status['failure']['kind'],'interrupted')
        self.assertNotIn('result',caught.exception.status)

    def test_cancellation_during_completion_serialization_is_not_published(self):
        import os,signal
        original=self.api._save
        def before_commit(directory,job,*args,**kwargs):
            if job.get('state')=='completed':os.kill(os.getpid(),signal.SIGTERM)
            return original(directory,job,*args,**kwargs)
        with patch.object(self.api,'_save',before_commit):
            with self.assertRaises(self.api.ReviewAttemptError) as caught:
                self.run_case(Backend())
        self.assertEqual(caught.exception.status['state'],'interrupted')
        self.assertNotIn('result',self.api.status(Path(caught.exception.attempt_directory)))

    def test_completed_status_returns_same_integrity_checked_committed_result(self):
        value=self.run_case(Backend());directory=Path(value['attemptDirectory'])
        state=self.api.status(directory)
        self.assertIn('result',state)
        self.assertEqual(state['result'],value)
        self.assertEqual(state['resultSha256'],self.api.digest(value))
        self.assertFalse((directory/'result.json').exists())
        state=json.loads((directory/'attempt.json').read_bytes())
        state['result']['reportJson']='tampered'
        (directory/'attempt.json').write_text(json.dumps(state))
        with self.assertRaises(ValueError):self.api.status(directory)

    def test_unknown_commit_after_rename_queries_original_completed_result(self):
        original=self.api._save
        def lost_reply(directory,job,*args,**kwargs):
            original(directory,job,*args,**kwargs)
            if job.get('state')=='completed':raise OSError('synthetic lost fsync reply')
        backend=Backend()
        with patch.object(self.api,'_save',lost_reply):
            with self.assertRaises(self.api.ReviewAttemptError) as caught:self.run_case(backend)
        self.assertEqual(caught.exception.status['state'],'completion-unconfirmed')
        self.assertNotIn('result',caught.exception.status)
        directory=Path(caught.exception.attempt_directory)
        state=self.api.status(directory)
        self.assertEqual(state['state'],'completed')
        self.assertEqual(state['resultSha256'],self.api.digest(state['result']))
        count=len(backend.calls)
        self.assertEqual(self.api.recover(directory,_engine_factory=backend.factory)['state'],'completed')
        self.assertEqual(len(backend.calls),count)

    def test_unknown_commit_before_rename_recovers_without_a_result(self):
        original=self.api._save
        def no_commit(directory,job,*args,**kwargs):
            if job.get('state')=='completed':raise OSError('synthetic no commit')
            return original(directory,job,*args,**kwargs)
        backend=Backend()
        with patch.object(self.api,'_save',no_commit):
            with self.assertRaises(self.api.ReviewAttemptError) as caught:self.run_case(backend)
        directory=Path(caught.exception.attempt_directory)
        self.assertNotIn('result',self.api.status(directory))
        recovered=self.api.recover(directory,_engine_factory=backend.factory)
        self.assertEqual(recovered['state'],'recovered')
        self.assertNotIn('result',recovered)
        self.assertEqual(sum(row[0]=='create' for row in backend.calls),1)
        self.assertEqual(sum(row[0]=='start' for row in backend.calls),1)

    def test_cancel_during_identity_check_does_not_start_container(self):
        backend=Backend('cancel-on-inspect')
        error=self.failure(backend)
        self.assertEqual(error.status['failure']['kind'],'interrupted')
        self.assertFalse(any(row[0]=='start' for row in backend.calls))
        self.assertTrue(error.status['cleanup']['confirmed'])

    def test_cleaning_journal_failure_still_attempts_cleanup_with_original_cause(self):
        backend=Backend('timeout');original=self.api._save
        def broken(directory,job,*args,**kwargs):
            if job.get('state')=='cleaning':raise OSError('synthetic full disk')
            return original(directory,job,*args,**kwargs)
        with patch.object(self.api,'_save',broken):
            try:self.run_case(backend)
            except Exception as error:
                self.assertIsInstance(error,self.api.ReviewAttemptError)
                self.assertEqual(error.status['failure']['kind'],'timed-out')
            else:self.fail('Expected original failed attempt')
        self.assertIsNone(backend.container)
        self.assertTrue(any(row[:2]==['rm','-f'] for row in backend.calls))

    def test_invalid_stage_is_reported_without_bypassing_failure_record(self):
        with patch.object(self.api,'_discard_stage',side_effect=ValueError('synthetic linked stage')):
            try:self.run_case(Backend())
            except Exception as error:
                self.assertIsInstance(error,self.api.ReviewAttemptError)
                self.assertEqual(error.status['failure']['kind'],'stage-cleanup-failed')
            else:self.fail('Expected stage ownership rejection')

    def test_hangup_and_quit_have_scoped_handlers(self):
        import signal
        for signum in [signal.SIGHUP,signal.SIGQUIT]:
            old=signal.getsignal(signum);cancel={}
            with self.api._interrupts(cancel):
                handler=signal.getsignal(signum)
                self.assertTrue(callable(handler),'Missing scoped signal handler')
                handler(signum,None)
            self.assertEqual(cancel['signal'],int(signum))
            self.assertIs(signal.getsignal(signum),old)

    def test_relocated_attempt_is_rejected_before_recovery_commands(self):
        backend=Backend('create-unknown');error=self.failure(backend)
        old=Path(error.attempt_directory);parent=self.root/'moved';parent.mkdir(mode=0o700)
        moved=parent/old.name;old.rename(moved)
        count=len(backend.calls)
        with self.assertRaises(ValueError):self.api.recover(moved,_engine_factory=backend.factory)
        self.assertEqual(len(backend.calls),count)

    def test_real_client_boundary_caps_stdout_and_stderr_without_host_privileges(self):
        import sys
        original=self.api.subprocess.Popen
        for stream,size,cap in [('stdout',self.api.LIMIT+65536,self.api.LIMIT),('stderr',131072,65536)]:
            directory=self.root/stream;directory.mkdir(mode=0o700)
            job={};cancel={}
            code='import sys;sys.'+stream+'.buffer.write(b"x"*'+str(size)+');sys.'+stream+'.flush()'
            def local_child(argv,**kwargs):
                return original([sys.executable,'-I','-B','-c',code],**kwargs)
            with patch.object(self.api.sys,'platform','linux'),patch.object(self.api.subprocess,'Popen',local_child):
                engine=self.api.DockerEngine(directory,job,lambda:None,cancel)
                try:engine._client(['/usr/bin/docker','--config',str(directory/'docker-config')],2,'bounded-fixture',True)
                except Exception as error:
                    self.assertIsInstance(error,self.api._Failure)
                    self.assertEqual(error.details['kind'],'client-output-limit')
                else:self.fail('Unbounded client output was accepted')
            self.assertLessEqual((directory/'client-1.stdout').stat().st_size,self.api.LIMIT)
            self.assertLessEqual((directory/'client-1.stderr').stat().st_size,65536)

    def test_cli_failure_exit_codes_and_query_original_hint(self):
        import contextlib,io,signal
        for state,kind,signum,expected in [('completion-unconfirmed','completion-commit-unconfirmed',None,3),('cleanup-unconfirmed','cleanup-failed',None,2),('timed-out','timed-out',None,124),('interrupted','interrupted',signal.SIGTERM,143),('interrupted','interrupted',signal.SIGHUP,129),('failed','report-invalid',None,1)]:
            value={'state':state,'failure':{'kind':kind}}
            if signum:value['failure']['signal']=int(signum)
            error=self.api.ReviewAttemptError(self.root,value);out=io.StringIO()
            args=['snapshot','run','/bundle','a'*64,'/project','/manifest','/scan','d'*64,'e'*64]
            with patch.object(self.api.sys,'argv',args),patch.object(self.api,'execute',side_effect=error),contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as stopped:self.api.main()
            self.assertEqual(stopped.exception.code,expected)
            self.assertEqual(json.loads(out.getvalue())['nextOperation'],'status')

    def test_successful_create_stdout_restores_known_creation_after_lost_controller(self):
        backend=Backend('create-unknown');error=self.failure(backend)
        directory=Path(error.attempt_directory)
        job=json.loads((directory/'attempt.json').read_bytes())
        job['state']='creating';job.pop('failure',None)
        job['createClient']={'phase':'create','index':1,'exitCode':0}
        (directory/'client-1.stdout').write_text('c'*64+'\n')
        (directory/'attempt.json').write_text(json.dumps(job))
        recovered=self.api.recover(directory,_engine_factory=backend.factory)
        self.assertEqual(recovered['state'],'recovered')
        self.assertTrue(recovered['createEvidenceRestored'])
        self.assertEqual(sum(row[0]=='create' for row in backend.calls),1)
        self.assertFalse(any(row[0]=='start' for row in backend.calls))

    def test_client_history_is_bounded_and_keeps_creation_summary(self):
        import sys
        original=self.api.subprocess.Popen
        directory=self.root/'bounded-history';directory.mkdir(mode=0o700)
        creation={'phase':'create','index':1,'exitCode':0}
        job={'clientCounter':128,'clients':[{'index':i} for i in range(1,129)],'createClient':creation}
        def local_child(argv,**kwargs):
            return original([sys.executable,'-I','-B','-c','print("ok")'],**kwargs)
        with patch.object(self.api.sys,'platform','linux'),patch.object(self.api.subprocess,'Popen',local_child):
            engine=self.api.DockerEngine(directory,job,lambda:None,{})
            engine._client(['/usr/bin/docker'],1,'fixture',False)
        self.assertEqual(len(job['clients']),128)
        self.assertTrue(job['clientHistoryTruncated'])
        self.assertEqual(job['createClient'],creation)
        self.assertEqual(job['clientCounter'],129)

    def test_create_success_record_is_saved_after_stdout_is_flushed(self):
        import sys
        original=self.api.subprocess.Popen
        directory=self.root/'flushed-create';directory.mkdir(mode=0o700)
        job={}
        def local_child(argv,**kwargs):return original([sys.executable,'-I','-B','-c','print("c"*64)'],**kwargs)
        def saved():
            event=job.get('createClient',{})
            if event.get('exitCode')==0:self.assertEqual((directory/'client-1.stdout').read_bytes(),b'c'*64+b'\n')
        with patch.object(self.api.sys,'platform','linux'),patch.object(self.api.subprocess,'Popen',local_child):
            engine=self.api.DockerEngine(directory,job,saved,{})
            engine._client(['/usr/bin/docker'],1,'create',True)

    def test_symlinked_recovery_directory_is_rejected(self):
        error = self.failure(Backend('create-unknown'))
        link = self.root/'linked';link.symlink_to(Path(error.attempt_directory),target_is_directory=True)
        with self.assertRaises(ValueError):
            self.api.recover(link, _engine_factory=Backend().factory)

    def test_mount_option_characters_are_rejected_before_docker(self):
        self.attempts = self.root/'bad,option'
        backend = Backend()
        with self.assertRaises(ValueError):
            self.run_case(backend)
        self.assertEqual(backend.calls, [])


class InputBoundaryTest(unittest.TestCase):
    def setUp(self):
        SnapshotTest.setUp(self)

    def freeze(self):
        return SnapshotTest.freeze(self)

    def fixture(self):
        return SnapshotTest.execution_fixture(self)

    def run_fixture(self, fixture, backend):
        snapshot,project,manifest,scan=fixture
        return self.api.execute(self.bundle,self.api.digest(snapshot),project,manifest,scan,'d'*64,'e'*64,
                                attempts_root=self.root/'attempts',_engine_factory=backend.factory)

    def assert_batch_accepts(self, project, manifest, scan):
        import subprocess,sys
        run=subprocess.run([sys.executable,'-I','-B',str(self.sources/self.api.FILES[0]),str(project),str(manifest),str(scan)],
                           capture_output=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr.decode())
        self.assertEqual(json.loads(run.stdout)['version'],1)

    def test_source_limit_matches_frozen_reviewer_and_rejects_before_attempt(self):
        fixture=self.fixture();snapshot,project,manifest,scan=fixture
        source=project/'safe.py';size=1024*1024
        for length in [size,size+1]:
            source.write_bytes(b'#'+b' '*(length-1))
            manifest.write_text(json.dumps({'files':{'safe.py':sha256(source.read_bytes()).hexdigest()},'scanSha256':sha256(scan.read_bytes()).hexdigest()}))
            if length==size:
                self.api.inputs(project,manifest,scan)
                self.assert_batch_accepts(project,manifest,scan)
            else:
                backend=Backend()
                with self.assertRaisesRegex(ValueError,'byte limit'):
                    self.run_fixture(fixture,backend)
                self.assertEqual(backend.calls,[])
                self.assertFalse((self.root/'attempts').exists())

    def test_manifest_and_scan_exact_byte_limits_match_reviewer(self):
        fixture=self.fixture();_,project,manifest,scan=fixture
        request=json.loads(manifest.read_bytes())
        for kind,limit in [('manifest',1024*1024),('scan',8*1024*1024)]:
            with self.subTest(kind=kind):
                scan.write_bytes(b'{"results":[]}')
                request['scanSha256']=sha256(scan.read_bytes()).hexdigest()
                if kind=='scan':
                    scan.write_bytes(scan.read_bytes()+b' '*(limit-scan.stat().st_size))
                    request['scanSha256']=sha256(scan.read_bytes()).hexdigest()
                manifest.write_text(json.dumps(request))
                if kind=='manifest':manifest.write_bytes(manifest.read_bytes()+b' '*(limit-manifest.stat().st_size))
                self.api.inputs(project,manifest,scan)
                self.assert_batch_accepts(project,manifest,scan)
                target=manifest if kind=='manifest' else scan
                target.write_bytes(target.read_bytes()+b' ')
                if kind=='scan':
                    request['scanSha256']=sha256(scan.read_bytes()).hexdigest();manifest.write_text(json.dumps(request))
                with self.assertRaisesRegex(ValueError,'byte limit'):
                    self.api.inputs(project,manifest,scan)

    def test_total_source_limit_matches_reviewer(self):
        _,project,manifest,scan=self.fixture();files={}
        (project/'safe.py').unlink()
        for index in range(8):
            p=project/f'source{index}.py';p.write_bytes(b'#'+b' '*(1024*1024-1));files[p.name]=sha256(p.read_bytes()).hexdigest()
        request={'files':files,'scanSha256':sha256(scan.read_bytes()).hexdigest()}
        manifest.write_text(json.dumps(request));self.api.inputs(project,manifest,scan)
        self.assert_batch_accepts(project,manifest,scan)
        extra=project/'extra.py';extra.write_bytes(b'\n');files[extra.name]=sha256(extra.read_bytes()).hexdigest();manifest.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError,'byte limit'):self.api.inputs(project,manifest,scan)

    def test_snapshot_version_requires_integer_two(self):
        original=self.freeze()
        for version in [True,2.0,'2',None]:
            with self.subTest(version=version):
                manifest={**original,'version':version};(self.bundle/'snapshot.json').write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError,'snapshot'):
                    self.api.verify(self.bundle,self.api.digest(manifest))

    def test_input_json_requires_unique_keys_finite_values_utf8_and_bounded_nesting(self):
        _,project,manifest,scan=self.fixture()
        bad=[b'{"results":[],"results":[]}',b'{"results":[],"extra":NaN}',b'{"results":[],"extra":1e400}',
             '{"results":[]}'.encode('utf-16'),b'{"results":[],"extra":'+b'['*1500+b'0'+b']'*1500+b'}',b'[]']
        for raw in bad:
            with self.subTest(raw=raw[:50]):
                scan.write_bytes(raw)
                manifest.write_text(json.dumps({'files':{'safe.py':sha256((project/'safe.py').read_bytes()).hexdigest()},'scanSha256':sha256(raw).hexdigest()}))
                with self.assertRaises(ValueError):self.api.inputs(project,manifest,scan)

    def test_json_container_depth_has_an_explicit_boundary(self):
        expected=0
        for _ in range(64):expected=[expected]
        self.assertEqual(self.api.load_json(b'['*64+b'0'+b']'*64),expected)
        with self.assertRaisesRegex(ValueError,'nesting'):
            self.api.load_json(b'['*65+b'0'+b']'*65)

    def test_report_type_encoding_and_ambiguous_json_fail_without_completion(self):
        fixture=self.fixture()
        bad=[b'{"version":true}',b'{"version":1.0}',b'{"version":"1"}',b'{"version":1,"value":Infinity}',
             b'{"version":1,"version":1}', '{"version":1}'.encode('utf-16')]
        for raw in bad:
            with self.subTest(raw=raw[:50]):
                backend=Backend();backend.report=raw
                with self.assertRaises(self.api.ReviewAttemptError) as caught:self.run_fixture(fixture,backend)
                state=self.api.status(Path(caught.exception.attempt_directory))
                self.assertEqual(state['failure']['kind'],'report-invalid')
                self.assertTrue(state['cleanup']['confirmed']);self.assertNotIn('result',state);self.assertIsNone(backend.container)

    def test_non_utf8_source_is_rejected_before_attempt(self):
        fixture=self.fixture();_,project,manifest,scan=fixture
        (project/'safe.py').write_bytes(b'#\xff')
        manifest.write_text(json.dumps({'files':{'safe.py':sha256((project/'safe.py').read_bytes()).hexdigest()},'scanSha256':sha256(scan.read_bytes()).hexdigest()}))
        backend=Backend()
        with self.assertRaises(ValueError):self.run_fixture(fixture,backend)
        self.assertEqual(backend.calls,[]);self.assertFalse((self.root/'attempts').exists())

    def test_oversized_completion_record_cannot_commit_an_unreadable_result(self):
        fixture=self.fixture();backend=Backend();backend.report=json.dumps({'version':1,'data':'a'*10000}).encode()
        with patch.object(self.api,'ATTEMPT_LIMIT',16384,create=True):
            with self.assertRaises(self.api.ReviewAttemptError) as caught:self.run_fixture(fixture,backend)
            state=self.api.status(Path(caught.exception.attempt_directory))
        self.assertEqual(state['failure']['kind'],'completion-record-invalid')
        self.assertEqual(state['state'],'failed');self.assertTrue(state['cleanup']['confirmed']);self.assertNotIn('result',state)

    def test_atomic_record_limit_is_checked_before_replacing_previous_record(self):
        directory=self.root/'record';directory.mkdir(mode=0o700)
        previous={'state':'prepared'};self.api._save(directory,previous)
        original=(directory/'attempt.json').read_bytes()
        with patch.object(self.api,'ATTEMPT_LIMIT',len(original),create=True):
            with self.assertRaisesRegex(ValueError,'record.*byte limit'):
                self.api._save(directory,{'state':'prepared','large':'a'*len(original)})
        self.assertEqual((directory/'attempt.json').read_bytes(),original)
        self.assertEqual(list(directory.glob('.attempt-*.json')),[])

    def test_completion_nesting_must_remain_readable_inside_the_record(self):
        fixture=self.fixture();backend=Backend();nested=0
        for _ in range(62):nested=[nested]
        backend.report=json.dumps({'version':1,'data':nested}).encode()
        with self.assertRaises(self.api.ReviewAttemptError) as caught:self.run_fixture(fixture,backend)
        state=self.api.status(Path(caught.exception.attempt_directory))
        self.assertEqual(state['failure']['kind'],'completion-record-invalid')
        self.assertNotIn('result',state);self.assertTrue(state['cleanup']['confirmed'])


class CreationRecoveryTest(unittest.TestCase):
    def setUp(self):
        SnapshotTest.setUp(self)

    def freeze(self):return SnapshotTest.freeze(self)

    def fixture(self):return SnapshotTest.execution_fixture(self)

    def execute(self, fixture, backend):
        snapshot,project,manifest,scan=fixture
        return self.api.execute(self.bundle,self.api.digest(snapshot),project,manifest,scan,'d'*64,'e'*64,
                                attempts_root=self.root/'attempts',_engine_factory=backend.factory)

    def unknown_record(self):
        backend=Backend('create-unknown')
        with self.assertRaises(self.api.ReviewAttemptError) as caught:self.execute(self.fixture(),backend)
        return Path(caught.exception.attempt_directory),backend

    def test_creating_save_failure_before_client_is_known_not_started(self):
        original=self.api._save;backend=Backend();fixture=self.fixture();failed=[False]
        def fail_once(root,job,*args,**kwargs):
            if job['state']=='creating' and not failed[0]:
                failed[0]=True;raise OSError('synthetic creating save failure')
            return original(root,job,*args,**kwargs)
        with patch.object(self.api,'_save',fail_once):
            with self.assertRaises(self.api.ReviewAttemptError) as caught:self.execute(fixture,backend)
        state=caught.exception.status
        self.assertTrue(state['cleanup']['confirmed'])
        self.assertFalse(state['creationAttempted'])
        self.assertEqual(state['creationNotStarted']['basis'],'no-durable-create-event')
        self.assertFalse(any(row[0] in ['create','start'] for row in backend.calls))
        recovered=self.api.recover(caught.exception.attempt_directory,_engine_factory=backend.factory)
        self.assertEqual(recovered['state'],'recovered');self.assertNotIn('result',recovered)

    def test_recovery_accepts_absent_event_only_with_new_protocol(self):
        directory,backend=self.unknown_record();job=json.loads((directory/'attempt.json').read_bytes())
        job['creationJournalVersion']=1;job.pop('createClient',None);job['clients']=[]
        self.api._save(directory,job)
        actions=len(backend.calls);value=self.api.recover(directory,_engine_factory=backend.factory)
        self.assertEqual(value['state'],'recovered');self.assertFalse(value['creationAttempted'])
        self.assertEqual(value['creationNotStarted']['basis'],'no-durable-create-event')
        self.assertFalse(any(row[0] in ['create','start'] for row in backend.calls[actions:]));self.assertNotIn('result',value)

    def test_legacy_missing_event_and_conflicting_create_history_remain_unknown(self):
        directory,backend=self.unknown_record();original=json.loads((directory/'attempt.json').read_bytes())
        for case in ['legacy','conflicting-history','pid-present','exit-present']:
            with self.subTest(case=case):
                job=json.loads(json.dumps(original));job['clients']=[];job.pop('createClient',None)
                job['creationJournalVersion']=1
                if case=='legacy':job.pop('creationJournalVersion')
                elif case=='conflicting-history':job['clients']=[{'phase':'create','index':1}]
                else:
                    job['createClient']={'phase':'create','index':1,'notStarted':True}
                    job['createClient']['pid' if case=='pid-present' else 'exitCode']=12345 if case=='pid-present' else 1
                self.api._save(directory,job)
                value=self.api.recover(directory,_engine_factory=backend.factory)
                self.assertEqual(value['state'],'cleanup-unconfirmed');self.assertTrue(value['creationAttempted'])
                self.assertNotIn('result',value)

    def test_explicit_unstarted_create_event_can_be_recovered(self):
        directory,backend=self.unknown_record();job=json.loads((directory/'attempt.json').read_bytes())
        job['creationJournalVersion']=1;event={'phase':'create','index':1,'notStarted':True,'notStartedReason':'client-spawn-failed'}
        job['createClient']=event;job['clients']=[event];self.api._save(directory,job)
        value=self.api.recover(directory,_engine_factory=backend.factory)
        self.assertEqual(value['state'],'recovered')
        self.assertEqual(value['creationNotStarted']['basis'],'explicit-unstarted-create-event');self.assertNotIn('result',value)

    def test_real_popen_exec_error_is_recorded_as_not_started(self):
        import subprocess
        original=self.api.subprocess.Popen;directory=self.root/'exec-error';directory.mkdir(mode=0o700);job={}
        def absent(argv,**kwargs):return original([str(directory/'missing-executable')],**kwargs)
        with patch.object(self.api.sys,'platform','linux'),patch.object(self.api.subprocess,'Popen',absent):
            engine=self.api.DockerEngine(directory,job,lambda:None,{})
            try:engine._client(['/usr/bin/docker'],1,'create',True)
            except self.api._Failure as error:
                self.assertEqual(error.details['kind'],'client-spawn-failed');self.assertTrue(error.details['notStarted'])
            except OSError:self.fail('Popen failure escaped without not-started evidence')
            else:self.fail('Missing executable unexpectedly started')
        self.assertTrue(job['createClient']['notStarted']);self.assertNotIn('pid',job['createClient'])

    def test_log_preparation_failure_persists_unstarted_event(self):
        directory=self.root/'log-error';directory.mkdir(mode=0o700);job={};original=Path.open
        def denied(path,*args,**kwargs):
            if path.name=='client-1.stdout':raise PermissionError('synthetic log denial')
            return original(path,*args,**kwargs)
        with patch.object(self.api.sys,'platform','linux'),patch.object(Path,'open',denied),patch.object(self.api.subprocess,'Popen') as spawn:
            engine=self.api.DockerEngine(directory,job,lambda:None,{})
            with self.assertRaises(self.api._Failure):engine._client(['/usr/bin/docker'],1,'create',True)
        spawn.assert_not_called();self.assertTrue(job['createClient'].get('notStarted'))

    def test_cancel_after_log_preparation_does_not_invoke_popen(self):
        import signal
        directory=self.root/'cancel-log';directory.mkdir(mode=0o700);job={};cancel={};original=Path.open
        def cancel_now(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            if path.name=='client-1.stderr':cancel['signal']=int(signal.SIGTERM)
            return stream
        with patch.object(self.api.sys,'platform','linux'),patch.object(Path,'open',cancel_now),patch.object(self.api.subprocess,'Popen',side_effect=AssertionError('Cancelled client spawned')) as spawn:
            engine=self.api.DockerEngine(directory,job,lambda:None,cancel)
            with self.assertRaises(self.api._Failure) as caught:engine._client(['/usr/bin/docker'],1,'create',True)
            self.assertEqual(caught.exception.details['kind'],'interrupted')
        spawn.assert_not_called();self.assertTrue(job['createClient'].get('notStarted'))

    def test_creation_protocol_requires_integer_one(self):
        directory,backend=self.unknown_record();original=json.loads((directory/'attempt.json').read_bytes())
        for version in [True,1.0,'1',2]:
            job={**original,'creationJournalVersion':version};self.api._save(directory,job);actions=len(backend.calls)
            with self.assertRaisesRegex(ValueError,'invalid owned attempt record'):
                self.api.recover(directory,_engine_factory=backend.factory)
            self.assertEqual(len(backend.calls),actions)

    def test_existing_cid_file_prevents_never_started_inference(self):
        directory,backend=self.unknown_record();job=json.loads((directory/'attempt.json').read_bytes())
        job['creationJournalVersion']=1;event={'phase':'create','index':1,'notStarted':True,'notStartedReason':'client-spawn-failed'}
        job['createClient']=event;job['clients']=[event];self.api._save(directory,job)
        (directory/'container.cid').write_text('c'*64+'\n')
        value=self.api.recover(directory,_engine_factory=backend.factory)
        self.assertEqual(value['state'],'cleanup-unconfirmed');self.assertTrue(value['creationAttempted'])

    def test_malformed_unstarted_reason_remains_unconfirmed_without_traceback(self):
        directory,backend=self.unknown_record();original=json.loads((directory/'attempt.json').read_bytes())
        for reason in [[],{}]:
            with self.subTest(reason=reason):
                job=json.loads(json.dumps(original));event={'phase':'create','index':1,'notStarted':True,'notStartedReason':reason}
                job['creationJournalVersion']=1;job['createClient']=event;job['clients']=[event];self.api._save(directory,job)
                try:value=self.api.recover(directory,_engine_factory=backend.factory)
                except Exception as error:self.fail('Malformed reason escaped recovery: '+type(error).__name__)
                self.assertEqual(value['state'],'cleanup-unconfirmed');self.assertTrue(value['creationAttempted'])
                self.assertEqual(value['failure'],original['failure']);self.assertNotIn('result',value)


class RetentionInventoryTest(unittest.TestCase):
    def setUp(self):
        SnapshotTest.setUp(self)
        self.assertTrue(callable(getattr(self.api,'retention_inventory',None)),'Read-only retention inventory is missing')
        self.attempts=self.root/'attempts'

    def freeze(self):return SnapshotTest.freeze(self)

    def completed(self):
        from datetime import datetime,timedelta
        snapshot,project,manifest,scan=SnapshotTest.execution_fixture(self)
        value=self.api.execute(self.bundle,self.api.digest(snapshot),project,manifest,scan,'d'*64,'e'*64,
                               attempts_root=self.attempts,_engine_factory=Backend().factory)
        directory=Path(value['attemptDirectory']);job=self.api.status(directory)
        self.now=datetime.fromisoformat(job['finishedAt'])+timedelta(days=31)
        return directory

    def inventory(self,**kwargs):
        return self.api.retention_inventory(self.attempts,now=self.now,**kwargs)

    def test_missing_root_returns_empty_preview_without_creating_it(self):
        plan=self.api.retention_inventory(self.attempts)
        self.assertFalse(self.attempts.exists());self.assertFalse(plan['directoryExists'])
        self.assertEqual(plan['entries'],[]);self.assertEqual(plan['capacity']['knownLogicalBytes'],0)
        self.assertEqual(plan['capacity']['state'],'within');self.assertTrue(plan['readOnly']);self.assertFalse(plan['deleteEnabled'])

    def test_terminal_old_record_is_archive_candidate_with_bound_fingerprints(self):
        directory=self.completed();log=directory/'client-1.stdout';log.write_bytes(b'private-synthetic-marker');log.chmod(0o600)
        before={str(p.relative_to(self.attempts)):(p.stat().st_size,p.stat().st_mtime_ns,sha256(p.read_bytes()).hexdigest()) for p in self.attempts.rglob('*') if p.is_file()}
        with patch.object(self.api.subprocess,'Popen',side_effect=AssertionError('No process in read-only preview')):
            plan=self.inventory()
        row=plan['entries'][0]
        self.assertEqual(row['classification'],'archive-candidate');self.assertFalse(row['safeToDelete'])
        self.assertEqual(row['files']['client-1.stdout']['sha256'],sha256(log.read_bytes()).hexdigest())
        self.assertEqual(row['recordSha256'],sha256((directory/'attempt.json').read_bytes()).hexdigest())
        self.assertIn('fresh-resource-check',row['requires']);self.assertIn('archive-verification',row['requires'])
        self.assertNotIn('private-synthetic-marker',json.dumps(plan))
        self.assertEqual(plan['planSha256'],self.api.digest({k:v for k,v in plan.items() if k!='planSha256'}))
        after={str(p.relative_to(self.attempts)):(p.stat().st_size,p.stat().st_mtime_ns,sha256(p.read_bytes()).hexdigest()) for p in self.attempts.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_recent_record_and_future_time_are_retained(self):
        from datetime import datetime,timedelta
        directory=self.completed();finished=datetime.fromisoformat(self.api.status(directory)['finishedAt'])
        recent=self.api.retention_inventory(self.attempts,now=finished+timedelta(days=1))
        self.assertIn('minimum-age',recent['entries'][0]['reasons'])
        future=self.api.retention_inventory(self.attempts,now=finished-timedelta(seconds=1))
        self.assertEqual(future['entries'][0]['classification'],'retain');self.assertIn('invalid-time',future['entries'][0]['reasons'])

    def test_active_operation_is_retained_and_existing_lock_is_not_replaced(self):
        directory=self.completed();original=(directory/'operation.lock').stat().st_ino
        with self.api.operation_lock(directory):plan=self.inventory()
        self.assertEqual(plan['entries'][0]['classification'],'retain');self.assertIn('active-operation',plan['entries'][0]['reasons'])
        self.assertEqual((directory/'operation.lock').stat().st_ino,original)

    def test_missing_lock_is_not_created_by_inventory(self):
        directory=self.completed();(directory/'operation.lock').unlink()
        plan=self.inventory();self.assertFalse((directory/'operation.lock').exists())
        self.assertEqual(plan['entries'][0]['classification'],'retain');self.assertIn('missing-lock',plan['entries'][0]['reasons'])

    def test_unknown_corrupt_and_stage_present_records_are_protected(self):
        directory=self.completed();original=(directory/'attempt.json').read_bytes()
        for scenario in ['unknown','corrupt','stage']:
            with self.subTest(scenario=scenario):
                (directory/'attempt.json').write_bytes(original)
                if scenario=='unknown':
                    job=json.loads(original);job['state']='cleanup-unconfirmed';job.pop('result',None);job.pop('resultSha256',None);self.api._save(directory,job)
                elif scenario=='corrupt':(directory/'attempt.json').write_bytes(b'{broken')
                else:(directory/'stage').mkdir(mode=0o700);(directory/'stage/private.py').write_bytes(b'private-stage-marker')
                plan=self.inventory();row=plan['entries'][0]
                self.assertEqual(row['classification'],'retain');self.assertFalse(row['safeToDelete'])
                self.assertNotIn('private-stage-marker',json.dumps(plan))
        self.assertTrue((directory/'stage/private.py').exists())

    def test_incomplete_cleanup_flags_cannot_be_candidate(self):
        directory=self.completed();job=json.loads((directory/'attempt.json').read_bytes());job['cleanup']={'confirmed':True};self.api._save(directory,job)
        row=self.inventory()['entries'][0]
        self.assertEqual(row['classification'],'retain');self.assertIn('unconfirmed-cleanup',row['reasons'])

    def test_links_and_unexpected_configuration_are_never_read_or_eligible(self):
        directory=self.completed();outside=self.root/'outside';outside.write_text('outside-private-marker')
        (directory/'client-1.stdout').symlink_to(outside)
        (directory/'docker-config/config.json').write_text('configuration-private-marker')
        plan=self.inventory();row=plan['entries'][0]
        self.assertEqual(row['classification'],'retain');self.assertIn('unsafe-entry',row['reasons'])
        self.assertNotIn('sha256',row['files']['client-1.stdout'])
        self.assertNotIn('outside-private-marker',json.dumps(plan));self.assertNotIn('configuration-private-marker',json.dumps(plan))

    def test_budget_reports_known_bytes_and_never_deletes_to_meet_it(self):
        directory=self.completed();total=sum(p.stat().st_size for p in self.attempts.rglob('*') if p.is_file())
        plan=self.inventory(budget_bytes=total-1)
        self.assertTrue(plan['capacity']['complete']);self.assertEqual(plan['capacity']['state'],'exceeded')
        self.assertEqual(plan['capacity']['knownLogicalBytes'],total);self.assertTrue((directory/'attempt.json').exists())

    def test_truncated_enumeration_marks_total_unknown(self):
        self.completed()
        with patch.object(self.api,'RETENTION_MAX_ENTRIES',1,create=True):plan=self.inventory()
        self.assertFalse(plan['capacity']['complete']);self.assertEqual(plan['capacity']['state'],'unknown')
        self.assertFalse(any(r['classification']=='archive-candidate' for r in plan['entries']))

    def test_hash_budget_protects_candidate_without_losing_capacity_statistics(self):
        self.completed()
        with patch.object(self.api,'RETENTION_HASH_LIMIT',1,create=True):plan=self.inventory()
        self.assertEqual(plan['entries'][0]['classification'],'retain');self.assertIn('hash-budget',plan['entries'][0]['reasons'])
        self.assertGreater(plan['capacity']['knownLogicalBytes'],1)

    def test_invalid_policy_and_linked_root_are_rejected(self):
        self.completed();link=self.root/'linked-attempts';link.symlink_to(self.attempts,target_is_directory=True)
        with self.assertRaises(ValueError):self.api.retention_inventory(link)
        for kwargs in [{'budget_bytes':True},{'budget_bytes':0},{'minimum_age_days':-1},{'minimum_age_days':1.0}]:
            with self.assertRaises(ValueError):self.inventory(**kwargs)

    def test_inventory_cli_prints_preview_without_execution(self):
        import contextlib,io
        self.completed();out=io.StringIO()
        args=['snapshot','retention-inventory',str(self.attempts),'--minimum-age-days','0','--budget-mib','256']
        with patch.object(self.api.sys,'argv',args),patch.object(self.api.subprocess,'Popen',side_effect=AssertionError('No subprocess')),contextlib.redirect_stdout(out):
            self.api.main()
        plan=json.loads(out.getvalue());self.assertTrue(plan['readOnly']);self.assertFalse(plan['deleteEnabled'])

    def test_concurrent_growth_cannot_exceed_hash_read_budget(self):
        import os
        directory=self.completed();log=directory/'client-1.stdout';log.write_bytes(b'x');log.chmod(0o600)
        inode=log.stat().st_ino;original=self.api.os.read;changed=[False]
        budget=sum(p.stat().st_size for p in self.attempts.rglob('*') if p.is_file())
        def grow(fd,size):
            if os.fstat(fd).st_ino==inode and not changed[0]:
                changed[0]=True;log.write_bytes(b'x'*100)
            return original(fd,size)
        with patch.object(self.api,'RETENTION_HASH_LIMIT',budget),patch.object(self.api.os,'read',grow):plan=self.inventory()
        self.assertTrue(changed[0]);self.assertLessEqual(plan['hashedBytes'],budget)
        self.assertFalse(plan['capacity']['complete']);self.assertEqual(plan['entries'][0]['classification'],'retain')

    def test_unexpected_empty_directory_protects_record(self):
        directory=self.completed();(directory/'extra-dir').mkdir(mode=0o700)
        row=self.inventory()['entries'][0]
        self.assertEqual(row['classification'],'retain');self.assertIn('unsafe-entry',row['reasons'])

    def test_foreign_directory_is_not_opened_for_descent(self):
        import types,os
        directory=self.completed();(directory/'extra-dir').mkdir(mode=0o700)
        original_stat=self.api.os.stat;original_open=self.api.os.open
        def foreign(path,*args,**kwargs):
            value=original_stat(path,*args,**kwargs)
            if path=='extra-dir' and 'dir_fd' in kwargs:
                keys=['st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_mtime_ns']
                return types.SimpleNamespace(**{k:os.geteuid()+1 if k=='st_uid' else getattr(value,k) for k in keys})
            return value
        def guarded(path,*args,**kwargs):
            if path=='extra-dir':self.fail('Opened foreign directory')
            return original_open(path,*args,**kwargs)
        with patch.object(self.api.os,'stat',foreign),patch.object(self.api.os,'open',guarded):plan=self.inventory()
        self.assertEqual(plan['entries'][0]['classification'],'retain');self.assertFalse(plan['capacity']['complete'])

    def test_replaced_lock_cannot_leave_a_candidate(self):
        import fcntl
        directory=self.completed();original=self.api.fcntl.flock;changed=[False]
        def replace_lock(fd,operation):
            result=original(fd,operation)
            if operation&fcntl.LOCK_SH and not changed[0]:
                changed[0]=True;p=directory/'operation.lock';p.unlink();p.write_bytes(b'');p.chmod(0o600)
            return result
        with patch.object(self.api.fcntl,'flock',replace_lock):plan=self.inventory()
        self.assertTrue(changed[0]);self.assertEqual(plan['entries'][0]['classification'],'retain')
        self.assertIn('changed-lock',plan['entries'][0]['reasons']);self.assertFalse(plan['capacity']['complete'])

    def test_top_level_foreign_device_is_not_traversed(self):
        import types
        directory=self.completed();inode=directory.stat().st_ino;original=self.api.os.fstat
        def mounted(fd):
            value=original(fd)
            if value.st_ino==inode:
                keys=['st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_mtime_ns']
                return types.SimpleNamespace(**{k:value.st_dev+1 if k=='st_dev' else getattr(value,k) for k in keys})
            return value
        with patch.object(self.api.os,'fstat',mounted):plan=self.inventory()
        row=plan['entries'][0];self.assertEqual(row['classification'],'retain');self.assertIn('unsafe-entry',row['reasons'])
        self.assertEqual(row['files'],{});self.assertFalse(plan['capacity']['complete'])

    def test_pre_record_attempt_does_not_acquire_shared_lock(self):
        directory=self.completed();(directory/'attempt.json').unlink()
        with patch.object(self.api.fcntl,'flock',side_effect=AssertionError('Pre-record preview acquired lock')):plan=self.inventory()
        row=plan['entries'][0];self.assertEqual(row['classification'],'retain');self.assertIn('record-unavailable',row['reasons'])
        self.assertTrue((directory/'operation.lock').exists())

    def test_nonregular_record_does_not_report_a_missing_existing_lock(self):
        directory=self.completed();(directory/'attempt.json').unlink();(directory/'attempt.json').mkdir(mode=0o700)
        row=self.inventory()['entries'][0]
        self.assertIn('record-unavailable',row['reasons']);self.assertNotIn('missing-lock',row['reasons'])


class StorageClosureTest(unittest.TestCase):
    def setUp(self):SnapshotTest.setUp(self)
    def freeze(self):return SnapshotTest.freeze(self)

    def test_storage_exists_and_uses_only_fixed_trusted_tool_bytes(self):
        self.assertTrue((HERE/'reviewer_storage.py').is_file(),'Storage maintenance module missing')
        manifest=self.freeze();module=self.api.storage_module(manifest['storageSha256'])
        self.assertEqual(module.__source_sha256__,manifest['storageSha256'])
        self.assertEqual(module.DEFAULT_BUDGET_BYTES,256*1024*1024)
        self.assertEqual(module.MIN_FREE_BYTES,512*1024*1024)

    def test_rebound_bundle_storage_is_rejected_without_execution(self):
        self.assertTrue((HERE/'reviewer_storage.py').is_file(),'Storage module missing')
        manifest=self.freeze();marker=self.root/'executed'
        raw=('from pathlib import Path\nPath('+repr(str(marker))+').write_text("bad")\n').encode()
        (self.bundle/'reviewer_storage.py').write_bytes(raw);manifest['storageSha256']=sha256(raw).hexdigest()
        (self.bundle/'snapshot.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'storage'):self.api.verify(self.bundle,self.api.digest(manifest))
        self.assertFalse(marker.exists())

    def test_legacy_snapshot_is_diagnostic_only(self):
        manifest=self.freeze();manifest['version']=1;manifest.pop('storageSha256',None)
        if (self.bundle/'reviewer_storage.py').exists():(self.bundle/'reviewer_storage.py').unlink()
        (self.bundle/'snapshot.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'legacy|diagnostic'):self.api.verify(self.bundle,self.api.digest(manifest))

    def test_loader_rejects_mismatch_and_extra_imports_before_execution(self):
        marker=self.root/'unexpected-execution';raw=('import os\nos.open('+repr(str(marker))+',os.O_CREAT|os.O_WRONLY,384)\n').encode()
        with patch.object(self.api,'read',return_value=raw):
            with self.assertRaisesRegex(ValueError,'digest'):self.api.storage_module('f'*64)
        self.assertFalse(marker.exists())
        raw=b'import unreviewed_helper\n'
        with patch.object(self.api,'read',return_value=raw):
            with self.assertRaisesRegex(ValueError,'import'):self.api.storage_module(sha256(raw).hexdigest())

    def test_installed_storage_drift_invalidates_snapshot(self):
        installed=self.root/'installed';installed.mkdir()
        for name in ['reviewer_snapshot.py','reviewer_storage.py']:shutil.copyfile(HERE/name,installed/name)
        spec=importlib.util.spec_from_file_location('isolated_tool',installed/'reviewer_snapshot.py');tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
        manifest=tool.freeze(self.sources,self.bundle,IMAGE)
        (installed/'reviewer_storage.py').write_bytes((installed/'reviewer_storage.py').read_bytes()+b'\n# changed\n')
        with self.assertRaisesRegex(ValueError,'storage'):tool.verify(self.bundle,tool.digest(manifest))


if __name__ == '__main__':
    unittest.main()
