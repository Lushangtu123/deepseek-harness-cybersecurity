import hashlib, importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

spec=importlib.util.spec_from_file_location('recovery_input',Path(__file__).with_name('manage.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RecoveryInput(unittest.TestCase):
 def bundle(self,root):
  folder=root/'recoveries'/m.CURRENT_RECOVERY
  for name in ['host-tools','launch-agents']:(folder/name).mkdir(parents=True)
  helpers={};jobs={}
  for name in sorted(m.RECOVERY_HELPERS):
   data=('synthetic '+name).encode();(folder/'host-tools'/name).write_bytes(data);helpers[name]=hashlib.sha256(data).hexdigest()
  for label in [m.LABEL,m.WEB_LABEL]:
   data=b'synthetic launch';name=label+'.plist';(folder/'launch-agents'/name).write_bytes(data);jobs[name]=hashlib.sha256(data).hexdigest()
  proof={'vmUUID':m.UUID,'mode':'improved','recoveryName':m.CURRENT_RECOVERY,'files':{'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'a'*64}}
  raw=json.dumps(proof).encode();(folder/'guest-proof.json').write_bytes(raw)
  manifest={'vmUUID':m.UUID,'snapshot':m.CURRENT_RECOVERY,'createdAt':'2026-10-29T00:00:00Z','helpers':helpers,'launchAgents':jobs,'guestProofSha256':hashlib.sha256(raw).hexdigest()}
  (folder/'manifest.json').write_text(json.dumps(manifest))
  return folder,manifest

 def status(self,root,manifest,snapshot_text=None):
  actual={'mode':'improved','originalCapabilities':True,'configDir':'/home/purge/.dsh-improved','modeFile':'improved','filesChecked':1,'differentFiles':[]}
  with patch.object(m,'ROOT',root),patch.object(m,'validate'),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps(actual))),patch.object(m,'current_host_inventory',return_value=manifest['helpers']),patch.object(m,'current_launch_inventory',return_value=manifest['launchAgents']),patch.object(m,'image_command',return_value=MagicMock(stdout=snapshot_text if snapshot_text is not None else json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))):
   try:return m.deployment_status()
   except Exception as error:self.fail('Bad recovery data must not abort runtime observation: '+type(error).__name__)

 def test_malformed_manifest_shapes_only_invalidate_the_recovery(self):
  for value in [[],None,4,'bad',{'helpers':[]}]:
   with self.subTest(value=value),tempfile.TemporaryDirectory() as temp:
    root=Path(temp);folder,manifest=self.bundle(root);(folder/'manifest.json').write_text(json.dumps(value))
    result=self.status(root,manifest)
    self.assertEqual(result['mode'],'improved');self.assertTrue(result['originalCapabilities']);self.assertEqual(result['recovery']['state'],'invalid')

 def test_valid_bundle_still_performs_digest_validation(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);folder,_=self.bundle(root)
   with patch.object(m,'ROOT',root):
    self.assertEqual(m.verify_recovery_bundle(m.CURRENT_RECOVERY)[0],folder)
    (folder/'host-tools/web-entry.mjs').write_bytes(b'changed')
    with self.assertRaises(ValueError):m.verify_recovery_bundle(m.CURRENT_RECOVERY)

 def test_nonregular_bundle_inputs_are_rejected_without_waiting_for_a_writer(self):
  for relative in ['manifest.json','guest-proof.json','host-tools/web-entry.mjs']:
   with self.subTest(relative=relative),tempfile.TemporaryDirectory() as temp:
    root=Path(temp);folder,_=self.bundle(root);target=folder/relative;target.unlink();os.mkfifo(target,0o600)
    script="""import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('bounded_reader',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=Path(sys.argv[2])
try:m.verify_recovery_bundle(m.CURRENT_RECOVERY)
except ValueError:print('REJECTED')
else:raise SystemExit('Nonregular bundle accepted')
"""
    try:run=subprocess.run([sys.executable,'-B','-c',script,str(Path(m.__file__).resolve()),str(root)],capture_output=True,text=True,timeout=2)
    except subprocess.TimeoutExpired:self.fail('Bundle reader blocked on '+relative)
    self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(run.stdout.strip(),'REJECTED')

 def test_oversized_valid_metadata_and_helpers_are_rejected(self):
  for kind in ['manifest','proof','helper']:
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
    root=Path(temp);folder,manifest=self.bundle(root)
    if kind=='manifest':manifest['padding']='x'*(2*1024*1024+1)
    elif kind=='proof':
     data=json.dumps({'files':{},'padding':'x'*(2*1024*1024+1)}).encode();(folder/'guest-proof.json').write_bytes(data);manifest['guestProofSha256']=hashlib.sha256(data).hexdigest()
    else:
     target=folder/'host-tools/web-entry.mjs'
     with target.open('wb') as f:f.truncate(8*1024*1024+1)
     with target.open('rb') as f:manifest['helpers']['web-entry.mjs']=hashlib.file_digest(f,'sha256').hexdigest()
    (folder/'manifest.json').write_text(json.dumps(manifest))
    with patch.object(m,'ROOT',root),self.assertRaises(ValueError):m.verify_recovery_bundle(m.CURRENT_RECOVERY)

 def test_malformed_digest_matched_proof_only_invalidates_recovery(self):
  for proof in [[],None,{'files':[]}]:
   with self.subTest(proof=proof),tempfile.TemporaryDirectory() as temp:
    root=Path(temp);folder,manifest=self.bundle(root);raw=json.dumps(proof).encode();(folder/'guest-proof.json').write_bytes(raw);manifest['guestProofSha256']=hashlib.sha256(raw).hexdigest();(folder/'manifest.json').write_text(json.dumps(manifest))
    result=self.status(root,manifest);self.assertEqual(result['mode'],'improved');self.assertEqual(result['recovery']['state'],'invalid')

 def test_linked_recovery_directory_only_invalidates_recovery(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);folder,manifest=self.bundle(root);detached=root/'detached';folder.rename(detached);folder.symlink_to(detached,target_is_directory=True)
   result=self.status(root,manifest);self.assertEqual(result['mode'],'improved');self.assertEqual(result['recovery']['state'],'invalid')

 def test_malformed_disk_metadata_does_not_abort_runtime_identity(self):
  for raw in ['[]','4','{"snapshots":null}','{"snapshots":[null]}']:
   with self.subTest(raw=raw),tempfile.TemporaryDirectory() as temp:
    root=Path(temp);_,manifest=self.bundle(root);result=self.status(root,manifest,raw)
    self.assertEqual(result['mode'],'improved');self.assertEqual(result['recovery']['state'],'invalid')

 def test_creation_time_is_valid_and_cannot_expand_status_output(self):
  for value in ['x'*140000,'today','2026-99-29T00:00:00Z']:
   with self.subTest(value=value[:24]),tempfile.TemporaryDirectory() as temp:
    root=Path(temp);folder,manifest=self.bundle(root);manifest['createdAt']=value;(folder/'manifest.json').write_text(json.dumps(manifest));result=self.status(root,manifest)
    self.assertEqual(result['mode'],'improved');self.assertEqual(result['recovery']['state'],'invalid')

 def test_ancestor_replacement_cannot_redirect_a_pinned_bundle_read(self):
  import shutil
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);folder,_=self.bundle(root);outside=root/'outside';shutil.copytree(folder/'host-tools',outside)
   real_open=m.os.open;swapped=False
   def replace_before_open(path,flags,*args,**kwargs):
    nonlocal swapped
    if Path(path).name=='web-entry.mjs' and not swapped:
     swapped=True;(folder/'host-tools').rename(folder/'original-host-tools');(folder/'host-tools').symlink_to(outside,target_is_directory=True)
    fd=real_open(path,flags,*args,**kwargs)
    if Path(path).name=='web-entry.mjs' and os.fstat(fd).st_ino==(outside/'web-entry.mjs').stat().st_ino:
     os.close(fd);self.fail('Recovery read followed the replaced ancestor outside its pinned directory')
    return fd
   with patch.object(m,'ROOT',root),patch.object(m.os,'open',side_effect=replace_before_open):
    try:m.verify_recovery_bundle(m.CURRENT_RECOVERY)
    except (ValueError,OSError):pass
   self.assertTrue(swapped,'Ancestor replacement control did not fire')

 def helper_status_fixture(self,root):
  folder,manifest=self.bundle(root);target=folder/'host-tools/qemu-image.py'
  raw=('print('+repr(json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}],'changedHelper':False}))+')\n').encode();target.write_bytes(raw);manifest['helpers'][target.name]=hashlib.sha256(raw).hexdigest();(folder/'manifest.json').write_text(json.dumps(manifest))
  actual={'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','filesChecked':1,'differentFiles':[]}
  return folder,manifest,target,raw,actual

 def test_helper_replaced_after_bundle_check_is_not_executed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);folder,manifest,target,raw,actual=self.helper_status_fixture(root);verify=m.verify_recovery_bundle
   def swapped(name):
    result=verify(name);target.write_text("raise SystemExit('UNVERIFIED_HELPER_RAN')\n");return result
   with patch.object(m,'ROOT',root),patch.object(m,'validate'),patch.object(m,'verify_recovery_bundle',side_effect=swapped),patch.object(m,'current_host_inventory',return_value=manifest['helpers']),patch.object(m,'current_launch_inventory',return_value=manifest['launchAgents']),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps(actual))),patch.object(m,'command',wraps=m.command) as command:
    result=m.deployment_status();self.assertEqual(result['mode'],'improved');self.assertEqual(result['recovery']['state'],'invalid');self.assertEqual(command.call_count,0,'Changed helper must be rejected before starting Python')

 def test_helper_exec_uses_checked_bytes_even_if_original_path_changes(self):
  self.assertEqual(m.PYTHON,'/opt/homebrew/bin/python3','Production Mac interpreter policy changed')
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);folder,manifest,target,raw,actual=self.helper_status_fixture(root);command=m.command;outputs=[]
   def swap_before_exec(*args,**kwargs):
    self.assertEqual(args[0][:2],[sys.executable,'-']);self.assertEqual(kwargs.get('input'),raw.decode())
    target.write_text("raise SystemExit('UNVERIFIED_HELPER_RAN')\n");result=command(*args,**kwargs);outputs.append(json.loads(result.stdout));return result
   with patch.object(m,'ROOT',root),patch.object(m,'PYTHON',sys.executable),patch.object(m,'validate'),patch.object(m,'current_host_inventory',return_value=manifest['helpers']),patch.object(m,'current_launch_inventory',return_value=manifest['launchAgents']),patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps(actual))),patch.object(m,'command',side_effect=swap_before_exec):
    result=m.deployment_status();self.assertEqual(result['mode'],'improved')
   self.assertEqual(len(outputs),1,'Checked helper must actually execute');self.assertFalse(outputs[0]['changedHelper'])

 def test_apply_reads_all_checked_sources_before_the_first_target_write(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);folder,manifest=self.bundle(root);tools=root/'installed';tools.mkdir();home=root/'home';jobs=home/'Library/LaunchAgents';jobs.mkdir(parents=True)
   original=(folder/'host-tools/qemu-image.py').read_bytes();write=m.atomic_recovery_write;changed=False
   def replace_remaining_source(*args,**kwargs):
    nonlocal changed
    if not changed:changed=True;(folder/'host-tools/qemu-image.py').write_bytes(b'changed-after-first-write')
    return write(*args,**kwargs)
   with patch.object(m,'ROOT',root),patch.object(m,'TOOLS',tools),patch.object(Path,'home',return_value=home),patch.object(m,'atomic_recovery_write',side_effect=replace_remaining_source):
    try:m.apply_host_bundle(folder,manifest)
    except RuntimeError as error:self.fail('Recovery read a changed source after starting writes: '+str(error))
   self.assertTrue(changed);self.assertEqual((tools/'qemu-image.py').read_bytes(),original)

if __name__=='__main__':unittest.main()
