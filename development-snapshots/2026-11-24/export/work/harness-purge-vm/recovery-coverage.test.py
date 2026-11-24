import importlib.util,tempfile,json,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
spec=importlib.util.spec_from_file_location('manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Coverage(unittest.TestCase):
 def test_current_point_includes_kali_bridge_but_never_secret_inputs(self):
  self.assertEqual(m.CURRENT_RECOVERY,'ready-security-review-20261101')
  self.assertIn('ready-storage-dashboard-20261101',m.REVIEWED_RECOVERIES)
  assets={'.local/bin/kali-vm','.dsh-improved/skills/kali/SKILL.md','.local/lib/harness-kali-tools/nmap','.local/lib/harness-kali-tools/curl','.config/harness-kali/ssh_config'}
  old=m.recovery_inventory({'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'a'*64}})
  self.assertTrue(assets<=set(old['uncovered']))
  supplied=m.recovery_inventory({'files':{**{name:'a'*64 for name in assets},'.config/harness-kali/id_ed25519':'b'*64}})
  self.assertTrue(assets<=set(supplied['expected']));self.assertNotIn('.config/harness-kali/id_ed25519',supplied['expected'])
 def test_tool_and_configuration_files_are_part_of_coverage(self):
  method=getattr(m,'recovery_inventory',None);self.assertTrue(callable(method),'Recovery inventory must include tools and config')
  files={'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'core','.dsh-improved/tooling/toolchain-version-checker/index.mjs':'tool','.dsh-improved/cordis.patch.yml':'config'}
  result=method({'files':files})
  self.assertEqual(result['expected'],files);self.assertIn('.local/bin/toolchain-versions',result['uncovered'])
  self.assertNotIn('.dsh-improved/cordis.patch.yml',result['uncovered'])
  self.assertEqual(set(result['groups']),{'program','runtime','tools','config','plugins'})
 def test_unrelated_proof_paths_cannot_expand_guest_reads(self):
  method=getattr(m,'recovery_inventory',None);self.assertTrue(callable(method),'Scoped recovery inventory missing')
  result=method({'files':{'tools/dsh-purge-personal-1.1.77-personal.1/../secret':'x','.dsh-improved/providers.yml':'secret','/etc/shadow':'x'}})
  self.assertEqual(result['expected'],{})
 def test_old_core_only_point_cannot_claim_full_coverage(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'checked_recovery_source',side_effect=lambda path,*args:(path.read_bytes() if path.name=='guest-proof.json' else b'original',0o600)),patch.object(m,'verify_recovery_bundle') as verify,patch.object(m,'current_host_inventory',return_value={name:'same' for name in m.RECOVERY_HELPERS}),patch.object(m,'image_command',return_value=MagicMock(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','differentFiles':[],'filesChecked':1}))):
   folder=Path(temp)/'recoveries'/m.CURRENT_RECOVERY;folder.mkdir(parents=True);(folder/'guest-proof.json').write_text(json.dumps({'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash'}}))
   verify.return_value=(folder,{'helpers':{name:'same' for name in m.RECOVERY_HELPERS},'guestProofSha256':'a'*64,'createdAt':'2026-10-26T00:00:00Z'})
   recovery=m.deployment_status()['recovery']
   self.assertEqual(recovery['state'],'older');self.assertIn('.local/bin/toolchain-versions',recovery['uncoveredFiles'])
 def test_latest_recovery_preserves_previous_points(self):
  self.assertEqual(m.CURRENT_RECOVERY,'ready-security-review-20261101');self.assertIn('ready-storage-preview-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-scanner-admission-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-parser-probe-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-session-lifecycle-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-auth-zap-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-ssh-channel-20261031',m.REVIEWED_RECOVERIES);self.assertIn('ready-professional-bootstrap-20261031',m.REVIEWED_RECOVERIES);self.assertIn('ready-pet-menu-20261030',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-pagination-20261030',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-lifecycle-20261030',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-background-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-diagnostics-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-workflow-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-validated-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-audit-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-recovery-proof-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-recovery-resume-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-recovery-guard-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-merged-stability-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-merged-capabilities-20261028-r1',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v30-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v29b-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v29-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v28-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v27b-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v27-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v26-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v25-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v24-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v23-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v22-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v21-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v20-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v19-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v18-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v17-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v16-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v15-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v14-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v13-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v12-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v11b-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v11-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v10-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v9-20261026',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v7-20261026',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v6-20261026',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v5-20261026',m.REVIEWED_RECOVERIES)
  self.assertIn('ready-workbench-v4-20261026',m.REVIEWED_RECOVERIES)
  self.assertIn('ready-workbench-v3-20261026',m.REVIEWED_RECOVERIES)
 def test_missing_disk_snapshot_cannot_show_matching_groups(self):
  method=getattr(m,'recovery_inventory',None);self.assertTrue(callable(method))
  files={'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash',**{name:'hash' for name in m.RECOVERY_TOOL_FILES|m.RECOVERY_CONFIG_FILES|m.RECOVERY_RUNTIME_FILES|{m.RECOVERY_PLUGIN_ROOT+n+'/package.json' for n in m.RECOVERY_PLUGINS}}}
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'checked_recovery_source',side_effect=lambda path,*args:(path.read_bytes() if path.name=='guest-proof.json' else b'original',0o600)),patch.object(m,'verify_recovery_bundle') as verify,patch.object(m,'current_host_inventory',return_value={name:'same' for name in m.RECOVERY_HELPERS}),patch.object(m,'image_command',return_value=MagicMock(stdout='{"snapshots":[]}')),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','differentFiles':[],'filesChecked':len(files)}))):
   folder=Path(temp)/'recoveries'/m.CURRENT_RECOVERY;folder.mkdir(parents=True);(folder/'guest-proof.json').write_text(json.dumps({'files':files}));verify.return_value=(folder,{'helpers':{name:'same' for name in m.RECOVERY_HELPERS},'guestProofSha256':'a'*64,'createdAt':'2026-10-26T00:00:00Z'})
   recovery=m.deployment_status()['recovery'];self.assertEqual(recovery['state'],'missing')
   self.assertTrue(all(group['state']=='missing' for group in recovery['groups'].values()))
 def test_host_launch_inventory_reads_only_the_two_fixed_non_symlink_files(self):
  method=getattr(m,'current_launch_inventory',None);self.assertTrue(callable(method),'Host launch coverage missing')
  with tempfile.TemporaryDirectory() as temp,patch.object(Path,'home',return_value=Path(temp)):
   folder=Path(temp)/'Library/LaunchAgents';folder.mkdir(parents=True)
   one=folder/(m.LABEL+'.plist');one.write_text('fixed egress definition')
   two=folder/(m.WEB_LABEL+'.plist');two.symlink_to(one)
   result=method();self.assertEqual(set(result),{one.name,two.name});self.assertEqual(result[one.name],m.file_sha(one));self.assertIsNone(result[two.name])
 def test_changed_or_missing_host_launch_config_invalidates_config_group(self):
  files={'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash',**{name:'hash' for name in m.RECOVERY_TOOL_FILES|m.RECOVERY_CONFIG_FILES|m.RECOVERY_RUNTIME_FILES|{m.RECOVERY_PLUGIN_ROOT+n+'/package.json' for n in m.RECOVERY_PLUGINS}}}
  expected={m.LABEL+'.plist':'egress',m.WEB_LABEL+'.plist':'web'}
  for actual in [{**expected,m.WEB_LABEL+'.plist':'changed'},{**expected,m.WEB_LABEL+'.plist':None},expected]:
   with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'checked_recovery_source',side_effect=lambda path,*args:(path.read_bytes() if path.name=='guest-proof.json' else b'original',0o600)),patch.object(m,'verify_recovery_bundle') as verify,patch.object(m,'current_host_inventory',return_value={name:'same' for name in m.RECOVERY_HELPERS}),patch.object(m,'current_launch_inventory',return_value=actual,create=True),patch.object(m,'image_command',return_value=MagicMock(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','differentFiles':[],'filesChecked':len(files)}))):
    folder=Path(temp)/'recoveries'/m.CURRENT_RECOVERY;folder.mkdir(parents=True);(folder/'guest-proof.json').write_text(json.dumps({'files':files}));verify.return_value=(folder,{'helpers':{name:'same' for name in m.RECOVERY_HELPERS},'launchAgents':expected,'guestProofSha256':'a'*64,'createdAt':'2026-10-26T00:00:00Z'})
    recovery=m.deployment_status()['recovery'];matches=actual==expected
    self.assertIn('launchAgentsMatch',recovery,'Host launch definitions are absent from coverage');self.assertEqual(recovery['launchAgentsMatch'],matches)
    self.assertEqual(recovery['state'],'matches' if matches else 'older')
    self.assertEqual(recovery['groups']['config']['state'],'matches' if matches else 'older')
    self.assertEqual(recovery['groups']['config']['filesChecked'],12)
    if not matches:self.assertIn('host-launch-agents/'+m.WEB_LABEL+'.plist',recovery['groups']['config']['differentFiles'])
 def test_security_runtime_lock_rules_and_metadata_are_covered_without_large_or_private_files(self):
  assets={'tools/security-workbench/images.json','tools/security-workbench/rules.json','tools/security-workbench/cache/db/metadata.json'}
  excluded={'tools/security-workbench/cache/db/trivy.db','tools/security-workbench/private-secrets.env','tools/security-workbench/backups/sample/journal.json'}
  value=m.recovery_inventory({'files':{name:'a'*64 for name in assets|excluded}})
  self.assertTrue(assets<=set(value['groups']['tools']))
  self.assertTrue(assets<=set(value['expected']))
  self.assertFalse(excluded&set(value['expected']))
  old=m.recovery_inventory({'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'a'*64}})
  self.assertTrue(assets<=set(old['uncovered']))
if __name__=='__main__':unittest.main()
