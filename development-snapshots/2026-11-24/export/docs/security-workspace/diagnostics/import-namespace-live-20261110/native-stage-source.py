
from pathlib import Path,PurePosixPath
from tempfile import mkdtemp
from hashlib import sha256
import base64,gzip,json,os,signal,sqlite3,subprocess,time
os.umask(0o077)
home=Path('/home/purge');program=home/'tools/dsh-purge-personal-1.1.77-personal.1';runtime=home/'tools/security-workbench';payload=json.loads(gzip.decompress(base64.b64decode(PAYLOAD)))
def protected():
 program_files={str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
 databases={}
 for p in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
  digest=sha256()
  with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
   for row in db.iterdump():digest.update((row+'\n').encode())
  databases[str(p)]=digest.hexdigest()
 pins={n:sha256((runtime/n).read_bytes()).hexdigest() for n in ['images.json','rules.json']}
 config={str(p):sha256(p.read_bytes()).hexdigest() for p in [home/'.dsh-improved/.credentials.yaml',home/'.dsh-improved/cordis.patch.yml'] if p.is_file()}
 return {'program':program_files,'databases':databases,'pins':pins,'config':config}
before=protected();assert len(before['program'])==169
root=Path(mkdtemp(prefix='import-namespace-live-',dir=home/'.cache'))
(root/'owned-session').write_text('import-namespace-live-20261110')
for name,encoded in payload['files'].items():
 rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts
 raw=base64.b64decode(encoded);assert sha256(raw).hexdigest()==payload['intent']['files'][name]
 p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
assert len([n for n in payload['files'] if n.startswith('package/')])==173
assert all(sha256((root/n).read_bytes()).hexdigest()==v for n,v in payload['intent']['files'].items())
(root/'protected-before.json').write_text(json.dumps(before));(root/'stage-intent.json').write_text(json.dumps(payload['intent']))
with (root/'session.log').open('w') as output:
 child=subprocess.Popen([str(home/'.local/node/bin/node'),str(root/'browser-service.mjs')],cwd=root,stdout=output,stderr=output,start_new_session=True)
for attempt in range(160):
 data=(root/'session.log').read_text()
 for line in data.splitlines():
  try:v=json.loads(line)
  except ValueError:continue
  if v.get('browserReady'):
   assert protected()==before
   print(json.dumps({**v,'root':str(root),'pid':child.pid,'programFilesProtected':169,'databasesProtected':len(before['databases']),'noApiKeysCopied':True}));raise SystemExit(0)
 if child.poll() is not None:raise RuntimeError('Isolated service failed: '+data[-6000:])
 time.sleep(.25)
os.killpg(child.pid,signal.SIGTERM)
raise RuntimeError('Isolated service readiness timeout')
