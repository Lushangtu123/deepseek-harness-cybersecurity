from pathlib import Path
import hashlib,importlib.util,json,os,tempfile,unittest
script=Path(__file__).resolve().parent.parent/'scripts/restore_preflight.py'
class Preflight(unittest.TestCase):
 def setUp(self):
  self.assertTrue(script.is_file(),'Read-only restore preflight is missing')
  spec=importlib.util.spec_from_file_location('preflight_test',script);self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.home=Path(self.temp.name)/'purge';self.home.mkdir()
  self.environment={'system':'Linux','machine':'aarch64','user':'purge','javaAvailable':True,'dockerAvailable':True}
  self.inventory={'restoreTarget':{'system':'Linux','machine':'aarch64','user':'purge','home':str(self.home),'harnessVersion':'0.2.1-rc.3','codegraphVersion':'1.6.2','reverseDirectory':'reverse-skill-fixture','ghidraDirectory':'ghidra_12.1.4_PUBLIC','pluginRoot':'tools/imported-dsh-plugins-20261027T185822Z'},'programFiles':{'lib/index.js':hashlib.sha256(b'fixture').hexdigest()},'guestFiles':{},'toolchain':{'rea':{'npmVersion':'6.8.0'}},'plugins':[{'name':'dsh-context','version':'0.75.1'}]}
  self.put('tools/dsh-purge-personal-1.1.77-personal.1/lib/index.js','fixture')
  p=self.put('.config/harness-vm-mode','improved\n');self.inventory['guestFiles']['guest-home/.config/harness-vm-mode']={'sourceSha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  for relative,version in [('tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/package.json','0.2.1-rc.3'),('tools/rea-runtime/node_modules/rea-agents/package.json','6.8.0'),('tools/codegraph-1.6.2/node_modules/@colbymchenry/codegraph/package.json','1.6.2'),('tools/imported-dsh-plugins-20261027T185822Z/dsh-context/package.json','0.75.1')]:self.put(relative,json.dumps({'version':version}))
  self.put('.local/node/bin/node','fixture').chmod(0o755)
  for directory in ['tools/reverse-skill/reverse-skill-fixture','tools/ghidra_12.1.4_PUBLIC']:(self.home/directory).mkdir(parents=True)
  self.put('tools/reverse-skill/reverse-skill-fixture/AGENTS.md','fixture')
  self.put('tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless','fixture').chmod(0o755)
  self.inventory['executionRequirements']={name:0o700 for name in ['.local/bin/harness-vm-web','.local/bin/toolchain-versions','.local/bin/dsh','.local/bin/codegraph','.local/bin/reverse-case','.local/bin/reverse-route','.dsh/toolchain/pentagi-cli.py','.local/bin/kali-vm']}
  self.inventory['executionRequirements'].update({'.local/lib/harness-kali-tools/'+name:0o700 for name in ['nmap', 'nuclei', 'masscan', 'fscan', 'gogo', 'suo5', 'frpc', 'frps', 'chisel', 'ffuf', 'httpx', 'dnsx', 'subfinder', 'ksubdomain', 'impacket', 'curl', 'wget', 'dig', 'openssl', 'tcpdump', 'tshark', 'whatweb', 'nikto', 'sqlmap', 'file', 'strings']})
  for name,mode in self.inventory['executionRequirements'].items():
   p=self.put(name,'#!/bin/sh\nexit 0\n');p.chmod(mode);self.inventory['guestFiles']['guest-home/'+name]={'sourceSha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  self.secret='synthetic-local-credential-value'
  self.put('.dsh-improved/.credentials.yaml',json.dumps({'refs':{'DEEPSEEK_API_KEY':self.secret}})).chmod(0o600)
  self.put('.dsh/toolchain/pentagi-admin.json',json.dumps({'password':self.secret,'passwordChanged':True})).chmod(0o600)
  self.put('.dsh/toolchain/pentagi-connection.json',json.dumps({'token':self.secret})).chmod(0o600)
  self.put('.dsh/toolchain/pentagi/secrets.env','\n'.join(k+'='+self.secret for k in ['DEEPSEEK_API_KEY','COOKIE_SIGNING_SALT','PENTAGI_POSTGRES_PASSWORD'])).chmod(0o600)
 def put(self,name,value):
  p=self.home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value);return p
 def assess(self):return self.m.assess(self.home,self.inventory,self.environment)
 def test_complete_installation_is_checked_without_mutation_or_secret_output(self):
  before={str(p):p.read_bytes() for p in self.home.rglob('*') if p.is_file()};r=self.assess();self.assertTrue(r['ok'],r);self.assertTrue(r['readOnly']);self.assertFalse(r['automaticChanges']);self.assertEqual(r['runtimeChecks'],'not_run');self.assertNotIn(self.secret,json.dumps(r));self.assertEqual(before,{str(p):p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
 def test_changed_source_file_and_version_are_independently_reported(self):
  self.put('.config/harness-vm-mode','original');self.put('tools/codegraph-1.6.2/node_modules/@colbymchenry/codegraph/package.json',json.dumps({'version':'0.0.0'}));r=self.assess();self.assertFalse(r['ok']);self.assertGreaterEqual(sum(x['state']!='ok' for x in r['checks']),2)
 def test_missing_credentials_are_explicit_and_do_not_invent_validity(self):
  (self.home/'.dsh-improved/.credentials.yaml').unlink();r=self.assess();self.assertFalse(r['ok']);self.assertTrue(any(x['id']=='credential:deepseek' and x['state']=='missing' for x in r['checks']));self.assertNotIn(self.secret,json.dumps(r))
 def test_unsafe_inventory_path_is_rejected_without_accessing_it(self):
  self.inventory['guestFiles']['guest-home/../private']={'sourceSha256':'a'*64};r=self.assess();self.assertFalse(r['ok']);self.assertTrue(any(x['id']=='inventory' and x['state']=='invalid' for x in r['checks']))
 def test_symlink_source_is_unconfirmed_without_following_it(self):
  p=self.home/'.config/harness-vm-mode';p.unlink();outside=Path(self.temp.name)/'outside';outside.write_text('improved\n');p.symlink_to(outside);r=self.assess();self.assertFalse(r['ok']);self.assertTrue(any(x['state']=='unsafe' for x in r['checks']))
 def test_wrong_environment_stops_before_target_reads(self):
  self.environment['system']='Darwin';r=self.assess();self.assertFalse(r['ok']);self.assertEqual(len(r['checks']),1);self.assertEqual(r['checks'][0]['id'],'environment')
 def test_missing_expected_versions_and_empty_packages_are_invalid(self):
  del self.inventory['restoreTarget']['harnessVersion'];del self.inventory['restoreTarget']['codegraphVersion'];del self.inventory['toolchain']['rea']['npmVersion'];del self.inventory['plugins'][0]['version']
  for name in ['tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/package.json','tools/rea-runtime/node_modules/rea-agents/package.json','tools/codegraph-1.6.2/node_modules/@colbymchenry/codegraph/package.json','tools/imported-dsh-plugins-20261027T185822Z/dsh-context/package.json']:self.put(name,'{}')
  self.assertFalse(self.assess()['ok'])
 def test_empty_tool_directories_cannot_be_reported_installed(self):
  (self.home/'tools/reverse-skill/reverse-skill-fixture/AGENTS.md').unlink();(self.home/'tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless').unlink();self.assertFalse(self.assess()['ok'])
 def test_lost_execute_bit_is_a_failure_without_chmod_repair(self):
  p=self.home/'.local/bin/harness-vm-web';p.chmod(0o600);r=self.assess();self.assertFalse(r['ok']);self.assertEqual(p.stat().st_mode&0o777,0o600);self.assertTrue(any(x['id']=='mode:.local/bin/harness-vm-web' and x['state']!='ok' for x in r['checks']))
 def test_unexpected_broader_mode_is_reported_without_repair(self):
  p=self.home/'.local/bin/toolchain-versions';p.chmod(0o777);self.assertFalse(self.assess()['ok']);self.assertEqual(p.stat().st_mode&0o777,0o777)
 def test_missing_or_malformed_mode_inventory_cannot_pass(self):
  for value in [{},{'.local/bin/harness-vm-web':True}]:
   self.inventory['executionRequirements']=value;self.assertFalse(self.assess()['ok'])
if __name__=='__main__':unittest.main()
