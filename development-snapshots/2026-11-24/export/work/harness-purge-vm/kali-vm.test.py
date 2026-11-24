import importlib.util,shlex,tempfile,unittest,re,os
from contextlib import chdir
from unittest.mock import patch
from pathlib import Path

class KaliClient(unittest.TestCase):
 def module(self):
  path=Path(__file__).with_name('kali-vm.py')
  self.assertTrue(path.is_file(),'Dedicated Kali client missing')
  spec=importlib.util.spec_from_file_location('kali_client',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 def test_exec_preserves_remote_argument_boundaries(self):
  mod=self.module();arguments=['printf','%s\n','a b','$(touch /tmp/unwanted)','; exit 42','']
  argv=mod.ssh_argv(['exec','--',*arguments],Path('/home/purge'))
  self.assertEqual(argv[:6],['/usr/bin/ssh','-F','/home/purge/.config/harness-kali/ssh_config','--','kali-lab',shlex.join(arguments)])
  self.assertEqual(len(argv),6)
 def test_shell_uses_fixed_target_and_no_implicit_privilege(self):
  mod=self.module();self.assertEqual(mod.ssh_argv(['shell'],Path('/home/purge')),['/usr/bin/ssh','-F','/home/purge/.config/harness-kali/ssh_config','--','kali-lab'])
  for arguments in [[],['exec'],['exec','--'],['shell','root'],['-o','User=root'],['anything']]:
   with self.subTest(arguments=arguments),self.assertRaises(ValueError):mod.ssh_argv(arguments,Path('/home/purge'))
 def test_status_is_fixed_readonly_guest_probe(self):
  mod=self.module();argv=mod.ssh_argv(['status'],Path('/home/purge'))
  self.assertEqual(argv[:5],['/usr/bin/ssh','-F','/home/purge/.config/harness-kali/ssh_config','--','kali-lab'])
  remote=shlex.split(argv[-1]);self.assertEqual(remote[:2],['python3','-c'])
  with tempfile.TemporaryDirectory() as directory:
   # The fixed status program only reads OS identity; compile catches malformed quoting.
   compile(remote[2],'<kali-status>','exec')
  self.assertNotIn('sudo',remote[2]);self.assertNotIn('subprocess',remote[2])

 def test_inventory_is_readonly_catalog_discovery_and_tool_arguments_stay_literal(self):
  mod=self.module();argv=mod.ssh_argv(['inventory'],Path('/home/purge'));remote=shlex.split(argv[-1]);self.assertEqual(remote[:2],['python3','-c']);compile(remote[2],'<inventory>','exec');self.assertIn('shutil',remote[2]);self.assertNotIn('sudo',remote[2])
  argv=mod.ssh_argv(['tool','nmap','--version','x; false','$(touch bad)'],Path('/home/purge'));remote=shlex.split(argv[-1]);self.assertEqual(remote[:2],['python3','-c']);self.assertEqual(remote[3:],['nmap','--version','x; false','$(touch bad)'])
  for value in [['tool','unknown'],['tool','../nmap'],['tool']]:
   with self.assertRaises(ValueError):mod.ssh_argv(value,Path('/home/purge'))

 def test_tool_discovery_includes_the_kali_users_private_install_directory(self):
  mod=self.module()
  with tempfile.TemporaryDirectory() as directory:
   home=Path(directory);binary=home/'.local/bin/fscan';binary.parent.mkdir(parents=True);binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o700)
   with patch.dict(os.environ,{'HOME':str(home),'PATH':''}):
    scope={};exec(mod.DISCOVERY_SOURCE,scope);self.assertEqual(scope['locate']('fscan'),str(binary))
 def test_network_and_file_inspection_catalogs_match_across_cli_and_plugin(self):
  mod=self.module();expected={'curl','wget','dig','openssl','tcpdump','tshark','whatweb','nikto','sqlmap','file','strings'}
  self.assertTrue(expected.issubset(mod.TOOL_NAMES),'Additional installed Kali commands are not exposed')
  base=Path(__file__).resolve().parent.parent/'harness-purge-improved/package/lib/redteam'
  source=(base/'personal-kali-environment.mjs').read_text();ids=re.search(r'KALI_TOOL_IDS = Object.freeze\((\[.*?\])\)',source).group(1);self.assertEqual(set(re.findall(r"'([^']+)'",ids)),set(mod.TOOL_NAMES))
  source=(base/'platform-config.js').read_text().split('export const TOOL_CATALOG = [',1)[1].split('const EMPTY',1)[0];self.assertEqual(set(re.findall(r"id:\s*'([^']+)'",source)),set(mod.TOOL_NAMES))

 def test_empty_or_relative_path_does_not_shadow_verified_user_bin_from_current_directory(self):
  mod=self.module()
  with tempfile.TemporaryDirectory() as directory:
   home=Path(directory)/'home';candidate=home/'.local/bin/fscan';candidate.parent.mkdir(parents=True);candidate.write_text('user-bin');candidate.chmod(0o700)
   cwd=Path(directory)/'work';cwd.mkdir();impostor=cwd/'fscan';impostor.write_text('cwd-impostor');impostor.chmod(0o700)
   for path in ['',':','.:relative']:
    with chdir(cwd),patch.dict(os.environ,{'HOME':str(home),'PATH':path}):
     scope={};exec(mod.DISCOVERY_SOURCE,scope);self.assertEqual(scope['locate']('fscan'),str(candidate))

if __name__=='__main__':unittest.main()
