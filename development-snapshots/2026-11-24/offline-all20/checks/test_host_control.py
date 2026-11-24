from pathlib import Path
from unittest.mock import patch,Mock
from types import SimpleNamespace
from hashlib import sha256
import importlib.util,tempfile,json,unittest
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('host_control',R/'operator/run_vm.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class HostControl(unittest.TestCase):
 def test_start_candidate_pin_required(self):
  with tempfile.TemporaryDirectory(dir=R/'checks') as t:
   r=Path(t);(r/'START.json').write_text(json.dumps({'guestRoot':str(m.FROZEN_GUEST),'candidateManifestSha256':'0'*64}));(r/'payload.json').write_bytes(b'{}')
   packet={'guestRoot':str(m.FROZEN_GUEST),'caseIds':[],'sourceManifestSha256':'1'*64,'files':{}}
   expected=dict(packet,payloadSha256=sha256(b'{}').hexdigest())
   with self.assertRaises(ValueError):m.validate_payload(packet,expected,r)
 def test_unknown_status_exit_is_three(self):
  packet={};expected={}
  with patch.object(m,'_action',return_value='status'),patch.object(m,'_read_json',side_effect=[packet,expected]),patch.object(m,'validate_payload'),patch.object(m,'_admission',return_value={}),patch.object(m,'load',return_value=SimpleNamespace()),patch.object(m,'_status_query',return_value={'kind':'guest-readonly-status','guestRoot':str(m.FROZEN_GUEST),'idleConfirmed':False}):
   self.assertEqual(m.main(),3)
 def test_ssh_exception_not_marked_returned(self):
  captured={};manager=SimpleNamespace(ssh=Mock(side_effect=TimeoutError('unit-unknown')))
  packet={'guestRoot':str(m.FROZEN_GUEST)};expected={}
  def recording(n,v,**kw):captured[n]=v
  with patch.object(m,'_action',return_value='run'),patch.object(m,'_read_json',side_effect=[packet,expected]),patch.object(m,'validate_payload'),patch.object(m,'_admission',return_value={'reviewReceiptSha256':'a'*64}),patch.object(m,'load',return_value=SimpleNamespace()),patch.object(m,'_build_run_remote',return_value=('unit-only',b'unit-only')),patch.object(m,'record',side_effect=recording),patch.object(m,'_manager',return_value=manager),patch.object(m,'_status_query',return_value={'idleConfirmed':False}):
   self.assertEqual(m.main(),3)
  self.assertFalse(captured['VM-acceptance.json']['transportReturned'])
if __name__=='__main__':unittest.main(verbosity=2)
