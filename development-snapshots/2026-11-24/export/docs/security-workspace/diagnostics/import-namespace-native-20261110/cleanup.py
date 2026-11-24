from pathlib import Path
import importlib.util,json
r=Path(__file__).resolve().parent;stage=json.loads((r/'stage.json').read_text())
p=importlib.util.spec_from_file_location('b',r/'vm-bridge.py');b=importlib.util.module_from_spec(p);p.loader.exec_module(b)
v=b.call('ROOT='+repr(stage['root'])+'\n'+(r/'cleanup-script.txt').read_text(),35)
(r/'cleanup-full.json').write_text(json.dumps(v,indent=2)+'\n');(r/'cleanup.json').write_text(json.dumps(v['summary'],indent=2)+'\n');print(json.dumps(v['summary']))
