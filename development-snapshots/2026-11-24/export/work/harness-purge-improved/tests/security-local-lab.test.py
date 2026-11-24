import http.client,importlib.util,json,threading,unittest,urllib.parse
from pathlib import Path
SOURCE=Path(__file__).parents[1]/'package/scripts/security-local-lab.py'

class LocalLoginLab(unittest.TestCase):
 def test_real_local_login_protects_pages_and_ledger_omits_credentials(self):
  self.assertTrue(SOURCE.is_file(),'Local login lab is missing')
  spec=importlib.util.spec_from_file_location('local_lab',SOURCE);lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)
  state=lab.LocalLab();server=lab.build_lab_server(0,state,'http://127.0.0.1:19091');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  def request(method,path,body=None,headers=None):
   connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
   try:
    connection.request(method,path,body,headers or {});response=connection.getresponse();return response.status,dict(response.getheaders()),response.read(65537)
   finally:connection.close()
  try:
   self.assertEqual(request('GET','/account')[0],401)
   self.assertEqual(request('GET','/account',headers={'Cookie':'lab_session=WRONG_CANARY_TOKEN'})[0],401)
   status,headers,_=request('POST','/login',urllib.parse.urlencode({'username':state.username,'password':state.password}),{'Content-Type':'application/x-www-form-urlencoded'})
   self.assertEqual(status,303);cookie=headers['Set-Cookie'].split(';',1)[0];status,_,body=request('GET','/account',headers={'Cookie':cookie});self.assertEqual(status,200);self.assertIn(b'HARNESS_AUTHENTICATED',body)
   self.assertEqual(request('POST','/test/invalidate',headers={'Cookie':cookie})[0],200);self.assertEqual(request('GET','/account',headers={'Cookie':cookie})[0],401)
   ledger=json.dumps(state.events);self.assertNotIn(state.password,ledger);self.assertNotIn(cookie,ledger);self.assertTrue(any(row['authenticated'] for row in state.events))
  finally:server.shutdown();server.server_close();thread.join(timeout=2)


class ControlledSessionRenewal(unittest.TestCase):
 def test_real_node_renewal_uses_private_stdin_and_preserves_original(self):
  import datetime,os,shutil,tempfile,types
  node=shutil.which('node');self.assertIsNotNone(node,'Existing Node runtime required')
  spec=importlib.util.spec_from_file_location('renew_lab',SOURCE);lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab);self.assertTrue(callable(getattr(lab,'renew_session',None)),'Controlled session renewal CLI adapter is missing')
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();root.chmod(0o700);lab.AUTH=root;lab.NODE=Path(node)
   old={'version':1,'revision':'879b1b08-0a7d-4f84-9f1d-d50cb7f94072','origin':'http://127.0.0.1:18080','header':'Cookie','value':'sid=OLD_CANARY_SESSION_123456789','verifyPath':'/account','loggedInMarker':'HARNESS_AUTHENTICATED','excludePaths':['/logout'],'expiresAt':'2000-01-01T00:00:00Z'}
   file=root/'old-login.json';lab.write_private(file,old);before=file.read_bytes();args=types.SimpleNamespace(from_profile='old-login',to_profile='fresh-login',origin=old['origin'],expected_revision=old['revision'],confirm=True)
   data={'value':'sid=NEW_CANARY_SESSION_987654321','expiresAt':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=20)).isoformat()}
   result=lab.renew_session(args,data);self.assertEqual(result['profile'],'fresh-login');self.assertNotEqual(result['revision'],old['revision']);self.assertEqual(file.read_bytes(),before);self.assertNotIn('CANARY',json.dumps(result));self.assertEqual(json.loads((root/'fresh-login.json').read_text())['value'],data['value']);self.assertEqual((root/'fresh-login.json').stat().st_mode&0o777,0o600)
   with self.assertRaises(lab.SafeError):lab.renew_session(args,data)
   self.assertEqual(file.read_bytes(),before)

if __name__=='__main__':unittest.main()
