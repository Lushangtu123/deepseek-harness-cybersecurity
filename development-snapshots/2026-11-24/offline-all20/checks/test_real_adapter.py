from pathlib import Path
from hashlib import sha256
from contextlib import contextmanager
from unittest.mock import Mock,patch
from types import SimpleNamespace
import importlib.util,unittest,sys
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
host=load('real_adapter_host',R/'operator/run_vm.py')
@contextmanager
def no_queue_writes(*a,**kw):yield
class RealManagerRoute(unittest.TestCase):
 def test_real_manager_ssh_routes_once_without_network(self):
  vm=load('actual_vm_read',R/'vm_read.py');manager=vm.manager();body='print(0)\n';seen=[]
  def command(argv,**kwargs):
   seen.append((argv,kwargs));return SimpleNamespace(returncode=0,stdout='unit-no-network',stderr='')
  manager.command=command
  with patch.object(manager,'ssh_channel',no_queue_writes):
   result=manager.ssh('/usr/bin/python3 -I -B -',input=body,timeout=3000,phase='native-check')
  self.assertEqual(result.stdout,'unit-no-network');self.assertEqual(len(seen),1)
  argv,kw=seen[0];self.assertEqual(argv,host._expected_ssh_argv(manager));self.assertEqual(kw['input'],body);self.assertGreaterEqual(kw['timeout'],2820)
 def test_second_adapter_invocation_is_rejected(self):
  manager=SimpleNamespace(SETUP=Path('/unit-only/setup'));transfer=SimpleNamespace(receive_command=Mock(return_value=SimpleNamespace(returncode=0)))
  body='print(0)\n'
  with patch.object(host,'load',return_value=SimpleNamespace(manager=lambda:manager)):
   managed=host._manager('VM',transfer,sha256(body.encode()).hexdigest(),2820)
  argv=host._expected_ssh_argv(manager);managed.command(argv,timeout=3000,input=body)
  with self.assertRaises(ValueError):managed.command(argv,timeout=3000,input=body)
  self.assertEqual(transfer.receive_command.call_count,1)
if __name__=='__main__':unittest.main(verbosity=2)
