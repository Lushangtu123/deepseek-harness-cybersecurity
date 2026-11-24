from pathlib import Path
import base64,gzip,importlib.util,json
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm'
files={}
for name in ['proof-contract.mjs','proof-contract.test.mjs','container-absence.mjs','container-absence.test.mjs']:files[name]=base64.b64encode((w/name).read_bytes()).decode()
for name in ['package/lib/redteam/personal-security-client.mjs','tests/joint-source-client.test.mjs']:files[name]=base64.b64encode((repo/'work/harness-purge-improved'/name).read_bytes()).decode()
files['diagnosis.json']=base64.b64encode((w/'cleanup-diagnosis.json').read_bytes()).decode()
source='PAYLOAD='+repr(base64.b64encode(gzip.compress(json.dumps(files).encode())).decode())+'\n'+r"""
from pathlib import Path
from tempfile import TemporaryDirectory
import base64,gzip,json,subprocess
files=json.loads(gzip.decompress(base64.b64decode(PAYLOAD)))
with TemporaryDirectory(prefix='source-location-closure-check-',dir='/home/purge/.cache') as tmp:
 root=Path(tmp)
 for n,b in files.items():
  p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(b))
 node='/home/purge/.local/node/bin/node';r=subprocess.run([node,'--test','proof-contract.test.mjs','container-absence.test.mjs','tests/joint-source-client.test.mjs'],cwd=root,capture_output=True,text=True,timeout=30);assert r.returncode==0,r.stdout+r.stderr
 replay="import {absenceReply} from './container-absence.mjs';import fs from 'node:fs';import assert from 'node:assert/strict';const v=JSON.parse(fs.readFileSync('diagnosis.json'));const e=v.containerById;const id=e.stderr.trim().split(': ').at(-1);assert.ok(absenceReply({status:e.code,stdout:e.stdout,stderr:e.stderr},id));assert.equal(v.imageControl.code,0);console.log(JSON.stringify({ok:true,actualLowercaseDockerErrorReplayed:true}));"
 p=subprocess.run([node,'--input-type=module','-e',replay],cwd=root,capture_output=True,text=True,timeout=10);assert p.returncode==0,p.stderr
 out={'ok':True,'testOutput':r.stdout+r.stderr,'replay':json.loads(p.stdout)}
assert not root.exists();out['temporaryRemoved']=True
print(json.dumps(out))
"""
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
v=json.loads(m.ssh('python3 -B -',input=source,timeout=45,phase='native-check').stdout);(w/'focused-native.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({k:v for k,v in v.items() if k!='testOutput'}));print('\n'.join(v['testOutput'].splitlines()[-8:]))
