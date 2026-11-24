from pathlib import Path
import importlib.util,json
work=Path(__file__).resolve().parent
host=Path.home()/'Library/Application Support/Harness Purge Original'
spec=importlib.util.spec_from_file_location('manager',host/'host-tools/manage.py')
manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)
manager.validate()
source=r'''
from pathlib import Path
import hashlib,json,sqlite3
home=Path('/home/purge')
def database(name):
    path=home/'.dsh-improved/redteam/engagements'/name/'assets.db'
    return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
with database('phishguard-model-closure-20261102') as db:
    task=json.loads(db.execute("SELECT data FROM security_joint WHERE id=?",('bd86f6bf-d1b3-474c-b3df-f55172f4e956',)).fetchone()[0])
items=task['findings']
unique={(row.get('tool'),row.get('rule'),row.get('location'),row.get('sourceTask')) for row in items}
assert len(items)==56 and len(unique)==49 and all(row['status']=='unverified' for row in items)
with database('personal-security-real-20261029') as db:
    statuses=dict(db.execute('SELECT status,COUNT(*) FROM security_finding GROUP BY status'))
assert statuses=={'unverified':95}
print(json.dumps({'oldTaskRawFindings':len(items),'oldTaskUniqueFindings':len(unique),'protectedFindingsByStatus':statuses}))
'''
receipt=json.loads(manager.ssh('python3 -B -',input=source,timeout=20,phase='native-check').stdout)
(work/'old-task-check.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
