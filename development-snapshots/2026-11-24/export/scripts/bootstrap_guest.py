#!/usr/bin/env python3
"""Plan or install only the basic Harness/plugin/web stack in an empty dedicated VM."""
from pathlib import Path
import argparse,base64,hashlib,json,os,platform,pwd,re,shutil,stat,subprocess,sys,tarfile,time,urllib.error,urllib.request

REPO=Path(__file__).resolve().parent.parent
TARGET=Path('/home/purge')
NODE_VERSION='24.22.1'
HARNESS_VERSION='0.2.1-rc.3'
PNPM_VERSION='11.28.5'
BASIC_FILES=['.config/systemd/user/dsh-original.service','.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket','.dsh-improved/cordis.patch.yml','.dsh-improved/profiles/web/package.json','.dsh-improved/profiles/web/cordis.patch.yml','tools/harness-improved-runtime/package.json','.dsh-improved/.credentials.yaml','.dsh-improved/storages/workspace.json']

def basic_file_receipt(home):
 result={}
 for name in BASIC_FILES:
  path=home/name
  if path.resolve()!=path or not path.is_file() or path.stat().st_size>2*1024*1024:raise ValueError('Basic configuration is not an ordinary bounded file')
  result[name]=hashlib.sha256(path.read_bytes()).hexdigest()
 return result

def supported_distribution(info):
 return info.get('ID')=='ubuntu' and info.get('VERSION_ID')=='24.04'

def fresh_workspace(path):
 try:
  metadata=path.lstat()
 except FileNotFoundError:
  return True
 except OSError:
  return False
 if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid!=os.geteuid():
  return False
 if not os.access(path,os.R_OK|os.W_OK|os.X_OK):
  return False
 try:
  return not any(path.iterdir())
 except OSError:
  return False

def fresh_home(home):
 # Restrict installation to an unused home. Reject whole tool/config/account
 # roots rather than trying to merge a pre-existing installation.
 for name in ['.dsh','.dsh-improved','tools','.local','.config','.npmrc','.harness-bootstrap']:
  path=home/name
  if path.exists() or path.is_symlink():return False
 return fresh_workspace(home/'workspace')

def check_digest(path,algorithm,expected):
 with path.open('rb') as source:digest=hashlib.file_digest(source,algorithm).digest()
 actual=digest.hex() if algorithm=='sha256' else base64.b64encode(digest).decode()
 if actual!=expected:raise ValueError('Downloaded archive identity mismatch')

def extract_node(archive,destination):
 prefix='node-v'+NODE_VERSION+'-linux-arm64'
 with tarfile.open(archive,'r:xz') as source:
  members=source.getmembers()
  # Validate the whole archive before extracting anything. data_filter also
  # rejects absolute/escaping links and device nodes on supported Python.
  for member in members:
   parts=member.name.split('/')
   if parts[0]!=prefix or any(part in {'.','..'} for part in parts):raise ValueError('Unsafe Node archive')
   try:tarfile.data_filter(member,str(destination))
   except tarfile.FilterError as error:raise ValueError('Unsafe Node archive') from error
  source.extractall(destination,members=members,filter='data')
 return destination/prefix

def installation_sources():
 files=program_files();lock=json.loads((REPO/'inventory/bootstrap-lock.json').read_text())
 if lock.get('nodeVersion')!=NODE_VERSION or lock.get('nodeUrl')!='https://nodejs.org/dist/v'+NODE_VERSION+'/node-v'+NODE_VERSION+'-linux-arm64.tar.xz' or not re.fullmatch('[a-f0-9]{64}',lock.get('nodeSha256','')):raise ValueError('Invalid Node pin')
 for key,name,version,tarball in [('harness','@deepseek-ai/dsh',HARNESS_VERSION,'https://registry.npmjs.org/@deepseek-ai/dsh/-/dsh-'+HARNESS_VERSION+'.tgz'),('pnpm','pnpm',PNPM_VERSION,'https://registry.npmjs.org/pnpm/-/pnpm-'+PNPM_VERSION+'.tgz')]:
  value=lock[key]
  if value['name']!=name or value['version']!=version or value['dist']['tarball']!=tarball or not re.fullmatch('sha512-[A-Za-z0-9+/]{86}==',value['dist']['integrity']):raise ValueError('Invalid package pin')
 return files,lock

def install():
 files,lock=installation_sources()
 # Guard parent components too: a fresh target must not redirect writes through
 # an existing symlink. A failed attempt remains explicit and is not replayed.
 for name in ['tools','.local','.config','.config/systemd','.config/systemd/user','workspace']:
  path=TARGET/name
  if path.is_symlink() or path.exists() and not path.is_dir():raise ValueError('Unsafe installation parent')
 marker=TARGET/'.harness-bootstrap';marker.mkdir(mode=0o700)
 log=marker/'installation.log';phase='download'
 env={**os.environ,'PATH':str(TARGET/'.local/node/bin')+':'+os.environ.get('PATH','/usr/bin:/bin'),'DSH_HOME':str(TARGET/'.dsh-improved'),'NODE_USE_ENV_PROXY':'1','HTTP_PROXY':'http://10.0.2.100:3128','HTTPS_PROXY':'http://10.0.2.100:3128','http_proxy':'http://10.0.2.100:3128','https_proxy':'http://10.0.2.100:3128','NO_PROXY':'localhost,127.0.0.1,::1,10.0.2.15','no_proxy':'localhost,127.0.0.1,::1,10.0.2.15','XDG_RUNTIME_DIR':'/run/user/1000','npm_config_registry':'https://registry.npmjs.org/','npm_config_audit':'false','npm_config_fund':'false'}
 def run(argv,cwd=TARGET,timeout=600):
  with log.open('ab') as output:
   os.chmod(log,0o600);subprocess.run(list(map(str,argv)),cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,check=True,timeout=timeout)
 def download(url,name):
  path=marker/name
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':env['HTTPS_PROXY']}))
  with opener.open(url,timeout=120) as source,path.open('xb') as output:
   os.chmod(path,0o600);size=0
   while chunk:=source.read(1024*1024):
    size+=len(chunk)
    if size>256*1024*1024:raise ValueError('Download too large')
    output.write(chunk)
  return path
 try:
  archives={}
  node=download(lock['nodeUrl'],'node.tar.xz');check_digest(node,'sha256',lock['nodeSha256'])
  for key in ['harness','pnpm']:
   value=lock[key]['dist'];archives[key]=download(value['tarball'],key+'.tgz');check_digest(archives[key],'sha512',value['integrity'][7:])
  phase='node';extracted=extract_node(node,marker)
  (TARGET/'.local').mkdir(exist_ok=True);extracted.rename(TARGET/'.local/node')
  runtime=TARGET/'tools/harness-improved-runtime';runtime.mkdir(parents=True)
  approved=['@deepseek-ai/dsh-subprocess-local','koffi','node-pty','@google/genai','protobufjs']
  (runtime/'package.json').write_text(json.dumps({'private':True,'allowScripts':{name:True for name in approved}},indent=2)+'\n')
  npm=TARGET/'.local/node/bin/npm'
  phase='packages';run([npm,'install','--prefix',runtime,'--ignore-scripts','--save-exact','--no-audit','--no-fund',archives['harness'],archives['pnpm']])
  for key in ['harness','pnpm']:
   package=runtime/'node_modules'/lock[key]['name']
   if json.loads((package/'package.json').read_text())['version']!=lock[key]['version']:raise ValueError('Installed package version mismatch')
  phase='native-dependencies'
  run([npm,'rebuild','--prefix',runtime,'--strict-allow-scripts',*approved])
  phase='profile';package=TARGET/'tools/dsh-purge-personal-1.1.77-personal.1';package.mkdir()
  source=REPO/'work/harness-purge-improved/package'
  for name in files:
   target=package/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,target)
  entry=runtime/'node_modules/@deepseek-ai/dsh/lib/bin.js'
  run([TARGET/'.local/node/bin/node',entry,'--profile','web','--dump-default-config'],timeout=60)
  profile=TARGET/'.dsh-improved/profiles/web';data=json.loads((profile/'package.json').read_text());data.setdefault('dependencies',{})['dsh-purge']='file:'+str(package)
  bundles=data['dsh']['profile']['bundles']
  if 'dsh-purge' not in bundles:bundles.append('dsh-purge')
  (profile/'package.json').write_text(json.dumps(data,indent=2)+'\n');modules=profile/'node_modules';modules.mkdir(exist_ok=True);(modules/'dsh-purge').symlink_to(package,target_is_directory=True)
  (TARGET/'.dsh-improved/cordis.patch.yml').write_text('''- id: session-log-deepseek
  config:
    enabled: false
- id: session-telemetry-otel
  disabled: true
- id: product-analytics
  config:
    enabled: false
''')
  (profile/'cordis.patch.yml').write_text('''- id: workspace-controller
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
''')
  workspace=TARGET/'workspace'
  workspace.mkdir(exist_ok=True)
  if not fresh_workspace(workspace):
   raise ValueError('Workspace must be empty, owned and writable')
  units=TARGET/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
  for name in ['harness-security.socket','harness-security.service']:
   shutil.copy2(REPO/'guest-home/.config/systemd/user'/name,units/name)
  # No original-capabilities runtime, imported accounts, optional plugins,
  # professional assets, or Mac integration is copied by this basic installer.
  unit='''[Unit]
Description=Harness basic fresh VM installation
After=network.target
[Service]
Type=simple
WorkingDirectory=/home/purge/workspace
Environment=PATH=/home/purge/.local/node/bin:/home/purge/tools/harness-improved-runtime/node_modules/.bin:/usr/bin:/bin
Environment=DSH_HOME=/home/purge/.dsh-improved
Environment=NODE_USE_ENV_PROXY=1
Environment=HTTP_PROXY=http://10.0.2.100:3128
Environment=HTTPS_PROXY=http://10.0.2.100:3128
Environment=NO_PROXY=localhost,127.0.0.1,::1,10.0.2.15
ExecStart=/home/purge/.local/node/bin/node /home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web --host 10.0.2.15 --port 3080 --public-url http://127.0.0.1:49224 --trusted-host 127.0.0.1:49224 --no-open
UMask=0077
Restart=no
TimeoutStopSec=30
[Install]
WantedBy=default.target
'''
  (units/'dsh-original.service').write_text(unit)
  phase='web-start';run(['sudo','-n','loginctl','enable-linger','purge'],timeout=15);run(['systemctl','--user','daemon-reload'],timeout=15);run(['systemctl','--user','enable','--now','harness-security.socket','dsh-original'],timeout=45)
  phase='web-ready';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));ready=False
  for attempt in range(30):
   try:
    with opener.open('http://10.0.2.15:3080/',timeout=2) as response:ready=response.status==200
   except urllib.error.HTTPError as error:ready=error.code==401
   except OSError:pass
   if ready:break
   time.sleep(1)
  if not ready:raise ValueError('Web startup not confirmed')
  result={'ok':True,'scope':'basic-harness-plugin-web','programFiles':len(files),'nodeVersion':NODE_VERSION,'harnessVersion':HARNESS_VERSION,'pnpmVersion':PNPM_VERSION,'webResponding':True,'copiesCredentials':False,'installsProfessionalTools':False,'modelOrScannerInvocation':False,'dependencyLock':str(runtime/'package-lock.json'),'privateInstallationLog':str(log),'accountSetupRequired':True}
  result['workspaceInitializationChecked']=False
  result['baseFiles']=basic_file_receipt(TARGET)
  (marker/'complete.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return 0
 except (OSError,ValueError,KeyError,subprocess.SubprocessError,tarfile.TarError):
  result={'ok':False,'phase':phase,'automaticRetry':False,'error':'Installation incomplete; inspect the private VM installation log','privateInstallationLog':str(log)}
  (marker/'failed.json').write_text(json.dumps(result)+'\n');print(json.dumps(result));return 1

def program_files():
 value=json.loads((REPO/'work/harness-purge-improved/package-files.json').read_text())
 if not isinstance(value,dict) or not value:raise ValueError('Program inventory unavailable')
 package=REPO/'work/harness-purge-improved/package'
 for name,digest in value.items():
  if not isinstance(name,str) or not name or name.startswith('/') or '\\' in name or any(p in {'','.','..'} for p in name.split('/')) or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Unsafe program inventory')
  path=package/name
  if path.resolve()!=path or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Program identity mismatch')
 return value

def plan():
 files,lock=installation_sources()
 return {'readOnly':True,'automaticChanges':False,'scope':'basic-harness-plugin-web','targetHome':str(TARGET),'programFiles':len(files),'nodeVersion':NODE_VERSION,'harnessVersion':HARNESS_VERSION,'pnpmVersion':PNPM_VERSION,'copiesCredentials':False,'installsProfessionalTools':False,'modelOrScannerInvocation':False,'remainingSetup':['model credentials supplied locally by user','REA/reverse-skill/PentAGI/scanner assets and accounts are separate','Mac VM management, egress and sharing are not installed or changed']}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
 if args.apply:
  valid=sys.platform=='linux' and platform.machine() in {'aarch64','arm64'} and os.geteuid()==1000 and pwd.getpwuid(os.geteuid()).pw_name=='purge' and Path.home()==TARGET and TARGET.resolve()==TARGET
  if valid:
   try:valid=supported_distribution(platform.freedesktop_os_release())
   except OSError:valid=False
  occupied=not fresh_home(TARGET) if valid else True
  if not valid or occupied:
   print(json.dumps({'ok':False,'error':'Dedicated empty VM required','automaticChanges':False}));return 1
  try:return install()
  except (OSError,ValueError,TypeError,KeyError):print(json.dumps({'ok':False,'error':'Installation input unavailable; no automatic retry','automaticChanges':False}));return 1
 try:print(json.dumps(plan(),ensure_ascii=False));return 0
 except (OSError,ValueError,TypeError):print(json.dumps({'ok':False,'error':'Installation source identity unavailable','automaticChanges':False}));return 1

if __name__=='__main__':raise SystemExit(main())
