#!/usr/bin/env python3
"""Read-only export checks; failures remain failures with Python optimization."""
from pathlib import Path,PurePosixPath
import ast,hashlib,json,re,os,stat

EXECUTABLES = {'.dsh/toolchain/pentagi-cli.py', '.local/bin/toolchain-versions', '.local/bin/harness-vm-web', '.local/bin/reverse-case', '.local/bin/dsh', '.local/bin/codegraph', '.local/bin/reverse-route', '.local/bin/kali-vm'} | {'.local/lib/harness-kali-tools/'+name for name in ['nmap', 'nuclei', 'masscan', 'fscan', 'gogo', 'suo5', 'frpc', 'frps', 'chisel', 'ffuf', 'httpx', 'dnsx', 'subfinder', 'ksubdomain', 'impacket', 'curl', 'wget', 'dig', 'openssl', 'tcpdump', 'tshark', 'whatweb', 'nikto', 'sqlmap', 'file', 'strings']}

PATTERNS={
 'provider-key':re.compile(rb'\bsk-[A-Za-z0-9_-]{20,}\b'),
 'github-token':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
 'private-key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
}

def safe_name(name):
 return isinstance(name,str) and bool(name) and not PurePosixPath(name).is_absolute() and not any(x in {'','..','.'} for x in name.split('/')) and '\\' not in name

def load_inventory(path):
 value=json.loads(path.read_text())
 if not isinstance(value,dict):raise ValueError('Invalid inventory')
 return value

def verify(root):
 manifest=root/'inventory/files.sha256.json'
 expected=load_inventory(manifest)
 if any(not safe_name(k) or not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for k,v in expected.items()):raise ValueError('Invalid inventory')
 actual={};issues=[];text_count=binary_count=0
 def issue(category,code,name):issues.append({'category':category,'kind':code,'file':name})
 for p in sorted(root.rglob('*')):
  relative=p.relative_to(root);name=str(relative)
  if any(part in {'.git','__pycache__'} for part in relative.parts):continue
  if p.is_symlink():issue('unsupported','symlink',name);continue
  if not p.is_file() or p==manifest:continue
  raw=p.read_bytes();actual[name]=hashlib.sha256(raw).hexdigest()
  if p.name.startswith(('.credentials.','guest-ed25519')) or p.name in {'.env','secrets.env','pentagi-admin.json','pentagi-connection.json','known_hosts'} or p.suffix in {'.db','.sqlite','.jsonl','.log','.qcow2','.img','.iso','.tar','.tgz','.zip'} or any(x in {'sessions','storages','node_modules','.ssh','harness-kali'} for x in relative.parts):issue('credential','excluded-artifact',name)
  for label,pattern in PATTERNS.items():
   if pattern.search(raw):issue('credential',label,name)
  try:text=raw.decode('utf-8');text_count+=1
  except UnicodeDecodeError:
   binary_count+=1
   if p.suffix not in {'.png','.jpg'}:issue('unsupported','unexpected-binary',name)
   continue
  try:
   if p.suffix=='.py':ast.parse(text,filename=name)
   if p.suffix=='.json':json.loads(text)
  except (ValueError,SyntaxError):issue('unsupported','parse-error',name)
 for name in sorted(set(actual)|set(expected)):
  if actual.get(name)!=expected.get(name):issue('integrity','manifest-mismatch',name)
 source=load_inventory(root/'work/harness-purge-improved/package-files.json')
 ledger=load_inventory(root/'inventory/export.json')
 guest=ledger.get('guestFiles')
 if not isinstance(guest,dict) or not source:raise ValueError('Invalid source inventory')
 if any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in source.values()):raise ValueError('Invalid program digest')
 if any(not isinstance(v,dict) or not isinstance(v.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',v['sha256']) for v in guest.values()):raise ValueError('Invalid guest digest')
 program_count=guest_count=0
 def digest(relative):
  if not safe_name(relative):raise ValueError('Invalid source path')
  p=root/relative
  if p.resolve()!=p or not p.is_file():return None
  return hashlib.sha256(p.read_bytes()).hexdigest()
 for name,want in source.items():
  if not safe_name(name):raise ValueError('Invalid source path')
  relative='work/harness-purge-improved/package/'+name
  if digest(relative)==want:program_count+=1
  else:issue('integrity','program-mismatch',relative)
 for name,row in guest.items():
  if not isinstance(row,dict):raise ValueError('Invalid guest inventory')
  if digest(name)==row.get('sha256'):guest_count+=1
  else:issue('integrity','guest-mismatch',name)
 modes=ledger.get('executionRequirements')
 if not isinstance(modes,dict) or set(modes)!=EXECUTABLES or any(type(mode) is not int or not 0 <= mode <= 0o777 or not mode&0o100 for mode in modes.values()):raise ValueError('Invalid executable inventory')
 for relative in modes:
  matches=[name for name,row in guest.items() if (row.get('sourcePath') or (name[len('guest-home/'):] if name.startswith('guest-home/') else None))==relative]
  if len(matches)!=1:raise ValueError('Invalid executable source')
  name=matches[0];p=root/name
  # Git preserves the executable class, not the exact private VM mode (0700/0755).
  if p.resolve()!=p or not p.is_file() or not p.stat().st_mode&stat.S_IXUSR or not os.access(p,os.X_OK):issue('integrity','execute-unavailable',name)
 return {'ok':not issues,'filesMatched':sum(actual.get(k)==v for k,v in expected.items()),'expectedFiles':len(expected),'programFilesMatched':program_count,'programExpected':len(source),'guestFilesMatched':guest_count,'guestExpected':len(guest),'textFilesChecked':text_count,'upstreamImageFiles':binary_count,'credentialPatternFindings':sum(x['category']=='credential' for x in issues),'integrityFindings':sum(x['category']=='integrity' for x in issues),'unsupportedFindings':sum(x['category']=='unsupported' for x in issues),'issues':issues,'scope':'integrity, Python/JSON parse and fixed credential patterns; not a complete security audit'}

def main():
 try:result=verify(Path(__file__).resolve().parent.parent)
 except (OSError,ValueError,TypeError,KeyError):result={'ok':False,'issues':[{'category':'integrity','kind':'inventory-unavailable-or-invalid','file':'inventory'}]}
 print(json.dumps(result,ensure_ascii=False))
 return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
