from pathlib import Path
import importlib.util,json,unittest
SCRIPT=Path(__file__).resolve().parent.parent/'package/scripts/security-parser-check.py'
class ParserProbeTest(unittest.TestCase):
 def test_gate_includes_html_regex_variants_and_positive_after_gap(self):
  m=self.module();self.assertIn('semicolon.mjs',m.FIXTURES);self.assertIn('no-comment.mjs',m.FIXTURES);self.assertIn('positive-after.mjs',m.FIXTURES)
  value=self.fixture(m,False);value['results']=[r for r in value['results'] if not (r['check_id']=='probe.eval' and r['path']=='/src/positive-after.mjs')];result=m.evaluate(value,0);self.assertFalse(result['parserReady'],'Missing positive-after eval control must fail')
 def module(self):
  self.assertTrue(SCRIPT.is_file(),'A reusable offline parser check is missing')
  spec=importlib.util.spec_from_file_location('parser_probe',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def fixture(self,m,broken=True):
  names=list(m.FIXTURES)
  result={'paths':{'scanned':['/src/'+name for name in names]},'errors':[{'type':'ParseError','path':'/src/invalid.mjs','message':'PRIVATE_RAW_DIAGNOSTIC'}], 'results':[{'check_id':'probe.expression','path':'/src/'+name} for name in names if name!='invalid.mjs']+[{'check_id':'probe.eval','path':'/src/'+name} for name in ['positive.mjs','positive-after.mjs']]}
  if broken:result['errors'].append({'type':['PartialParsing',[{'path':'/src/repro.mjs','start':{'line':5}}]],'message':'PRIVATE_RAW_DIAGNOSTIC'})
  return result
 def test_complete_execution_with_exit_zero_is_still_a_failed_parser_gate(self):
  m=self.module();result=m.evaluate(self.fixture(m),0)
  self.assertTrue(result['executionOk']);self.assertTrue(result['controlsPassed']);self.assertFalse(result['parserReady']);self.assertEqual(result['exitCode'],2)
  self.assertEqual(result['cases']['repro.mjs']['errors'],['PartialParsing']);self.assertNotIn('PRIVATE_RAW_DIAGNOSTIC',json.dumps(result));self.assertEqual(result['fixtureCount'],8)
 def test_fixed_candidate_must_pass_all_controls_before_parser_ready(self):
  m=self.module();good=self.fixture(m,False);result=m.evaluate(good,0);self.assertTrue(result['parserReady']);self.assertEqual(result['exitCode'],0)
  for change in ['missing-target','missing-positive','benign-false-positive','missing-invalid-error','escaped-error']:
   value=json.loads(json.dumps(good))
   if change=='missing-target':value['paths']['scanned'].remove('/src/repro.mjs')
   if change=='missing-positive':value['results']=[r for r in value['results'] if r['check_id']!='probe.eval']
   if change=='benign-false-positive':value['results'].append({'check_id':'probe.eval','path':'/src/benign.mjs'})
   if change=='missing-invalid-error':value['errors']=[]
   if change=='escaped-error':value['errors'].append({'type':'PartialParsing','path':'/src/escaped.mjs'})
   result=m.evaluate(value,0);self.assertFalse(result['parserReady'],change);self.assertFalse(result['controlsPassed'],change);self.assertEqual(result['exitCode'],1)
 def test_unknown_global_malformed_or_nonzero_results_are_not_coverage(self):
  m=self.module();good=self.fixture(m)
  cases=[(good,2),({},0),({**good,'paths':{'scanned':[]}},0),({**good,'errors':[{'type':'Timeout','path':'/src/foreign.mjs'}]},0),({**good,'errors':[{'type':['PartialParsing',[]]}]},0),({**good,'errors':[{'type':'RuleParseError'}]},0),({**good,'results':[{'check_id':'foreign','path':'/src/repro.mjs'}]},0),({**good,'paths':{'scanned':['/src/repro.mjs','/src/repro.mjs']}},0)]
  for value,code in cases:
   try:result=m.evaluate(value,code)
   except m.ProbeError:continue
   self.assertFalse(result['parserReady'])
 def test_container_plan_is_offline_readonly_pinned_and_never_pulls(self):
  m=self.module();args=m.plan('sha256:'+'a'*64,Path('/tmp/owned/inputs'),Path('/tmp/owned/output'),'harness-parser-123456789abc')
  for option,value in [('--pull','never'),('--network','none'),('--cap-drop','ALL'),('--user','1000:1000'),('--entrypoint','/bin/sh')]:self.assertEqual(args[args.index(option)+1],value)
  self.assertIn('--read-only',args);self.assertIn('type=bind,src=/tmp/owned/inputs,dst=/src,readonly',args);self.assertNotIn('--privileged',args)
  for image in ['--privileged','semgrep/semgrep:latest','sha256:short']:
   with self.assertRaises(m.ProbeError):m.plan(image,Path('/tmp/in'),Path('/tmp/out'),'harness-parser-123456789abc')
 def test_output_reader_rejects_links_nonregular_and_oversize_without_echo(self):
  import os,tempfile
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);file=root/'result.json';file.write_text('{"fixture":true}');self.assertEqual(m.read_result(file),{'fixture':True})
   for kind in ['link','hardlink','oversize','fifo']:
    suspect=root/kind
    if kind=='link':suspect.symlink_to(file)
    elif kind=='hardlink':os.link(file,suspect)
    elif kind=='oversize':suspect.write_bytes(b' '* (2*1024*1024+1))
    else:os.mkfifo(suspect)
    with self.assertRaises((m.ProbeError,OSError)):m.read_result(suspect)
    suspect.unlink()
 def test_fixture_is_exact_existing_reproduction_and_sources_are_not_executed(self):
  m=self.module();expected=Path(__file__).resolve().parents[2]/'harness-purge-vm/fixtures/semgrep-parser/repro.mjs';self.assertEqual(m.REPRO,expected.read_text());self.assertEqual(m.FIXTURES['escaped.mjs'],m.REPRO.replace('/<!--','/\\x3c!--'));self.assertIn('eval(input)',m.FIXTURES['positive.mjs'])
 def test_probe_refuses_host_platform_before_running_docker(self):
  import unittest.mock
  m=self.module()
  with unittest.mock.patch.object(m.sys,'platform','darwin'),unittest.mock.patch.object(m.subprocess,'run') as call:
   with self.assertRaises(m.ProbeError):m.check()
   call.assert_not_called()
 def test_timeouts_and_missing_invalid_target_never_satisfy_syntax_control(self):
  m=self.module()
  for kind in ['Timeout','OutOfMemory','RuleParseError']:
   value=self.fixture(m,False);value['errors']=[{'type':kind,'path':'/src/invalid.mjs'}];result=m.evaluate(value,0);self.assertFalse(result['controlsPassed'],kind);self.assertFalse(result['parserReady'],kind)
  value=self.fixture(m,False);value['paths']['scanned'].remove('/src/invalid.mjs');self.assertFalse(m.evaluate(value,0)['parserReady'])
 def test_output_quota_is_container_tmpfs_with_readonly_inputs_and_no_docker_log_file(self):
  m=self.module();args=m.plan('sha256:'+'a'*64,Path('/tmp/in'),Path('/tmp/old-output'),'harness-parser-123456789abc')
  self.assertIn('/out:rw,nosuid,nodev,noexec,size=16777216,uid=1000,gid=1000,mode=0700',args)
  self.assertEqual(args[args.index('--log-driver')+1],'none')
  self.assertFalse(any('src=/tmp/old-output' in item for item in args));self.assertTrue(any('security-output.sh' in item and 'readonly' in item for item in args))
if __name__=='__main__':unittest.main()
