#!/usr/bin/env python3
"""Build a VM-only frozen dependency image without project build/install hooks."""
from pathlib import Path
import hashlib,json,os,shutil,stat,subprocess,sys,tempfile
from email.parser import Parser

def digest(value):return hashlib.sha256(json.dumps(value,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def inventory(root):
 root=Path(root)
 if root.resolve()!=root or not root.is_dir():raise ValueError('Dependency root must be ordinary')
 rows=[];total=0
 for p in sorted(root.rglob('*')):
  if '__pycache__' in p.parts or p.suffix=='.pyc':continue
  st=p.lstat()
  if stat.S_ISLNK(st.st_mode) or p.resolve()!=p:raise ValueError('Dependency links are not admitted')
  if stat.S_ISDIR(st.st_mode):continue
  if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>64*1024*1024:raise ValueError('Dependency file is not bounded ordinary data')
  raw=p.read_bytes();after=p.stat()
  if len(raw)!=st.st_size or after.st_mtime_ns!=st.st_mtime_ns or after.st_ctime_ns!=st.st_ctime_ns:raise ValueError('Dependency changed while reading')
  total+=len(raw);rows.append({'path':str(p.relative_to(root)),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
  if len(rows)>10000 or total>400*1024*1024:raise ValueError('Dependency tree exceeds bounds')
 return rows

def freeze_dependencies(root,target,lock):
 rows=inventory(root)
 if digest(rows)!=lock['dependencyTreeSha256'] or len(rows)!=lock['dependencyFiles'] or sum(r['bytes'] for r in rows)!=lock['dependencyBytes']:raise ValueError('Installed dependency tree differs from lock')
 target.mkdir(mode=0o755)
 for row in rows:
  p=target/row['path'];p.parent.mkdir(parents=True,exist_ok=True,mode=0o755);raw=(root/row['path']).read_bytes()
  if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Dependency changed before copy')
  with p.open('xb') as f:f.write(raw)
  p.chmod(0o444)
 if inventory(root)!=rows or inventory(target)!=rows:raise ValueError('Frozen dependency verification failed')
 return rows

def main():
 if sys.argv[1:]!=['--confirm-build'] or sys.platform!='linux' or os.getuid()!=1000 or os.environ.get('DSH_HOME')!='/home/purge/.dsh-improved' or os.uname().machine not in ['aarch64','arm64']:raise ValueError('Dedicated ARM64 VM and explicit build confirmation required')
 lock=json.loads(Path(__file__).with_name('security-runtime-phishguard-lock.json').read_text());home=Path('/home/purge');project=home/'workspace/Phishing-Scam-Email-Detection';source=project/'.venv/lib/python3.12/site-packages'
 if hashlib.sha256((project/'requirements.txt').read_bytes()).hexdigest()!=lock['sourceRequirementSha256']:raise ValueError('Project requirements changed')
 versions=[]
 for p in sorted(source.glob('*.dist-info/METADATA')):
  v=Parser().parsestr(p.read_text());versions.append({'name':v['Name'],'version':v['Version']})
 if lock['baseImageTag']!='harness-pentagi-worker:20261025':raise ValueError('Unreviewed base image name')
 if versions!=lock['packages']:raise ValueError('Installed package versions changed')
 if shutil.disk_usage(home).free<2*1024**3:raise ValueError('Insufficient VM reserve for dependency image')
 root=home/'.dsh-improved/runtime-templates';root.mkdir(parents=True,exist_ok=True,mode=0o700)
 if root.resolve()!=root or root.stat().st_mode&0o077:raise ValueError('Private template root required')
 work=root/('build-'+lock['dependencyTreeSha256']+'-'+lock['baseImageId'][7:19]);work.mkdir(mode=0o700)
 rows=freeze_dependencies(source,work/'deps',lock);(work/'dependency-files.json').write_text(json.dumps(rows,separators=(',',':')));(work/'dependency-files.json').chmod(0o400)
 def docker(*args,timeout=120):
  try:return subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker',*args],text=True,timeout=timeout,stderr=subprocess.PIPE).strip()
  except subprocess.CalledProcessError as error:raise RuntimeError(error.stderr[-3000:]) from None
 base=json.loads(docker('image','inspect',lock['baseImageTag']))[0]
 if base['Id']!=lock['baseImageId']:raise ValueError('Base image identity changed')
 recipe='FROM '+lock['baseImageTag']+'\nCOPY deps/ /opt/harness-deps/\nLABEL personal.harness.template="phishguard-fastapi-v1" personal.harness.dependencies="'+lock['dependencyTreeSha256']+'" personal.harness.base="'+lock['baseImageId']+'"\n'
 (work/'Dockerfile').write_text(recipe);tag='personal-runtime/phishguard-fastapi:'+lock['dependencyTreeSha256'][:16]+'-'+lock['baseImageId'][7:19]
 docker('build','--network=none','--pull=false','--quiet','--tag',tag,str(work),timeout=180)
 info=json.loads(docker('image','inspect',tag))[0]
 if info['RootFS']['Layers'][:len(base['RootFS']['Layers'])]!=base['RootFS']['Layers']:raise ValueError('Dependency image base layers changed')
 smoke="import sys,platform,json;sys.path.append('/opt/harness-deps');import fastapi,uvicorn,pydantic_core,numpy,scipy,sklearn;modules=[fastapi,uvicorn,pydantic_core,numpy,scipy,sklearn];assert sys.version_info[:2]==(3,12);assert all(m.__file__.startswith('/opt/harness-deps/') for m in modules);assert not any('site-packages' in p for p in sys.path);print(json.dumps({'python':sys.version.split()[0],'executable':sys.executable,'machine':platform.machine(),'sysPath':sys.path,'importOrigins':{m.__name__:m.__file__ for m in modules}}))"
 observed=json.loads(docker('run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','1000:1000','--memory','512m','--pids-limit','64','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=33554432,uid=1000,gid=1000','--env','OPENBLAS_NUM_THREADS=1','--entrypoint','/usr/bin/python3',info['Id'],'-I','-S','-B','-c',smoke,timeout=90))
 value={'version':1,'template':lock['template'],'imageId':info['Id'],'baseImageId':lock['baseImageId'],'dependencyTreeSha256':lock['dependencyTreeSha256'],'smoke':observed};target=root/'phishguard-fastapi-v1.json'
 fd,name=tempfile.mkstemp(prefix='.template-',dir=root)
 with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
 os.chmod(name,0o600);os.replace(name,target)
 print(json.dumps({'template':value['template'],'imageId':value['imageId'],'dependencyTreeSha256':value['dependencyTreeSha256'],'dependencyFiles':len(rows),'dependencyBytes':lock['dependencyBytes'],'smoke':observed,'networkDuringBuild':'none','projectBuildHooksExecuted':False,'installedProjectModified':False}))
if __name__=='__main__':main()
