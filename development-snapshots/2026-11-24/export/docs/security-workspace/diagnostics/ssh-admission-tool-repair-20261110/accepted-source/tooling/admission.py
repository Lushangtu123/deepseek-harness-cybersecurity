"""Isolated control for the existing manager queue; never executes SSH."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import json, os, random, select, signal, socket, subprocess, sys
import tempfile, threading, time, types
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
MODES = ('unqueued', 'existing-queue')
RESERVED = set(range(49222, 49227))
MANAGER_SHA = '69cc27ae32ba7be4362e6a4d94a4f253ac54d573380c98f58fa40bdb8758e401'
CANCEL_SIGNALS = (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)
_cancel_events = []
_runtime_active = False
_runtime_deadline = None


def expire(signum, frame):
    # Never inject an exception into arbitrary cleanup or acquisition bytecode.
    _cancel_events.append(signum)


def pending_cancellation():
    return bool(_cancel_events)


def check_cancel():
    if _cancel_events or (_runtime_deadline is not None and time.monotonic() >= _runtime_deadline):
        raise TimeoutError('Isolated control cancelled at a safe checkpoint')


def remaining(deadline):
    check_cancel()
    limit = min(deadline, _runtime_deadline) if _runtime_deadline is not None else deadline
    value = limit-time.monotonic()
    if value <= 0: raise TimeoutError('Isolated operation deadline')
    return value


@contextmanager
def run_signals(deadline=None):
    """Own handlers before acquiring resources; restore after their cleanup."""
    global _runtime_active, _runtime_deadline
    if threading.current_thread() is not threading.main_thread() or _runtime_active:
        raise ValueError('Signal ownership requires a nonnested main-thread run')
    _cancel_events.clear()
    saved = {kind: signal.getsignal(kind) for kind in CANCEL_SIGNALS}
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, CANCEL_SIGNALS)
    try:
        try:
            for kind in CANCEL_SIGNALS: signal.signal(kind, expire)
        except BaseException as setup_error:
            for kind, handler in saved.items():
                try: signal.signal(kind, handler)
                except BaseException as restore_error:
                    setup_error.add_note('Signal setup rollback: '+type(restore_error).__name__)
            raise
    finally: signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    _runtime_active = True; _runtime_deadline = deadline
    body_error = None
    try:
        yield
    except BaseException as error:
        body_error = error; raise
    finally:
        _runtime_active = False; _runtime_deadline = None
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, CANCEL_SIGNALS)
        restore_errors = []
        try:
            for kind, handler in saved.items():
                try: signal.signal(kind, handler)
                except BaseException as error: restore_errors.append(type(error).__name__)
        finally: signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        if restore_errors:
            if body_error is not None: body_error.add_note('Signal restore errors: '+repr(restore_errors))
            else: raise RuntimeError('Signal restore failed: '+repr(restore_errors))


def load_manager(path, expected):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError('Snapshot digest mismatch; refusing execution')
    module = types.ModuleType('isolated_queue_manager')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def schedule():
    rng = random.Random(20261110)
    result = []
    for block in range(4):
        modes = list(MODES); rng.shuffle(modes)
        result.extend(dict(block=block, mode=mode) for mode in modes)
    return result


def summarize(trials):
    seen = set()
    for trial in trials:
        key = trial['block'], trial['mode']
        if key in seen or trial['mode'] not in MODES:
            raise ValueError('Duplicate or unknown trial')
        seen.add(key)
        if trial['workersReaped'] is not True or trial['serverStopped'] is not True:
            raise ValueError('Unconfirmed cleanup')
        clients = trial['clients']
        if len(clients) != 6 or sorted(c['index'] for c in clients) != list(range(6)):
            raise ValueError('Missing or duplicate client')
        for client in clients:
            if type(client['connected']) is not bool or type(client['complete']) is not bool:
                raise ValueError('Invalid outcome flags')
            calls = client['commandCalls']
            if type(calls) is not int or calls not in (0, 1):
                raise ValueError('Invalid executor invocation count')
            if type(client['returncode']) is not int or client['returncode'] not in (0, 1):
                raise ValueError('Invalid synthetic outcome code')
            state = client.get('requestState', 'complete' if client['complete'] else 'failed')
            if calls == 0:
                if (state != 'not-sent' or client['complete'] or client['connected'] or
                        client['returncode'] != 1 or client.get('errorStage') != 'queue' or
                        client.get('errorType') != 'SSHNotSent' or
                        any(k in client for k in ['exchangeStartedMonoNs', 'exchangeEndedMonoNs',
                                                  'connectReturnedMonoNs'])):
                    raise ValueError('Zero invocations lack queue-not-sent evidence')
            elif client['complete']:
                if state != 'complete' or not client['connected'] or client.get('errorType') or client['returncode'] != 0:
                    raise ValueError('Contradictory success')
            elif state != 'failed' or client['returncode'] != 1 or not client.get('errorType'):
                raise ValueError('Contradictory failed exchange')
    result = []
    for mode in MODES:
        rows = [r for r in trials if r['mode'] == mode]
        if not rows: continue
        clients = [c for r in rows for c in r['clients']]
        failures = [c for c in clients if c['commandCalls'] == 1 and not c['complete']]
        not_sent = [c for c in clients if c['commandCalls'] == 0]
        result.append(dict(mode=mode, trials=len(rows), clients=len(clients),
                           connected=sum(c['connected'] for c in clients),
                           complete=sum(c['complete'] for c in clients),
                           failed=len(failures), notSent=len(not_sent), errors=dict(Counter(
                               c.get('errorStage', 'unknown') + '|' +
                               c.get('errorType', 'unknown') + '|' + str(c.get('errno'))
                               for c in failures)), notSentReasons=dict(Counter(
                               c['errorStage'] + '|' + c['errorType'] + '|' + str(c.get('errno'))
                               for c in not_sent))))
    return result


def worker(manager_path, manager_sha, lock_root, mode, port, index):
    if mode not in MODES or int(port) in RESERVED or not 1024 <= int(port) <= 65535:
        raise ValueError('Invalid isolated trial target')
    os.umask(0o077)
    manager = load_manager(manager_path, manager_sha)
    manager.ROOT = Path(lock_root)
    value = dict(index=int(index), connected=False, complete=False, commandCalls=0)

    def exchange(argv=None, **kwargs):
        value['commandCalls'] += 1
        if value['commandCalls'] != 1: raise ValueError('Replay refused')
        stage = 'connect'; value['exchangeStartedMonoNs'] = time.monotonic_ns()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as channel:
                channel.settimeout(min(.75, kwargs.get('timeout', .75)))
                channel.connect(('127.0.0.1', int(port)))
                value.update(connected=True, connectReturnedMonoNs=time.monotonic_ns())
                stage = 'send'; token = bytes([int(index) + 1]); channel.sendall(token)
                stage = 'reply'; reply = channel.recv(1)
                value['complete'] = reply == token
                if reply != token:
                    value.update(errorStage='reply', errorType='EOF' if not reply else 'Mismatch')
        except OSError as error:
            value.update(errorStage=stage, errorType=type(error).__name__, errno=error.errno)
        finally: value['exchangeEndedMonoNs'] = time.monotonic_ns()
        if not value['complete']:
            raise subprocess.CalledProcessError(1, ['synthetic-echo'], stderr='Synthetic echo failed')
        return subprocess.CompletedProcess(['synthetic-echo'], 0, 'echo-ok', '')

    # This is the only command executor reachable from manager.ssh in this trial.
    # No ssh process is created; no identity or trust file is opened.
    manager.command = exchange
    print('READY', flush=True)
    if sys.stdin.readline() != 'GO\n': raise ValueError('Release missing')
    value['requestEnteredMonoNs'] = time.monotonic_ns()
    try:
        if mode == 'existing-queue':
            manager.ssh('SYNTHETIC-ECHO', timeout=2, phase='diagnostic-sample')
        else: exchange()
        value.update(returncode=0, requestState='complete')
    except manager.SSHNotSent:
        value.update(returncode=1, requestState='not-sent', errorStage='queue', errorType='SSHNotSent')
    except Exception as error:
        value.update(returncode=1, requestState='failed')
        if 'errorType' not in value:
            value.update(errorStage='queue-or-worker', errorType=type(error).__name__)
    value['requestEndedMonoNs'] = time.monotonic_ns()
    print(json.dumps(value), flush=True)


BOOTSTRAP = '''from pathlib import Path
from hashlib import sha256
import sys
raw=Path(sys.argv[1]).read_bytes()
if sha256(raw).hexdigest()!=sys.argv[2]:raise ValueError('Control source mismatch')
ns={'__name__':'isolated_admission_worker','__file__':sys.argv[1]}
exec(compile(raw,sys.argv[1],'exec'),ns)
ns['worker'](*sys.argv[3:])
'''


class CleanupFailure(RuntimeError):
    def __init__(self, report):
        super().__init__('Owned cleanup unconfirmed; inspect attached cleanup report')
        self.cleanup = report


def cleanup_owned(children, thread, stop, gate, budget=2):
    errors = []; deadline = time.monotonic() + budget
    def record(stage, index, error):
        errors.append(dict(stage=stage, index=index, type=type(error).__name__))
    supported = (threading.current_thread() is threading.main_thread() and _runtime_active and
                 all(signal.getsignal(kind) is expire for kind in CANCEL_SIGNALS))
    if not supported: errors.append(dict(stage='signal-ownership', index=None, type='UnsupportedCleanupContext'))
    try:
        stop.set(); gate.set()
        try:
            for attempt in range(2):
                for index, child in enumerate(children):
                    try:
                        if child.poll() is None: child.kill()
                    except BaseException as error: record('kill', index, error)
            for index, child in enumerate(children):
                try:
                    child.communicate(timeout=max(.001, deadline-time.monotonic()))
                except BaseException as error:
                    record('communicate', index, error)
                    try: child.wait(timeout=max(.001, deadline-time.monotonic()))
                    except BaseException as error: record('wait', index, error)
                finally:
                    for stream in [child.stdin, child.stdout, child.stderr]:
                        try:
                            if stream is not None and not stream.closed: stream.close()
                        except BaseException as error: record('pipe-close', index, error)
        finally:
            if thread is not None:
                try: thread.join(timeout=max(.001, deadline-time.monotonic()))
                except BaseException as error: record('join', None, error)
    except BaseException as error: record('cleanup-outer', None, error)
    reaped = []
    for index, child in enumerate(children):
        try: reaped.append(child.poll() is not None)
        except BaseException as error:
            reaped.append(False); record('poll', index, error)
    try: server_stopped = thread is None or not thread.is_alive()
    except BaseException as error:
        server_stopped = False; record('thread-state', None, error)
    interrupted = list(_cancel_events)
    return dict(allChildrenReaped=all(reaped), serverStopped=server_stopped,
                errors=errors, interruptedSignals=interrupted,
                unreapedWorkerIndexes=[i for i, done in enumerate(reaped) if not done],
                ok=all(reaped) and server_stopped and not errors and not interrupted)


def wait_ready(children, deadline):
    """Nonblocking complete-line protocol; a half line cannot defeat a deadline."""
    pending = {p.stdout: bytearray() for p in children}
    streams = list(pending)
    try:
        for stream in streams: os.set_blocking(stream.fileno(), False)
        while pending:
            readable, _, _ = select.select(list(pending), [], [], min(.05, remaining(deadline)))
            for stream in readable:
                data = os.read(stream.fileno(), 64)
                if not data: raise ValueError('Worker EOF before READY')
                pending[stream].extend(data)
                if len(pending[stream]) > 16: raise ValueError('Worker readiness byte limit')
                if b'\n' in pending[stream]:
                    if pending[stream] != b'READY\n': raise ValueError('Invalid READY message')
                    del pending[stream]
        check_cancel()
    finally:
        for stream in streams:
            if not stream.closed: os.set_blocking(stream.fileno(), True)


def trial(block, mode, source_sha):
    children = []; server_events = []; server_errors = []
    gate = threading.Event(); stop = threading.Event(); thread = None
    with tempfile.TemporaryDirectory(prefix='admission-') as temp, \
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        os.chmod(temp, 0o700)
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        if port in RESERVED: raise ValueError('Reserved port; no workers launched')
        listener.listen(1); listener.setblocking(False)

        def serve():
            if not gate.wait(5): return
            stop.wait(.025)
            while not stop.is_set():
                try:
                    if not select.select([listener], [], [], .02)[0]: continue
                    peer, _ = listener.accept()
                    event = dict(acceptedMonoNs=time.monotonic_ns())
                    with peer:
                        peer.settimeout(.5); data = peer.recv(1)
                        if data: peer.sendall(data)
                        event.update(requestBytes=len(data), responseSent=bool(data),
                                     requestIndex=data[0]-1 if len(data) == 1 else None)
                    server_events.append(event)
                except BlockingIOError: continue
                except OSError as error:
                    server_errors.append(dict(type=type(error).__name__, errno=error.errno))

        check_cancel()
        thread = threading.Thread(target=serve, name='owned-admission-echo')
        thread.start()
        body_error = None
        try:
            for index in range(6):
                check_cancel()
                argv = [sys.executable, '-I', '-B', '-c', BOOTSTRAP, str(Path(__file__).resolve()),
                        source_sha, str(ROOT/'inputs/manage.py'), MANAGER_SHA,
                        temp, mode, str(port), str(index)]
                children.append(subprocess.Popen(argv, stdin=subprocess.PIPE,
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            wait_ready(children, time.monotonic()+5)
            released = time.monotonic_ns(); gate.set()
            for child in children: child.stdin.write(b'GO\n'); child.stdin.flush()
            clients = []
            deadline = time.monotonic() + 4
            for child in children:
                out, err = child.communicate(timeout=remaining(deadline))
                if child.returncode or err: raise ValueError('Worker protocol or interpreter failed')
                clients.append(json.loads(out))
            check_cancel()
        except BaseException as error:
            body_error = error; raise
        finally:
            try: cleanup = cleanup_owned(children, thread, stop, gate)
            except BaseException as error:
                cleanup = dict(ok=False, errors=[dict(stage='cleanup-fatal', type=type(error).__name__)])
            if body_error is not None:
                body_error.cleanup = cleanup
                if not cleanup['ok']: body_error.add_note('Owned cleanup unconfirmed: '+json.dumps(cleanup))
            elif not cleanup['ok']: raise CleanupFailure(cleanup)
        return dict(block=block, mode=mode, requestedBacklog=1, acceptDelaySeconds=.025,
                    releaseMonoNs=released, portWasEphemeralNotVM=True, clients=clients,
                    serverEvents=server_events, serverErrors=server_errors,
                    workersReaped=cleanup['allChildrenReaped'],
                    serverStopped=cleanup['serverStopped'], cleanup=cleanup)


def run_control():
    check_cancel()
    contract_path = ROOT/'execution-contract.json'; result_path = ROOT/'control-results.json'
    if contract_path.exists() or result_path.exists(): raise ValueError('Attempt exists; no replay')
    source = Path(__file__).resolve(); manager = ROOT/'inputs/manage.py'
    hashes = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
              for p in [source, manager, ROOT/'tooling/analysis.test.py',
                        ROOT/'tooling/regression.test.py', ROOT/'record-analysis.py', ROOT/'tooling/r2.test.py']}
    if hashes['inputs/manage.py'] != MANAGER_SHA: raise ValueError('Manager changed')
    contract = dict(schemaVersion=2, sources=hashes, schedule=schedule(), maxClients=48, maxConcurrent=6,
                    newVmRequests=0, endpoint='own IPv4 loopback ephemeral only',
                    reservedPorts=sorted(RESERVED), processDeadlineSeconds=60,
                    protocol='one synthetic byte per worker; one executor invocation; no retries',
                    preregistration='same process writes contract immediately before execution; no external timestamp')
    with contract_path.open('x') as f: json.dump(contract, f, indent=2)
    trials = [trial(row['block'], row['mode'], hashes['tooling/admission.py']) for row in contract['schedule']]
    aggregates = summarize(trials)
    for name, expected in hashes.items():
        if sha256((ROOT/name).read_bytes()).hexdigest() != expected: raise ValueError('Source drift')
    result = dict(contractSha256=sha256(contract_path.read_bytes()).hexdigest(),
                  trials=trials, aggregates=aggregates, sourcesUnchanged=True,
                  newVmRequests=0, productionConfigurationModified=False,
                  preciseProductionRootCauseConfirmed=False,
                  limitations=['Not an SSH/QEMU/guest integration test.',
                               'Queue serializes full exchanges and changes pacing; no connect-only attribution.',
                               'Pipe release is not simultaneous network arrival; no kernel queue or packet trace.',
                               'Cleanup is by wait/join/context structure, not global socket census.'])
    check_cancel()
    with result_path.open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(dict(aggregates=aggregates, newVmRequests=0), indent=2))


def main():
    os.umask(0o077)
    with run_signals(deadline=time.monotonic()+60):
        signal.alarm(60)
        try: run_control(); check_cancel()
        finally: signal.alarm(0)


if __name__ == '__main__': main()
