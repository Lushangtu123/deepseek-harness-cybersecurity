import importlib.util,tempfile,json,hashlib,unittest,subprocess,time,sys
from pathlib import Path
from unittest.mock import patch
module_path=Path(__file__).resolve().parents[1]/'check_versions.py'
class Versions(unittest.TestCase):
 def setUp(self):
  self.assertTrue(module_path.exists(),'Read-only version checker is missing')
  spec=importlib.util.spec_from_file_location('versions',module_path);self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
 def test_refs_are_exact_and_annotated_tag_is_peeled(self):
  a='a'*40;b='b'*40
  parsed=self.m.parse_refs('ref: refs/heads/main\tHEAD\n'+a+'\tHEAD\n'+a+'\trefs/tags/v1.0\n'+b+'\trefs/tags/v1.0^{}\n')
  self.assertEqual(parsed['HEAD'],a);self.assertEqual(parsed['defaultBranch'],'main');self.assertEqual(self.m.tag_revision(parsed,'v1.0'),b)
 def test_release_redirect_rejects_other_hosts_repos_and_controls(self):
  self.assertEqual(self.m.release_tag('morluto/rea','https://github.com/morluto/rea/releases/tag/v6.8.0'),'v6.8.0')
  for url in ['https://outside.invalid/morluto/rea/releases/tag/v1','https://github.com/other/repo/releases/tag/v1','https://github.com/morluto/rea/releases/tag/v1%0Asecret']:
   with self.assertRaises(ValueError):self.m.release_tag('morluto/rea',url)
 def test_default_branch_changes_are_not_reported_as_a_new_stable_release(self):
  installed={'version':'6.8.0','revision':'a'*40,'available':True}
  result=self.m.compare(installed,{'state':'available','tag':'v6.8.0','revision':'a'*40},{'state':'available','revision':'b'*40,'branch':'main'})
  self.assertTrue(result['matchesLatestRelease']);self.assertFalse(result['matchesDefaultBranch']);self.assertEqual(result['status'],'release_matches_development_differs')
 def test_unknown_network_never_becomes_up_to_date(self):
  result=self.m.compare({'version':'6.8.0','revision':'a'*40,'available':True},{'state':'unavailable'},{'state':'unavailable'})
  self.assertEqual(result['status'],'unverified');self.assertIsNone(result['matchesLatestRelease']);self.assertIsNone(result['matchesDefaultBranch'])
 def test_no_release_and_unknown_installation_remain_explicit(self):
  result=self.m.compare({'revision':'a'*40,'available':True},{'state':'no_release'},{'state':'available','revision':'a'*40})
  self.assertEqual(result['status'],'matches_default_branch_no_release');self.assertIsNone(result['matchesLatestRelease'])
  result=self.m.compare({'available':False},{'state':'no_release'},{'state':'available','revision':'a'*40})
  self.assertEqual(result['status'],'unverified')
 def test_version_numbers_compare_numerically_without_guessing_prerelease_order(self):
  result=self.m.compare({'version':'6.8.0','available':True},{'state':'available','tag':'v6.10.0'},{'state':'available','revision':'b'*40})
  self.assertEqual(result['status'],'update_available')
  result=self.m.compare({'version':'2.2.0-ce.h123','revision':'a'*40,'available':True},{'state':'available','tag':'v2.1.0','revision':'b'*40},{'state':'available','revision':'c'*40})
  self.assertEqual(result['status'],'revision_differs')
 def test_reverse_archive_changes_invalidate_its_recorded_revision(self):
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);root=home/'tools/reverse-skill/reverse-skill-abc';root.mkdir(parents=True);(root/'SKILL.md').write_text('changed')
   catalog={'projects':{'reverse-skill':{'commit':'a'*40}},'reverseDirectory':'reverse-skill-abc','reverseFiles':{'SKILL.md':hashlib.sha256(b'original').hexdigest()}}
   result=self.m.read_installed('reverse-skill',catalog,home=home)
   self.assertFalse(result['available']);self.assertIsNone(result['revision']);self.assertEqual(result['changedFiles'],1)
 def test_git_query_is_read_only_fixed_origin_and_has_no_inherited_credentials(self):
  with patch.object(self.m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='a'*40+'\tHEAD\n',stderr='')) as run:
   self.m.query_refs('rea',['HEAD'])
   args=run.call_args.args[0];self.assertIn('ls-remote',args);self.assertIn('https://github.com/morluto/rea.git',args)
   self.assertNotIn('fetch',args);self.assertNotIn('pull',args);self.assertNotIn('GITHUB_TOKEN',run.call_args.kwargs['env'])
  with self.assertRaises(ValueError):self.m.query_refs('https://outside.invalid', ['HEAD'])
 def test_no_release_only_follows_a_successful_repository_check(self):
  with patch.object(self.m,'query_refs',side_effect=RuntimeError('offline')),patch.object(self.m,'latest_release',return_value={'state':'no_release'}):
   result=self.m.check_project('rea',{},installed={'version':'6.8.0','revision':'a'*40,'available':True})
   self.assertEqual(result['comparison']['status'],'unverified')
 def test_equal_version_with_failed_release_commit_is_not_confirmed_current(self):
  with patch.object(self.m,'query_refs',side_effect=[{'HEAD':'b'*40,'defaultBranch':'main'},RuntimeError('offline')]),patch.object(self.m,'latest_release',return_value={'state':'available','tag':'rea-agents-6.8.0'}):
   result=self.m.check_project('rea',{},installed={'version':'6.8.0','revision':'a'*40,'available':True})
   self.assertIsNone(result['comparison']['matchesLatestRelease'])
   self.assertEqual(result['comparison']['releaseVersionMatches'],True)
   self.assertIsNone(result['latestRelease']['revision'])
 def test_changed_rea_sources_invalidate_unchanged_package_version(self):
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);root=home/'tools/rea-runtime/node_modules/rea-agents';root.mkdir(parents=True)
   package=json.dumps({'name':'rea-agents','version':'6.8.0'});(root/'package.json').write_text(package);(root/'index.js').write_text('changed')
   catalog={'projects':{'rea':{'npmVersion':'6.8.0','revision':'a'*40}},'reaFiles':{'package.json':hashlib.sha256(package.encode()).hexdigest(),'index.js':hashlib.sha256(b'original').hexdigest()}}
   result=self.m.read_installed('rea',catalog,home=home)
   self.assertFalse(result['available']);self.assertIsNone(result['revision'])
 def test_release_rate_limit_or_foreign_redirect_remains_unavailable(self):
  for output in ['HTTP/2 429\n','HTTP/2 302\nlocation: https://outside.invalid/releases/tag/v1\n']:
   with patch.object(self.m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout=output,stderr='')) as run:
    self.assertEqual(self.m.latest_release('rea')['state'],'unavailable')
    self.assertNotIn('-L',run.call_args.args[0]);self.assertNotIn('--location',run.call_args.args[0])
 def test_one_project_timeout_keeps_other_results(self):
  method=getattr(self.m,'check_projects',None);self.assertTrue(callable(method),'Per-project result collection is missing')
  installed={'available':True,'version':'6.8.0','revision':'a'*40}
  def refs(project,patterns):
   if project=='rea':raise subprocess.TimeoutExpired('git',.01)
   return {'HEAD':'a'*40,'defaultBranch':'main'}
  with patch.object(self.m,'read_installed',return_value=installed),patch.object(self.m,'query_refs',side_effect=refs),patch.object(self.m,'latest_release',return_value={'state':'no_release'}):
   rows=method(list(self.m.PROJECTS),{},_runner=lambda name,catalog,local_only=False:self.m.check_project(name,catalog,local_only=local_only))
  self.assertEqual(len(rows),3);self.assertEqual(rows[0]['queryState'],'timeout')
  self.assertIsNone(rows[0]['comparison']['matchesLatestRelease'])
  self.assertTrue(all(row['comparison']['matchesDefaultBranch'] for row in rows[1:]))
 def test_a_project_shares_one_remaining_budget_across_queries(self):
  self.assertTrue(hasattr(self.m,'PROJECT_BUDGET'),'Per-project deadline is missing')
  observed=[]
  def run(*args,**kwargs):
   observed.append(kwargs['timeout'])
   time.sleep(.025)
   return subprocess.CompletedProcess(args[0],0,stdout='a'*40+'\tHEAD\n',stderr='')
  with patch.object(self.m,'PROJECT_BUDGET',.08),patch.object(self.m.subprocess,'run',side_effect=run),patch.object(self.m,'latest_release',return_value={'state':'available','tag':'v6.8.0'}):
   self.m.check_project('rea',{},installed={'available':True,'revision':'a'*40})
  self.assertEqual(len(observed),2);self.assertLess(observed[1],observed[0]);self.assertLessEqual(observed[0],.08)
 def test_expired_project_stops_starting_new_network_operations(self):
  self.assertTrue(hasattr(self.m,'PROJECT_BUDGET'),'Per-project deadline is missing')
  with patch.object(self.m,'PROJECT_BUDGET',0),patch.object(self.m.subprocess,'run') as run:
   row=self.m.check_project('rea',{},installed={'available':True,'revision':'a'*40})
  run.assert_not_called();self.assertEqual(row['queryState'],'timeout')
  self.assertEqual(row['comparison']['status'],'unverified')
 def test_blocked_local_inspection_is_killed_without_losing_other_projects(self):
  self.assertTrue(hasattr(self.m,'ProjectRunner'),'Killable per-project inspection is missing')
  def command(name,local_only):
   code="import time,json;"+("time.sleep(2);" if name=='rea' else '')+"print(json.dumps({'project':"+repr(name)+",'queryState':'completed','comparison':{'matchesDefaultBranch':True}}))"
   return [sys.executable,'-B','-c',code]
  start=time.monotonic()
  with patch.object(self.m,'PROJECT_BUDGET',.25),patch.object(self.m,'worker_command',side_effect=command):rows=self.m.check_projects(list(self.m.PROJECTS),{})
  self.assertLess(time.monotonic()-start,1.2);self.assertEqual(rows[0]['queryState'],'timeout')
  self.assertTrue(all(row['comparison']['matchesDefaultBranch'] for row in rows[1:]))
 def test_worker_reserves_time_to_serialize_partial_results_before_hard_timeout(self):
  observed=[]
  def run(*args,**kwargs):
   observed.append(kwargs['timeout']);raise subprocess.TimeoutExpired(args[0],kwargs['timeout'])
  with patch.object(self.m,'PROJECT_BUDGET',.1),patch.object(self.m.subprocess,'run',side_effect=run):
   self.m.check_project('rea',{},installed={'available':True,'revision':'a'*40})
  self.assertTrue(observed);self.assertLess(observed[0],.085)
 def test_github_rate_limit_has_a_fixed_code_without_exposing_response_text(self):
  with patch.object(self.m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='HTTP/2 429\nPRIVATE_CANARY\n',stderr='PRIVATE_CANARY')):
   result=self.m.latest_release('rea')
  self.assertEqual(result.get('errorCode'),'rate_limited');self.assertNotIn('PRIVATE_CANARY',json.dumps(result))
 def test_modified_local_files_have_a_distinct_error_code(self):
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);root=home/'tools/reverse-skill/reverse-skill-abc';root.mkdir(parents=True);(root/'SKILL.md').write_text('changed')
   catalog={'projects':{'reverse-skill':{'commit':'a'*40}},'reverseDirectory':'reverse-skill-abc','reverseFiles':{'SKILL.md':hashlib.sha256(b'original').hexdigest()}}
   result=self.m.read_installed('reverse-skill',catalog,home=home)
  self.assertEqual(result.get('errorCode'),'local_modified')
 def test_missing_container_metadata_is_not_a_generic_network_failure(self):
  with patch.object(self.m.subprocess,'run',return_value=subprocess.CompletedProcess([],1,stdout='',stderr='PRIVATE_CANARY')):
   result=self.m.read_installed('pentagi',{})
  self.assertEqual(result.get('errorCode'),'container_unavailable');self.assertNotIn('PRIVATE_CANARY',json.dumps(result))
 def test_each_project_result_has_its_own_completion_time(self):
  with patch.object(self.m,'query_refs',return_value={'HEAD':'a'*40}),patch.object(self.m,'latest_release',return_value={'state':'no_release'}):
   row=self.m.check_project('rea',{},installed={'available':True,'revision':'a'*40})
  self.assertTrue(row.get('checkedAt'));self.assertIsNotNone(self.m.datetime.fromisoformat(row['checkedAt']).tzinfo)
  self.assertTrue(self.m.failed_project('rea',True).get('checkedAt'))
 def test_unverified_repository_has_a_fixed_category(self):
  with patch.object(self.m,'query_refs',side_effect=RuntimeError('offline')),patch.object(self.m,'latest_release',return_value={'state':'no_release'}):
   row=self.m.check_project('rea',{},installed={'available':True,'revision':'a'*40})
  self.assertEqual(row['latestRelease'].get('errorCode'),'repository_unverified')
 def test_incomplete_container_labels_have_a_fixed_category(self):
  with patch.object(self.m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='{"version":"2.2.0","revision":null,"imageId":"synthetic"}',stderr='')):
   row=self.m.read_installed('pentagi',{})
  self.assertEqual(row.get('errorCode'),'container_metadata_unverified')
if __name__=='__main__':unittest.main()
