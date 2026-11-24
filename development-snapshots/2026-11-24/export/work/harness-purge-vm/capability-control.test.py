import contextlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('capability_manager',Path(__file__).with_name('manage.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class CapabilityControl(unittest.TestCase):
 def test_only_fixed_actions_can_be_dispatched(self):
  self.assertTrue(callable(getattr(m,'original_capabilities',None)),'Managed capability API missing')
  with self.assertRaises(ValueError):m.original_capabilities('arbitrary-command')

 def test_write_reuses_operation_lock_and_qualifies_current_runtime(self):
  self.assertTrue(callable(getattr(m,'original_capabilities',None)),'Managed capability API missing')
  result={'enabled':True,'configured':True,'changed':True}
  self.assertTrue(callable(getattr(m,'refresh_capability_access',None)),'Service-only access refresh missing')
  with patch.object(m,'validate'),patch.object(m,'vm_status',side_effect=RuntimeError('UTM unavailable')),patch.object(m,'vm_operation',return_value=contextlib.nullcontext()) as lock,patch.object(m,'ssh',return_value=SimpleNamespace(stdout=json.dumps(result))) as ssh,patch.object(m,'refresh_capability_access') as refresh:
   self.assertEqual(m.original_capabilities('enable'),result)
   lock.assert_called_once_with('switch');refresh.assert_called_once_with()
   self.assertEqual(ssh.call_args.args[0],'python3 - enable')
   self.assertIn('authenticated_plugin_ready',ssh.call_args.kwargs['input'])

 def test_contradictory_receipt_is_not_success(self):
  self.assertTrue(callable(getattr(m,'original_capabilities',None)),'Managed capability API missing')
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m,'vm_operation',return_value=contextlib.nullcontext()),patch.object(m,'ssh',return_value=SimpleNamespace(stdout='{"enabled":true,"configured":false}')),patch.object(m,'start') as start:
   with self.assertRaises(RuntimeError):m.original_capabilities('enable')
   start.assert_not_called()

if __name__=='__main__':unittest.main()
