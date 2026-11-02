import importlib.util,tempfile,unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parent.parent/'package/scripts/security-kali-lab.py'
class KaliLab(unittest.TestCase):
 def module(self):
  self.assertTrue(SCRIPT.is_file(),'Missing bounded Kali synthetic lab')
  spec=importlib.util.spec_from_file_location('kali_lab',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_fixed_argv_and_no_freeform_target(self):
  m=self.module();argv=m.remote_argv('run','review-fixture-001');self.assertEqual(argv[:4],['/home/purge/.local/bin/kali-vm','exec','--','python3']);self.assertEqual(argv[-3:],['run','review-fixture-001','normal'])
  for identity in ['../secret','short','x;touch owned']:
   with self.assertRaises(ValueError):m.remote_argv('run',identity)
  with self.assertRaises(ValueError):m.remote_argv('shell','valid-run-id')
 def test_runtime_source_only_checks_loopback_and_normalizes_proof(self):
  m=self.module();self.assertIn("'127.0.0.1'",m.REMOTE_SOURCE);self.assertIn("'--noproxy','*'",m.REMOTE_SOURCE);self.assertIn("'-sT'",m.REMOTE_SOURCE);self.assertNotIn('shell=True',m.REMOTE_SOURCE);self.assertIn('finally:',m.REMOTE_SOURCE)
if __name__=='__main__':unittest.main()
