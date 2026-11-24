#!/usr/bin/env python3
"""Fixed unprivileged loopback rehearsal over the existing pinned Kali connection."""
import argparse,json,re,subprocess,sys
REMOTE_SOURCE=r'''
from pathlib import Path
import http.server,json,os,signal,socket,stat,subprocess,sys,threading,time,uuid,xml.etree.ElementTree as ET
mode,identity,scenario=sys.argv[1:4]
assert os.getuid()==1000 and Path('/etc/os-release').read_text().find('ID=kali')>=0
assert __import__('re').fullmatch(r'[A-Za-z0-9_-]{8,100}',identity)
assert mode in ['run','status'] and scenario in ['normal','timeout-control','cancel-control','disconnect-control']
base=Path.home()/'.cache/harness-security-rehearsal';base.mkdir(mode=0o700,parents=True,exist_ok=True)
assert base.resolve()==base and base.stat().st_uid==1000 and base.stat().st_mode&0o077==0
receipt=base/(identity+'.json')
def load():
 st=receipt.lstat();assert stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==1000 and st.st_mode&0o077==0 and st.st_size<16384
 return json.loads(receipt.read_text())
def save(value):
 temp=base/(identity+'-'+uuid.uuid4().hex+'.tmp');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
  os.replace(temp,receipt)
 finally:
  if temp.exists():temp.unlink()
if mode=='status':
 value=load() if receipt.exists() else {'ok':False,'state':'not-found','id':identity}
 if value.get('state')=='running':
  try:alive=Path('/proc/sys/kernel/random/boot_id').read_text().strip()==value.get('bootId') and Path('/proc/'+str(value['pid'])+'/stat').read_text().split()[21]==value.get('startTicks')
  except (OSError,KeyError):alive=False
  if not alive or time.time()>value.get('deadline',0):
   cleanup=False
   if isinstance(value.get('port'),int):
    with socket.socket() as probe:probe.settimeout(.3);cleanup=probe.connect_ex(('127.0.0.1',value['port']))!=0
   value={'ok':False,'state':'interrupted' if not alive else 'unconfirmed','id':identity,'cleanupVerified':cleanup}
 print(json.dumps(value));sys.exit(0)
if receipt.exists():
 print(json.dumps(load()));sys.exit(0)
fd=os.open(receipt,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as f:json.dump({'ok':False,'state':'running','id':identity,'pid':os.getpid(),'startTicks':Path('/proc/self/stat').read_text().split()[21],'bootId':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'deadline':time.time()+25},f);f.flush();os.fsync(f.fileno())
server=None;worker=None;port=None;requests=[];checks=[];state='failed';problem=None;cleanup=False
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  requests.append(self.path)
  payload=b'{"synthetic":true,"marker":"harness-kali-loopback"}'
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
def interrupted(signum,frame):raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
try:
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);port=server.server_port
 worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);worker.start()
 running=load();running['port']=port;save(running)
 if scenario=='timeout-control':subprocess.run(['/usr/bin/python3','-c','import time;time.sleep(2)'],timeout=.1,check=True)
 if scenario=='cancel-control':os.kill(os.getpid(),signal.SIGTERM)
 if scenario=='disconnect-control':time.sleep(3)
 result=subprocess.run(['/usr/bin/nmap','-n','-Pn','-sT','--max-retries','0','--host-timeout','5s','-p',str(port),'-oX','-','127.0.0.1'],capture_output=True,timeout=8,check=True)
 assert len(result.stdout)<65536
 tree=ET.fromstring(result.stdout);ports=tree.findall('./host/ports/port');assert len(ports)==1 and ports[0].get('portid')==str(port) and ports[0].find('state').get('state')=='open'
 checks.append({'name':'nmap-loopback-tcp','passed':True})
 result=subprocess.run(['/usr/bin/curl','--noproxy','*','--fail','--silent','--show-error','--max-time','4','http://127.0.0.1:'+str(port)+'/fixture'],capture_output=True,timeout=6,check=True)
 assert len(result.stdout)<4096 and json.loads(result.stdout)=={'synthetic':True,'marker':'harness-kali-loopback'} and requests==['/fixture']
 checks.append({'name':'curl-loopback-http','passed':True});state='completed'
except KeyboardInterrupt:state='cancelled';problem='signal-cancelled'
except subprocess.TimeoutExpired:state='timed-out';problem='command-deadline'
except Exception:problem='fixture-or-tool-check-failed'
finally:
 if server:
  server.shutdown();server.server_close()
  if worker:worker.join(1)
 if port:
  with socket.socket() as probe:
   probe.settimeout(.3);cleanup=probe.connect_ex(('127.0.0.1',port))!=0
 value={'ok':state=='completed' and cleanup,'state':state,'id':identity,'uid':os.getuid(),'target':'127.0.0.1 synthetic fixture only','checks':checks,'cleanupVerified':cleanup,'problem':problem,'scenario':scenario}
 save(value)
print(json.dumps(value))
'''
def remote_argv(mode,identity,scenario='normal'):
 if mode not in ['run','status'] or not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',identity) or scenario not in ['normal','timeout-control','cancel-control','disconnect-control']:raise ValueError('Invalid fixed rehearsal request')
 return ['/home/purge/.local/bin/kali-vm','exec','--','python3','-c',REMOTE_SOURCE,mode,identity,scenario]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['run','status'],default='run');p.add_argument('--request-id',required=True);p.add_argument('--control',choices=['normal','timeout-control','cancel-control','disconnect-control'],default='normal');a=p.parse_args()
 try:
  r=subprocess.run(remote_argv(a.mode,a.request_id,a.control),capture_output=True,timeout=35)
  if r.returncode or len(r.stdout)>16384:raise ValueError('Remote result unavailable')
  value=json.loads(r.stdout);assert value.get('id')==a.request_id
  print(json.dumps(value));return 0
 except (ValueError,AssertionError,subprocess.SubprocessError,OSError):
  print(json.dumps({'ok':False,'id':a.request_id,'state':'unconfirmed','error':'Read status using the same request ID before any new run'}));return 1
if __name__=='__main__':sys.exit(main())
