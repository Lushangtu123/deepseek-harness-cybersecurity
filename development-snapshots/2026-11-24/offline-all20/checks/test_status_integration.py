from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import importlib.util,json,tempfile,unittest
from hashlib import sha256
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('status_integration',R/'operator/status_guest.py')
batch=load('status_integration_batch',R/'operator/full20_batch.py')
class StatusIntegration(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory(dir=R/'checks');self.addCleanup(t.cleanup);self.root=Path(t.name)
  (self.root/'candidate').mkdir();(self.root/'evidence/consumer-12').mkdir(parents=True)
  self.ident={'pid':2147483647,'pgid':2147483647,'groupLeader':True,'starttime':1,'bootId':'unit-only'}
  self.guard=SimpleNamespace(group_state=Mock(return_value={'state':'exited'}),process_state=Mock(return_value={'state':'exited'}),spawn_group_state=Mock(return_value={'state':'unknown'}))
  self.row={'suite':'consumer-12','pid':2147483647,'cleanupConfirmed':True}
  self.write_source('operator/full20_batch.py',(R/'operator/full20_batch.py').read_bytes())
  self.write_source('candidate/tools/resource_guard.py',b"def group_state(i):return {'state':'exited'}\ndef process_state(i):return {'state':'exited'}\ndef spawn_group_state(r):return {'state':'unknown','detail':'unit-other-role'}\n")
  self.expected={'guestRoot':str(self.root),'files':{n:{'sha256':sha256((self.root/n).read_bytes()).hexdigest(),'bytes':(self.root/n).stat().st_size} for n in ['operator/full20_batch.py','candidate/tools/resource_guard.py']}}
  self.final={'guestRoot':str(self.root),'attemptedSuites':['consumer-12'],'rows':[self.row],'groups':[{'suite':'consumer-12'}]}
  for name,v in [('final.json',self.final),('attempt.json',self.ident),('evidence/consumer-12/intent.json',{'suite':'consumer-12','identityRequired':True,'createdBeforeProcess':True,'cwd':str(self.root/'candidate')}),('evidence/consumer-12/process.json',{'pid':2147483647,'processGroup':2147483647,'originalPopenChild':True,'identity':self.ident}),('evidence/consumer-12/capture.json',self.row)]:self.write(name,v)
 def write_source(self,n,b):
  p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
 def write(self,n,v):
  p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
 def test_additional_inner_unknown_prevents_idle(self):
  self.write('candidate/other-sandbox/process-client-identity.json',{'role':'client','preflightId':'b'*32,'spawnState':'unknown'})
  with patch.object(batch,'_load_guard',return_value=self.guard):ok,detail=batch._safe_quiescence(self.root,{},['consumer-12'],[self.row])
  self.assertFalse(ok,detail)
  # Isolate the consumer-only path to expose omission of other inner roles.
  inner=[{'roleStates':{'client':{'state':'exited'},'observer':{'state':'exited'}},'stage':{'state':'absent'},'containers':{'allRemoved':True}}]
  with patch.object(m,'GUEST',self.root),patch.object(m.sys,'platform','linux'),patch.object(m.os,'getuid',return_value=1000),patch.object(m,'_root_check',return_value=(True,None)),patch.object(m,'_verify_expected',return_value=(True,[])),patch.object(m,'_load_guard',return_value=self.guard),patch.object(m,'_batch_lock',return_value={'released':True}),patch.object(m,'_inner',return_value=(inner,None)):
   result=m.main(self.expected)
  (R/'evidence/status-other-inner-counterexample.json').write_text(json.dumps({'unitOnly':True,'sharedResourceQuery':detail,'status':result},indent=2)+'\n')
  self.assertFalse(result['idleConfirmed'],result)
 def test_normal_same_producer_records_can_be_idle(self):
  inner=[{'roleStates':{'client':{'state':'exited'},'observer':{'state':'exited'}},'stage':{'state':'absent'},'containers':{'allRemoved':True}}]
  with patch.object(m,'GUEST',self.root),patch.object(m.sys,'platform','linux'),patch.object(m.os,'getuid',return_value=1000),patch.object(m,'_root_check',return_value=(True,None)),patch.object(m,'_verify_expected',return_value=(True,[])),patch.object(m,'_load_guard',return_value=self.guard),patch.object(m,'_batch_lock',return_value={'released':True}),patch.object(m,'_inner',return_value=(inner,None)):
   result=m.main(self.expected)
  self.assertTrue(result['idleConfirmed'],result)
 def test_missing_submitted_journal_does_not_query_identity(self):
  (self.root/'evidence/consumer-12/process.json').unlink()
  with patch.object(m,'GUEST',self.root):value=m._outer_groups(self.guard)
  self.assertEqual(value['state'],'unknown');self.guard.group_state.assert_not_called()
if __name__=='__main__':unittest.main(verbosity=2)
