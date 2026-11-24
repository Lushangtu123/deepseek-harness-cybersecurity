from pathlib import Path
import importlib.util,tempfile,unittest,json
HERE=Path(__file__).resolve().parent
class SnapshotTest(unittest.TestCase):
 def test_independent_snapshot_binds_code_dependencies_recipes_and_policy(self):
  script=HERE/'verifier_snapshot.py';self.assertTrue(script.exists(),'Verifier snapshot missing');s=importlib.util.spec_from_file_location('verifier_snapshot',script);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();deps=root/'deps';deps.mkdir();(deps/'example.py').write_text('# no execution\n')
   api=m.launcher();modules=HERE.parent/'work/harness-purge-improved/package/scripts';static=api.freeze(modules,root/'static','sha256:'+'a'*64);pin=api.digest(static)
   lock={'version':1,'files':{'example.py':api.sha256((deps/'example.py').read_bytes()).hexdigest()},'packages':[]}
   contract={'version':1,'path':'app.py','entry':{'kind':'function','name':'route','parameter':'value'},'inputContract':'untrusted-data-only'}
   value=m.freeze(root/'static',pin,deps,lock,[contract],root/'verifier');self.assertEqual(value['version'],1);self.assertEqual(len(value['code']),4)
   self.assertEqual(m.verify(root/'verifier',m.digest(value))[0],value)
   (root/'verifier/dependencies/example.py').chmod(0o600)
   (root/'verifier/dependencies/example.py').write_text('# changed\n')
   with self.assertRaises(ValueError):m.verify(root/'verifier',m.digest(value))
if __name__=='__main__':unittest.main()
