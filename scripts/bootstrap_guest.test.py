from pathlib import Path
import importlib.util,io,json,os,subprocess,sys,tarfile,tempfile,unittest

SCRIPT=Path(__file__).with_name('bootstrap_guest.py')
spec=importlib.util.spec_from_file_location('bootstrap',SCRIPT)
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)

class BootstrapTests(unittest.TestCase):
 def test_default_is_a_read_only_plan_with_explicit_scope(self):
  with tempfile.TemporaryDirectory() as folder:
   home=Path(folder)
   result=subprocess.run([sys.executable,'-B',str(SCRIPT)],env={**os.environ,'HOME':folder},capture_output=True,text=True,timeout=10)
   self.assertEqual(result.returncode,0,result.stderr)
   value=json.loads(result.stdout)
   self.assertTrue(value['readOnly']);self.assertFalse(value['automaticChanges']);self.assertEqual(value['programFiles'],151)
   self.assertEqual(value['scope'],'basic-harness-plugin-web');self.assertFalse(value['copiesCredentials']);self.assertFalse(value['installsProfessionalTools'])
   self.assertEqual(list(home.iterdir()),[])

 def test_apply_refuses_a_foreign_home_before_creating_any_installation(self):
  with tempfile.TemporaryDirectory() as folder:
   result=subprocess.run([sys.executable,'-B',str(SCRIPT),'--apply'],env={**os.environ,'HOME':folder},capture_output=True,text=True,timeout=10)
   self.assertEqual(result.returncode,1,result.stderr)
   value=json.loads(result.stdout)
   self.assertFalse(value['ok']);self.assertFalse(value['automaticChanges']);self.assertEqual(value['error'],'Dedicated empty VM required')
   self.assertEqual(list(Path(folder).iterdir()),[])

 def test_download_integrity_is_checked_before_extracting(self):
  with tempfile.TemporaryDirectory() as folder:
   archive=Path(folder)/'node.tar.xz';archive.write_bytes(b'changed archive')
   with self.assertRaises(ValueError):bootstrap.check_digest(archive,'sha256','0'*64)
   self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),['node.tar.xz'])

 def test_node_archive_cannot_escape_install_stage(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);archive=root/'bad.tar.xz'
   with tarfile.open(archive,'w:xz') as output:
    entry=tarfile.TarInfo('../outside');entry.size=1;output.addfile(entry,io.BytesIO(b'x'))
   destination=root/'stage';destination.mkdir()
   with self.assertRaises(ValueError):bootstrap.extract_node(archive,destination)
   self.assertFalse((root/'outside').exists());self.assertEqual(list(destination.iterdir()),[])

 def test_fresh_target_refuses_existing_service_or_account_state(self):
  for name in ['.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket','.dsh/credentials','.npmrc','workspace/existing-project/README.md']:
   with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
    home=Path(folder);path=home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('preserve')
    self.assertFalse(bootstrap.fresh_home(home));self.assertEqual(path.read_text(),'preserve')
  with tempfile.TemporaryDirectory() as folder:self.assertTrue(bootstrap.fresh_home(Path(folder)))

 def test_distribution_is_pinned_to_ubuntu_2404(self):
  self.assertTrue(bootstrap.supported_distribution({'ID':'ubuntu','VERSION_ID':'24.04'}))
  for info in [{'ID':'debian','VERSION_ID':'12'},{'ID':'ubuntu','VERSION_ID':'22.04'},{}]:self.assertFalse(bootstrap.supported_distribution(info))

 def test_basic_configuration_receipt_records_only_fixed_files_and_refuses_links(self):
  with tempfile.TemporaryDirectory() as folder:
   home=Path(folder).resolve()
   for name in bootstrap.BASIC_FILES:
    path=home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'basic configuration')
   receipt=bootstrap.basic_file_receipt(home)
   self.assertEqual(set(receipt),set(bootstrap.BASIC_FILES));self.assertTrue(all(value==__import__('hashlib').sha256(b'basic configuration').hexdigest() for value in receipt.values()))
   path=home/bootstrap.BASIC_FILES[0];path.rename(path.with_suffix('.saved'));path.symlink_to(path.with_suffix('.saved'))
   with self.assertRaises(ValueError):bootstrap.basic_file_receipt(home)

if __name__=='__main__':unittest.main()
