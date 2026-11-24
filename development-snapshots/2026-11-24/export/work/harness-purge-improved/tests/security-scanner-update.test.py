from pathlib import Path
import hashlib,importlib.util,json,tempfile,unittest
SCRIPT=Path(__file__).resolve().parent.parent/'package/scripts/security-scanner-update.py'
class AdmissionTests(unittest.TestCase):
 def module(self):
  self.assertTrue(SCRIPT.is_file(),'Controlled scanner update entry is missing')
  spec=importlib.util.spec_from_file_location('scanner_update',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.VERIFIED_SEMGREP_PUBLISHER_PINS=frozenset({('sha256:'+'f'*64,'2.0.0')});return m
 def fixture(self,root):
  value={'schemaVersion':1,'tools':[{'tool':tool,'imageId':'sha256:'+letter*64,'imageRef':'personal-security/'+tool+'@sha256:'+letter*64,'version':'1.0.0'} for tool,letter in [('semgrep','a'),('trivy','b'),('zap','c')]],'database':{'unchanged':'fixture'},'rulesSha256':'d'*64};p=root/'images.json';p.write_text(json.dumps(value));request={'imageId':'sha256:'+'f'*64,'version':'2.0.0','expectedManifestSha256':hashlib.sha256(p.read_bytes()).hexdigest(),'confirm':True};return p,request
 def test_failed_fresh_parser_gate_preserves_original_manifest_and_never_stops_services(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p,request=self.fixture(root);before=p.read_bytes();calls=[]
   with self.assertRaises(m.UpdateError):m.apply_candidate(root,request,probe=lambda *args:{'parserReady':False,'controlsPassed':True},check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:calls.append('start'),validate=lambda:True)
   self.assertEqual(p.read_bytes(),before);self.assertEqual(calls,[]);self.assertFalse((root/'maintenance.json').exists());self.assertFalse((root/'scanner-backups').exists())
 def test_success_changes_only_semgrep_and_keeps_exact_backup(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p,request=self.fixture(root);before=p.read_bytes();calls=[]
   result=m.apply_candidate(root,request,probe=lambda image,version:{'parserReady':True,'controlsPassed':True,'imageId':image,'version':version},check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:calls.append('start'),validate=lambda:True)
   self.assertTrue(result['changed']);self.assertEqual(calls,['stop','start']);after=json.loads(p.read_bytes());old=json.loads(before);self.assertEqual(after['tools'][1:],old['tools'][1:]);self.assertEqual(after['database'],old['database']);self.assertEqual(after['tools'][0]['imageId'],request['imageId']);self.assertEqual((Path(result['backup'])/'before-manifest.json').read_bytes(),before);self.assertFalse((root/'maintenance.json').exists())
 def test_validation_failure_restores_manifest_and_restarts_original(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p,request=self.fixture(root);before=p.read_bytes();calls=[]
   with self.assertRaisesRegex(m.UpdateError,'restored'):m.apply_candidate(root,request,probe=lambda image,version:{'parserReady':True,'controlsPassed':True,'imageId':image,'version':version},check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:calls.append('start'),validate=lambda:False)
   self.assertEqual(p.read_bytes(),before);self.assertEqual(calls,['stop','start']);self.assertFalse((root/'maintenance.json').exists())
 def test_stale_missing_confirmation_busy_or_foreign_maintenance_never_probes(self):
  m=self.module()
  for defect in ['stale','confirm','image','version','busy','maintenance']:
   with self.subTest(defect=defect),tempfile.TemporaryDirectory() as d:
    root=Path(d).resolve();p,request=self.fixture(root);before=p.read_bytes();calls=[]
    if defect=='stale':request['expectedManifestSha256']='0'*64
    if defect=='confirm':request['confirm']=False
    if defect=='image':request['imageId']='semgrep:latest'
    if defect=='version':request['version']='--escape'
    if defect=='maintenance':(root/'maintenance.json').write_text('{}')
    with self.assertRaises(m.UpdateError):m.apply_candidate(root,request,probe=lambda *args:calls.append('probe'),check_idle=lambda:defect!='busy',stop=lambda:calls.append('stop'),start=lambda:calls.append('start'),validate=lambda:True)
    self.assertEqual(p.read_bytes(),before);self.assertEqual(calls,[])
 def test_interrupted_install_recovers_from_exact_journal_and_refuses_database_marker(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p,request=self.fixture(root);before=p.read_bytes();calls=[]
   def fail_start():raise RuntimeError('synthetic restart failure')
   with self.assertRaises(m.UpdateError):m.apply_candidate(root,request,probe=lambda image,version:{'parserReady':True,'controlsPassed':True,'imageId':image,'version':version},check_idle=lambda:True,stop=lambda:None,start=fail_start,validate=lambda:True)
   self.assertTrue((root/'maintenance.json').exists());result=m.recover_candidate(root,check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:calls.append('start'));self.assertTrue(result['recovered']);self.assertEqual(p.read_bytes(),before);self.assertEqual(calls,['stop','start']);self.assertFalse((root/'maintenance.json').exists())
   (root/'maintenance.json').write_text('{"kind":"database","backup":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}')
   with self.assertRaises(m.UpdateError):m.recover_candidate(root,check_idle=lambda:True,stop=lambda:calls.append('bad-stop'),start=lambda:None)
   self.assertNotIn('bad-stop',calls)
 def test_process_lock_prevents_second_writer_before_probe_and_releases_after_failure(self):
  import subprocess,sys,os
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p,request=self.fixture(root);before=p.read_bytes();first=subprocess.Popen([sys.executable,'-B','-c',"import fcntl,os,sys;fd=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600);fcntl.flock(fd,fcntl.LOCK_EX);print('locked',flush=True);sys.stdin.read()",str(root/'.db-update.lock')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
   try:
    self.assertEqual(first.stdout.readline().strip(),'locked');calls=[]
    with self.assertRaises(m.UpdateError):m.apply_candidate(root,request,probe=lambda *args:calls.append('probe'),check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:None,validate=lambda:True)
    self.assertEqual(calls,[]);self.assertEqual(p.read_bytes(),before)
   finally:first.communicate(timeout=5)
 def test_manifest_change_during_probe_and_restart_failure_preserve_recovery_truth(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p,request=self.fixture(root);calls=[]
   def probe(image,version):
    old=json.loads(p.read_text());old['external']='changed';p.write_text(json.dumps(old));return {'parserReady':True,'controlsPassed':True,'imageId':image,'version':version}
   with self.assertRaises(m.UpdateError):m.apply_candidate(root,request,probe=probe,check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:None,validate=lambda:True)
   self.assertEqual(calls,[]);self.assertEqual(json.loads(p.read_text())['external'],'changed');self.assertFalse((root/'maintenance.json').exists())
 def test_publisher_gate_rejects_missing_or_wrong_image_before_any_probe_or_write(self):
  for pinned in [frozenset(),frozenset({('sha256:'+'e'*64,'2.0.0')})]:
   m=self.module()
   m.VERIFIED_SEMGREP_PUBLISHER_PINS=pinned
   with tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();manifest_file,request=self.fixture(root);before=manifest_file.read_bytes()
    def unexpected(*args):self.fail('unverified candidate must not probe or mutate')
    with self.assertRaisesRegex(m.UpdateError,'发布者'):
     m.apply_candidate(root,request,probe=unexpected,check_idle=unexpected,stop=unexpected,start=unexpected,validate=unexpected)
    self.assertEqual(manifest_file.read_bytes(),before)
    self.assertEqual(list(root.iterdir()),[manifest_file])
if __name__=='__main__':unittest.main()
