from pathlib import Path
import base64,hashlib,importlib.util,json,tempfile,unittest
p=Path(__file__).resolve().parents[1]/'package/scripts/security-kali-project.py'
class KaliProjectTests(unittest.TestCase):
 def test_handoff_is_bounded_and_cannot_escape_or_replace_credential_files(self):
  self.assertTrue(p.is_file(),'Fixed project handoff adapter is missing')
  spec=importlib.util.spec_from_file_location('joint_kali',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  raw=b'eval(input())\n';payload={'snapshotId':'a'*64,'seconds':30,'files':[{'path':'app.py','sha256':hashlib.sha256(raw).hexdigest(),'content':base64.b64encode(raw).decode()}]}
  self.assertEqual(m.validate_payload(payload)['files'][0]['path'],'app.py')
  for path in ['../app.py','/tmp/app.py','.ssh/config.py','nested/../../app.py','app.py\n','secret.key','node_modules/a.py']:
   bad=json.loads(json.dumps(payload));bad['files'][0]['path']=path
   with self.assertRaises(ValueError):m.validate_payload(bad)
  bad=json.loads(json.dumps(payload));bad['files'][0]['sha256']='b'*64
  with self.assertRaises(ValueError):m.validate_payload(bad)
  bad=json.loads(json.dumps(payload));bad['command']='id'
  with self.assertRaises(ValueError):m.validate_payload(bad)
if __name__=='__main__':unittest.main()
