#!/usr/bin/env python3
"""Build/check a credential-free offline asset bundle; install only over a pristine basic VM."""
from pathlib import Path,PurePosixPath
import argparse,gzip,hashlib,json,os,platform,posixpath,pwd,re,secrets,shutil,sqlite3,stat,subprocess,sys,tarfile,time,urllib.error,urllib.request

REPO=Path(__file__).resolve().parent.parent
HOME=Path('/home/purge')

COMPONENTS=['rea','reverse-skill','pentagi','security-scanners','original-capabilities','runtime-overrides','optional-plugins','codegraph']
ASSET_ROOTS=['tools/rea-runtime','tools/reverse-skill/reverse-skill-cab634bd855fc287f6e420c1f36fd1a6b9245960','tools/harness-improved-runtime','tools/harness-original-capabilities','tools/codegraph-1.6.2','tools/ghidra_12.1.4_PUBLIC','tools/imported-dsh-plugins-20261027T185822Z','.local/lib/node_modules','.dsh/profiles/web/node_modules']
SECURITY_FILES=['tools/security-workbench/'+name for name in ['images.json','rules.json','last-db-update.json','cache/db/trivy.db','cache/db/metadata.json']]
CONFIG_FILES=['.dsh/toolchain/reverse-tool-index.json','.dsh/toolchain/pentagi-cli.py','.dsh/toolchain/pentagi/pentagi.compose.yml','.dsh/toolchain/pentagi/Worker.Dockerfile','.dsh/toolchain/pentagi/deepseek-vm.provider.yml','.local/bin/dsh','.local/bin/harness-vm-web','.local/bin/reverse-route','.local/bin/reverse-case','.local/bin/codegraph','.local/bin/toolchain-versions','.config/harness-vm-mode','.config/harness-original-capabilities','.config/systemd/user/dsh-original.service','.config/systemd/user/dsh-original.service.d/30-personal-switch.conf','.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket','.dsh-improved/AGENTS.md','.dsh-improved/prompt-inject.md','.dsh-improved/cordis.patch.yml']
CONFIG_PREFIXES=['.dsh-improved/skills/','.dsh-improved/agent-presets/','.dsh-improved/tooling/']
MAX_BYTES=64*1024**3
IMAGES=[
 {'ref':'personal-security/semgrep:8a0b4b7d02bb','id':'sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7'},
 {'ref':'personal-security/trivy:c334fc962191','id':'sha256:4bad598527a6d97fa8e3296e0d8f68c3e2de7cdd40fecafa9ba12cd80f4c93a9'},
 {'ref':'personal-security/zap:403324289a6f','id':'sha256:422ac34a621bd46d5149f4e5032c660f0006c1c19085f9af61d2dc30eb531f04'},
 {'ref':'vxcontrol/pentagi:vm-cffed948','id':'sha256:dabcf08d64b8145ffd3f8b1cefe1fdcac365848c33eb2be6b3443cd3617136c4'},
 {'ref':'sha256:841d51ebcf46f4e98e15affc466f37be5492592863f04b6b4f479619938eb07a','id':'sha256:841d51ebcf46f4e98e15affc466f37be5492592863f04b6b4f479619938eb07a'},
 {'ref':'harness-pentagi-worker:20261025','id':'sha256:2a077741b88d6421e68ae45f0309bb149edc52a363fa596427a292cae12b1b1e'}]

def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def ordinary(path,limit=MAX_BYTES):
 if path.resolve()!=path:raise ValueError('Ordinary path required')
 info=path.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit:raise ValueError('Ordinary bounded file required')
 return info

def verify_bundle(bundle,want):
 bundle=Path(bundle)
 if bundle.resolve()!=bundle or not bundle.is_dir() or not re.fullmatch('[a-f0-9]{64}',want or ''):raise ValueError('Pinned ordinary bundle required')
 path=bundle/'manifest.json';ordinary(path,1024*1024)
 if digest(path)!=want:raise ValueError('Manifest identity mismatch')
 value=json.loads(path.read_text())
 if not isinstance(value,dict) or set(value)!={'schemaVersion','scope','platform','archives','components','images','payloadFiles','payloadBytes'} or value['schemaVersion']!=1 or value['scope']!='professional-offline-assets' or value['platform']!='linux/arm64' or value['components']!=COMPONENTS or value['images']!=IMAGES:raise ValueError('Unsupported asset manifest')
 if type(value['payloadFiles']) is not int or not 1<=value['payloadFiles']<=250000 or type(value['payloadBytes']) is not int or not 1<=value['payloadBytes']<=MAX_BYTES:raise ValueError('Invalid expanded payload inventory')
 if not isinstance(value['archives'],dict) or set(value['archives'])!={'programs.tgz','images.tar.gz'} or {p.name for p in bundle.iterdir()}!={'manifest.json','programs.tgz','images.tar.gz'}:raise ValueError('Unexpected bundle files')
 for name,row in value['archives'].items():
  if not isinstance(row,dict) or set(row)!={'sha256','bytes'} or not isinstance(row['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',row['sha256']) or type(row['bytes']) is not int or not 0<row['bytes']<=32*1024**3:raise ValueError('Invalid archive identity')
  path=bundle/name
  if ordinary(path).st_size!=row['bytes'] or digest(path)!=row['sha256']:raise ValueError('Archive identity mismatch')
 return value

def pristine_basic(home,program,owned_marker=None):
 home=Path(home)
 try:
  if home.resolve()!=home or not home.is_dir():return False
  for name in ['.config','.config/systemd','.config/systemd/user','tools','.local','.local/node','tools/harness-improved-runtime','tools/dsh-purge-personal-1.1.77-personal.1','.dsh-improved','.dsh-improved/profiles','.dsh-improved/profiles/web']:
   path=home/name
   if path.is_symlink() or path.exists() and (path.resolve()!=path or not path.is_dir()):return False
  for name in ['.dsh','.harness-professional','tools/rea-runtime','tools/security-workbench','tools/harness-original-capabilities']:
   path=home/name
   if name=='.harness-professional' and owned_marker is not None:
    info=path.lstat()
    if stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid() and not info.st_mode&0o077 and (info.st_dev,info.st_ino)==owned_marker:continue
   if path.exists() or path.is_symlink():return False
  path=home/'.harness-bootstrap/complete.json';ordinary(path,16384);marker=json.loads(path.read_text())
  if marker.get('ok') is not True or marker.get('scope')!='basic-harness-plugin-web':return False
  import bootstrap_guest
  if marker.get('baseFiles')!=bootstrap_guest.basic_file_receipt(home):return False
  startup_files={'.dsh-improved/.credentials.yaml','.dsh-improved/storages/workspace.json'}
  if {p.name for p in (home/'tools').iterdir()}!={'harness-improved-runtime','dsh-purge-personal-1.1.77-personal.1'} or {p.name for p in (home/'.local').iterdir()}!={'node'}:return False
  for root in [home/'.dsh-improved',home/'workspace']:
   if root.is_symlink():return False
   if root.exists():
    for path in root.rglob('*'):
     if path.is_symlink() and not (path.name=='dsh-purge' and path.resolve()==home/'tools/dsh-purge-personal-1.1.77-personal.1'):return False
     if str(path.relative_to(home)) in startup_files:continue
     if any(p in {'.ssh','.credentials.yaml','.credentials.json','.env','secrets.env'} for p in path.relative_to(root).parts):return False
     if any(p.lower().startswith(('.env','.credentials','credentials.')) or p.lower() in {'.npmrc','pentagi-admin.json','pentagi-connection.json'} for p in path.relative_to(root).parts):return False
     if path.name in {'sessions','engagements'} and (not path.is_dir() or any(path.iterdir())):return False
     if path.name=='storages' and (not path.is_dir() or any(str(item.relative_to(home)) not in startup_files for item in path.iterdir())):return False
     relative=str(path.relative_to(home))
     if path.is_file() and path.suffix in {'.db','.sqlite','.sqlite3','.jsonl'} and relative!='.dsh-improved/redteam/session-bindings.db':return False
   if root.name=='workspace' and root.exists() and any(root.iterdir()):return False
  package=home/'tools/dsh-purge-personal-1.1.77-personal.1'
  actual={str(p.relative_to(package)):digest(p) for p in package.rglob('*') if p.is_file()}
  binding=home/'.dsh-improved/redteam/session-bindings.db'
  if binding.exists():
   ordinary(binding,16*1024*1024)
   with sqlite3.connect('file:'+str(binding)+'?mode=ro',uri=True) as db:
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables<= {'session_binding','session_lineage','root_archive'}:return False
    for table in tables:
     if db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]:return False
  return actual==program and all(not p.is_symlink() for p in package.rglob('*'))
 except (OSError,ValueError,TypeError,sqlite3.Error):return False

def dedicated_environment():
 try:return sys.platform=='linux' and platform.machine() in {'aarch64','arm64'} and os.geteuid()==1000 and pwd.getpwuid(os.geteuid()).pw_name=='purge' and Path.home()==HOME and HOME.resolve()==HOME and platform.freedesktop_os_release().get('ID')=='ubuntu' and platform.freedesktop_os_release().get('VERSION_ID')=='24.04'
 except OSError:return False

def safe_name(name):
 return isinstance(name,str) and bool(name) and not name.startswith('/') and '\\' not in name and not any(part in {'','.','..'} for part in name.split('/')) and not any(ord(c)<32 for c in name)

def allowed(name):
 if not safe_name(name):return False
 parts=name.split('/')
 if any(p in {'.git','__pycache__','.cache','.ssh','secrets.env','.env','.credentials.yaml','.credentials.json','pentagi-admin.json','pentagi-connection.json'} for p in parts):return False
 # Only these pinned packages' code namespaces use a directory named sessions.
 # A nested node_modules directory must never make runtime state eligible.
 if any(p in {'sessions','storages'} for p in parts):
  state_at=next(i for i,p in enumerate(parts) if p in {'sessions','storages'})
  packages={('node_modules','@anthropic-ai','sdk'):[['lib','sessions'],['src','lib','sessions'],['resources','beta','sessions'],['src','resources','beta','sessions']],('node_modules','@deepseek-ai','dsh-api-session-controller'):[['lib','types','client','sessions']],('node_modules','openai'):[['resources','beta','agents','sessions'],['src','resources','beta','agents','sessions']]}
  namespace_ok=False
  for package,namespaces in packages.items():
   for i in range(len(parts)-len(package)):
    if tuple(parts[i:i+len(package)])!=package or state_at<i+len(package):continue
    tail=parts[i+len(package):]
    if any(tail[:len(prefix)]==prefix for prefix in namespaces):namespace_ok=True
  if not namespace_ok or 'storages' in parts:return False
  if PurePosixPath(name).suffix.lower() not in {'','.js','.mjs','.cjs','.ts','.mts','.cts','.map'}:return False
 if name not in SECURITY_FILES:
  code_suffixes={'.js','.mjs','.cjs','.ts','.mts','.cts','.map'}
  if any(p.lower().startswith(('.env','.credentials')) or p.lower().startswith('credentials.') and PurePosixPath(p).suffix.lower() not in code_suffixes or p.lower() in {'.npmrc','id_rsa','id_ed25519','known_hosts','authorized_keys'} for p in parts):return False
  if PurePosixPath(name).suffix.lower() in {'.db','.sqlite','.sqlite3','.jsonl','.log','.key','.pem'}:return False
 return name in SECURITY_FILES+CONFIG_FILES or any(name==root or name.startswith(root+'/') for root in ASSET_ROOTS) or any(name.startswith(prefix) for prefix in CONFIG_PREFIXES)

def payload_members(archive):
 members=archive.getmembers();seen={};total=0
 if not members or len(members)>250000:raise ValueError('Invalid payload member count')
 for item in members:
  if not allowed(item.name) or item.name in seen or not (item.isfile() or item.isdir() or item.issym()) or item.mode&0o7000:raise ValueError('Unsafe payload member')
  if item.size<0 or item.size>8*1024**3:raise ValueError('Payload member too large')
  total+=item.size
  if total>MAX_BYTES:raise ValueError('Payload expanded size too large')
  if item.issym():
   if not item.linkname or item.linkname.startswith('/') or '\\' in item.linkname or any(ord(c)<32 for c in item.linkname):raise ValueError('Unsafe payload link')
   target=posixpath.normpath(posixpath.join(posixpath.dirname(item.name),item.linkname))
   if not allowed(target):raise ValueError('Payload link leaves approved roots')
  seen[item.name]=item
 for name,item in seen.items():
  if any(str(parent) in seen and not seen[str(parent)].isdir() for parent in PurePosixPath(name).parents if str(parent)!='.'):raise ValueError('Payload parent is not a directory')
 return members

def bound_tar_headers(path):
 """Bound extension headers before tarfile parses PAX/GNU metadata into memory."""
 with gzip.open(path,'rb') as stream:
  headers=total=metadata=0
  while True:
   header=stream.read(512)
   if len(header)!=512:raise ValueError('Truncated payload header')
   if header==b'\0'*512:
    trailer=stream.read(10241)
    if len(trailer)>10240 or any(trailer):raise ValueError('Unexpected payload trailer')
    return
   headers+=1
   if headers>500000:raise ValueError('Too many raw payload headers')
   raw=header[124:136].rstrip(b'\0 ').lstrip(b' ')
   if not raw or any(c not in b'01234567' for c in raw):raise ValueError('Unsupported raw payload size')
   size=int(raw,8);kind=header[156:157];total+=size
   if size>8*1024**3 or total>MAX_BYTES:raise ValueError('Raw payload too large')
   if kind in {b'x',b'g',b'L',b'K'}:
    metadata+=size
    if kind!=b'x' or size>16384 or metadata>128*1024*1024:raise ValueError('Unsupported payload extension metadata')
    data=stream.read(size)
    if len(data)!=size:raise ValueError('Truncated payload metadata')
    offset=0
    while offset<len(data):
     space=data.find(b' ',offset)
     if space<0 or not data[offset:space].isdigit():raise ValueError('Invalid PAX record')
     length=int(data[offset:space]);end=offset+length
     if length<=space-offset+1 or end>len(data) or data[end-1:end]!=b'\n':raise ValueError('Invalid PAX record length')
     key,separator,_value=data[space+1:end-1].partition(b'=')
     if not separator or key not in {b'path',b'linkpath',b'mtime',b'atime',b'ctime'}:raise ValueError('Unsupported PAX semantic override')
     offset=end
    padding=(-size)%512
    if len(stream.read(padding))!=padding:raise ValueError('Truncated PAX padding')
    continue
   remaining=((size+511)//512)*512
   while remaining:
    data=stream.read(min(1024*1024,remaining))
    if not data:raise ValueError('Truncated payload data')
    remaining-=len(data)

def extract_payload(path,stage):
 stage=Path(stage)
 if stage.resolve()!=stage or not stage.is_dir() or any(stage.iterdir()):raise ValueError('Empty ordinary stage required')
 bound_tar_headers(path)
 with tarfile.open(path,'r:gz') as archive:
  members=payload_members(archive)
  for item in members:
   try:tarfile.data_filter(item,str(stage))
   except tarfile.FilterError as error:raise ValueError('Unsafe payload extraction') from error
  # All names, duplicates, types and link parents are checked before writing.
  archive.extractall(stage,members=members,filter='data')
 return {'files':sum(item.isfile() for item in members),'links':sum(item.issym() for item in members),'bytes':sum(item.size for item in members)}

def write_payload(home,names,output):
 home=Path(home);items=[];total=0
 if home.resolve()!=home or not home.is_dir() or len(names)>250000 or len(set(names))!=len(names):raise ValueError('Invalid source inventory')
 for name in names:
  if not allowed(name):raise ValueError('Source outside approved payload')
  path=home/name;info=path.lstat()
  if info.st_mode&0o7000 or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):raise ValueError('Unsupported source type')
  if path.is_symlink():
   target=path.resolve()
   if not target.is_relative_to(home) or not allowed(str(target.relative_to(home))):raise ValueError('Source link leaves approved roots')
   rawlink=os.readlink(path);link=rawlink if not rawlink.startswith('/') else posixpath.relpath(str(target.relative_to(home)),posixpath.dirname(name))
  else:
   if path.resolve()!=path:raise ValueError('Source parent redirected')
   link=None
  total+=info.st_size if path.is_file() and not path.is_symlink() else 0
  if total>MAX_BYTES:raise ValueError('Source payload too large')
  items.append((name,path,info,link))
 with tarfile.open(output,'x:gz',compresslevel=1,dereference=False) as archive:
  for name,path,info,link in items:
   item=archive.gettarinfo(str(path),arcname=name);item.uid=item.gid=0;item.uname=item.gname='';item.mode&=0o777
   if link is not None:item.type=tarfile.SYMTYPE;item.linkname=link;archive.addfile(item)
   elif stat.S_ISREG(info.st_mode):
    # Do not let tar turn shared package-store inodes into hardlinks.
    item.type=tarfile.REGTYPE;item.size=info.st_size;item.linkname=''
    with path.open('rb') as stream:archive.addfile(item,stream)
   else:archive.addfile(item)
   after=path.lstat()
   if (info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('Program changed while packing')
 return {'files':sum(stat.S_ISREG(info.st_mode) for _,_,info,_ in items),'links':sum(link is not None for _,_,_,link in items),'bytes':total}

def inspect_images():
 raw=subprocess.check_output(['sudo','-n','/usr/bin/docker','image','inspect',*[row['ref'] for row in IMAGES]],text=True,timeout=30)
 observed=json.loads(raw)
 if len(observed)!=len(IMAGES):raise ValueError('Image inventory incomplete')
 for pin,row in zip(IMAGES,observed):
  if row.get('Id')!=pin['id'] or row.get('Architecture')!='arm64' or row.get('Os')!='linux':raise ValueError('Pinned image mismatch')
 return True

def build_bundle(destination):
 if not dedicated_environment():raise ValueError('Dedicated source VM required')
 destination=Path(destination)
 if destination.resolve()!=destination or destination.exists() or not destination.parent.is_dir() or destination.is_relative_to(HOME/'tools'):raise ValueError('New ordinary external bundle directory required')
 names=[]
 for root in ASSET_ROOTS:
  path=HOME/root
  if not path.is_dir() or path.is_symlink():raise ValueError('Missing program root: '+root)
  names.append(root);names.extend(str(p.relative_to(HOME)) for p in path.rglob('*') if allowed(str(p.relative_to(HOME))))
 for name in SECURITY_FILES+['.dsh/toolchain/reverse-tool-index.json']:
  ordinary(HOME/name);names.append(name)
 verify_original_runtime(HOME)
 original=json.loads((HOME/'tools/harness-original-capabilities/.personal-runtime-manifest.json').read_text())
 packed=set(names)
 if any('tools/harness-original-capabilities/'+name not in packed for name in original['files']):raise ValueError('Original runtime files excluded from bundle')
 inspect_images()
 if shutil.disk_usage(destination.parent).free<7*1024**3:raise ValueError('Need at least 7GiB available for bundle export')
 destination.mkdir(mode=0o700)
 try:
  summary=write_payload(HOME,names,destination/'programs.tgz')
  # Docker data only: no volumes, container filesystem or account state.
  with (destination/'images.tar.gz').open('xb') as output:
   os.fchmod(output.fileno(),0o600)
   process=subprocess.Popen(['sudo','-n','/usr/bin/docker','image','save',*[row['ref'] for row in IMAGES]],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
   try:
    with gzip.GzipFile(fileobj=output,mode='wb',compresslevel=1,mtime=0) as compressed:shutil.copyfileobj(process.stdout,compressed,1024*1024)
    if process.wait(timeout=600)!=0:raise ValueError('Image export failed')
   finally:
    if process.poll() is None:process.kill();process.wait()
    process.stdout.close()
  archives={name:{'sha256':digest(destination/name),'bytes':(destination/name).stat().st_size} for name in ['programs.tgz','images.tar.gz']}
  value={'schemaVersion':1,'scope':'professional-offline-assets','platform':'linux/arm64','archives':archives,'components':COMPONENTS,'images':IMAGES,'payloadFiles':summary['files'],'payloadBytes':summary['bytes']}
  (destination/'manifest.json').write_text(json.dumps(value,indent=2)+'\n');(destination/'manifest.json').chmod(0o600)
  return {'ok':True,'bundle':str(destination),'manifestSha256':digest(destination/'manifest.json'),'archives':archives,'payload':summary,'copiesCredentials':False,'dockerVolumesCopied':False}
 except BaseException:
  # Preserve owned partial files; never publish a completion manifest on failure.
  raise

def stage_configuration(stage):
 inventory=json.loads((REPO/'inventory/export.json').read_text());copied=[]
 for name,row in inventory['guestFiles'].items():
  if not name.startswith('guest-home/'):continue
  target=name[len('guest-home/'):]
  if not (target in CONFIG_FILES or any(target.startswith(prefix) for prefix in CONFIG_PREFIXES)):continue
  source=REPO/name;ordinary(source,16*1024*1024)
  if digest(source)!=row['sha256']:raise ValueError('Exported configuration identity mismatch')
  path=stage/target
  if path.exists() or path.is_symlink():raise ValueError('Configuration collides with program payload')
  path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,path);copied.append(target)
 # Do not copy the original home, welcome acknowledgments, account settings,
 # source sessions, or old plugin state. Optional dependencies come from assets.
 source=REPO/'guest-home/.dsh-improved/profiles/web/package.json';ordinary(source,16384)
 value=json.loads(source.read_text())
 expected={'dsh-purge':'file:/home/purge/tools/dsh-purge-personal-1.1.77-personal.1',**{name:'file:/home/purge/tools/imported-dsh-plugins-20261027T185822Z/'+name for name in ['dsh-context','dsh-whale-widget','dshmarket']}}
 if value.get('dependencies')!=expected:raise ValueError('Profile dependency source mismatch')
 path=stage/'.dsh-improved/profiles/web';path.mkdir(parents=True,exist_ok=True)
 (path/'package.json').write_text(json.dumps(value,indent=2)+'\n')
 (path/'cordis.patch.yml').write_text('''- id: workspace-controller
  config:
    documentsDirectory: /home/purge/workspace
- id: ui-theme
  config:
    preference: light
- id: dsh-purge
  config:
    executionMode: vm-autonomous
    autoApplyOnStart: false
    autoUpdateOnStart: false
    autoRevertOnMissing: false
- id: dsh-market
  config:
    profile: web
    allowRestart: false
''')
 (stage/'.config/harness-vm-mode').write_text('improved\n')
 (stage/'.config/harness-original-capabilities').write_text('off\n')
 return copied

def verify_original_runtime(home):
 root=home/'tools/harness-original-capabilities';path=root/'.personal-runtime-manifest.json';ordinary(path,32*1024*1024);value=json.loads(path.read_text());entries=value.get('files')
 if value.get('source')!='/home/purge/.local/lib/node_modules/@deepseek-ai/dsh' or not isinstance(entries,dict) or not 1<=len(entries)<=100000:raise ValueError('Original runtime inventory unavailable')
 for name,row in entries.items():
  if not safe_name(name) or not isinstance(row,dict):raise ValueError('Unsafe original runtime inventory')
  path=root/name
  if not path.resolve().is_relative_to(root):raise ValueError('Original runtime escapes its root')
  if 'link' in row:
   if not path.is_symlink() or os.readlink(path)!=row['link']:raise ValueError('Original runtime link changed')
  elif path.is_symlink() or not path.is_file() or digest(path)!=row.get('sha256'):raise ValueError('Original runtime content changed')
 return len(entries)

def verify_installation(home=HOME):
 versions={}
 for name,want in [('tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/package.json','0.2.1-rc.3'),('tools/rea-runtime/node_modules/rea-agents/package.json','6.8.0'),('tools/codegraph-1.6.2/node_modules/@colbymchenry/codegraph/package.json','1.6.2'),*[(f'tools/imported-dsh-plugins-20261027T185822Z/{name}/package.json',version) for name,version in [('dsh-context','0.75.1'),('dsh-whale-widget','0.4.2'),('dshmarket','1.70.2')]]]:
  path=home/name;ordinary(path,1024*1024);value=json.loads(path.read_text())
  if value.get('version')!=want:raise ValueError('Installed tool version mismatch')
  versions[value['name']]=want
 for name in ['tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless','.local/bin/reverse-route','.local/bin/reverse-case','.dsh/toolchain/pentagi-cli.py','tools/harness-original-capabilities/lib/bin.js']:
  ordinary(home/name,8*1024*1024)
 if not os.access('/usr/lib/jvm/java-21-openjdk-arm64/bin/javac',os.X_OK):raise ValueError('Ghidra requires the full JDK, not only the Java runtime')
 original_count=verify_original_runtime(home);inspect_images();env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000','PATH':str(home/'.local/node/bin')+':'+str(home/'.local/bin')+':'+os.environ.get('PATH','/usr/bin:/bin'),'DSH_HOME':str(home/'.dsh-improved'),'JAVA_HOME':'/usr/lib/jvm/java-21-openjdk-arm64','GHIDRA_INSTALL_DIR':str(home/'tools/ghidra_12.1.4_PUBLIC')}
 def read(argv,timeout=30):return subprocess.check_output(list(map(str,argv)),env=env,text=True,stderr=subprocess.DEVNULL,timeout=timeout)
 version=json.loads(read([home/'.local/bin/rea','--version','--json']))
 if version.get('version')!='6.8.0':raise ValueError('REA command version mismatch')
 readiness=json.loads(read([home/'.local/node/bin/node',home/'tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-runtime-preflight.mjs'],timeout=45))
 if readiness.get('ok') is not True:raise ValueError('Loaded scanner resources not ready')
 units=read(['systemctl','--user','is-active','dsh-original','harness-security.socket']).split()
 if units!=['active','active']:raise ValueError('Professional web services not active')
 # Wait for an actual HTTP response. This read does not authenticate, accept a
 # notice, submit a model request, or create a project.
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));ready=False
 for _ in range(30):
  try:
   with opener.open('http://10.0.2.15:3080/',timeout=2) as response:ready=response.status==200
  except urllib.error.HTTPError as error:ready=error.code==401
  except OSError:pass
  if ready:break
  time.sleep(1)
 if not ready:raise ValueError('Professional web readiness not observed')
 return {'versions':versions,'reaCommandVersionMatched':True,'originalRuntimeFilesVerified':original_count,'scannerRuntimeReady':True,'scannerVersions':{name:row.get('version') for name,row in readiness.get('tools',{}).items()},'webResponding':True,'webAndSocketActive':True,'credentialsOrModelValidityTested':False,'modelOrScanStarted':False}

def install_bundle(bundle,want):
 import bootstrap_guest
 program=bootstrap_guest.program_files()
 if not dedicated_environment() or not pristine_basic(HOME,program):raise ValueError('Pristine dedicated basic VM required')
 value=verify_bundle(bundle,want)
 for path in ['/usr/bin/docker','/usr/lib/jvm/java-21-openjdk-arm64/bin/java','/usr/lib/jvm/java-21-openjdk-arm64/bin/javac','/usr/bin/file','/usr/bin/readelf']:
  if not os.access(path,os.X_OK):raise ValueError('Professional system prerequisite unavailable')
 if shutil.disk_usage(HOME).free<value['payloadBytes']*2+14*1024**3:raise ValueError('Insufficient staging, backup and image space')
 if subprocess.check_output(['sudo','-n','/usr/bin/docker','ps','-aq'],text=True,timeout=10).strip() or subprocess.check_output(['sudo','-n','/usr/bin/docker','volume','ls','-q'],text=True,timeout=10).strip():raise ValueError('Fresh Docker state required')
 os.umask(0o077);marker=HOME/'.harness-professional';marker.mkdir(mode=0o700);marker_info=marker.stat();owned_marker=(marker_info.st_dev,marker_info.st_ino);stage=marker/'stage';stage.mkdir();log=marker/'installation.log';phase='stage'
 env={**os.environ,'PATH':str(HOME/'.local/node/bin')+':'+str(HOME/'.local/bin')+':'+os.environ.get('PATH','/usr/bin:/bin'),'DSH_HOME':str(HOME/'.dsh-improved'),'XDG_RUNTIME_DIR':'/run/user/1000','JAVA_HOME':'/usr/lib/jvm/java-21-openjdk-arm64','GHIDRA_INSTALL_DIR':str(HOME/'tools/ghidra_12.1.4_PUBLIC'),'REA_ANALYSIS_PROVIDER':'ghidra'}
 def run(argv,timeout=120):
  with log.open('ab') as output:subprocess.run(list(map(str,argv)),env=env,stdout=output,stderr=subprocess.STDOUT,timeout=timeout,check=True)
 try:
  summary=extract_payload(Path(bundle)/'programs.tgz',stage)
  if summary['files']!=value['payloadFiles'] or summary['bytes']!=value['payloadBytes']:raise ValueError('Expanded inventory mismatch')
  config=stage_configuration(stage)
  phase='load-images';run(['sudo','-n','/usr/bin/docker','image','load','--input',Path(bundle)/'images.tar.gz'],timeout=600);inspect_images()
  # Docker save/load may not preserve repository digest aliases. Use exact
  # local content IDs, checked above, in the new runtime and compose configs.
  images=stage/'tools/security-workbench/images.json';runtime=json.loads(images.read_text())
  for row in runtime['tools']:
   pin=next(pin for pin in IMAGES if pin['ref'].startswith('personal-security/'+row['tool']+':'))
   if row['imageId']!=pin['id']:raise ValueError('Scanner manifest identity mismatch')
  phase='stop-basic';run(['systemctl','--user','stop','dsh-original','harness-security.socket','harness-security.service'])
  if not pristine_basic(HOME,program,owned_marker=owned_marker):raise ValueError('Basic installation changed while staging')
  phase='adopt';backup=marker/'basic-backup';backup.mkdir()
  old=HOME/'tools/harness-improved-runtime';old.rename(backup/'harness-improved-runtime')
  for root in ASSET_ROOTS:
   source=stage/root;target=HOME/root
   if target.exists() or target.is_symlink():raise ValueError('Occupied program destination')
   target.parent.mkdir(parents=True,exist_ok=True);source.rename(target)
  # Remaining staged assets/configuration are fixed paths. Replace only the
  # three basic units and basic telemetry patch, retaining their old bytes.
  replace={'.config/systemd/user/dsh-original.service','.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket','.dsh-improved/cordis.patch.yml','.dsh-improved/profiles/web/package.json','.dsh-improved/profiles/web/cordis.patch.yml'}
  for source in sorted(stage.rglob('*')):
   if source.is_dir():continue
   name=str(source.relative_to(stage));target=HOME/name
   if source.is_symlink():raise ValueError('Unexpected configuration link')
   if target.exists() or target.is_symlink():
    if name not in replace:raise ValueError('Existing configuration cannot be overwritten')
    target_backup=backup/name;target_backup.parent.mkdir(parents=True,exist_ok=True);target.rename(target_backup)
   target.parent.mkdir(parents=True,exist_ok=True);source.rename(target)
  # The generated basic profile remains present: replace only its known
  # package and plugin patch, preserving the old files in the private backup.
  phase='links';profile=HOME/'.dsh-improved/profiles/web';modules=profile/'node_modules'
  for name,target in {'dsh-purge':HOME/'tools/dsh-purge-personal-1.1.77-personal.1',**{name:HOME/'tools/imported-dsh-plugins-20261027T185822Z'/name for name in ['dsh-context','dsh-whale-widget','dshmarket']}}.items():
   path=modules/name
   if path.is_symlink() and path.resolve()==target:continue
   if path.exists() or path.is_symlink():raise ValueError('Unexpected profile module')
   path.symlink_to(target,target_is_directory=True)
  for name,target in [('rea',HOME/'tools/rea-runtime/node_modules/.bin/rea'),('pentagi-vm',HOME/'.dsh/toolchain/pentagi-cli.py')]:
   path=HOME/'.local/bin'/name
   if path.exists() or path.is_symlink():raise ValueError('Unexpected tool launcher')
   path.symlink_to(target)
  (HOME/'.local/bin/pnpm').symlink_to(HOME/'.local/lib/node_modules/pnpm/bin/pnpm.cjs')
  for name in ['.dsh/toolchain/pentagi-cli.py','.local/bin/harness-vm-web']:(HOME/name).chmod(0o700)
  for name in ['.local/bin/dsh','.local/bin/reverse-route','.local/bin/reverse-case','.local/bin/codegraph','.local/bin/toolchain-versions']:(HOME/name).chmod(0o755)
  phase='original-profile'
  with log.open('ab') as output:subprocess.run([str(HOME/'.local/node/bin/node'),str(HOME/'.local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js'),'--profile','web','--dump-default-config'],env={**env,'DSH_HOME':str(HOME/'.dsh')},stdout=output,stderr=subprocess.STDOUT,timeout=60,check=True)
  original=HOME/'.dsh/profiles/web/package.json';data=json.loads(original.read_text());data.setdefault('dependencies',{})['dsh-purge']='file:/home/purge/.dsh/profiles/web/node_modules/dsh-purge';bundles=data['dsh']['profile']['bundles']
  if 'dsh-purge' not in bundles:bundles.append('dsh-purge')
  original.write_text(json.dumps(data,indent=2)+'\n')
  (HOME/'.dsh/cordis.patch.yml').write_text((HOME/'.dsh-improved/cordis.patch.yml').read_text().split('- id: sandbox-policy')[0])
  (HOME/'.dsh/profiles/web/cordis.patch.yml').write_text('- id: ui-theme\n  config:\n    preference: light\n')
  phase='fresh-local-secrets';pentagi=HOME/'.dsh/toolchain/pentagi';compose=pentagi/'pentagi.compose.yml';text=compose.read_text().replace('vxcontrol/pgvector@sha256:841d51ebcf46f4e98e15affc466f37be5492592863f04b6b4f479619938eb07a',IMAGES[4]['id']);compose.write_text(text)
  with (pentagi/'secrets.env').open('x') as output:output.write('DEEPSEEK_API_KEY=\nCOOKIE_SIGNING_SALT='+secrets.token_hex(32)+'\nPENTAGI_POSTGRES_PASSWORD='+secrets.token_hex(24)+'\n')
  (pentagi/'secrets.env').chmod(0o600)
  phase='web-start';run(['systemctl','--user','daemon-reload']);run(['systemctl','--user','start','harness-security.socket','dsh-original'])
  phase='verify-readiness';verified=verify_installation(HOME)
  result={'ok':True,'scope':'professional-offline-assets','components':COMPONENTS,'assetManifestSha256':want,'payloadFiles':summary['files'],'payloadLinks':summary['links'],'configFiles':len(config),'imagesLoaded':len(IMAGES),'copiesCredentials':False,'oldProjectsOrAuditDataCopied':False,'modelOrScannerInvocation':False,'accountSetupRequired':True,'pentagiServiceStarted':False,'originalCapabilitiesEnabled':False,'hostIntegrationChanged':False,'privateInstallationLog':str(log)}
  result['readiness']=verified
  (marker/'complete.json').write_text(json.dumps(result,indent=2)+'\n');return result
 except BaseException:
  (marker/'failed.json').write_text(json.dumps({'phase':phase,'automaticRetry':False,'partialInstallationPreserved':True})+'\n');raise

def plan():
 return {'readOnly':True,'automaticChanges':False,'scope':'professional-offline-assets','components':COMPONENTS,'copiesCredentials':False,'requiresPristineBasicInstall':True,'modelOrScannerInvocation':False,'accountSetupRequired':True,'hostIntegrationChanged':False}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--build-bundle',type=Path);parser.add_argument('--bundle',type=Path);parser.add_argument('--manifest-sha256');parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 try:
  if args.apply and not dedicated_environment():raise ValueError('Pristine dedicated basic VM required')
  if args.build_bundle:
   if args.bundle or args.apply or args.manifest_sha256:raise ValueError('Choose one operation')
   value=build_bundle(args.build_bundle)
  elif args.apply:
   if args.bundle is None or args.manifest_sha256 is None:raise ValueError('Bundle and out-of-band manifest digest required')
   value=install_bundle(args.bundle,args.manifest_sha256)
  elif args.bundle:
   value=verify_bundle(args.bundle,args.manifest_sha256);value={**plan(),'bundleVerified':True,'payloadFiles':value['payloadFiles'],'images':len(value['images'])}
  else:
   if args.manifest_sha256:raise ValueError('Bundle required')
   value=plan()
  print(json.dumps(value));return 0
 except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError,tarfile.TarError) as error:
  known=str(error)=='Pristine dedicated basic VM required'
  print(json.dumps({'ok':False,'error':'Pristine dedicated basic VM required' if known else 'Professional asset operation incomplete; inspect local prerequisites, bundle identity or private installation state','automaticRetry':False,'automaticChanges':False if not dedicated_environment() else None}));return 1

if __name__=='__main__':raise SystemExit(main())
