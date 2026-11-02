from pathlib import Path
import importlib.util,tempfile,unittest,json
FILE=Path(__file__).resolve().parents[1]/'package/scripts/security-joint-adapter.py'
class AdapterContracts(unittest.TestCase):
 def module(self):
  self.assertTrue(FILE.is_file(),'Managed REA/PentAGI adapter is missing')
  s=importlib.util.spec_from_file_location('joint_adapter',FILE);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_rea_container_has_no_network_or_project_execution(self):
  m=self.module();plan=m.rea_plan('joint-'+'a'*40,'/home/purge/.cache/harness-joint-adapters/job',35)
  args=plan['args'];self.assertIn('none',args);self.assertIn('--read-only',args);self.assertIn('1000:1000',args);self.assertIn('ALL',args);self.assertIn('no-new-privileges',args);self.assertIn('analyze-javascript-application',args);self.assertIn('/usr/bin/timeout',args);self.assertFalse(any('docker.sock' in x for x in args))
 def test_handoff_rejects_changed_bytes_traversal_and_arbitrary_options(self):
  m=self.module();v={'snapshotId':'b'*64,'seconds':30,'files':[{'path':'app.js','sha256':'0'*64,'content':'YQ=='}]}
  with self.assertRaises(ValueError):m.validate_payload('rea',v)
  import hashlib;v['files'][0]['sha256']=hashlib.sha256(b'a').hexdigest();self.assertEqual(m.validate_payload('rea',v),v)
  for path in ['../app.js','.env','x/../../app.js','/etc/passwd','app.py']:
   v['files'][0]['path']=path
   with self.assertRaises(ValueError):m.validate_payload('rea',v)
 def test_pentagi_docker_policy_overrides_privilege_and_scope(self):
  m=self.module();p=m.PentagiDockerPolicy('joint-'+'a'*40,'/owned/source','sha256:'+'b'*64)
  request={'Image':'anything','User':'0','HostConfig':{'Privileged':True,'Binds':['/:/host'],'NetworkMode':'host'},'NetworkingConfig':{'EndpointsConfig':{'host':{}}}}
  safe=p.create(request);self.assertEqual(safe['Image'],'sha256:'+'b'*64);self.assertEqual(safe['User'],'1000:1000');h=safe['HostConfig'];self.assertEqual(h['NetworkMode'],'none');self.assertFalse(h.get('Privileged'));self.assertEqual(h['CapDrop'],['ALL']);self.assertEqual(h['Binds'],['/owned/source:/project:ro']);self.assertNotIn('NetworkingConfig',safe);self.assertEqual(h['RestartPolicy']['Name'],'no')
 def test_model_budget_reserves_before_forward_and_never_resets_unknown_call(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as t:
   b=m.ModelBudget(Path(t)/'budget.json',max_calls=2,max_output=100)
   request=b.reserve({'model':'forbidden','max_tokens':9999});self.assertEqual(request['max_tokens'],100);self.assertEqual(request['thinking'],{'type':'disabled'});b.reserve({})
   with self.assertRaises(ValueError):b.reserve({})
   with self.assertRaises(ValueError):m.ModelBudget(Path(t)/'budget.json',max_calls=2,max_output=100).reserve({})
 def test_concurrent_model_requests_cannot_exceed_reserved_budget(self):
  m=self.module()
  import concurrent.futures
  with tempfile.TemporaryDirectory() as t:
   b=m.ModelBudget(Path(t)/'budget.json',max_calls=3,max_output=50)
   def call(_):
    try:b.reserve({});return 1
    except ValueError:return 0
   with concurrent.futures.ThreadPoolExecutor(12) as pool:self.assertEqual(sum(pool.map(call,range(30))),3)
 def test_docker_proxy_denies_other_containers_and_network_changes(self):
  m=self.module()
  import http.client,socket,threading
  with tempfile.TemporaryDirectory() as t:
   server=m.DockerProxy(str(Path(t)/'policy.sock'),m.DockerHandler);server.deadline=m.time.time()+10;server.job=Path(t);server.policy=m.PentagiDockerPolicy('joint-'+'a'*40,'/source','sha256:'+'b'*64);server.container='c'*64;server.execs=set()
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   class Connection(http.client.HTTPConnection):
    def connect(self):self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.connect(str(Path(t)/'policy.sock'))
   try:
    for method,path in [('GET','/containers/not-owned/json'),('POST','/networks/create'),('POST','/build'),('POST','/exec/not-owned/start'),('POST','/containers/not-owned/exec')]:
     c=Connection('local');c.request(method,path,body=b'{}',headers={'Content-Type':'application/json'});r=c.getresponse();self.assertEqual(r.status,403,path);r.read();c.close()
   finally:server.shutdown();server.server_close()
 def test_docker_proxy_retains_daemon_api_version_negotiation(self):
  m=self.module()
  import http.client,socket,threading,unittest.mock
  class Response:
   status=200
   def getheader(self,k,default=None):return {'Api-Version':'1.52','Content-Type':'text/plain'}.get(k,default)
   def read(self,_):return b'OK'
  class Upstream:
   def request(self,*args,**kwargs):pass
   def getresponse(self):return Response()
   def close(self):pass
  with tempfile.TemporaryDirectory() as t,unittest.mock.patch.object(m,'UnixHTTP',Upstream):
   server=m.DockerProxy(str(Path(t)/'policy.sock'),m.DockerHandler);server.deadline=m.time.time()+10;server.job=Path(t);threading.Thread(target=server.serve_forever,daemon=True).start()
   try:
    c=http.client.HTTPConnection('local');c.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);c.sock.connect(str(Path(t)/'policy.sock'));c.request('GET','/_ping');r=c.getresponse();self.assertEqual(r.getheader('Api-Version'),'1.52');r.read();c.close()
   finally:server.shutdown();server.server_close()
 def test_pentagi_worker_deadline_never_exceeds_parent_remaining_time(self):
  m=self.module();p=m.PentagiDockerPolicy('joint-'+'a'*40,'/source','sha256:'+'b'*64);p.deadline=m.time.time()+7
  safe=p.create({});entry=safe['Entrypoint'];self.assertLessEqual(int(entry[3].removesuffix('s')),7)
 def test_completion_needs_all_declared_subtasks_and_nonempty_results(self):
  m=self.module();done={'status':'finished','result':'unverified static review'}
  self.assertTrue(m.finished_scope({'data':{'tasks':[{'status':'running','subtasks':[done]}]}}))
  for graph in [{'data':{'tasks':[]}}, {'data':{'tasks':[{'status':'running','subtasks':[done,{'status':'created','result':''}]}]}}, {'data':{'tasks':[{'status':'running','subtasks':[{'status':'finished','result':''}]}]}}, {'data':{'tasks':[{'status':'waiting','subtasks':[done]}]}}]:self.assertFalse(m.finished_scope(graph))
if __name__=='__main__':unittest.main()
