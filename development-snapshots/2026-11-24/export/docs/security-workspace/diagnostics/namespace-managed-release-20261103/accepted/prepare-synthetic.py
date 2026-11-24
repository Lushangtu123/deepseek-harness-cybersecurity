from pathlib import Path
import importlib.util,json,base64
w=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
source="from pathlib import Path\nimport base64,json,subprocess\ncode=base64.b64decode("+repr(base64.b64encode((w/'prepare-synthetic.mjs').read_bytes()).decode())+")\nr=subprocess.run(['/home/purge/.local/node/bin/node','--input-type=module','-'],input=code,capture_output=True,timeout=25)\nassert r.returncode==0,r.stderr.decode()\nprint(r.stdout.decode())"
v=json.loads(m.ssh('python3 -B -',input=source,timeout=40,phase='native-check').stdout);(w/'synthetic.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
