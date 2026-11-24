"""D1/D2/R1 regression cases; only owned files, pipes and synthetic processes."""
import contextlib, fcntl, hashlib, importlib.util, io, json, os
from pathlib import Path
import signal, subprocess, sys, tempfile, threading, time, unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('admission_candidate', ROOT/'tooling/admission.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class Regressions(unittest.TestCase):
    def test_queue_timeout_is_preserved_as_not_sent_without_executor_call(self):
        m = load()
        with tempfile.TemporaryDirectory() as temp:
            lock = os.open(Path(temp)/'.ssh-channel.lock', os.O_RDWR|os.O_CREAT, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
                out = io.StringIO()
                with contextlib.redirect_stdout(out), patch('sys.stdin', io.StringIO('GO\n')):
                    m.worker(str(ROOT/'inputs/manage.py'), m.MANAGER_SHA, temp,
                             'existing-queue', '65535', '0')
                row = json.loads(out.getvalue().splitlines()[-1])
            finally: os.close(lock)
        self.assertEqual(row['commandCalls'], 0)
        self.assertEqual(row['errorStage'], 'queue')
        self.assertEqual(row.get('requestState'), 'not-sent')
        trial = fixture_trial('existing-queue', 0)
        trial['clients'][0] = row; trial['serverEvents'].pop(0)
        aggregate = m.summarize([trial])[0]
        self.assertEqual(aggregate['notSent'], 1)
        self.assertEqual(aggregate['failed'], 0)
        self.assertEqual(aggregate['complete'], 5)

    def test_zero_calls_without_queue_timeout_proof_is_rejected(self):
        row = fixture_trial('existing-queue', 0)
        row['clients'][0].update(commandCalls=0, complete=False, connected=False,
                                  returncode=1, requestState='not-sent',
                                  errorStage='queue-or-worker', errorType='ValueError')
        with self.assertRaises(ValueError): load().summarize([row])

    def test_failed_exchange_with_exit_zero_is_rejected(self):
        row = fixture_trial('unqueued', 0)
        row['clients'][0].update(complete=False, requestState='failed',
                                  errorStage='reply', errorType='EOF')
        with self.assertRaises(ValueError): load().summarize([row])

    def test_analysis_rejects_forged_aggregate_in_normal_and_optimized_python(self):
        for optimized in [False, True]:
            with self.subTest(optimized=optimized), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); fixture_dataset(root)
                value = json.loads((root/'control-results.json').read_text())
                value['aggregates'][0]['clients'] = 999
                (root/'control-results.json').write_text(json.dumps(value))
                result = analyze_subprocess(root, optimized)
                self.assertNotEqual(result.returncode, 0, 'Forged aggregate accepted')
                self.assertFalse((root/'analysis.json').exists())

    def test_optimized_python_cannot_skip_contract_digest_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture_dataset(root)
            value = json.loads((root/'control-results.json').read_text())
            value['contractSha256'] = '0'*64
            (root/'control-results.json').write_text(json.dumps(value))
            result = analyze_subprocess(root, True)
            self.assertNotEqual(result.returncode, 0, 'python -O bypassed contract verification')
            self.assertFalse((root/'analysis.json').exists())

    def test_analysis_checks_server_evidence_and_full_schedule(self):
        for kind in ['response', 'schedule']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); fixture_dataset(root)
                value = json.loads((root/'control-results.json').read_text())
                if kind == 'response': value['trials'][0]['serverEvents'].pop()
                else: value['trials'].pop()
                (root/'control-results.json').write_text(json.dumps(value))
                result = analyze_subprocess(root, True)
                self.assertNotEqual(result.returncode, 0, 'Incomplete evidence accepted')

    def test_valid_dataset_is_independently_recomputed_under_optimized_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture_dataset(root)
            result = analyze_subprocess(root, True)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads((root/'analysis.json').read_text())
            self.assertTrue(value.get('independentlyRecomputed'), 'No independent recomputation')
            self.assertEqual(sum(r['complete'] for r in value['aggregates']), 48)

    def test_independent_analysis_preserves_legal_not_sent_outcome(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture_dataset(root)
            value = json.loads((root/'control-results.json').read_text())
            trial = next(t for t in value['trials'] if t['mode'] == 'existing-queue')
            trial['clients'][0] = dict(index=0, commandCalls=0, connected=False,
                complete=False, requestState='not-sent', returncode=1, errorStage='queue',
                errorType='SSHNotSent', requestEnteredMonoNs=100, requestEndedMonoNs=200)
            trial['serverEvents'].pop(0)
            aggregate = value['aggregates'][1]
            aggregate.update(connected=23, complete=23, notSent=1,
                             notSentReasons={'queue|SSHNotSent|None': 1})
            (root/'control-results.json').write_text(json.dumps(value))
            result = analyze_subprocess(root, True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = json.loads((root/'analysis.json').read_text())['aggregates']
            self.assertEqual(rows[1]['notSent'], 1)
            self.assertEqual(rows[1]['failed'], 0)

    def test_permanent_kill_failure_reports_unconfirmed_cleanup(self):
        m = load(); child = FakeChild(0, 'none')
        child.kill = lambda: (_ for _ in ()).throw(PermissionError('permanent synthetic fault'))
        result = m.cleanup_owned([child], FakeThread(), threading.Event(), threading.Event())
        self.assertFalse(result['allChildrenReaped'])
        self.assertFalse(result['ok'])
        self.assertTrue(result['errors'])

    def check_trial_cleanup(self, fault):
        m = load(); events = [threading.Event(), threading.Event()]
        workers = [FakeChild(i, fault) for i in range(6)]; thread = FakeThread()
        caught = None
        with patch.object(m.threading, 'Event', side_effect=events), \
                patch.object(m.threading, 'Thread', return_value=thread), \
                patch.object(m.subprocess, 'Popen', side_effect=workers), \
                patch.object(m.select, 'select', side_effect=TimeoutError('synthetic body failure')):
            try: m.trial(0, 'unqueued', '0'*64)
            except BaseException as error: caught = error
        self.assertIsNotNone(caught)
        self.assertTrue(events[1].is_set(), 'Server stop skipped after cleanup exception')
        self.assertTrue(events[0].is_set(), 'Gate was not released for shutdown')
        self.assertTrue(thread.joined, 'Join skipped after cleanup exception')
        self.assertTrue(all(c.kill_calls for c in workers[1:]), 'Later owned workers skipped')

    def test_kill_failure_cannot_skip_other_owned_workers_or_server(self):
        self.check_trial_cleanup('kill')

    def test_communicate_failure_cannot_skip_other_owned_workers_or_server(self):
        self.check_trial_cleanup('communicate')

    def test_cleanup_interrupt_cannot_skip_other_owned_workers_or_server(self):
        self.check_trial_cleanup('interrupt')

    def test_real_owned_children_are_reaped_despite_one_drain_failure(self):
        m = load()
        self.assertTrue(hasattr(m, 'cleanup_owned'), 'Missing bounded shared cleanup')
        children = [subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time;time.sleep(10)'],
                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        stop = threading.Event(); gate = threading.Event()
        thread = threading.Thread(target=lambda: (gate.wait(2), stop.wait(2))); thread.start()
        original = children[0].communicate
        try:
            with patch.object(children[0], 'communicate', side_effect=OSError('synthetic drain fault')):
                result = m.cleanup_owned(children, thread, stop, gate)
            self.assertTrue(result['allChildrenReaped'])
            self.assertTrue(result['serverStopped'])
            self.assertTrue(result['errors'])
            self.assertTrue(all(p.poll() is not None for p in children))
        finally:
            stop.set(); gate.set(); thread.join(2)
            for child in children:
                if child.poll() is None: child.kill()
                child.wait(timeout=2)
                for stream in [child.stdin, child.stdout, child.stderr]:
                    if stream and not stream.closed: stream.close()

    def test_sigterm_during_cleanup_is_deferred_until_resources_stop(self):
        m = load(); self.assertTrue(hasattr(m, 'cleanup_owned'), 'Missing bounded shared cleanup')
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time;time.sleep(10)'],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stop = threading.Event(); gate = threading.Event()
        thread = threading.Thread(target=lambda: (gate.wait(2), stop.wait(2))); thread.start()
        prior = signal.getsignal(signal.SIGTERM); original = child.communicate
        def drain(**kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            return original(**kwargs)
        try:
            signal.signal(signal.SIGTERM, m.expire)
            with patch.object(child, 'communicate', side_effect=drain):
                result = m.cleanup_owned([child], thread, stop, gate)
            self.assertTrue(result['allChildrenReaped']); self.assertTrue(result['serverStopped'])
            self.assertIn(signal.SIGTERM, result['interruptedSignals'])
            self.assertIs(signal.getsignal(signal.SIGTERM), m.expire)
        finally:
            signal.signal(signal.SIGTERM, prior); stop.set(); gate.set(); thread.join(2)
            if child.poll() is None: child.kill()
            child.wait(timeout=2)
            for stream in [child.stdin, child.stdout, child.stderr]:
                if stream and not stream.closed: stream.close()


class FakeChild:
    def __init__(self, index, fault):
        self.index=index; self.fault=fault; self.returncode=None; self.kill_calls=0
        self.stdin=io.BytesIO(); self.stdout=io.BytesIO(); self.stderr=io.BytesIO()
    def poll(self): return self.returncode
    def kill(self):
        self.kill_calls += 1
        if self.index == 0 and self.fault == 'kill' and self.kill_calls == 1:
            raise PermissionError('synthetic kill failure')
        self.returncode=-9
    def communicate(self, **kwargs):
        if self.index == 0 and self.fault == 'communicate': raise OSError('synthetic drain failure')
        if self.index == 0 and self.fault == 'interrupt': raise KeyboardInterrupt()
        return b'', b''
    def wait(self, **kwargs): return self.returncode


class FakeThread:
    joined=False
    def start(self): pass
    def join(self, **kwargs): self.joined=True
    def is_alive(self): return False


def fixture_trial(mode, block):
    clients=[]; events=[]
    for i in range(6):
        t=100+10*i
        clients.append(dict(index=i, commandCalls=1, complete=True, connected=True,
                            requestState='complete', returncode=0, requestEnteredMonoNs=t,
                            exchangeStartedMonoNs=t+1, connectReturnedMonoNs=t+2,
                            exchangeEndedMonoNs=t+3, requestEndedMonoNs=t+4))
        events.append(dict(requestIndex=i, responseSent=True, requestBytes=1, acceptedMonoNs=t+2))
    return dict(block=block, mode=mode, clients=clients, serverEvents=events,
                serverErrors=[], workersReaped=True, serverStopped=True, releaseMonoNs=1)


def fixture_dataset(root):
    m=load(); trials=[fixture_trial(r['mode'],r['block']) for r in m.schedule()]
    # Do not use the candidate summarizer to construct the expected aggregates.
    aggregates=[dict(mode=mode,trials=4,clients=24,connected=24,complete=24,failed=0,
                     notSent=0,errors={},notSentReasons={}) for mode in m.MODES]
    paths=['tooling/admission.py','record-analysis.py','tooling/regression.test.py','inputs/manage.py','tooling/analysis.test.py','tooling/r2.test.py']
    for name in paths:
        target=root/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes((ROOT/name).read_bytes())
    contract=dict(sources={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in paths},
                  schedule=m.schedule(),maxClients=48)
    (root/'execution-contract.json').write_text(json.dumps(contract))
    (root/'control-results.json').write_text(json.dumps(dict(
        contractSha256=hashlib.sha256((root/'execution-contract.json').read_bytes()).hexdigest(),
        trials=trials,aggregates=aggregates)))
    (root/'baseline.json').write_text(json.dumps(dict(canonicalFiles={},
        installedManagerSha256=m.MANAGER_SHA,exportManagerSha256='unused',
        sshFunctionHashes={'installed':'same','export':'same'})))


def analyze_subprocess(root, optimized):
    bootstrap='''from pathlib import Path
import sys
raw=Path(sys.argv[1]).read_bytes()
ns={'__name__':'analysis_test_import','__file__':str(Path(sys.argv[2])/'record-analysis.py')}
exec(compile(raw,sys.argv[1],'exec'),ns)
if 'write_analysis' in ns:ns['write_analysis'](Path(sys.argv[2]))
'''
    argv=[sys.executable,'-I','-B']+(['-O'] if optimized else [])
    return subprocess.run([*argv,'-c',bootstrap,str(ROOT/'record-analysis.py'),str(root)],
                          capture_output=True,text=True,timeout=5)


if __name__ == '__main__': unittest.main()
