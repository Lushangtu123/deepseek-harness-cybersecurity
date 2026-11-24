from pathlib import Path
from hashlib import sha256
import importlib.util,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('transport_contract_run',R/'operator/run_vm.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class TransportContract(unittest.TestCase):
 def setUp(self):
  self.argv=['/usr/bin/ssh','-F','/dev/null','purge@127.0.0.1','/usr/bin/python3 -I -B -'];self.body='print(0)\n';self.digest=sha256(self.body.encode()).hexdigest()
  self.fn=getattr(m,'validate_transport',None);self.assertTrue(callable(self.fn),'transport boundary contract absent')
 def call(self,argv=None,timeout=3000,body=None,expected=None,digest=None):
  return self.fn(self.argv if argv is None else argv,timeout,self.body if body is None else body,expected_argv=self.argv if expected is None else expected,expected_input_sha256=self.digest if digest is None else digest,minimum_seconds=2820)
 def test_exact_accepts(self):self.assertIs(self.call(),True)
 def test_shell_wrapper_rejected(self):
  with self.assertRaises(ValueError):self.call(argv=['/bin/sh','-c',' '.join(self.argv)])
 def test_extra_option_rejected(self):
  with self.assertRaises(ValueError):self.call(argv=self.argv+['extra'])
 def test_reordered_option_rejected(self):
  with self.assertRaises(ValueError):self.call(argv=list(reversed(self.argv)))
 def test_remote_command_changed_rejected(self):
  with self.assertRaises(ValueError):self.call(argv=self.argv[:-1]+['python3 -'])
 def test_same_argv_changed_stdin_rejected(self):
  with self.assertRaises(ValueError):self.call(body=self.body+'# changed')
 def test_digest_changed_rejected(self):
  with self.assertRaises(ValueError):self.call(digest='0'*64)
 def test_short_timeout_rejected(self):
  with self.assertRaises(ValueError):self.call(timeout=2700)
 def test_invalid_timeout_rejected(self):
  for value in [True,False,float('inf'),float('nan'),-1,0,'3000']:
   with self.subTest(value=repr(value)),self.assertRaises(ValueError):self.call(timeout=value)
class ActualAdapter(unittest.TestCase):
 def run_boundary(self,mutation=None,timeout=3000):
  body='print(0)\n';fake=SimpleNamespace(SETUP=Path('/unit-only/setup'));transfer=SimpleNamespace(receive_command=Mock(return_value='accepted'))
  with patch.object(m,'load',return_value=SimpleNamespace(manager=lambda:fake)):
   managed=m._manager('VM',transfer,sha256(body.encode()).hexdigest(),2820)
  argv=m._expected_ssh_argv(fake)
  if mutation=='argv':argv=['/bin/sh','-c',' '.join(argv)]
  if mutation=='input':body+='changed'
  if mutation is None and timeout>=2820:
   self.assertEqual(managed.command(argv,timeout=timeout,input=body),'accepted');transfer.receive_command.assert_called_once()
  else:
   with self.assertRaises(ValueError):managed.command(argv,timeout=timeout,input=body)
   transfer.receive_command.assert_not_called()
 def test_actual_adapter_valid_forwards_once(self):self.run_boundary()
 def test_actual_adapter_wrapper_never_transfers(self):self.run_boundary('argv')
 def test_actual_adapter_changed_stdin_never_transfers(self):self.run_boundary('input')
 def test_actual_remaining_queue_budget_never_transfers_when_short(self):self.run_boundary(timeout=2800)
if __name__=='__main__':unittest.main(verbosity=2)
