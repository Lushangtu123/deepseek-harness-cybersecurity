"""Independent preparation checks; never launch a suite or target."""
import ast
import contextlib
import fcntl
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

R = Path(__file__).resolve().parents[1]
C = R / 'candidate'
spec = importlib.util.spec_from_file_location('shared_regression', C/'checks/regression_lib.py')
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


class Coordination(unittest.TestCase):
    def test_shared_lock_blocks_sampler_then_releases(self):
        helper = getattr(lib, 'sampling_fault_window', None)
        self.assertTrue(callable(helper), 'shared sampling helper missing')
        with tempfile.TemporaryDirectory(dir=R/'checks') as tmp:
            root = Path(tmp)/'candidate'
            root.mkdir()
            lock = root.parent/'.sampling.lock'
            lock.touch(mode=0o600)
            with patch.object(lib, 'ROOT', root), patch.dict(os.environ, HARNESS_SAMPLING_LOCK=str(lock)):
                with lock.open() as sampler:
                    with helper():
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(sampler, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    fcntl.flock(sampler, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    fcntl.flock(sampler, fcntl.LOCK_UN)

    def test_all_three_real_permission_faults_are_coordinated(self):
        for file, func in [('run_consumer_closure_checks.py','reservation_unknown_directory'),
                           ('run_unified_recovery_checks.py','b8_directory_permission'),
                           ('run_rev7_checks.py','test_permission_error_retained')]:
            tree = ast.parse((C/'checks'/file).read_text())
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func)
            windows = [n for n in ast.walk(fn) if isinstance(n, ast.With) and any(
                isinstance(x.context_expr, ast.Call) and
                ((isinstance(x.context_expr.func, ast.Attribute) and x.context_expr.func.attr == 'sampling_fault_window') or
                 (isinstance(x.context_expr.func, ast.Name) and x.context_expr.func.id == 'sampling_fault_window'))
                for x in n.items)]
            self.assertEqual(len(windows), 1, file)
            faults = [n for n in ast.walk(windows[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == 'chmod' and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == 0]
            restores = [n for n in ast.walk(windows[0]) if isinstance(n, ast.Try) and any(
                isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == 'chmod'
                for f in n.finalbody for x in ast.walk(f))]
            self.assertEqual(len(faults), 1, file)
            self.assertTrue(restores, file)

    def test_automatic_teardown_preserves_identity_and_recovery(self):
        retire = getattr(lib, 'retire_sandbox', None)
        self.assertTrue(callable(retire), 'managed teardown missing')
        with tempfile.TemporaryDirectory(dir=R/'checks') as tmp:
            root = Path(tmp)/'candidate'; (root/'checks/tmp').mkdir(parents=True)
            lock = root.parent/'.sampling.lock'; lock.touch(mode=0o600)
            with patch.object(lib, 'ROOT', root), patch.dict(os.environ, HARNESS_SAMPLING_LOCK=str(lock)):
                box = root/'checks/tmp/original'; box.mkdir()
                rec = box/'process-client-identity.json'; rec.write_bytes(b'{"pid":42,"state":"unknown"}\n')
                recovery = box/'recovery-1.json'; recovery.write_bytes(b'{"cleanupConfirmed":false}\n')
                retire(box)
                self.assertEqual(rec.read_bytes(), b'{"pid":42,"state":"unknown"}\n')
                self.assertTrue(recovery.is_file())
                plain = root/'checks/tmp/plain'; plain.mkdir(); (plain/'text').write_text('disposable')
                retire(plain)
                self.assertFalse(plain.exists())


if __name__ == '__main__':
    unittest.main()
