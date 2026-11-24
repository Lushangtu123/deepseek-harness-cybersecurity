from pathlib import Path
import importlib.util,json
w=Path(__file__).resolve().parent;spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
source=r'''
from pathlib import Path
import json,subprocess
manifest=json.loads(Path('/home/purge/tools/security-workbench/images.json').read_text());image=next(t['imageId'] for t in manifest['tools'] if t['tool']=='semgrep');name='pymatgen-runtime-check-20261103'
code="import json,platform,sys;from pathlib import Path;print(json.dumps({'python':sys.version.split()[0],'libc':platform.libc_ver(),'osRelease':Path('/etc/os-release').read_text()}))"
try:
 r=subprocess.run(['sudo','-n','/usr/bin/docker','run','--rm','--pull','never','--name',name,'--network','none','--user','65534:65534','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','128m','--pids-limit','16','--entrypoint','python3',image,'-I','-B','-c',code],capture_output=True,text=True,timeout=10);assert r.returncode==0,r.stderr;print(r.stdout)
finally:subprocess.run(['sudo','-n','/usr/bin/docker','rm','-f',name],capture_output=True,timeout=5)
'''
v=json.loads(m.ssh('python3 -B -',input=source,timeout=20,phase='native-check').stdout);(w/'runtime-check.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
