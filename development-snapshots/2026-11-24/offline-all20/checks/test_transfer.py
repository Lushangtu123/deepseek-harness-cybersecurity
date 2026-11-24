from pathlib import Path
from hashlib import sha256
import base64,importlib.util,io,json,os,sys,unittest
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
def module():
    p=R/'operator/transfer.py'
    if not p.exists():return None
    s=importlib.util.spec_from_file_location('transfer_subject',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
MAGIC=b'HARNESS-CONSUMER12/1\n'
def frame(raw=b'raw-zip-unit',change=None,tail=b''):
    head={'version':1,'delivery':{'unitOnly':True},'archiveBytes':len(raw),'archiveSha256':sha256(raw).hexdigest()}
    if change:change(head)
    data=json.dumps(head,separators=(',',':')).encode()
    return MAGIC+len(data).to_bytes(8,'big')+data+raw+tail
class Transfer(unittest.TestCase):
    def setUp(self):
        self.m=module();self.assertIsNotNone(self.m,'bounded framed receiver not implemented')
        self.root=R/'checks/tmp'/('transfer-'+os.urandom(5).hex());(self.root/'evidence').mkdir(parents=True)
    def command(self,wire,stderr=b''):
        code='import sys,base64;sys.stdin.buffer.read();sys.stdout.buffer.write(base64.b64decode('+repr(base64.b64encode(wire).decode())+'));sys.stdout.buffer.flush();sys.stderr.buffer.write(base64.b64decode('+repr(base64.b64encode(stderr).decode())+'))'
        return [sys.executable,'-I','-B','-c',code]
    def run_wire(self,wire,stderr=b'',**kw):return self.m.receive_command(self.command(wire,stderr),input=b'owned input',root=self.root,timeout=5,**kw)
    def test_original_body_is_saved_once(self):
        p=self.run_wire(frame());self.assertEqual(p.returncode,0);self.assertTrue(json.loads(p.stdout)['unitOnly'])
        self.assertEqual((self.root/'evidence/VM-original-evidence.zip').read_bytes(),b'raw-zip-unit')
        self.assertFalse((self.root/'evidence/VM-transport.stdout').exists())
    def test_wrong_digest_is_rejected(self):
        with self.assertRaises(Exception):self.run_wire(frame(change=lambda h:h.update(archiveSha256='0'*64)))
    def test_truncated_body_is_rejected(self):
        with self.assertRaises(Exception):self.run_wire(frame()[:-1])
    def test_trailing_byte_is_rejected(self):
        with self.assertRaises(Exception):self.run_wire(frame(tail=b'x'))
    def test_declared_archive_over_cap_rejected_before_body(self):
        with self.assertRaises(Exception):self.run_wire(frame(change=lambda h:h.update(archiveBytes=1025)),archive_limit=1024)
        p=self.root/'evidence/VM-original-evidence.zip';self.assertFalse(p.exists() and p.stat().st_size)
    def test_oversize_header_is_rejected(self):
        with self.assertRaises(Exception):self.run_wire(MAGIC+(1048577).to_bytes(8,'big'))
    def test_stderr_flood_is_bounded(self):
        with self.assertRaises(Exception):self.run_wire(frame(),stderr=b'x'*1048577)
        p=self.root/'evidence/VM-transport.stderr';self.assertLessEqual(p.stat().st_size if p.exists() else 0,1048576)
    def test_encoder_matches_wire_contract(self):
        out=io.BytesIO();self.m.emit_frame({'unitOnly':True,'archiveBytesPayload':b'raw-zip-unit'},out)
        data=out.getvalue();self.assertTrue(data.startswith(MAGIC));n=int.from_bytes(data[len(MAGIC):len(MAGIC)+8],'big');j=json.loads(data[len(MAGIC)+8:len(MAGIC)+8+n]);self.assertEqual(j['archiveSha256'],sha256(b'raw-zip-unit').hexdigest());self.assertEqual(data[-12:],b'raw-zip-unit')
    def test_invalid_prefix_is_retained_as_bounded_raw_evidence(self):
        with self.assertRaises(Exception):self.run_wire(b'INVALID-FRAME-UNIT')
        p=self.root/'evidence/VM-wire-header.bin'
        self.assertTrue(p.is_file(),'invalid raw prefix was discarded')
        self.assertEqual(p.read_bytes(),b'INVALID-FRAME-UNIT')
    def test_final_inventory_failure_never_leaves_success_receipt(self):
        original=self.m._strict_usage;receipt=self.root/'evidence/VM-transfer.json'
        def fail_after_success(root):
            try:saved=json.loads(receipt.read_bytes()) if receipt.exists() else {}
            except json.JSONDecodeError:saved={}
            if saved.get('transfer',{}).get('state')=='success':
                raise PermissionError('synthetic-final-inventory')
            return original(root)
        with patch.object(self.m,'_strict_usage',fail_after_success):
            try:self.run_wire(frame())
            except PermissionError:
                self.fail('post-success inventory failed after successful receipt was already published')
        self.assertEqual(json.loads(receipt.read_bytes())['transfer']['state'],'success')
    def test_budget_boundary_is_checked_before_write(self):
        used=self.m.CAP-self.m.STOP-1
        with patch.object(self.m,'_strict_usage',return_value=used),patch.object(self.m,'_free_bytes',return_value=self.m.FLOOR+100):
            self.m._check_budget(str(self.root),1)
            with self.assertRaises(ValueError):self.m._check_budget(str(self.root),2)
    def test_prepublication_inventory_error_cannot_pass(self):
        original=self.m._strict_usage;body=self.root/'evidence/VM-original-evidence.zip';receipt=self.root/'evidence/VM-transfer.json'
        def fail_at_final_scan(root):
            if body.exists() and body.stat().st_size==12 and not receipt.exists():raise PermissionError('synthetic-prepublication-inventory')
            return original(root)
        with patch.object(self.m,'_strict_usage',fail_at_final_scan),self.assertRaises(PermissionError):self.run_wire(frame())
        if receipt.exists():self.assertNotEqual(json.loads(receipt.read_bytes())['transfer']['state'],'success')
if __name__=='__main__':unittest.main(verbosity=2)
