from pathlib import Path
from hashlib import sha256
import ast,importlib.util,json,unittest
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class IntegratedContract(unittest.TestCase):
 def test_guest_root_is_one_frozen_authority(self):
  want=json.loads((R/'START.json').read_bytes())['guestRoot']
  for file in ('consumer_vm.py','status_guest.py'):
   m=load('contract_'+file.replace('.','_'),R/'operator'/file)
   self.assertEqual(str(m.GUEST),want,file)
 def test_transport_requires_exact_argv_before_execute(self):
  m=load('contract_host',R/'operator/run_vm.py')
  self.assertTrue(callable(getattr(m,'validate_transport',None)),'missing actual-boundary argv/input/deadline validation')
 def test_full20_has_independent_byte_gate(self):
  m=load('contract_verifier',R/'operator/verify_delivery.py')
  self.assertTrue(callable(getattr(m,'verify_full20_bundle',None)),'consumer-only verification is insufficient')
 def test_batch_deadline_exceeds_all_groups(self):
  m=load('contract_batch',R/'operator/full20_batch.py')
  self.assertEqual(getattr(m,'BATCH_DEADLINE_SECONDS',None),2700)
  self.assertGreaterEqual(m.BATCH_DEADLINE_SECONDS,20*120+300)
 def test_candidate_and_baseline_byte_identity(self):
  for name in ('candidate','candidate/baseline'):
   p=R/name/'protocol-manifest.json';d=json.loads(p.read_bytes())
   for rel,h in d['files'].items():self.assertEqual(sha256((R/name/rel).read_bytes()).hexdigest(),h,rel)
if __name__=='__main__':unittest.main(verbosity=2)
