from pathlib import Path
from hashlib import sha256
import base64,gzip,importlib.util,json
w=Path(__file__).resolve().parent;out=w.parents[1]/'exports/deepseek-harness-vm/docs/security-workspace/oracles/pymatgen-20261103';files={p.name:base64.b64encode(p.read_bytes()).decode() for p in out.iterdir() if p.is_file() and p.name!='manifest.json'};payload=base64.b64encode(gzip.compress(json.dumps(files).encode())).decode();expected=json.loads((w/'consistency.json').read_text())
source='PAYLOAD='+repr(payload)+'\nEXPECTED='+repr(expected)+'\n'+r'''
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import base64,gzip,json,subprocess
program=Path('/home/purge/tools/dsh-purge-personal-1.1.77-personal.1');inventory=lambda:{str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts};before=inventory()
with TemporaryDirectory(prefix='cve-consistency-',dir='/home/purge/.cache') as tmp:
 root=Path(tmp)
 for n,raw in json.loads(gzip.decompress(base64.b64decode(PAYLOAD))).items():
  assert Path(n).name==n;(root/n).write_bytes(base64.b64decode(raw))
 r=subprocess.run(['/usr/bin/python3','-I','-B',str(root/'check-evidence.py'),'--program',str(program),'--ledger',str(root/'ledger-after.json')],capture_output=True,text=True,timeout=15);assert r.returncode==0,r.stderr;value=json.loads(r.stdout);assert value==EXPECTED
assert not root.exists() and inventory()==before;print(json.dumps({'ok':True,'MacAndVMResultsIdentical':True,'dailyProgramFilesMatched':len(before),'temporaryRemoved':True,'sourceExecutionDuringConsistencyCheck':False,'result':value}))
'''
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate();v=json.loads(m.ssh('python3 -B -',input=source,timeout=30,phase='native-check').stdout);(w/'consistency-vm.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
