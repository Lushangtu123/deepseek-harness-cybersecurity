"""Preparation-only controls; no suite producer is run."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

R = Path(__file__).resolve().parents[1]


class BatchAdmission(unittest.TestCase):
    def load(self):
        p = R/'operator/full20_batch.py'
        self.assertTrue(p.is_file(), 'Linux full20 adapter absent')
        s = importlib.util.spec_from_file_location('full20_batch_check', p)
        m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
        return m

    def test_registry_exact_and_fail_closed(self):
        m = self.load(); plan = json.loads((R/'operator/suite-plan.json').read_bytes())
        source = plan['sourceManifestSha256']
        self.assertTrue(m.validate_registry(plan, source))
        for mutate in [lambda p: p['order'].pop(),
                       lambda p: p['order'].reverse(),
                       lambda p: p['order'].__setitem__(1, p['order'][0]),
                       lambda p: p.__setitem__('sourceManifestSha256', '0'*64),
                       lambda p: p['suites']['pure-compile']['command'].append('-O')]:
            bad = copy.deepcopy(plan); mutate(bad)
            with self.assertRaises(ValueError): m.validate_registry(bad, source)

    def test_distinct_native_result_formats_preserved(self):
        m = self.load()
        self.assertTrue(callable(m.run_batch))
        source = (R/'operator/full20_batch.py').read_text()
        self.assertIn('_validate_independent_entry', source)
        self.assertIn('_validate_baseline_entry', source)
        self.assertIn('_validate_ordinary_entry', source)
        self.assertNotIn('normaliz', source.lower())


if __name__ == '__main__': unittest.main()
