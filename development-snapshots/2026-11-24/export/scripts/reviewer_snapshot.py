"""Freeze the supported offline reviewer and run only its verified bytes in a VM container.

The manifest is a content binding, not publisher authentication or an independent seal.
Docker, the VM kernel and this launcher remain part of the execution trust boundary.
"""
import argparse
import ast
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from contextlib import contextmanager
import fcntl
import shutil
import signal
import selectors
import sys
import time
import uuid
import types

FILES = ('eval_evidence_batch.py', 'eval_guard_review.py', 'eval_import_review.py')
STORAGE_FILE = 'reviewer_storage.py'
_STORAGE_MODULES = {}
STORAGE_STDLIB = {'os','re','stat','json','shutil','fcntl','uuid','pathlib','hashlib','datetime','contextlib','tarfile','gzip','io','time','ctypes'}
STDLIB = {'argparse', 'ast', 'hashlib', 'json', 'os', 'pathlib', 're', 'stat', 'sys'}
HASH = re.compile('[a-f0-9]{64}')
IMAGE = re.compile('sha256:[a-f0-9]{64}')
NAME = re.compile(r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}/){0,12}[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\.py')
LIMIT = 2 * 1024 * 1024
# Input contract of the supported three-module reviewer, separate from output/code.
SOURCE_LIMIT = 1024 * 1024
MANIFEST_LIMIT = SOURCE_LIMIT
SCAN_LIMIT = 8 * SOURCE_LIMIT
TOTAL_SOURCE_LIMIT = 8 * SOURCE_LIMIT
ATTEMPT_LIMIT = 8 * LIMIT
JSON_DEPTH_LIMIT = 64
RETENTION_MAX_ENTRIES = 20000
RETENTION_MAX_ATTEMPTS = 1000
RETENTION_MAX_DEPTH = 24
RETENTION_HASH_LIMIT = 64 * 1024 * 1024


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def load_json(raw):
    """Unambiguous UTF-8 JSON; parser resource limits remain part of the boundary."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('non-finite JSON value')
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('non-finite JSON value')
        return result
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid UTF-8 JSON or nesting') from error
    _check_json_depth(result)
    return result


def _check_json_depth(value):
    # An iterator per depth avoids making a second wide copy of parsed input.
    stack = [(iter([value]), 0)]
    while stack:
        iterator, depth = stack[-1]
        try:
            value = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        if isinstance(value, (dict, list)):
            if depth >= JSON_DEPTH_LIMIT:
                raise ValueError('JSON nesting exceeds limit')
            stack.append((iter(value.values() if isinstance(value, dict) else value), depth + 1))


def read(path, limit=LIMIT):
    path = Path(path)
    if path.resolve() != path:
        raise ValueError('linked or noncanonical path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('ordinary file required')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('file exceeds byte limit')
    return raw


def storage_module(expected):
    """Load installed trusted bytes, never executable code supplied by a bundle."""
    path=Path(__file__).resolve().with_name(STORAGE_FILE)
    raw=read(path)
    if not isinstance(expected,str) or not HASH.fullmatch(expected) or sha256(raw).hexdigest()!=expected:
        raise ValueError('installed storage digest mismatch')
    for node in ast.walk(ast.parse(raw,filename=str(path))):
        modules=[alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) else []
        if (isinstance(node,ast.ImportFrom) and node.level or any(name not in STORAGE_STDLIB for name in modules)
                or isinstance(node,ast.Call) and (isinstance(node.func,ast.Name) and node.func.id=='__import__'
                    or isinstance(node.func,ast.Attribute) and node.func.attr=='import_module')):
            raise ValueError('storage import outside supported standard-library closure')
    if expected in _STORAGE_MODULES:return _STORAGE_MODULES[expected]
    module=types.ModuleType('harness_reviewer_storage')
    module.__file__=str(path);module.__source_sha256__=expected
    exec(compile(raw,str(path),'exec'),module.__dict__)
    _STORAGE_MODULES[expected]=module
    return module


def imports(files):
    """Closed supported import surface; new dependencies require explicit review."""
    local = {Path(name).stem for name in FILES}
    for name, raw in files.items():
        tree = ast.parse(raw, filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise ValueError('relative import outside supported closure')
                modules = [node.module]
            else:
                modules = []
            if any(module not in STDLIB | local for module in modules):
                raise ValueError('import outside supported dependency closure')
            if isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name) and node.func.id == '__import__'
                or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module'
            ):
                raise ValueError('dynamic import outside supported dependency closure')


def freeze(sources, destination, image_id):
    if not isinstance(image_id, str) or not IMAGE.fullmatch(image_id):
        raise ValueError('immutable local image ID required')
    sources, destination = Path(sources), Path(destination)
    if sources.resolve() != sources or not sources.is_dir() or destination.parent.resolve() != destination.parent:
        raise ValueError('canonical directories required')
    files = {name: read(sources / name) for name in FILES}
    imports(files)
    storage=read(Path(__file__).resolve().with_name(STORAGE_FILE))
    manifest = {'version': 2, 'kind': 'python-evidence-reviewer', 'entrypoint': FILES[0],
                'files': {name: sha256(raw).hexdigest() for name, raw in files.items()},
                'storageSha256':sha256(storage).hexdigest(),
                'launcherSha256': sha256(read(Path(__file__).resolve())).hexdigest(), 'imageId': image_id}
    destination.mkdir(mode=0o700, exist_ok=False)
    for name, raw in files.items():
        (destination / name).write_bytes(raw)
        (destination / name).chmod(0o600)
    (destination/STORAGE_FILE).write_bytes(storage)
    (destination/STORAGE_FILE).chmod(0o600)
    (destination / 'snapshot.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (destination / 'snapshot.json').chmod(0o600)
    return manifest


def verify(bundle, expected):
    bundle = Path(bundle)
    if bundle.resolve() != bundle or not bundle.is_dir():
        raise ValueError('canonical snapshot directory required')
    contents={p.name for p in bundle.iterdir()}
    if contents==set(FILES)|{'snapshot.json'}:
        legacy=load_json(read(bundle/'snapshot.json'))
        if isinstance(legacy,dict) and type(legacy.get('version')) is int and legacy['version']==1:
            raise ValueError('legacy snapshot is diagnostic-only; recreate version 2')
    if contents != set(FILES) | {'snapshot.json',STORAGE_FILE}:
        raise ValueError('unexpected snapshot contents')
    manifest = load_json(read(bundle / 'snapshot.json'))
    if not isinstance(manifest, dict) or not isinstance(expected, str) or not HASH.fullmatch(expected) or digest(manifest) != expected:
        raise ValueError('snapshot digest mismatch')
    if (set(manifest) != {'version', 'kind', 'entrypoint', 'files', 'launcherSha256', 'storageSha256','imageId'}
            or type(manifest['version']) is not int or manifest['version'] != 2 or manifest['kind'] != 'python-evidence-reviewer'
            or manifest['entrypoint'] != FILES[0] or not isinstance(manifest['files'], dict)
            or set(manifest['files']) != set(FILES) or not isinstance(manifest['imageId'], str)
            or not IMAGE.fullmatch(manifest['imageId'])):
        raise ValueError('invalid snapshot manifest')
    if manifest['launcherSha256'] != sha256(read(Path(__file__).resolve())).hexdigest():
        raise ValueError('launcher digest mismatch')
    installed_storage=read(Path(__file__).resolve().with_name(STORAGE_FILE))
    if (not isinstance(manifest['storageSha256'],str) or not HASH.fullmatch(manifest['storageSha256'])
            or sha256(installed_storage).hexdigest()!=manifest['storageSha256']
            or read(bundle/STORAGE_FILE)!=installed_storage):
        raise ValueError('storage dependency digest mismatch')
    files = {name: read(bundle / name) for name in FILES}
    if any(sha256(raw).hexdigest() != manifest['files'][name] for name, raw in files.items()):
        raise ValueError('reviewer dependency digest mismatch')
    imports(files)
    return manifest, files


def inputs(root, manifest_path, scan_path):
    root = Path(root)
    if root.resolve() != root or not root.is_dir():
        raise ValueError('canonical project directory required')
    manifest_raw = read(manifest_path, MANIFEST_LIMIT)
    manifest = load_json(manifest_raw)
    scan_raw = b'{"results":[]}' if scan_path is None else read(scan_path, SCAN_LIMIT)
    if scan_path is None and isinstance(manifest,dict):
        manifest={'files':manifest.get('files'),'scanSha256':sha256(scan_raw).hexdigest(),**({'locationBinding':manifest['locationBinding']} if 'locationBinding' in manifest else {})}
        manifest_raw=json.dumps(manifest,separators=(',',':')).encode()
    if not isinstance(load_json(scan_raw), dict):
        raise ValueError('invalid scan export')
    if (not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict)
            or not 1 <= len(manifest['files']) <= 64
            or manifest.get('scanSha256') != sha256(scan_raw).hexdigest()):
        raise ValueError('invalid input manifest or scan digest')
    payload = {'manifest.json': manifest_raw, 'scan.json': scan_raw}
    remaining = TOTAL_SOURCE_LIMIT
    for name, expected in manifest['files'].items():
        if not NAME.fullmatch(name) or not isinstance(expected, str) or not HASH.fullmatch(expected):
            raise ValueError('invalid source name or digest')
        raw = read(root / name, min(SOURCE_LIMIT, remaining))
        if sha256(raw).hexdigest() != expected:
            raise ValueError('source digest mismatch')
        raw.decode('utf-8')
        remaining -= len(raw)
        payload['sources/' + name] = raw
    return payload, digest({name: sha256(raw).hexdigest() for name, raw in payload.items()})


def validate_locations(inventory,payload):
    expected={name.removeprefix('sources/'):raw for name,raw in payload.items() if name.startswith('sources/')}
    if (not isinstance(inventory,dict) or type(inventory.get('version')) is not int or inventory['version']!=1
            or inventory.get('protocol')!='python-sink-locations-1' or not isinstance(inventory.get('runtimePython'),str)
            or not re.fullmatch(r'3\.\d{1,3}\.\d{1,3}',inventory['runtimePython'])
            or not isinstance(inventory.get('files'),dict) or set(inventory['files'])!=set(expected)):
        raise ValueError('invalid location inventory')
    for name,raw in expected.items():
        row=inventory['files'][name];source_sha=sha256(raw).hexdigest()
        if (not isinstance(row,dict) or row.get('sha256')!=source_sha or type(row.get('bytes')) is not int or row['bytes']!=len(raw)
                or row.get('state') not in {'completed','unavailable'} or not isinstance(row.get('points'),list) or len(row['points'])>64
                or row['state']=='unavailable' and (row['points'] or row.get('reason') not in {'source-parse-unavailable','point-limit'})):
            raise ValueError('invalid location source row')
        def position(value):
            if not isinstance(value,dict) or set(value)!={'line','col','offset'} or any(type(v) is not int for v in value.values()):return False
            offset=value['offset']
            return (0<=offset<=len(raw) and (offset==len(raw) or raw[offset]&0xc0!=0x80)
                    and value['line']==raw[:offset].count(b'\n')+1 and value['col']==offset-raw.rfind(b'\n',0,offset))
        def span(value):
            return isinstance(value,dict) and set(value)=={'start','end'} and position(value['start']) and position(value['end']) and value['end']['offset']>value['start']['offset']
        ids=set();previous=-1
        for point in row['points']:
            if (not isinstance(point,dict) or point.get('sourceSha256')!=source_sha or point.get('callee') not in {'eval','exec','builtins.eval','builtins.exec'}
                    or point.get('builtinIdentity')!='unverified' or not span(point.get('call'))
                    or point.get('argument') is not None and (not span(point['argument']) or point['argument']['start']['offset']<point['call']['start']['offset'] or point['argument']['end']['offset']>point['call']['end']['offset'])
                    or point.get('id')!=digest({k:point[k] for k in ('sourceSha256','callee','call')}) or point['id'] in ids
                    or point['call']['start']['offset']<previous):
                raise ValueError('invalid execution point')
            ids.add(point['id']);previous=point['call']['start']['offset']
    return inventory


class ReviewAttemptError(RuntimeError):
    """No completed receipt; inspect/recover this exact private attempt."""
    def __init__(self, directory, state):
        self.attempt_directory = str(directory)
        self.status = json.loads(json.dumps(state))
        super().__init__('Review not completed; inspect attempt ' + str(directory))


class ReviewTaskBusy(ValueError):
    code='task-busy'
    retryable=True
    def __init__(self, root):
        self.details={'directory':str(root)}
        super().__init__('attempt still has an active operation')


class _Failure(Exception):
    def __init__(self, kind, **details):
        self.details = {'kind': kind, **details}
        super().__init__(kind)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _private(path):
    path = Path(path)
    value = path.stat()
    if path.resolve() != path or not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or value.st_mode & 0o077:
        raise ValueError('private canonical owned directory required')
    return path


def _save(root, job, cancel=None):
    _check_json_depth(job)
    encoded = (json.dumps(job, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    if len(encoded) > ATTEMPT_LIMIT:
        raise ValueError('attempt record exceeds byte limit')
    temporary = root / ('.attempt-' + uuid.uuid4().hex + '.json')
    try:
        with temporary.open('xb') as stream:
            temporary.chmod(0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if cancel and cancel.get('signal'):
            raise _Failure('interrupted', signal=cancel['signal'])
        temporary.replace(root / 'attempt.json')
        if sys.platform == 'linux':
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def operation_lock(root):
    root = _private(root)
    fd = os.open(root / 'operation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        value = os.fstat(fd)
        if not stat.S_ISREG(value.st_mode) or value.st_uid != os.geteuid() or value.st_mode & 0o077 or value.st_nlink != 1:
            raise ValueError('invalid operation lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReviewTaskBusy(root) from None
        yield
    finally:
        os.close(fd)


@contextmanager
def _interrupts(cancel):
    previous = {}
    def requested(signum, frame):
        cancel['signal'] = int(signum)
    try:
        for signum in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT]:
            previous[signum] = signal.signal(signum, requested)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


# Read only process identity. Never print command lines or signal unrelated PIDs.
_CLIENT_PROBE = r'''import json,os
from pathlib import Path
import sys
marker=sys.argv[1].encode();excluded=set();pid=os.getpid()
while pid>0 and pid not in excluded:
 excluded.add(pid)
 try:pid=int(Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[1])
 except FileNotFoundError:break
active=[];errors=0
for folder in Path('/proc').glob('[0-9]*'):
 try:
  if int(folder.name) in excluded:continue
  raw=(folder/'cmdline').read_bytes()
  if not raw or marker not in raw:continue
  active.append(int(folder.name))
 except (FileNotFoundError,ProcessLookupError):pass
 except OSError:errors+=1
print(json.dumps({'active':active,'readErrors':errors}))
'''


class DockerEngine:
    """Fixed local VM commands; root GNU timeout bounds privileged CLI descendants."""
    def __init__(self, root, job, save, cancel):
        if sys.platform != 'linux' or os.geteuid() == 0:
            raise ValueError('non-root Linux VM controller required')
        self.root, self.job, self.save, self.cancel = root, job, save, cancel
        self.io_failed=False
        self.env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        self.prefix = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', '--config', str(root/'docker-config')]

    def _persist(self, phase, strict=False):
        try:
            self.save()
        except (OSError, ValueError) as error:
            self.io_failed = True
            errors = self.job.setdefault('journalErrors', [])
            errors.append({'phase':phase,'type':type(error).__name__})
            self.job['journalErrorCount'] = self.job.get('journalErrorCount',0)+1
            self.job['journalErrors'] = errors[-32:]
            if strict:
                raise _Failure('journal-write-failed',phase=phase,notStarted=True) from None

    def _client(self, command, seconds, phase, cancellable):
        if cancellable and self.cancel.get('signal'):
            raise _Failure('interrupted',signal=self.cancel['signal'],phase=phase,notStarted=True)
        if cancellable and self.io_failed:
            raise _Failure('journal-write-failed',phase=phase,notStarted=True)
        counter = self.job.get('clientCounter', 0)+1
        self.job['clientCounter'] = counter
        event = {'index':counter,'phase':phase,'startedAt':_now(),'deadlineSeconds':seconds}
        history = self.job.setdefault('clients',[])
        history.append(event)
        if len(history)>128:
            self.job['clientHistoryTruncated']=True
            self.job['clients']=history[-128:]
        if phase=='create':
            self.job['createClient']=event
        paths=[self.root/f'client-{counter}.stdout',self.root/f'client-{counter}.stderr']
        logs=[]
        try:
            self._persist(phase,cancellable)
            for path in paths:
                try:
                    log=path.open('xb');path.chmod(0o600);logs.append(log)
                except OSError as error:
                    self.io_failed=True;logs.append(None)
                    if cancellable:
                        raise _Failure('client-log-failed',phase=phase,notStarted=True) from error
            argv=['/usr/bin/sudo','-n','/usr/bin/timeout','--signal=TERM','--kill-after=2',str(seconds),*command]
            if cancellable and self.cancel.get('signal'):
                raise _Failure('interrupted',signal=self.cancel['signal'],phase=phase,notStarted=True)
            started=time.monotonic()
            try:
                child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                       env=self.env,start_new_session=True,close_fds=True)
            except OSError as error:
                raise _Failure('client-spawn-failed',phase=phase,notStarted=True,errorType=type(error).__name__) from error
            event['pid']=child.pid
            self._persist(phase)
            buffers=[bytearray(),bytearray()];limits=[LIMIT,65536];sent=False;overflow=False
            with selectors.DefaultSelector() as selector:
                for index,pipe in enumerate([child.stdout,child.stderr]):
                    os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,index)
                try:
                    while selector.get_map():
                        stop=(cancellable and self.cancel.get('signal')) or overflow or (cancellable and self.io_failed)
                        if stop and not sent:
                            sent=True
                            try:child.send_signal(signal.SIGTERM)
                            except (PermissionError,ProcessLookupError):pass
                        for key,_ in selector.select(.1):
                            chunk=os.read(key.fileobj.fileno(),65536)
                            if not chunk:
                                selector.unregister(key.fileobj);continue
                            index=key.data;remaining=limits[index]-len(buffers[index]);kept=chunk[:remaining]
                            buffers[index].extend(kept)
                            if len(chunk)>remaining:
                                overflow=True;event['outputLimitExceeded']=True
                            if logs[index] is not None:
                                try:logs[index].write(kept)
                                except OSError:
                                    self.io_failed=True
                                    try:logs[index].close()
                                    except OSError:pass
                                    logs[index]=None
                        if time.monotonic()-started>seconds+5:
                            event['clientExitUnconfirmed']=True
                            self._persist(phase)
                            raise _Failure('client-unconfirmed',phase=phase)
                finally:
                    child.stdout.close();child.stderr.close()
            try:code=child.wait(timeout=2)
            except subprocess.TimeoutExpired:raise _Failure('client-unconfirmed',phase=phase) from None
            # A saved successful create event must have durable CID stdout.
            for log in logs:
                if log is not None:
                    try:log.flush();os.fsync(log.fileno())
                    except OSError:self.io_failed=True
            elapsed=time.monotonic()-started
            event.update(exitCode=code,finishedAt=_now(),elapsedSeconds=round(elapsed,3))
            self._persist(phase)
            if overflow:
                raise _Failure('client-output-limit',phase=phase)
            if cancellable and self.io_failed:
                raise _Failure('journal-write-failed',phase=phase)
            return {'exitCode':code,'stdout':bytes(buffers[0]),'deadlineExceeded':code in [124,137,-9] and elapsed>=seconds}
        except _Failure as error:
            if error.details.get('notStarted'):
                event.update(notStarted=True,notStartedReason=error.details['kind'])
                self._persist(phase)
            raise
        finally:
            for log in logs:
                if log is not None:
                    try:log.close()
                    except OSError:self.io_failed=True

    def invoke(self, args, seconds, phase, cancellable=True):
        return self._client([*self.prefix, *args], seconds, phase, cancellable)

    def clients_stopped(self):
        result = self._client(['/usr/bin/python3', '-I', '-B', '-S', '-c', _CLIENT_PROBE,
                               str(self.root/'docker-config')], 5, 'client-probe', False)
        if result['exitCode']:
            raise ValueError('client probe failed')
        data = json.loads(result['stdout'])
        if not isinstance(data, dict) or data.get('readErrors') != 0 or not isinstance(data.get('active'), list):
            raise ValueError('client probe unconfirmed')
        return not data['active']


_CONTAINER_WATCHDOG = r'''import os,signal,subprocess,sys
class Stopped(Exception):pass
def stop(sig,frame):raise Stopped(sig)
for sig in [signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGQUIT]:signal.signal(sig,stop)
child=None;code=1
try:
 child=subprocess.Popen([sys.executable,'-I','-B','-S',*sys.argv[2:]],stdin=subprocess.DEVNULL,start_new_session=True)
 code=child.wait(timeout=float(sys.argv[1]))
except subprocess.TimeoutExpired:code=124
except Stopped as error:code=128+error.args[0]
finally:
 for sig in [signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGQUIT]:signal.signal(sig,signal.SIG_IGN)
 if child is not None:
  try:os.killpg(child.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  try:child.wait(timeout=2)
  except subprocess.TimeoutExpired:pass
os._exit(code if code>=0 else 128-code)
'''

_LABEL = 'io.deepseek.harness.review.'


def _labels(job):
    return {_LABEL+'attempt': job['id'], _LABEL+'snapshot': job['snapshotSha256'], _LABEL+'input': job['inputSha256']}


def _find(engine, job, cid=None):
    token = 'id='+cid if cid else 'name=^/'+job['name']+'$'
    result = engine.invoke(['container','ls','--all','--quiet','--no-trunc','--filter',token], 6, 'lookup', False)
    if result['exitCode']:
        raise ValueError('container lookup failed')
    rows = result['stdout'].decode('ascii').splitlines()
    if not rows:
        return None
    if len(rows) != 1 or not HASH.fullmatch(rows[0]) or cid and rows[0] != cid:
        raise ValueError('container lookup ambiguous')
    return rows[0]


def _owned(engine, job, cid):
    result = engine.invoke(['container','inspect',cid], 6, 'inspect', False)
    if result['exitCode']:
        raise _Failure('container-identity')
    data = json.loads(result['stdout'])
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise _Failure('container-identity')
    value = data[0]
    labels = value.get('Config', {}).get('Labels') or {}
    if (value.get('Id') != cid or value.get('Name') != '/'+job['name'] or value.get('Image') != job['imageId']
            or any(labels.get(key) != expected for key, expected in _labels(job).items())
            or job.get('containerId') is not None and job['containerId'] != cid):
        raise _Failure('container-identity')
    job['containerId'] = cid
    job['containerObserved'] = True
    return value


def _cleanup(engine, job):
    result = {'confirmed':False, 'idAbsent':False, 'nameAbsent':False, 'clientsStopped':False,
              'creationResolved':False, 'errors':[], 'checkedAt':_now()}
    try:
        result['clientsInitiallyStopped'] = engine.clients_stopped()
        cid = _find(engine, job)
        if cid is None and job.get('containerId'):
            cid = _find(engine, job, job['containerId'])
        if cid is not None:
            _owned(engine, job, cid)
            removed = engine.invoke(['rm','-f',cid], 8, 'remove', False)
            if removed['exitCode']:
                result['errors'].append('remove-client-failed')
        cid = job.get('containerId')
        result['idAbsent'] = cid is None or _find(engine, job, cid) is None
        result['nameAbsent'] = _find(engine, job) is None
        result['clientsStopped'] = engine.clients_stopped()
        result['creationResolved'] = bool(job.get('createSucceeded') or job.get('containerObserved') or not job['creationAttempted'])
    except Exception as error:
        result['errors'].append(error.details['kind'] if isinstance(error, _Failure) else type(error).__name__)
    if getattr(engine,'io_failed',False):result['errors'].append('journal-or-log-write-failed')
    result['confirmed'] = all(result[key] for key in ['idAbsent','nameAbsent','clientsStopped','creationResolved']) and not result['errors']
    return result


@contextmanager
def _failure_guard(root,job,holder,recovery=False):
    try:
        yield
    except ReviewAttemptError:
        raise
    except Exception as error:
        if job.get('state')=='completed':
            memory=dict(job);memory.pop('result',None);memory.pop('resultSha256',None)
            memory.update(state='completion-unconfirmed',failure={'kind':'completion-commit-unconfirmed','type':type(error).__name__})
            raise ReviewAttemptError(root,memory) from error
        job.setdefault('failure',{'kind':'journal-write-failed' if isinstance(error,OSError) else 'controller-error','type':type(error).__name__})
        _restore_create_evidence(root,job)
        engine=holder.get('engine')
        job['cleanup']=_cleanup(engine,job) if engine is not None else {'confirmed':not job['creationAttempted'],'errors':[],'noClientStarted':True}
        job['state']='cleanup-unconfirmed' if recovery or not job['cleanup']['confirmed'] else 'failed'
        job['finishedAt']=_now()
        try:_save(root,job)
        except (OSError,ValueError):job['lastJournalSaveFailed']=True
        raise ReviewAttemptError(root,job) from error


def _restore_create_evidence(root,job):
    event=job.get('createClient')
    try:
        cid_file_absent=not (root/'container.cid').exists() and not (root/'container.cid').is_symlink()
    except OSError:
        cid_file_absent=False
    if (job.get('creationJournalVersion')==1 and type(job.get('creationJournalVersion')) is int
            and job['creationAttempted'] and not job['createSucceeded']
            and not job['containerObserved'] and job.get('containerId') is None and cid_file_absent):
        history=job.get('clients',[])
        basis=None
        if isinstance(history,list) and all(isinstance(row,dict) for row in history):
            creates=[row for row in history if row.get('phase')=='create']
            if 'createClient' not in job and not creates:
                basis='no-durable-create-event'
            elif (isinstance(event,dict) and event.get('phase')=='create'
                    and type(event.get('index')) is int and event['index']>0
                    and event.get('notStarted') is True and 'pid' not in event and 'exitCode' not in event
                    and isinstance(event.get('notStartedReason'),str)
                    and event.get('notStartedReason') in {'client-spawn-failed','client-log-failed','journal-write-failed','interrupted'}
                    and all(row==event for row in creates)):
                basis='explicit-unstarted-create-event'
        if basis:
            job['creationAttempted']=False
            job.setdefault('creationNotStarted',{'basis':basis,'checkedAt':_now()})
    if job['createSucceeded'] or not isinstance(event,dict) or event.get('exitCode')!=0:return
    index=event.get('index')
    if type(index) is not int or index<1:return
    try:cid=read(root/f'client-{index}.stdout',256).decode('ascii').strip()
    except (OSError,ValueError):return
    if HASH.fullmatch(cid) and job.get('containerId') in [None,cid]:
        job.update(containerId=cid,createSucceeded=True,createEvidenceRestored=True)


def _load_attempt(directory):
    root = _private(directory)
    job = load_json(read(root/'attempt.json', ATTEMPT_LIMIT))
    _validate_attempt(root, job)
    _private(root/'docker-config')
    return root, job


def _validate_attempt(root, job):
    if (not re.fullmatch(r'review-[0-9a-f]{32}', root.name) or not isinstance(job, dict)
            or type(job.get('version')) is not int or job['version'] != 1 or job.get('id') != root.name.removeprefix('review-')
            or job.get('directory')!=str(root)
            or job.get('state') not in {'prepared','creating','waiting','cleaning','completed','failed','timed-out','interrupted','cleanup-unconfirmed','recovering','recovered'}
            or job.get('name') != 'harness-review-'+job['id'] or not isinstance(job.get('imageId'),str) or not IMAGE.fullmatch(job['imageId'])
            or any(not isinstance(job.get(key), str) or not HASH.fullmatch(job[key]) for key in
                   ['snapshotSha256','inputSha256','datasetSha256','freezeSha256'])
            or job.get('containerId') is not None and (not isinstance(job['containerId'],str) or not HASH.fullmatch(job['containerId']))
            or 'creationJournalVersion' in job and (type(job['creationJournalVersion']) is not int or job['creationJournalVersion']!=1)
            or any(type(job.get(key)) is not bool for key in ['creationAttempted','createSucceeded','containerObserved'])):
        raise ValueError('invalid owned attempt record')
    if job.get('state') == 'completed':
        result = job.get('result')
        if (not isinstance(result,dict) or digest(result)!=job.get('resultSha256')
                or result.get('attemptDirectory')!=str(root)
                or not isinstance(result.get('reviewerExecution'),dict) or result['reviewerExecution'].get('state')!='completed'):
            raise ValueError('committed result integrity mismatch')


def status(directory):
    if not Path(directory).exists():return _archived_status(directory)
    _, job = _load_attempt(directory)
    return {**job, 'recordedOnly':True}


def _archived_status(directory):
    directory=Path(directory)
    if directory.resolve()!=directory:raise ValueError('canonical attempt path required')
    storage=storage_module(sha256(read(Path(__file__).resolve().with_name(STORAGE_FILE))).hexdigest())
    return storage.archived_lookup(storage.existing_policy(directory.parent),directory)


def _retention_names(fd, maximum):
    names=[]
    with os.scandir(fd) as iterator:
        for entry in iterator:
            if len(names)>=maximum:return sorted(names),True
            names.append(entry.name)
    return sorted(names),False


def _retention_signature(value):
    return (value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink,value.st_size,value.st_mtime_ns)


def _retention_tree(fd, context, files, raw_records, reasons, hashing, prefix='', depth=0):
    """Metadata-only traversal except bounded known artifacts; no linked descent."""
    before=os.fstat(fd)
    names,truncated=_retention_names(fd,max(0,RETENTION_MAX_ENTRIES-context['entries']))
    context['entries']+=len(names)
    if truncated:
        context['complete']=False;reasons.add('enumeration-limit')
    for name in names:
        relative=prefix+name
        try:
            value=os.stat(name,dir_fd=fd,follow_symlinks=False)
            item={'bytes':value.st_size,'mode':stat.S_IMODE(value.st_mode),'uid':value.st_uid,
                  'device':value.st_dev,'inode':value.st_ino,'mtimeNs':value.st_mtime_ns}
            files[relative]=item
            if stat.S_ISDIR(value.st_mode):
                item['type']='directory'
                if value.st_uid!=os.geteuid() or value.st_dev!=before.st_dev:
                    context['complete']=False;reasons.add('unsafe-entry');continue
                if relative not in {'docker-config','stage'} and not relative.startswith('stage/'):
                    reasons.add('unsafe-entry')
                if depth>=RETENTION_MAX_DEPTH:
                    context['complete']=False;reasons.add('enumeration-limit');continue
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    if _retention_signature(os.fstat(child))!=_retention_signature(value):
                        context['complete']=False;reasons.add('changed-entry');continue
                    _retention_tree(child,context,files,raw_records,reasons,hashing,relative+'/',depth+1)
                finally:os.close(child)
            elif stat.S_ISREG(value.st_mode):
                item['type']='file';context['bytes']+=value.st_size
                known=(relative in {'attempt.json','operation.lock','container.cid'}
                       or re.fullmatch(r'client-[1-9][0-9]*\.(stdout|stderr)',relative))
                if not known and not relative.startswith('stage/'):
                    reasons.add('unsafe-entry')
                if value.st_nlink!=1 or value.st_uid!=os.geteuid():
                    reasons.add('unsafe-entry');continue
                if not hashing or not known:continue
                if value.st_mode&0o077:
                    reasons.add('unsafe-entry');continue
                limit=ATTEMPT_LIMIT if relative=='attempt.json' else LIMIT if relative.endswith('.stdout') else 65536 if relative.endswith('.stderr') else 256
                if value.st_size>limit:
                    reasons.add('oversized-file');continue
                if value.st_size>RETENTION_HASH_LIMIT-context['hashed']:
                    reasons.add('hash-budget');continue
                leaf=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    start=os.fstat(leaf)
                    if not stat.S_ISREG(start.st_mode) or _retention_signature(start)!=_retention_signature(value):
                        context['complete']=False;reasons.add('changed-entry');continue
                    chunks=[];hasher=sha256();length=0
                    while length<value.st_size:
                        chunk=os.read(leaf,min(65536,value.st_size-length))
                        if not chunk:break
                        length+=len(chunk);context['hashed']+=len(chunk);hasher.update(chunk)
                        if relative=='attempt.json':chunks.append(chunk)
                    if length!=value.st_size or _retention_signature(os.fstat(leaf))!=_retention_signature(start):
                        context['complete']=False;reasons.add('changed-entry');continue
                    item['sha256']=hasher.hexdigest()
                    if relative=='attempt.json':raw_records['attempt.json']=b''.join(chunks)
                finally:os.close(leaf)
            else:
                item['type']='link' if stat.S_ISLNK(value.st_mode) else 'special'
                context['complete']=False;reasons.add('unsafe-entry')
        except OSError:
            context['complete']=False;reasons.add('unreadable-entry')
    after_names,extra=_retention_names(fd,len(names)+1)
    if extra or names!=after_names or _retention_signature(os.fstat(fd))!=_retention_signature(before):
        context['complete']=False;reasons.add('changed-entry')


def _retention_entry(parent_fd, name, base, context, now, minimum_age_days):
    row={'directory':str(base/name),'classification':'retain','safeToDelete':False,
         'requires':['fresh-resource-check','archive-verification'],'files':{}}
    reasons=set();fd=None;lock=None
    try:
        if not re.fullmatch(r'review-[0-9a-f]{32}',name):
            reasons.add('unexpected-entry');context['complete']=False;return row
        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent_fd)
        value=os.fstat(fd)
        if value.st_uid!=os.geteuid() or value.st_mode&0o077 or value.st_dev!=os.fstat(parent_fd).st_dev:
            reasons.add('unsafe-entry');context['complete']=False;return row
        hashing=False
        try:
            # A first execution creates its record only after taking EX. Avoid
            # competing with that initial lock acquisition while no record exists.
            record_info=os.stat('attempt.json',dir_fd=fd,follow_symlinks=False)
            if not stat.S_ISREG(record_info.st_mode):raise FileNotFoundError('ordinary record not available')
            lock=os.open('operation.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            info=os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_nlink!=1:
                reasons.add('unsafe-entry')
            else:
                fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB);hashing=True
        except FileNotFoundError:
            try:available=os.stat('attempt.json',dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:reasons.add('record-unavailable')
            else:reasons.add('missing-lock' if stat.S_ISREG(available.st_mode) else 'record-unavailable')
        except BlockingIOError:reasons.add('active-operation');context['complete']=False
        except OSError:reasons.add('unsafe-entry')
        raw_records={}
        _retention_tree(fd,context,row['files'],raw_records,reasons,hashing)
        if hashing:
            lock_now=row['files'].get('operation.lock',{})
            if (_retention_signature(os.fstat(lock))!=_retention_signature(info)
                    or (lock_now.get('device'),lock_now.get('inode'))!=(info.st_dev,info.st_ino)):
                context['complete']=False;reasons.add('changed-lock')
        if 'stage' in row['files']:reasons.add('stage-present')
        config=row['files'].get('docker-config',{})
        if config.get('type')!='directory' or config.get('uid')!=os.geteuid() or config.get('mode',0o777)&0o077:
            reasons.add('unsafe-entry')
        raw=raw_records.get('attempt.json')
        if raw is None:
            reasons.add('record-unavailable')
        else:
            row['recordSha256']=sha256(raw).hexdigest()
            try:
                job=load_json(raw);_validate_attempt(base/name,job);row['state']=job['state']
                if job['state'] not in {'completed','recovered'}:reasons.add('nonterminal-record')
                if job['state']=='recovered' and ('result' in job or 'resultSha256' in job):reasons.add('invalid-record')
                cleanup=job.get('cleanup',{})
                if (not isinstance(cleanup,dict) or any(cleanup.get(k) is not True for k in
                      ['confirmed','idAbsent','nameAbsent','clientsStopped','creationResolved']) or cleanup.get('errors')!=[]
                      or job.get('stageRemoved') is not True):reasons.add('unconfirmed-cleanup')
                try:
                    finished=datetime.fromisoformat(job['finishedAt'])
                    if finished.tzinfo is None or finished>now:raise ValueError('invalid completion time')
                    if (now-finished).total_seconds()<minimum_age_days*86400:reasons.add('minimum-age')
                    row['finishedAt']=job['finishedAt']
                except (KeyError,TypeError,ValueError):reasons.add('invalid-time')
            except (ValueError,TypeError,KeyError):reasons.add('invalid-record')
        current=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
        if (current.st_dev,current.st_ino)!=(value.st_dev,value.st_ino):
            context['complete']=False;reasons.add('changed-entry')
        if not reasons:row['classification']='archive-candidate'
        return row
    except OSError:
        context['complete']=False;reasons.add('unreadable-entry');return row
    finally:
        row['reasons']=sorted(reasons)
        if lock is not None:os.close(lock)
        if fd is not None:os.close(fd)


def retention_inventory(directory=None, *, budget_bytes=256*1024*1024, minimum_age_days=30, now=None):
    """Read-only archive preview, never a live resource check or deletion permit."""
    if type(budget_bytes) is not int or budget_bytes<=0 or type(minimum_age_days) is not int or not 0<=minimum_age_days<=3650:
        raise ValueError('invalid retention policy')
    now=datetime.now(timezone.utc) if now is None else now
    if not isinstance(now,datetime) or now.tzinfo is None:raise ValueError('timezone-aware inventory time required')
    base=Path(directory) if directory is not None else Path.home()/'.cache/harness-review-attempts'
    if base.resolve()!=base:raise ValueError('canonical retention directory required')
    context={'entries':0,'bytes':0,'hashed':0,'complete':True};rows=[];exists=False
    try:fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:fd=None
    if fd is not None:
        exists=True
        try:
            before=os.fstat(fd)
            if before.st_uid!=os.geteuid() or before.st_mode&0o077:raise ValueError('private owned retention directory required')
            names,truncated=_retention_names(fd,min(RETENTION_MAX_ATTEMPTS,RETENTION_MAX_ENTRIES));context['entries']+=len(names)
            if truncated:context['complete']=False
            for name in names:rows.append(_retention_entry(fd,name,base,context,now,minimum_age_days))
            after_names,extra=_retention_names(fd,len(names)+1)
            try:visible=os.stat(base,follow_symlinks=False)
            except OSError:visible=None
            if (extra or after_names!=names or _retention_signature(os.fstat(fd))!=_retention_signature(before)
                    or visible is None or (visible.st_dev,visible.st_ino)!=(before.st_dev,before.st_ino)):
                context['complete']=False
        finally:os.close(fd)
    if not context['complete']:
        for row in rows:
            row['classification']='retain';row['reasons']=sorted(set(row['reasons'])|{'inventory-incomplete'})
    result={'version':1,'directory':str(base),'directoryExists':exists,'generatedAt':now.isoformat(),
            'readOnly':True,'deleteEnabled':False,'resourceVerification':'recorded-only',
            'policy':{'minimumAgeDays':minimum_age_days,'budgetBytes':budget_bytes},
            'capacity':{'knownLogicalBytes':context['bytes'],'complete':context['complete'],'budgetBytes':budget_bytes,
                        'state':'exceeded' if context['bytes']>budget_bytes else 'within' if context['complete'] else 'unknown'},
            'hashedBytes':context['hashed'],'entries':rows}
    return {**result,'planSha256':digest(result)}


def _discard_stage(root):
    stage = root/'stage'
    if stage.exists() or stage.is_symlink():
        _private(stage)
        shutil.rmtree(stage)
    return not stage.exists()


def recover(directory, *, _engine_factory=None):
    if not Path(directory).exists():return _archived_status(directory)
    value=_recover_core(directory,_engine_factory=_engine_factory)
    _settle_storage(Path(directory))
    return value


def _settle_storage(directory):
    try:
        storage=storage_module(sha256(read(Path(__file__).resolve().with_name(STORAGE_FILE))).hexdigest())
        if not storage.settle(storage.existing_policy(directory.parent),directory.name.removeprefix('review-'),_api_view()):
            print('storage-settlement-pending; query status and storage-reconcile before retrying',file=sys.stderr)
    except (Exception,KeyboardInterrupt):
        # The analysis record is authoritative. A retained reservation is
        # conservative and can be reconciled later; never replay analysis here.
        print('storage-settlement-pending; query status and storage-reconcile before retrying',file=sys.stderr)


def _api_view():
    return types.SimpleNamespace(__file__=__file__,_load_attempt=_load_attempt,_validate_attempt=_validate_attempt,
                                 load_json=load_json,archive_probe=_archive_probe)


def _archive_probe(transaction,source,job):
    """Fresh read-only VM queries. No cleanup or source journal mutation."""
    _private(transaction);(transaction/'docker-config').mkdir(mode=0o700)
    query={'clientCounter':0,'clients':[]}
    engine=DockerEngine(transaction,query,lambda:_save(transaction,query),{})
    def absent(args):
        result=engine.invoke(['container','ls','--all','--quiet','--no-trunc','--filter',args],6,'archive-lookup',False)
        return result['exitCode']==0 and result['stdout']==b''
    container_absent=absent('name=^/'+job['name']+'$')
    if job.get('containerId'):container_absent=absent('id='+job['containerId']) and container_absent
    container_absent=absent('label='+_LABEL+'attempt='+job['id']) and container_absent
    result=engine._client(['/usr/bin/python3','-I','-B','-S','-c',_CLIENT_PROBE,str(source/'docker-config')],5,'archive-client-probe',False)
    clients=load_json(result['stdout']) if result['exitCode']==0 else {}
    stopped=isinstance(clients,dict) and clients.get('readErrors')==0 and clients.get('active')==[]
    confirmed=container_absent and stopped and not engine.io_failed
    return {'confirmed':confirmed,'readOnly':True,'containerAbsent':container_absent,'clientsStopped':stopped,
            'checkedAt':_now(),'queryDirectory':str(transaction),'logSha256':{p.name:sha256(read(p)).hexdigest() for p in transaction.iterdir() if p.is_file()}}


def _recover_core(directory, *, _engine_factory=None):
    root, _ = _load_attempt(directory)
    cancel = {}
    with operation_lock(root), _interrupts(cancel):
        _, job = _load_attempt(root)
        holder={}
        with _failure_guard(root,job,holder,True):
            return _recover_locked(root,job,cancel,holder,_engine_factory)


def _recover_locked(root,job,cancel,holder,_engine_factory):
        if job.get('state') == 'completed':
            return {**job, 'recordedOnly':True, 'recoveryAction':'already-completed-no-new-receipt'}
        _restore_create_evidence(root,job)
        engine = holder['engine'] = (_engine_factory or DockerEngine)(root, job, lambda:_save(root,job), cancel)
        job.setdefault('originalState', job['state'])
        job['state'] = 'recovering'
        _save(root, job)
        job['cleanup'] = _cleanup(engine, job)
        if job['cleanup']['confirmed']:
            try:
                job['stageRemoved'] = _discard_stage(root)
                job['state'] = 'recovered'
            except (OSError,ValueError) as error:
                job['cleanup']['confirmed'] = False
                job['cleanup']['errors'].append('stage-removal-'+type(error).__name__)
                job['state'] = 'cleanup-unconfirmed'
        else:
            job['state'] = 'cleanup-unconfirmed'
        job['finishedAt'] = _now()
        if cancel:
            job['recoverySignal'] = cancel['signal']
        _save(root, job)
        return job


def verifier_module():
    # Fixed shipped tool module only; bundle/project never selects executable host code.
    import importlib.util
    path=Path(__file__).resolve().with_name('verifier_snapshot.py')
    spec=importlib.util.spec_from_file_location('trusted_verifier_snapshot',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def verify_execution(bundle,expected,root,manifest_path,scan_path,request_path,dataset_sha,freeze_sha,**kwargs):
    return execute(bundle,expected,root,manifest_path,scan_path,dataset_sha,freeze_sha,_operation='verify-execution',_request_path=request_path,**kwargs)


def execute(bundle, expected, root, manifest_path, scan_path, dataset_sha, freeze_sha, *,
            attempts_root=None, timeout=30, _engine_factory=None, storage_policy=None, _operation='review', _request_path=None):
    if _operation not in {'review','locations','verify-execution'}:raise ValueError('unsupported operation')
    if _operation in {'review','verify-execution'} and scan_path is None:raise ValueError('review requires original scan file')
    if _engine_factory is None and sys.platform != 'linux':
        raise ValueError('VM execution requires Linux; no Mac Docker invocation')
    if os.geteuid() == 0 or isinstance(timeout, bool) or not isinstance(timeout, (float,int)) or not .1 <= timeout <= 30:
        raise ValueError('non-root controller and bounded timeout required')
    if not all(isinstance(value, str) and HASH.fullmatch(value) for value in [dataset_sha, freeze_sha]):
        raise ValueError('dataset and quality freeze digests required')
    base = Path(attempts_root) if attempts_root is not None else Path.home()/'.cache/harness-review-attempts'
    if base.resolve() != base or not re.fullmatch(r'[A-Za-z0-9/_.-]+', str(base)):
        raise ValueError('canonical mount-safe attempts directory required')
    if _operation=='verify-execution':
        vm=verifier_module();manifest,verifier_files=vm.verify(bundle,expected)
        files={n.removeprefix('code/'):v for n,v in verifier_files.items() if n.startswith('code/')}
    else:manifest,files=verify(bundle,expected)
    payload,input_sha=inputs(root,manifest_path,scan_path)
    if _operation=='verify-execution':
        raw=read(_request_path,262144);request=load_json(raw);source_manifest=load_json(payload['manifest.json'])
        if not isinstance(request,dict) or set(request)!={'version','contract','point','challenge'} or request['version']!=1 or not isinstance(request['challenge'],str) or not HASH.fullmatch(request['challenge']):raise ValueError('Invalid verification request')
        vm.contract(request['contract'])
        if digest(request['contract']) not in manifest['recipes'] or manifest['recipes'][digest(request['contract'])]!=request['contract']:raise ValueError('Unfrozen verification recipe')
        binding=source_manifest.get('locationBinding')
        if not isinstance(binding,dict) or binding.get('snapshotSha256')!=manifest['staticSha256'] or binding.get('imageId')!=manifest['imageId'] or binding.get('uid')!=os.geteuid():raise ValueError('Location runtime mismatch')
        validate_locations(binding.get('inventory'),payload)
        row=binding['inventory']['files'].get(request['contract']['path'])
        if row is None or request['point'] not in row['points']:raise ValueError('Unknown frozen point')
        payload.update({n:v for n,v in verifier_files.items() if n.startswith('dependencies/')})
        payload['verification-request.json']=raw
        payload['verification.json']=json.dumps({**request,'manifest':source_manifest},separators=(',',':')).encode()
        input_sha=digest({n:sha256(v).hexdigest() for n,v in payload.items()})
    storage=storage_module(manifest['storageSha256'])
    policy=storage.existing_policy(base) if storage_policy is None else storage.validate_policy(storage_policy)
    if policy['cacheRoot']!=str(base):raise ValueError('storage policy cache mismatch')
    attempt_id=uuid.uuid4().hex
    reservation=storage.reserve(policy,attempt_id,sum(map(len,files.values()))+sum(map(len,payload.values())),_api_view())
    phase={'enginePossible':False}
    try:
        return _execute_verified(base,attempt_id,manifest,files,payload,input_sha,expected,dataset_sha,freeze_sha,timeout,_engine_factory,reservation,phase,_operation)
    finally:
        try:
            directory=base/('review-'+attempt_id)
            if not phase['enginePossible'] and not (directory/'attempt.json').exists() and not (directory/'container.cid').exists():
                storage.cancel_preparation(policy,attempt_id)
            elif not storage.settle(policy,attempt_id,_api_view()):
                print('storage-settlement-pending; query status and storage-reconcile before retrying',file=sys.stderr)
        except (Exception,KeyboardInterrupt):
            print('storage-settlement-pending; query status and storage-reconcile before retrying',file=sys.stderr)


def _execute_verified(base,attempt_id,manifest,files,payload,input_sha,expected,dataset_sha,freeze_sha,timeout,_engine_factory,reservation,phase,operation):
    base.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    base.mkdir(mode=0o700, exist_ok=True)
    _private(base)
    attempt = base/('review-'+attempt_id)
    attempt.mkdir(mode=0o700)
    (attempt/'docker-config').mkdir(mode=0o700)
    stage = attempt/'stage'
    stage.mkdir(mode=0o700)
    for relative, raw in {**{'code/'+key:value for key,value in files.items()}, **payload}.items():
        path = stage/relative
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        path.write_bytes(raw);path.chmod(0o444)
    job = {'version':1, 'directory':str(attempt), 'id':attempt_id, 'name':'harness-review-'+attempt_id, 'state':'prepared',
           'snapshotSha256':expected, 'inputSha256':input_sha, 'imageId':manifest['imageId'],
           'datasetSha256':dataset_sha, 'freezeSha256':freeze_sha, 'startedAt':_now(),
           'creationAttempted':False, 'createSucceeded':False, 'containerObserved':False, 'containerId':None,
           'creationJournalVersion':1,'storageReservation':reservation,'operation':operation}
    failure = None
    cancel = {}
    holder={}
    with operation_lock(attempt), _interrupts(cancel), _failure_guard(attempt,job,holder):
        _save(attempt, job)
        phase['enginePossible']=True
        engine = holder['engine'] = (_engine_factory or DockerEngine)(attempt, job, lambda:_save(attempt,job), cancel)
        command = ['create','--pull','never','--name',job['name'],'--cidfile',str(attempt/'container.cid')]
        for key,value in _labels(job).items():
            command += ['--label',key+'='+value]
        command += ['--network','none','--read-only','--user',f'{os.geteuid()}:{os.getegid()}',
                    '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m',
                    '--memory-swap','256m','--cpus','1','--pids-limit','32','--log-driver','none',
                    '--no-healthcheck','--workdir','/','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777',
                    '--mount',f'type=bind,src={stage},dst=/review,readonly','--entrypoint','python3',
                    manifest['imageId'],'-I','-B','-S','-c',_CONTAINER_WATCHDOG,str(timeout),'/review/code/'+FILES[0],
                    *(['--locations'] if operation=='locations' else []),'/review/sources','/review/manifest.json','/review/scan.json']
        if operation=='verify-execution':
            for flag,value in [('--memory','512m'),('--memory-swap','512m'),('--pids-limit','64'),('--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777')]:command[command.index(flag)+1]=value
            marker=command.index('/review/code/'+FILES[0]);command[marker:]=['/review/code/python_execution_verify.py','/review']
        try:
            if cancel:
                raise _Failure('interrupted', signal=cancel['signal'])
            job.update(state='creating', creationAttempted=True)
            _save(attempt, job)
            created = engine.invoke(command, timeout, 'create')
            if cancel:
                raise _Failure('interrupted', signal=cancel['signal'])
            if created['exitCode']:
                raise _Failure('timed-out' if created['deadlineExceeded'] else 'create-failed', exitCode=created['exitCode'])
            cid = created['stdout'].decode('ascii').strip()
            if not HASH.fullmatch(cid):
                raise _Failure('container-identity')
            job.update(containerId=cid, createSucceeded=True)
            _owned(engine, job, cid)
            if cancel:raise _Failure('interrupted',signal=cancel['signal'])
            job['state'] = 'waiting'
            _save(attempt, job)
            if cancel:raise _Failure('interrupted',signal=cancel['signal'])
            run = engine.invoke(['start','--attach',cid], timeout, 'start')
            if cancel:
                raise _Failure('interrupted', signal=cancel['signal'])
            if run['exitCode']:
                raise _Failure('timed-out' if run['deadlineExceeded'] else 'reviewer-failed', exitCode=run['exitCode'])
            raw = run['stdout']
            try:
                report = load_json(raw)
                if not isinstance(report, dict) or type(report.get('version')) is not int or report['version'] not in [1,2]:
                    raise ValueError('invalid report')
                location_binding=None
                if operation=='verify-execution':
                    request=load_json(payload['verification-request.json'])
                    if (len(raw)>262144 or report['version']!=1 or report.get('operation')!='verify-execution'
                        or report.get('decision') not in {'confirmed','excluded','unknown'} or report.get('pointId')!=request['point']['id']
                        or report.get('sourceSha256')!=request['point']['sourceSha256'] or report.get('point')!=request['point']
                        or report.get('contractSha256')!=digest(request['contract']) or report.get('runtimePython')!=manifest['pythonVersion']
                        or report.get('challengeSha256')!=sha256(request['challenge'].encode()).hexdigest() or not isinstance(report.get('runs'),list) or len(report['runs'])>4):raise ValueError('Invalid verification report')
                elif report['version']==2:
                    inventory=report.get('locations')
                    validate_locations(inventory,payload)
                    if report.get('operation','review')!=operation:raise ValueError('operation mismatch')
                    location_binding={'version':1,'snapshotSha256':expected,'imageId':manifest['imageId'],'uid':os.geteuid(),'inventory':inventory}
                    frozen_binding=load_json(payload['manifest.json']).get('locationBinding')
                    if frozen_binding is not None and frozen_binding!=location_binding:
                        raise _Failure('location-binding-changed',nextOperation='refreeze')
                elif operation=='locations':raise ValueError('location report required')
            except (ValueError, UnicodeError):
                raise _Failure('report-invalid') from None
        except BaseException as error:
            failure = error.details if isinstance(error,_Failure) else {'kind':'controller-error','type':type(error).__name__}
            _restore_create_evidence(attempt,job)
        job['state'] = 'cleaning'
        if failure is not None:
            job['failure'] = failure
        _save(attempt, job)
        job['cleanup'] = _cleanup(engine, job)
        if cancel and failure is None:
            failure = job['failure'] = {'kind':'interrupted','signal':cancel['signal']}
        if not job['cleanup']['confirmed'] and failure is None:
            failure = job['failure'] = {'kind':'cleanup-failed'}
        if failure is None:
            try:
                job['stageRemoved'] = _discard_stage(attempt)
            except (OSError,ValueError) as error:
                failure = job['failure'] = {'kind':'stage-cleanup-failed','type':type(error).__name__}
                job['cleanup']['confirmed'] = False
                job['cleanup']['errors'].append('stage-removal-failed')
        if cancel and failure is None:
            failure = job['failure'] = {'kind':'interrupted','signal':cancel['signal']}
        if failure is not None:
            job['state'] = ('interrupted' if failure['kind']=='interrupted' else 'timed-out' if failure['kind']=='timed-out' else 'failed') if job['cleanup']['confirmed'] else 'cleanup-unconfirmed'
            job['finishedAt'] = _now()
            _save(attempt, job)
        else:
            input_files = {name:sha256(value).hexdigest() for name,value in payload.items()}
            receipt = {'version':2,'state':'completed','snapshotSha256':expected,'datasetSha256':dataset_sha,
                       'freezeSha256':freeze_sha,'inputSha256':input_sha,'inputFiles':dict(input_files),
                       'scanSha256':input_files['scan.json'],'reportSha256':sha256(raw).hexdigest(),
                       'startedAt':job['startedAt'],'finishedAt':_now()}
            if location_binding is not None:
                receipt.update(version=3,operation=operation,locationBindingSha256=digest(location_binding))
            result = {'reviewerSnapshot':manifest,'reviewerExecution':receipt,'report':report,'reportJson':raw.decode('utf-8'),
                      'inputFiles':input_files,'temporaryRemoved':job['stageRemoved'],'cleanup':job['cleanup'],
                      'attemptDirectory':str(attempt),**({'locationBinding':location_binding} if location_binding is not None else {})}
            if location_binding is not None and operation=='review':
                result['reviewArtifact']={'locationBinding':location_binding,'reportJson':raw.decode('utf-8'),
                    'scanJson':payload['scan.json'].decode('utf-8'),'manifestJson':payload['manifest.json'].decode('utf-8')}
            if operation=='verify-execution':
                receipt.update(version=1,operation=operation,verifierSha256=expected,requestSha256=input_files['verification-request.json'],policySha256=digest(manifest['policy']),uid=os.geteuid(),cleanupVerified=True)
                result['verificationExecution']=dict(receipt)
                result['verificationArtifact']={'reportJson':raw.decode(),'requestJson':payload['verification-request.json'].decode(),'manifestJson':payload['manifest.json'].decode(),'scanJson':payload['scan.json'].decode()}
            # State and original result commit in one atomic record, not two files.
            job.update(state='completed', finishedAt=receipt['finishedAt'], resultSha256=digest(result), result=result)
            try:
                _save(attempt, job, cancel)
            except _Failure as error:
                job.pop('result',None);job.pop('resultSha256',None)
                failure=job['failure']=error.details
                job.update(state='interrupted',finishedAt=_now())
                _save(attempt,job)
            except ValueError as error:
                # Encoding/size is checked before opening a temporary record.
                job.pop('result',None);job.pop('resultSha256',None)
                failure=job['failure']={'kind':'completion-record-invalid','type':type(error).__name__}
                job.update(state='failed',finishedAt=_now())
                _save(attempt,job)
            except OSError as error:
                # Rename may already have committed. Query the original record;
                # never overwrite it as failed or replay this analysis blindly.
                job=dict(job);job.pop('result',None);job.pop('resultSha256',None)
                failure=job['failure']={'kind':'completion-commit-unconfirmed','type':type(error).__name__}
                job['state']='completion-unconfirmed'
    if failure is not None:
        raise ReviewAttemptError(attempt, job)
    return result



def locations(bundle,expected,root,manifest_path,**kwargs):
    return execute(bundle,expected,root,manifest_path,None,'0'*64,'0'*64,_operation='locations',**kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    creator = commands.add_parser('freeze')
    creator.add_argument('sources', type=Path)
    creator.add_argument('destination', type=Path)
    creator.add_argument('image_id')
    freezer=commands.add_parser('freeze-verifier')
    for name in ['static_bundle','static_sha','dependencies','lock_path','contracts_path','destination']:freezer.add_argument(name)
    verifier = commands.add_parser('verify')
    runner = commands.add_parser('run')
    executor=commands.add_parser('verify-execution')
    for name in ['bundle','expected','root','manifest_path','scan_path','request_path','dataset_sha','freeze_sha']:executor.add_argument(name)
    executor.add_argument('--attempts-root',type=Path);executor.add_argument('--timeout',type=float,default=30)
    locator = commands.add_parser('locations')
    for command in [verifier, runner, locator]:
        command.add_argument('bundle', type=Path)
        command.add_argument('expected')
    for name in ['root', 'manifest_path', 'scan_path']:
        runner.add_argument(name, type=Path)
    locator.add_argument('root',type=Path)
    locator.add_argument('manifest_path',type=Path)
    locator.add_argument('--attempts-root',type=Path)
    locator.add_argument('--timeout',type=float,default=30)
    locator.add_argument('--storage-policy',type=Path)
    runner.add_argument('dataset_sha')
    runner.add_argument('freeze_sha')
    runner.add_argument('--attempts-root', type=Path)
    runner.add_argument('--timeout', type=float, default=30)
    runner.add_argument('--storage-policy',type=Path)
    for name in ['status','recover']:
        commands.add_parser(name).add_argument('directory', type=Path)
    inventory=commands.add_parser('retention-inventory')
    inventory.add_argument('directory',type=Path,nargs='?')
    inventory.add_argument('--budget-mib',type=int,default=256)
    inventory.add_argument('--minimum-age-days',type=int,default=30)
    commands.add_parser('storage-reconcile').add_argument('directory',type=Path,nargs='?')
    planner=commands.add_parser('archive-plan');planner.add_argument('directory',type=Path);planner.add_argument('--attempt-id',action='append',dest='attempt_ids')
    apply=commands.add_parser('archive-apply');apply.add_argument('directory',type=Path);apply.add_argument('plan_path',type=Path)
    for name in ['archive-status','archive-restore']:
        command=commands.add_parser(name);command.add_argument('directory',type=Path);command.add_argument('transaction_id')
    args = vars(parser.parse_args())
    action = args.pop('action')
    try:
        if action=='freeze-verifier':
            args['lock']=load_json(read(args.pop('lock_path')));args['contracts']=load_json(read(args.pop('contracts_path')))
            value=verifier_module().freeze(**args)
        elif action=='verify-execution':value=verify_execution(**args)
        elif action=='retention-inventory':
            args['budget_bytes']=args.pop('budget_mib')*1024*1024
            value=retention_inventory(**args)
        elif action=='storage-reconcile' or action.startswith('archive-'):
            storage=storage_module(sha256(read(Path(__file__).resolve().with_name(STORAGE_FILE))).hexdigest())
            directory=args['directory'] or Path.home()/'.cache/harness-review-attempts'
            policy=storage.existing_policy(directory)
            if action=='storage-reconcile':value=storage.reconcile(policy,_api_view())
            elif action=='archive-plan':value=storage.archive_plan(policy,_api_view(),attempt_ids=args.get('attempt_ids'))
            elif action=='archive-apply':value=storage.archive_apply(policy,load_json(read(args['plan_path'],ATTEMPT_LIMIT)),_api_view())
            elif action=='archive-status':value=storage.archive_status(policy,args['transaction_id'],_api_view())
            else:value=storage.archive_restore(policy,args['transaction_id'],_api_view())
        else:
            if action in {'run','locations'} and args.get('storage_policy') is not None:args['storage_policy']=load_json(read(args['storage_policy']))
            value = freeze(**args) if action == 'freeze' else verify(**args)[0] if action == 'verify' else status(**args) if action == 'status' else recover(**args) if action == 'recover' else locations(**args) if action=='locations' else execute(**args)
        print(json.dumps(value, indent=2))
        if action=='recover' and value.get('state')!='completed' and not value.get('cleanup',{}).get('confirmed'):
            parser.exit(2)
    except ReviewAttemptError as error:
        print(json.dumps({'attemptDirectory':error.attempt_directory,'status':error.status,'nextOperation':'status'},indent=2))
        state=error.status['state'];failure=error.status['failure']
        parser.exit(3 if state=='completion-unconfirmed' else 2 if state=='cleanup-unconfirmed' else 128+failure.get('signal',2) if failure['kind']=='interrupted' else 124 if failure['kind']=='timed-out' else 1)
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as error:
        if isinstance(getattr(error,'code',None),str):
            print(json.dumps({'state':'storage-blocked','reason':error.code,'retryable':getattr(error,'retryable',False),'details':getattr(error,'details',{})}))
            parser.exit(4)
        parser.exit(1, f'Reviewer snapshot rejected: {error}\n')


if __name__ == '__main__':
    main()
