import {execFileSync} from 'node:child_process';
import {SENSITIVE_KEY_PATTERN} from './personal-evidence-redaction.mjs';
import {runReviewParser,reviewCheckpoint} from './personal-review-control.mjs';
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
sensitive=re.compile(p['sensitiveKeyPattern'],re.I)
def sensitive_name(key):
 key=re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1_\2',key)
 key=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',key).replace('-','_').lower()
 return sensitive.fullmatch(key)
forced=set();ambiguous=set()
def force(n):
 if isinstance(n,ast.Constant):forced.add(id(n));return
 if isinstance(n,ast.JoinedStr):ambiguous.add(id(n));return
 # Lookup keys identify a value, as with .get(); keep their names visible.
 if isinstance(n,ast.Subscript):force(n.value);return
 # Environment/dict getter keys are identifiers, not credential values.
 if isinstance(n,ast.Call):
  if isinstance(n.func,ast.Attribute):force(n.func.value)
  getter=isinstance(n.func,ast.Attribute) and n.func.attr in ('get','getenv') or isinstance(n.func,ast.Name) and n.func.id=='getenv'
  for a in n.args[1:] if getter else n.args:force(a)
  for k in n.keywords:force(k.value)
  return
 for c in ast.iter_child_nodes(n):force(c)
def target_sensitive(t):
 if isinstance(t,ast.Name):return bool(sensitive_name(t.id))
 if isinstance(t,ast.Attribute):return bool(sensitive_name(t.attr))
 if isinstance(t,ast.Subscript):
  key=t.slice
  if isinstance(key,ast.Index):key=key.value
  return isinstance(key,ast.Constant) and isinstance(key.value,str) and bool(sensitive_name(key.value))
 if isinstance(t,(ast.Tuple,ast.List)):return any(target_sensitive(c) for c in t.elts)
 if isinstance(t,ast.Starred):return target_sensitive(t.value)
 return False
def force_assignment(t,v):
 if not target_sensitive(t):return
 if isinstance(t,(ast.Tuple,ast.List)):
  if not isinstance(v,(ast.Tuple,ast.List)) or len(t.elts)!=len(v.elts) or any(isinstance(c,ast.Starred) for c in t.elts+v.elts):
   raise ValueError('ambiguous sensitive unpacking')
  for a,b in zip(t.elts,v.elts):force_assignment(a,b)
 elif isinstance(t,ast.Starred):raise ValueError('ambiguous sensitive unpacking')
 else:force(v)
for n in nodes:
 if isinstance(n,(ast.Assign,ast.AnnAssign,ast.NamedExpr)):
  targets=n.targets if isinstance(n,ast.Assign) else [n.target]
  if n.value is not None:
   for t in targets:force_assignment(t,n.value)
 elif isinstance(n,ast.arguments):
  positional=n.posonlyargs+n.args
  for a,v in zip(positional[len(positional)-len(n.defaults):],n.defaults):
   if sensitive_name(a.arg):force(v)
  for a,v in zip(n.kwonlyargs,n.kw_defaults):
   if v is not None and sensitive_name(a.arg):force(v)
 elif isinstance(n,ast.keyword) and n.arg and sensitive_name(n.arg):force(n.value)
 elif isinstance(n,ast.Dict):
  for k,v in zip(n.keys,n.values):
   if isinstance(k,ast.Constant) and isinstance(k.value,str) and sensitive_name(k.value):force(v)
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
function parse(text){try{return JSON.parse(execFileSync('/usr/bin/python3',['-I','-S','-B','-c',PARSER],{input:JSON.stringify({source:text,sensitiveKeyPattern:SENSITIVE_KEY_PATTERN}),encoding:'utf8',timeout:5000,maxBuffer:8388608,env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'},stdio:['pipe','pipe','ignore']}))}catch{throw Error('Python源码不能安全解析或脱敏；未执行项目代码')}}
function rewritePython(text,items,sanitize,sanitizeKnown){
 const changes=[];for(const item of items){const safe=item.force?'[REDACTED]':String(sanitize(item.value));if(safe===item.value&&!item.force)continue;if(item.ambiguous)throw Error('Python插值字符串不能安全脱敏');let replacement;if(item.comment)replacement=safe.replace(/[\r\n]/g,' ');else if(item.bytes){if([...safe].some(c=>c.codePointAt(0)>255))throw Error('Python字节字符串不能安全脱敏');replacement="b'"+[...safe].map(c=>'\\x'+c.codePointAt(0).toString(16).padStart(2,'0')).join('')+"'"}else replacement=JSON.stringify(safe);changes.push({start:item.span[0],end:item.span[1],replacement})}
 changes.sort((a,b)=>a.start-b.start);const raw=Buffer.from(text);let end=0;const parts=[];for(const change of changes){if(change.start<end||change.end<change.start||change.end>raw.length)throw Error('Python脱敏位置重叠');parts.push(raw.subarray(end,change.start),Buffer.from(change.replacement));end=change.end}parts.push(raw.subarray(end));const safe=Buffer.concat(parts).toString('utf8');if(String(sanitizeKnown(safe))!==safe)throw Error('Python源码仍含已登记敏感值，拒绝复制');return{safe,changed:changes.length>0};
}
export function sanitizePythonSource(text,sanitize,sanitizeKnown){const {safe,changed}=rewritePython(text,parse(text),sanitize,sanitizeKnown);if(changed)parse(safe);return safe}
async function parseAsync(text,control){
 const result=await runReviewParser('/usr/bin/python3',['-I','-S','-B','-c',PARSER],JSON.stringify({source:text,sensitiveKeyPattern:SENSITIVE_KEY_PATTERN}),control);
 if(result.code!==0)throw Error('Python源码不能安全解析或脱敏；未执行项目代码');
 try{return JSON.parse(result.stdout)}catch{throw Error('Python解析输出无效；未执行项目代码')}
}
export async function sanitizePythonSourceAsync(text,sanitize,sanitizeKnown,control){const {safe,changed}=rewritePython(text,await parseAsync(text,control),sanitize,sanitizeKnown);reviewCheckpoint(control);if(changed)await parseAsync(safe,control);return safe}
