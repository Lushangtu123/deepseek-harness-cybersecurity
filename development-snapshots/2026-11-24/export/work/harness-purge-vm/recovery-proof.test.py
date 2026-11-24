import hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
spec=importlib.util.spec_from_file_location('proof_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RecoveryProof(unittest.TestCase):
 def proof(self,name=None):return {'vmUUID':m.UUID,'mode':'improved','recoveryName':name or m.CURRENT_RECOVERY,'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'a'*64}}
 def host_bundle(self,folder):
  hashes={};jobs={}
  for section in ['host-tools','launch-agents']:(folder/section).mkdir()
  for name in sorted(m.RECOVERY_HELPERS):
   raw=('synthetic '+name).encode();(folder/'host-tools'/name).write_bytes(raw);hashes[name]=hashlib.sha256(raw).hexdigest()
  for label in [m.LABEL,m.WEB_LABEL]:
   raw=b'synthetic job';name=label+'.plist';(folder/'launch-agents'/name).write_bytes(raw);jobs[name]=hashlib.sha256(raw).hexdigest()
  return {'vmUUID':m.UUID,'helpers':hashes,'launchAgents':jobs}
 def bundle(self,root,name,proof):
  folder=root/'recoveries'/name;folder.mkdir(parents=True);data=self.host_bundle(folder);raw=json.dumps(proof).encode();(folder/'guest-proof.json').write_bytes(raw)
  data.update(snapshot=name,guestProofSha256=hashlib.sha256(raw).hexdigest(),createdAt='2026-10-29T00:00:00Z');(folder/'manifest.json').write_text(json.dumps(data));return folder
 def test_creation_archives_only_the_proof_bytes_it_validated(self):
  for replace in [False,True]:
   with self.subTest(replace=replace),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp).resolve();path=root/('recovery-input-'+m.CURRENT_RECOVERY+'.json');raw=json.dumps(self.proof()).encode();path.write_bytes(raw)
    swapped=False
    def copied(folder):
     nonlocal swapped
     data=self.host_bundle(folder)
     if replace:swapped=True;path.write_text(json.dumps({**self.proof(),'mode':'original','vmUUID':'synthetic-other-vm'}))
     return data
    with patch.object(m,'ROOT',root),patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'copy_host_bundle',side_effect=copied),patch.object(m,'image_command',return_value=MagicMock(stdout='{"snapshots":[]}')),patch('builtins.print'):m.create_current_recovery()
    self.assertEqual(swapped,replace);self.assertEqual((root/'recoveries'/m.CURRENT_RECOVERY/'guest-proof.json').read_bytes(),raw)
 def test_digest_matched_wrong_identity_mode_name_and_inventory_are_rejected(self):
  for change in [{'vmUUID':'synthetic-other-vm'},{'mode':'original'},{'recoveryName':'wrong-point'},{'files':[]},{'files':{}},{'files':{'client.js':'bad-digest'}}]:
   with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp).resolve();self.bundle(root,m.CURRENT_RECOVERY,{**self.proof(),**change})
    with patch.object(m,'ROOT',root),self.assertRaises(ValueError):m.verify_recovery_bundle(m.CURRENT_RECOVERY)
 def test_only_the_known_first_legacy_point_may_omit_its_recovery_name(self):
  for name in [m.REVIEWED_RECOVERIES[0],m.CURRENT_RECOVERY]:
   with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp).resolve();proof=self.proof(name);del proof['recoveryName'];self.bundle(root,name,proof)
    with patch.object(m,'ROOT',root):
     if name==m.REVIEWED_RECOVERIES[0]:self.assertEqual(m.verify_recovery_bundle(name)[0].name,name)
     else:
      with self.assertRaises(ValueError):m.verify_recovery_bundle(name)
 def test_malformed_prepared_proof_is_rejected_before_copy_or_snapshot_creation(self):
  for value in [[],None,{**self.proof(),'files':['bad']},{**self.proof(),'recoveryName':'other'}]:
   with self.subTest(value=value),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp).resolve();(root/('recovery-input-'+m.CURRENT_RECOVERY+'.json')).write_text(json.dumps(value))
    with patch.object(m,'ROOT',root),patch.object(m,'validate'),patch.object(m,'vm_status',return_value='stopped'),patch.object(m,'copy_host_bundle') as copy,patch.object(m,'image_command',return_value=MagicMock(stdout='{"snapshots":[]}')) as image:
     with self.assertRaises(ValueError):m.create_current_recovery()
     copy.assert_not_called();self.assertFalse(any(c.args[0][0]=='snapshot' for c in image.call_args_list))
if __name__=='__main__':unittest.main()
