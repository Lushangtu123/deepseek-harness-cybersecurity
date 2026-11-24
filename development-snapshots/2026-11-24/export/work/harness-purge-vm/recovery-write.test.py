from pathlib import Path
from unittest.mock import patch
import importlib.util, tempfile, unittest, json
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('recovery_write_manager',Path(__file__).with_name('manage.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RecoveryWrite(unittest.TestCase):
 def test_one_time_replace_failure_leaves_old_file_and_allows_rollback_write(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'helper';path.write_bytes(b'before')
   with patch.object(m.os,'replace',side_effect=OSError('synthetic replace failed')):
    with self.assertRaisesRegex(OSError,'synthetic replace'):m.atomic_recovery_write(path,b'after')
   self.assertEqual(path.read_bytes(),b'before')
   self.assertEqual(sorted(p.name for p in path.parent.iterdir()),['helper'])
   m.atomic_recovery_write(path,b'rollback')
   self.assertEqual(path.read_bytes(),b'rollback')

 def test_fsync_failure_cleans_only_owned_temporary_and_preserves_stale_file(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'helper';path.write_bytes(b'before')
   stale=Path(temp)/'helper.recovery-next';stale.write_bytes(b'old orphan')
   with patch.object(m.os,'fsync',side_effect=OSError('synthetic fsync failed')):
    with self.assertRaisesRegex(OSError,'synthetic fsync'):m.atomic_recovery_write(path,b'after')
   self.assertEqual(path.read_bytes(),b'before');self.assertEqual(stale.read_bytes(),b'old orphan')
   self.assertEqual(len(list(Path(temp).iterdir())),2)
   m.atomic_recovery_write(path,b'final',0o700)
   self.assertEqual(path.read_bytes(),b'final');self.assertEqual(path.stat().st_mode&0o777,0o700)

 def test_symbolic_target_is_rejected_without_writing(self):
  with tempfile.TemporaryDirectory() as temp:
   target=Path(temp)/'target';target.write_bytes(b'unchanged')
   link=Path(temp)/'helper';link.symlink_to(target)
   with self.assertRaisesRegex(ValueError,'symlink'):m.atomic_recovery_write(link,b'after')
   self.assertEqual(target.read_bytes(),b'unchanged')

 def test_disk_rollback_failure_still_attempts_host_rollback_and_reports_both(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'verify_recovery_bundle',return_value=(Path('/synthetic/bundle'),{'helpers':{}})),patch.object(m,'prepare_host_bundle',return_value={'helpers':{'qemu-image.py':(b'checked helper',0o600)}}),patch.object(m,'copy_host_bundle',return_value={'helpers':{}}),patch.object(m,'image_command') as image,patch.object(m,'apply_host_bundle',side_effect=[RuntimeError('first host failure'),None]) as apply:
   (Path(temp)/'recoveries').mkdir()
   calls=0
   def disk(args,**kwargs):
    nonlocal calls
    calls+=1
    if calls==4:raise OSError('disk rollback failure')
    return SimpleNamespace(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))
   image.side_effect=disk
   with self.assertRaisesRegex(RuntimeError,'Rollback needs attention') as raised:m.restore_current_recovery(m.CURRENT_RECOVERY)
   self.assertEqual(apply.call_count,2)
   self.assertIn('disk',str(raised.exception));self.assertIsInstance(raised.exception.__cause__,RuntimeError)
   self.assertEqual(str(raised.exception.__cause__),'first host failure')

if __name__=='__main__':unittest.main()
