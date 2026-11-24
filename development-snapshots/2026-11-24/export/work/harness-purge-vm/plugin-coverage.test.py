import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('plugin_coverage_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ROOT='tools/imported-dsh-plugins-20261027T185822Z/'
class PluginCoverage(unittest.TestCase):
 def test_plugin_sources_and_nested_dependencies_are_covered_with_profile_manifest(self):
  files={ROOT+'dsh-context/lib/index.js':'a',ROOT+'dsh-context/node_modules/zod/index.js':'b',ROOT+'dshmarket/package.json':'c','.dsh-improved/profiles/web/package.json':'d'}
  result=m.recovery_inventory({'files':files})
  self.assertEqual(result['expected'],files)
  self.assertEqual(set(result['groups']['plugins']),{ROOT+name+'/package.json' for name in ['dsh-context','dshmarket','dsh-whale-widget']}|{ROOT+'dsh-context/lib/index.js',ROOT+'dsh-context/node_modules/zod/index.js'})
 def test_old_points_report_each_imported_plugin_manifest_as_uncovered(self):
  result=m.recovery_inventory({'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'a'}})
  self.assertTrue({ROOT+name+'/package.json' for name in ['dsh-context','dshmarket','dsh-whale-widget']}<=set(result['uncovered']))
 def test_plugin_scope_cannot_expand_to_unrelated_packages_or_private_home(self):
  invalid={ROOT+'other-plugin/index.js':'x',ROOT+'dsh-context/../credentials.yml':'x',ROOT+'dsh-context/.env':'x','tools/other-import/dsh-context/index.js':'x','.dsh-improved/providers.yml':'x'}
  self.assertEqual(m.recovery_inventory({'files':invalid})['expected'],{})
if __name__=='__main__':unittest.main()
