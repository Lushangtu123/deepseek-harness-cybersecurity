from pathlib import Path
from hashlib import sha256
import importlib.util,json
w=Path(__file__).resolve().parent;host=Path.home()/'Library/Application Support/Harness Purge Original';spec=importlib.util.spec_from_file_location('m',host/'host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
protected=[host/'host-tools'/n for n in ['manage.py','egress_proxy.py','qemu-image.py','web-entry.mjs','web-health.mjs']]+[m.VM/'config.plist']
(w/'host-baseline.json').write_text(json.dumps({str(p):sha256(p.read_bytes()).hexdigest() for p in protected},indent=2)+'\n')
source="from pathlib import Path\nimport hashlib,json,os,re,sqlite3,subprocess\nhome=Path('/home/purge')\n"+(w/'helpers.py').read_text()+r"""
assert_idle()
program=home/'tools/dsh-purge-personal-1.1.77-personal.1'
files=inventory(program)
assert len(files)==166
units=['dsh-original.service','harness-security.socket','harness-security.service']
values={'program':files,'watched':watched(),'raw':watched_raw(),'services':{u:active(u) for u in units},'dailyPid':re.search(r'^MainPID=([1-9][0-9]*)$',system('show','dsh-original.service').stdout,re.M).group(1)}
print(json.dumps(values))
"""
v=json.loads(m.ssh('python3 -B -',input=source,timeout=50,phase='native-check').stdout);prior=json.loads((w.parent/'harness-namespace-managed-acceptance-v2-20261103/daily-baseline-program.json').read_text());assert v['program']==prior
(w/'baseline.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({'programFiles':len(v['program']),'protectedLogicalAndFiles':len(v['watched']),'services':v['services'],'dailyPid':v['dailyPid'],'dailyBaselineMatched':True,'auditsAndContainersIdle':True}))
