from pathlib import Path
from unittest.mock import patch
import fcntl,importlib.util,os,unittest
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('sample_subject',R/'operator/bounded.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Sampling(unittest.TestCase):
    def setUp(self):
        self.root=R/'checks/tmp'/('sampling-'+os.urandom(5).hex());self.root.mkdir(parents=True)
        self.lock=self.root/'.sampling.lock';self.lock.write_bytes(b'')
        self.plans=self.root/'candidate/checks/tmp/closure-reserve-unknown-dir-unit/prepare/plans';self.plans.mkdir(parents=True)
    def test_exclusive_permission_window_defers_sample(self):
        fd=os.open(self.lock,os.O_RDONLY)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.plans.chmod(0)
            try:
                try:value=getattr(m,'sample_usage',m.usage)(self.root)
                except PermissionError:value='permission-error-aborted'
                self.assertIsNone(value,'sampler traversed deliberately unreadable tree instead of deferring')
            finally:self.plans.chmod(0o700)
        finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
    def test_read_error_without_exclusive_window_still_fails(self):
        self.plans.chmod(0)
        try:
            with self.assertRaises(PermissionError):getattr(m,'sample_usage',m.usage)(self.root)
        finally:self.plans.chmod(0o700)
    def test_readable_control_counts_actual_bytes(self):
        (self.root/'x').write_bytes(b'abc')
        self.assertEqual(getattr(m,'sample_usage',m.usage)(self.root),3)
    def test_replaced_lock_is_rejected_for_pinned_attempt(self):
        st=self.lock.lstat();identity=(st.st_dev,st.st_ino);new=self.root/'replacement';new.write_bytes(b'');os.replace(new,self.lock)
        with self.assertRaises(ValueError):m._sample_usage(self.root,identity)
    def test_hardlinked_lock_is_rejected(self):
        alias=self.root/'alias';os.link(self.lock,alias)
        try:
            with self.assertRaises(ValueError):m.sample_usage(self.root)
        finally:alias.unlink()
if __name__=='__main__':unittest.main(verbosity=2)
