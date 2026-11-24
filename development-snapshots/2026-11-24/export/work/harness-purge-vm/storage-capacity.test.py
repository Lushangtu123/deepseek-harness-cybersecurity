import importlib.util,json,subprocess,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
s=importlib.util.spec_from_file_location('storage_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class CapacityTests(unittest.TestCase):
 def test_stopped_vm_reports_host_counts_without_start_scan_or_ssh(self):
  method=getattr(m,'storage_capacity',None);self.assertTrue(callable(method),'Lightweight capacity command missing')
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m.shutil,'disk_usage',return_value=MagicMock(total=100,free=20)),patch.object(m,'ssh',side_effect=AssertionError('No SSH')),patch.object(m,'start',side_effect=AssertionError('No VM start')),patch.object(m,'recovery_catalog',side_effect=AssertionError('No disk inventory')):
   result=method()
  self.assertTrue(result['readOnly']);self.assertFalse(result['deletionAvailable']);self.assertEqual(result['hostFilesystem'],{'totalBytes':100,'availableBytes':20});self.assertEqual(result['guest']['state'],'not-running')
 def test_running_probe_is_fixed_bounded_and_never_returns_private_extra_fields(self):
  method=getattr(m,'storage_capacity',None);self.assertTrue(callable(method))
  value={'version':1,'readOnly':True,'automaticChanges':False,'deletionAvailable':False,'filesystem':{'state':'warning','totalBytes':100,'availableBytes':9,'inodeTotal':1000,'inodeAvailable':800},'secret':'must-not-reach-http'}
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m.shutil,'disk_usage',return_value=MagicMock(total=200,free=30)),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps(value))) as ssh:
   result=method()
  self.assertEqual(ssh.call_args.args,('python3 -B /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-storage-preview.py --capacity-only',));self.assertLessEqual(ssh.call_args.kwargs['timeout'],8)
  self.assertEqual(result['guest']['filesystem']['inodeAvailable'],800);self.assertNotIn('secret',json.dumps(result));self.assertEqual(result['guest']['state'],'observed')
 def test_failed_vm_probe_is_unknown_and_never_uses_zero_capacity(self):
  method=getattr(m,'storage_capacity',None);self.assertTrue(callable(method))
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m.shutil,'disk_usage',side_effect=OSError('private path')),patch.object(m,'ssh',side_effect=subprocess.TimeoutExpired('private command',8)):
   result=method()
  self.assertIsNone(result['hostFilesystem']);self.assertEqual(result['guest'],{'state':'unavailable'});self.assertNotIn('private',json.dumps(result))
if __name__=='__main__':unittest.main()
