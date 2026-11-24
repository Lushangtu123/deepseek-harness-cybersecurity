"""Static proof and contract tests; never execute project input on Mac."""
from pathlib import Path
import importlib.util,unittest
P=Path(__file__).with_name('python_execution_verify.py')
class VerifyTest(unittest.TestCase):
 def api(self):
  self.assertTrue(P.exists(),'Independent verifier missing');s=importlib.util.spec_from_file_location('execution_verify',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_safe_literal_set_has_complete_narrow_proof(self):
  m=self.api();source='def route(value):\n    if value not in ("1", "\\\'hello\\\'"):\n        return "rejected"\n    return eval(value)\n'
  proof=m.exclusion_proof(source,4);self.assertEqual(proof['kind'],'finite-literal-set');self.assertEqual(proof['values'],['1',"'hello'"])
 def test_dangerous_set_assignment_and_introspection_remain_unknown(self):
  m=self.api()
  for source in ['def route(value):\n    if value not in ("len([])",):\n        return "no"\n    return eval(value)\n','def route(value):\n    if value not in ("1",):\n        return "no"\n    value=other\n    return eval(value)\n','import sys\ndef route(value):\n    return eval(value)\n']:
   self.assertIsNone(m.exclusion_proof(source,source.count('\n')))
 def test_plain_string_shape_proof_requires_dominating_guard(self):
  m=self.api();source='def route(value):\n    if not value.startswith("\\\'") or not value.endswith("\\\'") or "\\\'" in value[1:-1]:\n        return "invalid"\n    return eval(value)\n'
  self.assertEqual(m.exclusion_proof(source,4)['kind'],'single-quoted-string')
 def test_string_flow_supports_fixed_slice_but_not_callback_or_overwrite(self):
  m=self.api();source='def route(value):\n    prefix="help"\n    prefix+=value\n    prefix+="suffix"\n    bar=prefix[4:-6]\n    if not bar.startswith("\\\'") or not bar.endswith("\\\'") or "\\\'" in bar[1:-1]:\n        return "invalid"\n    return eval(bar)\n'
  self.assertEqual(m.exclusion_proof(source,8)['kind'],'single-quoted-string')
  self.assertIsNone(m.exclusion_proof(source.replace('bar=prefix[4:-6]','bar=callback(prefix)'),8))
 def test_additional_untyped_default_parameter_cannot_support_exclusion(self):
  m=self.api();source='def route(value, other=callback()):\n    value=other\n    if value not in ("1",):\n        return "no"\n    return eval(value)\n'
  self.assertIsNone(m.exclusion_proof(source,5))
 def test_source_cannot_replace_output_or_write_raw_trace(self):
  m=self.api()
  for source in ['import builtins\nbuiltins.print=lambda *args: None\n','import os\nos.write(1,b"fake")\n','import os\nos.sys.monitoring.set_events(3,0)\n']:
   self.assertFalse(m.passive_source(source))
 def test_probe_challenge_is_not_a_fixed_source_constant(self):
  m=self.api();a=m.probes_for('a'*64);b=m.probes_for('b'*64)
  self.assertNotEqual(a,b);self.assertTrue(all(('a'*64 in p) for p in a[1:3]))
 def test_quoted_challenge_is_not_expression_execution(self):
  m=self.api();probe=m.probes_for('a'*64)[1]
  self.assertTrue(m.same_program(probe+'_lines(line)',probe,'eval'))
  self.assertFalse(m.same_program(repr('a'*64),probe,'eval'))
  self.assertFalse(m.same_program('"str(\'x\')#"',probe,'eval'))
 def test_default_side_effect_and_internal_marker_never_support_proof(self):
  m=self.api();source='def route(value=callback()):\n    if value not in ("1",):\n        return "no"\n    return eval(value)\n'
  self.assertIsNone(m.exclusion_proof(source,4));self.assertFalse(m.passive_source('__harness_probe__="forged"'))
 def test_unreviewed_project_bytes_are_not_executed(self):
  m=self.api();self.assertNotIn(m.sha256(b'def route(value): return eval(repr(value))').hexdigest(),m.APPROVED_SOURCES)
 def test_unreviewed_source_returns_before_project_import_or_exec(self):
  from tempfile import TemporaryDirectory
  from hashlib import sha256
  m=self.api()
  with TemporaryDirectory() as directory:
   root=Path(directory).resolve();raw=b'raise RuntimeError("must not execute")\n';(root/'app.py').write_bytes(raw)
   v={'sourceRoot':str(root),'dependencies':str(root/'absent'),'files':{'app.py':sha256(raw).hexdigest()},'contract':{'version':1,'path':'app.py','entry':{'kind':'function','name':'route','parameter':'value'},'inputContract':'untrusted-data-only'},'point':{'id':'a'*64},'probe':'none','challenge':'b'*64}
   self.assertEqual(m.run_probe(v),{'state':'unknown','reason':'source-profile-not-reviewed'})
 def test_contract_forbids_executable_hooks_and_overbudget_probes(self):
  m=self.api();valid={'version':1,'path':'app.py','entry':{'kind':'function','name':'route','parameter':'value'},'inputContract':'untrusted-data-only'}
  self.assertEqual(m.validate_contract(valid),valid)
  for mutate in [lambda v:v.update(setup='exec(1)'),lambda v:v.update(probes=['untrusted']),lambda v:v['entry'].update(command='sh'),lambda v:v.update(inputContract='python-code-intended')]:
   import copy;value=copy.deepcopy(valid);mutate(value)
   with self.assertRaises(ValueError):m.validate_contract(value)
if __name__=='__main__':unittest.main()
