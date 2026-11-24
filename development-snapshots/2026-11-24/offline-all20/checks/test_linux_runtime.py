from pathlib import Path
from contextlib import ExitStack,contextmanager
from unittest.mock import patch
import importlib.util,os,unittest
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('runtime_subject',R/'operator/linux_admission.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
BOOT='11111111-2222-4333-8444-555555555555'
STAT='12345 (unit (nested)) S 1 12345 12345 '+'0 '*15+'99\n'
@contextmanager
def good(boot=BOOT,stat=STAT):
    def text(p,*a,**kw):
        return boot if str(p)=='/proc/sys/kernel/random/boot_id' else stat
    with ExitStack() as st:
        for obj,name,value in [(m.sys,'platform','linux'),(m.os,'getuid',lambda:1000),(m.os,'getpid',lambda:12345),(m.platform,'machine',lambda:'aarch64'),(m.platform,'python_version',lambda:'3.12.3')]:st.enter_context(patch.object(obj,name,value))
        st.enter_context(patch.dict(os.environ,{'PYTHONOPTIMIZE':''}))
        st.enter_context(patch.object(Path,'read_text',text))
        st.enter_context(patch.object(Path,'read_bytes',return_value=b'unit-interpreter'))
        st.enter_context(patch.object(m.hashlib,'sha256',return_value=type('H',(),{'hexdigest':lambda self:m._EXPECTED_SHA256})()))
        yield
class Runtime(unittest.TestCase):
    def test_positive_actual_shape(self):
        with good():v=m.check_runtime()
        self.assertEqual((v['pid'],v['pgid'],v['starttime'],v['bootId']),(12345,12345,99,BOOT))
    def test_bad_boot(self):
        with good(boot='broken'),self.assertRaisesRegex(ValueError,'boot-id-malformed'):m.check_runtime()
    def test_bad_stat(self):
        with good(stat='invalid'),self.assertRaisesRegex(ValueError,'proc-stat'):m.check_runtime()
    def test_wrong_pid(self):
        with good(stat=STAT.replace('12345 (','67890 (')),self.assertRaisesRegex(ValueError,'proc-stat-pid'):m.check_runtime()
    def test_proc_permission(self):
        with good(),patch.object(Path,'read_text',side_effect=PermissionError('unit')),self.assertRaisesRegex(ValueError,'boot-id-unreadable'):m.check_runtime()
    def test_wrong_interpreter(self):
        with good(),patch.object(m.hashlib,'sha256',return_value=type('H',(),{'hexdigest':lambda self:'0'*64})()),self.assertRaisesRegex(ValueError,'interpreter-sha256'):m.check_runtime()
if __name__=='__main__':unittest.main(verbosity=2)
