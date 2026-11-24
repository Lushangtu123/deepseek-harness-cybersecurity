from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import base64,importlib.util,json,threading
w=Path(__file__).resolve().parent;session=json.loads((w/'session.json').read_text());assert session['root'].startswith('/home/purge/.cache/import-namespace-live-')
spec=importlib.util.spec_from_file_location('b',w/'vm-bridge.py');bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
allowed={'/','/base.css','/react.js','/react-dom.js','/client.mjs','/personal-semgrep-profile.mjs','/personal-security-observation.mjs','/api','/health','/__collect','/__stop'}
done=threading.Event()
def remote(route,method,body,host,origin):
 args={'url':'http://127.0.0.1:'+str(session['port'])+route,'method':method,'headers':{'Host':host}}
 if origin:args['headers']['Origin']=origin
 if body:args['data']=base64.b64encode(body).decode()
 source='ARGS='+repr(args)+'\n'+r'''
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import base64,json
if 'data' in ARGS:ARGS['data']=base64.b64decode(ARGS['data'])
try:r=urlopen(Request(**ARGS),timeout=45)
except HTTPError as e:r=e
with r:
 raw=r.read(4*1024*1024+1);assert len(raw)<=4*1024*1024
 print(json.dumps({'status':r.status,'type':r.headers.get('Content-Type','text/plain'),'body':base64.b64encode(raw).decode()}))
'''
 return bridge.call(source,55)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def process(self):
  host='127.0.0.1:'+str(self.server.server_port)
  if self.path not in allowed or self.headers.get('Host')!=host:self.send_error(404);return
  if self.command=='POST' and self.headers.get('Origin')!='http://'+host:self.send_error(403);return
  try:
   length=int(self.headers.get('Content-Length',0));assert 0<=length<=32768
   r=remote(self.path,self.command,self.rfile.read(length) if length else None,host,self.headers.get('Origin'))
   self.send_response(r['status']);self.send_header('Content-Type',r['type']);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'");self.end_headers();self.wfile.write(base64.b64decode(r['body']))
   if self.path=='/__stop':done.set()
  except Exception as e:self.send_error(502,'Owned test relay unavailable');print(json.dumps({'relayError':type(e).__name__}),flush=True)
 do_GET=process
 do_POST=process
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
url='http://127.0.0.1:'+str(server.server_port);(w/'access-url.txt').write_text(url+'/\n');print(json.dumps({'url':url+'/','transport':'loopback SSH command relay; no forwarding or config change'}),flush=True)
try:done.wait(1200)
finally:server.shutdown();server.server_close()
