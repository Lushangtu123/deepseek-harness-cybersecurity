#!/usr/bin/env python3
"""Fixed guest-local PentAGI client; credentials never appear in model output."""
import argparse,http.cookiejar,json,os,re,secrets,sys,urllib.request,urllib.error,tempfile
from pathlib import Path
BASE='http://127.0.0.1:18443'
ROOT=Path('/home/purge/.dsh/toolchain')
STATE=ROOT/'pentagi-connection.json'
ADMIN=ROOT/'pentagi-admin.json'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):raise urllib.error.HTTPError(BASE,code,'Local API redirect rejected',headers,fp)

def operation(action,flow=None,task=None):
 if action=='status':return 'GET','/api/v1/info',None
 if action=='providers':return 'GET','/api/v1/providers/',None
 if action=='flows':return 'GET','/api/v1/flows/?page=1&size=100&type=init',None
 if action=='run':
  if not isinstance(task,str) or not task.strip() or len(task)>16000:raise ValueError('Task must be 1..16000 characters')
  return 'POST','/api/v1/flows/',{'provider':'deepseek','input':task}
 if not isinstance(flow,str) or not re.fullmatch(r'[1-9][0-9]{0,17}',flow):raise ValueError('Flow ID must be a positive integer')
 path='/api/v1/flows/'+flow
 if action=='flow':return 'GET',path,None
 if action=='logs':return 'GET',path+'/termlogs/?page=1&size=100&type=init',None
 if action=='toolcalls':return 'GET',path+'/toolcalls/?page=1&size=100&type=init',None
 if action=='stop':return 'PUT',path,{'action':'stop'}
 if action=='finish':return 'PUT',path,{'action':'finish'}
 raise ValueError('Unsupported operation')

def redact(value,hidden):
 if isinstance(value,dict):return {k:('[REDACTED]' if re.search(r'(?i)(api.?key|password|secret|credential|access.?token|refresh.?token|^token$)',k) else redact(v,hidden)) for k,v in value.items()}
 if isinstance(value,list):return [redact(v,hidden) for v in value]
 if isinstance(value,str):
  for s in hidden:
   if isinstance(s,str) and s:value=value.replace(s,'[REDACTED]')
 return value

def opener():return urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def validate_token(token):
 if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{16,8192}',token):raise ValueError('Invalid stored local API token; credential value omitted')

def request(client,method,path,body=None,token=None):
 if not path.startswith('/api/v1/') or any(c in path for c in ['#', '\r', '\n']) or '..' in path:raise ValueError('Invalid fixed local API path')
 if '?' in path and not re.fullmatch(r'/api/v1/flows/(?:[1-9][0-9]{0,17}/(?:termlogs|toolcalls)/)?\?page=1&size=100&type=init',path):raise ValueError('Only fixed local pagination query is allowed')
 headers={'Accept':'application/json'}
 if token is not None:validate_token(token);headers['Authorization']='Bearer '+token
 payload=None if body is None else json.dumps(body).encode()
 if payload is not None:headers['Content-Type']='application/json'
 req=urllib.request.Request(BASE+path,data=payload,headers=headers,method=method)
 try:
  with client.open(req,timeout=45) as r:data=r.read(4*1024*1024+1)
 except urllib.error.HTTPError as e:raise RuntimeError('PentAGI local API returned HTTP '+str(e.code)+'; response body omitted') from None
 if len(data)>4*1024*1024:raise RuntimeError('Local API response exceeded 4MiB; use a smaller scoped query')
 return json.loads(data)

def private_json(path,data):
 if path.is_symlink():raise ValueError('Credential target cannot be a symlink')
 fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'-')
 try:
  with os.fdopen(fd,'w') as f:json.dump(data,f);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(temp,path)
  directory=os.open(path.parent,os.O_RDONLY)
  try:os.fsync(directory)
  finally:os.close(directory)
 finally:
  try:os.unlink(temp)
  except FileNotFoundError:pass

def bootstrap():
 if STATE.exists():
  state=json.loads(STATE.read_text());request(opener(),'GET','/api/v1/providers/',token=state['token']);print('Existing guest-local connection verified.');return
 client=opener()
 if ADMIN.exists():admin=json.loads(ADMIN.read_text())
 else:
  admin={'mail':'admin@pentagi.com','password':secrets.token_urlsafe(32),'passwordChanged':False};private_json(ADMIN,admin)
 # The new database uses the upstream initial admin. A saved pending password
 # also permits reconciling a disconnect after a successful password update.
 try:request(client,'POST','/api/v1/auth/login',{'mail':admin['mail'],'password':admin['password']})
 except RuntimeError:
  if admin['passwordChanged']:raise
  request(client,'POST','/api/v1/auth/login',{'mail':admin['mail'],'password':'admin'})
  request(client,'PUT','/api/v1/user/password',{'current_password':'admin','password':admin['password'],'confirm_password':admin['password']})
 admin['passwordChanged']=True;private_json(ADMIN,admin)
 existing=request(client,'GET','/api/v1/tokens/')
 # A lost token-creation response cannot safely be retried as another token.
 if 'harness-local' in json.dumps(existing):raise RuntimeError('Existing harness-local token found without saved plaintext; reconcile it before creating another')
 result=request(client,'POST','/api/v1/tokens/',{'name':'harness-local','ttl':2592000})
 token=result['data']['token'];assert isinstance(token,str) and len(token)>16
 private_json(STATE,{'base':BASE,'token':token,'ttlSeconds':2592000})
 print('Guest-local API credential initialized; initial administrator password rotated. Secret values omitted.')

def renew():
 # Explicit maintenance only. Never retry a running task POST on a 401.
 if ADMIN.is_symlink() or ADMIN.stat().st_mode&0o077:raise ValueError('Administrator file must be owner-only and not a symlink')
 admin=json.loads(ADMIN.read_text());client=opener()
 request(client,'POST','/api/v1/auth/login',{'mail':admin['mail'],'password':admin['password']})
 items=request(client,'GET','/api/v1/tokens/')['data']['tokens']
 if not isinstance(items,list):raise ValueError('Unexpected managed-token inventory')
 old=[x for x in items if x.get('name')=='harness-local']
 if len(old)>1:raise ValueError('Multiple managed tokens; inspect inventory before renewing')
 for token in old:
  token_id=token['token_id']
  if not isinstance(token_id,str) or not re.fullmatch(r'[A-Za-z0-9]{10}',token_id):raise ValueError('Invalid managed-token ID')
  request(client,'DELETE','/api/v1/tokens/'+token_id)
 result=request(client,'POST','/api/v1/tokens/',{'name':'harness-local','ttl':2592000})
 token=result['data']['token'];validate_token(token)
 private_json(STATE,{'base':BASE,'token':token,'ttlSeconds':2592000})
 print('Guest-local managed token renewed. Secret values omitted.')

def main():
 if str(Path.home())!='/home/purge' or sys.platform!='linux':raise ValueError('This client runs only inside the dedicated guest')
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['status','providers','flows','run','flow','logs','toolcalls','stop','finish','bootstrap','renew']);p.add_argument('flow',nargs='?');p.add_argument('--task');a=p.parse_args()
 if a.action=='bootstrap':bootstrap();return
 if a.action=='renew':renew();return
 if STATE.is_symlink() or STATE.stat().st_mode&0o077:raise ValueError('Local API connection file must be owner-only and not a symlink')
 state=json.loads(STATE.read_text());assert state['base']==BASE
 method,path,body=operation(a.action,a.flow,a.task)
 result=request(opener(),method,path,body,state['token'])
 print(json.dumps(redact(result,[state['token']]),ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception:print('Local PentAGI operation failed; inspect service status and credential metadata. For an expired local token, run pentagi-vm renew explicitly. Secret values omitted.',file=sys.stderr);raise SystemExit(1)
