from pathlib import Path
import ast,base64,gzip,importlib.util,json,sys
from hashlib import sha256
w=Path(__file__).resolve().parent;revision=sys.argv[1] if sys.argv[1:] else 'v1';assert revision in ['v1','v2','v3'];protocolFile='protocol.json' if revision=='v1' else 'protocol-'+revision+'.json';probeFile='probe.py' if revision=='v1' else 'probe-'+revision+'.py';plan=json.loads((w/protocolFile).read_text());assert sha256((w/probeFile).read_bytes()).hexdigest()==plan['probeSha256']
files={'probe.py':(w/probeFile).read_bytes()};files['protocol.json']=(w/protocolFile).read_bytes();files['wheels.json']=(w/'runtime-wheels.json').read_bytes()
for v in ['vulnerable','patched']:files['src/'+v+'.py']=(w/(v+'.py')).read_bytes();assert sha256(files['src/'+v+'.py']).hexdigest()==plan['inputs']['/src/'+v+'.py']
for row in json.loads((w/'runtime-wheels.json').read_text()):files['wheels/'+row['filename']]=(w/'wheels'/row['filename']).read_bytes()
payload=base64.b64encode(gzip.compress(json.dumps({n:base64.b64encode(v).decode() for n,v in files.items()}).encode())).decode()
old=ast.parse((w.parent/'harness-independent-oracle-20261103/run-native-oracle-v2.py').read_text());n=next(n for n in old.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='source' for t in n.targets));remote=n.value.right.value
remote=remote.replace("assert total<=12*1024*1024 and entry.file_size<=2*1024*1024","assert total<=140*1024*1024 and entry.file_size<=25*1024*1024")
remote=remote.replace("root/'protocol.json').read_text());assert", "root/'protocol.json').read_text());assert program_before==plan['candidateProgram'];assert")
remote=remote.replace("'--env','HOME=/tmp'","'--env','HOME=/tmp','--env','OPENBLAS_NUM_THREADS=1','--env','OMP_NUM_THREADS=1'")
remote=remote.replace('timeout -s KILL 15s python3 -I -S /probe.py','timeout -s KILL 30s python3 -I -S -B /probe.py').replace('timeout=22','timeout=40')
(w/('oracle-remote-'+revision+'.py')).write_text(remote)
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
try:r=m.ssh('python3 -B -',input='PAYLOAD='+repr(payload)+'\n'+remote,timeout=90,phase='native-check')
except m.SSHFailure as e:
 (w/('oracle-'+revision+'-failure.json')).write_text(json.dumps({'stdout':e.stdout,'stderr':e.stderr,'summary':str(e)},indent=2)+'\n');raise
v=json.loads(r.stdout);(w/('oracle-'+revision+'.json')).write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({k:v for k,v in v.items() if k!='result'}))
