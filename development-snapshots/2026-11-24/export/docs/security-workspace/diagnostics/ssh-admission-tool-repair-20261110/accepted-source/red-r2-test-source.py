"""Reproduce review blockers with deterministic files/signals/owned pipes."""
import importlib.util, json, os, signal, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fixtures',ROOT/'tooling/regression.test.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)


class ReviewRegressions(unittest.TestCase):
    def test_missing_analysis_test_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixtures.fixture_dataset(root)
            contract=json.loads((root/'execution-contract.json').read_text())
            del contract['sources']['tooling/analysis.test.py']
            (root/'execution-contract.json').write_text(json.dumps(contract))
            result=json.loads((root/'control-results.json').read_text())
            import hashlib
            result['contractSha256']=hashlib.sha256((root/'execution-contract.json').read_bytes()).hexdigest()
            (root/'control-results.json').write_text(json.dumps(result))
            value=fixtures.analyze_subprocess(root,True)
            self.assertNotEqual(value.returncode,0,'Incomplete source set accepted')

    def test_bad_server_event_types_and_times_are_rejected(self):
        for kind in ['missing-time','truthy-string','bytes-bool','before-request','after-completion','reverse-order']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);fixtures.fixture_dataset(root)
                result=json.loads((root/'control-results.json').read_text())
                event=result['trials'][0]['serverEvents'][0]
                if kind=='missing-time':del event['acceptedMonoNs']
                elif kind=='truthy-string':event['responseSent']='yes'
                elif kind=='bytes-bool':event['requestBytes']=True
                elif kind=='before-request':event['acceptedMonoNs']=1
                elif kind=='after-completion':event['acceptedMonoNs']=999999
                else:result['trials'][0]['serverEvents'].reverse()
                (root/'control-results.json').write_text(json.dumps(result))
                value=fixtures.analyze_subprocess(root,True)
                self.assertNotEqual(value.returncode,0,'Invalid server event accepted')

    def test_cancel_handler_records_without_async_exception(self):
        m=fixtures.load()
        try:m.expire(signal.SIGTERM,None)
        except BaseException as error:self.fail('Cancellation raised during arbitrary bytecode: '+type(error).__name__)
        self.assertTrue(m.pending_cancellation())

    def test_nonmain_cleanup_never_claims_supported_success(self):
        m=fixtures.load();result=[]
        def run():result.append(m.cleanup_owned([],fixtures.FakeThread(),threading.Event(),threading.Event()))
        thread=threading.Thread(target=run);thread.start();thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result[0]['ok'],'Unsupported nonmain cleanup reported success')
        self.assertTrue(result[0]['errors'])

    def test_body_exception_retains_cleanup_details(self):
        m=fixtures.load();workers=[fixtures.FakeChild(i,'communicate') for i in range(6)]
        thread=fixtures.FakeThread();error=TimeoutError('original synthetic body failure');caught=None
        with patch.object(m.threading,'Thread',return_value=thread),patch.object(m.subprocess,'Popen',side_effect=workers),patch.object(m.select,'select',side_effect=error):
            try:m.trial(0,'unqueued','0'*64)
            except BaseException as result:caught=result
        self.assertIs(caught,error,'Cleanup replaced original body exception')
        self.assertTrue(hasattr(caught,'cleanup'),'Cleanup details lost from failed body')
        self.assertTrue(caught.cleanup['errors'])

    def test_cleanup_failure_exception_carries_full_report(self):
        m=fixtures.load();self.assertTrue(hasattr(m,'CleanupFailure'),'Missing structured failure')
        report={'ok':False,'errors':[{'stage':'wait','index':0,'type':'TimeoutExpired'}],
                'allChildrenReaped':False,'serverStopped':True,'unreapedWorkerIndexes':[0]}
        failure=m.CleanupFailure(report)
        self.assertEqual(failure.cleanup,report)

    def test_real_sigint_is_recorded_at_cleanup_safe_point(self):
        m=fixtures.load();self.assertTrue(hasattr(m,'run_signals'),'Missing run-scoped signal ownership')
        with m.run_signals():
            stop=threading.Event();gate=threading.Event()
            thread=threading.Thread(target=lambda:(gate.wait(2),stop.wait(2)));thread.start()
            child=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(10)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            original=child.communicate
            def drain(**kwargs):
                os.kill(os.getpid(),signal.SIGINT);os.kill(os.getpid(),signal.SIGALRM)
                return original(**kwargs)
            with patch.object(child,'communicate',side_effect=drain):
                result=m.cleanup_owned([child],thread,stop,gate)
            self.assertTrue(result['allChildrenReaped']);self.assertTrue(result['serverStopped'])
            self.assertFalse(result['ok']);self.assertIn(signal.SIGINT,result['interruptedSignals'])
            self.assertIn(signal.SIGALRM,result['interruptedSignals'])

    def test_partial_ready_line_has_local_deadline(self):
        m=fixtures.load();self.assertTrue(hasattr(m,'wait_ready'),'Missing bounded READY reader')
        with m.run_signals():
            child=subprocess.Popen([sys.executable,'-I','-B','-c',"import sys,time;sys.stdout.write('REA');sys.stdout.flush();time.sleep(10)"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                started=time.monotonic()
                with self.assertRaises(TimeoutError):m.wait_ready([child],time.monotonic()+.15)
                self.assertLess(time.monotonic()-started,1)
            finally:
                child.kill();child.communicate(timeout=2)


if __name__=='__main__':unittest.main()
