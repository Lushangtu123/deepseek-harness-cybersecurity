import importlib.util,unittest,copy,subprocess,tempfile,urllib.request,urllib.error,plistlib,json,hashlib
from unittest.mock import patch,MagicMock
from pathlib import Path
spec=importlib.util.spec_from_file_location('manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ConfigurationGate(unittest.TestCase):
 def setUp(self):
  folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);root=patch.object(m,'ROOT',Path(folder.name));root.start();self.addCleanup(root.stop)
 def test_accepts_only_dedicated_isolated_configuration(self):m.validate_config(m.expected_config_fixture())
 def test_rejects_any_normal_nic_host_share_or_wrong_vm(self):
  for group,field,value in [('Information','UUID','other'),('Sharing','ClipboardSharing',True),('Sharing','DirectoryShareMode','VirtFS'),('Input','UsbSharing',True)]:
   c=m.expected_config_fixture();c[group][field]=value
   with self.assertRaises(ValueError):m.validate_config(c)
class GuestClock(unittest.TestCase):
 def responses(self,values,scripts):
  values=iter(values)
  def run(script,**kwargs):
   scripts.append(script() if callable(script) else script)
   return MagicMock(stdout=next(values))
  return run
 def test_small_skew_is_measured_without_changing_time(self):
  scripts=[]
  with patch.object(m.time,'time',side_effect=[1000,1000.2]),patch.object(m,'ssh',side_effect=self.responses(['1000.1'],scripts)) as ssh:
   result=m.synchronize_clock()
   self.assertFalse(result['adjusted']);self.assertAlmostEqual(result['offsetSeconds'],0)
   self.assertEqual(ssh.call_count,1)
 def test_large_skew_sets_only_guest_time_and_verifies_it(self):
  scripts=[]
  with patch.object(m.time,'time',side_effect=[1000,1000.2,1000.3,1000.4,1000.6]),patch.object(m,'ssh',side_effect=self.responses(['900','','1000.5'],scripts)) as ssh:
   result=m.synchronize_clock()
   self.assertTrue(result['adjusted']);self.assertAlmostEqual(result['offsetSeconds'],0)
   self.assertIn('sudo -n /usr/bin/date -u --set=@1000.300000',scripts[1])
   self.assertEqual(ssh.call_count,3)
 def test_ambiguous_or_slow_measurement_never_sets_time(self):
  for value,clock in [('nan',[1000,1000.1]),('invalid',[1000,1000.1]),('1000',[1000,1003])]:
   with patch.object(m.time,'time',side_effect=clock),patch.object(m,'ssh',side_effect=self.responses([value],[])) as ssh:
    with self.assertRaises(ValueError):m.synchronize_clock()
    self.assertEqual(ssh.call_count,1)
 def test_unverified_adjustment_fails_instead_of_claiming_ready(self):
  with patch.object(m.time,'time',side_effect=[1000,1000.2,1000.3,1000.4,1000.6]),patch.object(m,'ssh',side_effect=self.responses(['900','','900'],[])):
   with self.assertRaises(RuntimeError):m.synchronize_clock()

class Lifecycle(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  guard=patch.object(m,'ROOT',Path(self.temp.name));guard.start();self.addCleanup(guard.stop)
 def test_current_recovery_keeps_the_previous_reviewed_recovery_available(self):
  self.assertEqual(m.CURRENT_RECOVERY,'ready-security-review-20261101');self.assertIn('ready-scanner-admission-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-parser-probe-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-session-lifecycle-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-auth-zap-20261101',m.REVIEWED_RECOVERIES);self.assertIn('ready-ssh-channel-20261031',m.REVIEWED_RECOVERIES);self.assertIn('ready-professional-bootstrap-20261031',m.REVIEWED_RECOVERIES);self.assertIn('ready-pet-menu-20261030',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-pagination-20261030',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-lifecycle-20261030',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-background-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-diagnostics-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-workflow-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-validated-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-security-audit-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-recovery-proof-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-recovery-resume-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-recovery-guard-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-merged-stability-20261029',m.REVIEWED_RECOVERIES);self.assertIn('ready-merged-capabilities-20261028-r1',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v30-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v29b-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v29-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v28-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v27b-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v27-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v26-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v25-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v24-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v23-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v22-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v21-20261028',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v20-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v19-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v18-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v17-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v16-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v15-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v14-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v13-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v12-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v11b-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v11-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v10-20261027',m.REVIEWED_RECOVERIES);self.assertIn('ready-workbench-v9-20261026',m.REVIEWED_RECOVERIES)
  self.assertEqual(m.recovery_path('ready-workbench-v6-20261026').name,'ready-workbench-v6-20261026')
  self.assertEqual(m.recovery_path('ready-workbench-v5-20261026').name,'ready-workbench-v5-20261026')
  self.assertEqual(m.recovery_path('ready-workbench-v3-20261026').name,'ready-workbench-v3-20261026')
  self.assertEqual(m.recovery_path('ready-workbench-20261026').name,'ready-workbench-20261026')
  self.assertEqual(m.recovery_path('ready-improved-20261026').name,'ready-improved-20261026')
 def test_deployment_status_uses_actual_runtime_and_validates_recovery_code_coverage(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'checked_recovery_source',side_effect=lambda path,*args:(path.read_bytes() if path.name=='guest-proof.json' else b'original',0o600)),patch.object(m,'verify_recovery_bundle') as verify,patch.object(m,'current_host_inventory',return_value={'manage.py':'same'}),patch.object(m,'image_command',return_value=MagicMock(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({'mode':'original','configDir':'/home/purge/.dsh','modeFile':'original','differentFiles':['client.js'],'filesChecked':1}))) as ssh:
   folder=Path(temp)/'bundle';folder.mkdir();(folder/'guest-proof.json').write_text(json.dumps({'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash'}}))
   (Path(temp)/'recoveries'/m.CURRENT_RECOVERY).mkdir(parents=True)
   verify.return_value=(folder,{'helpers':{'manage.py':'same','qemu-image.py':'same'},'guestProofSha256':'a'*64,'createdAt':'2026-10-26T00:00:00Z'})
   method=getattr(m,'deployment_status',None);self.assertTrue(callable(method),'Read-only deployment status is missing')
   result=method();self.assertEqual(result['mode'],'original');self.assertEqual(result['configDir'],'/home/purge/.dsh');self.assertEqual(result['recovery']['state'],'older');self.assertIn('python3',ssh.call_args.args[0]);self.assertNotIn('restart',ssh.call_args.args[0])
 def test_recovery_status_cannot_match_when_the_disk_snapshot_is_missing(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'checked_recovery_source',side_effect=lambda path,*args:(path.read_bytes() if path.name=='guest-proof.json' else b'original',0o600)),patch.object(m,'verify_recovery_bundle') as verify,patch.object(m,'current_host_inventory',return_value={'manage.py':'same'}),patch.object(m,'image_command',return_value=MagicMock(stdout='{"snapshots":[]}')),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','differentFiles':[],'filesChecked':1}))):
   folder=Path(temp)/'recoveries'/m.CURRENT_RECOVERY;folder.mkdir(parents=True);(folder/'guest-proof.json').write_text(json.dumps({'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash'}}));verify.return_value=(folder,{'helpers':{'manage.py':'same','qemu-image.py':'same'},'guestProofSha256':'a'*64,'createdAt':'2026-10-26T00:00:00Z'})
   self.assertEqual(m.deployment_status()['recovery']['state'],'missing')
 def test_readiness_requires_assets_and_authenticated_read_api_not_just_html(self):
  response=MagicMock();response.__enter__.return_value=response;response.status=200
  response.read.side_effect=[b'<script src="./assets/main.js"></script>',b'console.log(1)',b'{"ok":false}']
  with patch.object(m.urllib.request,'build_opener',return_value=MagicMock(open=MagicMock(return_value=response))):
   self.assertFalse(m.authenticated_ready('http://127.0.0.1:49226/?token=synthetic'))
 def test_recovery_bundle_checks_every_helper_and_rejects_tampering(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)):
   folder=Path(temp)/'recoveries'/m.CURRENT_RECOVERY
   (folder/'host-tools').mkdir(parents=True);(folder/'launch-agents').mkdir()
   data={'vmUUID':m.UUID,'snapshot':m.CURRENT_RECOVERY,'createdAt':'2026-10-29T00:00:00Z','helpers':{},'launchAgents':{}}
   for name in m.RECOVERY_HELPERS:
    file=folder/'host-tools'/name;file.write_text('synthetic '+name);data['helpers'][name]=m.file_sha(file)
   for label in [m.LABEL,m.WEB_LABEL]:
    file=folder/'launch-agents'/(label+'.plist');file.write_text('synthetic plist');data['launchAgents'][file.name]=m.file_sha(file)
   (folder/'guest-proof.json').write_text(json.dumps({'vmUUID':m.UUID,'mode':'improved','recoveryName':m.CURRENT_RECOVERY,'files':{'client.js':'a'*64}}));data['guestProofSha256']=m.file_sha(folder/'guest-proof.json')
   (folder/'manifest.json').write_text(json.dumps(data))
   self.assertEqual(m.verify_recovery_bundle(m.CURRENT_RECOVERY)[1],data)
   (folder/'host-tools/manage.py').write_text('tampered')
   with self.assertRaisesRegex(ValueError,'checksum'):m.verify_recovery_bundle(m.CURRENT_RECOVERY)
 def test_current_recovery_will_not_overwrite_an_existing_snapshot(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'image_command',return_value=MagicMock(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))) as image:
   with self.assertRaisesRegex(ValueError,'already exists'):m.create_current_recovery()
   self.assertEqual(image.call_count,1)
 def test_failed_combined_restore_rolls_back_disk_and_host_helpers(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'verify_recovery_bundle',return_value=(Path('/synthetic/recovery'),{'helpers':{}})),patch.object(m,'prepare_host_bundle',return_value={'helpers':{'qemu-image.py':(b'checked helper',0o600)}}),patch.object(m,'copy_host_bundle',return_value={'helpers':{'before':'hash'}}),patch.object(m,'image_command',return_value=MagicMock(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))) as image,patch.object(m,'apply_host_bundle',side_effect=[RuntimeError('host switch failed'),None]) as apply:
   (Path(temp)/'recoveries').mkdir()
   with self.assertRaisesRegex(RuntimeError,'host switch failed'):m.restore_current_recovery(m.CURRENT_RECOVERY)
   calls=[c.args[0] for c in image.call_args_list]
   self.assertEqual(calls[2][:3],['snapshot','-a',m.CURRENT_RECOVERY])
   self.assertTrue(calls[3][2].startswith('pre-restore-'))
   self.assertEqual(apply.call_count,2)
   self.assertEqual(apply.call_args.args[1],{'helpers':{'before':'hash'}})
   self.assertFalse(m.copy_host_bundle.call_args.kwargs['verify_current'])
   for call in image.call_args_list:
    self.assertEqual(call.kwargs.get('helper'),b'checked helper','Restoration must not depend on a missing or damaged current image helper')
 def test_current_recovery_requires_offline_vm_before_any_snapshot_change(self):
  create=getattr(m,'create_current_recovery',None)
  self.assertTrue(callable(create),'Current improved recovery creation must exist')
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m,'image_command') as image:
   with self.assertRaises(RuntimeError):create()
   image.assert_not_called()
 def test_new_recovery_restoration_requires_verified_matching_host_helpers(self):
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'verify_recovery_bundle',side_effect=ValueError('Recovery bundle checksum mismatch'),create=True) as verify,patch.object(m,'image_command') as image:
   with self.assertRaisesRegex(ValueError,'checksum'):m.restore(True,'ready-improved-20261026')
   verify.assert_called_once();image.assert_not_called()
 def test_switch_rejects_arbitrary_modes_before_starting(self):
  with patch.object(m,'start') as start,patch.object(m,'ssh') as ssh:
   with self.assertRaises(ValueError):m.switch('improved; touch bad',True)
   start.assert_not_called();ssh.assert_not_called()
 def test_switch_uses_fixed_guest_mode_and_refreshes_authenticated_entry(self):
  with patch.object(m,'start') as start,patch.object(m,'ssh') as ssh,patch('builtins.print'):
   m.switch('improved',True)
   self.assertEqual(start.call_count,2)
   self.assertIn("mode = 'improved'",ssh.call_args.args[0])
   self.assertIn('systemctl',ssh.call_args.args[0])
   self.assertNotIn('danger-full-access',ssh.call_args.args[0])
 def test_readiness_cannot_follow_guest_redirect_to_another_host_service(self):
  with self.assertRaises(urllib.error.HTTPError):m.LocalRedirect().redirect_request(None,None,302,'Found',{},'http://127.0.0.1:80/')
 def test_start_does_not_save_stale_unauthenticated_url(self):
  old='http://127.0.0.1:49224/?token=old-synthetic';new='http://127.0.0.1:49224/?token=current-synthetic'
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'proxy_start'),patch.object(m,'web_entry_start',create=True) as entry,patch.object(m,'vm_status',return_value='started'),patch.object(m,'synchronize_clock',return_value={'adjusted':False,'offsetSeconds':0},create=True) as sync,patch.object(m,'ssh',side_effect=[MagicMock(stdout='active'),MagicMock(stdout=old),MagicMock(stdout='active'),MagicMock(stdout=new)]),patch.object(m,'authenticated_ready',side_effect=[False,True],create=True) as ready,patch.object(m.time,'sleep'),patch('builtins.print'):
   m.start(True)
   stable=new.replace(':49224/',':49226/')
   self.assertEqual((Path(temp)/'access-url.txt').read_text().strip(),stable)
   shortcut=Path(temp)/'打开虚拟机Harness.webloc'
   self.assertEqual(plistlib.loads(shortcut.read_bytes()),{'URL':stable})
   self.assertEqual(shortcut.stat().st_mode&0o777,0o600)
   self.assertEqual(ready.call_count,2)
   sync.assert_called_once()
   entry.assert_called_once()
 def test_stable_entry_uses_only_the_dedicated_managed_helper(self):
  job=getattr(m,'web_entry_job',lambda:{})()
  self.assertEqual(job.get('ProgramArguments'),['/opt/homebrew/bin/node',str(m.TOOLS/'web-entry.mjs')])
  self.assertFalse(job['RunAtLoad']);self.assertFalse(job['KeepAlive'])
 def test_stable_entry_requires_its_own_pid_and_exact_loopback_listener(self):
  check=getattr(m,'web_entry_listener_owned',lambda:False)
  for listener,expected in [('p123\nn127.0.0.1:49226\n',True),('p123\nn*:49226\n',False),('',False)]:
   with patch.object(m.subprocess,'run',side_effect=[MagicMock(returncode=0,stdout='\tpid = 123\n'),MagicMock(returncode=0,stdout=listener)]):
    self.assertEqual(check(),expected)
 def test_stop_also_closes_the_stable_entry(self):
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'web_entry_stop',create=True) as entry,patch.object(m,'proxy_stop'),patch('builtins.print'):
   m.stop();entry.assert_called_once()
 def test_entry_stop_waits_through_reset_until_listener_refuses_connections(self):
  with patch.object(m.subprocess,'run',return_value=MagicMock(returncode=0)),patch.object(m.socket,'create_connection',side_effect=[ConnectionResetError(54,'Connection reset by peer'),ConnectionRefusedError()]) as probe,patch.object(m.time,'sleep'):
   m.web_entry_stop()
   self.assertEqual(probe.call_count,2)
 def test_entry_stop_repeated_resets_do_not_prove_listener_closed(self):
  with patch.object(m.subprocess,'run',return_value=MagicMock(returncode=0)),patch.object(m.socket,'create_connection',side_effect=ConnectionResetError(54,'Connection reset by peer')),patch.object(m.time,'monotonic',side_effect=[0,1,9]),patch.object(m.time,'sleep'):
   with self.assertRaisesRegex(RuntimeError,'remains open'):m.web_entry_stop()
 def test_entry_stop_keeps_unexpected_probe_failure_visible(self):
  with patch.object(m.subprocess,'run',return_value=MagicMock(returncode=0)),patch.object(m.socket,'create_connection',side_effect=PermissionError('denied')):
   with self.assertRaises(PermissionError):m.web_entry_stop()
 def test_restore_rejects_unreviewed_snapshot_names(self):
  with patch.object(m,'validate'),patch.object(m,'command') as command:
   with self.assertRaises(ValueError):m.restore(True,'../../other-vm')
   command.assert_not_called()
 def test_image_utility_resolves_only_installed_utm_frameworks(self):
  with patch.object(m,'command') as command:
   m.image_command(['info','disk.qcow2'])
   self.assertEqual(command.call_args.kwargs['env']['DYLD_FRAMEWORK_PATH'],'/Applications/UTM.app/Contents/Frameworks')
 def test_ssh_uses_single_quoted_trust_path_without_global_fallback(self):
  with patch.object(m,'command') as run:
   m.ssh('true');args=run.call_args.args[0]
   self.assertIn('UserKnownHostsFile="'+str(m.SETUP/'known_hosts')+'"',args)
   self.assertIn('GlobalKnownHostsFile=/dev/null',args)
 def test_paused_vm_never_reports_successful_stop(self):
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='paused'),patch.object(m,'ssh') as ssh,patch('builtins.print') as out:
   with self.assertRaises(RuntimeError):m.stop()
   ssh.assert_not_called();out.assert_not_called()
 def test_proxy_stop_failure_is_not_reported_as_success(self):
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'web_entry_stop') as entry,patch.object(m,'proxy_stop',side_effect=RuntimeError('proxy still running')) as proxy,patch.object(m.subprocess,'run',side_effect=AssertionError('Unit test attempted a real host process')),patch('builtins.print') as out:
   with self.assertRaisesRegex(RuntimeError,'proxy still running'):m.stop()
   entry.assert_called_once();proxy.assert_called_once()
   out.assert_not_called()
 def test_restore_requires_explicit_confirmation(self):
  with patch.object(m,'command') as command:
   with self.assertRaises(ValueError):m.restore()
   command.assert_not_called()
 def test_restore_refuses_live_vm(self):
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='started'),patch.object(m,'command') as command:
   with self.assertRaises(RuntimeError):m.restore(True)
   command.assert_not_called()
 def test_restore_missing_snapshot_never_mutates_disk(self):
  with patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'command',return_value=MagicMock(stdout='{"snapshots":[]}')) as command:
   with self.assertRaises(ValueError):m.restore(True)
   self.assertEqual(command.call_count,1)
 def test_restore_takes_safety_snapshot_before_rollback(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'command',return_value=MagicMock(stdout='{"snapshots":[{"name":"ready-original"}]}')) as command,patch('builtins.print'):
   m.restore(True)
   args=[c.args[0] for c in command.call_args_list]
   self.assertEqual(args[1][2:4],['snapshot','-c']);self.assertTrue(args[1][4].startswith('pre-restore-'))
   self.assertEqual(args[2][2:5],['snapshot','-a','ready-original'])
 def test_rejects_argument_injection_and_forward_bind_changes(self):
  for mutate in [lambda a:a.append('-netdev user,id=escape'),lambda a:a.__setitem__(0,a[0].replace('127.0.0.1:49224','0.0.0.0:49224')),lambda a:a.__setitem__(0,a[0].replace('ipv6=off','ipv6=on')),lambda a:a.__setitem__(0,a[0].replace('restrict=on','restrict=off'))]:
   c=m.expected_config_fixture();mutate(c['QEMU']['AdditionalArguments'])
   with self.assertRaises(ValueError):m.validate_config(c)
 def test_rejects_host_drive_and_relative_or_symlink_path_strings(self):
  for image in ['/Users/chenyinqi/.dsh','../../secret','seed.iso']:
   c=m.expected_config_fixture();c['Drive'][0]['ImageName']=image
   with self.assertRaises(ValueError):m.validate_config(c)
if __name__=='__main__':unittest.main()
