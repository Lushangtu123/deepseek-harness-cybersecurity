import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('plugin_observation',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PluginObservation(unittest.TestCase):
 def test_added_files_and_replaced_links_are_detected_without_reading_link_targets(self):
  method=getattr(m,'plugin_differences',None);self.assertTrue(callable(method),'Missing live plugin inventory comparison')
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);source=home/'tools/imported/dsh-context';source.mkdir(parents=True)
   (source/'package.json').write_text('{}');(source/'extra.js').write_text('extra')
   modules=home/'.dsh-improved/profiles/web/node_modules';modules.mkdir(parents=True)
   link=modules/'dsh-context';link.symlink_to(source)
   expected={'tools/imported/dsh-context/package.json':'unused'};roots={'dsh-context':'tools/imported/dsh-context'}
   self.assertEqual(method(home,expected,roots),['tools/imported/dsh-context/extra.js'])
   (source/'extra.js').unlink();link.unlink();link.symlink_to(home/'private-unrelated')
   self.assertEqual(method(home,expected,roots),['.dsh-improved/profiles/web/node_modules/dsh-context'])
 def test_symlinked_package_directories_are_not_traversed(self):
  method=getattr(m,'plugin_differences',None);self.assertTrue(callable(method))
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);secret=home/'private';secret.mkdir();(secret/'not-to-read').write_text('private')
   source=home/'tools/imported/dsh-context';source.mkdir(parents=True);(source/'linked').symlink_to(secret,target_is_directory=True)
   modules=home/'.dsh-improved/profiles/web/node_modules';modules.mkdir(parents=True);(modules/'dsh-context').symlink_to(source)
   self.assertEqual(method(home,{}, {'dsh-context':'tools/imported/dsh-context'}),['tools/imported/dsh-context/linked'])
 def test_symlink_in_import_parent_is_rejected_without_scanning_its_contents(self):
  method=getattr(m,'plugin_differences',None);self.assertTrue(callable(method))
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);(home/'tools').mkdir();private=home/'private/dsh-context';private.mkdir(parents=True);(private/'not-to-scan').write_text('private')
   (home/'tools/imported').symlink_to(home/'private',target_is_directory=True)
   result=method(home,{}, {'dsh-context':'tools/imported/dsh-context'})
   self.assertIn('tools/imported/dsh-context/package.json',result)
   self.assertFalse(any('not-to-scan' in name for name in result))
if __name__=='__main__':unittest.main()
