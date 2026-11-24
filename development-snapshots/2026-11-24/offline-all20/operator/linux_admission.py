'''Linux-only admission gate for the bounded consumer VM controller.'''
import hashlib
import os
import platform
import sys
import uuid
from pathlib import Path

_EXPECTED_UID = 1000
_EXPECTED_MACHINE = 'aarch64'
_EXPECTED_VERSION = '3.12.3'
_EXPECTED_SHA256 = 'c86f21d0da9290ece2d7d49a3f7ed52aed59cb029abdf0ea25c79634f6cbe960'
_PROC_STATES = frozenset('RSDZTtXxKWP?I')


def _fail(reason):
    raise ValueError(reason)


def _boot_id():
    try:
        text = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    except OSError as error:
        _fail('boot-id-unreadable:' + type(error).__name__)
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError):
        _fail('boot-id-malformed')
    if str(parsed) != text.lower():
        _fail('boot-id-not-canonical')
    return str(parsed)


def _proc_stat(pid):
    if type(pid) is not int or pid <= 0:
        _fail('pid-invalid')
    try:
        raw = Path('/proc/%d/stat' % pid).read_text(encoding='ascii')
    except OSError as error:
        _fail('proc-stat-unreadable:' + type(error).__name__)
    try:
        head, tail = raw.rsplit(')', 1)
    except ValueError:
        _fail('proc-stat-malformed')
    prefix = head.split('(', 1)
    if len(prefix) != 2:
        _fail('proc-stat-malformed')
    try:
        observed_pid = int(prefix[0].strip())
    except ValueError:
        _fail('proc-stat-pid')
    if observed_pid != pid:
        _fail('proc-stat-pid')
    fields = tail.split()
    if len(fields) < 20 or fields[0] not in _PROC_STATES:
        _fail('proc-stat-shape')
    try:
        ppid = int(fields[1])
        pgid = int(fields[2])
        session = int(fields[3])
        starttime = int(fields[19])
    except (ValueError, IndexError):
        _fail('proc-stat-number')
    if ppid < 0 or pgid < 0 or session < 0 or starttime < 0:
        _fail('proc-stat-range')
    return {
        'pid': pid,
        'state': fields[0],
        'ppid': ppid,
        'pgid': pgid,
        'session': session,
        'starttime': starttime,
    }


def check_runtime():
    if sys.platform != 'linux':
        _fail('platform-not-linux')
    uid = os.getuid()
    if uid != _EXPECTED_UID:
        _fail('uid-not-1000')
    machine = platform.machine()
    if machine != _EXPECTED_MACHINE:
        _fail('machine-not-aarch64')
    if os.environ.get('PYTHONOPTIMIZE'):
        _fail('pythonoptimize-set')
    if sys.flags.optimize:
        _fail('optimize-enabled')
    version = platform.python_version()
    if version != _EXPECTED_VERSION:
        _fail('python-version')
    try:
        executable_path = Path(sys.executable).resolve()
        executable = str(executable_path)
        digest = hashlib.sha256(executable_path.read_bytes()).hexdigest()
    except OSError as error:
        _fail('interpreter-unreadable:' + type(error).__name__)
    if digest != _EXPECTED_SHA256:
        _fail('interpreter-sha256')
    boot_id = _boot_id()
    stat = _proc_stat(os.getpid())
    return {
        'uid': uid,
        'platform': sys.platform,
        'machine': machine,
        'version': version,
        'executable': executable,
        'pythonSha256': digest,
        'bootId': boot_id,
        'pid': stat['pid'],
        'pgid': stat['pgid'],
        'starttime': stat['starttime'],
    }
