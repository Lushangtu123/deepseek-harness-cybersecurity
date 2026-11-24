"""The CI gate must propagate failure and never rebuild the checked-in bundle in place."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util,subprocess,tempfile,unittest,io

class CIGate(unittest.TestCase):
 def setUp(self):
  output=patch('sys.stdout',new_callable=io.StringIO);output.start();self.addCleanup(output.stop)
 def load(self):
  path=Path(__file__).with_name('ci.py');self.assertTrue(path.is_file(),'Dependency-free CI entry point missing')
  spec=importlib.util.spec_from_file_location('ci_fixture',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 def fixture(self,root):
  for name in ['scripts/one.test.py','work/harness-purge-vm/two.test.py','work/harness-purge-improved/tests/three.test.py']:
   path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('pass\n')
 def test_python_gate_discovers_all_owned_test_roots(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();self.fixture(root);calls=[]
   def run(argv,**kwargs):calls.append((argv,kwargs));return SimpleNamespace(returncode=0)
   self.assertEqual(module.run_suite(root,'python',run=run),0)
   self.assertEqual({Path(argv[-1]).relative_to(root).as_posix() for argv,_ in calls},{'scripts/one.test.py','work/harness-purge-vm/two.test.py','work/harness-purge-improved/tests/three.test.py'})
   self.assertTrue(all('-B' in argv for argv,_ in calls))
 def test_nonzero_child_exit_is_not_converted_to_success_or_retried(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();self.fixture(root);calls=[]
   def run(argv,**kwargs):calls.append(argv);return SimpleNamespace(returncode=7)
   self.assertEqual(module.run_suite(root,'python',run=run),7);self.assertEqual(len(calls),1)
 def test_timeout_and_missing_tool_remain_nonzero(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();self.fixture(root)
   def timeout(argv,**kwargs):raise subprocess.TimeoutExpired(argv,1)
   self.assertEqual(module.run_suite(root,'python',run=timeout),124)
   (root/'work/harness-purge-improved/tests/sample.test.mjs').write_text('')
   with patch.object(module.shutil,'which',return_value=None):self.assertEqual(module.run_suite(root,'plugin'),127)
 def test_empty_or_symlinked_test_inventory_cannot_pass(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();self.assertNotEqual(module.run_suite(root,'python'),0);self.fixture(root)
   outside=root/'outside.py';outside.write_text('pass\n');(root/'scripts/linked.test.py').symlink_to(outside)
   self.assertNotEqual(module.run_suite(root,'python'),0)
 def test_client_rebuild_checks_a_temporary_copy_and_rejects_changed_bytes(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();package=root/'work/harness-purge-improved/package';(package/'scripts').mkdir(parents=True);(package/'client.js').write_bytes(b'original');(package/'scripts/build-client.mjs').write_text('// fixture')
   def changed(argv,**kwargs):
    self.assertNotEqual(Path(kwargs['cwd']),package);(Path(kwargs['cwd'])/'client.js').write_bytes(b'changed');return SimpleNamespace(returncode=0)
   with patch.object(module.shutil,'which',return_value='/node-fixture'):self.assertNotEqual(module.run_suite(root,'client',run=changed),0)
   self.assertEqual((package/'client.js').read_bytes(),b'original')

if __name__=='__main__':unittest.main()
