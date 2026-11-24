from pathlib import Path
import importlib.util,json
w=Path(__file__).resolve().parent;session=json.loads((w/'session.json').read_text());source='SESSION='+repr(session)+'\n'+(w/'recovery-source.py').read_text()
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
r=json.loads(m.ssh('python3 -B -',input=source,timeout=35,phase='native-check').stdout);(w/'cleanup-full.json').write_text(json.dumps(r,indent=2)+'\n');s={k:v for k,v in r.items() if k!='final'};(w/'cleanup.json').write_text(json.dumps(s,indent=2)+'\n');print(json.dumps(s))
