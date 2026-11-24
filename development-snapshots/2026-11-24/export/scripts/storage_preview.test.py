from pathlib import Path
import contextlib,importlib.util,json,unittest
from types import SimpleNamespace
from unittest.mock import Mock
SCRIPT=Path(__file__).with_name('storage_preview.py')
class HostStorageTests(unittest.TestCase):
 def module(self):
  self.assertTrue(SCRIPT.is_file(),'Combined storage preview entry missing');s=importlib.util.spec_from_file_location('storage_host',SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_stopped_vm_stays_stopped_and_partial_recovery_inventory_stays_partial(self):
  m=self.module();manager=SimpleNamespace(validate=Mock(),vm_status=Mock(return_value='stopped'),start=Mock(),ssh=Mock(),recovery_catalog=Mock(return_value={'readOnly':True,'currentRecovery':'ready-current','storage':{'freeBytes':10,'totalBytes':100},'snapshots':[{'name':'ready-current','current':True,'protected':True,'reviewCandidate':False}],'images':[],'nextCursor':'continuation','nextSnapshotCursor':None,'truncated':True}))
  report=m.collect(manager=manager);manager.start.assert_not_called();manager.ssh.assert_not_called();self.assertEqual(report['guest']['state'],'not-running');self.assertFalse(report['catalogComplete']);self.assertEqual(report['recoveryPreview'][0]['action'],'retain');self.assertIsNone(report['recoveryPreview'][0]['reclaimableBytes']);self.assertFalse(report['deletionAvailable'])
 def test_guest_failure_stays_unknown_and_no_mutation_method_is_called(self):
  import subprocess
  m=self.module();manager=SimpleNamespace(validate=Mock(),vm_status=Mock(return_value='started'),start=Mock(),ssh=Mock(side_effect=subprocess.TimeoutExpired('readonly-ssh',45)),recovery_catalog=Mock(side_effect=ValueError('unavailable')))
  result=m.collect(manager=manager);self.assertEqual(result['guest']['state'],'unavailable');self.assertEqual(result['hostFilesystem']['state'],'unknown');self.assertFalse(result['catalogComplete']);self.assertEqual(result['recoveryPreview'],[]);manager.start.assert_not_called()
 def test_host_capacity_works_when_scripts_are_moved_without_repository_package(self):
  import shutil,subprocess,sys,tempfile
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   for name in ['storage_preview.py','security_db_update.py','security_db_transaction.py']:shutil.copyfile(SCRIPT.parent/name,root/name)
   r=subprocess.run([sys.executable,'-B','-c',"import storage_preview;assert storage_preview.capacity(100*1024**3,20*1024**3)['state']=='healthy'"],cwd=root,capture_output=True,text=True,timeout=5);self.assertEqual(r.returncode,0,r.stderr)
if __name__=='__main__':unittest.main()
