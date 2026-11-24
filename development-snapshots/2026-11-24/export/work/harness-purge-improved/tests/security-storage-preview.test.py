from pathlib import Path
import importlib.util,os,tempfile,unittest
from unittest.mock import patch
SCRIPT=Path(__file__).resolve().parent.parent/'package/scripts/security-storage-preview.py'
class StorageTests(unittest.TestCase):
 def test_capacity_only_probe_never_walks_directories_or_invokes_docker(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as folder,patch.object(m,'measure',side_effect=AssertionError('No directory scan')),patch.object(m,'children',side_effect=AssertionError('No candidates')),patch.object(m,'docker_summary',side_effect=AssertionError('No Docker')):
   result=m.preview(Path(folder).resolve(),capacity_only=True)
  self.assertEqual(result['version'],1);self.assertTrue(result['readOnly']);self.assertFalse(result['deletionAvailable']);self.assertFalse(result['automaticChanges'])
  self.assertGreater(result['filesystem']['totalBytes'],0)
  self.assertNotIn('objects',result);self.assertNotIn('reviewDirectories',result);self.assertNotIn('docker',result)
 def module(self):
  self.assertTrue(SCRIPT.is_file(),'VM storage monitor missing');s=importlib.util.spec_from_file_location('storage_monitor',SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_capacity_thresholds_report_critical_warning_and_healthy_with_units(self):
  m=self.module();g=1024**3
  for total,available,state in [(100*g,4*g,'critical'),(100*g,9*g,'warning'),(100*g,14*g,'warning'),(100*g,20*g,'healthy')]:self.assertEqual(m.capacity(total,available)['state'],state)
  self.assertEqual(m.capacity(100*g,80*g,inode_total=1000,inode_available=30)['state'],'critical')
  for total,available in [(0,0),(100,-1),(100,101),(True,1)]:
   with self.assertRaises(ValueError):m.capacity(total,available)
 def test_metadata_walk_is_bounded_deduplicates_hardlinks_and_never_follows_links(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();folder=root/'tree';folder.mkdir();f=folder/'one';f.write_bytes(b'x'*4096);os.link(f,folder/'two');(folder/'outside').symlink_to(root);os.mkfifo(folder/'fifo');before=f.read_bytes();result=m.measure(folder)
   self.assertTrue(result['complete']);self.assertEqual(result['fileCount'],1);self.assertEqual(result['apparentBytes'],4096);self.assertEqual(result['linksSkipped'],1);self.assertEqual(f.read_bytes(),before)
   limited=m.measure(folder,max_entries=1);self.assertFalse(limited['complete']);self.assertIn('entry-limit',limited['reasons'])
   self.assertEqual(m.measure(root/'missing')['state'],'missing');self.assertIsNone(m.measure(root/'missing')['allocatedBytes']);self.assertEqual(m.measure(folder/'outside')['state'],'unavailable')
 def test_preview_retains_projects_private_accounts_and_backups_and_has_no_deletion_mode(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'workspace').mkdir();(root/'workspace/private.txt').write_text('PRIVATE_BODY_MUST_NOT_APPEAR');(root/'.dsh-improved/security-auth').mkdir(parents=True);(root/'.dsh-improved/security-auth/token.json').write_text('PRIVATE_AUTH_MUST_NOT_APPEAR');(root/'downloads').mkdir();(root/'downloads/unknown-user-folder').mkdir();(root/'downloads/unknown-user-folder/user.txt').write_text('keep')
   report=m.preview(root,docker=False);serialized=str(report);self.assertNotIn('PRIVATE_BODY_MUST_NOT_APPEAR',serialized);self.assertNotIn('PRIVATE_AUTH_MUST_NOT_APPEAR',serialized);self.assertNotIn('token.json',serialized);self.assertTrue(report['readOnly']);self.assertFalse(report['automaticChanges']);self.assertTrue(all(row['action']=='retain' for row in report['objects']));self.assertTrue((root/'downloads/unknown-user-folder/user.txt').exists())
 def test_download_preview_names_only_bounded_candidates_and_never_marks_them_approved(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();folder=root/'downloads';folder.mkdir();(folder/'owned-check-20261101').mkdir();(folder/'owned-check-20261101/data').write_bytes(b'x'*20);(folder/'private-token-cache').mkdir();(folder/'linked').symlink_to(root)
   rows=m.children(folder);self.assertEqual(len(rows['items']),1);row=rows['items'][0];self.assertEqual(row['action'],'review');self.assertFalse(row['deletionApproved']);self.assertEqual(row['usage']['apparentBytes'],20)
 def test_cli_rejects_delete_apply_and_arbitrary_paths_before_any_operation(self):
  import subprocess,sys
  for args in [['--apply'],['--delete'],['--root','/private/user-data']]:
   result=subprocess.run([sys.executable,'-B',str(SCRIPT),*args],capture_output=True,text=True,timeout=5);self.assertEqual(result.returncode,2)
 def test_expired_budget_and_changed_root_never_claim_complete_usage(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'data').write_bytes(b'x');r=m.measure(root,seconds=-1);self.assertFalse(r['complete']);self.assertIn('time-limit',r['reasons'])
 def test_ancestor_symlink_swap_cannot_return_outside_usage_as_complete(self):
  from unittest.mock import patch
  m=self.module()
  for operation in ['measure','children']:
   with self.subTest(operation=operation),tempfile.TemporaryDirectory() as d:
    root=Path(d).resolve();scope=root/'scope';tree=scope/'tree';tree.mkdir(parents=True);(tree/'item').mkdir();(tree/'item/a').write_bytes(b'x'*3);outside=root/'outside';(outside/'tree/item').mkdir(parents=True);(outside/'tree/item/b').write_bytes(b'y'*123);original=m.os.open;fired=[]
    def raced(path,flags,*args,**kwargs):
     if not fired and str(path) in [str(tree),'tree']:
      scope.rename(root/'old-scope');scope.symlink_to(outside,target_is_directory=True);fired.append(True)
     return original(path,flags,*args,**kwargs)
    with patch.object(m.os,'open',side_effect=raced):result=getattr(m,operation)(tree)
    self.assertTrue(fired,'Fault must fire');self.assertFalse(result['complete'])
    if operation=='measure':self.assertNotEqual(result.get('apparentBytes'),123)
if __name__=='__main__':unittest.main()
