def digest(raw):return hashlib.sha256(raw).hexdigest()
def inventory(root):
    return {str(p.relative_to(root)):digest(p.read_bytes()) for p in root.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts}
def system(action,unit,check=True):
    return subprocess.run(['systemctl','--user',action,unit],env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'},
                          capture_output=True,text=True,check=check,timeout=30)
def active(unit):return system('is-active',unit,False).returncode==0
def docker(*args):
    return subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker',*args],text=True,timeout=10).splitlines()
def assert_idle():
    for file in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
        with sqlite3.connect(file.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('security_run','security_joint'):
                if table in tables:
                    assert db.execute("SELECT COUNT(*) FROM "+table+" WHERE state IN ('running','cancelling')").fetchone()[0]==0
            if 'security_joint_pending' in tables:assert db.execute('SELECT COUNT(*) FROM security_joint_pending').fetchone()[0]==0
    for label in ('personal.harness.security=true','personal.harness.joint','personal.harness.runtime'):
        assert not docker('ps','-aq','--filter','label='+label)
    assert not docker('network','ls','-q','--filter','label=personal.harness.runtime')
    assert not any(n.startswith('pentagi-terminal-') for n in docker('ps','--format','{{.Names}}'))
    assert not list((home/'.dsh-improved/security-runtime-links').glob('*.json'))
def watched_raw():
    files=sorted((home/'.dsh-improved/redteam/engagements').glob('*/assets.db'))
    files += [home/name for name in ['.dsh-improved/cordis.patch.yml','.dsh-improved/.credentials.yaml','tools/security-workbench/images.json','tools/security-workbench/rules.json','.dsh-improved/profiles/web/cordis.patch.yml','.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket'] if (home/name).is_file()]
    result={}
    for path in files:
        with path.open('rb') as stream:result[str(path)]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result
def watched():
    files=sorted((home/'.dsh-improved/redteam/engagements').glob('*/assets.db'))
    result={}
    for path in files:
        digest=hashlib.sha256()
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)
        try:
            for statement in db.iterdump():digest.update((statement+'\n').encode())
        finally:db.close()
        result[str(path)]=digest.hexdigest()
    for path in [home/name for name in ['.dsh-improved/cordis.patch.yml','.dsh-improved/.credentials.yaml','tools/security-workbench/images.json','tools/security-workbench/rules.json','.dsh-improved/profiles/web/cordis.patch.yml','.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket'] if (home/name).is_file()]:
        result[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result
