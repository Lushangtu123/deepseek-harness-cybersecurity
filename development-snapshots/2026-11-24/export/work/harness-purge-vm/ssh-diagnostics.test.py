"""Connection failures stay diagnosable without retaining remote commands/data."""
import fcntl,importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
spec=importlib.util.spec_from_file_location('ssh_diagnostic_manager',Path(__file__).with_name('manage.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SSHDiagnostics(unittest.TestCase):
 def setUp(self):
  folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);root=patch.object(m,'ROOT',Path(folder.name));root.start();self.addCleanup(root.stop)
 def failure(self,stderr='ssh: connect to host 127.0.0.1 port 49223: Connection refused\n',code=255):
  return subprocess.CalledProcessError(code,['ssh','secret-command'],output='private output',stderr=stderr)
 def test_transport_reason_is_retained_without_command_or_output_and_no_retry(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=self.failure()) as command:
   with self.assertRaises(subprocess.CalledProcessError) as caught:m.ssh('echo secret-command')
   self.assertEqual(command.call_count,1)
   self.assertIn('Connection refused',str(caught.exception))
   self.assertNotIn('secret-command',str(caught.exception))
   rows=m.ssh_diagnostics();self.assertEqual(rows[-1]['exitCode'],255)
   self.assertEqual(rows[-1]['reason'],'connection-refused')
   self.assertNotIn('private output',json.dumps(rows))
   self.assertEqual((Path(temp)/'ssh-diagnostics.json').stat().st_mode&0o777,0o600)
 def test_remote_stderr_is_not_persisted_or_displayed(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=self.failure('password=PRIVATE sentinel private output\n',7)):
   with self.assertRaises(subprocess.CalledProcessError) as caught:m.ssh('secret-command')
   self.assertNotIn('PRIVATE',str(caught.exception));self.assertNotIn('secret-command',str(caught.exception))
   rows=m.ssh_diagnostics();self.assertEqual(rows[-1]['reason'],'remote-or-unknown-error');self.assertNotIn('PRIVATE',json.dumps(rows))
 def test_correlated_phase_and_reported_python_frame_survive_without_source_or_message(self):
  stderr='Traceback (most recent call last):\n  File "<stdin>", line 23, in <module>\n    private_source(password="PRIVATE")\nAssertionError: password=PRIVATE\n'
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=self.failure(stderr,1)) as command:
   with self.assertRaises(subprocess.CalledProcessError) as caught:m.ssh('secret-command',input='private-input',phase='native-check')
   trace=caught.exception.trace;self.assertEqual(trace['phase'],'native-check');self.assertEqual(trace['remoteException'],'AssertionError');self.assertEqual(trace['remoteLine'],23);self.assertRegex(trace['id'],r'^[a-f0-9-]{36}$');self.assertEqual(m.ssh_diagnostics()[-1]['trace'],trace);self.assertEqual(command.call_count,1)
   for value in [str(caught.exception),json.dumps(m.ssh_diagnostics())]:self.assertNotIn('PRIVATE',value);self.assertNotIn('private_source',value);self.assertNotIn('secret-command',value);self.assertNotIn('private-input',value);self.assertIn(trace['id'],value)
 def test_unrecognized_diagnostic_phase_is_rejected_before_execution(self):
  with patch.object(m,'command') as command:
   with self.assertRaises(ValueError):m.ssh('secret-command',phase='password=PRIVATE')
   command.assert_not_called()
 def test_legacy_rows_and_new_traces_coexist_and_unknown_exception_text_is_not_retained(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)):
   self.assertTrue(m.record_ssh_failure('connection-refused',255,.1))
   with patch.object(m,'command',side_effect=self.failure('Traceback (most recent call last):\n  File "<stdin>", line 99999999, in private\nPrivatePasswordError: PRIVATE\n',2)):
    with self.assertRaises(subprocess.CalledProcessError):m.ssh('secret-command',phase='recovery-proof')
   rows=m.ssh_diagnostics();self.assertEqual(len(rows),2);self.assertNotIn('trace',rows[0]);self.assertEqual(rows[1]['trace']['remoteException'],None);self.assertEqual(rows[1]['trace']['remoteLine'],None);self.assertNotIn('PRIVATE',json.dumps(rows))
 def test_timeout_has_a_correlated_phase_even_when_diagnostic_storage_is_unavailable(self):
  with patch.object(m,'record_ssh_failure',return_value=False),patch.object(m,'command',side_effect=subprocess.TimeoutExpired(['ssh','secret-command'],5)):
   with self.assertRaises(subprocess.TimeoutExpired) as caught:m.ssh('secret-command',phase='clock-read')
   self.assertEqual(caught.exception.trace['phase'],'clock-read');self.assertFalse(caught.exception.diagnosticRecorded);self.assertIn(caught.exception.trace['id'],str(caught.exception));self.assertNotIn('secret-command',str(caught.exception))
 def test_spoofed_prefix_cannot_append_private_data(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=self.failure('ssh: Connection refused password=PRIVATE\n')):
   with self.assertRaises(subprocess.CalledProcessError) as caught:m.ssh('secret-command')
   self.assertNotIn('PRIVATE',str(caught.exception));self.assertNotIn('PRIVATE',json.dumps(m.ssh_diagnostics()))
 def test_timeout_is_recorded_and_not_retried(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=subprocess.TimeoutExpired(['ssh','secret-command'],5,stderr=b'PRIVATE')) as command:
   with self.assertRaises(subprocess.TimeoutExpired) as caught:m.ssh('secret-command',timeout=5)
   self.assertEqual(command.call_count,1);self.assertNotIn('secret-command',str(caught.exception))
   self.assertEqual(m.ssh_diagnostics()[-1]['reason'],'timeout');self.assertNotIn('PRIVATE',json.dumps(m.ssh_diagnostics()))
 def test_symlink_log_is_not_followed_and_original_failure_survives(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);other=root/'untouched';other.write_text('sentinel');(root/'ssh-diagnostics.json').symlink_to(other)
   with patch.object(m,'ROOT',root),patch.object(m,'command',side_effect=self.failure()):
    with self.assertRaises(subprocess.CalledProcessError) as caught:m.ssh('secret-command')
   self.assertEqual(other.read_text(),'sentinel');self.assertIn('Connection refused',str(caught.exception))
 def test_retention_is_bounded(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=self.failure()):
   for _ in range(55):
    with self.assertRaises(subprocess.CalledProcessError):m.ssh('secret-command')
   self.assertEqual(len(m.ssh_diagnostics()),50)
 def test_invalid_prior_diagnostics_never_mask_the_ssh_failure(self):
  for contents in [json.dumps([{'observedAtUnix':10**400,'elapsedMs':1,'exitCode':255,'reason':'connection-refused','detail':'Connection refused'}]),'['*1200+'0'+']'*1200]:
   with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=self.failure()):
    path=Path(temp)/'ssh-diagnostics.json';path.write_text(contents);path.chmod(0o600)
    with self.assertRaises(subprocess.CalledProcessError) as caught:m.ssh('secret-command')
    self.assertFalse(caught.exception.diagnosticRecorded)
 def test_busy_logger_does_not_block_the_ssh_failure(self):
  with tempfile.TemporaryDirectory() as temp:
   lock=os.open(Path(temp)/'.ssh-diagnostics.lock',os.O_RDWR|os.O_CREAT,0o600)
   try:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    code="""import importlib.util,subprocess,sys
from pathlib import Path
from unittest.mock import patch
s=importlib.util.spec_from_file_location('child_manager',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT=Path(sys.argv[2])
with patch.object(m,'command',side_effect=subprocess.CalledProcessError(255,['ssh','private'],stderr='Connection refused')):
 try:m.ssh('private')
 except subprocess.CalledProcessError as e:assert e.diagnosticRecorded is False
 else:raise AssertionError('Failure was lost')
"""
    try:r=subprocess.run([sys.executable,'-B','-c',code,m.__file__,temp],capture_output=True,text=True,timeout=2)
    except subprocess.TimeoutExpired:self.fail('Diagnostic lock blocked delivery of the SSH failure')
    else:self.assertEqual(r.returncode,0,r.stderr)
   finally:os.close(lock)
 def test_explicit_clock_cli_reuses_existing_calibration_and_validates_identity(self):
  with patch.object(m.sys,'argv',['manage.py','clock-sync']),patch.object(m,'validate') as validate,patch.object(m,'synchronize_clock',return_value={'adjusted':True,'offsetSeconds':0.1}) as sync,patch('builtins.print'):
   m.main();validate.assert_called_once();sync.assert_called_once()

if __name__=='__main__':unittest.main()
