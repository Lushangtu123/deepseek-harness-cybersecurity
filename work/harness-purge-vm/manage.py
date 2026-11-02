#!/usr/bin/env python3
"""On-demand controller for one dedicated VM. Never opens or drives a browser."""
import argparse,base64,binascii,copy,hashlib,inspect,json,math,os,plistlib,re,shutil,socket,stat,subprocess,sys,time,urllib.request,http.cookiejar,tempfile,fcntl,functools,threading,uuid,signal
from contextlib import contextmanager
from pathlib import Path
ROOT=Path.home()/'Library/Application Support/Harness Purge Original'
VM=ROOT/'Harness Purge Original.utm'
SETUP=ROOT/'setup'
TOOLS=ROOT/'host-tools'
UUID='347CD41C-E149-4BD7-BC9E-21A55E06243A'
LABEL='com.personal.harness-purge-original-egress'
UTM='/Applications/UTM.app/Contents/MacOS/utmctl'
PLIST=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
PYTHON='/opt/homebrew/bin/python3'
CURRENT_RECOVERY='ready-security-review-20261101'
REVIEWED_RECOVERIES=('ready-improved-20261026','ready-workbench-20261026','ready-workbench-v3-20261026','ready-workbench-v4-20261026','ready-workbench-v5-20261026','ready-workbench-v6-20261026','ready-workbench-v7-20261026','ready-workbench-v8-20261026','ready-workbench-v9-20261026','ready-workbench-v10-20261027','ready-workbench-v11-20261027','ready-workbench-v11b-20261027','ready-workbench-v12-20261027','ready-workbench-v13-20261027','ready-workbench-v14-20261027','ready-workbench-v15-20261027','ready-workbench-v16-20261027','ready-workbench-v17-20261027','ready-workbench-v18-20261027','ready-workbench-v19-20261027','ready-workbench-v20-20261027','ready-workbench-v21-20261028','ready-workbench-v22-20261028','ready-workbench-v23-20261028','ready-workbench-v24-20261028','ready-workbench-v25-20261028','ready-workbench-v26-20261028','ready-workbench-v27-20261028','ready-workbench-v27b-20261028','ready-workbench-v28-20261028','ready-workbench-v29-20261028','ready-workbench-v29b-20261028','ready-workbench-v30-20261028','ready-merged-capabilities-20261028','ready-merged-capabilities-20261028-r1','ready-merged-switch-20261029','ready-merged-stability-20261029','ready-recovery-guard-20261029','ready-recovery-resume-20261029','ready-recovery-proof-20261029','ready-security-audit-20261029','ready-security-validated-20261029','ready-security-workflow-20261029','ready-security-diagnostics-20261029','ready-security-background-20261029','ready-security-lifecycle-20261030','ready-security-pagination-20261030','ready-security-reload-20261030','ready-security-multiwindow-20261030','ready-pet-corner-20261030','ready-pet-menu-20261030','ready-professional-bootstrap-20261031','ready-ssh-channel-20261031','ready-auth-zap-20261101','ready-session-lifecycle-20261101','ready-parser-probe-20261101','ready-scanner-admission-20261101','ready-storage-preview-20261101','ready-storage-dashboard-20261101',CURRENT_RECOVERY)
RECOVERY_HELPERS={'manage.py','egress_proxy.py','qemu-image.py','web-entry.mjs','web-health.mjs'}
RECOVERY_TOOL_FILES={'.dsh-improved/tooling/toolchain-version-checker/'+name for name in ['index.mjs','process.mjs','check_versions.py','catalog.json']}|{'.local/bin/toolchain-versions'}
RECOVERY_TOOL_FILES|={'tools/security-workbench/'+name for name in ['images.json','rules.json','cache/db/metadata.json']}
RECOVERY_TOOL_FILES|={'.local/bin/kali-vm','.dsh-improved/skills/kali/SKILL.md'}|{'.local/lib/harness-kali-tools/'+name for name in ['nmap', 'nuclei', 'masscan', 'fscan', 'gogo', 'suo5', 'frpc', 'frps', 'chisel', 'ffuf', 'httpx', 'dnsx', 'subfinder', 'ksubdomain', 'impacket', 'curl', 'wget', 'dig', 'openssl', 'tcpdump', 'tshark', 'whatweb', 'nikto', 'sqlmap', 'file', 'strings']}
RECOVERY_CONFIG_FILES={'.config/harness-original-capabilities','.dsh-improved/cordis.patch.yml','.dsh-improved/profiles/web/package.json','.dsh-improved/profiles/web/cordis.patch.yml','.dsh-improved/AGENTS.md','.config/harness-vm-mode','.local/bin/harness-vm-web'}
RECOVERY_CONFIG_FILES|={'.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket'}
RECOVERY_CONFIG_FILES|={'.config/harness-kali/ssh_config'}
RECOVERY_PLUGIN_ROOT='tools/imported-dsh-plugins-20261027T185822Z/'
RECOVERY_PLUGINS={'dsh-context':'0.75.1','dsh-whale-widget':'0.4.2','dshmarket':'1.70.2'}
RECOVERY_RUNTIME_FILES={'tools/harness-improved-runtime/node_modules/@deepseek-ai/'+name+'/lib/index.js' for name in ['dsh-tools','dsh-tool-bash','dsh-permission-presets','dsh-user-approval']}|{'tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/package.json','tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js'}

RECOVERY_RUNTIME_FILES|={'tools/harness-original-capabilities/'+name for name in ['.personal-runtime-manifest.json','lib/bin.js','package.json']}|{'tools/harness-original-capabilities/node_modules/@deepseek-ai/'+name+'/lib/index.js' for name in ['dsh-tools','dsh-tool-bash','dsh-permission-presets','dsh-user-approval']}

_operation_owner=threading.local()
_operation_labels={'start':'启动','stop':'关闭','switch':'切换版本','snapshot':'建立恢复点','restore':'恢复','clock':'核对时间'}

@contextmanager
def vm_operation(action):
 if action not in _operation_labels:raise ValueError('Unknown VM operation')
 key=(os.getpid(),str(ROOT))
 if getattr(_operation_owner,'key',None)==key:
  yield;return
 if ROOT.is_symlink() or not ROOT.is_dir() or ROOT.stat().st_uid!=os.getuid() or ROOT.stat().st_mode&0o077:raise ValueError('VM operation lock requires the private owner directory')
 fd=os.open(ROOT/'.vm-operation.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,0o600)
 acquired=False
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1:raise ValueError('VM operation lock must be a private regular file')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:
   try:active=json.loads(os.pread(fd,512,0)).get('action')
   except (ValueError,AttributeError):active=None
   if not isinstance(active,str):active=None
   raise RuntimeError('专用 VM 正在进行'+_operation_labels.get(active,'其他操作')+'，请等待完成后重试。') from None
  acquired=True
  data=json.dumps({'action':action,'pid':os.getpid()},ensure_ascii=True).encode()
  os.ftruncate(fd,0);os.pwrite(fd,data,0);os.fsync(fd);_operation_owner.key=key
  yield
 finally:
  try:
   if acquired:
    _operation_owner.key=None
    try:os.ftruncate(fd,0)
    finally:fcntl.flock(fd,fcntl.LOCK_UN)
  finally:os.close(fd)

def vm_mutation(action):
 def decorate(function):
  @functools.wraps(function)
  def guarded(*args,**kwargs):
   with vm_operation(action):return function(*args,**kwargs)
  return guarded
 return decorate

def network_args():return ['-netdev "user,id=purgenet,ipv6=off,restrict=on,hostfwd=tcp:127.0.0.1:49223-:22,hostfwd=tcp:127.0.0.1:49224-:3080,guestfwd=tcp:10.0.2.100:3128-cmd:/usr/bin/nc 127.0.0.1 49222"','-device virtio-net-pci,netdev=purgenet,mac=02:00:00:50:23:01',f'-drive "file={VM}/Data/seed.iso,if=none,media=cdrom,readonly=on,id=cloudseed"','-device virtio-scsi-pci,id=seedscsi','-device scsi-cd,bus=seedscsi.0,drive=cloudseed']

def expected_config_fixture():return {'Information':{'UUID':UUID},'Network':[],'Sharing':{'ClipboardSharing':False,'DirectoryShareMode':'None'},'Input':{'UsbSharing':False,'MaximumUsbShare':0},'QEMU':{'AdditionalArguments':network_args()},'Drive':[{'ImageName':'ubuntu.qcow2','ImageType':'Disk','Interface':'VirtIO','ReadOnly':False}],'Serial':[{'Mode':'TcpServer','Target':'Auto','TcpPort':49225,'WaitForConnection':False,'RemoteConnectionAllowed':False}]}

def validate_config(c):
 if c.get('Information',{}).get('UUID')!=UUID:raise ValueError('Wrong VM identity')
 if c.get('Network')!=[]:raise ValueError('Normal network interface is forbidden')
 if c.get('Sharing',{}).get('ClipboardSharing') is not False or c.get('Sharing',{}).get('DirectoryShareMode')!='None':raise ValueError('Host sharing/clipboard must remain off')
 if c.get('Input',{}).get('UsbSharing') is not False or c['Input'].get('MaximumUsbShare')!=0:raise ValueError('Host USB passthrough must remain off')
 if c.get('QEMU',{}).get('AdditionalArguments')!=network_args():raise ValueError('Restricted network/custom devices changed; launch refused pending review')
 drives=c.get('Drive',[])
 if len(drives)!=1 or drives[0].get('ImageName')!='ubuntu.qcow2' or drives[0].get('ImageType')!='Disk' or drives[0].get('Interface')!='VirtIO':raise ValueError('Unexpected guest disk or host path')
 serial=c.get('Serial',[])
 if len(serial)!=1 or serial[0].get('Mode')!='TcpServer' or serial[0].get('TcpPort')!=49225 or serial[0].get('RemoteConnectionAllowed') is not False:raise ValueError('Serial console must remain loopback only')

def validate():
 for p in [ROOT,VM,VM/'config.plist',VM/'Data',VM/'Data/ubuntu.qcow2',VM/'Data/seed.iso',SETUP,SETUP/'guest-ed25519',SETUP/'known_hosts']:
  if p.is_symlink():raise ValueError('Dedicated VM path cannot be a symlink')
  if not p.exists():raise ValueError('Missing VM prerequisite: '+str(p))
 if ROOT.stat().st_mode&0o077:raise ValueError('VM root must be owner-only')
 if (SETUP/'known_hosts').stat().st_mode&0o077:raise ValueError('Dedicated SSH trust file must be owner-only')
 lines=(SETUP/'known_hosts').read_text().splitlines()
 if len(lines)!=1 or not re.fullmatch(r'\[127\.0\.0\.1\]:49223 ssh-ed25519 [A-Za-z0-9+/=]+',lines[0]):raise ValueError('Dedicated SSH trust must contain exactly this VM host key')
 validate_config(plistlib.loads((VM/'config.plist').read_bytes()))

def command(argv,**kw):return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=kw.pop('timeout',30),**kw)

SSH_REASONS={'queue-timeout':'SSH channel busy; request not sent','connection-refused':'Connection refused','connection-reset':'Connection reset by peer','connection-closed':'Connection closed','connection-timeout':'Connection timed out','authentication-denied':'Permission denied (publickey)','host-key-mismatch':'Host key verification failed','identity-unavailable':'Dedicated SSH identity unavailable','timeout':'SSH command deadline exceeded','remote-or-unknown-error':'SSH or remote command error; raw command and output omitted'}
SSH_PHASES={'general','clock-read','clock-set','service-readiness','access-url','guest-shutdown','runtime-status','recovery-proof','program-update','native-check','diagnostic-sample'}
SSH_TRANSPORT_STAGES={'queue','connect','identification','authentication','host-key','remote','unknown'}
REMOTE_EXCEPTIONS={'AssertionError','ValueError','TypeError','KeyError','IndexError','AttributeError','CalledProcessError','TimeoutExpired','OSError','PermissionError','FileNotFoundError','ModuleNotFoundError','ImportError','RuntimeError','SyntaxError'}

def valid_ssh_trace(value):
 return isinstance(value,dict) and set(value) in ({'id','phase','remoteException','remoteLine'},{'id','phase','remoteException','remoteLine','transportStage'}) and ('transportStage' not in value or isinstance(value['transportStage'],str) and value['transportStage'] in SSH_TRANSPORT_STAGES) and isinstance(value['id'],str) and re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value['id']) is not None and isinstance(value['phase'],str) and value['phase'] in SSH_PHASES and (value['remoteException'] is None or isinstance(value['remoteException'],str) and value['remoteException'] in REMOTE_EXCEPTIONS) and (value['remoteLine'] is None or type(value['remoteLine']) is int and 1<=value['remoteLine']<=999999)

def reported_transport_stage(raw,code):
 if code!=255:return 'remote'
 if isinstance(raw,bytes):raw=raw.decode('utf-8','replace')
 if not isinstance(raw,str):return 'unknown'
 raw=raw[:8192].lower()
 if any(marker in raw for marker in ['kex_exchange_identification','ssh_exchange_identification','banner exchange']):return 'identification'
 if 'permission denied (publickey' in raw:return 'authentication'
 if 'host key verification failed' in raw:return 'host-key'
 if 'ssh: connect to host ' in raw:return 'connect'
 return 'unknown'

def reported_remote_failure(raw):
 # Keep only allowlisted Python exception names and a numeric stdin frame.
 # Never persist a traceback message, filename, source line or command.
 if isinstance(raw,bytes):raw=raw.decode('utf-8','replace')
 if not isinstance(raw,str):return None,None
 raw=raw[-8192:].strip()
 if 'Traceback (most recent call last):' not in raw:return None,None
 match=re.match(r'^([A-Za-z]+)(?::|$)',raw.splitlines()[-1])
 kind=match.group(1) if match and match.group(1) in REMOTE_EXCEPTIONS else None
 lines=re.findall(r'^\s*File "<stdin>", line ([1-9][0-9]{0,5}),',raw,re.M)
 return kind,int(lines[-1]) if kind and lines else None

def ssh_trace_text(error):
 trace=getattr(error,'trace',None)
 if not valid_ssh_trace(trace):return ''
 return '; ref='+trace['id']+' phase='+trace['phase']+' transport='+trace.get('transportStage','unknown')+((' reported='+trace['remoteException']) if trace['remoteException'] else '')+((' stdinLine='+str(trace['remoteLine'])) if trace['remoteLine'] else '')+' diagnosticSaved='+str(getattr(error,'diagnosticRecorded',False)).lower()

def ssh_diagnostics():
 try:fd=os.open(ROOT/'ssh-diagnostics.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 except FileNotFoundError:return []
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1 or info.st_size>65536:raise ValueError('Unsafe SSH diagnostic file')
  with os.fdopen(fd,'r') as source:fd=None;rows=json.load(source)
 finally:
  if fd is not None:os.close(fd)
 if not isinstance(rows,list) or len(rows)>50:raise ValueError('Invalid SSH diagnostics')
 for row in rows:
  base={'observedAtUnix','elapsedMs','exitCode','reason','detail'}
  if not isinstance(row,dict) or set(row) not in (base,base|{'trace'}) or row.get('reason') not in SSH_REASONS or row.get('detail')!=SSH_REASONS[row['reason']]:raise ValueError('Invalid SSH diagnostic row')
  if 'trace' in row and not valid_ssh_trace(row['trace']):raise ValueError('Invalid SSH diagnostic trace')
  if any(type(row[key]) not in (int,float) or not math.isfinite(row[key]) or row[key]<0 for key in ['observedAtUnix','elapsedMs']):raise ValueError('Invalid SSH diagnostic time')
  if row['exitCode'] is not None and (type(row['exitCode']) is not int or not -128<=row['exitCode']<=255):raise ValueError('Invalid SSH diagnostic exit')
 return rows

def record_ssh_failure(reason,code,elapsed,trace=None):
 fd=None;temporary=None
 try:
  info=ROOT.stat()
  if ROOT.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:return False
  fd=os.open(ROOT/'.ssh-diagnostics.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600);info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1:return False
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if trace is not None and not valid_ssh_trace(trace):return False
  rows=ssh_diagnostics();rows.append({'observedAtUnix':time.time(),'elapsedMs':max(0,round(elapsed*1000)),'exitCode':code,'reason':reason,'detail':SSH_REASONS[reason],**({'trace':trace} if trace is not None else {})})
  out,temporary=tempfile.mkstemp(prefix='.ssh-diagnostic-',dir=ROOT)
  with os.fdopen(out,'w') as stream:json.dump(rows[-50:],stream);stream.flush();os.fsync(stream.fileno())
  os.replace(temporary,ROOT/'ssh-diagnostics.json');temporary=None
  return True
 except Exception:return False
 finally:
  if temporary is not None:
   try:os.unlink(temporary)
   except OSError:pass
  if fd is not None:os.close(fd)

class SSHFailure(subprocess.CalledProcessError):
 def __str__(self):return f'VM SSH failed (exit {self.returncode}): '+SSH_REASONS[self.reason]+ssh_trace_text(self)

class SSHNotSent(subprocess.TimeoutExpired):
 def __str__(self):return f'VM SSH channel wait timed out after {self.timeout} seconds; request not sent'+ssh_trace_text(self)

class SSHChannelWaitExpired(TimeoutError):pass

def terminate_ssh_controller(signum,_frame):raise SystemExit(128+signum)

@contextmanager
def ssh_channel(deadline):
 # Separate from the VM lifecycle lock: ordinary read-only status calls use it
 # too. Keep one channel through command exit; never replay a remote operation.
 if ROOT.is_symlink() or not ROOT.is_dir() or ROOT.stat().st_uid!=os.getuid() or ROOT.stat().st_mode&0o077:raise ValueError('SSH channel requires the private owner directory')
 fd=os.open(ROOT/'.ssh-channel.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,0o600)
 term_guard=threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM)==signal.SIG_DFL
 try:
  # execFile's outer deadline sends SIGTERM. Unwind subprocess.run so its
  # active SSH child is killed/reaped before the channel descriptor closes.
  if term_guard:signal.signal(signal.SIGTERM,terminate_ssh_controller)
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1:raise ValueError('SSH channel lock must be a private regular file')
  while True:
   remaining=deadline-time.monotonic()
   if remaining<=0:raise SSHChannelWaitExpired('SSH channel wait deadline')
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:time.sleep(min(.02,remaining))
  yield
 finally:
  try:os.close(fd)
  finally:
   if term_guard:signal.signal(signal.SIGTERM,signal.SIG_DFL)

class SSHDeadline(subprocess.TimeoutExpired):
 def __str__(self):return f'VM SSH command timed out after {self.timeout} seconds; remote outcome unconfirmed'+ssh_trace_text(self)

def ssh(script,timeout=15,*,input=None,phase='general'):
 if not isinstance(phase,str) or phase not in SSH_PHASES:raise ValueError('Unknown SSH diagnostic phase')
 if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:raise ValueError('SSH timeout must be finite and positive')
 trace={'id':str(uuid.uuid4()),'phase':phase,'remoteException':None,'remoteLine':None,'transportStage':'unknown'}
 argv=['/usr/bin/ssh','-F','/dev/null','-p','49223','-i',str(SETUP/'guest-ed25519'),'-o','IdentityAgent=none','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=3','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+str(SETUP/'known_hosts')+'"','-o','GlobalKnownHostsFile=/dev/null','purge@127.0.0.1']
 started=time.monotonic()
 try:
  with ssh_channel(started+timeout):
   # A trusted local builder samples clock inputs only after queueing.
   prepared=script() if callable(script) else script
   if not isinstance(prepared,str):raise ValueError('SSH command must be text')
   remaining=started+timeout-time.monotonic()
   if remaining<=0:raise SSHChannelWaitExpired('SSH channel wait deadline')
   return command([*argv,prepared],timeout=remaining,**({'input':input} if input is not None else {}))
 except SSHChannelWaitExpired:
  trace['transportStage']='queue'
  failure=SSHNotSent('managed SSH request',timeout);failure.trace=trace;failure.diagnosticRecorded=record_ssh_failure('queue-timeout',None,time.monotonic()-started,trace)
  raise failure from None
 except subprocess.CalledProcessError as error:
  reason='remote-or-unknown-error';raw=error.stderr
  if isinstance(raw,bytes):raw=raw.decode('utf-8','replace')
  if error.returncode==255 and isinstance(raw,str):
   for key,needle in [('connection-refused','connection refused'),('connection-reset','connection reset by peer'),('connection-closed','connection closed'),('connection-timeout','connection timed out'),('authentication-denied','permission denied (publickey'),('host-key-mismatch','host key verification failed'),('identity-unavailable','no such identity')]:
    if needle in raw[:8192].lower():reason=key;break
  failure=SSHFailure(error.returncode,error.cmd,output=error.output,stderr=error.stderr);failure.reason=reason
  trace['transportStage']=reported_transport_stage(error.stderr,error.returncode)
  if error.returncode!=255:trace['remoteException'],trace['remoteLine']=reported_remote_failure(error.stderr)
  failure.trace=trace;failure.diagnosticRecorded=record_ssh_failure(reason,error.returncode,time.monotonic()-started,trace)
  raise failure from None
 except subprocess.TimeoutExpired as error:
  failure=SSHDeadline(error.cmd,error.timeout,output=error.output,stderr=error.stderr);failure.trace=trace;failure.diagnosticRecorded=record_ssh_failure('timeout',None,time.monotonic()-started,trace)
  raise failure from None

SSH_JOURNAL_MARKERS={'maxStartups':'maxstartups','drop':'drop connection','penalty':'penalty','forkFailure':'fork:','outOfMemory':'cannot allocate memory','acceptedKey':'accepted publickey','preAuthClosed':'[preauth]'}

def summarize_ssh_journal(raw):
 unavailable={'state':'unavailable','rows':None,'truncated':False,'markers':None}
 try:
  if not isinstance(raw,str) or len(raw.encode('utf-8'))>262144:return unavailable
  lines=raw.splitlines()
  if len(lines)>201:return unavailable
  messages=[]
  for line in lines:
   row=json.loads(line)
   if not isinstance(row,dict) or not isinstance(row.get('MESSAGE'),str):return unavailable
   messages.append(row['MESSAGE'].lower())
  return {'state':'read','rows':min(200,len(messages)),'truncated':len(messages)>200,'markers':{key:sum(marker in message for message in messages[:200]) for key,marker in SSH_JOURNAL_MARKERS.items()}}
 except (ValueError,UnicodeError):return unavailable

def capture_ssh_journal(start,end):
 """Bound stdout and kill the fixed command's process group, including pipe holders."""
 import os,signal,subprocess,threading
 journal={'state':'unavailable','rows':None,'truncated':False,'markers':None}
 process=None;timer=None
 def stop():
  if process is not None:
   try:os.killpg(process.pid,signal.SIGKILL)
   except ProcessLookupError:pass
 try:
  process=subprocess.Popen(['/usr/bin/journalctl','--boot=0','-u','ssh.service','--since','@'+str(start),'--until','@'+str(end),'-n','201','--output=json','--output-fields=MESSAGE','--no-pager'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
  timer=threading.Timer(3,stop);timer.start();raw=process.stdout.read(262145)
  if len(raw)>262144:stop()
  code=process.wait(timeout=1)
  if code==0 and len(raw)<=262144:journal=summarize_ssh_journal(raw.decode('utf-8'))
 except (OSError,ValueError,subprocess.SubprocessError):pass
 finally:
  if timer is not None:timer.cancel()
  if process is not None:
   stop();process.wait(timeout=1)
   process.stdout.close()
 return journal

def guest_ssh_correlation(start,end):
 """Fixed read-only VM observer runs as the existing VM admin, never on the host."""
 from pathlib import Path
 import os,subprocess,time
 if os.geteuid()!=0:raise PermissionError('VM observer identity unavailable')
 now=time.time();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();boot_started=now-float(Path('/proc/uptime').read_text().split()[0])
 state=subprocess.run(['/usr/bin/systemctl','is-active','ssh.service'],capture_output=True,text=True,timeout=2).stdout.strip()
 if state not in {'active','inactive','failed','activating','deactivating'}:state='unknown'
 journal=capture_ssh_journal(start,end)
 return {'serviceState':state,'bootId':boot,'guestObservedAtUnix':now,'guestBootStartedAtUnix':boot_started,'journal':journal}

def valid_ssh_server_sample(value):
 if not isinstance(value,dict) or set(value)!={'serviceState','bootId','guestObservedAtUnix','guestBootStartedAtUnix','journal'} or value['serviceState'] not in {'active','inactive','failed','activating','deactivating','unknown'} or not isinstance(value['bootId'],str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value['bootId']):return False
 if any(type(value[key]) not in (int,float) or not math.isfinite(value[key]) or value[key]<=0 for key in ['guestObservedAtUnix','guestBootStartedAtUnix']):return False
 journal=value['journal']
 if not isinstance(journal,dict) or set(journal)!={'state','rows','truncated','markers'} or type(journal['truncated']) is not bool:return False
 if journal['state']=='unavailable':return journal['rows'] is None and journal['markers'] is None and not journal['truncated']
 return journal['state']=='read' and type(journal['rows']) is int and 0<=journal['rows']<=200 and isinstance(journal['markers'],dict) and set(journal['markers'])==set(SSH_JOURNAL_MARKERS) and all(type(count) is int and 0<=count<=journal['rows'] for count in journal['markers'].values())

def store_ssh_correlation(value):
 temporary=None
 try:
  info=ROOT.stat()
  if ROOT.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:return False
  path=ROOT/'ssh-correlation.json'
  try:
   previous=path.lstat()
   if not stat.S_ISREG(previous.st_mode) or previous.st_uid!=os.getuid() or previous.st_mode&0o077 or previous.st_nlink!=1:return False
  except FileNotFoundError:pass
  raw=json.dumps(value).encode()
  if len(raw)>8192:return False
  fd,temporary=tempfile.mkstemp(prefix='.ssh-correlation-',dir=ROOT)
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.replace(temporary,path);temporary=None;return True
 except (OSError,ValueError,TypeError):return False
 finally:
  if temporary is not None:
   try:os.unlink(temporary)
   except OSError:pass

def correlate_ssh_failure(reference=None):
 """Observe a saved failure through a new read-only connection; never replay it."""
 rows=ssh_diagnostics();available=[row for row in rows if valid_ssh_trace(row.get('trace'))]
 if reference is None:reference=available[-1]['trace']['id'] if available else None
 if not isinstance(reference,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',reference):raise ValueError('No saved SSH failure reference')
 original=next((row for row in available if row['trace']['id']==reference),None)
 if original is None:raise ValueError('SSH failure reference not found')
 validate();started=time.time();begin=time.monotonic();duration=min(original['elapsedMs']/1000,120);start=max(0,original['observedAtUnix']-duration-2);end=original['observedAtUnix']+2
 result={'reference':reference,'failureObservedAtUnix':original['observedAtUnix'],'sampledAtUnix':started,'windowStartUnix':start,'windowEndUnix':end,'attemptWindowClipped':original['elapsedMs']>120000,'vmState':'unknown','probeState':'unavailable','probeFailureReference':None,'server':None,'currentClockOffsetRangeSeconds':None,'failureWindowWithinCurrentBoot':None,'correlationState':'unavailable','exactConnectionIdentified':False}
 try:
  vm=vm_status();result['vmState']=vm if vm in {'started','stopped','paused','starting','stopping'} else 'unknown'
  if vm!='started':result['probeState']='not-running'
  else:
   source='import json\nSSH_JOURNAL_MARKERS='+repr(SSH_JOURNAL_MARKERS)+'\n'+inspect.getsource(summarize_ssh_journal)+'\n'+inspect.getsource(capture_ssh_journal)+'\n'+inspect.getsource(guest_ssh_correlation)+'\nprint(json.dumps(guest_ssh_correlation('+repr(start)+','+repr(end)+')))\n'
   before=time.time();probe=ssh('sudo -n /usr/bin/python3 -',input=source,timeout=15,phase='diagnostic-sample');after=time.time()
   if len(probe.stdout.encode('utf-8'))>8192:raise ValueError('Oversized SSH sample')
   server=json.loads(probe.stdout)
   if not valid_ssh_server_sample(server):raise ValueError('Invalid SSH sample')
   offsets=[server['guestObservedAtUnix']-after,server['guestObservedAtUnix']-before];comparable=offsets[0]>=-2 and offsets[1]<=2
   result.update(probeState='read',server=server,currentClockOffsetRangeSeconds=offsets,correlationState='time-window-only' if comparable else 'clock-unconfirmed')
   if comparable:
    earliest=start+offsets[0];latest=start+offsets[1];boot=server['guestBootStartedAtUnix'];result['failureWindowWithinCurrentBoot']=True if earliest>=boot else False if latest<boot else None
   else:server['journal']={'state':'unavailable','rows':None,'truncated':False,'markers':None}
 except Exception as error:
  trace=getattr(error,'trace',None)
  if valid_ssh_trace(trace):result['probeFailureReference']=trace['id']
 result['elapsedMs']=max(0,round((time.monotonic()-begin)*1000));recorded=store_ssh_correlation(result)
 return {**result,'recorded':recorded}

def vm_status():return command([UTM,'status',UUID],timeout=10).stdout.strip()

WEB_LABEL='com.personal.harness-purge-original-web-entry'

def web_entry_job():return {'Label':WEB_LABEL,'ProgramArguments':['/opt/homebrew/bin/node',str(TOOLS/'web-entry.mjs')],'WorkingDirectory':str(TOOLS),'RunAtLoad':False,'KeepAlive':False,'ProcessType':'Background','StandardOutPath':str(ROOT/'web-entry.stdout.log'),'StandardErrorPath':str(ROOT/'web-entry.stderr.log')}

def web_entry_listener_owned():
 target='gui/'+str(os.getuid())+'/'+WEB_LABEL
 state=subprocess.run(['/bin/launchctl','print',target],capture_output=True,text=True,timeout=5)
 pid=re.search(r'^\s*pid = (\d+)\s*$',state.stdout,re.M)
 if state.returncode or not pid:return False
 result=subprocess.run(['/usr/sbin/lsof','-nP','-a','-p',pid.group(1),'-iTCP:49226','-sTCP:LISTEN','-Fn'],capture_output=True,text=True,timeout=5)
 return result.returncode==0 and {line for line in result.stdout.splitlines() if line.startswith('n')}=={'n127.0.0.1:49226'}

def web_entry_start():
 plist=Path.home()/'Library/LaunchAgents'/f'{WEB_LABEL}.plist'
 if plist.is_symlink() or plistlib.loads(plist.read_bytes())!=web_entry_job():raise ValueError('Stable web entry launch definition changed; refusing')
 domain='gui/'+str(os.getuid());target=domain+'/'+WEB_LABEL
 if subprocess.run(['/bin/launchctl','print',target],capture_output=True,timeout=10).returncode!=0:
  command(['/bin/launchctl','bootstrap',domain,str(plist)])
 command(['/bin/launchctl','kickstart',target])
 deadline=time.monotonic()+8
 while time.monotonic()<deadline:
  if web_entry_listener_owned():return
  time.sleep(0.1)
 raise RuntimeError('Stable entry listener is not owned by the managed process; no login token sent')

def web_entry_stop():
 target='gui/'+str(os.getuid())+'/'+WEB_LABEL
 result=subprocess.run(['/bin/launchctl','kill','SIGTERM',target],capture_output=True,timeout=10)
 if result.returncode:
  state=subprocess.run(['/bin/launchctl','print',target],capture_output=True,text=True,timeout=10)
  if state.returncode==0 and re.search(r'^\s*pid = \d+',state.stdout,re.M):raise RuntimeError('Stable web entry termination failed')
 deadline=time.monotonic()+8
 while time.monotonic()<deadline:
  try:
   with socket.create_connection(('127.0.0.1',49226),timeout=0.5):pass
  except ConnectionRefusedError:return
  except ConnectionResetError:pass  # Closing listener can reset a probe; keep waiting for refusal.
  time.sleep(0.2)
 raise RuntimeError('Stable web entry remains open after stop')

def job_spec():return {'Label':LABEL,'ProgramArguments':[PYTHON,str(TOOLS/'egress_proxy.py')],'WorkingDirectory':str(TOOLS),'RunAtLoad':False,'KeepAlive':False,'ProcessType':'Background','StandardOutPath':str(ROOT/'proxy.stdout.log'),'StandardErrorPath':str(ROOT/'proxy.stderr.log'),'SoftResourceLimits':{'NumberOfFiles':128,'NumberOfProcesses':24}}

def proxy_start():
 if plistlib.loads(PLIST.read_bytes())!=job_spec():raise ValueError('Proxy launch definition changed; refusing')
 domain='gui/'+str(os.getuid());target=domain+'/'+LABEL
 present=subprocess.run(['/bin/launchctl','print',target],capture_output=True,timeout=10)
 if present.returncode!=0:command(['/bin/launchctl','bootstrap',domain,str(PLIST)])
 command(['/bin/launchctl','kickstart',target])

URL_SCRIPT="""python3 - <<'VM_URL'
import subprocess,re,os
s=subprocess.run(['journalctl','--user','-u','dsh-original','-b','-n','40','--no-pager'],capture_output=True,text=True,check=True,env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/'+str(os.getuid())}).stdout
urls=re.findall(r'http://127\\.0\\.0\\.1:49224/\\?token=[A-Za-z0-9_-]+',s)
assert urls,'No current authenticated URL found'
print(urls[-1])
VM_URL"""

class LocalRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  if newurl!='http://127.0.0.1:49226/':raise urllib.error.HTTPError('local VM readiness',403,'Redirect outside fixed VM entry denied',headers,fp)
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def authenticated_ready(url):
 if not re.fullmatch(r'http://127\.0\.0\.1:49226/\?token=[A-Za-z0-9_-]+',url):return False
 client=urllib.request.build_opener(urllib.request.ProxyHandler({}),LocalRedirect(),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 try:
  with client.open(url,timeout=3) as response:
   if response.status!=200:return False
   document=response.read(2*1024*1024+1)
  if len(document)>2*1024*1024:return False
  assets=list(dict.fromkeys(re.findall(r'(?:src|href)=[\"\']\.?(/assets/[A-Za-z0-9._-]+\.(?:js|css))[\"\']',document.decode('utf-8'))))
  if not assets or len(assets)>16:return False
  base='http://127.0.0.1:49226'
  for asset in assets:
   with client.open(base+asset,timeout=3) as response:
    if response.status!=200 or len(response.read(8*1024*1024+1))>8*1024*1024:return False
  request=urllib.request.Request(base+'/redteam/api',json.dumps({'op':'bootstrap'}).encode(),{'Origin':base,'Content-Type':'application/json','Sec-Fetch-Site':'same-origin'})
  with client.open(request,timeout=3) as response:return response.status==200 and json.loads(response.read(2*1024*1024)).get('ok') is True
 except (OSError,ValueError):return False

def measure_guest_clock():
 before=None
 def request():
  nonlocal before
  before=time.time()
  return "python3 -c 'import time; print(time.time())'"
 raw=ssh(request,timeout=5,phase='clock-read').stdout.strip()
 after=time.time()
 guest=float(raw)
 if before is None or not math.isfinite(guest) or not 0<=after-before<=2:raise ValueError('Guest clock measurement invalid or too slow; no time change attempted')
 return (before+after)/2-guest

def synchronize_clock():
 offset=measure_guest_clock()
 adjusted=abs(offset)>2
 if adjusted:
  def request():
   epoch=time.time()
   if not math.isfinite(epoch) or epoch<=0:raise ValueError('Host clock unavailable')
   # Only the dedicated guest is set; sample after acquiring its channel.
   return f'sudo -n /usr/bin/date -u --set=@{epoch:.6f} >/dev/null'
  ssh(request,timeout=8,phase='clock-set')
  offset=measure_guest_clock()
  if abs(offset)>2:raise RuntimeError('Guest clock adjustment was not verified; startup readiness stopped')
 return {'adjusted':adjusted,'offsetSeconds':round(offset,6)}

def guest_ssh_listening():
 try:
  value=command(['/usr/sbin/lsof','-nP','-a','-u',str(os.getuid()),'-iTCP@127.0.0.1:49223','-sTCP:LISTEN','-Fp'],timeout=5).stdout
 except subprocess.CalledProcessError as error:
  if error.returncode==1:return False
  raise
 return any(re.fullmatch(r'p[1-9][0-9]*',line) for line in value.splitlines())

def maintain_clock():
 try:
  with vm_operation('clock'):
   validate()
   # Background launchd children cannot reliably use UTM's GUI IPC. Observe
   # only our owned loopback SSH listener; SSH still checks the pinned host key.
   if not guest_ssh_listening():return {'state':'skipped','reason':'not-listening'}
   value=synchronize_clock()
   return {'state':'adjusted' if value['adjusted'] else 'current',**value}
 except RuntimeError as error:
  if str(error).startswith('专用 VM 正在进行'):return {'state':'skipped','reason':'busy'}
  raise

@vm_mutation('start')
def start(quiet=False):
 validate();proxy_start()
 if vm_status()!='started':command([UTM,'start',UUID],timeout=30)
 deadline=time.monotonic()+75;last=None;clock_checked=False;entry_checked=False
 while time.monotonic()<deadline:
  try:
   active=ssh('XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active dsh-original',timeout=6,phase='service-readiness')
   if active.stdout.strip()=='active':
    if not clock_checked:
     clock=synchronize_clock();clock_checked=True
     print('VM clock verified: '+json.dumps(clock))
    if not entry_checked:
     web_entry_start();entry_checked=True
    url=ssh(URL_SCRIPT,phase='access-url').stdout.strip()
    if not re.fullmatch(r'http://127\.0\.0\.1:49224/\?token=[A-Za-z0-9_-]+',url):raise ValueError('Invalid guest access URL')
    url=url.replace(':49224/',':49226/',1)
    if authenticated_ready(url):break
  except (subprocess.SubprocessError,OSError) as error:last=type(error).__name__
  time.sleep(1)
 else:raise RuntimeError('VM started but guest service did not become ready; no permission change or fallback attempted: '+str(last))
 if not re.fullmatch(r'http://127\.0\.0\.1:49226/\?token=[A-Za-z0-9_-]+',url):raise ValueError('Invalid stable access URL')
 fd=os.open(ROOT/'access-url.txt',os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write(url+'\n')
 os.chmod(ROOT/'access-url.txt',0o600)
 shortcut=ROOT/'打开虚拟机Harness.webloc'
 fd=os.open(shortcut,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:plistlib.dump({'URL':url},f)
 os.chmod(shortcut,0o600)
 print('专用虚拟机已启动。当前版本和权限以 Harness 会话为准；宿主共享关闭。')
 if not quiet:print('也可在 Finder 双击本次更新的登录快捷方式：\n'+str(shortcut)+'\n在浏览器中打开以下完整本机地址（含本地访问令牌，请勿分享）：\n'+url)
 else:print('Authenticated URL saved privately; token omitted from diagnostics.')

@vm_mutation('switch')
def switch(mode,quiet=False):
 if mode not in ('original','improved'):raise ValueError('Only original or improved mode is supported')
 start(True)
 script="""python3 - <<'VM_MODE'
import os,subprocess
from pathlib import Path
mode = MODE_VALUE
root=Path('/home/purge')
entry=root/('.local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js' if mode=='original' else 'tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js')
profile=root/('.dsh' if mode=='original' else '.dsh-improved')/'profiles/web/package.json'
if not entry.is_file() or not profile.is_file():raise RuntimeError('Selected runtime is not installed')
target=root/'.config/harness-vm-mode'
if target.is_symlink():raise RuntimeError('Refusing symbolic mode file')
temporary=target.with_name(target.name+'.next-'+str(os.getpid()))
fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as output:output.write(mode+'\\n')
os.replace(temporary,target)
subprocess.run(['systemctl','--user','restart','dsh-original'],check=True,timeout=30,env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/'+str(os.getuid())})
print('Selected VM mode: '+mode)
VM_MODE""".replace('MODE_VALUE',repr(mode))
 ssh(script,timeout=40)
 start(quiet)
 print('已切换到'+('改进版：采用 VM 独立权限配置；具体档位见会话菜单。' if mode=='improved' else '完整原版：完全访问仅限专用虚拟机。'))

def proxy_stop():
 target='gui/'+str(os.getuid())+'/'+LABEL
 result=subprocess.run(['/bin/launchctl','kill','SIGTERM',target],capture_output=True,timeout=10)
 if result.returncode:
  state=subprocess.run(['/bin/launchctl','print',target],capture_output=True,text=True,timeout=10)
  if state.returncode==0 and re.search(r'^\s*pid = \d+',state.stdout,re.M):raise RuntimeError('Proxy termination failed; inspect the dedicated launch job')
 deadline=time.monotonic()+8
 while time.monotonic()<deadline:
  try:
   with socket.create_connection(('127.0.0.1',49222),timeout=0.5):pass
  except ConnectionRefusedError:return
  time.sleep(0.2)
 raise RuntimeError('Port 49222 remains open; proxy stop not confirmed')

@vm_mutation('stop')
def stop():
 validate()
 state=vm_status()
 if state not in ('started','stopped'):raise RuntimeError('VM state is '+state+'; resume it in UTM before normal shutdown')
 if state=='started':
  try:ssh('sudo /usr/sbin/shutdown -h now',timeout=10,phase='guest-shutdown')
  except subprocess.CalledProcessError as e:
   if e.returncode!=255:raise
  deadline=time.monotonic()+45
  while time.monotonic()<deadline:
   if vm_status()=='stopped':break
   time.sleep(1)
  else:raise RuntimeError('Guest did not shut down; refusing forced stop')
 web_entry_stop();proxy_stop()
 print('专用虚拟机已正常关闭，出网代理已停止。')

def image_command(args,timeout=30,helper=None):
 # Archived helpers execute the bytes whose digest was checked, never a path
 # that can be replaced between verification and process startup.
 pinned=isinstance(helper,bytes)
 return command([PYTHON,'-' if pinned else str(helper or TOOLS/'qemu-image.py'),*args],timeout=timeout,env={**os.environ,'DYLD_FRAMEWORK_PATH':'/Applications/UTM.app/Contents/Frameworks'},**({'input':helper.decode('utf-8')} if pinned else {}))

def recovery_path(snapshot):
 if snapshot not in REVIEWED_RECOVERIES:raise ValueError('Unreviewed current recovery name')
 folder=ROOT/'recoveries'/snapshot
 for path in [folder.parent,folder]:
  if path.is_symlink():raise ValueError('Recovery path cannot be a symlink')
 return folder

RECOVERY_JSON_LIMIT=2*1024*1024
RECOVERY_FILE_LIMIT=8*1024*1024

@contextmanager
def recovery_source(path,limit):
 path=Path(path).absolute();launches=Path.home()/'Library/LaunchAgents'
 anchor=ROOT if path.is_relative_to(ROOT) else Path.home() if path.is_relative_to(launches) else path.parent
 parts=path.relative_to(anchor).parts
 if not parts or any(part in ('.','..') for part in parts):raise ValueError('Invalid recovery source path')
 flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC;directories=[];fd=None
 try:
  directory=os.open(anchor,flags|os.O_DIRECTORY);directories.append(directory)
  for part in parts[:-1]:
   directory=os.open(part,flags|os.O_DIRECTORY,dir_fd=directory);directories.append(directory)
  fd=os.open(parts[-1],flags,dir_fd=directory)
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise ValueError('Recovery source must be a bounded regular file')
  with os.fdopen(fd,'rb',closefd=False) as source:yield source
 finally:
  if fd is not None:os.close(fd)
  for directory in reversed(directories):os.close(directory)

def recovery_json(path):
 with recovery_source(path,RECOVERY_JSON_LIMIT) as source:raw=source.read(RECOVERY_JSON_LIMIT+1)
 if len(raw)>RECOVERY_JSON_LIMIT:raise ValueError('Recovery metadata exceeds the size limit')
 return json.loads(raw)

def file_sha(path,limit=RECOVERY_FILE_LIMIT):
 digest=hashlib.sha256();size=0
 with recovery_source(path,limit) as source:
  while chunk:=source.read(65536):
   size+=len(chunk)
   if size>limit:raise ValueError('Recovery source exceeds the size limit')
   digest.update(chunk)
 return digest.hexdigest()

def checked_recovery_source(path,digest,limit=RECOVERY_FILE_LIMIT):
 with recovery_source(path,limit) as source:
  mode=os.fstat(source.fileno()).st_mode&0o777
  raw=source.read(limit+1)
 if len(raw)>limit or not isinstance(digest,str) or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Recovery source checksum mismatch')
 return raw,mode

def validated_recovery_proof(raw,snapshot,allow_legacy=False):
 proof=json.loads(raw)
 if not isinstance(proof,dict) or proof.get('vmUUID')!=UUID or proof.get('mode')!='improved':raise ValueError('Recovery guest proof identity mismatch')
 legacy=allow_legacy and snapshot=='ready-improved-20261026' and 'recoveryName' not in proof
 if not legacy and proof.get('recoveryName')!=snapshot:raise ValueError('Recovery guest proof name mismatch')
 files=proof.get('files')
 if not isinstance(files,dict) or not files or any(not isinstance(name,str) or not name or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) for name,digest in files.items()):raise ValueError('Recovery guest proof inventory is invalid')
 return proof

def prepare_host_bundle(folder,data):
 """Freeze every source before the first write, also for rollback bundles."""
 prepared={}
 for section,subdir,allowed in [('helpers','host-tools',RECOVERY_HELPERS),('launchAgents','launch-agents',{f'{LABEL}.plist',f'{WEB_LABEL}.plist'})]:
  entries=data[section]
  missing=data.get('missingHelpers' if section=='helpers' else 'missingLaunchAgents',[])
  if not isinstance(entries,dict) or not set(entries)<=allowed or not isinstance(missing,list) or any(name not in allowed for name in missing) or set(entries)&set(missing):raise ValueError('Invalid recovery source inventory')
  prepared[section]={name:checked_recovery_source(folder/subdir/name,digest) for name,digest in entries.items()}
 return prepared

def public_archive_name(name):
 return isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._/-]{0,240}',name) and not any(part in ('','.','..') or part.startswith('.') or re.search(r'credential|secret|token|provider',part,re.I) for part in name.split('/'))

def archive_cursor(after):
 if after is None:return None,None
 if isinstance(after,str) and after.startswith('v1:'):
  try:
   if len(after)>4096 or not re.fullmatch(r'v1:[A-Za-z0-9_-]+',after):raise ValueError()
   raw=after[3:];value=json.loads(base64.b64decode(raw+'='*(-len(raw)%4),altchars=b'-_',validate=True))
   if not isinstance(value,list) or len(value)!=2:raise ValueError()
   entry,stack=value
   if not public_archive_name(entry) or '/' in entry or not isinstance(stack,list) or not 1<=len(stack)<=5:raise ValueError()
   previous=None
   for frame in stack:
    if not isinstance(frame,list) or len(frame)!=2:raise ValueError()
    relative,last=frame
    if not public_archive_name(relative) or len(relative.split('/'))>5 or not isinstance(last,str) or last and (not public_archive_name(last) or '/' in last):raise ValueError()
    if previous is None:
     if relative!=entry:raise ValueError()
    elif relative!=previous[0]+'/'+previous[1]:raise ValueError()
    previous=frame
   return entry,stack
  except (ValueError,TypeError,binascii.Error):raise ValueError('Invalid recovery cursor') from None
 if not public_archive_name(after) or len(after)>240 or '/' in after:raise ValueError('Invalid recovery cursor')
 return after,None

def internal_archive_cursor(entry,stack):
 raw=json.dumps([entry,[[frame['path'],frame['after']] for frame in stack]],separators=(',',':')).encode()
 return 'v1:'+base64.urlsafe_b64encode(raw).decode().rstrip('=')

def archive_directory(relative):
 """Read at most 512 entries through pinned directory descriptors."""
 flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC;opened=[]
 try:
  fd=os.open(ROOT,flags);opened.append(fd)
  for part in ['archived-validation',*relative.split('/')]:
   fd=os.open(part,flags,dir_fd=fd);opened.append(fd)
  rows=[];limited=False
  with os.scandir(fd) as listing:
   for index,entry in enumerate(listing):
    if index>=512:limited=True;break
    key=relative+'/'+entry.name
    if not public_archive_name(key):continue
    info=entry.stat(follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):rows.append((entry.name,True,None,None))
    elif stat.S_ISREG(info.st_mode) and entry.name.endswith('.qcow2'):rows.append((entry.name,False,info.st_size,info.st_blocks*512))
  return sorted(rows),limited
 finally:
  for fd in reversed(opened):os.close(fd)

def snapshot_catalog(snapshot_after):
 safe=public_archive_name
 protected={'ready-original','ready-toolchain-20261025',*REVIEWED_RECOVERIES[-3:]}
 snapshot_state='observed';snapshots=[];snapshot_name_limit=False
 try:
  metadata=json.loads(image_command(['info','--force-share','--output=json',str(VM/'Data/ubuntu.qcow2')],timeout=5).stdout)
  if not isinstance(metadata,dict) or not isinstance(metadata.get('snapshots',[]),list):raise ValueError('Invalid disk snapshot metadata')
  records=metadata.get('snapshots',[])
  if any(not isinstance(row,dict) or not isinstance(row.get('name'),str) or not row['name'] for row in records):raise ValueError('Invalid disk snapshot record')
  actual={row['name'] for row in records if safe(row['name']) and len(row['name'])<=240 and '/' not in row['name']}
  snapshot_name_limit=any(not safe(row['name']) or len(row['name'])>240 or '/' in row['name'] for row in records)
 except (OSError,ValueError,TypeError,AttributeError,subprocess.SubprocessError):snapshot_state='unavailable';actual=set()
 names=sorted(actual|set(REVIEWED_RECOVERIES)|protected)
 pinned=list(dict.fromkeys([CURRENT_RECOVERY,'ready-original','ready-toolchain-20261025',*reversed(REVIEWED_RECOVERIES[-3:])]))
 pinned=[name for name in pinned if name in names] if snapshot_after is None else []
 remaining_snapshots=[name for name in names if name not in protected and (snapshot_after is None or name>snapshot_after)]
 selected=remaining_snapshots[:80-len(pinned)]
 next_snapshot_cursor=selected[-1] if len(selected)<len(remaining_snapshots) else None
 for name in [*pinned,*selected]:
  bundle_state='not-reviewed';created=None
  if name in REVIEWED_RECOVERIES:
   bundle_state='missing'
   try:
    if recovery_path(name).exists():
     _,bundle=verify_recovery_bundle(name);bundle_state='verified';created=bundle.get('createdAt')
   except (OSError,ValueError,KeyError,TypeError,AttributeError,subprocess.SubprocessError):bundle_state='invalid'
  present=name in actual if snapshot_state=='observed' else None
  snapshots.append({'name':name,'present':present,'current':name==CURRENT_RECOVERY,'protected':name in protected,'reviewCandidate':present is True and name not in protected,'bundleState':bundle_state,'createdAt':created})
 return {'snapshotState':snapshot_state,'snapshots':snapshots,'nextSnapshotCursor':next_snapshot_cursor},(['snapshot-name-limit'] if snapshot_name_limit else [])

def image_catalog(after):
 safe=public_archive_name;after_entry,resume_stack=archive_cursor(after)
 images=[];base=ROOT/'archived-validation';visited=0;skipped=0;scanned=0;reasons=set();continuation=set();next_cursor=None
 deadline=time.monotonic()+2
 entries=[];remaining=[]
 if base.is_dir() and not base.is_symlink() and base.resolve()==base:
  try:
   with os.scandir(base) as listing:
    for index,entry in enumerate(listing):
     if index>=512:reasons.add('entry-limit');break
     if not entry.is_symlink() and len(entry.name)<=240 and safe(entry.name) and (entry.is_dir(follow_symlinks=False) or entry.name.endswith('.qcow2')):entries.append(entry.name)
  except OSError:reasons.add('read-error')
  remaining=sorted(name for name in entries if after_entry is None or name>after_entry or resume_stack is not None and name==after_entry)
  if resume_stack and after_entry not in entries:reasons.add('read-error')
  for name in remaining[:16]:
   if scanned and (visited>=512 or len(images)>=80 or time.monotonic()>=deadline):break
   path=base/name;scanned+=1
   if path.is_file():
    try:
     with recovery_source(path,2**63-1) as source:info=os.fstat(source.fileno())
     images.append({'id':name,'logicalBytes':info.st_size,'allocatedBytes':info.st_blocks*512,'reviewCandidate':True})
    except (OSError,ValueError):reasons.add('read-error')
    continue
   stack=[{'path':relative,'after':last} for relative,last in resume_stack] if resume_stack and name==after_entry else [{'path':name,'after':''}]
   while stack:
    frame=stack[-1]
    if 'rows' not in frame:
     if visited>=512 or visited and time.monotonic()>=deadline:
      continuation.add('directory-limit' if visited>=512 else 'time-limit');break
     visited+=1
     try:
      rows,limited=archive_directory(frame['path'])
      if limited:reasons.add('directory-entry-limit')
     except OSError:reasons.add('read-error');stack.pop();continue
     metadata={'host-tools','launch-agents','__pycache__'} if frame['path']==name else set()
     skipped+=sum(child in metadata and directory for child,directory,*_ in rows)
     frame['rows']=[row for row in rows if row[0]>frame['after'] and not (row[1] and row[0] in metadata)];frame['index']=0
    if frame['index']>=len(frame['rows']):stack.pop();continue
    if len(images)>=80:continuation.add('image-limit');break
    child,directory,logical,allocated=frame['rows'][frame['index']];frame['index']+=1;frame['after']=child
    relative=frame['path']+'/'+child
    if directory:
     if len(relative.split('/'))>5:reasons.add('depth-limit')
     else:stack.append({'path':relative,'after':''})
    else:images.append({'id':relative,'logicalBytes':logical,'allocatedBytes':allocated,'reviewCandidate':True})
   if stack:
    next_cursor=internal_archive_cursor(name,stack);break
  if next_cursor is None and scanned<len(remaining) and scanned:next_cursor=remaining[scanned-1]
 elif base.exists():reasons.add('invalid-root')
 space=shutil.disk_usage(ROOT);disk=(VM/'Data/ubuntu.qcow2').stat()
 scan={'entriesScanned':scanned,'entriesRemaining':max(0,len(remaining)-scanned),'visitedDirectories':visited,'skippedMetadataDirectories':skipped,'reasons':sorted(reasons),'continuationReasons':sorted(continuation)}
 return {'images':images,'nextCursor':next_cursor,'archiveScan':scan,'storage':{'freeBytes':space.free,'totalBytes':space.total,'primaryLogicalBytes':disk.st_size,'primaryAllocatedBytes':disk.st_blocks*512}}

def recovery_catalog(after=None,snapshot_after=None,part='all'):
 """Read one bounded public list, or both for backward-compatible initial reads."""
 if part not in ('all','snapshots','images') or part=='images' and snapshot_after is not None or part=='snapshots' and after is not None:raise ValueError('Invalid recovery catalog part')
 archive_cursor(after)
 if snapshot_after is not None and (not public_archive_name(snapshot_after) or len(snapshot_after)>240 or '/' in snapshot_after):raise ValueError('Invalid recovery cursor')
 validate()
 result={'part':part,'readOnly':True,'currentRecovery':CURRENT_RECOVERY}
 snapshot_reasons=[]
 if part!='images':
  value,snapshot_reasons=snapshot_catalog(snapshot_after);result.update(value)
 if part!='snapshots':result.update(image_catalog(after))
 scan=result.setdefault('archiveScan',{'entriesScanned':0,'entriesRemaining':0,'visitedDirectories':0,'skippedMetadataDirectories':0,'reasons':[],'continuationReasons':[]})
 scan['reasons']=sorted(set(scan['reasons'])|set(snapshot_reasons))
 result.update(truncated=bool(scan['reasons']),observedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
 return result

def verify_recovery_bundle(snapshot):
 folder=recovery_path(snapshot)
 manifest=folder/'manifest.json'
 if manifest.is_symlink():raise ValueError('Recovery manifest cannot be a symlink')
 data=recovery_json(manifest)
 if not isinstance(data,dict):raise ValueError('Recovery manifest must be an object')
 if data.get('vmUUID')!=UUID or data.get('snapshot')!=snapshot:raise ValueError('Recovery identity mismatch')
 created=data.get('createdAt')
 if not isinstance(created,str) or len(created)!=20 or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z',created):raise ValueError('Recovery creation time is invalid')
 time.strptime(created,'%Y-%m-%dT%H:%M:%SZ')
 if not isinstance(data.get('helpers'),dict) or not isinstance(data.get('launchAgents'),dict):raise ValueError('Recovery inventories must be objects')
 if any(not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value) for value in [data.get('guestProofSha256'),*data['helpers'].values(),*data['launchAgents'].values()]):raise ValueError('Recovery digest is invalid')
 if set(data.get('helpers',{}))!=RECOVERY_HELPERS:raise ValueError('Recovery helper inventory mismatch')
 expected_jobs={f'{LABEL}.plist',f'{WEB_LABEL}.plist'}
 if set(data.get('launchAgents',{}))!=expected_jobs:raise ValueError('Recovery launch inventory mismatch')
 for section,subdir in [('helpers','host-tools'),('launchAgents','launch-agents')]:
  if (folder/subdir).is_symlink():raise ValueError('Recovery directory cannot be a symlink')
  for name,digest in data[section].items():
   path=folder/subdir/name
   if path.is_symlink() or file_sha(path)!=digest:raise ValueError('Recovery bundle checksum mismatch')
 if (folder/'guest-proof.json').is_symlink():raise ValueError('Recovery proof cannot be a symlink')
 proof,_mode=checked_recovery_source(folder/'guest-proof.json',data['guestProofSha256'],RECOVERY_JSON_LIMIT)
 validated_recovery_proof(proof,snapshot,allow_legacy=True)
 return folder,data

def recovery_inventory(proof):
 """Limit coverage to program files and an explicit non-secret tool/config list."""
 if not isinstance(proof,dict) or not isinstance(proof.get('files'),dict):raise ValueError('Recovery proof inventory must be an object')
 prefix='tools/dsh-purge-personal-1.1.77-personal.1/'
 manifests={RECOVERY_PLUGIN_ROOT+name+'/package.json' for name in RECOVERY_PLUGINS}
 fixed=RECOVERY_TOOL_FILES|RECOVERY_CONFIG_FILES|RECOVERY_RUNTIME_FILES|manifests
 def plugin_path(key):
  if not key.startswith(RECOVERY_PLUGIN_ROOT):return False
  parts=key[len(RECOVERY_PLUGIN_ROOT):].split('/')
  return len(parts)>1 and parts[0] in RECOVERY_PLUGINS and not any(part.startswith('.') and not (part=='.gitkeep' and index==len(parts)-1) for index,part in enumerate(parts))
 expected={key:value for key,value in proof.get('files',{}).items() if isinstance(key,str) and isinstance(value,str) and not any(part in ('','..','.') for part in key.split('/')) and (key.startswith(prefix) or key in fixed or plugin_path(key))}
 groups={'program':sorted(key for key in expected if key.startswith(prefix)),'runtime':sorted(RECOVERY_RUNTIME_FILES),'tools':sorted(RECOVERY_TOOL_FILES),'config':sorted(RECOVERY_CONFIG_FILES),'plugins':sorted({key for key in expected if plugin_path(key)}|manifests)}
 return {'expected':expected,'groups':groups,'uncovered':sorted(fixed-expected.keys())}

def plugin_differences(home,expected,roots):
 """Observe only the fixed imported sources; never traverse package symlinks."""
 home=home.resolve();different=set()
 for name,relative in roots.items():
  source=home/relative;link=home/'.dsh-improved/profiles/web/node_modules'/name
  if not link.is_symlink() or link.resolve()!=source:different.add(str(link.relative_to(home)))
  wanted={key for key in expected if key.startswith(relative+'/')};actual=set()
  if source.is_symlink() or source.resolve()!=source or not source.is_dir():
   different.add(relative+'/package.json');continue
  for directory,dirs,files in os.walk(source,followlinks=False):
   for entry in [*dirs,*files]:
    path=Path(directory)/entry;key=str(path.relative_to(home))
    if path.is_symlink():different.add(key)
    elif path.is_file():actual.add(key)
  different.update(wanted^actual)
 return sorted(different)

def deployment_status():
 """Read runtime identity and scoped program/tool/config coverage; never mutate."""
 validate()
 recovery={'state':'missing','name':CURRENT_RECOVERY,'scope':'improved-program-tools-config'};expected={};inventory=None
 for name in reversed(REVIEWED_RECOVERIES):
  try:
   if not recovery_path(name).exists():continue
   folder,bundle=verify_recovery_bundle(name)
   proof=json.loads(checked_recovery_source(folder/'guest-proof.json',bundle['guestProofSha256'],RECOVERY_JSON_LIMIT)[0])
   helper=checked_recovery_source(folder/'host-tools/qemu-image.py',bundle['helpers']['qemu-image.py'])[0]
   inventory=recovery_inventory(proof);expected=inventory['expected']
   if not inventory['groups']['program']:raise ValueError('Missing program coverage')
   launches=current_launch_inventory();archived=bundle.get('launchAgents',{});helpers=current_host_inventory(verify=False)
   helper_changes=['host-tools/'+name for name in sorted(RECOVERY_HELPERS) if not helpers.get(name) or helpers[name]!=bundle['helpers'].get(name)]
   launch_changes=['host-launch-agents/'+key for key in launches if not launches[key] or launches[key]!=archived.get(key)]
   recovery={'state':'pending','name':name,'createdAt':bundle['createdAt'],'scope':'improved-program-tools-config','helpersMatch':not helper_changes,'launchAgentsMatch':not launch_changes,'uncoveredFiles':inventory['uncovered']}
   metadata=json.loads(image_command(['info','--force-share','--output=json',str(VM/'Data/ubuntu.qcow2')],timeout=5,helper=helper).stdout)
   if not isinstance(metadata,dict) or not isinstance(metadata.get('snapshots',[]),list):raise ValueError('Invalid disk snapshot metadata')
   snapshots=metadata.get('snapshots',[])
   if any(not isinstance(row,dict) or not isinstance(row.get('name'),str) for row in snapshots):raise ValueError('Invalid disk snapshot record')
   if not any(row.get('name')==name for row in snapshots):recovery['state']='missing'
  except (OSError,ValueError,KeyError,subprocess.SubprocessError):recovery={'state':'invalid','name':name,'scope':'improved-program-tools-config'};expected={};inventory=None
  break
 script="""from pathlib import Path
import os,subprocess,json,hashlib
home=Path('/home/purge');env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'}
pid=int(subprocess.check_output(['systemctl','--user','show','dsh-original','-p','MainPID','--value'],env=env,text=True).strip())
args=Path('/proc/'+str(pid)+'/cmdline').read_bytes().split(b'\\0')
variables=dict(x.split(b'=',1) for x in Path('/proc/'+str(pid)+'/environ').read_bytes().split(b'\\0') if b'=' in x)
config=variables.get(b'DSH_HOME',b'').decode();mode='unknown';package=None
for label,entry,directory in [('original',home/'.local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js',home/'.dsh'),('improved',home/'tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js',home/'.dsh-improved'),('improved',home/'tools/harness-original-capabilities/lib/bin.js',home/'.dsh-improved')]:
 if str(entry).encode() in args and config==str(directory):mode=label;package=entry.parent.parent/'package.json'
version=None
try:
 if package and not package.is_symlink() and package.resolve().is_relative_to(home):
  with package.open('rb') as source:raw=source.read(65537)
  if len(raw)<=65536:
   metadata=json.loads(raw)
   if isinstance(metadata,dict):version=metadata.get('version')
except (OSError,ValueError):pass
expected=EXPECTED;different=[]
for name,digest in expected.items():
 p=home/name
 try:
  matches=not p.is_symlink() and p.resolve()==p and p.resolve().is_relative_to(home) and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==digest
 except OSError:matches=False
 if not matches:different.append(name)
PLUGIN_OBSERVATION
plugin_changes=plugin_differences(home,expected,PLUGIN_ROOTS)
different=sorted(set(different)|set(plugin_changes))
originalCapabilities=mode=='improved' and str(home/'tools/harness-original-capabilities/lib/bin.js').encode() in args and variables.get(b'DSH_PERSONAL_ORIGINAL')==b'enabled'
print(json.dumps({'originalCapabilities':originalCapabilities,'mode':mode,'configDir':config if mode!='unknown' else 'unverified','modeFile':(home/'.config/harness-vm-mode').read_text().strip(),'filesChecked':len(expected),'differentFiles':different,'runtimePackageVersion':version}))
""".replace('EXPECTED',repr(expected)).replace('PLUGIN_OBSERVATION',inspect.getsource(plugin_differences)).replace('PLUGIN_ROOTS',repr({name:RECOVERY_PLUGIN_ROOT+name for name in RECOVERY_PLUGINS}))
 # Plugin manifests exceed Linux's per-argument shell limit; stream the fixed
 # read-only observer instead of making the inventory a remote command argument.
 actual=json.loads(ssh('python3 -',input=script,timeout=10,phase='runtime-status').stdout)
 if actual.get('mode') not in ('original','improved','unknown'):raise ValueError('Invalid runtime identity')
 if inventory:
  different=set(actual.get('differentFiles',[]));recovery['groups']={}
  for group,names in inventory['groups'].items():
   uncovered=[name for name in names if name not in expected];changed=[name for name in names if name in different]
   recovery['groups'][group]={'state':'uncovered' if group in ('runtime','plugins') and uncovered else 'older' if uncovered or changed else 'matches','filesChecked':len(names)-len(uncovered),'uncoveredFiles':uncovered,'differentFiles':changed}
   if group=='plugins':
    extra=sorted(name for name in different if name.startswith(RECOVERY_PLUGIN_ROOT) or name.startswith('.dsh-improved/profiles/web/node_modules/'))
    differences=sorted(set(changed)|set(extra))
    recovery['groups'][group].update({'differentFiles':differences[:80],'differentFileCount':len(differences),'differenceDetailsTruncated':len(differences)>80})
    if extra:recovery['groups'][group]['state']='older' if not uncovered else 'uncovered'
   if group=='config':
    recovery['groups'][group]['filesChecked']+=len(launches)
    recovery['groups'][group]['differentFiles']+=launch_changes
    if launch_changes:recovery['groups'][group]['state']='older'
   if recovery['state'] in ('missing','invalid'):recovery['groups'][group]['state']=recovery['state']
  recovery['groups']['tools']['filesChecked']+=len(RECOVERY_HELPERS)
  recovery['groups']['tools']['differentFiles']+=helper_changes
  if helper_changes and recovery['groups']['tools']['state']=='matches':recovery['groups']['tools']['state']='older'
 if recovery['state']=='pending':recovery['state']='matches' if actual.get('filesChecked')==len(expected) and not actual.get('differentFiles') and not recovery['uncoveredFiles'] and recovery['helpersMatch'] and recovery['launchAgentsMatch'] else 'older'
 version=actual.get('runtimePackageVersion');version=version if isinstance(version,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}',version) else None
 return {'originalCapabilities':actual.get('originalCapabilities') is True,'mode':actual['mode'],'configDir':actual['configDir'],'runtimePackageVersion':version,'modeFileMatches':actual['mode']==actual.get('modeFile'),'observedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'recovery':recovery}

def current_launch_inventory():
 result={}
 for label in [LABEL,WEB_LABEL]:
  name=label+'.plist';path=Path.home()/'Library/LaunchAgents'/name
  try:result[name]=file_sha(path) if path.is_file() and not path.is_symlink() else None
  except OSError:result[name]=None
 return result

def current_host_inventory(verify=True):
 if not verify:
  actual={}
  for name in sorted(RECOVERY_HELPERS):
   path=TOOLS/name
   try:actual[name]=file_sha(path) if path.is_file() and not path.is_symlink() else None
   except OSError:actual[name]=None
  return actual
 hashes=recovery_json(ROOT/'host-tools.sha256.json')
 if set(hashes)!=RECOVERY_HELPERS:raise ValueError('Current helper inventory mismatch')
 if any((TOOLS/name).is_symlink() or file_sha(TOOLS/name)!=digest for name,digest in hashes.items()):raise ValueError('Current host helper checksum mismatch')
 return hashes

def copy_host_bundle(folder,verify_current=True):
 if verify_current:hashes=current_host_inventory()
 else:
  hashes={name:file_sha(TOOLS/name) for name in RECOVERY_HELPERS if (TOOLS/name).is_file() and not (TOOLS/name).is_symlink()}
 (folder/'host-tools').mkdir(mode=0o700)
 (folder/'launch-agents').mkdir(mode=0o700)
 for name in hashes:shutil.copy2(TOOLS/name,folder/'host-tools'/name)
 jobs={};missing_jobs=[]
 for label in [LABEL,WEB_LABEL]:
  name=f'{label}.plist';source=Path.home()/'Library/LaunchAgents'/name
  if source.is_symlink():raise ValueError('Launch definition cannot be a symlink')
  if not source.is_file():
   if verify_current:raise ValueError('Current launch definition is missing')
   missing_jobs.append(name);continue
  shutil.copy2(source,folder/'launch-agents'/name);jobs[name]=file_sha(source)
 return {'vmUUID':UUID,'helpers':hashes,'launchAgents':jobs,'missingHelpers':sorted(RECOVERY_HELPERS-set(hashes)),'missingLaunchAgents':missing_jobs}

def atomic_recovery_write(path,data,mode=0o600):
 if path.is_symlink():raise ValueError('Recovery target cannot be a symlink')
 fd,name=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'.recovery-')
 temporary=Path(name)
 try:
  with os.fdopen(fd,'wb') as output:
   os.fchmod(output.fileno(),mode);output.write(data);output.flush();os.fsync(output.fileno())
  os.replace(temporary,path)
 finally:temporary.unlink(missing_ok=True)

def apply_host_bundle(folder,data,prepared=None):
 prepared=prepare_host_bundle(folder,data) if prepared is None else prepared
 for name,(raw,mode) in prepared['helpers'].items():
  atomic_recovery_write(TOOLS/name,raw,mode)
 for name,(raw,_mode) in prepared['launchAgents'].items():
  atomic_recovery_write(Path.home()/'Library/LaunchAgents'/name,raw)
 for name in data.get('missingHelpers',[]):
  if name not in RECOVERY_HELPERS:raise ValueError('Unexpected missing helper')
  (TOOLS/name).unlink(missing_ok=True)
 for name in data.get('missingLaunchAgents',[]):
  if name not in {f'{LABEL}.plist',f'{WEB_LABEL}.plist'}:raise ValueError('Unexpected missing launch agent')
  (Path.home()/'Library/LaunchAgents'/name).unlink(missing_ok=True)
 atomic_recovery_write(ROOT/'host-tools.sha256.json',(json.dumps(data['helpers'],indent=2)+'\n').encode())
 helpers=current_host_inventory(verify=False)
 if any(helpers.get(name)!=data['helpers'].get(name) for name in RECOVERY_HELPERS):raise RuntimeError('Applied recovery helper verification failed')
 launches=current_launch_inventory()
 if any(launches.get(name)!=data['launchAgents'].get(name) for name in launches):raise RuntimeError('Applied recovery launch verification failed')

@vm_mutation('snapshot')
def create_current_recovery():
 validate()
 if vm_status()!='stopped':raise RuntimeError('Current recovery requires normal offline shutdown')
 folder=recovery_path(CURRENT_RECOVERY)
 if folder.exists():raise ValueError('Current recovery exists; refusing overwrite')
 image=str(VM/'Data/ubuntu.qcow2')
 info=json.loads(image_command(['info','--output=json',image]).stdout)
 if any(row.get('name')==CURRENT_RECOVERY for row in info.get('snapshots',[])):raise ValueError('Snapshot already exists; reconcile before retrying')
 proof=ROOT/('recovery-input-'+CURRENT_RECOVERY+'.json')
 if proof.is_symlink() or not proof.is_file():raise ValueError('Prepared guest recovery proof is required')
 with recovery_source(proof,RECOVERY_JSON_LIMIT) as source:proof_bytes=source.read(RECOVERY_JSON_LIMIT+1)
 if len(proof_bytes)>RECOVERY_JSON_LIMIT:raise ValueError('Recovery metadata exceeds the size limit')
 validated_recovery_proof(proof_bytes,CURRENT_RECOVERY)
 folder.parent.mkdir(mode=0o700,exist_ok=True)
 staging=Path(tempfile.mkdtemp(prefix='.creating-',dir=folder.parent))
 data=copy_host_bundle(staging)
 atomic_recovery_write(staging/'guest-proof.json',proof_bytes)
 data.update({'snapshot':CURRENT_RECOVERY,'guestProofSha256':hashlib.sha256(proof_bytes).hexdigest(),'createdAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
 image_command(['check',image],timeout=90)
 image_command(['snapshot','-c',CURRENT_RECOVERY,image],timeout=90)
 image_command(['check',image],timeout=90)
 atomic_recovery_write(staging/'manifest.json',(json.dumps(data,indent=2)+'\n').encode())
 os.rename(staging,folder)
 verify_recovery_bundle(CURRENT_RECOVERY)
 print(json.dumps({'createdRecovery':CURRENT_RECOVERY,'hostHelpers':len(data['helpers']),'guestProofRecorded':True,'offline':True,'folder':str(folder)},indent=2))

@vm_mutation('restore')
def restore_current_recovery(snapshot):
 folder,data=verify_recovery_bundle(snapshot)
 prepared=prepare_host_bundle(folder,data)
 helper=prepared['helpers']['qemu-image.py'][0]
 image=str(VM/'Data/ubuntu.qcow2')
 info=json.loads(image_command(['info','--output=json',image],helper=helper).stdout)
 if not any(row.get('name')==snapshot for row in info.get('snapshots',[])):raise ValueError('Current recovery disk snapshot is missing')
 safety='pre-restore-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+str(os.getpid())
 backup=ROOT/'recoveries'/safety;backup.mkdir(mode=0o700)
 previous=copy_host_bundle(backup,verify_current=False)
 previous_sources=prepare_host_bundle(backup,previous)
 atomic_recovery_write(backup/'host-manifest.json',(json.dumps(previous,indent=2)+'\n').encode())
 image_command(['snapshot','-c',safety,image],timeout=90,helper=helper)
 try:
  image_command(['snapshot','-a',snapshot,image],timeout=90,helper=helper)
  apply_host_bundle(folder,data,prepared)
  image_command(['check',image],timeout=90,helper=helper)
 except BaseException as original:
  errors=[]
  try:
   image_command(['snapshot','-a',safety,image],timeout=90,helper=helper)
   image_command(['check',image],timeout=90,helper=helper)
  except BaseException as error:errors.append('disk: '+type(error).__name__)
  try:apply_host_bundle(backup,previous,previous_sources)
  except BaseException as error:errors.append('host helpers: '+type(error).__name__)
  if errors:raise RuntimeError('Rollback needs attention ('+', '.join(errors)+'); safety snapshot: '+safety) from original
  raise
 (ROOT/'access-url.txt').unlink(missing_ok=True)
 print('已恢复当前改进版磁盘及对应宿主入口；恢复前内容保存在 '+safety+'。请重新运行启动入口。')

@vm_mutation('restore')
def restore(confirmed=False,snapshot='ready-original'):
 if not confirmed:raise ValueError('Restore requires --confirm-restore; it reverts guest files and sessions')
 if snapshot not in ('ready-original','ready-toolchain-20261025',*REVIEWED_RECOVERIES):raise ValueError('Only a reviewed dedicated VM recovery point is permitted')
 validate()
 if vm_status()!='stopped':raise RuntimeError('Close the dedicated VM normally before restoring; no forced stop attempted')
 if snapshot in REVIEWED_RECOVERIES:return restore_current_recovery(snapshot)
 image=str(VM/'Data/ubuntu.qcow2')
 info=json.loads(image_command(['info','--output=json',image]).stdout)
 if not any(s.get('name')==snapshot for s in info.get('snapshots',[])):raise ValueError('Selected verified snapshot is missing')
 backup='pre-restore-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+str(os.getpid())
 image_command(['snapshot','-c',backup,image],timeout=90)
 image_command(['snapshot','-a',snapshot,image],timeout=90)
 (ROOT/'access-url.txt').unlink(missing_ok=True)
 print('已恢复 '+snapshot+'；恢复前的数据保存在快照 '+backup+'。请重新运行启动入口。')

CAPABILITIES_GUEST_SCRIPT = '"""Fixed, guest-side original-capability transition, streamed over managed SSH."""\nimport hashlib\nimport json\nimport http.client\nfrom http.cookies import SimpleCookie\nimport os\nimport re\nfrom pathlib import Path\nimport stat\nimport subprocess\nimport sys\nimport tempfile\nimport time\n\nHOME = Path(\'/home/purge\')\nSTATE = HOME / \'.config/harness-original-capabilities\'\nRUNTIME = HOME / \'tools/harness-original-capabilities\'\n\ndef read_mode(path):\n if path.is_symlink():raise ValueError(\'Mode cannot be a symbolic link\')\n if not path.exists():return False\n if not path.is_file() or path.stat().st_size>8:raise ValueError(\'Invalid mode file\')\n value=path.read_bytes()\n if value not in (b\'on\\n\',b\'off\\n\'):raise ValueError(\'Invalid mode contents\')\n return value==b\'on\\n\'\n\ndef write_mode(path, enabled):\n if path.is_symlink():raise ValueError(\'Mode cannot be a symbolic link\')\n descriptor, name=tempfile.mkstemp(dir=path.parent,prefix=\'.original-mode-\')\n try:\n  with os.fdopen(descriptor,\'wb\') as output:\n   os.fchmod(output.fileno(),0o600);output.write(b\'on\\n\' if enabled else b\'off\\n\');output.flush();os.fsync(output.fileno())\n  os.replace(name,path)\n finally:Path(name).unlink(missing_ok=True)\n\ndef transition(path, enabled, restart, observe):\n before=read_mode(path);existed=path.exists()\n if before==enabled and observe(enabled):return False\n write_mode(path,enabled)\n try:\n  restart()\n  if not observe(enabled):raise RuntimeError(\'Requested runtime not confirmed\')\n except BaseException as original:\n  try:\n   if existed:write_mode(path,before)\n   else:path.unlink(missing_ok=True)\n   restart()\n   if not observe(before):raise RuntimeError(\'Rollback runtime not confirmed\')\n  except BaseException as rollback:\n   raise RuntimeError(\'Switch failed; rollback needs attention: \'+type(rollback).__name__) from original\n  raise\n return True\n\ndef service_environment():\n return {**os.environ,\'XDG_RUNTIME_DIR\':\'/run/user/\'+str(os.getuid())}\n\ndef actual_mode():\n result=subprocess.run([\'systemctl\',\'--user\',\'show\',\'dsh-original\',\'-p\',\'MainPID\',\'--value\'],env=service_environment(),capture_output=True,text=True,timeout=5,check=True)\n pid=int(result.stdout.strip())\n if pid<=0:return None\n try:\n  args=(Path(\'/proc\')/str(pid)/\'cmdline\').read_bytes().split(b\'\\0\')\n  variables=dict(part.split(b\'=\',1) for part in (Path(\'/proc\')/str(pid)/\'environ\').read_bytes().split(b\'\\0\') if b\'=\' in part)\n except (FileNotFoundError,ProcessLookupError):return None\n if variables.get(b\'DSH_HOME\')!=b\'/home/purge/.dsh-improved\':return None\n expected=RUNTIME/\'lib/bin.js\'\n if str(expected).encode() in args and variables.get(b\'DSH_PERSONAL_ORIGINAL\')==b\'enabled\':return True\n daily=HOME/\'tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js\'\n if str(daily).encode() in args and variables.get(b\'DSH_PERSONAL_ORIGINAL\',b\'\')!=b\'enabled\':return False\n return None\n\ndef observe(enabled):\n deadline=time.monotonic()+20\n while time.monotonic()<deadline:\n  try:\n   if actual_mode() is enabled and authenticated_plugin_ready(enabled):return True\n  except (OSError,ValueError,subprocess.SubprocessError):pass\n  time.sleep(.2)\n return False\n\ndef confirmed_plugin_mode(status, data, enabled):\n return status==200 and isinstance(data,dict) and data.get(\'ok\') is True and data.get(\'ready\') is True and data.get(\'originalCapabilities\',{}).get(\'enabled\') is enabled\n\ndef authenticated_plugin_ready(enabled):\n # A 401 at the anonymous root is normal for this private Harness. Validate\n # its current owner login and the merged plugin acknowledgement instead.\n result=subprocess.run([\'systemctl\',\'--user\',\'show\',\'dsh-original\',\'-p\',\'MainPID\',\'--value\'],env=service_environment(),capture_output=True,text=True,timeout=3,check=True)\n pid=int(result.stdout.strip())\n journal=subprocess.run([\'journalctl\',\'--user\',\'-u\',\'dsh-original\',\'_PID=\'+str(pid),\'-n\',\'40\',\'--no-pager\',\'-o\',\'cat\'],env=service_environment(),capture_output=True,text=True,timeout=3,check=True).stdout\n tokens=re.findall(r\'http://127\\.0\\.0\\.1:49224/\\?token=([A-Za-z0-9_-]+)\',journal)\n if not tokens:return False\n connection=http.client.HTTPConnection(\'10.0.2.15\',3080,timeout=3)\n try:\n  connection.request(\'GET\',\'/?token=\'+tokens[-1],headers={\'Host\':\'127.0.0.1:49224\'})\n  login=connection.getresponse();cookies=SimpleCookie()\n  for name,value in login.getheaders():\n   if name.lower()==\'set-cookie\':cookies.load(value)\n  login.read(2*1024*1024)\n  if not cookies:return False\n  connection.request(\'GET\',\'/dsh-purge/status\',headers={\'Host\':\'127.0.0.1:49224\',\'Cookie\':\'; \'.join(key+\'=\'+value.value for key,value in cookies.items())})\n  response=connection.getresponse();body=response.read(2*1024*1024+1)\n  if len(body)>2*1024*1024:return False\n  return confirmed_plugin_mode(response.status,json.loads(body),enabled)\n finally:connection.close()\n\ndef verify_runtime():\n if RUNTIME.is_symlink() or not RUNTIME.is_dir():raise ValueError(\'Isolated original runtime is missing\')\n manifest=RUNTIME/\'.personal-runtime-manifest.json\'\n if manifest.is_symlink() or not manifest.is_file():raise ValueError(\'Runtime inventory is missing\')\n data=json.loads(manifest.read_text())\n if data.get(\'source\')!=\'/home/purge/.local/lib/node_modules/@deepseek-ai/dsh\':raise ValueError(\'Unexpected original source\')\n entries=data.get(\'files\')\n if not isinstance(entries,dict) or not entries:raise ValueError(\'Empty runtime inventory\')\n for relative,record in entries.items():\n  item=Path(relative)\n  if item.is_absolute() or any(part in (\'.\',\'..\') for part in item.parts):raise ValueError(\'Invalid runtime path\')\n  path=RUNTIME/item\n  if not path.resolve().is_relative_to(RUNTIME):raise ValueError(\'Runtime link escapes its copy\')\n  if \'link\' in record:\n   if not path.is_symlink() or os.readlink(path)!=record[\'link\']:raise ValueError(\'Runtime link changed\')\n  elif path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=record[\'sha256\']:\n   raise ValueError(\'Original runtime inventory differs\')\n return len(entries)\n\ndef main():\n if sys.platform!=\'linux\' or Path.home()!=HOME or os.getuid()!=1000:raise ValueError(\'Dedicated VM required\')\n if (HOME/\'.config/harness-vm-mode\').read_text().strip()!=\'improved\':raise ValueError(\'Select the improved workbench before changing original capabilities\')\n action=sys.argv[1]\n if action==\'status\':\n  print(json.dumps({\'enabled\':actual_mode(),\'configured\':read_mode(STATE),\'sharedHome\':\'/home/purge/.dsh-improved\'}));return\n if action not in (\'enable\',\'disable\'):raise ValueError(\'Unknown mode action\')\n if action==\'enable\':verify_runtime()\n def restart():subprocess.run([\'systemctl\',\'--user\',\'restart\',\'dsh-original\'],env=service_environment(),check=True,timeout=30,capture_output=True)\n changed=transition(STATE,action==\'enable\',restart,observe)\n print(json.dumps({\'enabled\':actual_mode(),\'configured\':read_mode(STATE),\'changed\':changed,\'sharedHome\':\'/home/purge/.dsh-improved\'}))\n\nif __name__==\'__main__\':main()\n'

def refresh_capability_access():
 # This changes an already-running guest service, so it needs trusted SSH and
 # owner readiness, not a UTM app lifecycle request.
 if not web_entry_listener_owned():raise RuntimeError('Managed local entry ownership not confirmed')
 url=ssh(URL_SCRIPT,timeout=10).stdout.strip()
 if not re.fullmatch(r'http://127\.0\.0\.1:49224/\?token=[A-Za-z0-9_-]+',url):raise ValueError('Invalid guest access URL')
 url=url.replace(':49224/',':49226/',1)
 if not authenticated_ready(url):raise RuntimeError('Authenticated local entry not ready')
 atomic_recovery_write(ROOT/'access-url.txt',(url+'\n').encode(),0o600)
 atomic_recovery_write(ROOT/'打开虚拟机Harness.webloc',plistlib.dumps({'URL':url}),0o600)

def original_capabilities(action):
 if action not in ('enable','disable','status'):raise ValueError('Invalid original capability action')
 def run():
  validate()
  result=json.loads(ssh('python3 - '+action,input=CAPABILITIES_GUEST_SCRIPT,timeout=120).stdout)
  enabled=result.get('enabled');configured=result.get('configured')
  if type(enabled) is not bool or type(configured) is not bool:raise RuntimeError('Capability state not confirmed')
  if action!='status':
   expected=action=='enable'
   if enabled is not expected or configured is not expected:raise RuntimeError('Capability receipt mismatch')
   refresh_capability_access()
  return result
 if action=='status':return run()
 with vm_operation('switch'):return run()

def repair_profile(*,apply=False):
 if type(apply) is not bool:raise ValueError('Explicit boolean apply required')
 script="""import {homedir} from 'node:os';
import path from 'node:path';
import {repairProfilePnpm} from 'file:///home/purge/tools/dsh-purge-personal-1.1.77-personal.1/lib/personal-pnpm-repair.mjs';
if(process.platform!=='linux'||homedir()!=='/home/purge'||process.getuid()!==1000)throw Error('Dedicated VM required');
const result=repairProfilePnpm('/home/purge/.dsh-improved/profiles/web',OPTIONS);
if(result.backup)result.backup=path.basename(result.backup);
console.log(JSON.stringify(result));
""".replace('OPTIONS',json.dumps({'apply':apply},separators=(',',':')))
 with vm_operation('switch'):
  validate()
  result=json.loads(ssh('/home/purge/.local/node/bin/node --input-type=module',input=script,timeout=30).stdout)
  if not isinstance(result,dict) or result.get('ok') is not True or result.get('profile')!='web' or result.get('dryRun') is not (not apply):raise RuntimeError('Profile repair receipt unconfirmed')
  if type(result.get('changed')) is not bool or type(result.get('wrote')) is not bool:raise RuntimeError('Profile repair result unconfirmed')
  if result['wrote'] and (not apply or not result['changed']):raise RuntimeError('Profile repair write unconfirmed')
  for key in ['beforeSha256','afterSha256']:
   value=result.get(key)
   if value is not None and (not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value)):raise RuntimeError('Profile repair digest unconfirmed')
  if result['changed'] and any(result.get(key) is None for key in ['beforeSha256','afterSha256']):raise RuntimeError('Profile repair digest missing')
  return result

def storage_capacity():
 # Only counters, never a recursive inventory, Docker query or VM lifecycle action.
 validate();host=None;guest={'state':'unavailable'}
 try:
  space=shutil.disk_usage(ROOT);host={'totalBytes':space.total,'availableBytes':space.free}
 except OSError:pass
 if vm_status()=='stopped':guest={'state':'not-running'}
 else:
  try:
   result=ssh('python3 -B /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-storage-preview.py --capacity-only',timeout=8,phase='native-check')
   if len(result.stdout.encode())>8192:raise ValueError('Capacity response too large')
   value=json.loads(result.stdout);space=value.get('filesystem',{})
   keys=['totalBytes','availableBytes','inodeTotal','inodeAvailable']
   if value.get('version')!=1 or value.get('readOnly') is not True or value.get('automaticChanges') is not False or value.get('deletionAvailable') is not False or any(type(space.get(key)) is not int or not 0<=space[key]<=9007199254740991 for key in keys) or space['totalBytes']==0 or space['availableBytes']>space['totalBytes'] or space['inodeAvailable']>space['inodeTotal']:raise ValueError('Invalid capacity counters')
   guest={'state':'observed','filesystem':{key:space[key] for key in keys}}
  except (OSError,ValueError,AttributeError,TypeError,subprocess.SubprocessError):pass
 return {'version':1,'readOnly':True,'automaticChanges':False,'deletionAvailable':False,'checkedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'hostFilesystem':host,'guest':guest}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['start','stop','status','restore','switch','snapshot-current','environment','recoveries','capabilities','repair-profile','clock-sync','ssh-diagnostics','ssh-correlate','clock-maintain','storage-capacity']);parser.add_argument('--mode',choices=['original','improved']);parser.add_argument('--quiet',action='store_true');parser.add_argument('--confirm-restore',action='store_true');parser.add_argument('--snapshot',choices=['ready-original','ready-toolchain-20261025',*REVIEWED_RECOVERIES],default='ready-original');parser.add_argument('--catalog-part',choices=['all','snapshots','images'],default='all');parser.add_argument('--archive-after');parser.add_argument('--snapshot-after');parser.add_argument('--capability-mode',choices=['enable','disable','status'],default='status');parser.add_argument('--apply-profile-repair',action='store_true');parser.add_argument('--reference');args=parser.parse_args()
 if args.action=='start':start(args.quiet)
 elif args.action=='clock-sync':validate();print(json.dumps(synchronize_clock()))
 elif args.action=='clock-maintain':print(json.dumps(maintain_clock()))
 elif args.action=='storage-capacity':print(json.dumps(storage_capacity()))
 elif args.action=='ssh-diagnostics':validate();print(json.dumps(ssh_diagnostics()))
 elif args.action=='ssh-correlate':print(json.dumps(correlate_ssh_failure(args.reference)))
 elif args.action=='repair-profile':print(json.dumps(repair_profile(apply=args.apply_profile_repair)))
 elif args.action=='switch':switch(args.mode,args.quiet)
 elif args.action=='stop':stop()
 elif args.action=='restore':restore(args.confirm_restore,args.snapshot)
 elif args.action=='snapshot-current':create_current_recovery()
 elif args.action=='capabilities':print(json.dumps(original_capabilities(args.capability_mode)))
 elif args.action=='environment':print(json.dumps(deployment_status()))
 elif args.action=='recoveries':print(json.dumps(recovery_catalog(after=args.archive_after,snapshot_after=args.snapshot_after,part=args.catalog_part)))
 else:validate();print(json.dumps({'vm':UUID,'status':vm_status(),'hostShares':False,'clipboard':False,'usb':False,'network':'Restricted IPv4; only allowlisted public origins through external proxy','originalGuestFullAccessAvailable':True,'hostFullAccess':False},indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:print('操作停止：'+str(e),file=sys.stderr);raise SystemExit(1)
