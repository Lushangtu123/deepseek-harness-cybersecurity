import importlib.util,tempfile,unittest,subprocess
from unittest.mock import patch
from pathlib import Path
module_path=Path(__file__).resolve().parents[1]/'install_guest.py'
class Install(unittest.TestCase):
 def setUp(self):
  self.assertTrue(module_path.exists(),'Guest rollback installer is missing')
  spec=importlib.util.spec_from_file_location('installer',module_path);self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
 def fixture(self,home):
  root=home/'tooling';profile=home/'improved.yml';original=home/'original.yml';command=home/'bin/toolchain-versions'
  root.mkdir();command.parent.mkdir();profile.write_text('improved-before\n');original.write_text('original-before\n')
  return root,profile,original,command
 def test_failed_restart_rolls_back_existing_and_new_files(self):
  with tempfile.TemporaryDirectory() as temp:
   args=self.fixture(Path(temp));root,profile,original,command=args
   (root/'index.mjs').write_text('old');command.write_text('old command');command.chmod(0o750)
   calls=[]
   def restart():
    calls.append(1)
    if len(calls)==1:raise subprocess.CalledProcessError(1,'restart')
   with self.assertRaises(subprocess.CalledProcessError):self.m.install(*args,{'index.mjs':'new','catalog.json':'{}'},restart)
   self.assertEqual((root/'index.mjs').read_text(),'old');self.assertFalse((root/'catalog.json').exists());self.assertEqual(command.read_text(),'old command')
   self.assertEqual(command.stat().st_mode&0o777,0o750);self.assertEqual(profile.read_text(),'improved-before\n');self.assertEqual(original.read_text(),'original-before\n');self.assertEqual(len(calls),2)
 def test_success_installs_once_preserving_original_profile(self):
  with tempfile.TemporaryDirectory() as temp:
   args=self.fixture(Path(temp));root,profile,original,command=args
   for i in range(2):self.m.install(*args,{'index.mjs':'new','catalog.json':'{}'},lambda:None)
   self.assertEqual(profile.read_text().count('id: personal-toolchain-versions'),1);self.assertEqual(original.read_text(),'original-before\n');self.assertTrue(command.stat().st_mode&0o100)
   self.assertEqual((root/'cordis-before-toolchain.yml').read_text(),'improved-before\n')
 def test_restart_commands_have_bounded_budgets(self):
  with patch.object(self.m.subprocess,'run') as run:
   self.m.restart_service()
   self.assertEqual(len(run.call_args_list),2)
   for call in run.call_args_list:
    self.assertGreater(call.kwargs.get('timeout',0),0)
    self.assertLessEqual(call.kwargs['timeout'],40)
 def test_restart_timeout_restores_files(self):
  with tempfile.TemporaryDirectory() as temp:
   args=self.fixture(Path(temp));calls=[]
   def restart():
    calls.append(1)
    if len(calls)==1:raise subprocess.TimeoutExpired('systemctl',40)
   with self.assertRaises(subprocess.TimeoutExpired):self.m.install(*args,{'index.mjs':'new'},restart)
   self.assertFalse((args[0]/'index.mjs').exists());self.assertEqual(args[1].read_text(),'improved-before\n');self.assertFalse(args[3].exists());self.assertEqual(len(calls),2)
 def test_rollback_restart_failure_is_explicit(self):
  with tempfile.TemporaryDirectory() as temp:
   args=self.fixture(Path(temp))
   def restart():raise subprocess.TimeoutExpired('systemctl',40)
   with self.assertRaisesRegex(RuntimeError,'rollback needs inspection'):self.m.install(*args,{'index.mjs':'new'},restart)
   self.assertFalse((args[0]/'index.mjs').exists());self.assertEqual(args[1].read_text(),'improved-before\n')
if __name__=='__main__':unittest.main()
