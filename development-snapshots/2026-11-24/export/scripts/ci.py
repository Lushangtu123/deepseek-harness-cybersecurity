#!/usr/bin/env python3
"""Dependency-free checks for the sanitized export; no VM or account access."""
from pathlib import Path
import argparse,shutil,subprocess,sys,tempfile

SUITES=('export','python','plugin','host','client')

def invoke(argv,**kwargs):return subprocess.run(argv,capture_output=True,text=True,**kwargs)

def execute(argv,root,run,label):
 try:result=run(argv,cwd=root,timeout=180)
 except subprocess.TimeoutExpired:print('FAIL '+label+': deadline exceeded',flush=True);return 124
 except FileNotFoundError:print('FAIL '+label+': executable unavailable',flush=True);return 127
 code=result.returncode
 if type(code) is not int:raise ValueError('Check did not return a process exit code')
 print(('PASS ' if code==0 else 'FAIL ')+label+' (exit '+str(code)+')',flush=True)
 output=(getattr(result,'stdout','') or '')+(getattr(result,'stderr','') or '')
 if output:
  limit=1600 if code==0 else 24000
  if len(output)>limit:print('[earlier child output omitted; final output follows]',flush=True)
  print(output[-limit:],flush=True)
 return code if 0<=code<=255 else 1

def tests(root,directory,pattern):
 files=sorted((root/directory).glob(pattern))
 if any(path.is_symlink() or not path.is_file() or path.resolve()!=path for path in files):raise ValueError('Test inventory must contain ordinary files')
 return files

def run_suite(root,suite,run=invoke):
 root=Path(root).resolve()
 try:
  if suite=='export':return execute([sys.executable,'-B',str(root/'scripts/verify_export.py')],root,run,'export integrity and fixed credential patterns')
  if suite=='python':
   files=[]
   for directory in ['scripts','work/harness-purge-vm','work/harness-purge-improved/tests']:files.extend(tests(root,directory,'*.test.py'))
   if not files:raise ValueError('Python test inventory is empty')
   for file in files:
    code=execute([sys.executable,'-B',str(file)],root,run,str(file.relative_to(root)))
    if code:return code
   return 0
  node=shutil.which('node')
  if not node:print('FAIL '+suite+': Node.js unavailable',flush=True);return 127
  if suite in ['plugin','host']:
   directory='work/harness-purge-improved/tests' if suite=='plugin' else 'work/harness-purge-vm';files=tests(root,directory,'*.test.mjs')
   if not files:raise ValueError('Node test inventory is empty')
   return execute([node,'--test',*map(str,files)],root,run,suite+' tests ('+str(len(files))+' files)')
  if suite=='client':
   source=root/'work/harness-purge-improved/package'
   if source.is_symlink() or not source.is_dir() or any(path.is_symlink() for path in source.rglob('*')):raise ValueError('Client source must be an ordinary directory tree')
   with tempfile.TemporaryDirectory(prefix='harness-client-ci-') as directory:
    copied=Path(directory).resolve()/'package';shutil.copytree(source,copied)
    code=execute([node,'scripts/build-client.mjs'],copied,run,'client rebuild in temporary copy')
    if code:return code
    if (copied/'client.js').read_bytes()!=(source/'client.js').read_bytes():print('FAIL client: checked-in bundle differs from source rebuild',flush=True);return 1
   print('PASS client bundle is reproducible; original files unchanged',flush=True);return 0
  raise ValueError('Unknown check suite')
 except (OSError,ValueError):print('FAIL '+suite+': missing or unsafe check input',flush=True);return 1

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--suite',choices=('all',*SUITES),default='all');args=parser.parse_args();root=Path(__file__).resolve().parent.parent
 for suite in SUITES if args.suite=='all' else [args.suite]:
  code=run_suite(root,suite)
  if code:return code
 return 0

if __name__=='__main__':raise SystemExit(main())
