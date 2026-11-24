"""Multiplex the isolated acceptance transport on one authenticated SSH master."""
from pathlib import Path
from tempfile import TemporaryFile, TemporaryDirectory
import importlib.util
import argparse
import json
import os
import select
import shlex
import socket
import socketserver
import stat
import subprocess
import threading
import time
import uuid
import signal

parser = argparse.ArgumentParser(description='Temporary loopback relay for an isolated Harness acceptance instance')
parser.add_argument('--stage-dir', type=Path, required=True)
parser.add_argument('--port', type=int, default=0)
options = parser.parse_args()
if not 0 <= options.port <= 65535:
    parser.error('--port must be between 0 and 65535')
here = options.stage_dir.resolve(strict=True)
if not here.is_dir():
    raise ValueError('The stage directory is unavailable')
stage = json.loads((here / 'stage.json').read_text())
if not stage['ready'] or type(stage['port']) is not int or not 1 <= stage['port'] <= 65535:
    raise ValueError('The isolated stage is not ready')
guest_root = Path(stage['root'])
if guest_root.parent != Path('/home/purge/.cache') or not guest_root.name.startswith('score-native-qa-'):
    raise ValueError('The stage is outside the isolated acceptance directory')
log_path = here / 'relay-mux-traces.jsonl'
if log_path.exists():
    raise FileExistsError('Retain the original trace attempt')
path = Path.home() / 'Library/Application Support/Harness Purge Original/host-tools/manage.py'
spec = importlib.util.spec_from_file_location('harness_manager', path)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)
manager.validate()
guest = r'''
from pathlib import Path
from urllib.parse import urlsplit
import json,os,select,socket,sys,time
root=Path(sys.argv[1]);port=int(sys.argv[2])
if root.parent!=Path('/home/purge/.cache') or not root.name.startswith('score-native-qa-'):
 raise ValueError('Invalid isolated guest path')
def log(phase, **details):
 os.write(2,('QA:'+json.dumps({'phase':phase,**details})+'\n').encode())
raw=b''
while b'\n' not in raw:
 part=os.read(sys.stdin.fileno(),8192)
 if not part:log('request-eof');raise SystemExit(0)
 raw+=part
 if len(raw)>65536:raise SystemExit(1)
first,rest=raw.split(b'\n',1);first+=b'\n'
if first.startswith(b'GET /__qa_login '):
 parsed=urlsplit((root/'native-access.private').read_text())
 first=b'GET /?'+parsed.query.encode()+b' HTTP/1.1\r\n'
try:sock=socket.create_connection(('127.0.0.1',port),timeout=5)
except OSError as error:log('upstream-connect-error',error=type(error).__name__);raise SystemExit(2)
sock.settimeout(None);sock.sendall(first+rest);log('upstream-connected')
started=time.monotonic();received=0
while time.monotonic()-started<1200:
 ready,_,_=select.select([sys.stdin.buffer,sock],[],[],2)
 for item in ready:
  data=os.read(item.fileno(),65536)
  if not data:log('upstream-eof' if item is sock else 'stdin-eof',received=received);raise SystemExit(0)
  if item is sock:
   received+=len(data);sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
  else:sock.sendall(data)
'''
setup = manager.SETUP
args = ['/usr/bin/ssh', '-F', '/dev/null', '-p', '49223', '-i', str(setup / 'guest-ed25519'),
        '-o', 'IdentityAgent=none', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile="' + str(setup / 'known_hosts') + '"',
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ServerAliveInterval=10',
        '-o', 'ServerAliveCountMax=2', '-T', 'purge@127.0.0.1',
        'python3 -u -c ' + shlex.quote(guest) + ' ' + shlex.quote(stage['root']) + ' ' + str(stage['port'])]
children = set()
lock = threading.Lock()
stopping = threading.Event()
admission = threading.BoundedSemaphore(8)
connections = threading.BoundedSemaphore(16)
ADMISSION_TIMEOUT = 5.0
MAX_QUEUED_BYTES = 65536
peak_exec_clients = 0


def record(value):
    with lock:
        with log_path.open('a') as target:
            target.write(json.dumps(value) + '\n')


def stop_process(process, timeout):
    if process.poll() is not None:
        return True
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return process.poll() is not None


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        prefix = bytearray()
        admitted = False
        reason = None
        try:
            while True:
                if stopping.is_set():
                    reason = 'stopping'
                    return
                remaining = ADMISSION_TIMEOUT - (time.monotonic() - started)
                if remaining <= 0:
                    reason = 'timeout'
                    try:
                        self.request.settimeout(.25)
                        self.request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
                    except OSError:
                        pass
                    return
                # Drain at most 64 KiB so FIN behind a queued request is observable.
                # This prefix is forwarded unchanged on admission, never logged.
                if len(prefix) < MAX_QUEUED_BYTES:
                    try:
                        readable, _, _ = select.select([self.request], [], [], 0)
                        data = self.request.recv(MAX_QUEUED_BYTES-len(prefix), socket.MSG_DONTWAIT) if readable else None
                    except OSError:
                        reason = 'client-disconnected'
                        return
                    if data is not None:
                        if not data:
                            reason = 'client-disconnected'
                            return
                        prefix.extend(data)
                        continue
                if admission.acquire(timeout=min(.05, remaining)):
                    admitted = True
                    if stopping.is_set():
                        reason = 'stopping'
                        return
                    self.forward(request_id, started, bytes(prefix))
                    return
        finally:
            if admitted:
                admission.release()
            if reason:
                record({'id':request_id,'admissionReason':reason,
                        'queuedMs':round((time.monotonic()-started)*1000),
                        'bufferedRequestBytes':len(prefix),'execStarted':False})

    def forward(self, request_id, started, prefix):
        global peak_exec_clients
        state = {'id': request_id, 'queuedMs': round((time.monotonic() - started) * 1000),
                 'startedAt': time.time(), 'requestBytes': 0, 'responseBytes': 0}
        stderr = None
        launch_phase = 'stderr-file'
        try:
            stderr = TemporaryFile()
            with lock:
                if stopping.is_set():
                    stderr.close()
                    return
                launch_phase = 'ssh-client'
                child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
                children.add(child)
                peak_exec_clients = max(peak_exec_clients, len(children))
                state['execClientsAtStart'] = len(children)
        except OSError as error:
            if stderr is not None:
                try:
                    stderr.close()
                except OSError:
                    pass
            state.update(execStarted=False, execStartError=type(error).__name__,
                         execStartPhase=launch_phase, execStartErrno=error.errno, httpStatus='502')
            try:
                self.request.settimeout(.25)
                response = b'HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'
                self.request.sendall(response)
                state['responseBytes'] = len(response)
            except OSError as response_error:
                state['responseError'] = type(response_error).__name__
            state['elapsedMs'] = round((time.monotonic()-started)*1000)
            record(state)
            return
        def send_request(data):
            if not state['requestBytes']:
                line = data.split(b'\r\n', 1)[0].split(b' ')
                if len(line) == 3:
                    state['method'] = line[0].decode(errors='replace')
                    state['path'] = line[1].split(b'?', 1)[0].decode(errors='replace')[:200]
            state['requestBytes'] += len(data)
            child.stdin.write(data)
            child.stdin.flush()
        try:
            if prefix:
                send_request(prefix)
            while time.monotonic() - started < 1200:
                ready, _, _ = select.select([self.request, child.stdout], [], [], 2)
                for item in ready:
                    data = os.read(item.fileno(), 65536)
                    if not data:
                        state['eof'] = 'browser' if item is self.request else 'ssh-stdout'
                        return
                    if item is self.request:
                        send_request(data)
                    else:
                        if not state['responseBytes']:
                            state['firstByteMs'] = round((time.monotonic() - started) * 1000)
                            first = data.split(b'\r\n', 1)[0].split(b' ')
                            state['httpStatus'] = first[1].decode() if len(first) >= 2 and first[1].isdigit() else None
                        state['responseBytes'] += len(data)
                        self.request.sendall(data)
        except (BrokenPipeError, ConnectionError, OSError) as error:
            state['relayError'] = type(error).__name__
        finally:
            state['sshExitedBeforeCleanup'] = child.poll() is not None
            state['cleanupConfirmed'] = stop_process(child, 3)
            state['sshExitCode'] = child.returncode
            for stream in [child.stdin, child.stdout]:
                try:
                    stream.close()
                except BrokenPipeError:
                    pass
            stderr.seek(0)
            raw = stderr.read(65536).decode(errors='replace')
            guest_events = []
            for line in raw.splitlines():
                if line.startswith('QA:'):
                    guest_events.append(json.loads(line[3:]))
            state['guest'] = guest_events
            needles = ['connection reset', 'connection closed', 'connection refused', 'connection timed out',
                       'permission denied', 'maxstartups', 'kex_exchange_identification', 'broken pipe', 'traceback']
            state['sshErrorKinds'] = [needle for needle in needles if needle in raw.lower()]
            state['elapsedMs'] = round((time.monotonic() - started) * 1000)
            record(state)
            stderr.close()
            with lock:
                if state['cleanupConfirmed']:
                    children.discard(child)
                else:
                    stopping.set()


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 20

    def process_request(self, request, client_address):
        if stopping.is_set() or not connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            connections.release()


# Install interruption handling before creating any SSH process or control socket.
server = None
thread = None
master = None
master_log = None
control_directory = None
authenticated = False


def interrupted(_signum, _frame):
    stopping.set()
    # A signal during Popen must not escape before the new child is assigned.
    if master is not None:
        raise KeyboardInterrupt


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
try:
    control_directory = TemporaryDirectory(prefix='hmux-', dir='/private/tmp')
    control_path = Path(control_directory.name) / 'control'
    common, host, remote_command = args[:-2], args[-2], args[-1]
    master_args = common + ['-M', '-N', '-S', str(control_path), '-o', 'ControlPersist=no', host]
    master_log = TemporaryFile()
    if stopping.is_set():
        raise KeyboardInterrupt
    master = subprocess.Popen(master_args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=master_log)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if stopping.is_set():
            raise KeyboardInterrupt
        if master.poll() is not None:
            raise RuntimeError('SSH master failed before readiness')
        if control_path.exists():
            info = control_path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Invalid private SSH control socket')
            checked = subprocess.run(['/usr/bin/ssh', '-F', '/dev/null', '-S', str(control_path), '-O', 'check', host],
                                     capture_output=True, timeout=2)
            if checked.returncode == 0:
                authenticated = True
                break
        time.sleep(.05)
    else:
        raise TimeoutError('SSH master readiness deadline')
    # ProxyCommand=false prevents an exec client from making a replacement connection.
    args = common + ['-S', str(control_path), '-o', 'ControlMaster=no', '-o', 'ProxyCommand=false', host, remote_command]
    (here / 'mux-lifecycle.json').write_text(json.dumps({'authenticatedMaster': True, 'masterPID': master.pid,
        'clientFallbackDisabled': True, 'maxConcurrentExecChannels': 8, 'stopped': False}) + '\n')
    server = Server(('127.0.0.1', options.port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:' + str(server.server_address[1]) + '/__qa_login'
    (here / 'relay-url.txt').write_text(url + '\n')
    print(json.dumps({'url': url, 'trace': str(log_path)}), flush=True)
    input('Stop after the isolated diagnostics.\n')
finally:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        with lock:
            stopping.set()
            active = list(children)
        try:
            if thread is not None and thread.is_alive():
                server.shutdown()
            if server is not None:
                server.server_close()
        finally:
            try:
                for child in active:
                    stop_process(child, 4)
            finally:
                if master is not None:
                    stop_process(master, 4)
    finally:
        if master_log is not None:
            master_log.close()
        if control_directory is not None:
            control_directory.cleanup()
        remaining = [child.pid for child in active if child.poll() is None]
        master_stopped = master is None or master.poll() is not None
        if not master_stopped:
            remaining.append(master.pid)
        (here / 'mux-lifecycle.json').write_text(json.dumps({'authenticatedMaster': authenticated,
            'masterPID': master.pid if master else None, 'clientFallbackDisabled': True,
            'maxConcurrentExecChannels': 8, 'maxConnectionHandlers': 16,
            'peakExecClients': peak_exec_clients, 'admissionTimeoutSeconds': ADMISSION_TIMEOUT,
            'maxQueuedBytesPerConnection': MAX_QUEUED_BYTES,
            'masterStopped': master_stopped, 'remainingPids': remaining, 'stopped': not remaining,
            'controlDirectoryRemoved': control_directory is None or not Path(control_directory.name).exists()}) + '\n')
        if remaining:
            raise RuntimeError('Relay cleanup could not confirm process exit; see mux-lifecycle.json')
print('Multiplexed relay stopped.', flush=True)
