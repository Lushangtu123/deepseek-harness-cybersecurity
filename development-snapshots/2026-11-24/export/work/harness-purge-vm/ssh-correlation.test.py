"""A separate bounded observation never replays an uncertain SSH command."""
import importlib.util,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

spec=importlib.util.spec_from_file_location('ssh_correlation_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
REF='3d281c69-bbe4-4fa8-a922-3dce229d7caa'
MARKERS=['maxStartups','drop','penalty','forkFailure','outOfMemory','acceptedKey','preAuthClosed']
def server():return{'serviceState':'active','bootId':'8c61c2ce-f056-49b1-9bf0-74b51d6e9fd5','guestObservedAtUnix':time.time(),'guestBootStartedAtUnix':time.time()-3600,'journal':{'state':'read','rows':2,'truncated':False,'markers':{key:int(key=='acceptedKey') for key in MARKERS}}}

class SSHCorrelation(unittest.TestCase):
 def test_current_clock_skew_leaves_historical_correlation_unknown(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({**server(),'guestObservedAtUnix':time.time()-1000}))):
   self.save_failure();value=m.correlate_ssh_failure(REF);self.assertEqual(value.get('correlationState'),'clock-unconfirmed');self.assertIsNone(value['failureWindowWithinCurrentBoot']);self.assertIsNone(value['server']['journal']['markers'])
 def test_capture_timeout_and_oversize_kill_a_descendant_that_keeps_the_pipe_open(self):
  method=getattr(m,'capture_ssh_journal',None);self.assertTrue(callable(method),'Missing process-group journal supervisor')
  real_popen=subprocess.Popen
  for oversized in [False,True]:
   with self.subTest(oversized=oversized),tempfile.TemporaryDirectory() as temp:
    marker=Path(temp)/'child.pid';launched=[]
    code="import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);Path("+repr(str(marker))+").write_text(str(p.pid));"+("sys.stdout.write('A'*300000);sys.stdout.flush();" if oversized else '')+"time.sleep(30)"
    def launch(argv,**kwargs):
     self.assertEqual(argv[0],'/usr/bin/journalctl');self.assertTrue(kwargs.get('start_new_session'));process=real_popen([sys.executable,'-c',code],**kwargs);launched.append(process);return process
    try:
     start=time.monotonic()
     with patch.object(subprocess,'Popen',side_effect=launch):value=method(time.time()-2,time.time())
     self.assertLess(time.monotonic()-start,5);self.assertEqual(value['state'],'unavailable');self.assertTrue(marker.is_file());child=int(marker.read_text());status=subprocess.run(['ps','-p',str(child),'-o','stat='],capture_output=True,text=True,timeout=2).stdout.strip();self.assertTrue(not status or status.startswith('Z'),'Descendant survived journal capture cleanup')
    finally:
     for process in launched:
      try:os.killpg(process.pid,signal.SIGKILL)
      except ProcessLookupError:pass
      process.wait(timeout=2)
 def test_cli_forwards_only_an_explicit_saved_failure_reference(self):
  with patch.object(m.sys,'argv',['manage.py','ssh-correlate','--reference',REF]),patch.object(m,'correlate_ssh_failure',return_value={'reference':REF}) as sample,patch('builtins.print'):
   m.main();sample.assert_called_once_with(REF)
 def save_failure(self):
  trace={'id':REF,'phase':'native-check','remoteException':None,'remoteLine':None}
  self.assertTrue(m.record_ssh_failure('connection-reset',255,.2,trace))
 def test_reported_transport_stage_is_bounded_and_preserves_legacy_trace(self):
  for raw,expected in [('kex_exchange_identification: read: Connection reset by peer PRIVATE','identification'),('ssh: connect to host 127.0.0.1 port 49223: Connection refused','connect'),('Permission denied (publickey).','authentication'),('PRIVATE','unknown')]:
   with self.subTest(expected=expected),tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=subprocess.CalledProcessError(255,['ssh','PRIVATE'],stderr=raw)):
    with self.assertRaises(subprocess.CalledProcessError) as caught:m.ssh('PRIVATE',phase='native-check')
    self.assertEqual(caught.exception.trace.get('transportStage'),expected);self.assertNotIn('PRIVATE',json.dumps(m.ssh_diagnostics()))
 def test_separate_probe_is_bound_to_saved_reference_and_retains_only_safe_summary(self):
  method=getattr(m,'correlate_ssh_failure',None);self.assertTrue(callable(method),'Missing bounded SSH correlation sampler')
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps(server()))) as ssh:
   self.save_failure();before=(Path(temp)/'ssh-diagnostics.json').read_bytes();value=method(REF)
   self.assertEqual(value['reference'],REF);self.assertEqual(value['probeState'],'read');self.assertFalse(value['exactConnectionIdentified']);self.assertTrue(value['recorded']);self.assertEqual(ssh.call_count,1);self.assertEqual(ssh.call_args.args,('sudo -n /usr/bin/python3 -',));self.assertEqual(ssh.call_args.kwargs['phase'],'diagnostic-sample');self.assertLessEqual(ssh.call_args.kwargs['timeout'],15)
   path=Path(temp)/'ssh-correlation.json';self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertEqual((Path(temp)/'ssh-diagnostics.json').read_bytes(),before);self.assertNotIn('PRIVATE',path.read_text());self.assertEqual(value['server']['journal']['markers']['acceptedKey'],1)
 def test_invalid_or_missing_reference_never_probes_or_changes_evidence(self):
  method=getattr(m,'correlate_ssh_failure',None);self.assertTrue(callable(method),'Missing sampler')
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'ssh') as ssh,patch.object(m,'vm_status') as state:
   self.save_failure()
   for value in ['PRIVATE','00000000-0000-0000-0000-000000000000']:
    with self.assertRaises(ValueError):method(value)
   ssh.assert_not_called();state.assert_not_called();self.assertFalse((Path(temp)/'ssh-correlation.json').exists())
 def test_stopped_vm_or_failed_probe_never_claims_empty_journal_or_retries(self):
  method=getattr(m,'correlate_ssh_failure',None);self.assertTrue(callable(method),'Missing sampler')
  for vm in ['stopped','started']:
   with self.subTest(vm=vm),tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',return_value=vm),patch.object(m,'ssh',side_effect=RuntimeError('PRIVATE')) as ssh:
    self.save_failure();value=method(REF);self.assertEqual(value['probeState'],'not-running' if vm=='stopped' else 'unavailable');self.assertIsNone(value['server']);self.assertEqual(ssh.call_count,int(vm=='started'));self.assertNotIn('PRIVATE',json.dumps(value));self.assertTrue(value['recorded'])
 def test_malformed_probe_and_linked_sample_file_preserve_the_original(self):
  method=getattr(m,'correlate_ssh_failure',None);self.assertTrue(callable(method),'Missing sampler')
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({**server(),'secret':'PRIVATE'}))):
   self.save_failure();other=Path(temp)/'untouched';other.write_text('sentinel');(Path(temp)/'ssh-correlation.json').symlink_to(other);value=method(REF);self.assertEqual(value['probeState'],'unavailable');self.assertIsNone(value['server']);self.assertFalse(value['recorded']);self.assertEqual(other.read_text(),'sentinel');self.assertNotIn('PRIVATE',json.dumps(value));self.assertEqual(m.ssh_diagnostics()[0]['trace']['id'],REF)
 def test_journal_summary_bounds_rows_and_never_copies_raw_messages(self):
  method=getattr(m,'summarize_ssh_journal',None);self.assertTrue(callable(method),'Missing bounded journal summary')
  raw='\n'.join(json.dumps({'MESSAGE':'Accepted publickey PRIVATE'}) for _ in range(201));value=method(raw);self.assertEqual(value['state'],'read');self.assertEqual(value['rows'],200);self.assertTrue(value['truncated']);self.assertEqual(value['markers']['acceptedKey'],200);self.assertNotIn('PRIVATE',json.dumps(value))
  for raw in ['PRIVATE',json.dumps({'MESSAGE':['PRIVATE']}),'x'*262145]:
   value=method(raw);self.assertEqual(value['state'],'unavailable');self.assertIsNone(value['markers']);self.assertIsNone(value['rows'])

if __name__=='__main__':unittest.main()
