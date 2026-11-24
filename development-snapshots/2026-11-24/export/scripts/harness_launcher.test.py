import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import shlex
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch


class LauncherTests(unittest.TestCase):
 def test_ssh_correlation_menu_never_starts_switches_or_replays_vm_work(self):
  manager=self.manager();manager.correlate_ssh_failure=Mock(return_value={'reference':'saved-reference','probeState':'read','recorded':True,'exactConnectionIdentified':False})
  _,_,opened,output,result=self.run_menu(['10','0'],manager)
  manager.correlate_ssh_failure.assert_called_once_with();manager.start.assert_not_called();manager.switch.assert_not_called();manager.stop.assert_not_called();opened.assert_not_called();self.assertEqual(result,0);self.assertIn('不重试原命令',output);self.assertIn('saved-reference',output)
 def test_database_menu_is_explicit_and_check_does_not_start_vm(self):
  module=self.load();self.assertTrue(callable(getattr(module,'database_update',None)),'Database maintenance entry is missing')
  with patch.object(module,'database_update',return_value=0) as action,patch.object(module,'load_manager') as load,patch('builtins.input',side_effect=['1']),contextlib.redirect_stdout(io.StringIO()):module.execute('9')
  action.assert_called_once_with(['--check']);load.assert_not_called()
 def test_database_update_cancel_does_not_call_updater(self):
  module=self.load();self.assertTrue(callable(getattr(module,'database_update',None)))
  with patch.object(module,'database_update') as action,patch.object(module,'load_manager') as load,patch('builtins.input',side_effect=['2','取消']),contextlib.redirect_stdout(io.StringIO()):module.execute('9')
  action.assert_not_called();load.assert_not_called()
 def test_database_update_and_recovery_require_distinct_confirmation(self):
  module=self.load();self.assertTrue(callable(getattr(module,'database_update',None)))
  for choice,word,args in [('2','更新',[]),('3','恢复',['--recover-last'])]:
   with self.subTest(choice=choice),patch.object(module,'database_update',return_value=0) as action,patch('builtins.input',side_effect=[choice,word]),contextlib.redirect_stdout(io.StringIO()):module.execute('9');action.assert_called_once_with(args)
 def load(self):
  path=Path(__file__).with_name('harness_launcher.py')
  self.assertTrue(path.is_file(),'Unified Harness menu is missing')
  spec=importlib.util.spec_from_file_location('launcher_fixture',path)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  return module

 def manager(self,mode='improved',enabled=False,vm='started'):
  state={'mode':mode,'modeFileMatches':True,'originalCapabilities':enabled,'recovery':{'name':'ready-merged-switch-20261029','state':'matches'}}
  return SimpleNamespace(ROOT=Path('/synthetic/Harness VM'),CURRENT_RECOVERY='ready-merged-switch-20261029',
   validate=Mock(),vm_status=Mock(return_value=vm),deployment_status=Mock(return_value=state),
   start=Mock(),switch=Mock(),stop=Mock(),restore=Mock(),
   original_capabilities=Mock(return_value={'enabled':True,'configured':True}),
   vm_operation=Mock(side_effect=lambda action:contextlib.nullcontext()))

 def run_menu(self,inputs,manager=None):
  module=self.load();manager=manager or self.manager();output=io.StringIO()
  with patch.object(module,'load_manager',return_value=manager) as load,patch.object(module,'open_harness') as opened,patch('builtins.input',side_effect=inputs),contextlib.redirect_stdout(output):
   result=module.main()
  return manager,load,opened,output.getvalue(),result

 def test_exit_does_not_load_or_start_vm(self):
  _,load,opened,_,result=self.run_menu(['0'])
  load.assert_not_called();opened.assert_not_called();self.assertEqual(result,0)

 def test_eof_exits_without_default_start(self):
  _,load,opened,_,result=self.run_menu([EOFError()])
  load.assert_not_called();opened.assert_not_called();self.assertEqual(result,0)

 def test_enter_opens_improved_without_restart_or_changing_enabled_flag(self):
  manager=self.manager(enabled=True)
  _,_,opened,_,_=self.run_menu(['','0'],manager)
  manager.start.assert_called_once_with(quiet=True);manager.switch.assert_not_called()
  manager.original_capabilities.assert_not_called();opened.assert_called_once_with(manager)
  manager.vm_operation.assert_called_once_with('switch')

 def test_failed_start_never_opens_or_exposes_captured_error(self):
  manager=self.manager();manager.start.side_effect=RuntimeError('private-log-should-not-appear')
  _,_,opened,output,_=self.run_menu(['1','0'],manager)
  opened.assert_not_called();manager.switch.assert_not_called()
  self.assertNotIn('private-log-should-not-appear',output);self.assertIn('未完成',output)

 def test_cancelled_enable_has_no_mode_side_effect(self):
  manager,_,opened,_,_=self.run_menu(['2','取消','0'])
  manager.start.assert_not_called();manager.original_capabilities.assert_not_called();opened.assert_not_called()

 def test_enable_uses_existing_controller_after_confirmation(self):
  manager,_,opened,_,_=self.run_menu(['2','启用','0'])
  manager.original_capabilities.assert_called_once_with('enable');opened.assert_called_once_with(manager)

 def test_disable_rejects_contradictory_receipt_without_open_or_retry(self):
  manager=self.manager(enabled=True);manager.original_capabilities.return_value={'enabled':False,'configured':True}
  _,_,opened,output,_=self.run_menu(['3','停用','0'],manager)
  manager.original_capabilities.assert_called_once_with('disable');opened.assert_not_called();self.assertIn('未确认',output)

 def test_disable_qualifies_configured_state_even_when_runtime_is_already_off(self):
  manager=self.manager();manager.original_capabilities.return_value={'enabled':False,'configured':False,'changed':False}
  self.run_menu(['3','停用','0'],manager)
  manager.switch.assert_not_called();manager.original_capabilities.assert_called_once_with('disable')

 def test_original_mode_remains_a_separate_choice(self):
  manager=self.manager();manager.deployment_status.side_effect=[{'mode':'improved','modeFileMatches':True},{'mode':'original','modeFileMatches':True}]
  _,_,opened,_,_=self.run_menu(['4','原版','0'],manager)
  manager.switch.assert_called_once_with('original',quiet=True);manager.original_capabilities.assert_not_called();opened.assert_called_once_with(manager)

 def test_stopped_status_does_not_use_guest_ssh_or_start(self):
  manager=self.manager(vm='stopped')
  _,_,opened,output,_=self.run_menu(['5','0'],manager)
  manager.deployment_status.assert_not_called();manager.start.assert_not_called();opened.assert_not_called();self.assertIn('已关闭',output)

 def test_cancelled_restore_is_non_destructive(self):
  manager,_,_,_,_=self.run_menu(['7','yes','0'])
  manager.restore.assert_not_called();manager.start.assert_not_called();manager.stop.assert_not_called()

 def test_restore_requires_exact_confirmation_and_uses_installed_recovery(self):
  manager=self.manager(vm='stopped')
  self.run_menu(['7','恢复','0'],manager)
  manager.restore.assert_called_once_with(confirmed=True,snapshot=manager.CURRENT_RECOVERY)
  manager.start.assert_not_called();manager.stop.assert_not_called()

 def test_running_vm_restore_does_not_force_shutdown(self):
  manager,_,_,output,_=self.run_menu(['7','恢复','0'])
  manager.restore.assert_not_called();manager.stop.assert_not_called();self.assertIn('先正常关闭',output)

 def test_shutdown_is_explicit_and_does_not_open_browser(self):
  manager,_,opened,_,_=self.run_menu(['6','关闭','0'])
  manager.stop.assert_called_once_with();opened.assert_not_called()

 def test_unconfirmed_runtime_does_not_open_or_change_flag(self):
  manager=self.manager();manager.deployment_status.return_value['modeFileMatches']=False
  _,_,opened,_,_=self.run_menu(['1','0'],manager)
  opened.assert_not_called();manager.original_capabilities.assert_not_called()

 def test_invalid_choice_does_not_invoke_manager(self):
  _,load,opened,_,_=self.run_menu(['not-a-choice','0'])
  load.assert_not_called();opened.assert_not_called()

 def test_profile_repair_cancel_does_not_load_manager(self):
  _,load,opened,output,_=self.run_menu(['8','取消','0'])
  load.assert_not_called();opened.assert_not_called();self.assertIn('已取消',output)

 def test_profile_repair_requires_confirmation_and_does_not_restart_or_open(self):
  manager=self.manager();manager.repair_profile=Mock(return_value={'ok':True,'profile':'web','changed':False,'wrote':False,'dryRun':False})
  self.run_menu(['8','修复','0'],manager)
  manager.repair_profile.assert_called_once_with(apply=True);manager.start.assert_not_called();manager.switch.assert_not_called()

 def test_command_resolves_support_script_from_folder_with_spaces(self):
  source=Path(__file__).resolve().parents[1]/'Harness.command'
  self.assertTrue(source.is_file(),'Single double-click entry is missing')
  canonical=source.read_text();self.assertIn('exec /opt/homebrew/bin/python3 ',canonical,'Production Mac interpreter policy changed')
  with tempfile.TemporaryDirectory(prefix='Harness launch ') as directory:
   root=Path(directory);(root/source.name).write_text(canonical.replace('/opt/homebrew/bin/python3',shlex.quote(sys.executable),1));(root/'scripts').mkdir()
   (root/'scripts/harness_launcher.py').write_text("print('RELATIVE_LAUNCH_OK')\n")
   result=subprocess.run(['/bin/sh',str(root/source.name)],cwd=tempfile.gettempdir(),capture_output=True,text=True,timeout=5)
   self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'RELATIVE_LAUNCH_OK')


import harness_launcher as launcher
class ScannerMenuTests(unittest.TestCase):
 def test_candidate_menu_cancellation_never_loads_manager(self):
  self.assertTrue(hasattr(launcher,'scanner_menu'),'Scanner menu is missing')
  with patch('builtins.input',side_effect=['0']),patch.object(launcher,'load_manager') as load:
   launcher.execute('11');load.assert_not_called()
 def test_rejected_candidate_never_reaches_apply(self):
  self.assertTrue(hasattr(launcher,'scanner_update'),'Scanner entry is missing')
  with patch('builtins.input',side_effect=['2','sha256:'+'a'*64,'1.0.0']),patch.object(launcher,'scanner_update',return_value=({'admitted':False,'changed':False},2)) as run:
   with self.assertRaises(launcher.LauncherNotice):launcher.execute('11')
   self.assertEqual(run.call_count,1);self.assertNotIn('apply',run.call_args.kwargs)
 def test_parser_pass_without_publisher_does_not_prompt_for_apply(self):
  with patch('builtins.input',side_effect=['2','sha256:'+'a'*64,'1.0.0']) as read,patch.object(launcher,'scanner_update',return_value=({'admitted':True,'publisherAdmission':'unverified','changed':False},0)) as run:
   with self.assertRaisesRegex(launcher.LauncherNotice,'发布者'):launcher.execute('11')
   self.assertEqual(read.call_count,3);run.assert_called_once()
class StorageMenuTests(unittest.TestCase):
 def test_storage_menu_only_calls_readonly_preview_without_vm_start(self):
  self.assertTrue(hasattr(launcher,'storage_preview'),'Storage preview menu missing')
  with patch.object(launcher,'storage_preview',return_value=0) as preview,patch.object(launcher,'load_manager') as load:launcher.execute('12');preview.assert_called_once_with();load.assert_not_called()
if __name__=='__main__':unittest.main()
