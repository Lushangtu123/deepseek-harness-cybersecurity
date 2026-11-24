
from pathlib import Path, PurePosixPath
import base64,hashlib,http.client,io,json,os,re,sqlite3,subprocess,tarfile,time,signal,stat
from http.cookies import SimpleCookie

home=Path('/home/purge')
assert Path.home()==home and os.getuid()==1000
package=home/'tools/dsh-purge-personal-1.1.77-personal.1'
backup=home/'.cache/harness-namespace-managed-release-20261103'
assert not backup.exists() and package.resolve()==package
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
units=['dsh-original.service','harness-security.socket','harness-security.service']
assert inventory(package)==OLD
assert len(OLD)==166 and len(NEW)==169 and len(BASELINE['watched'])==48
before_watched=watched();assert before_watched==BASELINE['watched']
raw_before=watched_raw()
assert_idle()
was={unit:active(unit) for unit in units}
assert was==BASELINE['services'] and was[units[0]]
raw=base64.b64decode(ARCHIVE);assert digest(raw)==EXPECTED['archiveSha256']
backup.mkdir(mode=0o700);assert backup.stat().st_dev==package.stat().st_dev
(backup/'protected-before.json').write_text(json.dumps({'logical':before_watched,'raw':raw_before}))
stage=backup/'candidate';stage.mkdir(mode=stat.S_IMODE(package.stat().st_mode));stage.chmod(stat.S_IMODE(package.stat().st_mode))
previous=backup/'previous'
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    seen=set()
    for member in archive:
        name=member.name; rel=PurePosixPath(name)
        assert member.isfile() and name in NEW and name not in seen and not rel.is_absolute() and '..' not in rel.parts
        path=stage/rel;path.parent.mkdir(parents=True,exist_ok=True)
        data=archive.extractfile(member).read();assert digest(data)==NEW[name]
        path.write_bytes(data);path.chmod(member.mode & 0o755);seen.add(name)
assert inventory(stage)==NEW
node=home/'.local/node/bin/node'
subprocess.run([node,'--check',stage/'client.js'],timeout=12,check=True)
def record(phase):
    atomic_json(backup/'state.json',{'phase':phase,'archiveSha256':EXPECTED['archiveSha256'],'servicesWereActive':was})
def stop():
    for unit in (units[1],units[2],units[0]):
        try:system('stop',unit)
        except subprocess.TimeoutExpired:pass
        deadline=time.monotonic()+10
        while True:
            result=system('show',unit)
            values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
            if values.get('ActiveState') in ('inactive','failed') and 'Job' in values and values['Job'] in ('','0'):break
            if time.monotonic()>=deadline:raise RuntimeError('Unit stop or job completion not confirmed: '+unit)
            time.sleep(0.2)
def start():
    for unit in units:
        if was[unit]:system('start',unit)
    assert active(units[0])
def healthy():
    pid=system('show','dsh-original.service')
    current=re.search(r'^MainPID=([1-9][0-9]*)$',pid.stdout,re.M)
    if not current:return False
    logs=subprocess.run(['journalctl','--user','-u','dsh-original','_PID='+current[1],'-n','45','--no-pager','-o','cat'],
        env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'},capture_output=True,text=True,timeout=4,check=True).stdout
    keys=re.findall(r'http://127\.0\.0\.1:49224/\?token=([A-Za-z0-9_-]+)',logs)
    if not keys:return False
    connection=http.client.HTTPConnection('10.0.2.15',3080,timeout=3)
    try:
        connection.request('GET','/?token='+keys[-1],headers={'Host':'127.0.0.1:49224'})
        response=connection.getresponse()
        cookies=SimpleCookie()
        for name,value in response.getheaders():
            if name.lower()=='set-cookie':cookies.load(value)
        response.read(2*1024*1024)
        if not cookies:return False
        connection.request('GET','/dsh-purge/status',headers={'Host':'127.0.0.1:49224',
            'Cookie':'; '.join(name+'='+value.value for name,value in cookies.items())})
        response=connection.getresponse()
        value=json.loads(response.read(1024*1024))
        return response.status==200 and value.get('ok') is True and value.get('ready') is True
    finally:connection.close()
def wait_healthy():
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try:
            if healthy():return
        except Exception:pass
        time.sleep(0.5)
    raise RuntimeError('Authenticated candidate health check failed')
def restore_previous():
    if previous.exists():
        if package.exists():
            failed=backup/'candidate-failed'
            assert not failed.exists() and not package.is_symlink()
            package.rename(failed)
            sync_dirs(package.parent,failed.parent)
        previous.rename(package)
        sync_dirs(previous.parent,package.parent)
    assert inventory(package)==OLD
def sync_dirs(*paths):
    for path in set(paths):
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
def rollback():
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    record('rollback-started')
    try:
        if previous.exists():
            stop()
            restore_previous()
        else:
            assert inventory(package)==OLD
        start()
        wait_healthy()
        assert all(active(unit) for unit in units if was[unit]) and watched()==before_watched
        record('rolled-back')
    except BaseException:
        record('rollback-failed')
        raise
def terminated(_signal,_frame):raise RuntimeError('Deployment service asked to stop')
signal.signal(signal.SIGTERM,terminated)
signal.signal(signal.SIGHUP,terminated)
record('prepared')
try:
    stop()
    assert_idle()
    raw_stopped=watched_raw()
    (backup/'protected-stopped.json').write_text(json.dumps({'logical':watched(),'raw':raw_stopped}))
    assert inventory(package)==OLD and watched()==before_watched
    package.rename(previous)
    sync_dirs(package.parent,previous.parent)
    record('previous-retained')
    stage.rename(package)
    sync_dirs(stage.parent,package.parent)
    record('candidate-in-place')
    assert inventory(package)==NEW
    start()
    wait_healthy()
    assert watched()==before_watched
    assert all(active(unit) for unit in units if was[unit])
    record('candidate-service-active')
except BaseException:
    rollback()
    raise
signal.signal(signal.SIGTERM,signal.SIG_IGN)
signal.signal(signal.SIGHUP,signal.SIG_IGN)
result={'programFiles':len(NEW),'rollbackFiles':len(OLD),'servicesRestarted':was,
                  'protectedFileDigestsMatched':len(before_watched),'archiveSha256':EXPECTED['archiveSha256'],
                  'backup':str(backup),'candidateServiceActive':True,'databaseProtection':'logical dump; other protected files byte digest','physicalProtectedFilesChangedAfterStop':sum(raw_stopped.get(k)!=v for k,v in raw_before.items()),'physicalChangeMeaning':'informational only; logical database equality is the protection criterion'}
