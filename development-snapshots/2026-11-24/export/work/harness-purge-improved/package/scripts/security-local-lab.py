#!/usr/bin/env python3
"""VM-local synthetic login lab and private Cookie/Bearer session importer."""
import argparse,datetime,http.client,http.server,json,os,re,secrets,signal,subprocess,sys,threading,time,urllib.parse,uuid
from pathlib import Path
HOME=Path('/home/purge')
AUTH=HOME/'.dsh-improved/security-auth'
NODE=HOME/'.local/node/bin/node'
MANAGEMENT={3080,18443,49222,49223,49224,49226,49090}
class SafeError(Exception):pass

class LocalLab:
 def __init__(self,ledger=None,ttl_seconds=900):
  self.username='lab-user';self.password=secrets.token_urlsafe(24);self.token=None;self.invalidated=False;self.expires=time.monotonic()+ttl_seconds;self.lock=threading.RLock();self.events=[];self.ledger=ledger
 def authenticated(self,headers):
  with self.lock:return bool(self.token and not self.invalidated and time.monotonic()<self.expires and (headers.get('Cookie')=='lab_session='+self.token or headers.get('Authorization')=='Bearer '+self.token))
 def record(self,method,route,headers,authenticated):
  known={'/','/login','/account','/account/report','/logout','/test/invalidate','/leave-scope','/robots.txt','/sitemap.xml','/sink'}
  with self.lock:
   row={'sequence':len(self.events)+1,'method':method,'route':route if route in known else 'other','authenticated':authenticated,'cookiePresent':bool(headers.get('Cookie')),'authorizationPresent':bool(headers.get('Authorization'))}
   if len(self.events)>=10000:return
   self.events.append(row)
   if self.ledger:
    descriptor=os.open(self.ledger,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as out:out.write(json.dumps(row)+'\n')

def build_lab_server(port,state,sink_origin,*,sink=False):
 class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self,*_):pass
  def setup(self):super().setup();self.connection.settimeout(3)
  def respond(self,status,body,headers=None):
   raw=body.encode();self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Connection','close')
   for key,value in (headers or {}).items():self.send_header(key,value)
   self.end_headers();self.wfile.write(raw)
  def do_GET(self):
   route=urllib.parse.urlsplit(self.path).path;authenticated=state.authenticated(self.headers);state.record('GET',route,self.headers,authenticated)
   if sink:self.respond(200,'LOCAL_SCOPE_SINK');return
   if route=='/':
    self.respond(200,"<html><title>Harness local login lab</title><a href='/account'>Account</a><a href='/account/report'>Report</a><a href='/logout'>Logout</a><a href='"+sink_origin+"/sink'>Out of scope link</a><a href='/leave-scope'>Out of scope redirect</a><form method='post' action='/login'><input name='username'><input name='password' type='password'><button>Login</button></form></html>")
   elif route in ['/account','/account/report']:
    self.respond(200,"<html>HARNESS_AUTHENTICATED<a href='/account/report'>Local private report</a></html>") if authenticated else self.respond(401,'LOGIN_REQUIRED')
   elif route=='/logout':
    if authenticated:
     with state.lock:state.invalidated=True
    self.respond(200,'LOGGED_OUT')
   elif route=='/leave-scope':self.respond(302,'LOCAL_REDIRECT',{'Location':sink_origin+'/sink'})
   elif route=='/robots.txt':self.respond(200,'User-agent: *\nAllow: /\n')
   else:self.respond(404,'LOCAL_NOT_FOUND')
  def do_POST(self):
   route=urllib.parse.urlsplit(self.path).path;authenticated=state.authenticated(self.headers);state.record('POST',route,self.headers,authenticated)
   try:length=int(self.headers.get('Content-Length','0'))
   except ValueError:self.respond(400,'INVALID_REQUEST');return
   if length<0 or length>4096:self.respond(413,'REQUEST_TOO_LARGE');return
   body=self.rfile.read(length)
   if route=='/login':
    fields=urllib.parse.parse_qs(body.decode('utf-8','replace'))
    if fields.get('username')==[state.username] and fields.get('password')==[state.password]:
     with state.lock:state.token=secrets.token_urlsafe(32);state.invalidated=False;cookie='lab_session='+state.token
     self.respond(303,'LOCAL_LOGIN_ACCEPTED',{'Location':'/account','Set-Cookie':cookie+'; HttpOnly; SameSite=Lax; Path=/'})
    else:self.respond(401,'LOGIN_REQUIRED')
   elif route=='/test/invalidate' and authenticated:
    with state.lock:state.invalidated=True
    self.respond(200,'LOCAL_SESSION_INVALIDATED')
   else:self.respond(401,'LOGIN_REQUIRED')
 server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;return server

def slug(value):return isinstance(value,str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,47}',value)
def write_private(path,value):
 descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(descriptor,'w') as out:json.dump(value,out);out.write('\n');out.flush();os.fsync(out.fileno())
def import_session(name,value):
 if not slug(name) or not isinstance(value,dict):raise SafeError('配置名或JSON结构无效')
 if not AUTH.exists():AUTH.mkdir(mode=0o700)
 info=AUTH.lstat()
 if AUTH.is_symlink() or not AUTH.is_dir() or AUTH.resolve()!=AUTH or info.st_uid!=os.getuid() or info.st_mode&0o077:raise SafeError('认证目录须为当前VM用户的私有普通目录')
 path=AUTH/(name+'.json');value={**value,'version':1,'revision':str(uuid.uuid4())};raw=json.dumps(value)
 if len(raw.encode())>8192:raise SafeError('配置超过8192字节上限')
 try:write_private(path,value)
 except FileExistsError:raise SafeError('配置名已存在；请导入新名称，不会覆盖原凭据') from None
 try:
  module=(Path(__file__).resolve().parent.parent/'lib/redteam/personal-security-auth.mjs').as_uri()
  code="import {readFileSync} from 'node:fs';import {homedir} from 'node:os';import {join} from 'node:path';import {readZapAuthProfile} from "+json.dumps(module)+";const name=process.argv[1],raw=JSON.parse(readFileSync(join(homedir(),'.dsh-improved/security-auth',name+'.json'),'utf8'));const a=readZapAuthProfile(name,raw.origin);console.log(JSON.stringify({profile:name,revision:a.revision,origin:a.origin,header:a.header,expiresAt:a.expiresAt}));"
  result=subprocess.run([str(NODE),'--input-type=module','-e',code,name],capture_output=True,text=True,timeout=8)
  if result.returncode:raise SafeError('认证配置无效；仅支持匹配本地范围的Cookie或Bearer私有会话')
  metadata=json.loads(result.stdout);assert metadata['revision']==value['revision'];return metadata
 except BaseException:
  path.unlink(missing_ok=True);raise

def session_operation(operation,request,value=None):
 module=(Path(__file__).resolve().parent.parent/'lib/redteam/personal-security-auth.mjs').as_uri()
 code="import {readFileSync} from 'node:fs';import {readZapAuthStatus,renewZapAuthProfile} from "+json.dumps(module)+";const request=JSON.parse(process.argv[1]),root="+json.dumps(str(AUTH))+";const result="+("readZapAuthStatus(request.profile,request.origin,{root})" if operation=='status' else "renewZapAuthProfile(request,JSON.parse(readFileSync(0,'utf8')),{root})")+";console.log(JSON.stringify(result));"
 payload=json.dumps(value) if value is not None else None
 if payload is not None and len(payload.encode())>8192:raise SafeError('配置超过8192字节上限')
 result=subprocess.run([str(NODE),'--input-type=module','-e',code,json.dumps(request)],input=payload,capture_output=True,text=True,timeout=8)
 if result.returncode:raise SafeError('私有会话操作未完成；请核对原配置版本、确认项和未使用的新名称')
 return json.loads(result.stdout)

def renew_session(args,value):
 return session_operation('renew',{'from':args.from_profile,'to':args.to_profile,'origin':args.origin,'expectedRevision':args.expected_revision,'confirm':args.confirm},value)

def dedicated_vm():
 if sys.platform!='linux' or Path.home()!=HOME or os.getuid()!=1000:raise SafeError('仅在专用Linux VM的purge账号中运行')

def serve(args):
 if args.port in MANAGEMENT or args.sink_port in MANAGEMENT or min(args.port,args.sink_port)<1024 or max(args.port,args.sink_port)>65535 or args.port==args.sink_port:raise SafeError('只能使用两个不同的非管理本地端口')
 if not 60<=args.ttl<=3600:raise SafeError('会话期限须为60–3600秒')
 run=uuid.uuid4().hex[:12];name=args.profile or 'lab-'+run
 if not slug(name):raise SafeError('配置名无效')
 stage=HOME/'downloads'/('harness-auth-lab-'+run);stage.mkdir(mode=0o700)
 repo=HOME/'workspace'/('harness-auth-lab-'+run);repo.mkdir(mode=0o700);(repo/'README.md').write_text('Synthetic VM-local login fixture. No real account or project data.\n')
 account=stage/'lab-account.json';state=LocalLab(stage/'requests.jsonl',args.ttl);sink_state=LocalLab(stage/'sink.jsonl',args.ttl);write_private(account,{'username':state.username,'password':state.password})
 servers=[];threads=[];metadata=None;stop=threading.Event()
 def finish(_signum,_frame):stop.set()
 prior={sig:signal.signal(sig,finish) for sig in [signal.SIGINT,signal.SIGTERM]}
 try:
  for port,current,sink in [(args.sink_port,sink_state,True),(args.port,state,False)]:
   server=build_lab_server(port,current,'http://127.0.0.1:'+str(args.sink_port),sink=sink);servers.append(server);thread=threading.Thread(target=server.serve_forever,daemon=True);threads.append(thread);thread.start()
  connection=http.client.HTTPConnection('127.0.0.1',args.port,timeout=3)
  try:
   connection.request('POST','/login',urllib.parse.urlencode({'username':state.username,'password':state.password}),{'Content-Type':'application/x-www-form-urlencoded'});response=connection.getresponse();cookie=response.getheader('Set-Cookie','').split(';',1)[0];body=response.read(4097)
   if response.status!=303 or len(body)>4096 or not cookie.startswith('lab_session='):raise SafeError('合成登录未确认')
  finally:connection.close()
  expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=args.ttl)).isoformat().replace('+00:00','Z')
  value=cookie if args.header=='Cookie' else 'Bearer '+cookie.split('=',1)[1]
  metadata=import_session(name,{'origin':'http://127.0.0.1:'+str(args.port),'header':args.header,'value':value,'verifyPath':'/account','loggedInMarker':'HARNESS_AUTHENTICATED','excludePaths':['/logout','/test/invalidate'],'expiresAt':expires})
  print(json.dumps({'ready':True,'pid':os.getpid(),'profile':name,'repository':str(repo),'stage':str(stage),'origin':metadata['origin'],'sinkOrigin':'http://127.0.0.1:'+str(args.sink_port),'expiresAt':expires}),flush=True)
  while not stop.wait(.25):pass
 finally:
  for server in servers:server.shutdown();server.server_close()
  for thread in threads:thread.join(timeout=2)
  account.unlink(missing_ok=True)
  if metadata:
   target=AUTH/(name+'.json')
   try:
    if not target.is_symlink() and json.loads(target.read_text()).get('revision')==metadata['revision']:target.unlink()
   except (OSError,ValueError):pass
  write_private(stage/'closed.json',{'serversClosed':True,'ownedAccountFileRemoved':not account.exists(),'profile':name,'fixture':run})
  for sig,handler in prior.items():signal.signal(sig,handler)

def main():
 parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
 imp=commands.add_parser('import-session',help='Read a private session JSON from stdin without overwriting an existing name');imp.add_argument('name')
 status=commands.add_parser('status',help='Read session expiry metadata only; never sends target HTTP requests');status.add_argument('name');status.add_argument('--origin',required=True)
 renew=commands.add_parser('renew-session',help='Read only value/expiresAt from private stdin and create a new name; source is preserved');renew.add_argument('from_profile');renew.add_argument('to_profile');renew.add_argument('--origin',required=True);renew.add_argument('--expected-revision',required=True);renew.add_argument('--confirm',action='store_true',required=True)
 lab=commands.add_parser('serve',help='Run an owned synthetic login lab until Ctrl-C');lab.add_argument('--port',type=int,default=18780);lab.add_argument('--sink-port',type=int,default=18781);lab.add_argument('--profile');lab.add_argument('--header',choices=['Cookie','Authorization'],default='Cookie');lab.add_argument('--ttl',type=int,default=900)
 args=parser.parse_args();dedicated_vm()
 if args.command in ['import-session','renew-session']:
  raw=sys.stdin.buffer.read(8193)
  if len(raw)>8192:raise SafeError('配置超过8192字节上限')
  value=json.loads(raw);result=import_session(args.name,value) if args.command=='import-session' else renew_session(args,value);print(json.dumps(result))
 elif args.command=='status':print(json.dumps(session_operation('status',{'profile':args.name,'origin':args.origin})))
 else:serve(args)

if __name__=='__main__':
 try:main()
 except SafeError as error:print(str(error),file=sys.stderr);raise SystemExit(1)
 except Exception:print('本地认证操作未完成；私有值未输出，请检查VM环境及配置。',file=sys.stderr);raise SystemExit(1)
