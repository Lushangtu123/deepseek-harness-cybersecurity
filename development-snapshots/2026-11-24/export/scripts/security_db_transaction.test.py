import hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
import tempfile,unittest

class TransactionTests(unittest.TestCase):
 def module(self):
  p=Path(__file__).with_name('security_db_transaction.py');self.assertTrue(p.exists(),'Database transaction helper is missing');s=importlib.util.spec_from_file_location('db_transaction_fixture',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def fixture(self,folder):
  root=folder.resolve()/'assets';(root/'cache/db').mkdir(parents=True);old=b'A'*4096;new=b'B'*4096;oldmeta={'Version':2,'UpdatedAt':'2026-10-28T00:00:00Z','NextUpdate':'2026-10-29T00:00:00Z'};newmeta={'Version':2,'UpdatedAt':'2026-10-29T00:00:00Z','NextUpdate':'2026-10-30T00:00:00Z'}
  manifest={'schemaVersion':1,'tools':[],'database':{'fileSha256':hashlib.sha256(old).hexdigest(),'fileBytes':len(old),'metadata':oldmeta,'digest':'sha256:'+'a'*64}};(root/'images.json').write_text(json.dumps(manifest));(root/'cache/db/trivy.db').write_bytes(old);(root/'cache/db/metadata.json').write_text(json.dumps(oldmeta));stage=root/'staged';stage.mkdir();(stage/'trivy.db').write_bytes(new);(stage/'metadata.json').write_text(json.dumps(newmeta));identity={'fileSha256':hashlib.sha256(new).hexdigest(),'fileBytes':len(new),'metadata':newmeta,'digest':'sha256:'+'b'*64};return root,stage,identity,manifest,old
 def test_commit_preserves_backup_and_never_changes_tools(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as temp:
   root,stage,identity,manifest,old=self.fixture(Path(temp));calls=[];result=m.commit(root,stage,identity,check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:calls.append('start'),validate=lambda:True);self.assertTrue(result['changed']);self.assertEqual(calls,['stop','start']);self.assertEqual((root/'cache/db/trivy.db').read_bytes(),b'B'*4096);self.assertEqual((Path(result['backup'])/'db/trivy.db').read_bytes(),old);self.assertEqual(json.loads((root/'images.json').read_text())['tools'],manifest['tools']);self.assertFalse((root/'maintenance.json').exists())
 def test_active_scan_refuses_before_stopping_or_writing(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as temp:
   root,stage,identity,manifest,old=self.fixture(Path(temp));before=(root/'images.json').read_bytes()
   with self.assertRaises(RuntimeError):m.commit(root,stage,identity,check_idle=lambda:False,stop=lambda:self.fail('stopped active service'),start=lambda:None,validate=lambda:True)
   self.assertEqual((root/'images.json').read_bytes(),before);self.assertEqual((root/'cache/db/trivy.db').read_bytes(),old)
 def test_validation_failure_restores_exact_database_and_manifest(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as temp:
   root,stage,identity,manifest,old=self.fixture(Path(temp));before=(root/'images.json').read_bytes();calls=[]
   with self.assertRaises(RuntimeError):m.commit(root,stage,identity,check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:calls.append('start'),validate=lambda:False)
   self.assertEqual((root/'cache/db/trivy.db').read_bytes(),old);self.assertEqual((root/'images.json').read_bytes(),before);self.assertEqual(calls,['stop','start']);self.assertFalse((root/'maintenance.json').exists())
 def test_failed_start_rolls_back_then_restarts_old_service(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as temp:
   root,stage,identity,manifest,old=self.fixture(Path(temp));before=(root/'images.json').read_bytes();calls=[]
   def start():
    calls.append('start')
    if len(calls)==1:raise RuntimeError('new startup failed')
   with self.assertRaises(RuntimeError):m.commit(root,stage,identity,check_idle=lambda:True,stop=lambda:None,start=start,validate=lambda:True)
   self.assertEqual(calls,['start','start']);self.assertEqual((root/'images.json').read_bytes(),before);self.assertEqual((root/'cache/db/trivy.db').read_bytes(),old)
 def test_real_process_loss_after_database_install_can_recover_without_replaying_update(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as temp:
   root,stage,identity,manifest,old=self.fixture(Path(temp));before=(root/'images.json').read_bytes();module=Path(__file__).with_name('security_db_transaction.py')
   code="import importlib.util,json,os;from pathlib import Path\ns=importlib.util.spec_from_file_location('m',"+repr(str(module))+");m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nwrite=m.write_json\ndef interrupted(path,value):\n if value.get('phase')=='new-db-installed':os._exit(77)\n return write(path,value)\nm.write_json=interrupted\nm.commit(Path("+repr(str(root))+"),Path("+repr(str(stage))+"),"+repr(identity)+",check_idle=lambda:True,stop=lambda:None,start=lambda:None,validate=lambda:True)"
   result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,timeout=10);self.assertEqual(result.returncode,77,result.stderr);self.assertTrue((root/'maintenance.json').exists());self.assertEqual((root/'cache/db/trivy.db').read_bytes(),b'B'*4096);calls=[];recovered=m.recover(root,check_idle=lambda:True,stop=lambda:calls.append('stop'),start=lambda:calls.append('start'));self.assertTrue(recovered['recovered']);self.assertEqual(calls,['stop','start']);self.assertEqual((root/'images.json').read_bytes(),before);self.assertEqual((root/'cache/db/trivy.db').read_bytes(),old);self.assertFalse((root/'maintenance.json').exists())
 def test_recovery_refuses_active_scanner_without_service_or_file_changes(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as temp:
   root,stage,identity,manifest,old=self.fixture(Path(temp));before=(root/'images.json').read_bytes()
   # A recovery check must happen before attempting to stop an active scanner.
   with self.assertRaises(RuntimeError):m.recover(root,check_idle=lambda:False,stop=lambda:self.fail('stopped active service'),start=lambda:None)
   self.assertEqual((root/'images.json').read_bytes(),before);self.assertEqual((root/'cache/db/trivy.db').read_bytes(),old)
 def test_scan_detected_after_stop_restarts_with_original_bytes(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as temp:
   root,stage,identity,manifest,old=self.fixture(Path(temp));checks=iter([True,False]);calls=[];before=(root/'images.json').read_bytes()
   with self.assertRaises(RuntimeError):m.commit(root,stage,identity,check_idle=lambda:next(checks),stop=lambda:calls.append('stop'),start=lambda:calls.append('start'),validate=lambda:True)
   self.assertEqual((root/'images.json').read_bytes(),before);self.assertEqual((root/'cache/db/trivy.db').read_bytes(),old);self.assertEqual(calls,['stop','start'])

if __name__=='__main__':unittest.main()
