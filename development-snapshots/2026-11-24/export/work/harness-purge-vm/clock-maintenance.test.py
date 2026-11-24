import importlib.util,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
s=importlib.util.spec_from_file_location('clock_maintenance_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Maintenance(unittest.TestCase):
 def test_stopped_vm_is_not_started_or_contacted(self):
  self.assertTrue(callable(getattr(m,'maintain_clock',None)),'background clock maintenance missing')
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',side_effect=AssertionError('Background maintenance must not invoke UTM IPC')),patch.object(m,'guest_ssh_listening',return_value=False,create=True),patch.object(m,'synchronize_clock') as sync:
   self.assertEqual(m.maintain_clock(),{'state':'skipped','reason':'not-listening'});sync.assert_not_called()
 def test_running_vm_reuses_verified_calibration(self):
  self.assertTrue(callable(getattr(m,'maintain_clock',None)))
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',side_effect=AssertionError('Background maintenance must not invoke UTM IPC')),patch.object(m,'guest_ssh_listening',return_value=True,create=True),patch.object(m,'synchronize_clock',return_value={'adjusted':True,'offsetSeconds':.2}) as sync:
   self.assertEqual(m.maintain_clock(),{'state':'adjusted','adjusted':True,'offsetSeconds':.2});sync.assert_called_once()
 def test_listener_discovery_is_fixed_to_our_loopback_port_and_uid(self):
  with patch.object(m,'command',return_value=MagicMock(stdout='p123\nf21\n')) as command:
   self.assertTrue(m.guest_ssh_listening());args=command.call_args.args[0];self.assertEqual(args,['/usr/sbin/lsof','-nP','-a','-u',str(m.os.getuid()),'-iTCP@127.0.0.1:49223','-sTCP:LISTEN','-Fp'])
 def test_no_listener_is_a_skip_but_unexpected_probe_failure_is_not_a_false_success(self):
  with patch.object(m,'command',side_effect=subprocess.CalledProcessError(1,['lsof'])):self.assertFalse(m.guest_ssh_listening())
  with patch.object(m,'command',side_effect=subprocess.CalledProcessError(2,['lsof'])):
   with self.assertRaises(subprocess.CalledProcessError):m.guest_ssh_listening()
if __name__=='__main__':unittest.main()
