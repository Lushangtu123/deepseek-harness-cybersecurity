def digest(path):return sha256(path.read_bytes()).hexdigest()

def identity():
    databases={}
    for p in (daily/'redteam/engagements').glob('*/assets.db'):
        value=sha256()
        with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
            for row in db.iterdump():value.update((row+'\n').encode())
        databases[str(p)]=value.hexdigest()
    return {'program':{str(p.relative_to(installed)):digest(p) for p in installed.rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts},
            'config':{str(p):digest(p) for p in [daily/'.credentials.yaml',daily/'cordis.patch.yml',
                 daily/'profiles/web/package.json',daily/'profiles/web/cordis.patch.yml']},
            'pins':{name:digest(home/'tools/security-workbench'/name) for name in ['images.json','rules.json']},
            'runtime':digest(runtime/'@deepseek-ai/dsh-tools/lib/index.js'),'databases':databases,
            'outsideMountNamespace':os.readlink('/proc/self/ns/mnt'),'homeInode':daily.stat().st_ino}