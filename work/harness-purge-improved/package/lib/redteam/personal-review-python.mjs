import {execFileSync} from 'node:child_process';
// Fixed stdlib parser only. Project bytes are stdin data, never code to this process.
const PARSER=String.raw`
import ast,io,json,sys,tokenize
p=json.load(sys.stdin);s=p['source'];raw=s.encode('utf-8')
assert len(raw)<=1048576
encoding,_=tokenize.detect_encoding(io.BytesIO(raw).readline)
assert encoding.lower().replace('_','-') in ('utf-8','utf-8-sig')
assert '\r' not in s.replace('\r\n','')
tree=ast.parse(s,feature_version=(3,12));nodes=list(ast.walk(tree));assert len(nodes)<=100000
stack=[(tree,0)]
while stack:
 n,d=stack.pop();assert d<=200
 stack.extend((c,d+1) for c in ast.iter_child_nodes(n))
lines=s.split('\n');lines=[line+'\n' for line in lines[:-1]]+[lines[-1]];offsets=[0]
for line in lines:offsets.append(offsets[-1]+len(line.encode('utf-8')))
def span(n):return [offsets[n.lineno-1]+n.col_offset,offsets[n.end_lineno-1]+n.end_col_offset]
def point(p):return offsets[p[0]-1]+len(lines[p[0]-1][:p[1]].encode('utf-8'))
import re
sensitive=re.compile(r'^(?:secret(?:_value)?|pass_key|password|passwd|access_token|refresh_token|api_key|apikey|authorization|proxy-authorization|cookie|set-cookie)$',re.I)
forced=set();ambiguous=set()
def force(n):
 if isinstance(n,ast.Constant):forced.add(id(n));return
 if isinstance(n,ast.JoinedStr):ambiguous.add(id(n));return
 # Environment/dict getter keys are identifiers, not credential values.
 if isinstance(n,ast.Call):
  if isinstance(n.func,ast.Attribute):force(n.func.value)
  getter=isinstance(n.func,ast.Attribute) and n.func.attr in ('get','getenv') or isinstance(n.func,ast.Name) and n.func.id=='getenv'
  for a in n.args[1:] if getter else n.args:force(a)
  for k in n.keywords:force(k.value)
  return
 for c in ast.iter_child_nodes(n):force(c)
for n in nodes:
 if isinstance(n,(ast.Assign,ast.AnnAssign,ast.NamedExpr)):
  targets=n.targets if isinstance(n,ast.Assign) else [n.target]
  if any(isinstance(t,(ast.Name,ast.Attribute)) and sensitive.fullmatch(t.id if isinstance(t,ast.Name) else t.attr) for t in targets) and n.value is not None:force(n.value)
 elif isinstance(n,ast.arguments):
  positional=n.posonlyargs+n.args
  for a,v in zip(positional[len(positional)-len(n.defaults):],n.defaults):
   if sensitive.fullmatch(a.arg):force(v)
  for a,v in zip(n.kwonlyargs,n.kw_defaults):
   if v is not None and sensitive.fullmatch(a.arg):force(v)
 elif isinstance(n,ast.keyword) and n.arg and sensitive.fullmatch(n.arg):force(n.value)
 elif isinstance(n,ast.Dict):
  for k,v in zip(n.keys,n.values):
   if isinstance(k,ast.Constant) and isinstance(k.value,str) and sensitive.fullmatch(k.value):force(v)
joined=set()
for n in nodes:
 if isinstance(n,ast.JoinedStr):joined.update(id(c) for c in ast.walk(n))
covered=set()
for n in nodes:
 if isinstance(n,ast.JoinedStr) and id(n) in ambiguous:covered.update(id(c) for c in ast.walk(n) if c is not n)
items=[]
for n in nodes:
 if id(n) in covered:continue
 if isinstance(n,ast.Constant):
  if isinstance(n.value,(str,bytes)):
   items.append(dict(span=span(n),value=n.value.decode('latin1') if isinstance(n.value,bytes) else n.value,bytes=isinstance(n.value,bytes),force=id(n) in forced,ambiguous=id(n) in joined))
  elif id(n) in forced:items.append(dict(span=span(n),value='',force=True))
 elif isinstance(n,ast.JoinedStr) and id(n) in ambiguous:items.append(dict(span=span(n),value='',force=True))
for t in tokenize.generate_tokens(io.StringIO(s).readline):
 if t.type==tokenize.COMMENT:items.append(dict(span=[point(t.start),point(t.end)],value=t.string,comment=True))
print(json.dumps(items,ensure_ascii=True))
`;
function parse(text){try{return JSON.parse(execFileSync('/usr/bin/python3',['-I','-S','-B','-c',PARSER],{input:JSON.stringify({source:text}),encoding:'utf8',timeout:5000,maxBuffer:8388608,env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'},stdio:['pipe','pipe','ignore']}))}catch{throw Error('Python源码不能安全解析或脱敏；未执行项目代码')}}
export function sanitizePythonSource(text,sanitize,sanitizeKnown){
 const changes=[];for(const item of parse(text)){const safe=item.force?'[REDACTED]':String(sanitize(item.value));if(safe===item.value&&!item.force)continue;if(item.ambiguous)throw Error('Python插值字符串不能安全脱敏');let replacement;if(item.comment)replacement=safe.replace(/[\r\n]/g,' ');else if(item.bytes){if([...safe].some(c=>c.codePointAt(0)>255))throw Error('Python字节字符串不能安全脱敏');replacement="b'"+[...safe].map(c=>'\\x'+c.codePointAt(0).toString(16).padStart(2,'0')).join('')+"'"}else replacement=JSON.stringify(safe);changes.push({start:item.span[0],end:item.span[1],replacement})}
 changes.sort((a,b)=>a.start-b.start);const raw=Buffer.from(text);let end=0;const parts=[];for(const change of changes){if(change.start<end||change.end<change.start||change.end>raw.length)throw Error('Python脱敏位置重叠');parts.push(raw.subarray(end,change.start),Buffer.from(change.replacement));end=change.end}parts.push(raw.subarray(end));const safe=Buffer.concat(parts).toString('utf8');if(String(sanitizeKnown(safe))!==safe)throw Error('Python源码仍含已登记敏感值，拒绝复制');if(changes.length)parse(safe);return safe;
}
