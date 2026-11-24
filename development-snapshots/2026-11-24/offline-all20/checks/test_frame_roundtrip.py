"""Real local subprocess framing, never a VM/target execution."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import importlib.util,io,json,os,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class FrameRoundtrip(unittest.TestCase):
 def setUp(self):
  self.t=load('frame_real_roundtrip',R/'operator/transfer.py');self.tmp=tempfile.TemporaryDirectory(dir=R/'checks/tmp');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'evidence').mkdir()
 def receive(self,wire,**kwargs):
  p=self.root/'input-wire';p.write_bytes(wire)
  code='import sys;from pathlib import Path;sys.stdin.buffer.read();sys.stdout.buffer.write(Path('+repr(str(p))+').read_bytes())'
  return self.t.receive_command([sys.executable,'-I','-B','-c',code],input=b'unit-only',root=self.root,timeout=10,**kwargs)
 def wire(self,delivery):
  out=io.BytesIO();self.t.emit_frame(delivery,out);return out.getvalue()
 def test_header_between_one_and_two_mib_roundtrip(self):
  wire=self.wire({'padding':'x'*(1500*1024),'archiveBytesPayload':b'unit'});p=self.receive(wire)
  self.assertEqual(p.returncode,0);self.assertEqual((self.root/'evidence/VM-original-evidence.zip').read_bytes(),b'unit');self.assertEqual(len(json.loads(p.stdout)['padding']),1500*1024)
 def test_empty_diagnostic_return_roundtrip_and_host_rejects(self):
  d={'archiveBytesPayload':b'','archiveSha256':sha256(b'').hexdigest(),'members':{},'linksRecordedNotFollowed':[],'archiveComplete':False,'diagnosticArchiveComplete':False,'result':{'complete':False}}
  p=self.receive(self.wire(d));self.assertEqual(p.returncode,0);out=json.loads(p.stdout);self.assertFalse(out['archiveComplete']);self.assertEqual(out['archiveSha256'],sha256(b'').hexdigest())
  v=load('empty_full20_validator',R/'operator/verify_delivery.py')
  with self.assertRaisesRegex(ValueError,'full20:delivery-incomplete'):v.verify_full20_bundle(out,b'',{'full20':True})
 def test_over_two_mib_declared_header_rejected(self):
  with self.assertRaisesRegex(ValueError,'^declared header exceeds 2 MiB$'):self.receive(self.t.MAGIC+(2*1024**2+1).to_bytes(8,'big'))
 def test_truncated_large_header_rejected(self):
  wire=self.wire({'padding':'x'*(1500*1024)});cut=len(self.t.MAGIC)+8+100
  with self.assertRaisesRegex(ValueError,'^incomplete frame header$'):self.receive(wire[:cut])
 def test_body_digest_corruption_rejected(self):
  wire=self.wire({'archiveBytesPayload':b'unit'})
  with self.assertRaisesRegex(ValueError,'^archive digest mismatch$'):self.receive(wire[:-1]+b'X')
 def test_header_reserve_is_in_admission_formula(self):
  # Exact formula at current tree usage is conservative before any subprocess.
  self.receive(self.wire({'archiveBytesPayload':b'unit'}))
  admission=json.loads((self.root/'evidence/VM-transfer.json').read_bytes())['admission']
  self.assertEqual(admission['headerReserve'],2*1024**2+64)
  self.assertEqual(admission['stderrReserve'],self.t.E_RESERVE)
  self.assertEqual(admission['zmax'],(self.t.CAP-self.t.STOP-self.t.F_RESERVE)//2-admission['rootBytes']-self.t.H_RESERVE-self.t.E_RESERVE)
  # Also retain the over-budget no-launch check in a different fresh root.
  self.root=self.root/'capacity-failure';(self.root/'evidence').mkdir(parents=True)
  with patch.object(self.t,'_strict_usage',return_value=self.t.CAP-self.t.STOP),self.assertRaisesRegex(ValueError,'^admission: archive budget is not positive$'):self.receive(self.wire({'archiveBytesPayload':b'x'}))
if __name__=='__main__':unittest.main(verbosity=2)
