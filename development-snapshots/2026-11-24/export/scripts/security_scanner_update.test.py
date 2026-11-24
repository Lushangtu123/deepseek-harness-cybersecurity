from pathlib import Path
import importlib.util,json,subprocess,unittest
from unittest.mock import Mock
SCRIPT=Path(__file__).with_name('security_scanner_update.py')
class HostUpdateTests(unittest.TestCase):
 def module(self):
  self.assertTrue(SCRIPT.is_file(),'Mac scanner admission entry missing');s=importlib.util.spec_from_file_location('host_scanner',SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_invalid_candidate_is_rejected_before_loading_manager(self):
  m=self.module();manager=Mock()
  with self.assertRaises(ValueError):m.run_candidate(image_id='semgrep:latest',version='1.0.0',manager=manager)
  manager.ssh.assert_not_called();manager.start.assert_not_called()
 def test_read_only_check_keeps_rejected_gate_status_and_does_not_restart(self):
  m=self.module();manager=Mock();manager.ssh.side_effect=subprocess.CalledProcessError(2,['ssh'],output=json.dumps({'admitted':False,'changed':False,'parser':{'parserReady':False}}),stderr='')
  result,code=m.run_candidate(image_id='sha256:'+'a'*64,version='1.0.0',manager=manager)
  self.assertEqual(code,2);self.assertFalse(result['admitted']);manager.start.assert_not_called();manager.vm_operation.assert_not_called();self.assertIn('--image-id',manager.ssh.call_args.args[0]);self.assertNotIn('--apply',manager.ssh.call_args.args[0])
 def test_unverified_apply_never_contacts_the_vm(self):
  m=self.module();manager=Mock()
  with self.assertRaisesRegex(ValueError,'发布者'):
   m.run_candidate(image_id='sha256:'+'a'*64,version='1.2.3',expected_manifest='b'*64,apply=True,confirm=True,manager=manager)
  manager.ssh.assert_not_called();manager.vm_operation.assert_not_called();manager.start.assert_not_called()
if __name__=='__main__':unittest.main()
