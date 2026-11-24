"""Synthetic model budget checks: no provider, Docker or paid model calls."""
from pathlib import Path
import importlib.util,json,tempfile,unittest,concurrent.futures
FILE=Path(__file__).resolve().parents[1]/'package/scripts/security-joint-adapter.py'
spec=importlib.util.spec_from_file_location('adapter_counts',FILE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ModelCountsTest(unittest.TestCase):
 def fixture(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);return Path(tmp.name)/'budget.json'
 def initialized(self,path,**kwargs):
  b=m.ModelBudget(path,**kwargs);b.initialize();return b
 def test_missing_counter_never_starts_at_zero(self):
  p=self.fixture()
  with self.assertRaises(ValueError):m.ModelBudget(p).reserve({})
  self.assertFalse(p.exists())
 def test_initialization_is_explicit_and_cannot_overwrite_or_reset(self):
  p=self.fixture();b=self.initialized(p);self.assertEqual(b.snapshot()['calls'],0);b.reserve({})
  with self.assertRaises(ValueError):b.initialize()
  self.assertEqual(m.ModelBudget(p).snapshot()['calls'],1)
 def test_deleted_counter_does_not_reinitialize_on_resume(self):
  p=self.fixture();b=self.initialized(p);b.reserve({});p.unlink()
  with self.assertRaises(ValueError):m.ModelBudget(p).reserve({})
 def test_invalid_or_wrong_identity_counters_reject_forwarding(self):
  for mutate in [lambda v:v.update(calls=-1),lambda v:v.update(calls=True),lambda v:v.update(identity='different'),lambda v:v.update(maxCalls=999),lambda v:v.update(usage='bad')]:
   p=self.fixture();b=self.initialized(p);v=b.snapshot();mutate(v);m.atomic(p,v)
   with self.assertRaises(ValueError):b.reserve({})
 def test_concurrent_instances_share_one_reservation_limit(self):
  p=self.fixture();self.initialized(p,max_calls=3)
  def reserve(_):
   try:m.ModelBudget(p,max_calls=3).reserve({});return 1
   except ValueError:return 0
  with concurrent.futures.ThreadPoolExecutor(12) as pool:self.assertEqual(sum(pool.map(reserve,range(40))),3)
  self.assertEqual(m.ModelBudget(p,max_calls=3).snapshot()['calls'],3)
 def test_status_projection_keeps_missing_unknown_and_legacy_number_labeled(self):
  p=self.fixture();job=p.parent;v={'tool':'pentagi','modelCalls':0};before=json.dumps(v)
  out=m.model_count_view(job,v);self.assertIsNone(out['modelCalls']);self.assertEqual(out['modelCallsState'],'legacy');self.assertEqual(out['modelCallsRecorded'],0);self.assertEqual(json.dumps(v),before)
 def test_valid_counter_can_prove_zero_but_corrupt_counter_cannot(self):
  p=self.fixture();b=self.initialized(p);v={'tool':'pentagi','modelCallsProtocol':1};out=m.model_count_view(p.parent,v);self.assertEqual(out['modelCalls'],0);self.assertEqual(out['modelCallsState'],'verified')
  m.atomic(p,{'calls':0});out=m.model_count_view(p.parent,v);self.assertIsNone(out['modelCalls']);self.assertEqual(out['modelCallsState'],'unknown')
 def test_reservation_syncs_parent_directory_before_returning(self):
  import os,stat
  from unittest.mock import patch
  p=self.fixture();b=self.initialized(p);seen=[];original=os.fsync
  def observe(fd):seen.append(stat.S_ISDIR(os.fstat(fd).st_mode));return original(fd)
  with patch.object(m.os,'fsync',observe):b.reserve({})
  self.assertIn(True,seen)
 def test_synthetic_gateway_refuses_missing_counter_without_forwarding(self):
  import threading,http.client
  from unittest.mock import patch
  p=self.fixture();server=m.Gateway(('127.0.0.1',0),m.GatewayHandler);server.nonce='synthetic';server.key='not-a-real-key';server.deadline=m.time.time()+10;server.budget=m.ModelBudget(p)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with patch.object(m.urllib.request,'build_opener') as opener:
    c=http.client.HTTPConnection(*server.server_address);c.request('POST','/chat/completions',body=b'{}',headers={'Authorization':'Bearer synthetic'});r=c.getresponse();self.assertEqual(r.status,429);r.read();c.close();opener.assert_not_called()
  finally:server.shutdown();server.server_close()
if __name__=='__main__':unittest.main()
