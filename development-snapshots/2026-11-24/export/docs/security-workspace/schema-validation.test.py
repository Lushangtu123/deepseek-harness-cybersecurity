"""Standard Draft 2020-12 validation, run with the existing VM scanner Python."""
import copy,json,sys,unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

schema=json.loads(Path(sys.argv[1]).read_text());sys.argv=sys.argv[:1]
examples={v['kind']:v for v in schema['examples']}
H='a'*64
class Contracts(unittest.TestCase):
 def validator(self,name):
  return Draft202012Validator({'$ref':'#/$defs/'+name,'$defs':schema['$defs']})
 def test_schema_and_all_nine_objects(self):
  Draft202012Validator.check_schema(schema)
  self.assertEqual(set(schema['$defs'])-{'budget','dimensions'}, {'plan','step','observation','problem','evidence','coverage','verification','intelligenceMatch','notification'})
  for name,value in examples.items():
   with self.subTest(name=name):self.validator(name).validate(value)
 def test_unknown_coverage_preserves_unknown_denominator(self):
  value=copy.deepcopy(examples['coverage']);value.update(state='unknown',total=None,checked=None)
  self.validator('coverage').validate(value)
  with self.assertRaises(ValidationError):self.validator('coverage').validate({**value,'total':-1})
 def test_tasks_do_not_collapse_axes(self):
  step=copy.deepcopy(examples['step']);step['dimensions'].update(execution='ended',ingestion='recorded',coverage='incomplete',cleanup='unconfirmed')
  self.validator('step').validate(step)
  for axis in ['execution','ingestion','coverage','cleanup']:
   invalid=copy.deepcopy(step);del invalid['dimensions'][axis]
   self.assertFalse(self.validator('step').is_valid(invalid),axis)
 def test_facts_and_workflow_are_separate_and_no_shell_in_plan(self):
  self.assertFalse(self.validator('problem').is_valid({**examples['problem'],'vex':'not_affected'}))
  self.assertFalse(self.validator('step').is_valid({**examples['step'],'command':'arbitrary shell'}))
  self.assertFalse(self.validator('plan').is_valid({**examples['plan'],'executable':True}))
 def test_origin_reference_and_scope_required(self):
  for name,field in [('observation','stepId'),('evidence','sha256'),('coverage','scopeIdentity'),('verification','validatorVersion'),('intelligenceMatch','sourceRevision'),('notification','dedupeKey')]:
   value=copy.deepcopy(examples[name]);del value[field]
   self.assertFalse(self.validator(name).is_valid(value),name)
 def test_problem_roundtrip_retains_recurrence_and_withdrawal(self):
  problem=copy.deepcopy(examples['problem']);problem.update(recurrence=True,detectionReason='advisory-withdrawn')
  self.validator('problem').validate(problem)
  self.assertTrue(json.loads(json.dumps(problem))['recurrence'])
 def test_budget_retains_cpu_tmp_token_and_task_parallelism_limits(self):
  plan=copy.deepcopy(examples['plan']);plan['budget'].update(cpuMillis=1000,tmpBytes=67108864,outputTokensPerCall=0,parallelism=1)
  step=copy.deepcopy(examples['step']);step['budget'].update(cpuMillis=500,tmpBytes=16777216,outputTokensPerCall=0)
  self.validator('plan').validate(plan);self.validator('step').validate(step)
  del plan['budget']['parallelism'];self.assertFalse(self.validator('plan').is_valid(plan))
  step['budget']['parallelism']=1;self.assertFalse(self.validator('step').is_valid(step))

unittest.main(verbosity=2)
