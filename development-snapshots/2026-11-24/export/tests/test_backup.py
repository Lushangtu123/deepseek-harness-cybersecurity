from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest

repo=Path(__file__).resolve().parent.parent
class Backup(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'export'
  shutil.copytree(repo,self.root,ignore=shutil.ignore_patterns('.git','__pycache__'))
  self.manifest=self.root/'inventory/files.sha256.json'
  self.expected={str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file() and p!=self.manifest}
  self.manifest.write_text(json.dumps(self.expected))
 def run_check(self,*flags,env=None):return subprocess.run([sys.executable,*flags,'-B','scripts/verify_export.py'],cwd=self.root,capture_output=True,text=True,env=env,timeout=20)
 def change(self):
  with (self.root/'README.md').open('a') as f:f.write('\nSYNTHETIC_UNRECORDED_EDIT\n')
 def test_optimized_and_environment_optimized_reject_changed_bytes(self):
  self.change()
  for flags,env in [(('-O',),None),((),{**os.environ,'PYTHONOPTIMIZE':'1'})]:
   with self.subTest(flags=flags,envOptimized=env is not None):self.assertNotEqual(self.run_check(*flags,env=env).returncode,0)
 def test_integrity_findings_are_not_counted_as_credentials_or_matches(self):
  self.change();r=self.run_check();self.assertNotEqual(r.returncode,0);self.assertTrue(r.stdout,'Failures must be structured JSON')
  d=json.loads(r.stdout);self.assertEqual(d['credentialPatternFindings'],0);self.assertEqual(d['integrityFindings'],1);self.assertEqual(d['filesMatched'],len(self.expected)-1)
 def test_optimized_missing_file_is_a_structured_failure(self):
  (self.root/'README.md').unlink();r=self.run_check('-O');self.assertNotEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)['integrityFindings'],1)
 def test_clean_export_succeeds_in_both_modes(self):
  for flags in [(),('-O',)]:
   r=self.run_check(*flags);self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout);self.assertIn('ok',d);self.assertTrue(d['ok']);self.assertEqual(d['filesMatched'],len(self.expected))
 def test_fixed_credential_detection_does_not_echo_its_value(self):
  secret='sk-'+'A'*24
  with (self.root/'README.md').open('a') as f:f.write('\n'+secret+'\n')
  r=self.run_check('-O');self.assertNotEqual(r.returncode,0);self.assertNotIn(secret,r.stdout+r.stderr);d=json.loads(r.stdout);self.assertEqual(d['credentialPatternFindings'],1);self.assertEqual(d['integrityFindings'],1)
 def test_null_source_digests_cannot_match_missing_files(self):
  p=self.root/'work/harness-purge-improved/package-files.json';p.write_text(json.dumps({'missing.js':None}))
  p=self.root/'inventory/export.json';d=json.loads(p.read_text());d['guestFiles']={'guest-home/missing':{}};p.write_text(json.dumps(d))
  self.expected={str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file() and p!=self.manifest};self.manifest.write_text(json.dumps(self.expected))
  for flags in [(),('-O',)]:self.assertNotEqual(self.run_check(*flags).returncode,0)
 def test_repository_execute_bit_loss_fails_even_when_bytes_match(self):
  p=self.root/'guest-home/.local/bin/harness-vm-web';p.chmod(0o600);r=self.run_check('-O');self.assertNotEqual(r.returncode,0);d=json.loads(r.stdout);self.assertGreater(d['integrityFindings'],0);self.assertEqual(p.stat().st_mode&0o777,0o600)
if __name__=='__main__':unittest.main()
