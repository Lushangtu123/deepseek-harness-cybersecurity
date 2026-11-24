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
 def test_returned_dependency_bytes_are_the_same_bytes_that_were_hashed(self):
  from unittest.mock import patch
  s=importlib.util.spec_from_file_location('vs_read_once',HERE/'verifier_snapshot.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();p=root/'dep.py';raw=b'approved bytes';p.write_bytes(raw);want=m.sha256(raw).hexdigest();original=Path.read_bytes;reads=[]
   def raced(file):
    if file==p:
     reads.append(1);return raw if len(reads)==1 else b'replacement bytes'
    return original(file)
   with patch.object(Path,'read_bytes',raced):returned=m.tree(root,{'dep.py':want})
   self.assertEqual(m.sha256(returned['dep.py']).hexdigest(),want)
 def test_linked_or_external_dependency_never_enters_snapshot(self):
  s=importlib.util.spec_from_file_location('vs_links',HERE/'verifier_snapshot.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();d=root/'deps';d.mkdir();p=root/'outside.py';p.write_bytes(b'outside');(d/'dep.py').symlink_to(p)
   with self.assertRaises(ValueError):m.tree(d,{'dep.py':m.sha256(b'outside').hexdigest()})
if __name__=='__main__':unittest.main()
