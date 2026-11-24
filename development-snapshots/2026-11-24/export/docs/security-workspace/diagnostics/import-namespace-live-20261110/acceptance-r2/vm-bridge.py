from pathlib import Path
from hashlib import sha256
import json,types
MANAGER_SHA='19bd85c390e6d7482f78e77f6fe9de733258df0454d9a7921125be82b4a48bbf'
root=Path(__file__).resolve().parent

def call(script,timeout=30):
 p=Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py';raw=p.read_bytes()
 if sha256(raw).hexdigest()!=MANAGER_SHA:raise ValueError('Manager digest changed')
 m=types.ModuleType('review_vm_manager');m.__file__=str(p);exec(compile(raw,str(p),'exec'),m.__dict__);m.validate()
 result=m.ssh('/usr/bin/python3 -I -B -',input=script,timeout=timeout,phase='native-check')
 log=root/'vm-bridge-calls.jsonl'
 with log.open('a') as stream:stream.write(json.dumps({'purpose':'namespace route acceptance control only','remoteScriptSha256':sha256(script.encode()).hexdigest(),'exitCode':result.returncode,'timeout':timeout})+'\n')
 return json.loads(result.stdout)
