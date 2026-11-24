"""Controller lifecycle checks use synthetic backend, never Mac Docker."""
from pathlib import Path
import importlib.util,json,sys,unittest
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('oldtests',HERE/'reviewer_snapshot.test.py');old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
sys.path.insert(0,str(HERE.parent/'work/harness-purge-improved/package/scripts'));import eval_evidence_batch as batch
class ControllerTest(old.SnapshotTest):
 def fixture(self):
  snap,root,manifest,scan=self.execution_fixture();(root/'safe.py').write_text('eval(value)\n');raw=(root/'safe.py').read_bytes();inv=batch.location_inventory({'safe.py':raw.decode()});inv['runtimePython']='3.12.15'
  location={'version':1,'snapshotSha256':self.api.digest(snap),'imageId':old.IMAGE,'uid':self.api.os.geteuid(),'inventory':inv}
  manifest.write_text(json.dumps({'files':{'safe.py':batch.sha256(raw).hexdigest()},'scanSha256':batch.sha256(scan.read_bytes()).hexdigest(),'locationBinding':location}))
  spec=importlib.util.spec_from_file_location('vs',HERE/'verifier_snapshot.py');vs=importlib.util.module_from_spec(spec);spec.loader.exec_module(vs)
  deps=self.root/'deps';deps.mkdir();contract={'version':1,'path':'safe.py','entry':{'kind':'function','name':'route','parameter':'value'},'inputContract':'untrusted-data-only'}
  lock={'version':1,'packages':[],'files':{}}
  vs.trusted_dependency_lock=lambda:lock
  self.api.verifier_module=lambda:vs
  ver=vs.freeze(self.bundle,self.api.digest(snap),deps,lock,[contract],self.root/'verifier')
  request={'version':1,'contract':contract,'point':inv['files']['safe.py']['points'][0],'challenge':'c'*64};path=self.root/'request.json';path.write_text(json.dumps(request));return ver,root,manifest,scan,path,request
 def test_verify_uses_owned_lifecycle_policy_and_returns_original_on_recover(self):
  ver,root,manifest,scan,path,request=self.fixture();backend=old.Backend();report={'version':1,'operation':'verify-execution','decision':'unknown','reason':'synthetic-not-a-runtime-proof','pointId':request['point']['id'],'sourceSha256':request['point']['sourceSha256'],'point':request['point'],'contractSha256':self.api.digest(request['contract']),'runtimePython':'3.12.15','challengeSha256':self.api.sha256(request['challenge'].encode()).hexdigest(),'runs':[],'proof':None}
  backend.report=json.dumps(report).encode();value=self.api.verify_execution(self.root/'verifier',self.api.digest(ver),root,manifest,scan,path,'d'*64,'e'*64,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
  receipt=value['verificationExecution'];self.assertEqual((receipt['version'],receipt['operation']),(1,'verify-execution'));self.assertEqual(receipt['verifierSha256'],self.api.digest(ver));self.assertEqual(value['verificationArtifact']['requestJson'],path.read_bytes().decode())
  for x in ['512m','64','python_execution_verify.py']:self.assertTrue(any(x in v for v in backend.create_args))
  self.assertEqual(self.api.recover(Path(value['attemptDirectory']))['result'],value)
 def test_unfrozen_contract_rejected_before_reservation_or_engine(self):
  ver,root,manifest,scan,path,request=self.fixture();request['contract']['entry']['name']='changed';path.write_text(json.dumps(request));backend=old.Backend()
  with self.assertRaises(ValueError):self.api.verify_execution(self.root/'verifier',self.api.digest(ver),root,manifest,scan,path,'d'*64,'e'*64,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
  self.assertEqual(backend.calls,[]);self.assertFalse((self.root/'attempts').exists())
for n in list(old.SnapshotTest.__dict__):
 if n.startswith('test_'):setattr(ControllerTest,n,None)
if __name__=='__main__':unittest.main()
