#!/usr/bin/env python3
"""Offline synthetic Semgrep parser check; never changes the installed image or project data."""
from pathlib import Path
import argparse,hashlib,json,os,re,stat,subprocess,sys,tempfile,uuid

HOME=Path('/home/purge')
MANIFEST=HOME/'tools/security-workbench/images.json'
REPRO="""const source = name => readFileSync(new URL(`./${name}`, import.meta.url), 'utf8');
function loadI18n({languages = ['en-US'], storage = memoryStorage(), document, console: con = console, zh = true} = {}) {
}
test('all visible homepage text is translatable except language-neutral names', () => {
  const html = source('index.html').replace(/<!--[\\s\\S]*?-->|<!DOCTYPE[^>]*>/g, '')
  for (const [, close, tag, attrs, textNode] of html.matchAll(/<(\\/?)([a-z0-9]+)\\b([^>]*)>|([^<]+)/g)) {
    if (textNode !== undefined) {
    }
  }
  assert.doesNotMatch(html, /data-i18n-html=/, 'the workspace writes no dictionary HTML');
});
"""
FIXTURES={'repro.mjs':REPRO,'escaped.mjs':REPRO.replace('/<!--','/\\x3c!--'),
 'semicolon.mjs':REPRO.replace("DOCTYPE[^>]*>/g, '')","DOCTYPE[^>]*>/g, '');"),
 'no-comment.mjs':REPRO.replace('<!--[\\s\\S]*?-->|',''),
 'positive-after.mjs':REPRO+'\nexport function call(input) { return eval(input); }\n',
 'benign.mjs':'export const read = input => JSON.parse(input);\n',
 'positive.mjs':'export function call(input) { return eval(input); }\n',
 'invalid.mjs':'function broken( {\n'}
RULES={'rules':[{'id':'probe.expression','languages':['javascript'],'message':'Parser expression control','severity':'INFO','pattern':'$X'},
 {'id':'probe.eval','languages':['javascript'],'message':'Synthetic eval control','severity':'INFO','pattern':'eval(...)'}]}
IMAGE=re.compile(r'sha256:[a-f0-9]{64}\Z')
class ProbeError(Exception):pass

def target(value):
 if not isinstance(value,str):raise ProbeError('Parser response target invalid')
 name=value.removeprefix('/src/')
 if name not in FIXTURES:raise ProbeError('Parser response target unexpected')
 return name

def evaluate(value,exit_code):
 if exit_code!=0 or not isinstance(value,dict) or not isinstance(value.get('paths'),dict) or not isinstance(value['paths'].get('scanned'),list) or not isinstance(value.get('errors'),list) or not isinstance(value.get('results'),list):raise ProbeError('Parser response invalid')
 scanned=[target(name) for name in value['paths']['scanned']]
 if len(set(scanned))!=len(scanned):raise ProbeError('Parser response duplicate targets')
 cases={name:{'scanned':name in scanned,'errors':[],'expressionMatches':0,'evalMatches':0} for name in FIXTURES}
 for error in value['errors']:
  if not isinstance(error,dict):raise ProbeError('Parser diagnostic invalid')
  kind=error.get('type');locations=kind[1] if isinstance(kind,list) and len(kind)==2 else None
  paths=[item.get('path') for item in locations] if isinstance(locations,list) and locations and all(isinstance(item,dict) for item in locations) else [error.get('path')]
  code=kind[0] if isinstance(kind,list) and len(kind)==2 else kind
  if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9 _-]{0,79}',code):raise ProbeError('Parser diagnostic invalid')
  for name in set(target(path) for path in paths):cases[name]['errors'].append(code)
 for finding in value['results']:
  if not isinstance(finding,dict) or finding.get('check_id') not in ['probe.expression','probe.eval']:raise ProbeError('Parser control result invalid')
  name=target(finding.get('path'));key='expressionMatches' if finding['check_id']=='probe.expression' else 'evalMatches';cases[name][key]+=1
 controls=all(cases[name]['scanned'] and not cases[name]['errors'] and cases[name]['expressionMatches']>0 for name in ['escaped.mjs','no-comment.mjs','benign.mjs','positive.mjs']) and cases['positive.mjs']['evalMatches']>0 and cases['benign.mjs']['evalMatches']==0 and cases['invalid.mjs']['scanned'] and bool(cases['invalid.mjs']['errors']) and all(code in ['PartialParsing','ParseError','LexicalError'] for code in cases['invalid.mjs']['errors']) and all(cases[name]['scanned'] for name in ['repro.mjs','semicolon.mjs','positive-after.mjs'])
 ready=controls and all(not cases[name]['errors'] and cases[name]['expressionMatches']>0 for name in ['repro.mjs','semicolon.mjs','positive-after.mjs']) and cases['positive-after.mjs']['evalMatches']>0
 return {'version':1,'executionOk':True,'controlsPassed':bool(controls),'parserReady':bool(ready),'exitCode':0 if ready else 2 if controls else 1,'fixtureCount':len(FIXTURES),'cases':cases,'limits':'Synthetic parser and rule controls only; no proof of complete project coverage or exploitability.'}

def plan(image,inputs,outputs,name):
 if not isinstance(image,str) or not IMAGE.fullmatch(image) or not re.fullmatch(r'harness-parser-[a-f0-9]{12}',name):raise ProbeError('Local image identity invalid')
 return ['sudo','-n','docker','run','--rm','--pull','never','--name',name,'--log-driver','none','--label','personal.harness.parser.probe=true','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','128','--memory','1g','--cpus','1','--user','1000:1000','--tmpfs','/tmp:rw,nosuid,nodev,size=134217728','--env','HOME=/tmp','--env','SEMGREP_ENABLE_VERSION_CHECK=0','--env','SEMGREP_SEND_METRICS=off','--mount','type=bind,src='+str(inputs)+',dst=/src,readonly','--tmpfs','/out:rw,nosuid,nodev,noexec,size=16777216,uid=1000,gid=1000,mode=0700','--mount','type=bind,src='+str(Path(__file__).with_name('security-output.sh'))+',dst=/policy-output.sh,readonly','--entrypoint','/bin/sh',image,'/policy-output.sh','/out','semgrep','scan','--config','/src/probe-rules.json','--json','--output','/out/result.json','--metrics=off','--disable-version-check','--jobs','1','--timeout','5','--max-target-bytes','1000000','/src']

def read_result(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_size>2*1024*1024:raise ProbeError('Parser output file invalid')
  with os.fdopen(fd,'rb',closefd=False) as source:raw=source.read(2*1024*1024+1)
  if len(raw)>2*1024*1024:raise ProbeError('Parser output exceeds limit')
  return json.loads(raw)
 finally:os.close(fd)

def check(image=None):
 if sys.platform!='linux' or Path.home()!=HOME or os.getuid()!=1000:raise ProbeError('仅在专用Linux VM的purge账号中执行解析自检')
 before=hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
 if image is None:image=next(row['imageId'] for row in json.loads(MANIFEST.read_text())['tools'] if row['tool']=='semgrep')
 if not isinstance(image,str) or not IMAGE.fullmatch(image):raise ProbeError('Local image identity invalid')
 inspected=subprocess.run(['sudo','-n','docker','image','inspect',image],capture_output=True,text=True,timeout=8)
 if inspected.returncode:raise ProbeError('镜像未在本机就绪；自检不会拉取或升级镜像')
 metadata=json.loads(inspected.stdout)
 if not isinstance(metadata,list) or len(metadata)!=1 or metadata[0].get('Id')!=image or metadata[0].get('Architecture')!='arm64' or metadata[0].get('Os')!='linux':raise ProbeError('Local image identity or platform mismatch')
 name='harness-parser-'+uuid.uuid4().hex[:12]
 with tempfile.TemporaryDirectory(prefix='harness-parser-check-') as directory:
  root=Path(directory).resolve();inputs=root/'inputs';outputs=root/'output';inputs.mkdir(mode=0o700);outputs.mkdir(mode=0o700)
  for filename,source in FIXTURES.items():(inputs/filename).write_text(source)
  (inputs/'probe-rules.json').write_text(json.dumps(RULES));argv=plan(image,inputs,outputs,name)
  try:
   try:result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=45)
   except subprocess.TimeoutExpired:raise ProbeError('解析自检超过45秒期限')
   if len(result.stdout)>2*1024*1024:raise ProbeError('Parser output exceeds limit')
   envelope=json.loads(result.stdout);report=evaluate(envelope.get('result'),result.returncode)
  finally:
   # Address only this invocation's owned name. A killed Docker client can leave
   # its container alive; deletion is followed by an independent inventory read.
   subprocess.run(['sudo','-n','docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
   left=subprocess.run(['sudo','-n','docker','ps','-aq','--filter','name=^/'+name+'$'],capture_output=True,text=True,timeout=8)
   if left.returncode or left.stdout.strip():raise ProbeError('解析自检容器清理未确认')
 if hashlib.sha256(MANIFEST.read_bytes()).hexdigest()!=before:raise ProbeError('Installed scanner identity changed during probe')
 report.update(imageId=image,network='none',sourceExecuted=False,realProjectScanned=False,automaticChanges=False,installedManifestUnchanged=True,temporaryFilesRemoved=True,containerRemoved=True,outputQuotaBytes=16777216,hostOutputBind=False,fixturesSha256={name:hashlib.sha256(raw.encode()).hexdigest() for name,raw in FIXTURES.items()})
 return report

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image-id',help='Explicit immutable ID of an already loaded Linux ARM64 candidate; never pulls or installs');args=parser.parse_args()
 try:
  result=check(args.image_id);print(json.dumps(result,ensure_ascii=False,indent=2));return result['exitCode']
 except Exception:
  print(json.dumps({'version':1,'executionOk':False,'parserReady':False,'exitCode':1,'error':'解析自检未完成；请核对专用VM、固定本地镜像与容器状态。原扫描器和项目不自动更改。'},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
