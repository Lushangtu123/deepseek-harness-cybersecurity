from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm';assets=w.parent/'harness-workspace-browser-20261103/assets';r=json.loads((w/'native.json').read_text())['nativeReviewer']['automaticJoint'];task=r['task'];eng=task['engagement']
html="""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>执行点观察 · 只读界面回放</title><script src="/react.js"></script><script src="/react-dom.js"></script><style>body{font:16px system-ui;background:#f6f8fb;color:#172233;margin:0}main{max-width:1120px;padding:24px;margin:auto}.rt-card,aside{padding:20px;background:#fff;border:1px solid #dbe3ec;border-radius:12px;margin-bottom:16px}button{padding:8px;margin:6px}li{margin:14px 0}code,p{overflow-wrap:anywhere}</style><main><aside><b>执行点观察 · 只读界面回放</b><p>数据来自 VM 真实受限 worker 及联合记录；扫描器输入复用旧回执。本页仅检查正式组件展示，不调用工具、不代表日常部署。</p></aside><div id="root"></div></main><script type="module">import {createJointPanel} from '/client.mjs';const api=async r=>(await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(r)})).json();const C=createJointPanel(React,api);ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(C,{engagement:__ENG__,profile:{revision:1,expiresAt:'2099-01-01T00:00:00Z'}}));</script></html>"""
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,body,kind='application/json'):
  if not isinstance(body,bytes):body=body.encode()
  self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
 def do_GET(self):
  paths={'/react.js':assets/'react.production.min.js','/react-dom.js':assets/'react-dom.production.min.js','/client.mjs':repo/'work/harness-purge-improved/package/lib/redteam/personal-security-client.mjs','/personal-security-observation.mjs':repo/'work/harness-purge-improved/package/lib/redteam/personal-security-observation.mjs'}
  if self.path=='/':return self.send(200,html.replace('__ENG__',json.dumps(eng)),'text/html')
  if self.path in paths:return self.send(200,paths[self.path].read_bytes(),'text/javascript')
  self.send(404,'{}')
 def do_POST(self):
  if self.headers.get('Origin')!=origin or int(self.headers.get('Content-Length','0'))>16384:return self.send(403,'{}')
  if self.path=='/__stop':self.send(200,'{"stopped":true}');threading.Thread(target=self.server.shutdown,daemon=True).start();return
  q=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));action=q.get('action');v={'ok':True,'engagement':eng}
  if q.get('engagement')!=eng:return self.send(403,'{}')
  if action=='plan':v.update(profileRevision=1,availableSteps=['semgrep'],kaliAllowed=False,workspace={'mode':'deep'})
  elif action=='status':v.update(task=task,requestState='accepted')
  elif action=='report' and q.get('id')==task['id'] and q.get('section') in r['sections']:
   section=q['section'];rows=r['sections'][section];start=int(q.get('cursor','0'));end=min(start+3,len(rows));v.update(task=task,page={'section':section,'items':rows[start:end],'total':len(rows),'complete':end==len(rows),'nextCursor':str(end) if end<len(rows) else None})
  else:return self.send(403,'{"ok":false,"error":"Read-only UI replay"}')
  self.send(200,json.dumps(v))
s=ThreadingHTTPServer(('127.0.0.1',0),H);origin='http://127.0.0.1:'+str(s.server_port);(w/'ui-url.txt').write_text(origin+'/');print(json.dumps({'url':origin+'/','purpose':'read-only replay of actual VM joint namespace artifacts'}),flush=True)
timer=threading.Timer(900,s.shutdown);timer.daemon=True;timer.start();s.serve_forever();s.server_close();timer.cancel()
