"""Independent owned-fixture lifecycle controls, no VM or target execution."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util,os,stat,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'candidate/checks'))
import regression_lib as lib

def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
u=load('all20_unified',R/'candidate/checks/run_unified_recovery_checks.py')
c=load('all20_consumer',R/'candidate/checks/run_consumer_closure_checks.py')
wmod=load('all20_recovery',R/'candidate/checks/run_recovery_close_checks.py')
b=load('all20_walker',R/'operator/full20_batch.py')
class All20Links(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=R/'checks/tmp');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.private=self.root/'owned';self.private.mkdir();self.external=self.root/'external';self.external.mkdir();(self.external/'sentinel').write_text('unchanged')
 def owner(self):
  self.assertTrue(callable(getattr(lib,'FixtureLinks',None)),'shared owned fixture link helper missing');return lib.FixtureLinks(self.private)
 def link(self,name='pointer',target=None):
  p=self.private/name;p.symlink_to(target or self.external,target_is_directory=True);return p
 def runner(self):return SimpleNamespace(ROOT=self.root,PREPARE=self.root,RUNS=self.root,STATE=self.root,_PREFLIGHT_RESULT=None,release_batch_lock=lambda:None)
 def test_shared_directory_link_close(self):
  o=self.owner();p=self.link();o.track(p);self.assertTrue(p.is_symlink());o.close();self.assertFalse(os.path.lexists(p));self.assertEqual((self.external/'sentinel').read_text(),'unchanged')
 def test_shared_file_link_close(self):
  o=self.owner();p=self.link(target=self.external/'sentinel');o.track(p);o.close();self.assertFalse(os.path.lexists(p));self.assertEqual((self.external/'sentinel').read_text(),'unchanged')
 def test_shared_dangling_link_close(self):
  o=self.owner();p=self.link(target=self.external/'missing');o.track(p);o.close();self.assertFalse(os.path.lexists(p))
 def test_unregistered_link_is_retained(self):
  o=self.owner();p=self.link()
  with self.assertRaisesRegex(RuntimeError,'unregistered fixture symlink retained'):o.close()
  self.assertTrue(p.is_symlink())
 def test_replaced_link_retained(self):
  o=self.owner();p=self.link();o.track(p);p.unlink();p.symlink_to(self.external/'replacement')
  with self.assertRaisesRegex(RuntimeError,'fixture link (identity|contents) changed'):o.close()
  self.assertTrue(p.is_symlink())
 def test_replaced_root_retained(self):
  o=self.owner();p=self.link();o.track(p);self.private.rename(self.root/'old-owned');self.private.mkdir();new=self.link()
  with self.assertRaisesRegex(RuntimeError,'fixture root identity changed'):o.close()
  self.assertTrue(new.is_symlink())
 def test_replaced_parent_retained(self):
  o=self.owner();parent=self.private/'sub';parent.mkdir();p=parent/'link';p.symlink_to(self.external);o.track(p);parent.rename(self.private/'old-sub');(self.private/'old-sub'/'link').unlink();parent.mkdir();new=parent/'link';new.symlink_to(self.external)
  with self.assertRaisesRegex(RuntimeError,'fixture parent identity changed'):o.close()
  self.assertTrue(new.is_symlink())
 def test_read_failure_retains_link(self):
  o=self.owner();p=self.link();o.track(p)
  with patch.object(lib.os,'readlink',side_effect=PermissionError('fixture-read-unknown')),self.assertRaises(PermissionError):o.close()
  self.assertTrue(p.is_symlink())
 def test_unlink_failure_is_not_success(self):
  o=self.owner();p=self.link();o.track(p)
  with patch.object(lib.os,'unlink',side_effect=PermissionError('fixture-unlink-failed')),self.assertRaises(PermissionError):o.close()
  self.assertTrue(p.is_symlink())
 def test_external_link_cannot_be_registered(self):
  o=self.owner();p=self.root/'not-owned';p.symlink_to(self.external)
  with self.assertRaisesRegex(ValueError,'outside the private root'):o.track(p)
  self.assertTrue(p.is_symlink())
 def test_consumer_damage_plan_registers_its_link(self):
  runner=self.runner()
  with patch.object(c.U,'TMP',self.private):w=c.U.Workspace(runner,'consumer-owned-')
  path=w.prepare/'plans'/'unit.json';path.parent.mkdir();path.write_text('{}')
  runner.lifecycle_plan_path=lambda _identifier:path
  c.damage_plan(runner,'unit','symlink',workspace=w);self.assertTrue(path.is_symlink())
  with patch.object(lib,'retire_sandbox',return_value=False):w.close()
  self.assertFalse(os.path.lexists(path))
 def test_recovery_workspace_has_registered_close(self):
  with patch.object(wmod,'TMP',self.private):w=wmod.Workspace(self.runner(),'recovery-owned-')
  p=w.prepare/'link-stage';p.symlink_to(self.external);w.track_fixture_link(p)
  with patch.object(lib,'retire_sandbox',return_value=False):w.close()
  self.assertFalse(os.path.lexists(p));self.assertEqual((self.external/'sentinel').read_text(),'unchanged')
 def walker(self,target):
  root=self.private; (root/'candidate').mkdir();(root/'evidence').mkdir();p=root/'candidate'/'unknown-link';p.symlink_to(target)
  with patch.object(b,'_load_guard',return_value=SimpleNamespace()):ok,detail=b._actual_process_quiescence(root,{},[],[])
  return ok,detail,p
 def test_resource_scan_rejects_file_link(self):
  ok,d,p=self.walker(self.external/'sentinel');self.assertFalse(ok);self.assertEqual(d['state'],'unknown');self.assertEqual(d['reason'],'linked-file');self.assertTrue(p.is_symlink())
 def test_resource_scan_rejects_dangling_link(self):
  ok,d,p=self.walker(self.external/'missing');self.assertFalse(ok);self.assertEqual(d['state'],'unknown');self.assertEqual(d['reason'],'linked-file');self.assertTrue(p.is_symlink())
 def test_resource_scan_keeps_normal_empty_tree(self):
  (self.private/'candidate').mkdir();(self.private/'evidence').mkdir()
  with patch.object(b,'_load_guard',return_value=SimpleNamespace()):ok,d=b._actual_process_quiescence(self.private,{},[],[])
  self.assertTrue(ok);self.assertEqual(d['state'],'quiescent')
 def test_all_records_checked_before_any_unlink(self):
  o=self.owner();a=self.link('a');z=self.link('z');o.track(a);o.track(z);z.unlink();z.symlink_to(self.external/'replacement')
  with patch.object(lib.os,'unlink',wraps=lib.os.unlink) as unlink,self.assertRaisesRegex(RuntimeError,'fixture link (identity|contents) changed'):o.close()
  self.assertEqual(unlink.call_count,0);self.assertTrue(a.is_symlink());self.assertTrue(z.is_symlink())
 def test_unregistered_link_blocks_registered_unlink(self):
  o=self.owner();a=self.link('a');o.track(a);z=self.link('unknown')
  with patch.object(lib.os,'unlink',wraps=lib.os.unlink) as unlink,self.assertRaisesRegex(RuntimeError,'unregistered fixture symlink retained'):o.close()
  self.assertEqual(unlink.call_count,0);self.assertTrue(a.is_symlink());self.assertTrue(z.is_symlink())
 def test_recovery_close_error_does_not_retire_unknown(self):
  with patch.object(wmod,'TMP',self.private):w=wmod.Workspace(self.runner(),'recovery-unknown-')
  p=w.prepare/'link-stage';p.symlink_to(self.external);w.track_fixture_link(p);p.unlink();p.symlink_to(self.external/'replacement')
  with patch.object(lib,'retire_sandbox') as retire,self.assertRaisesRegex(RuntimeError,'fixture link (identity|contents) changed'):w.close()
  retire.assert_not_called();self.assertTrue(p.is_symlink())
 def test_resource_scan_read_failure_is_unknown(self):
  (self.private/'candidate').mkdir();(self.private/'evidence').mkdir();p=self.private/'candidate'/'ordinary';p.write_text('unit')
  original=b.os.lstat
  def fail(path,*args,**kwargs):
   if os.fspath(path)==str(p):raise PermissionError('unit-entry-unreadable')
   return original(path,*args,**kwargs)
  with patch.object(b,'_load_guard',return_value=SimpleNamespace()),patch.object(b.os,'lstat',side_effect=fail):ok,d=b._actual_process_quiescence(self.private,{},[],[])
  self.assertFalse(ok);self.assertEqual(d['reason'],'walk-entry:PermissionError');self.assertEqual(p.read_text(),'unit')
if __name__=='__main__':unittest.main(verbosity=2)
