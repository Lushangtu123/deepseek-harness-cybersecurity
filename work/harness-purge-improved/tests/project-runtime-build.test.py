import hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'package/scripts/security-runtime-template-build.py'
class FrozenDependencies(unittest.TestCase):
 def module(self):
  self.assertTrue(P.exists(),'Offline template builder missing');s=importlib.util.spec_from_file_location('template_build_test',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_exact_tree_copies_without_executing_hooks_and_rejects_late_changes(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve()/'deps';root.mkdir();(root/'package.py').write_text('raise RuntimeError("NEVER_IMPORT_THIS_ON_HOST")\n');rows=m.inventory(root);lock={'dependencyTreeSha256':m.digest(rows),'dependencyFiles':1,'dependencyBytes':rows[0]['bytes']};out=Path(d).resolve()/'stage';m.freeze_dependencies(root,out,lock);self.assertEqual((out/'package.py').read_bytes(),(root/'package.py').read_bytes());(root/'package.py').write_text('changed');self.assertRaises(ValueError,m.freeze_dependencies,root,Path(d).resolve()/'changed',lock)
 def test_dependency_links_cannot_read_outside_the_locked_tree(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve()/'deps';root.mkdir();(root/'escape.py').symlink_to('/etc/hosts');self.assertRaises(ValueError,m.inventory,root)
if __name__=='__main__':unittest.main()
