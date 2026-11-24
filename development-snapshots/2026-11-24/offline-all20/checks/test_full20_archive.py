"""Full archive contract tests with fabricated unit receipts, never VM acceptance evidence."""
from pathlib import Path
from unittest.mock import patch
import importlib.util,unittest,json,copy
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('full20_archive_fixture',R/'checks/full20_archive_fixture.py');m=load('full20_archive_gate',R/'operator/verify_delivery.py')
class Full20Archive(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.original,cls.expected,cls.final=f.make()
 def evaluate(self,change=None):
  blobs=dict(self.original);final=copy.deepcopy(self.final)
  if change:change(blobs,final)
  blobs['final.json']=f.j(final);delivery,raw=f.pack(blobs,self.expected,final)
  return m.verify_bundle(delivery,raw,self.expected)
 def test_complete_unit_contract(self):
  value=self.evaluate();self.assertTrue(value['allPassed']);self.assertEqual(value['suites'],20);self.assertEqual(value['formalTargets'],'0/16')
 def test_wrong_root(self):
  blobs=dict(self.original);delivery,raw=f.pack(blobs,self.expected,self.final);delivery['guestRoot']+='/other'
  with self.assertRaisesRegex(ValueError,'guest-root'):m.verify_bundle(delivery,raw,self.expected)
 def test_missing_raw_stdout_with_updated_archive_digest(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:b.pop(f.BASE+'/raw/consumer-12/stdout.bin'))
 def test_modified_raw_stdout_with_updated_member_map(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:b.__setitem__(f.BASE+'/raw/consumer-12/stdout.bin',b'changed'))
 def test_duplicated_group(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:v['groups'].__setitem__(1,v['groups'][0]))
 def test_missing_group(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:v['rows'].pop())
 def test_reordered_group(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:v['groups'].reverse())
 def test_cleanup_unknown(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:v['rows'][0].__setitem__('cleanupConfirmed',False))
 def test_missing_journal(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:b.pop('evidence/consumer-12/process.json'))
 def test_tampered_frozen_source(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:b.__setitem__('candidate/tools/resource_guard.py',b'changed'))
 def test_nonempty_resource_call_log(self):
  with self.assertRaises(ValueError):self.evaluate(lambda b,v:b.__setitem__('evidence/unexpected-resource-calls.log',b'unexpected'))
 def test_wrong_proof_count(self):
  def mutate(b,v):d=json.loads(b['candidate/proof.json']);d['passed']=20;d['total']=20;b['candidate/proof.json']=f.j(d)
  with self.assertRaises(ValueError):self.evaluate(mutate)
 def test_missing_closure_artifact(self):
  def mutate(b,v):d=json.loads(b['candidate/closure-manifest.json']);d['validatedArtifactMap'].pop();b['candidate/closure-manifest.json']=f.j(d)
  with self.assertRaises(ValueError):self.evaluate(mutate)
if __name__=='__main__':unittest.main(verbosity=2)
