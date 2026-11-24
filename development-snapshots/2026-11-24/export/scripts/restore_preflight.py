#!/usr/bin/env python3
"""Read-only installation preflight inside the dedicated VM; no repairs or probes."""
from pathlib import Path,PurePosixPath
import argparse,getpass,hashlib,json,os,platform,re,stat,sys

EXECUTABLES = {'.dsh/toolchain/pentagi-cli.py', '.local/bin/toolchain-versions', '.local/bin/harness-vm-web', '.local/bin/reverse-case', '.local/bin/dsh', '.local/bin/codegraph', '.local/bin/reverse-route', '.local/bin/kali-vm'} | {'.local/lib/harness-kali-tools/'+name for name in ['nmap', 'nuclei', 'masscan', 'fscan', 'gogo', 'suo5', 'frpc', 'frps', 'chisel', 'ffuf', 'httpx', 'dnsx', 'subfinder', 'ksubdomain', 'impacket', 'curl', 'wget', 'dig', 'openssl', 'tcpdump', 'tshark', 'whatweb', 'nikto', 'sqlmap', 'file', 'strings']}

def safe_name(value):
 return isinstance(value,str) and bool(value) and not PurePosixPath(value).is_absolute() and '\\' not in value and not any(x in {'','..','.'} for x in value.split('/'))

def environment():
 return {'system':platform.system(),'machine':platform.machine(),'user':getpass.getuser(),
  'javaAvailable':os.access('/usr/lib/jvm/java-21-openjdk-arm64/bin/java',os.X_OK),
  'dockerAvailable':os.access('/usr/bin/docker',os.X_OK)}

def assess(home,inventory,observed=None):
 checks=[]
 def row(identity,state,path=None):
  value={'id':identity,'state':state}
  if path is not None:value['path']=path
  checks.append(value)
 def result():return {'ok':bool(checks) and all(x['state']=='ok' for x in checks),'readOnly':True,'automaticChanges':False,'runtimeChecks':'not_run','scope':'installation files, recorded versions and local credential presence; no boot, service, API-token validity or upstream-latest verification','checks':checks}
 try:
  target=inventory['restoreTarget'];guest=inventory['guestFiles'];program=inventory['programFiles']
  if not isinstance(target,dict) or not isinstance(guest,dict) or not isinstance(program,dict) or not program:raise ValueError()
  names=[]
  for name,item in guest.items():
   relative=item.get('sourcePath') or (name[len('guest-home/'):] if name.startswith('guest-home/') else None)
   if not safe_name(relative) or not re.fullmatch('[a-f0-9]{64}',item.get('sourceSha256','')):raise ValueError()
   names.append((relative,item['sourceSha256']))
  for name,digest in program.items():
   if not safe_name(name) or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError()
   names.append(('tools/dsh-purge-personal-1.1.77-personal.1/'+name,digest))
  modes=inventory.get('executionRequirements')
  if not isinstance(modes,dict) or set(modes)!=EXECUTABLES:raise ValueError()
  if any(type(mode) is not int or not 0 <= mode <= 0o777 or not mode&0o100 for mode in modes.values()):raise ValueError()
  if not set(modes)<=set(relative for relative,_ in names):raise ValueError()
  for key in ['pluginRoot','reverseDirectory','ghidraDirectory']:
   if not safe_name(target[key]):raise ValueError()
  plugins=inventory['plugins']
  if not isinstance(plugins,list) or any(not safe_name(x.get('name')) or '/' in x['name'] for x in plugins):raise ValueError()
  versions=[target.get('harnessVersion'),target.get('codegraphVersion'),inventory.get('toolchain',{}).get('rea',{}).get('npmVersion'),*(x.get('version') for x in plugins)]
  if any(not isinstance(v,str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?',v) for v in versions):raise ValueError()
 except (KeyError,TypeError,ValueError,AttributeError):row('inventory','invalid');return result()
 observed=observed if observed is not None else environment()
 if observed.get('system')!=target.get('system') or observed.get('machine') not in {target.get('machine'),'arm64' if target.get('machine')=='aarch64' else target.get('machine')} or observed.get('user')!=target.get('user'):
  row('environment','different');return result()
 row('environment','ok')
 home=Path(home)
 if home.is_symlink() or not home.is_dir():row('target-home','unsafe');return result()
 home=home.resolve()
 if home!=Path(target.get('home','')).resolve():row('target-home','different');return result()
 row('target-home','ok')
 def read(relative,private=False):
  if not safe_name(relative):return None,'unsafe'
  p=home/relative
  try:
   if p.is_symlink() or p.resolve()!=p:return None,'unsafe'
   info=p.stat()
   if not stat.S_ISREG(info.st_mode) or info.st_size>16*1024*1024:return None,'unknown'
   if private and info.st_mode&0o077:return None,'unsafe'
   return p.read_bytes(),'ok'
  except FileNotFoundError:return None,'missing'
  except OSError:return None,'unknown'
 for relative,want in names:
  raw,state=read(relative)
  if state=='ok' and hashlib.sha256(raw).hexdigest()!=want:state='different'
  row('file:'+relative,state,relative)
 for relative,want in modes.items():
  _,state=read(relative)
  if state=='ok':
   try:
    path=home/relative
    state='ok' if stat.S_IMODE(path.stat().st_mode)==want and os.access(path,os.X_OK) else 'different'
   except OSError:state='unknown'
  row('mode:'+relative,state,relative)
 def version(identity,relative,want):
  raw,state=read(relative)
  if state=='ok':
   try:state='ok' if json.loads(raw).get('version')==want else 'different'
   except (ValueError,AttributeError):state='unknown'
  row(identity,state,relative)
 version('dependency:harness','tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/package.json',target.get('harnessVersion'))
 version('dependency:rea','tools/rea-runtime/node_modules/rea-agents/package.json',inventory.get('toolchain',{}).get('rea',{}).get('npmVersion'))
 version('dependency:codegraph','tools/codegraph-1.6.2/node_modules/@colbymchenry/codegraph/package.json',target.get('codegraphVersion'))
 for plugin in plugins:version('plugin:'+plugin['name'],target['pluginRoot']+'/'+plugin['name']+'/package.json',plugin.get('version'))
 for identity,relative in [('dependency:reverse-skill','tools/reverse-skill/'+target['reverseDirectory']+'/AGENTS.md'),('dependency:ghidra','tools/'+target['ghidraDirectory']+'/support/analyzeHeadless')]:
  raw,state=read(relative)
  if state=='ok' and (not raw or (identity.endswith('ghidra') and not os.access(home/relative,os.X_OK))):state='unknown'
  row(identity,state,relative)
 node=home/'.local/node/bin/node'
 row('dependency:node','ok' if node.is_file() and node.resolve().is_relative_to(home) and os.access(node,os.X_OK) else 'missing','.local/node/bin/node')
 for key in ['java','docker']:row('dependency:'+key,'ok' if observed.get(key+'Available') is True else 'unknown')
 def private_data(relative,yaml_allowed=False):
  raw,state=read(relative,private=True)
  if state!='ok':return None,state
  try:
   try:return json.loads(raw),'ok'
   except ValueError:
    if not yaml_allowed:return None,'unknown'
    try:import yaml
    except ImportError:return None,'unknown'
    return yaml.safe_load(raw),'ok'
  except Exception:return None,'unknown'
 def configured(value):return isinstance(value,str) and len(value)>=16 and not value.startswith(('${','__LOCAL_SECRET_REQUIRED__','<'))
 value,state=private_data('.dsh-improved/.credentials.yaml',yaml_allowed=True)
 if state=='ok':state='ok' if isinstance(value,dict) and isinstance(value.get('refs'),dict) and configured(value['refs'].get('DEEPSEEK_API_KEY')) else 'unknown'
 row('credential:deepseek',state)
 for identity,relative,key in [('credential:pentagi-admin','.dsh/toolchain/pentagi-admin.json','password'),('credential:pentagi-connection','.dsh/toolchain/pentagi-connection.json','token')]:
  value,state=private_data(relative)
  if state=='ok':state='ok' if isinstance(value,dict) and configured(value.get(key)) and (key!='password' or value.get('passwordChanged') is True) else 'unknown'
  row(identity,state)
 raw,state=read('.dsh/toolchain/pentagi/secrets.env',private=True)
 if state=='ok':
  try:
   values=dict(line.split('=',1) for line in raw.decode().splitlines() if line.strip() and not line.lstrip().startswith('#') and '=' in line)
   state='ok' if all(configured(values.get(key,'' ).strip().strip('"\'')) for key in ['DEEPSEEK_API_KEY','COOKIE_SIGNING_SALT','PENTAGI_POSTGRES_PASSWORD']) else 'unknown'
  except (ValueError,UnicodeError):state='unknown'
 row('credential:pentagi-environment',state)
 return result()

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--home',default='/home/purge');parser.add_argument('--inventory-stdin',action='store_true');parser.add_argument('--json',action='store_true')
 args=parser.parse_args()
 try:
  inventory=json.load(sys.stdin) if args.inventory_stdin else json.loads((Path(__file__).resolve().parent.parent/'inventory/export.json').read_text())
  output=assess(Path(args.home),inventory)
 except (OSError,ValueError,TypeError,KeyError):output={'ok':False,'readOnly':True,'automaticChanges':False,'runtimeChecks':'not_run','checks':[{'id':'inventory','state':'unavailable'}]}
 if args.json:print(json.dumps(output,ensure_ascii=False))
 else:
  print('只读恢复预检：'+('所列安装检查通过' if output['ok'] else '存在缺项、差异或未确认项'))
  for item in output['checks']:print(item['id']+': '+item['state'])
  print('未启动/修复服务，未验证令牌有效性，未检查GitHub最新版本。')
 return 0 if output['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
