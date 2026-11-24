import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import time

CAP = 64 * 1024 * 1024
STOP = 4 * 1024 * 1024
FLOOR = 512 * 1024 * 1024
MAGIC = b'HARNESS-CONSUMER12/1' + bytes([10])
MAX_HEADER = 2 * 1024 * 1024
MAX_STDERR = 1024 * 1024
CHUNK = 65536
H_RESERVE = MAX_HEADER + 64
E_RESERVE = MAX_STDERR
F_RESERVE = 4 * 1024 * 1024
HEX64 = re.compile('[0-9a-f]{64}')
PREFIX_RE = re.compile('(?:VM|status-[0-9a-f]{16})')

def _write_chunks(out, data):
    for i in range(0, len(data), CHUNK):
        out.write(data[i:i + CHUNK])

def emit_frame(delivery, out=None):
    if out is None:
        out = sys.stdout.buffer
    if not isinstance(delivery, dict):
        raise TypeError('delivery must be a dict')
    d = dict(delivery)
    raw = d.pop('archiveBytesPayload', b'')
    if raw is None:
        raw = b''
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('archiveBytesPayload must be bytes or None')
    raw = bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if 'archiveSha256' in d and d['archiveSha256'] != digest:
        raise ValueError('delivery archiveSha256 does not match payload')
    header = {'version': 1, 'delivery': d, 'archiveBytes': len(raw), 'archiveSha256': digest}
    try:
        hb = json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError('header is not JSON serializable') from exc
    if len(hb) > MAX_HEADER:
        raise ValueError('header exceeds 2 MiB')
    prefix = MAGIC + len(hb).to_bytes(8, 'big') + hb
    _write_chunks(out, prefix)
    _write_chunks(out, raw)

def _raise_walk(err):
    raise err

def _validate_root(root):
    st = os.lstat(root)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ValueError('root must be a non-symlink directory')
    uid = getattr(os, 'getuid', lambda: st.st_uid)()
    if st.st_uid != uid:
        raise ValueError('root is not owned by current user')

def _strict_usage(root):
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False, onerror=_raise_walk):
        for name in list(dirnames):
            p = os.path.join(dirpath, name)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise ValueError('symlink or special directory in root')
        for name in filenames:
            p = os.path.join(dirpath, name)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                raise ValueError('symlink in root')
            if not stat.S_ISREG(st.st_mode):
                raise ValueError('special file in root')
            total += st.st_size
    return total

def _free_bytes(root):
    v = os.statvfs(root)
    return v.f_bavail * v.f_frsize

def _check_budget(root, chunk, *, cap=CAP - STOP, label='disk'):
    used = _strict_usage(root)
    if used + chunk > cap:
        raise ValueError(label + ': capacity would be exceeded')
    if _free_bytes(root) < FLOOR + chunk:
        raise ValueError(label + ': free space floor would be violated')

def _open_exclusive(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags, 0o600), 'wb', buffering=0)

def _close_quiet(f):
    if f is None:
        return
    try:
        f.close()
    except Exception:
        pass

def _write_budgeted(root, path, data, label, cap=CAP - STOP):
    f = _open_exclusive(path)
    try:
        for i in range(0, len(data), CHUNK):
            chunk = data[i:i + CHUNK]
            _check_budget(root, len(chunk), cap=cap, label=label)
            f.write(chunk)
    finally:
        f.close()

class _Parser:
    def __init__(self, root, header_path, body_path, zmax):
        self.root = root
        self.header_path = header_path
        self.body_path = body_path
        self.zmax = zmax
        self.buf = bytearray()
        self.header_parsed = False
        self.delivery = None
        self.expected = None
        self.expected_hash = None
        self.observed_hash = hashlib.sha256()
        self.written = 0
        self.body_file = None
        self.done = False

    def feed(self, data):
        if not data:
            return
        if self.done:
            raise ValueError('trailing bytes after body')
        if not self.header_parsed:
            self.buf.extend(data)
            if len(self.buf) < len(MAGIC):
                return
            if bytes(self.buf[:len(MAGIC)]) != MAGIC:
                raise ValueError('invalid frame magic')
            if len(self.buf) < len(MAGIC) + 8:
                return
            n = int.from_bytes(self.buf[len(MAGIC):len(MAGIC) + 8], 'big')
            if n > MAX_HEADER:
                raise ValueError('declared header exceeds 2 MiB')
            total = len(MAGIC) + 8 + n
            if len(self.buf) < total:
                return
            raw = bytes(self.buf[:total])
            rest = bytes(self.buf[total:])
            self.buf.clear()
            try:
                self._parse_header(raw, n)
            except BaseException:
                self.buf = bytearray(raw)
                raise
            if rest:
                self._consume_body(rest)
        else:
            self._consume_body(data)

    def _parse_header(self, raw, n):
        try:
            obj = json.loads(raw[len(MAGIC) + 8:].decode('utf-8'))
        except Exception as exc:
            raise ValueError('invalid header JSON') from exc
        if not isinstance(obj, dict):
            raise ValueError('header is not a JSON object')
        if type(obj.get('version')) is not int or obj.get('version') != 1:
            raise ValueError('unsupported header version')
        delivery = obj.get('delivery')
        if not isinstance(delivery, dict):
            raise ValueError('header delivery must be an object')
        ab = obj.get('archiveBytes')
        if type(ab) is not int or ab < 0:
            raise ValueError('archiveBytes must be a nonnegative integer')
        digest = obj.get('archiveSha256')
        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            raise ValueError('archiveSha256 must be lowercase 64-hex')
        if ab > self.zmax:
            raise ValueError('archiveBytes exceeds admitted limit')
        if 'archiveSha256' in delivery and delivery['archiveSha256'] != digest:
            raise ValueError('delivery archiveSha256 mismatch')
        _write_budgeted(self.root, self.header_path, raw, 'wire-header')
        self.delivery = delivery
        self.expected = ab
        self.expected_hash = digest
        self.header_parsed = True
        self.body_file = _open_exclusive(self.body_path)
        if ab == 0:
            self.body_file.close()
            self.body_file = None
            self.done = True

    def _consume_body(self, data):
        if self.done:
            raise ValueError('trailing bytes after body')
        remaining = self.expected - self.written
        if remaining <= 0:
            raise ValueError('trailing bytes after body')
        take = min(len(data), remaining)
        if take:
            self._write_body(data[:take])
        if len(data) > take:
            raise ValueError('trailing bytes after body')
        if self.written == self.expected:
            if self.body_file is not None:
                self.body_file.close()
                self.body_file = None
            self.done = True

    def _write_body(self, chunk):
        if self.body_file is None:
            raise ValueError('body file is closed')
        _check_budget(self.root, len(chunk), label='body')
        self.body_file.write(chunk)
        self.observed_hash.update(chunk)
        self.written += len(chunk)

    def finish(self):
        if not self.header_parsed:
            raise ValueError('incomplete frame header')
        if self.written != self.expected:
            raise ValueError('truncated body')
        if self.observed_hash.hexdigest() != self.expected_hash:
            raise ValueError('archive digest mismatch')
        if self.body_file is not None:
            self.body_file.close()
            self.body_file = None

    def preserve_prefix(self):
        if os.path.lexists(self.header_path):
            return 'present' if self.header_parsed else 'unknown'
        data = bytes(self.buf)
        if not data:
            return 'empty'
        limit = MAX_HEADER + len(MAGIC) + 8
        original_len = len(data)
        truncated = original_len > limit
        if truncated:
            data = data[:limit]
        try:
            _write_budgeted(self.root, self.header_path, data, 'wire-header-prefix', cap=CAP)
        except Exception:
            return 'unknown'
        if truncated:
            return 'truncated:' + str(original_len) + ':' + str(limit)
        return 'written'

    def close(self):
        if self.body_file is not None:
            try:
                self.body_file.close()
            except Exception:
                pass
            self.body_file = None

class _StderrWriter:
    def __init__(self, root, path):
        self.root = root
        self.path = path
        self.f = None
        self.written = 0

    def feed(self, data):
        if not data:
            return
        if self.written + len(data) > MAX_STDERR:
            allowed = MAX_STDERR - self.written
            if allowed > 0:
                self._write(data[:allowed])
            raise ValueError('stderr exceeds 1 MiB')
        self._write(data)

    def _write(self, data):
        if not data:
            return
        if self.f is None:
            self.f = _open_exclusive(self.path)
        for i in range(0, len(data), CHUNK):
            chunk = data[i:i + CHUNK]
            _check_budget(self.root, len(chunk), label='stderr')
            self.f.write(chunk)
            self.written += len(chunk)

    def close(self):
        if self.f is not None:
            try:
                self.f.close()
            except Exception:
                pass
            self.f = None

def _terminate(proc):
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    else:
        try:
            proc.wait(timeout=0)
        except Exception:
            pass

def _safe_argv(argv):
    out = []
    for a in list(argv):
        s = str(a)
        if len(s) > 128:
            s = s[:125] + '...'
        out.append(s)
    if len(out) > 16:
        out = out[:16] + ['...']
    return out

def _make_receipt(prefix, admission, state, argv, proc, expected, written, observed, error):
    return {
        'version': 1,
        'prefix': prefix,
        'admission': admission,
        'transfer': {
            'state': state,
            'originalCommand': _safe_argv(argv),
            'localPID': getattr(proc, 'pid', None) if proc is not None else None,
            'localExit': getattr(proc, 'returncode', None) if proc is not None else None,
            'expectedBodyBytes': expected,
            'actualWrittenBytes': written,
            'observedSha256': observed,
            'remoteOutcome': 'unknown' if state != 'success' else 'success',
        },
        'error': error,
    }

def _write_receipt(root, path, receipt, failure=False):
    data = json.dumps(receipt, separators=(',', ':'), sort_keys=True).encode('utf-8')
    if len(data) > 8192:
        receipt = dict(receipt)
        receipt.pop('error', None)
        data = json.dumps(receipt, separators=(',', ':'), sort_keys=True).encode('utf-8')
    if len(data) > 8192:
        raise ValueError('receipt exceeds 8 KiB')
    _write_budgeted(root, path, data, 'transfer-receipt', cap=(CAP if failure else CAP - STOP))

def receive_command(argv, *, input, root, timeout, archive_limit=None, prefix='VM'):
    if not isinstance(prefix, str) or PREFIX_RE.fullmatch(prefix) is None:
        raise ValueError('invalid prefix')
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError('timeout must be positive')
    if archive_limit is not None and (type(archive_limit) is not int or archive_limit < 0):
        raise ValueError('archive_limit must be a nonnegative integer')
    root_s = os.fspath(root)
    _validate_root(root_s)
    evidence = os.path.join(root_s, 'evidence')
    os.makedirs(evidence, exist_ok=True)
    est = os.lstat(evidence)
    if stat.S_ISLNK(est.st_mode) or not stat.S_ISDIR(est.st_mode):
        raise ValueError('evidence is not a directory')
    header_path = os.path.join(evidence, prefix + '-wire-header.bin')
    body_path = os.path.join(evidence, prefix + '-original-evidence.zip')
    stderr_path = os.path.join(evidence, prefix + '-transport.stderr')
    receipt_path = os.path.join(evidence, prefix + '-transfer.json')
    for p in (header_path, body_path, stderr_path, receipt_path):
        if os.path.lexists(p):
            raise ValueError('preexisting output path: ' + p)
    if isinstance(input, str):
        in_bytes = input.encode('utf-8')
    elif isinstance(input, (bytes, bytearray, memoryview)):
        in_bytes = bytes(input)
    else:
        raise TypeError('input must be str or bytes')
    used = _strict_usage(root_s)
    half = (CAP - STOP - F_RESERVE) // 2
    zmax = half - used - H_RESERVE - E_RESERVE
    if zmax <= 0:
        raise ValueError('admission: archive budget is not positive')
    if archive_limit is not None:
        zmax = min(zmax, archive_limit)
    if _free_bytes(root_s) < FLOOR + H_RESERVE + E_RESERVE + F_RESERVE:
        raise ValueError('admission: free space floor would be violated')
    admission = {'rootBytes': used, 'headerReserve': H_RESERVE, 'stderrReserve': E_RESERVE, 'finalReserve': F_RESERVE, 'zmax': zmax, 'archiveLimit': archive_limit}
    proc = None
    parser = None
    stderr_writer = None
    receipt_written = False
    started = time.monotonic()
    try:
        proc = subprocess.Popen(list(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, close_fds=True)
        for f in (proc.stdin, proc.stdout, proc.stderr):
            os.set_blocking(f.fileno(), False)
        parser = _Parser(root_s, header_path, body_path, zmax)
        stderr_writer = _StderrWriter(root_s, stderr_path)
        sel = selectors.DefaultSelector()
        try:
            in_pos = 0
            stdin_done = False
            stdout_eof = False
            stderr_eof = False
            if len(in_bytes) == 0:
                _close_quiet(proc.stdin)
                stdin_done = True
            else:
                sel.register(proc.stdin, selectors.EVENT_WRITE, 'stdin')
            sel.register(proc.stdout, selectors.EVENT_READ, 'stdout')
            sel.register(proc.stderr, selectors.EVENT_READ, 'stderr')
            while not (stdout_eof and stderr_eof and stdin_done):
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError('transport timed out')
                events = sel.select(remaining)
                if not events:
                    raise TimeoutError('transport timed out')
                for key, mask in events:
                    tag = key.data
                    if tag == 'stdin':
                        if stdin_done:
                            continue
                        try:
                            n = os.write(proc.stdin.fileno(), in_bytes[in_pos:in_pos + CHUNK])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            _close_quiet(proc.stdin)
                            stdin_done = True
                            try:
                                sel.unregister(key.fileobj)
                            except Exception:
                                pass
                            continue
                        if n:
                            in_pos += n
                        if in_pos >= len(in_bytes):
                            _close_quiet(proc.stdin)
                            stdin_done = True
                            try:
                                sel.unregister(key.fileobj)
                            except Exception:
                                pass
                    elif tag == 'stdout':
                        try:
                            data = os.read(proc.stdout.fileno(), CHUNK)
                        except BlockingIOError:
                            continue
                        if data:
                            parser.feed(data)
                        else:
                            stdout_eof = True
                            try:
                                sel.unregister(key.fileobj)
                            except Exception:
                                pass
                    elif tag == 'stderr':
                        try:
                            data = os.read(proc.stderr.fileno(), CHUNK)
                        except BlockingIOError:
                            continue
                        if data:
                            stderr_writer.feed(data)
                        else:
                            stderr_eof = True
                            try:
                                sel.unregister(key.fileobj)
                            except Exception:
                                pass
                if proc.poll() is not None and not stdin_done:
                    _close_quiet(proc.stdin)
                    stdin_done = True
                    try:
                        sel.unregister(proc.stdin)
                    except Exception:
                        pass
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError('transport timed out')
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise TimeoutError('transport timed out')
        finally:
            sel.close()
        if proc.returncode != 0:
            raise ValueError('local process exited with status ' + str(proc.returncode))
        parser.finish()
        stderr_writer.close()
        _strict_usage(root_s)
        receipt = _make_receipt(prefix, admission, 'success', list(argv), proc, parser.expected, parser.written, parser.observed_hash.hexdigest(), None)
        _write_receipt(root_s, receipt_path, receipt, failure=False)
        receipt_written = True
        return subprocess.CompletedProcess(list(argv), 0, stdout=json.dumps(parser.delivery), stderr='')
    except BaseException as exc:
        _terminate(proc)
        if proc is not None:
            _close_quiet(proc.stdin)
            _close_quiet(proc.stdout)
            _close_quiet(proc.stderr)
        if parser is not None:
            parser.close()
        if stderr_writer is not None:
            stderr_writer.close()
        if not receipt_written and proc is not None:
            try:
                expected = parser.expected if parser is not None else None
                written = parser.written if parser is not None else 0
                observed = parser.observed_hash.hexdigest() if parser is not None else ''
                prefix_status = 'not-applicable'
                if parser is not None:
                    try:
                        prefix_status = parser.preserve_prefix()
                    except Exception:
                        prefix_status = 'unknown'
                err = str(exc)[:200]
                if prefix_status not in ('present', 'written', 'empty', 'not-applicable'):
                    err = (err + '; raw-prefix=' + prefix_status)[:256]
                receipt = _make_receipt(prefix, admission, 'failed', list(argv), proc, expected, written, observed, err)
                _write_receipt(root_s, receipt_path, receipt, failure=True)
            except Exception:
                pass
        raise
    finally:
        if proc is not None:
            _close_quiet(proc.stdin)
            _close_quiet(proc.stdout)
            _close_quiet(proc.stderr)
            if proc.poll() is None:
                _terminate(proc)
        if parser is not None:
            parser.close()
        if stderr_writer is not None:
            stderr_writer.close()
