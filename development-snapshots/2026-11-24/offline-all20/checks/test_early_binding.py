"""Unit-only binding admission controls. No SSH or guest-side resources."""
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import base64
import importlib.util
import json
import shutil
import tempfile
import unittest

R = Path(__file__).resolve().parents[1]


def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m);return m


class EarlyBinding(unittest.TestCase):
    def packet(self):
        guest=load('early_guest',R/'operator/consumer_vm.py')
        manifest=json.loads((R/'candidate/protocol-manifest.json').read_bytes())
        baseline=json.loads((R/'candidate/baseline/protocol-manifest.json').read_bytes())
        names={'candidate/'+n for n in manifest['files']} | {'candidate/protocol-manifest.json'}
        names|={'candidate/baseline/'+n for n in baseline['files']} | {'candidate/baseline/protocol-manifest.json'}
        names|=set(guest.OPERATOR_FILES)|set(guest.EXTRA_FILES)
        rows={}
        for n in names:
            raw=(R/n).read_bytes();rows[n]={'bytes':base64.b64encode(raw).decode(),'sha256':sha256(raw).hexdigest()}
        return guest,{'guestRoot':str(guest.GUEST),'caseIds':list(guest.CONSUMER_CASE_IDS),
                      'sourceManifestSha256':sha256((R/'candidate/protocol-manifest.json').read_bytes()).hexdigest(),
                      'files':rows,'unitOnly':True}

    def test_guest_rejects_wrong_registry_before_mkdir(self):
        guest,packet=self.packet()
        self.assertIsInstance(guest._validate_packet(packet),tuple)
        registry=json.loads((R/'operator/suite-plan.json').read_bytes());registry['sourceManifestSha256']='0'*64
        raw=json.dumps(registry).encode();packet['files']['operator/suite-plan.json']={
            'bytes':base64.b64encode(raw).decode(),'sha256':sha256(raw).hexdigest()}
        with patch.object(Path,'mkdir',side_effect=AssertionError('resource mkdir forbidden')) as mkdir:
            with self.assertRaises(ValueError): guest._validate_packet(packet)
        mkdir.assert_not_called()

    def test_host_rejects_binding_before_intent_or_ssh(self):
        host=load('early_host',R/'operator/run_vm.py');guest,packet=self.packet()
        # Only the unit's isolated temporary admission accepts the bad source label.
        packet['sourceManifestSha256']='0'*64
        with tempfile.TemporaryDirectory(dir=R/'checks') as tmp:
            root=Path(tmp);(root/'evidence').mkdir()
            for n in packet['files']:
                target=root/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(R/n,target)
            shutil.copy2(R/'operator/run_vm.py',root/'operator/run_vm.py')
            shutil.copy2(R/'operator/verify_delivery.py',root/'operator/verify_delivery.py')
            shutil.copy2(R/'vm_read.py',root/'vm_read.py')
            receipt=root/'unit-review.json';receipt.write_text('{"unitOnly":true}')
            for n,v in [('payload.json',packet),('expected-cases.json',{}),('START.json',{}),
                        ('evidence/payload-manifest.json',{})]:
                (root/n).write_text(json.dumps(v))
            files={p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest()
                   for p in root.rglob('*') if p.is_file()}
            admission={'accepted':True,'unitOnly':True,'files':files,'reviewReceipt':'unit-review.json',
                       'reviewReceiptSha256':sha256(receipt.read_bytes()).hexdigest()}
            (root/'source-admission.json').write_text(json.dumps(admission))
            with patch.object(host,'R',root),patch.object(host,'_action',return_value='run'), \
                 patch.object(host,'validate_payload',return_value=None), \
                 patch.object(host,'_manager',side_effect=AssertionError('SSH forbidden')) as manager, \
                 patch.object(host,'record',side_effect=AssertionError('intent forbidden')) as record:
                positive=dict(packet,sourceManifestSha256=sha256((R/'candidate/protocol-manifest.json').read_bytes()).hexdigest())
                self.assertEqual(host._admission(positive,{}),admission)
                with self.assertRaises(ValueError): host.main()
            manager.assert_not_called();record.assert_not_called()
            self.assertFalse((root/'evidence/VM-submission-intent.json').exists())


if __name__=='__main__':unittest.main(verbosity=2)
