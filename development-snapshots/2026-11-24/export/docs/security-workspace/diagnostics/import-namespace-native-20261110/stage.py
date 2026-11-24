from pathlib import Path
from hashlib import sha256
import base64, gzip, importlib.util, json

root=Path(__file__).resolve().parent
if (root/'stage-attempt.json').exists():raise ValueError('Inspect original attempt; do not submit again')
repo=root.parents[1]/'exports/deepseek-harness-vm'
baseline=json.loads((root/'baseline.json').read_text())
files={}
for name,want in baseline['program'].items():
    p=repo/'work/harness-purge-improved/package'/name
    if p.is_symlink() or p.resolve()!=p or sha256(p.read_bytes()).hexdigest()!=want:raise ValueError('Candidate drift')
    files['package/'+name]=p.read_bytes()
for name in ['controls.json','seed.mjs','native-contract.mjs','qa-fence.mjs','proof-contract.mjs',
             'test-service.mjs','run-app.py','activate-security.py','namespace-init.py']:
    files[name]=(root/name).read_bytes()
envelope={'files':{name:base64.b64encode(raw).decode() for name,raw in files.items()},
    'hashes':{name:sha256(raw).hexdigest() for name,raw in files.items()},
    'programDigest':baseline['programManifestSha256']}
(root/'staging-manifest.json').write_text(json.dumps(envelope['hashes'],indent=2)+'\n')
payload=base64.b64encode(gzip.compress(json.dumps(envelope).encode())).decode()
source='PAYLOAD='+repr(payload)+'\n'+(root/'stage-guest.py').read_text()
(root/'stage-attempt.json').write_text(json.dumps({'sourceSha256':sha256(source.encode()).hexdigest(),
    'state':'intent-before-submit','programFiles':173})+'\n')
spec=importlib.util.spec_from_file_location('b',root/'vm-bridge.py');bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
value=bridge.call(source,55)
(root/'stage.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value));raise SystemExit(0 if value.get('ready') else 1)
