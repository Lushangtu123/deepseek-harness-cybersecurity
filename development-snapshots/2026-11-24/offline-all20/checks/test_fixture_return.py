"""Codex independent RED/GREEN controls; no real VM, Docker or target."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from hashlib import sha256
import importlib.util, io, json, os, stat, sys, tempfile, unittest
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'candidate/checks'))
sys.path.insert(0,str(R/'checks'))
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('closure_fixture',R/'candidate/checks/run_unified_recovery_checks.py')
t=load('closure_transfer',R/'operator/transfer.py')
c=load('closure_consumer',R/'operator/consumer_vm.py')
class FixtureReturn(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=R/'checks/tmp');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.runner=SimpleNamespace(ROOT=self.root,PREPARE=self.root,RUNS=self.root,STATE=self.root,_PREFLIGHT_RESULT=None,release_batch_lock=lambda:None)
 def workspace(self):
  with patch.object(f,'TMP',self.root):return f.Workspace(self.runner,'b8-unit-')
 def track(self,w,p):
  self.assertTrue(callable(getattr(w,'track_fixture_link',None)),'fixture-owned link registration missing');w.track_fixture_link(p)
 def test_owned_link_removed_after_assertion_without_follow(self):
  w=self.workspace();target=w.prepare/'real-plans';target.mkdir();target.chmod(0o500);p=w.prepare/'plans';p.symlink_to(target,target_is_directory=True);self.track(w,p)
  self.assertTrue(p.is_symlink(),'recovery assertion needs retained link')
  seen=[]
  with patch.object(f.regression_lib,'retire_sandbox',side_effect=lambda root:seen.append(not os.path.lexists(p)) or True):w.close()
  self.assertEqual(seen,[True]);self.assertFalse(os.path.lexists(p))
 def test_untracked_link_not_followed_or_removed(self):
  w=self.workspace();target=self.root/'external';target.mkdir();target.chmod(0o500);p=w.prepare/'plans';p.symlink_to(target,target_is_directory=True)
  with patch.object(f.regression_lib,'retire_sandbox',return_value=False),self.assertRaises(Exception):w.close()
  self.assertTrue(p.is_symlink());self.assertEqual(stat.S_IMODE(target.lstat().st_mode),0o500)
 def test_replacement_link_retained(self):
  w=self.workspace();a=w.prepare/'a';a.mkdir();p=w.prepare/'plans';p.symlink_to(a);self.track(w,p)
  p.unlink();p.symlink_to(self.root/'not-owned')
  with patch.object(f.regression_lib,'retire_sandbox',return_value=False),self.assertRaises(Exception):w.close()
  self.assertTrue(p.is_symlink())
 def test_changed_parent_retained(self):
  w=self.workspace();a=w.prepare/'a';a.mkdir();p=w.prepare/'plans';p.symlink_to(a);self.track(w,p)
  w.prepare.rename(w.root/'old-prepare');w.prepare.mkdir();p.symlink_to(self.root/'external')
  with patch.object(f.regression_lib,'retire_sandbox',return_value=False),self.assertRaises(Exception):w.close()
  self.assertTrue(p.is_symlink())
 def test_lstat_error_fails_close(self):
  w=self.workspace();p=w.prepare/'plans';p.symlink_to(w.prepare/'missing');self.track(w,p)
  original=f.os.lstat
  def failure(path,*args,**kw):
   if os.fspath(path)==str(p):raise PermissionError('unit-lstat-unknown')
   return original(path,*args,**kw)
  with patch.object(f.os,'lstat',side_effect=failure),patch.object(f.regression_lib,'retire_sandbox',return_value=False),self.assertRaises(Exception):w.close()
  self.assertTrue(p.is_symlink())
 def test_controller_exception_empty_delivery_is_canonical(self):
  with patch.object(c,'_validate_packet',side_effect=ValueError('unit-pre-stage')):d=c.main({})
  self.assertEqual(d.get('archiveBytesPayload'),b'');self.assertEqual(d.get('archiveSha256'),sha256(b'').hexdigest())
  self.assertEqual(d.get('members'),{});self.assertEqual(d.get('linksRecordedNotFollowed'),[]);self.assertFalse(d['archiveComplete'])
  out=io.BytesIO();t.emit_frame(d,out);self.assertGreater(len(out.getvalue()),len(t.MAGIC))
 def test_controller_resource_unknown_empty_frame(self):
  j=load('closure_required_journal',R/'checks/test_required_journal.py');case=j.RequiredJournal('test_missing_row_after_intent_blocks_controller_collection');case.setUp()
  try:d,collector=case.controller('no-row')
  finally:case.doCleanups()
  collector.assert_not_called();self.assertEqual(d.get('archiveBytesPayload'),b'');self.assertEqual(d.get('archiveSha256'),sha256(b'').hexdigest());self.assertEqual(d.get('members'),{});self.assertEqual(d.get('linksRecordedNotFollowed'),[])
  out=io.BytesIO();t.emit_frame(d,out);self.assertFalse(d['archiveComplete']);self.assertFalse(d['diagnosticArchiveComplete'])
 def test_empty_frame_is_not_full_archive(self):
  v=load('empty_host_gate',R/'operator/verify_delivery.py')
  d={'kind':'bounded-VM-full20-linux-delivery','full20':True,'archiveComplete':False,'archiveBytesPayload':b'','archiveSha256':sha256(b'').hexdigest(),'members':{},'linksRecordedNotFollowed':[],'result':{'complete':False}}
  ff=load('empty_gate_contract_fixture',R/'checks/full20_archive_fixture.py');_blobs,expected,_final=ff.make()
  d.update(guestRoot=expected['guestRoot'],controllerFinalWritten=True,collectionIssues=[])
  out=io.BytesIO();t.emit_frame(d,out);wire=out.getvalue();n=int.from_bytes(wire[len(t.MAGIC):len(t.MAGIC)+8],'big');actual=json.loads(wire[len(t.MAGIC)+8:len(t.MAGIC)+8+n])['delivery']
  with self.assertRaisesRegex(ValueError,'^full20:delivery-incomplete$'):v.verify_full20_bundle(actual,b'',expected)
  forged=dict(actual,archiveComplete=True,result={'complete':True})
  with self.assertRaisesRegex(ValueError,'^full20:archive-bad:BadZipFile$'):v.verify_full20_bundle(forged,b'',expected)
 def test_full20_fixture_header_emits_under_new_cap(self):
  ff=load('complete_header_fixture',R/'checks/full20_archive_fixture.py');blobs,expected,final=ff.make();d,raw=ff.pack(blobs,expected,final);d['archiveBytesPayload']=raw
  out=io.BytesIO();t.emit_frame(d,out);wire=out.getvalue();n=int.from_bytes(wire[len(t.MAGIC):len(t.MAGIC)+8],'big');self.assertGreater(n,1024**2);self.assertLessEqual(n,2*1024**2)
 def test_two_mib_reservation_and_emitter_limit(self):
  self.assertEqual(t.MAX_HEADER,2*1024**2);self.assertEqual(t.H_RESERVE,t.MAX_HEADER+64)
  with self.assertRaises(ValueError):t.emit_frame({'filler':'x'*(2*1024**2)},io.BytesIO())
 def test_wrong_payload_digest_still_rejected(self):
  with self.assertRaisesRegex(ValueError,'archiveSha256'):t.emit_frame({'archiveBytesPayload':b'x','archiveSha256':sha256(b'').hexdigest()},io.BytesIO())
if __name__=='__main__':unittest.main(verbosity=2)
