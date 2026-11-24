import os,sys,json,hashlib,platform
from pathlib import Path
root=Path('/home/purge/workspace/harness-new-script-acceptance-20261113/stdlib-cli-all20-fixture-lifecycle-20261124-r1')
try:
 info=os.lstat(root);state='present'
except FileNotFoundError:state='absent'
parent=root.parent;v=os.statvfs(parent);exe=Path(sys.executable).resolve();raw=exe.read_bytes()
print(json.dumps({'kind':'readonly-vm-readiness','uid':os.getuid(),'platform':sys.platform,'machine':platform.machine(),'pythonVersion':sys.version,'executable':sys.executable,'resolvedExecutable':str(exe),'executableSha256':hashlib.sha256(raw).hexdigest(),'rootState':state,'freeBytes':v.f_bavail*v.f_frsize,'floorBytes':512*1024**2,'guestFilesWritten':0,'batchSubmitted':False}))
