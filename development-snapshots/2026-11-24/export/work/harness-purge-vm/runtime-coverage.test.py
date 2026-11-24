import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
spec=importlib.util.spec_from_file_location('runtime_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PREFIX='tools/harness-improved-runtime/node_modules/@deepseek-ai/'
EXPECTED={PREFIX+name+'/lib/index.js' for name in ['dsh-tools','dsh-tool-bash','dsh-permission-presets','dsh-user-approval']}|{PREFIX+'dsh/package.json',PREFIX+'dsh/lib/bin.js'}

ORIGINAL='tools/harness-original-capabilities/'
EXPECTED|={ORIGINAL+'.personal-runtime-manifest.json',ORIGINAL+'lib/bin.js',ORIGINAL+'package.json'}|{ORIGINAL+'node_modules/@deepseek-ai/'+name+'/lib/index.js' for name in ['dsh-tools','dsh-tool-bash','dsh-permission-presets','dsh-user-approval']}

class RuntimeCoverage(unittest.TestCase):
 def test_core_coverage_is_a_fixed_daily_and_original_file_list_not_an_arbitrary_directory(self):
  self.assertEqual(getattr(m,'RECOVERY_RUNTIME_FILES',set()),EXPECTED)
  files={name:'a'*64 for name in EXPECTED};files[PREFIX+'dsh/providers/credentials.yml']='private'
  result=m.recovery_inventory({'files':files})
  self.assertEqual(set(result['expected']),EXPECTED);self.assertEqual(set(result['groups']['runtime']),EXPECTED)
 def status(self,files):
  folder=Path(self.temp)/'recoveries'/m.CURRENT_RECOVERY;folder.mkdir(parents=True)
  (folder/'guest-proof.json').write_text(json.dumps({'files':files}))
  jobs={m.LABEL+'.plist':'egress',m.WEB_LABEL+'.plist':'web'}
  actual={'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','filesChecked':len(files),'differentFiles':[],'runtimePackageVersion':'0.2.1-rc.3'}
  with patch.object(m,'ROOT',Path(self.temp)),patch.object(m,'validate'),patch.object(m,'checked_recovery_source',side_effect=lambda path,*args:(path.read_bytes() if path.name=='guest-proof.json' else b'original',0o600)),patch.object(m,'verify_recovery_bundle',return_value=(folder,{'helpers':{name:'same' for name in m.RECOVERY_HELPERS},'launchAgents':jobs,'guestProofSha256':'a'*64,'createdAt':'2026-10-26T00:00:00Z'})),patch.object(m,'current_host_inventory',return_value={name:'same' for name in m.RECOVERY_HELPERS}),patch.object(m,'current_launch_inventory',return_value=jobs),patch.object(m,'image_command',return_value=MagicMock(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps(actual))) as ssh:
   result=m.deployment_status();self.guest_script=ssh.call_args.kwargs['input'];return result
 def test_an_old_recovery_point_explicitly_leaves_runtime_uncovered(self):
  with tempfile.TemporaryDirectory() as self.temp:
   files={'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash',**{name:'hash' for name in m.RECOVERY_TOOL_FILES|m.RECOVERY_CONFIG_FILES}}
   data=self.status(files)
   self.assertIn('runtime',data['recovery'].get('groups',{}),'Runtime coverage must not disappear for an old point')
   self.assertEqual(data['recovery']['groups']['runtime']['state'],'uncovered')
   self.assertEqual(data['recovery']['state'],'older');self.assertEqual(set(data['recovery']['uncoveredFiles']),EXPECTED|{m.RECOVERY_PLUGIN_ROOT+n+'/package.json' for n in m.RECOVERY_PLUGINS})
 def test_complete_fixed_runtime_coverage_and_package_version_are_exposed(self):
  with tempfile.TemporaryDirectory() as self.temp:
   files={'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash',**{name:'hash' for name in m.RECOVERY_TOOL_FILES|m.RECOVERY_CONFIG_FILES|EXPECTED|{m.RECOVERY_PLUGIN_ROOT+n+'/package.json' for n in m.RECOVERY_PLUGINS}}}
   data=self.status(files)
   self.assertEqual(data.get('runtimePackageVersion'),'0.2.1-rc.3')
   self.assertEqual(data['recovery']['groups']['runtime']['filesChecked'],len(EXPECTED))
   self.assertEqual(data['recovery']['state'],'matches')
 def test_a_non_object_package_json_cannot_abort_the_rest_of_status_inspection(self):
  with tempfile.TemporaryDirectory() as self.temp:
   self.status({'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash'})
   fragment='version=None\n'+self.guest_script.split('version=None\n',1)[1].split('expected=',1)[0]
   package=Path(self.temp)/'package.json'
   for value in [[],None,17,'synthetic invalid metadata',{'version':'0.2.1-rc.3'}]:
    package.write_text(json.dumps(value));scope={'package':package,'home':Path(self.temp).resolve(),'json':json}
    try:exec(fragment,scope)
    except Exception as error:self.fail('Malformed package metadata aborted status: '+type(error).__name__)
    self.assertEqual(scope['version'],value.get('version') if isinstance(value,dict) else None)
if __name__=='__main__':unittest.main()
