"""Independent v1 verifier closure: trusted shipped code, offline dependencies and data-only recipes."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import os
import re
import shutil
import stat

HERE=Path(__file__).resolve().parent
CODE=('eval_evidence_batch.py','eval_guard_review.py','eval_import_review.py','python_execution_verify.py')
POLICY={'version':1,'maxInputs':4,'inputSeconds':5,'pointSeconds':30,'memoryMiB':512,'cpus':1,'pids':64,'tmpMiB':32,'outputBytes':262144,'network':'none','proof':'python-narrow-literal-1'}
PROBES=["control-literal-v1","expression-with-frozen-random-challenge-v1","statement-with-frozen-random-challenge-v1","syntax-error-v1"]
def digest(v):return sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
def launcher():
 spec=importlib.util.spec_from_file_location('verifier_controller',HERE/'reviewer_snapshot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def safe(n):return isinstance(n,str) and len(n)<=240 and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./+~-]*',n) and all(p not in {'','..','.'} for p in n.split('/'))
def tree(root,expected):
 root=Path(root)
 if root.resolve()!=root or not isinstance(expected,dict) or len(expected)>1000:raise ValueError('Invalid dependency root')
 result={};total=0;directories=0
 def walk(fd,prefix='',depth=0):
  nonlocal total,directories
  st=os.fstat(fd);directories+=1
  if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.geteuid() or st.st_mode&0o022 or depth>16 or directories>1000:raise ValueError('Invalid dependency directory')
  for name in sorted(os.listdir(fd)):
   n=prefix+name
   if not safe(n):raise ValueError('Invalid dependency name')
   st=os.stat(name,dir_fd=fd,follow_symlinks=False)
   if stat.S_ISDIR(st.st_mode):
    child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
    try:walk(child,n+'/',depth+1)
    finally:os.close(child)
   else:
    if not stat.S_ISREG(st.st_mode):raise ValueError('Linked or special dependency')
    if n not in expected or len(result)>=1000:raise ValueError('Unexpected dependency')
    file=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    try:
     before=os.fstat(file)
     if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or before.st_nlink!=1 or before.st_size>4*1024*1024:raise ValueError('Invalid dependency file')
     with os.fdopen(os.dup(file),'rb') as stream:raw=stream.read(4*1024*1024+1)
     after=os.fstat(file)
     if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or len(raw)!=before.st_size:raise ValueError('Dependency changed during read')
     total+=len(raw)
     if total>16*1024*1024 or sha256(raw).hexdigest()!=expected[n]:raise ValueError('Dependency digest mismatch')
     result[n]=raw
    finally:os.close(file)
 fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:walk(fd)
 finally:os.close(fd)
 if set(result)!=set(expected):raise ValueError('Missing dependency')
 return result

def contract(v):
 # Shipped worker is trusted tool code; never import a module selected by project/recipe.
 path=HERE/'python_execution_verify.py';spec=importlib.util.spec_from_file_location('trusted_verifier_contract',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m.validate_contract(v)
def approved_sources():
 path=HERE/'python_execution_verify.py';spec=importlib.util.spec_from_file_location('trusted_verifier_profiles',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m.APPROVED_SOURCES

def trusted_dependency_lock():
 return json.loads((HERE/'verifier-dependencies.lock.json').read_bytes())

def freeze(static_bundle,static_sha,dependencies,lock,contracts,destination):
 api=launcher();snapshot,verified=api.verify(Path(static_bundle),static_sha);code={n:verified[n] for n in CODE[:3]}
 if lock!=trusted_dependency_lock():raise ValueError('Untrusted verifier dependency lock')
 deps=tree(dependencies,lock.get('files'))
 if not isinstance(contracts,list) or not 1<=len(contracts)<=64:raise ValueError('Recipe limit')
 recipes={digest(contract(v)):v for v in contracts}
 if len(recipes)!=len(contracts):raise ValueError('Duplicate recipe')
 raw=(HERE/'python_execution_verify.py').read_bytes();code['python_execution_verify.py']=raw
 value={'version':1,'kind':'python-execution-verifier','code':{n:sha256(v).hexdigest() for n,v in code.items()},'staticSnapshot':snapshot,'staticSha256':static_sha,'imageId':snapshot['imageId'],'pythonVersion':'3.12.15','sourceProfiles':approved_sources(),'dependencies':lock['files'],'dependencyPackages':lock['packages'],'recipes':recipes,'policy':POLICY,'probes':PROBES,'controllerSha256':sha256((HERE/'reviewer_snapshot.py').read_bytes()).hexdigest(),'verifierControllerSha256':sha256(Path(__file__).read_bytes()).hexdigest(),'storageSha256':snapshot['storageSha256']}
 dest=Path(destination)
 if dest.resolve()!=dest:raise ValueError('Canonical destination required')
 dest.mkdir(mode=0o700,parents=False,exist_ok=False)
 (dest/'dependencies').mkdir(mode=0o755)
 for n,data in {**{'code/'+k:v for k,v in code.items()},**{'dependencies/'+k:v for k,v in deps.items()}}.items():
  path=dest/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o444)
 (dest/'verifier.json').write_text(json.dumps(value,indent=2)+'\n');return value

def verify(bundle,expected):
 api=launcher();bundle=Path(bundle)
 if bundle.resolve()!=bundle or bundle.stat().st_uid!=os.geteuid() or bundle.stat().st_mode&0o077:raise ValueError('Private canonical verifier required')
 value=api.load_json(api.read(bundle/'verifier.json'))
 if (not isinstance(value,dict) or value.get('version')!=1 or value.get('kind')!='python-execution-verifier' or digest(value)!=expected
     or set(value.get('code',{}))!=set(CODE) or value.get('policy')!=POLICY or value.get('probes')!=PROBES
     or value.get('staticSha256')!=digest(value.get('staticSnapshot')) or value.get('imageId')!=value['staticSnapshot'].get('imageId')
     or value.get('controllerSha256')!=sha256((HERE/'reviewer_snapshot.py').read_bytes()).hexdigest()
     or value.get('verifierControllerSha256')!=sha256(Path(__file__).read_bytes()).hexdigest()
     or value.get('storageSha256')!=sha256((HERE/'reviewer_storage.py').read_bytes()).hexdigest()):raise ValueError('Verifier identity mismatch')
 if value.get('sourceProfiles')!=approved_sources():raise ValueError('Source profile mismatch')
 if value['pythonVersion']!='3.12.15' or value['staticSnapshot'].get('version')!=2:raise ValueError('Verifier runtime mismatch')
 lock=trusted_dependency_lock()
 if value.get('dependencies')!=lock['files'] or value.get('dependencyPackages')!=lock['packages']:raise ValueError('Untrusted verifier dependency lock')
 code=tree(bundle/'code',value['code']);deps=tree(bundle/'dependencies',value['dependencies'])
 for n in CODE[:3]:
  if value['code'][n]!=value['staticSnapshot']['files'].get(n):raise ValueError('Static closure mismatch')
 if value['code']['python_execution_verify.py']!=sha256((HERE/'python_execution_verify.py').read_bytes()).hexdigest():raise ValueError('Untrusted verifier worker')
 if not isinstance(value.get('recipes'),dict) or not 1<=len(value['recipes'])<=64 or any(digest(contract(v))!=k for k,v in value['recipes'].items()):raise ValueError('Invalid frozen recipes')
 return value,{**{'code/'+n:raw for n,raw in code.items()},**{'dependencies/'+n:raw for n,raw in deps.items()}}
