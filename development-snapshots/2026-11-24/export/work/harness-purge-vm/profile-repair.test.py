import contextlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('profile_repair_manager',Path(__file__).with_name('manage.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ProfileRepair(unittest.TestCase):
 def api(self):
  self.assertTrue(callable(getattr(m,'repair_profile',None)),'Explicit profile maintenance is missing')
  return m.repair_profile

 def test_preview_uses_fixed_profile_and_no_utm_lifecycle(self):
  api=self.api();receipt={'ok':True,'profile':'web','changed':False,'wrote':False,'dryRun':True,'beforeSha256':None,'afterSha256':None}
  with patch.object(m,'validate'),patch.object(m,'vm_operation',return_value=contextlib.nullcontext()) as lock,patch.object(m,'vm_status',side_effect=RuntimeError('UTM unavailable')),patch.object(m,'ssh',return_value=SimpleNamespace(stdout=json.dumps(receipt))) as ssh:
   self.assertEqual(api(),receipt);lock.assert_called_once_with('switch')
   self.assertEqual(ssh.call_args.args[0],'/home/purge/.local/node/bin/node --input-type=module')
   self.assertIn('/home/purge/.dsh-improved/profiles/web',ssh.call_args.kwargs['input']);self.assertIn('"apply":false',ssh.call_args.kwargs['input'])

 def test_apply_rejects_boolean_and_receipt_contradictions(self):
  api=self.api()
  with self.assertRaises(ValueError):api(apply=1)
  bad={'ok':True,'profile':'web','changed':True,'wrote':True,'dryRun':True,'beforeSha256':'a'*64,'afterSha256':'b'*64}
  with patch.object(m,'validate'),patch.object(m,'vm_operation',return_value=contextlib.nullcontext()),patch.object(m,'ssh',return_value=SimpleNamespace(stdout=json.dumps(bad))):
   with self.assertRaises(RuntimeError):api(apply=True)

if __name__=='__main__':unittest.main()
