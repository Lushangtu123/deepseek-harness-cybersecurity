"""Rerun the already-used diagnostic, preserving original receipts; not new qualification."""
from pathlib import Path
from hashlib import sha256
import base64,datetime,gzip,importlib.util,json,sys,uuid
if sys.flags.optimize:raise RuntimeError('Run without Python optimization')
w=Path(__file__).resolve().parent;plan=json.loads((w/'protocol-v3.json').read_text());files={'probe.py':(w/'probe-v3.py').read_bytes(),'protocol.json':(w/'protocol-v3.json').read_bytes(),'wheels.json':(w/'runtime-wheels.json').read_bytes()};assert sha256(files['probe.py']).hexdigest()==plan['probeSha256']
for variant in ['vulnerable','patched']:
 n='src/'+variant+'.py';files[n]=(w/(variant+'.py')).read_bytes();assert sha256(files[n]).hexdigest()==plan['inputs']['/'+n]
for row in json.loads(files['wheels.json']):
 name=row['filename'];assert Path(name).name==name;raw=(w/'wheels'/name).read_bytes();assert sha256(raw).hexdigest()==row['sha256'];files['wheels/'+name]=raw
payload=base64.b64encode(gzip.compress(json.dumps({n:base64.b64encode(raw).decode() for n,raw in files.items()}).encode())).decode();remote=(w/'oracle-remote-v3.py').read_text()
spec=importlib.util.spec_from_file_location('manager',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate();receipt=w/('diagnostic-rerun-'+str(uuid.uuid4())+'.json')
try:
 r=m.ssh('python3 -B -',input='PAYLOAD='+repr(payload)+'\n'+remote,timeout=90,phase='native-check');value={'scope':'already-used diagnostic rerun; not new independent qualification','r3Qualified':False,'receipt':json.loads(r.stdout)}
except m.SSHFailure as e:
 receipt.write_text(json.dumps({'scope':'failed diagnostic rerun','r3Qualified':False,'stdout':e.stdout,'stderr':e.stderr},indent=2)+'\n');raise
receipt.write_text(json.dumps(value,indent=2)+'\n');print(str(receipt))
