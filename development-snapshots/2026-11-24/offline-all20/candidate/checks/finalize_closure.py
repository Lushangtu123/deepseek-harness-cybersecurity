#!/usr/bin/env python3
"""Sequential report / proof / seal / archive gate for the closure deliverable.

Stages are explicit and strictly ordered:

1. ``report``   - generate REPORT.md and read it back;
2. ``proof``    - independently verify the bound proof/evidence records;
3. ``manifest`` - build a closure input manifest from the frozen source
                  manifest plus REPORT.md, phase-result.json and the evidence
                  index, write it, then read back and re-hash every member;
4. ``archive``  - only after all three checked results succeed.  The offline
                  worker has no archive function: the real operator archive is
                  a separate action after independent review.

A failure or exception at any stage prevents every later stage; in particular
the archive function is never called.  No Docker, BPF, compiler, selfcheck,
fixture, target, admission or reviewer is used.
"""
import argparse
import hashlib
import json
import os
import stat
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _regular_bytes(path, label):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise ValueError("%s:missing" % label)
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("%s:symlink" % label)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("%s:type-change" % label)
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError("%s:unreadable:%s" % (label, type(error).__name__))


def _safe_parts(relative, label):
    if type(relative) is not str or not relative:
        raise ValueError('%s:path' % label)
    pure = Path(relative)
    if pure.is_absolute():
        raise ValueError('%s:path-escape:%s' % (label, relative))
    parts = pure.parts
    if not parts or any(part in {'', '.', '..'} for part in parts):
        raise ValueError('%s:path-escape:%s' % (label, relative))
    return parts


def _relative_under(base, path, label):
    base = Path(base).resolve()
    value = Path(path)
    if not value.is_absolute():
        value = base / value
    try:
        normalized = Path(os.path.normpath(str(value)))
    except (OSError, ValueError):
        raise ValueError('%s:path' % label)
    try:
        relative = normalized.relative_to(base)
    except ValueError:
        raise ValueError('%s:path-escape:%s' % (label, value))
    parts = relative.parts
    if not parts or any(part in {'', '.', '..'} for part in parts):
        raise ValueError('%s:path' % label)
    return str(Path(*parts))


def _prepare_destination(base, relative, label):
    parts = _safe_parts(relative, label)
    current = Path(base)
    try:
        base_info = current.lstat()
    except FileNotFoundError:
        try:
            current.mkdir(parents=True)
        except OSError as error:
            raise ValueError('%s:mkdir:%s' % (label, type(error).__name__))
        base_info = current.lstat()
    except OSError as error:
        raise ValueError('%s:unreadable:%s' % (label, type(error).__name__))
    if stat.S_ISLNK(base_info.st_mode):
        raise ValueError('%s:symlink:%s' % (label, str(current)))
    if not stat.S_ISDIR(base_info.st_mode):
        raise ValueError('%s:type:%s' % (label, str(current)))
    for part in parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as error:
                raise ValueError('%s:mkdir:%s' % (label, type(error).__name__))
            try:
                info = current.lstat()
            except OSError as error:
                raise ValueError('%s:unreadable:%s' % (label, type(error).__name__))
        except OSError as error:
            raise ValueError('%s:unreadable:%s' % (label, type(error).__name__))
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('%s:symlink:%s' % (label, str(current)))
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('%s:type:%s' % (label, str(current)))
    return current / parts[-1]


def _remove_if_same_inode(path, info):
    if info is None:
        return False
    try:
        current = Path(path).lstat()
    except OSError:
        return False
    if not stat.S_ISREG(current.st_mode):
        return False
    if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
        return False
    try:
        os.unlink(str(path))
        return True
    except OSError:
        return False


def _atomic_write_bytes(path, data, label):
    if type(data) is not bytes:
        raise ValueError('%s:data' % label)
    final = Path(path)
    parent = final.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ValueError('%s:mkdir:%s' % (label, type(error).__name__))
    try:
        final.lstat()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ValueError('%s:unreadable:%s' % (label, type(error).__name__))
    else:
        raise ValueError('%s:exists' % label)
    pending = parent / ('.%s.pending-%d-%s' % (
        final.name, os.getpid(), os.urandom(8).hex()))
    fd = None
    pending_exists = False
    published_info = None
    try:
        fd = os.open(str(pending), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        pending_exists = True
        with os.fdopen(fd, 'wb') as handle:
            fd = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        readback = _regular_bytes(pending, label + ':pending')
        if readback != data:
            raise ValueError('%s:pending-readback' % label)
        try:
            pending_info = pending.lstat()
        except OSError as error:
            raise ValueError('%s:unreadable:%s' % (label, type(error).__name__))
        try:
            os.link(str(pending), str(final))
        except FileExistsError:
            raise ValueError('%s:exists' % label)
        except OSError as error:
            raise ValueError('%s:publish:%s' % (label, type(error).__name__))
        published_info = pending_info
        try:
            os.unlink(str(pending))
            pending_exists = False
        except OSError:
            pending_exists = True
        final_body = _regular_bytes(final, label)
        if final_body != data:
            raise ValueError('%s:readback' % label)
        return {'ok': True, 'path': str(final),
                'sha256': hashlib.sha256(data).hexdigest(),
                'bytes': len(data)}
    except BaseException:
        _remove_if_same_inode(final, published_info)
        if pending_exists:
            try:
                os.unlink(str(pending))
            except OSError:
                pass
        raise
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _add_file(files, relative, digest, label):
    if relative in files and files[relative] != digest:
        raise ValueError('%s:conflict:%s' % (label, relative))
    files[relative] = digest


def _materialize_bytes(base, relative, body, label):
    dest = _prepare_destination(base, relative, label)
    try:
        info = dest.lstat()
    except FileNotFoundError:
        _atomic_write_bytes(dest, body, label)
    except OSError as error:
        raise ValueError('%s:unreadable:%s' % (label, type(error).__name__))
    else:
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('%s:symlink:%s' % (label, relative))
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('%s:type:%s' % (label, relative))
        try:
            existing = dest.read_bytes()
        except OSError as error:
            raise ValueError('%s:unreadable:%s' % (label, type(error).__name__))
        if existing != body:
            raise ValueError('%s:destination-exists:%s' % (label, relative))
    actual, digest = _safe_member(base, relative, label)
    if actual != body:
        raise ValueError('%s:readback:%s' % (label, relative))
    return digest, len(body)


def _normalize_relative(value, label):
    return str(Path(*_safe_parts(value, label)))


def _lstat_regular_under(base, relative, label):
    parts = _safe_parts(relative, label)
    current = Path(base)
    info = None
    for part in parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            raise ValueError('%s:missing:%s' % (label, relative))
        except OSError as error:
            raise ValueError('%s:unreadable:%s:%s' % (label, relative, type(error).__name__))
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('%s:symlink:%s' % (label, relative))
    if info is None or not stat.S_ISREG(info.st_mode):
        raise ValueError('%s:type-change:%s' % (label, relative))
    return current, info


def _read_actual_artifact(base, relative, role, suite, label=None):
    label = label or ('artifact:' + role)
    if role in ('capture', 'result') and label in ('capture', 'result'):
        label = 'member'
    relative = _normalize_relative(relative, label)
    path, before = _lstat_regular_under(base, relative, label)
    try:
        body = path.read_bytes()
    except OSError as error:
        raise ValueError('%s:unreadable:%s:%s' % (label, relative, type(error).__name__))
    try:
        after = path.lstat()
    except OSError as error:
        raise ValueError('%s:unreadable:%s:%s' % (label, relative, type(error).__name__))
    if stat.S_ISLNK(after.st_mode) or not stat.S_ISREG(after.st_mode):
        raise ValueError('%s:type-change:%s' % (label, relative))
    if before.st_dev != after.st_dev or before.st_ino != after.st_ino:
        raise ValueError('%s:identity-change:%s' % (label, relative))
    if before.st_size != len(body) or after.st_size != len(body):
        raise ValueError('%s:size-change:%s' % (label, relative))
    try:
        source_path = str(path.resolve())
    except OSError:
        source_path = str(path)
    return body, {
        'suite': suite,
        'role': role,
        'sourcePath': source_path,
        'relativePath': relative,
        'sha256': hashlib.sha256(body).hexdigest(),
        'bytes': len(body),
        'identity': [before.st_dev, before.st_ino],
    }

def _relative_from_absolute_under(base, value, label):
    base_value = Path(os.path.abspath(str(base)))
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ValueError('%s:path' % label)
    candidate_abs = Path(os.path.abspath(str(candidate)))
    base_norm = _normalize_system_prefix_path(base_value)
    candidate_norm = _normalize_system_prefix_path(candidate_abs, base_norm)
    try:
        relative = candidate_norm.relative_to(base_norm)
    except ValueError:
        raise ValueError('%s:path-escape:%s' % (label, value))
    parts = relative.parts
    if not parts or any(part in {'', '.', '..'} for part in parts):
        raise ValueError('%s:path:%s' % (label, value))
    return str(Path(*parts))


_SYSTEM_PREFIX_ALIASES = (
    ('/var', '/private/var'),
    ('/tmp', '/private/tmp'),
    ('/etc', '/private/etc'),
)

def _system_alias_ok(short, canonical):
    try:
        if not os.path.islink(short):
            return False
        target = os.readlink(short)
    except OSError:
        return False
    if not os.path.isabs(target):
        target = os.path.join(os.path.dirname(short), target)
    return os.path.normpath(target) == os.path.normpath(canonical)

def _normalize_system_prefix_path(path, base_norm=None):
    text = os.path.normpath(str(path))
    for short, canonical in _SYSTEM_PREFIX_ALIASES:
        if text != short and not text.startswith(short + os.sep):
            continue
        if not _system_alias_ok(short, canonical):
            continue
        if base_norm is not None:
            base_text = os.path.normpath(str(base_norm))
            canonical_text = os.path.normpath(canonical)
            if not (base_text == canonical_text or base_text.startswith(canonical_text + os.sep)):
                continue
        remainder = text[len(short):].lstrip(os.sep)
        return Path(canonical) if not remainder else Path(canonical) / remainder
    return Path(text)

def _capture_sibling_relative(capture_relative, value, label):
    parts = _safe_parts(value, label)
    parent = Path(capture_relative).parent
    if str(parent) == '.':
        combined = Path(*parts)
    else:
        combined = parent / Path(*parts)
    return str(Path(*_safe_parts(str(combined), label)))


def _capture_result_relative(base, capture):
    value = capture.get('resultFile')
    if type(value) is not str or not value:
        raise ValueError('capture:result-path')
    cwd = capture.get('cwd')
    if type(cwd) is not str or not cwd or not Path(cwd).is_absolute():
        raise ValueError('capture:result-path')
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    return _relative_from_absolute_under(base, candidate, 'result')


def _artifact_for(artifacts, role):
    for item in artifacts:
        if type(item) is dict and item.get('role') == role:
            return item
    raise ValueError('artifact:role:%s' % role)


def _check_optional_entry_field(entry, field, expected, label):
    if field not in entry:
        return
    if entry.get(field) != expected:
        raise ValueError('%s:%s' % (label, field))


def _check_legacy_raw_fields(entry, role, artifact):
    prefix = role
    _check_optional_entry_field(entry, prefix + 'File', artifact['relativePath'], 'raw:' + prefix)
    _check_optional_entry_field(entry, prefix + 'Sha256', artifact['sha256'], 'raw:' + prefix)
    for name in ('Bytes', 'Size', 'Count'):
        _check_optional_entry_field(entry, prefix + name, artifact['bytes'], 'raw:' + prefix)


def _check_capture_raw_claim(capture, side, artifact):
    expected_bytes = capture.get(side + 'Bytes')
    if type(expected_bytes) is not int or expected_bytes < 0:
        raise ValueError('raw:' + side + '-bytes')
    if expected_bytes != artifact['bytes']:
        raise ValueError('raw:' + side + '-bytes')
    expected_sha = capture.get(side + 'Sha256')
    if type(expected_sha) is not str or not expected_sha:
        raise ValueError('raw:' + side + '-digest')
    if expected_sha != artifact['sha256']:
        raise ValueError('raw:' + side + '-digest')


def _resolve_member_under(base, value, capture_path, cwd, label):
    base = Path(base).resolve()
    capture_path = Path(capture_path)
    if label == 'result':
        candidate = Path(value)
        if not candidate.is_absolute():
            if type(cwd) is not str or not cwd or not Path(cwd).is_absolute():
                raise ValueError('capture:result-path')
            candidate = Path(cwd) / candidate
        relative = _relative_from_absolute_under(base, candidate, 'result')
    else:
        if type(value) is not str or not value:
            raise ValueError('%s:path' % label)
        parts = _safe_parts(value, label)
        candidate = capture_path.parent / Path(*parts)
        relative = _relative_from_absolute_under(base, candidate, label)
    body, _artifact = _read_actual_artifact(base, relative, label, None, label)
    return relative, body, hashlib.sha256(body).hexdigest()


def resolve_capture_artifacts(base, capture_relative, entry=None):
    base = Path(base).resolve()
    capture_relative = _normalize_relative(capture_relative, 'capture')
    capture_body, capture_artifact = _read_actual_artifact(
        base, capture_relative, 'capture', None, 'capture')
    if entry is not None:
        if type(entry) is not dict:
            raise ValueError('index:entry-shape')
        entry_capture_file = entry.get('captureFile')
        if type(entry_capture_file) is not str or not entry_capture_file:
            raise ValueError('index:entry-capture-file')
        if _normalize_relative(entry_capture_file, 'member') != capture_relative:
            raise ValueError('index:entry-capture-file')
        capture_declared = entry.get('captureSha256')
        if type(capture_declared) is not str or not capture_declared:
            raise ValueError('index:entry-capture-sha')
        if capture_declared != capture_artifact['sha256']:
            raise ValueError('member:digest:' + capture_relative)
    try:
        capture = json.loads(capture_body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError('capture:json:%s' % type(error).__name__)
    if type(capture) is not dict:
        raise ValueError('capture:shape')
    suite = capture.get('suite')
    if type(suite) is not str or not suite:
        raise ValueError('capture:suite')
    capture_artifact['suite'] = suite
    if entry is not None:
        if entry.get('suite') != suite:
            raise ValueError('capture:suite')
        command = capture.get('command')
        if (not _is_command(command)
                or not _is_command(entry.get('command'))
                or entry.get('command') != command):
            raise ValueError('capture:command')
    result_relative = _capture_result_relative(base, capture)
    result_body, result_artifact = _read_actual_artifact(
        base, result_relative, 'result', suite, 'result')
    try:
        result = json.loads(result_body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError('result:json:%s' % type(error).__name__)
    if type(result) is not dict:
        raise ValueError('result:shape')
    if entry is not None:
        entry_result_file = entry.get('resultFile')
        if type(entry_result_file) is not str or not entry_result_file:
            raise ValueError('index:entry-result-file')
        if _normalize_relative(entry_result_file, 'member') != result_relative:
            raise ValueError('capture:result-path')
        result_declared = entry.get('resultSha256')
        if type(result_declared) is not str or not result_declared:
            raise ValueError('index:entry-result-sha')
        if result_declared != result_artifact['sha256']:
            raise ValueError('member:digest:' + result_relative)
        capture_result_sha = capture.get('resultSha256')
        if type(capture_result_sha) is not str or not capture_result_sha:
            raise ValueError('capture:result-digest-required')
        if capture_result_sha != result_artifact['sha256']:
            raise ValueError('capture:result-digest')
    artifacts = [capture_artifact, result_artifact]
    for side in ('stdout', 'stderr'):
        value = capture.get(side + 'File')
        if type(value) is not str or not value:
            raise ValueError('raw:' + side + '-file')
        relative = _capture_sibling_relative(capture_relative, value, 'raw:' + side)
        body, artifact = _read_actual_artifact(
            base, relative, side, suite, 'raw:' + side)
        artifacts.append(artifact)
        if entry is not None:
            _check_capture_raw_claim(capture, side, artifact)
            _check_legacy_raw_fields(entry, side, artifact)
    rc_relative = _capture_sibling_relative(
        capture_relative, 'returncode.txt', 'raw:returncode')
    rc_body, rc_artifact = _read_actual_artifact(
        base, rc_relative, 'returncode', suite, 'raw:returncode')
    artifacts.append(rc_artifact)
    if entry is not None:
        declared_rc_file = capture.get('returncodeFile')
        if declared_rc_file is not None:
            if type(declared_rc_file) is not str or not declared_rc_file:
                raise ValueError('raw:returncode-file')
            declared_rel = _capture_sibling_relative(
                capture_relative, declared_rc_file, 'raw:returncode')
            _declared_path, declared_info = _lstat_regular_under(
                base, declared_rel, 'raw:returncode')
            if [declared_info.st_dev, declared_info.st_ino] != rc_artifact['identity']:
                raise ValueError('raw:returncode-file')
        try:
            rc_value = _returncode_value(rc_body)
        except ValueError as error:
            raise ValueError(str(error))
        capture_rc = capture.get('returncode')
        if type(capture_rc) is not int:
            raise ValueError('capture:returncode')
        if rc_value != capture_rc:
            raise ValueError('raw:returncode')
        if rc_value != 0:
            raise ValueError('raw:returncode')
        _check_legacy_raw_fields(entry, 'returncode', rc_artifact)
    return {'capture': capture, 'result': result, 'artifacts': artifacts}

def generate_report(evidence_index, report_path):
    payload, index_sha = _read_json_regular(evidence_index, 'evidence-index')
    if type(payload) is not dict:
        raise ValueError('evidence-index:shape')
    entries = payload.get('entries')
    if entries is not None and type(entries) is not list:
        raise ValueError('evidence-index:entries-shape')
    report_path = Path(report_path)
    lines = [
        '# Consumer closure report',
        '',
        'Status: **pending independent Codex/host review**.',
        '',
        'No real target, container, BPF program, compiler, selfcheck, admission',
        'or reviewer was executed by the offline implementation worker.',
        'R3 remains blocked; formal targets remain 0/16.',
        '',
        '## Bound evidence',
        '',
        '- evidence index: `%s`' % evidence_index,
        '- evidence index SHA-256: `%s`' % index_sha,
        '- evidence entries: %s' % (len(entries) if entries is not None else 'n/a'),
        '',
    ]
    for item in entries or []:
        if type(item) is not dict:
            continue
        label = item.get('suite') or item.get('file') or item.get('resultFile')
        digest = item.get('resultSha256') or item.get('sha256')
        if label:
            lines.append('- `%s` `%s`' % (label, digest))
    body = (chr(10).join(lines) + chr(10)).encode('utf-8')
    written = _atomic_write_bytes(report_path, body, 'report')
    actual = _regular_bytes(report_path, 'report')
    if actual != body:
        raise ValueError('report:readback')
    return {'ok': True, 'path': str(report_path),
            'sha256': written['sha256'], 'bytes': len(body)}


def _read_json_regular(path, label):
    raw = _regular_bytes(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("%s:json:%s" % (label, type(error).__name__))
    return value, hashlib.sha256(raw).hexdigest()


INDEX_KIND = "consumer-closure-evidence-index"
PROOF_KIND = "consumer-closure-proof"


def _safe_member(base, relative, label="member"):
    """Read one relative regular file, refusing escape, links and ambiguity."""
    if type(relative) is not str or not relative:
        raise ValueError("%s:path" % label)
    pure = Path(relative)
    if pure.is_absolute():
        raise ValueError("%s:path-escape:%s" % (label, relative))
    parts = pure.parts
    if not parts or any(part in {"..", ".", ""} for part in parts):
        raise ValueError("%s:path-escape:%s" % (label, relative))
    current = Path(base)
    info = None
    for part in parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            raise ValueError("%s:missing:%s" % (label, relative))
        except OSError as error:
            raise ValueError("%s:unreadable:%s:%s" % (
                label, relative, type(error).__name__))
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("%s:symlink:%s" % (label, relative))
    if info is None or not stat.S_ISREG(info.st_mode):
        raise ValueError("%s:type-change:%s" % (label, relative))
    try:
        body = current.read_bytes()
    except OSError as error:
        raise ValueError("%s:unreadable:%s:%s" % (
            label, relative, type(error).__name__))
    return body, hashlib.sha256(body).hexdigest()


def _json_member(base, relative, label):
    body, digest = _safe_member(base, relative, label)
    try:
        value = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("%s:json:%s" % (label, type(error).__name__))
    return value, digest


def _source_state(source_root):
    """Rehash every file declared by the actual source manifest."""
    source_root = Path(source_root).resolve()
    manifest_path = source_root / "protocol-manifest.json"
    body = _regular_bytes(manifest_path, "source-manifest")
    manifest_sha = hashlib.sha256(body).hexdigest()
    try:
        document = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("source-manifest:json:%s" % type(error).__name__)
    if type(document) is not dict or type(document.get("files")) is not dict:
        raise ValueError("source-manifest:files")
    actual = {}
    for relative, expected in sorted(document["files"].items()):
        _raw, digest = _safe_member(source_root, relative, "source")
        if digest != expected:
            raise ValueError("source:digest:%s" % relative)
        actual[relative] = digest
    if type(document.get("fileCount")) is int \
            and document["fileCount"] != len(actual):
        raise ValueError("source-manifest:file-count")
    return {
        "sourceRoot": source_root,
        "manifestPath": manifest_path,
        "manifestSha256": manifest_sha,
        "files": document["files"],
        "actual": actual,
    }


def _is_command(value):
    if type(value) is not list or not value:
        return False
    for item in value:
        if type(item) is not str or not item:
            return False
    return True
def _path_identity(path):
    return os.path.normcase(os.path.abspath(str(path)))
def _capture_result_identity(capture):
    value = capture.get('resultFile')
    if type(value) is not str or not value:
        raise ValueError('capture:result-path')
    candidate = Path(value)
    if not candidate.is_absolute():
        cwd = capture.get('cwd')
        if type(cwd) is not str or not cwd:
            raise ValueError('capture:result-path')
        candidate = Path(cwd) / candidate
    return _path_identity(candidate)
def _returncode_value(body):
    marker = bytes([10])
    if not body.endswith(marker):
        raise ValueError('raw:returncode')
    text_bytes = body[:-1]
    if not text_bytes:
        raise ValueError('raw:returncode')
    for value in text_bytes:
        if value < 48 or value > 57:
            raise ValueError('raw:returncode')
    text = text_bytes.decode('ascii')
    if text != '0' and text.startswith('0'):
        raise ValueError('raw:returncode')
    number = int(text)
    if str(number) != text:
        raise ValueError('raw:returncode')
    return number
def _source_failure_reason(message):
    policy_path = 'tools/closure-suite-plan.json'
    if policy_path in message and (
            'missing' in message or 'symlink' in message
            or 'unreadable' in message):
        return 'policy:unbound'
    return message
_FIXED_COUNTS = {
    'consumer-12': 12,
    'evidence-gate': 13,
    'record-validation-15': 15,
    'unified-recovery-27': 27,
    'association-recovery-21': 21,
    'recovery-close-24': 24,
    'formal-admission-15': 15,
    'original-28': 28,
    'end-lf-13': 13,
    'rev6-24': 24,
    'rev7-12': 12,
    'rev8-13': 13,
    'diagnostics-20': 20,
    'repair-11': 11,
    'buffer-preflight-29': 29,
    'pure-compile': 57,
    'buffer-red-6': 6,
    'baseline-verify': 87,
    'static': 300,
    'independent-116': 116,
}
_FULL_OFFLINE_SUITES = frozenset((
    'consumer-12',
    'evidence-gate',
    'record-validation-15',
    'unified-recovery-27',
    'association-recovery-21',
    'recovery-close-24',
    'formal-admission-15',
    'original-28',
    'end-lf-13',
    'rev6-24',
    'rev7-12',
    'rev8-13',
    'diagnostics-20',
    'repair-11',
    'buffer-preflight-29',
    'pure-compile',
    'buffer-red-6',
    'baseline-verify',
    'static',
    'independent-116',
))
_ROW_IDENTITY_FIELDS = ('id', 'name', 'test', 'check', 'file')
_INDEPENDENT_COMPONENTS = {
    'independent-component.py': (
        '596333233046287665d6dbaf4fc5527123613933ab1ba98ac6c543bacb2140b5', 65),
    'independent-recovery.py': (
        'e48968422f261b119cf6f9dc0743964f794ebe151317a27bd6a04add89bfbcf1', 6),
    'independent-association.py': (
        'bdd413211dc82b96fc417d9470a66c04d36e4645e4693da9d46b43e46d5317fa', 13),
    'independent-scope.py': (
        '94716aa9c6db8e448bbdd2068d2020b63b78f09f32a60a744e334dfaf21b3ba7', 8),
    'independent-validation.py': (
        '2a95df4396aa72e5c6d5dc98ee4e32de8666b288572ede8414077e7ed5cd438d', 12),
    'independent-consumers.py': (
        '0df55bccd2457964e17735715a51f74db7a2608c2975dc0dfffd427faad2b47b', 4),
    'independent-public-consumer.py': (
        '45b20b2b9103babc3c1dd54fb237889700ae5910f181b4f20c7e16402c734d47', 1),
    'independent-settlement-scope.py': (
        '74a44586f93f41373b636c32d7356fa34f5a56c6c859c2d3a3c34f5985f33e52', 5),
    'independent-public-main.py': (
        '1bc69e1a01815b364d0f863d108ab254a8b0ff6cc99bc85c6c8e38ec390ce923', 1),
    'independent-recovery-refusal.py': (
        '1ec741e8501ec2f927947cc594408243a9cf92dec5908dd0ca088bc6f8faf25a', 1),
}
_BASELINE_MANIFEST_SHA256 = (
    'fdeb973492f251cba0a9a7aaa0ee702afb76ba8c6b4768d057c6320b43880eb0')
_COMPILE_FILE_COUNT = 57
_STATIC_COMPLETE_ROW_COUNT = 300


def _row_identity(row, label):
    if type(row) is not dict:
        raise ValueError(label)
    values = []
    for field in _ROW_IDENTITY_FIELDS:
        if field in row:
            value = row.get(field)
            if type(value) is not str or not value:
                raise ValueError(label)
            values.append(value)
    if not values:
        raise ValueError(label)
    identity = values[0]
    for value in values[1:]:
        if value != identity:
            raise ValueError(label)
    return identity


def _validate_rows(rows, suite, label, require_file=False):
    if type(rows) is not list or not rows:
        raise ValueError(label)
    seen = set()
    files = []
    for row in rows:
        if type(row) is not dict:
            raise ValueError(label)
        if row.get('passed') is not True:
            raise ValueError('result:failed')
        if 'suite' in row and row.get('suite') != suite:
            raise ValueError('result:rows')
        if require_file:
            file_value = row.get('file')
            if type(file_value) is not str or not file_value:
                raise ValueError('result:rows')
            files.append(file_value)
        identity = _row_identity(row, label)
        if identity in seen:
            raise ValueError('result:rows')
        seen.add(identity)
    return seen, files


def _compile_source_files(files):
    found = set()
    for name in files:
        if type(name) is not str:
            continue
        if not name.endswith('.py'):
            continue
        if ((name.startswith(('tools/', 'checks/')) and name.count('/') == 1)
                or (name.startswith('checks/formal_admission/')
                    and name.count('/') == 2)):
            found.add(name)
    return found


def _validate_baseline_members(source_root):
    body, digest = _safe_member(
        source_root, 'baseline/protocol-manifest.json', 'baseline-manifest')
    if digest != _BASELINE_MANIFEST_SHA256:
        raise ValueError('baseline-manifest-digest')
    try:
        document = json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ValueError('baseline-manifest-json')
    if type(document) is not dict or type(document.get('files')) is not dict:
        raise ValueError('baseline-manifest-files')
    files = document['files']
    expected_count = _FIXED_COUNTS['baseline-verify']
    if len(files) != expected_count:
        raise ValueError('baseline-manifest-file-count')
    declared = document.get('fileCount')
    if declared is not None and (
            type(declared) is not int or declared != expected_count):
        raise ValueError('baseline-manifest-file-count')
    for relative, expected in sorted(files.items()):
        if (type(relative) is not str or not relative
                or type(expected) is not str or not expected):
            raise ValueError('baseline-manifest-files')
        parts = _safe_parts(relative, 'baseline-member')
        member_relative = str(Path('baseline') / Path(*parts))
        _body, actual = _safe_member(
            source_root, member_relative, 'baseline-member')
        if actual != expected:
            raise ValueError('baseline-member-digest')
    return True


def _validate_baseline_entry(result, source_root):
    if 'results' in result or 'checks' in result:
        raise ValueError('result:rows')
    mismatched = result.get('mismatched')
    if type(mismatched) is not list:
        raise ValueError('result:shape')
    if mismatched:
        raise ValueError('result:failed')
    expected = _FIXED_COUNTS['baseline-verify']
    file_count = result.get('fileCount')
    recomputed = result.get('recomputed')
    if (type(file_count) is not int or type(recomputed) is not int
            or file_count != expected or recomputed != expected):
        raise ValueError('result:counts')
    if result.get('manifestSha256') != _BASELINE_MANIFEST_SHA256:
        raise ValueError('result:counts')
    try:
        _validate_baseline_members(source_root)
    except ValueError as error:
        raise ValueError('result:baseline:%s' % error)
    return 1, 1


def _validate_independent_entry(result, suite, source):
    if 'results' in result or 'mismatched' in result:
        raise ValueError('result:rows')
    expected = _FIXED_COUNTS[suite]
    checks = result.get('checks')
    if type(checks) is not list or not checks:
        raise ValueError('result:rows')
    if result.get('allPassed') is not True:
        raise ValueError('result:rows')
    passed = result.get('passed')
    total = result.get('total')
    if (type(passed) is not int or type(total) is not int
            or passed != expected or total != expected
            or len(checks) != expected):
        raise ValueError('result:counts')
    candidate = result.get('candidateManifestSha256')
    if type(candidate) is not str or candidate != source['manifestSha256']:
        raise ValueError('result:source')
    _validate_rows(checks, suite, 'result:rows')
    components = result.get('components')
    if (type(components) is not list
            or len(components) != len(_INDEPENDENT_COMPONENTS)):
        raise ValueError('result:components')
    seen = set()
    component_total = 0
    for component in components:
        if type(component) is not dict:
            raise ValueError('result:components')
        name = component.get('script')
        if (type(name) is not str or not name
                or name in seen or name not in _INDEPENDENT_COMPONENTS):
            raise ValueError('result:components')
        seen.add(name)
        pinned_sha, pinned_count = _INDEPENDENT_COMPONENTS[name]
        if component.get('scriptSha256') != pinned_sha:
            raise ValueError('result:components')
        exit_code = component.get('exitCode')
        if type(exit_code) is not int or exit_code != 0:
            raise ValueError('result:components')
        component_passed = component.get('passed')
        component_total_value = component.get('total')
        if (type(component_passed) is not int
                or type(component_total_value) is not int
                or component_passed != pinned_count
                or component_total_value != pinned_count):
            raise ValueError('result:components')
        component_total += component_total_value
    if seen != set(_INDEPENDENT_COMPONENTS) or component_total != expected:
        raise ValueError('result:components')
    return expected, expected


def _validate_ordinary_entry(result, suite, source, scope):
    if 'checks' in result or 'mismatched' in result:
        raise ValueError('result:rows')
    if 'failed' not in result:
        raise ValueError('result:failed')
    failed = result.get('failed')
    if type(failed) is not list or failed:
        raise ValueError('result:failed')
    rows = result.get('results')
    if type(rows) is not list or not rows:
        raise ValueError('result:rows')
    expected = _FIXED_COUNTS.get(suite)
    if expected is None and scope != 'diagnostic-contract':
        raise ValueError('policy:coverage')
    passed = result.get('passed')
    total = result.get('total')
    if (type(passed) is not int or type(total) is not int
            or passed <= 0 or total <= 0):
        raise ValueError('result:counts')
    if expected is not None:
        if passed != expected or total != expected or len(rows) != expected:
            raise ValueError('result:counts')
    else:
        if passed != total or passed != len(rows):
            raise ValueError('result:counts')
    require_file = suite == 'pure-compile'
    _identities, files = _validate_rows(
        rows, suite, 'result:rows', require_file=require_file)
    if suite == 'pure-compile':
        expected_files = _compile_source_files(source['files'])
        if len(expected_files) != _COMPILE_FILE_COUNT:
            raise ValueError('result:counts')
        if len(files) != _COMPILE_FILE_COUNT or set(files) != expected_files:
            raise ValueError('result:rows')
    if suite == 'static' and len(rows) != _STATIC_COMPLETE_ROW_COUNT:
        raise ValueError('result:counts')
    return passed, total


def _policy_suites(source, source_root):
    relative = 'tools/closure-suite-plan.json'
    if relative not in source['files']:
        raise ValueError('policy:unbound')
    try:
        body, digest = _safe_member(source_root, relative, 'policy')
    except ValueError:
        raise ValueError('policy:unbound')
    if digest != source['files'][relative]:
        raise ValueError('policy:digest')
    try:
        policy = json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError('policy:json:%s' % type(error).__name__)
    if type(policy) is not dict:
        raise ValueError('policy:shape')
    if policy.get('kind') != 'consumer-closure-suite-plan':
        raise ValueError('policy:kind')
    if policy.get('version') != 1:
        raise ValueError('policy:version')
    scope = policy.get('scope')
    if scope not in {'offline-closure', 'diagnostic-contract'}:
        raise ValueError('policy:scope')
    required = policy.get('requiredSuites')
    if type(required) is not list or not required:
        raise ValueError('policy:required-suites')
    seen = set()
    for item in required:
        if type(item) is not str or not item:
            raise ValueError('policy:required-suites')
        if item in seen:
            raise ValueError('policy:required-suites')
        seen.add(item)
    if scope == 'offline-closure' and seen != set(_FULL_OFFLINE_SUITES):
        raise ValueError('policy:required-suites')
    return {'scope': scope, 'requiredSuites': seen}


def _validate_index(index, base, source_root):
    source_root = Path(source_root).resolve()
    base = Path(base).resolve()
    if type(index) is not dict:
        return {'ok': False, 'reason': 'index:shape'}
    if index.get('kind') != INDEX_KIND:
        return {'ok': False, 'reason': 'index:kind'}
    if index.get('version') != 1:
        return {'ok': False, 'reason': 'index:version'}
    try:
        source = _source_state(source_root)
    except ValueError as error:
        return {'ok': False, 'reason': _source_failure_reason(str(error))}
    try:
        policy = _policy_suites(source, source_root)
    except ValueError as error:
        return {'ok': False, 'reason': str(error)}
    scope = policy['scope']
    required_suites = policy['requiredSuites']
    declared_source = index.get('sourceManifest')
    if type(declared_source) is not dict:
        return {'ok': False, 'reason': 'index:source-manifest'}
    if declared_source.get('sha256') != source['manifestSha256']:
        return {'ok': False, 'reason': 'index:source-manifest-digest'}
    if declared_source.get('entries') != source['actual']:
        return {'ok': False, 'reason': 'index:source-entries'}
    if declared_source.get('fileCount') not in {None, len(source['actual'])}:
        return {'ok': False, 'reason': 'index:source-entries'}
    declared_checks = index.get('checks')
    if type(declared_checks) is dict:
        for name, value in sorted(declared_checks.items()):
            if value is not True:
                return {'ok': False, 'reason': 'index:check:' + str(name)}
    entries = index.get('entries')
    if type(entries) is not list or not entries:
        return {'ok': False, 'reason': 'index:entries'}
    seen_suites = set()
    artifact_identities = set()
    artifact_digests = set()
    total_passed = 0
    total_cases = 0
    validated_artifacts = []
    for entry in entries:
        if type(entry) is not dict:
            return {'ok': False, 'reason': 'index:entry-shape'}
        suite = entry.get('suite')
        if type(suite) is not str or not suite:
            return {'ok': False, 'reason': 'index:entry-suite'}
        command = entry.get('command')
        if not _is_command(command):
            return {'ok': False, 'reason': 'index:entry-command'}
        if suite in seen_suites:
            return {'ok': False, 'reason': 'index:duplicate'}
        if scope == 'offline-closure' and suite not in _FULL_OFFLINE_SUITES:
            return {'ok': False, 'reason': 'index:coverage'}
        seen_suites.add(suite)
        result_rel = entry.get('resultFile')
        if type(result_rel) is not str or not result_rel:
            return {'ok': False, 'reason': 'index:entry-result-file'}
        result_declared = entry.get('resultSha256')
        if type(result_declared) is not str or not result_declared:
            return {'ok': False, 'reason': 'index:entry-result-sha'}
        capture_rel = entry.get('captureFile')
        if type(capture_rel) is not str or not capture_rel:
            return {'ok': False, 'reason': 'index:entry-capture-file'}
        capture_declared = entry.get('captureSha256')
        if type(capture_declared) is not str or not capture_declared:
            return {'ok': False, 'reason': 'index:entry-capture-sha'}
        try:
            resolved = resolve_capture_artifacts(base, capture_rel, entry)
        except ValueError as error:
            return {'ok': False, 'reason': str(error)}
        capture = resolved['capture']
        result = resolved['result']
        artifacts = resolved['artifacts']
        capture_artifact = _artifact_for(artifacts, 'capture')
        result_artifact = _artifact_for(artifacts, 'result')
        for artifact in (capture_artifact, result_artifact):
            identity = tuple(artifact.get('identity') or [])
            digest = artifact.get('sha256')
            if identity in artifact_identities or digest in artifact_digests:
                return {'ok': False, 'reason': 'index:duplicate'}
            artifact_identities.add(identity)
            artifact_digests.add(digest)
        if type(result) is not dict:
            return {'ok': False, 'reason': 'result:shape'}
        if 'suite' in result and result.get('suite') != suite:
            return {'ok': False, 'reason': 'result:suite'}
        if 'allPassed' in result and result.get('allPassed') is not True:
            return {'ok': False, 'reason': 'result:rows'}
        if 'failed' in result:
            failed = result.get('failed')
            if type(failed) is not list:
                return {'ok': False, 'reason': 'result:failed'}
            if failed:
                return {'ok': False, 'reason': 'result:failed'}
        try:
            if suite == 'baseline-verify':
                passed, total = _validate_baseline_entry(result, source_root)
            elif suite == 'independent-116':
                passed, total = _validate_independent_entry(result, suite, source)
            else:
                passed, total = _validate_ordinary_entry(result, suite, source, scope)
        except ValueError as error:
            return {'ok': False, 'reason': str(error)}
        except (TypeError, KeyError, IndexError):
            return {'ok': False, 'reason': 'result:shape'}
        if capture.get('sourceUnchanged') is not True:
            return {'ok': False, 'reason': 'capture:source-unchanged'}
        if capture.get('sourceClosureOk') is not True:
            return {'ok': False, 'reason': 'capture:source-closure'}
        for side in ('sourceManifestBefore', 'sourceManifestAfter'):
            snapshot = capture.get(side)
            if type(snapshot) is not dict:
                return {'ok': False, 'reason': 'capture:source-map'}
            if snapshot.get('entries') != source['actual']:
                return {'ok': False, 'reason': 'capture:source-entries'}
            if snapshot.get('manifestSha256') != source['manifestSha256']:
                return {'ok': False, 'reason': 'capture:source-manifest-digest'}
            if snapshot.get('ok') is not True:
                return {'ok': False, 'reason': 'capture:source-closure'}
        total_passed += passed
        total_cases += total
        validated_artifacts.extend(artifacts)
    if seen_suites != required_suites:
        return {'ok': False, 'reason': 'index:coverage'}
    if scope == 'offline-closure' and seen_suites != set(_FULL_OFFLINE_SUITES):
        return {'ok': False, 'reason': 'index:coverage'}
    return {
        'ok': True,
        'decision': 'pass',
        'sourceManifestSha256': source['manifestSha256'],
        'sourceFileCount': len(source['actual']),
        'entryCount': len(entries),
        'passed': total_passed,
        'total': total_cases,
        'validatedArtifacts': validated_artifacts,
    }
def verify_proof(proof_path, evidence_index, source_root=ROOT):
    try:
        proof, proof_sha = _read_json_regular(proof_path, 'proof')
    except ValueError as error:
        return {'ok': False, 'reason': str(error)}
    if type(proof) is not dict:
        return {'ok': False, 'reason': 'proof:shape'}
    if proof.get('kind') != PROOF_KIND:
        return {'ok': False, 'reason': 'proof:kind'}
    if proof.get('version') != 1:
        return {'ok': False, 'reason': 'proof:version'}
    if proof.get('state') != 'verified':
        return {'ok': False, 'reason': 'proof:state'}
    if proof.get('decision') != 'pass':
        return {'ok': False, 'reason': 'proof:decision'}
    if proof.get('verdict') not in {None, 'pass'}:
        return {'ok': False, 'reason': 'proof:verdict'}
    source_root = Path(source_root).resolve()
    declared_root = proof.get('sourceRoot')
    if (type(declared_root) is not str
            or Path(declared_root).resolve() != source_root):
        return {'ok': False, 'reason': 'proof:source-root'}
    try:
        source = _source_state(source_root)
    except ValueError as error:
        return {'ok': False, 'reason': _source_failure_reason(str(error))}
    if proof.get('sourceManifestSha256') != source['manifestSha256']:
        return {'ok': False, 'reason': 'proof:source-manifest-digest'}
    try:
        index, index_sha = _read_json_regular(evidence_index, 'evidence-index')
    except ValueError as error:
        return {'ok': False, 'reason': str(error)}
    if proof.get('evidenceIndexSha256') != index_sha:
        return {'ok': False, 'reason': 'proof:evidence-index-digest'}
    base = Path(evidence_index).resolve().parent
    try:
        validated = _validate_index(index, base, source_root)
    except ValueError as error:
        return {'ok': False, 'reason': str(error)}
    if validated.get('ok') is not True:
        return validated
    if validated.get('sourceManifestSha256') != source['manifestSha256']:
        return {'ok': False, 'reason': 'proof:source-manifest-digest'}
    validated_artifacts = validated.get('validatedArtifacts')
    if type(validated_artifacts) is not list:
        return {'ok': False, 'reason': 'proof:validated-artifacts'}
    return {
        'ok': True,
        'decision': 'pass',
        'proofSha256': proof_sha,
        'evidenceIndexSha256': index_sha,
        'sourceManifestSha256': validated['sourceManifestSha256'],
        'sourceFileCount': validated['sourceFileCount'],
        'entryCount': validated['entryCount'],
        'passed': validated['passed'],
        'total': validated['total'],
        'validatedArtifacts': validated_artifacts,
    }
def _hash_member(base, relative):
    path = Path(base) / relative
    body = _regular_bytes(path, relative)
    return hashlib.sha256(body).hexdigest()


def _member_key(base, member, label='member'):
    base = Path(base).resolve()
    member = Path(member)
    if member.is_absolute():
        try:
            relative = member.relative_to(base)
        except ValueError:
            try:
                relative = Path(os.path.normpath(str(member))).relative_to(base)
            except ValueError:
                raise ValueError('%s:outside-base:%s' % (label, member))
        parts = relative.parts
        if not parts or any(part in {'', '.', '..'} for part in parts):
            raise ValueError('%s:path:%s' % (label, member))
        return str(Path(*parts))
    parts = _safe_parts(str(member), label)
    return str(Path(*parts))


def _source_dest_key(base, source_root, relative):
    source_root = Path(source_root).resolve()
    relative_parts = _safe_parts(relative, 'source')
    try:
        root_rel = source_root.relative_to(Path(base).resolve())
    except ValueError:
        return str(Path('source') / Path(*relative_parts))
    if str(root_rel) == '.':
        return str(Path(*relative_parts))
    return str(root_rel / Path(*relative_parts))


def _verify_proof_source(base, closure_members, source_state):
    for member in closure_members:
        key = _member_key(base, member, 'member')
        try:
            value, _digest = _json_member(base, key, 'member')
        except ValueError:
            continue
        if type(value) is dict and value.get('kind') == PROOF_KIND:
            declared = value.get('sourceManifestSha256')
            if declared != source_state['manifestSha256']:
                raise ValueError('source-changed-after-proof')
            return
    return None


def seal_closure(source_root, closure_manifest, closure_members,
                 required_members=None, *, expected_verification=None):
    source_root = Path(source_root).resolve()
    closure_manifest = Path(closure_manifest)
    base = closure_manifest.parent.resolve()
    try:
        closure_manifest.lstat()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ValueError('closure-manifest:unreadable:%s' % type(error).__name__)
    else:
        raise ValueError('closure-manifest:exists')
    member_records = []
    index_key = None
    proof_key = None
    index_count = 0
    proof_count = 0
    for member in closure_members:
        key = _member_key(base, member, 'member')
        body, digest = _safe_member(base, key, 'member')
        member_records.append((key, body, digest))
        try:
            document = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            continue
        if type(document) is not dict:
            continue
        kind = document.get('kind')
        if kind == INDEX_KIND:
            index_count += 1
            index_key = key
        elif kind == PROOF_KIND:
            proof_count += 1
            proof_key = key
    if index_count != 1 or proof_count != 1:
        raise ValueError('closure-index-proof:missing')
    index_path = base / index_key
    proof_path = base / proof_key
    fresh = verify_proof(proof_path, index_path, source_root=source_root)
    if type(fresh) is not dict or fresh.get('ok') is not True:
        reason = fresh.get('reason') if type(fresh) is dict else 'shape'
        raise ValueError('proof:%s' % reason)
    fresh_context = _verification_context(fresh)
    if expected_verification is not None:
        expected_context = _verification_context(expected_verification)
        if not _verification_context_equal(fresh_context, expected_context):
            raise ValueError('evidence:changed')
    source_state = _source_state(source_root)
    files = {}
    for relative, expected in sorted(source_state['files'].items()):
        body, digest = _safe_member(source_root, relative, 'source')
        if digest != expected:
            raise ValueError('source:%s:digest-mismatch' % relative)
        dest_key = _source_dest_key(base, source_root, relative)
        actual_digest, _actual_bytes = _materialize_bytes(
            base, dest_key, body, 'source:' + relative)
        if actual_digest != expected:
            raise ValueError('source:%s:digest-mismatch' % relative)
        _add_file(files, dest_key, expected, 'source')
    manifest_body = _regular_bytes(source_state['manifestPath'], 'source-manifest')
    manifest_digest = hashlib.sha256(manifest_body).hexdigest()
    if manifest_digest != source_state['manifestSha256']:
        raise ValueError('source-manifest:digest')
    manifest_key = _source_dest_key(base, source_root, 'protocol-manifest.json')
    _materialize_bytes(base, manifest_key, manifest_body, 'source-manifest')
    _add_file(files, manifest_key, manifest_digest, 'source-manifest')
    fresh_artifacts = fresh.get('validatedArtifacts')
    if type(fresh_artifacts) is not list or not fresh_artifacts:
        raise ValueError('proof:validated-artifacts')
    groups = {}
    for artifact in fresh_artifacts:
        if type(artifact) is not dict:
            raise ValueError('artifact:shape')
        suite = _safe_suite_component(artifact.get('suite'))
        role = artifact.get('role')
        if role not in _EVIDENCE_ROLE_NAMES:
            raise ValueError('artifact:role')
        groups.setdefault(suite, []).append(role)
    for suite, roles in groups.items():
        if sorted(roles) != sorted(_EVIDENCE_ROLE_NAMES):
            raise ValueError('artifact:roles:%s' % suite)
    validated_artifact_map = []
    for artifact in sorted(fresh_artifacts, key=_artifact_sort_key):
        suite = _safe_suite_component(artifact.get('suite'))
        role = artifact.get('role')
        archive_relative = str(Path('evidence') / suite / _EVIDENCE_ROLE_NAMES[role])
        record = _materialize_validated_artifact(
            base, artifact, archive_relative, files)
        validated_artifact_map.append(record)
    for key, body, digest in member_records:
        _add_file(files, key, digest, 'member')
    required_source = required_members or {
        'REPORT.md', 'phase-result.json',
        'checks-evidence-index.json', 'proof.json'}
    required = set()
    for relative in required_source:
        required.add(_member_key(base, relative, 'required'))
    missing = required - set(files)
    if missing:
        raise ValueError('closure-member-missing:' + ','.join(sorted(missing)))
    after = verify_proof(proof_path, index_path, source_root=source_root)
    if type(after) is not dict or after.get('ok') is not True:
        reason = after.get('reason') if type(after) is dict else 'shape'
        raise ValueError('proof:changed:%s' % reason)
    if not _verification_context_equal(
            fresh_context, _verification_context(after)):
        raise ValueError('evidence:changed')
    for relative, expected in sorted(files.items()):
        body, digest = _safe_member(base, relative, 'closure')
        if digest != expected:
            raise ValueError('closure-member:digest:%s' % relative)
    document = {
        'kind': 'consumer-closure-input-manifest',
        'version': 1,
        'state': 'pending-independent-review',
        'sourceRoot': str(source_root),
        'sourceManifestSha256': source_state['manifestSha256'],
        'selfExcluded': True,
        'files': files,
        'fileCount': len(files),
        'requiredClosureMembers': sorted(required),
        'validatedArtifactMap': validated_artifact_map,
        'validatedArtifactCount': len(validated_artifact_map),
        'targetExecutions': 0,
        'realContainers': 0,
        'realBpftrace': 0,
        'formalTargets': '0/16',
        'r3': 'blocked',
        'createdAt': utc_now(),
        'limitations': [
            'Source and raw receipts are rehashed from local paths recorded by the capture.',
            'Absolute capture provenance paths are preserved; package file and hash verification alone is not a portable execution proof.',
            'Full-suite and VM phase evidence remains pending independent review.',
        ],
    }
    data = (json.dumps(document, sort_keys=True, indent=1) + chr(10)).encode('utf-8')
    written = _atomic_write_bytes(closure_manifest, data, 'closure-manifest')
    return {'ok': True, 'path': str(closure_manifest),
            'sha256': written['sha256'], 'fileCount': len(files),
            'members': sorted(files)}


_EVIDENCE_ROLE_NAMES = {
    'capture': 'capture.json',
    'result': 'result.json',
    'stdout': 'stdout.bin',
    'stderr': 'stderr.bin',
    'returncode': 'returncode.txt',
}
_EVIDENCE_ROLE_ORDER = {
    'capture': 0,
    'result': 1,
    'stdout': 2,
    'stderr': 3,
    'returncode': 4,
}
def _artifact_sort_key(artifact):
    return (
        str(artifact.get('suite')),
        _EVIDENCE_ROLE_ORDER.get(artifact.get('role'), 99),
        str(artifact.get('relativePath')),
    )
def _safe_suite_component(value):
    if type(value) is not str or not value:
        raise ValueError('artifact:suite')
    for character in value:
        if not (('a' <= character <= 'z')
                or ('A' <= character <= 'Z')
                or ('0' <= character <= '9')
                or character in '-_'):
            raise ValueError('artifact:suite')
    return value
def _verification_context(value):
    if type(value) is not dict:
        raise ValueError('verification:shape')
    artifacts = value.get('validatedArtifacts')
    if type(artifacts) is not list:
        raise ValueError('verification:artifacts')
    records = []
    for artifact in artifacts:
        if type(artifact) is not dict:
            raise ValueError('verification:artifact')
        identity = artifact.get('identity')
        if type(identity) not in (list, tuple) or len(identity) != 2:
            raise ValueError('verification:identity')
        records.append({
            'suite': artifact.get('suite'),
            'role': artifact.get('role'),
            'sourcePath': artifact.get('sourcePath'),
            'relativePath': artifact.get('relativePath'),
            'sha256': artifact.get('sha256'),
            'bytes': artifact.get('bytes'),
            'identity': [identity[0], identity[1]],
        })
    records.sort(key=lambda item: (
        str(item.get('suite')),
        str(item.get('role')),
        str(item.get('relativePath')),
        str(item.get('sha256')),
    ))
    return {
        'proofSha256': value.get('proofSha256'),
        'evidenceIndexSha256': value.get('evidenceIndexSha256'),
        'sourceManifestSha256': value.get('sourceManifestSha256'),
        'validatedArtifacts': records,
    }
def _verification_context_equal(actual, expected):
    return actual == expected
def _materialize_validated_artifact(base, artifact, archive_relative, files):
    if type(artifact) is not dict:
        raise ValueError('artifact:shape')
    role = artifact.get('role')
    if role not in _EVIDENCE_ROLE_NAMES:
        raise ValueError('artifact:role')
    suite = _safe_suite_component(artifact.get('suite'))
    relative = _normalize_relative(artifact.get('relativePath'), 'artifact')
    declared_bytes = artifact.get('bytes')
    declared_sha = artifact.get('sha256')
    identity = artifact.get('identity')
    if type(declared_bytes) is not int or declared_bytes < 0:
        raise ValueError('artifact:bytes')
    if type(declared_sha) is not str or not declared_sha:
        raise ValueError('artifact:sha256')
    if type(identity) not in (list, tuple) or len(identity) != 2:
        raise ValueError('artifact:identity')
    if type(identity[0]) is not int or type(identity[1]) is not int:
        raise ValueError('artifact:identity')
    path, info = _lstat_regular_under(base, relative, 'artifact')
    if [info.st_dev, info.st_ino] != [identity[0], identity[1]]:
        raise ValueError('artifact:identity:%s' % relative)
    if info.st_size != declared_bytes:
        raise ValueError('artifact:size:%s' % relative)
    try:
        body = path.read_bytes()
    except OSError as error:
        raise ValueError('artifact:unreadable:%s:%s' % (
            relative, type(error).__name__))
    digest = hashlib.sha256(body).hexdigest()
    if len(body) != declared_bytes or digest != declared_sha:
        raise ValueError('artifact:digest:%s' % relative)
    actual_digest, actual_bytes = _materialize_bytes(
        base, archive_relative, body, 'artifact-copy:' + role)
    if actual_digest != declared_sha or actual_bytes != declared_bytes:
        raise ValueError('artifact:copy:%s' % archive_relative)
    copied_body, copied_digest = _safe_member(
        base, archive_relative, 'artifact-copy')
    if copied_digest != declared_sha or len(copied_body) != declared_bytes:
        raise ValueError('artifact:copy:%s' % archive_relative)
    if copied_body != body:
        raise ValueError('artifact:copy:%s' % archive_relative)
    _add_file(files, archive_relative, copied_digest, 'artifact')
    record = dict(artifact)
    record['archivePath'] = archive_relative
    record['suite'] = suite
    return record

def run_gate(source_root, evidence_index, proof_path, phase_result,
             report_path, closure_manifest, archive_function=None,
             report_generator=None, proof_verifier=None, hooks=None):
    '''Run the ordered gate.  Every stage result is explicitly checked.'''
    source_root = Path(source_root).resolve()
    evidence_index = Path(evidence_index).resolve()
    proof_path = Path(proof_path).resolve()
    phase_result = Path(phase_result).resolve()
    report_path = Path(report_path).resolve()
    closure_manifest = Path(closure_manifest).resolve()
    hooks = hooks or {}
    stages = []
    result = {
        'kind': 'consumer-closure-report-archive-gate',
        'version': 1,
        'state': 'running',
        'failedStage': None,
        'detail': None,
        'archiveCalls': 0,
        'stages': stages,
        'targetExecutions': 0,
        'realContainers': 0,
        'realBpftrace': 0,
        'formalTargets': '0/16',
        'r3': 'blocked',
    }

    def fail(stage, detail):
        stages.append({'stage': stage, 'ok': False, 'detail': str(detail)[:600],
                       'checkedAt': utc_now()})
        result['state'] = 'failed'
        result['failedStage'] = stage
        result['detail'] = str(detail)[:600]
        return result

    generator = report_generator or generate_report
    try:
        report = generator(evidence_index=evidence_index,
                           report_path=report_path)
    except BaseException as error:  # noqa: BLE001 - checked failure
        return fail('report', '%s:%s' % (type(error).__name__, error))
    if type(report) is not dict or report.get('ok') is not True:
        return fail('report', report)
    if not report_path.is_file() or os_is_link(report_path):
        return fail('report', 'report-missing-or-link')
    if sha(report_path) != report.get('sha256'):
        return fail('report', 'report-readback-mismatch')
    result['report'] = {'path': str(report_path),
                        'sha256': report.get('sha256'),
                        'bytes': report.get('bytes')}
    stages.append({'stage': 'report', 'ok': True,
                   'sha256': report.get('sha256'), 'checkedAt': utc_now()})
    hook = hooks.get('after_report')
    if hook is not None:
        hook()

    verifier = proof_verifier or verify_proof
    try:
        proof = verifier(proof_path, evidence_index, source_root=source_root)
    except BaseException as error:  # noqa: BLE001 - checked failure
        return fail('proof', '%s:%s' % (type(error).__name__, error))
    if type(proof) is not dict or proof.get('ok') is not True:
        return fail('proof', proof)
    try:
        proof_context = _verification_context(proof)
    except ValueError as error:
        return fail('proof', str(error))
    result['proof'] = proof
    stages.append({'stage': 'proof', 'ok': True,
                   'decision': proof.get('decision'),
                   'checkedAt': utc_now()})
    hook = hooks.get('after_proof')
    if hook is not None:
        hook()

    try:
        base = closure_manifest.parent
        required = set()
        for member in (report_path, phase_result, evidence_index, proof_path):
            try:
                required.add(str(member.resolve().relative_to(base)))
            except ValueError:
                raise ValueError('member:outside-closure-base:%s' % member)
        sealed = seal_closure(
            source_root, closure_manifest,
            [report_path, phase_result, evidence_index, proof_path],
            required_members=required,
            expected_verification=proof_context)
    except BaseException as error:  # noqa: BLE001 - checked failure
        return fail('manifest', '%s:%s' % (type(error).__name__, error))
    result['closureManifest'] = sealed
    result['readback'] = {'ok': sealed.get('ok') is True,
                          'members': sealed.get('members'),
                          'fileCount': sealed.get('fileCount')}
    stages.append({'stage': 'manifest', 'ok': True,
                   'sha256': sealed.get('sha256'),
                   'fileCount': sealed.get('fileCount'),
                   'checkedAt': utc_now()})

    if archive_function is None:
        result['state'] = 'pending-independent-review'
        result['archive'] = {'state': 'pending-operator-archive',
                             'archiveCalls': 0}
        stages.append({'stage': 'archive', 'ok': True,
                       'state': 'pending-operator-archive',
                       'checkedAt': utc_now()})
        return result
    try:
        archived = archive_function(closure_manifest)
    except BaseException as error:  # noqa: BLE001 - checked failure
        return fail('archive', '%s:%s' % (type(error).__name__, error))
    result['archiveCalls'] = 1
    result['archive'] = {'state': 'called', 'result': archived}
    result['state'] = 'completed'
    stages.append({'stage': 'archive', 'ok': True, 'checkedAt': utc_now()})
    return result

def os_is_link(path):
    try:
        return stat.S_ISLNK(Path(path).lstat().st_mode)
    except OSError:
        return True


def build_evidence_index(source_root, captures, out_path):
    source_root = Path(source_root).resolve()
    source = _source_state(source_root)
    out_path = Path(out_path)
    base = out_path.parent.resolve()
    entries = []
    seen_suites = set()
    seen_paths = set()
    for item in captures:
        if type(item) is dict:
            capture_value = item.get('capture') or item.get('captureFile') or item.get('path')
            suite_hint = item.get('suite')
            command_hint = item.get('command')
            result_hint = item.get('result')
        else:
            capture_value = item
            suite_hint = None
            command_hint = None
            result_hint = None
        if type(capture_value) is not str or not capture_value:
            raise ValueError('capture:path')
        capture_path = Path(capture_value)
        if capture_path.is_absolute():
            capture_rel = _relative_from_absolute_under(base, capture_path, 'capture')
        else:
            capture_rel = _normalize_relative(capture_value, 'capture')
        resolved = resolve_capture_artifacts(base, capture_rel, None)
        capture = resolved.get('capture')
        result = resolved.get('result')
        artifacts = resolved.get('artifacts')
        if type(capture) is not dict or type(result) is not dict or type(artifacts) is not list:
            raise ValueError('capture:shape')
        by_role = {}
        for artifact in artifacts:
            if type(artifact) is not dict:
                raise ValueError('artifact:shape')
            role = artifact.get('role')
            if role in by_role:
                raise ValueError('artifact:duplicate-role')
            by_role[role] = artifact
        for role in ('capture', 'result', 'stdout', 'stderr', 'returncode'):
            if role not in by_role:
                raise ValueError('artifact:missing:' + role)
        capture_artifact = by_role['capture']
        result_artifact = by_role['result']
        suite = capture.get('suite')
        if type(suite) is not str or not suite:
            raise ValueError('capture:suite-missing')
        if suite_hint is not None and suite_hint != suite:
            raise ValueError('capture:suite-mismatch')
        command = capture.get('command')
        if not _is_command(command):
            raise ValueError('capture:command')
        if command_hint is not None:
            if not _is_command(command_hint) or command_hint != command:
                raise ValueError('capture:command-mismatch')
        if result_hint is not None:
            _compare_result_hint(base, result_hint, result, result_artifact)
        if suite in seen_suites:
            raise ValueError('duplicate-suite:%s' % suite)
        seen_suites.add(suite)
        entry = {
            'suite': suite,
            'command': list(command),
            'captureFile': capture_artifact.get('relativePath'),
            'captureSha256': capture_artifact.get('sha256'),
            'resultFile': result_artifact.get('relativePath'),
            'resultSha256': result_artifact.get('sha256'),
        }
        for field in ('captureFile', 'captureSha256', 'resultFile', 'resultSha256'):
            value = entry.get(field)
            if type(value) is not str or not value:
                raise ValueError('entry:' + field)
        for artifact in artifacts:
            relative = artifact.get('relativePath')
            if type(relative) is not str or not relative:
                raise ValueError('artifact:path')
            if relative in seen_paths:
                raise ValueError('duplicate-path:%s' % relative)
            seen_paths.add(relative)
        entries.append(entry)
    if not entries:
        raise ValueError('index:entries')
    source_after = _source_state(source_root)
    if source_after['manifestSha256'] != source['manifestSha256'] or source_after['actual'] != source['actual']:
        raise ValueError('source:changed')
    payload = {
        'kind': INDEX_KIND,
        'version': 1,
        'state': 'completed',
        'sourceManifest': {
            'path': 'protocol-manifest.json',
            'sha256': source['manifestSha256'],
            'fileCount': len(source['actual']),
            'entries': dict(source['actual']),
        },
        'entries': entries,
        'checks': {
            'sourceUnchanged': True,
            'allReturncodesZero': True,
            'allResultsPassed': True,
        },
        'targetExecutions': 0,
        'realContainers': 0,
        'realBpftrace': 0,
        'formalTargets': '0/16',
        'r3': 'blocked',
        'createdAt': utc_now(),
    }
    validation = _validate_index(payload, base, source_root)
    if type(validation) is not dict or validation.get('ok') is not True:
        reason = validation.get('reason') if type(validation) is dict else 'shape'
        raise ValueError('evidence-index:%s' % reason)
    if validation.get('decision') != 'pass':
        raise ValueError('evidence-index:decision')
    if validation.get('sourceManifestSha256') not in {None, source['manifestSha256']}:
        raise ValueError('evidence-index:source-manifest')
    if validation.get('entryCount') not in {None, len(entries)}:
        raise ValueError('evidence-index:entries')
    source_final = _source_state(source_root)
    if source_final['manifestSha256'] != source['manifestSha256'] or source_final['actual'] != source['actual']:
        raise ValueError('source:changed')
    data = (json.dumps(payload, sort_keys=True, indent=1) + chr(10)).encode('utf-8')
    written = _atomic_write_bytes(out_path, data, 'evidence-index')
    return {'ok': True, 'path': str(out_path), 'sha256': written['sha256'],
            'entries': len(entries)}


def _compare_result_hint(base, hint, result, result_artifact):
    if type(hint) is dict:
        if hint != result:
            raise ValueError('result-hint:mismatch')
        return
    if type(hint) is not str or not hint:
        raise ValueError('result-hint:shape')
    hint_path = Path(hint)
    if hint_path.is_absolute():
        hint_rel = _relative_from_absolute_under(base, hint_path, 'result-hint')
    else:
        hint_rel = _normalize_relative(hint, 'result-hint')
    actual = result_artifact.get('relativePath')
    if type(actual) is not str or hint_rel != actual:
        raise ValueError('result-hint:mismatch')

def build_proof(source_root, evidence_index, out_path):
    source_root = Path(source_root).resolve()
    source = _source_state(source_root)
    evidence_index = Path(evidence_index)
    index, index_sha = _read_json_regular(evidence_index, 'evidence-index')
    base = evidence_index.parent.resolve()
    validation = _validate_index(index, base, source_root)
    if type(validation) is not dict or validation.get('ok') is not True:
        reason = validation.get('reason') if type(validation) is dict else 'shape'
        raise ValueError('evidence-index:%s' % reason)
    if validation.get('decision') != 'pass':
        raise ValueError('evidence-index:decision')
    if validation.get('sourceManifestSha256') != source['manifestSha256']:
        raise ValueError('evidence-index:source-manifest')
    source_after = _source_state(source_root)
    index_after, index_sha_after = _read_json_regular(evidence_index, 'evidence-index')
    if index_sha_after != index_sha:
        raise ValueError('evidence-index:changed')
    if source_after['manifestSha256'] != source['manifestSha256'] \
            or source_after['actual'] != source['actual']:
        raise ValueError('source:changed')
    payload = {
        'kind': PROOF_KIND,
        'version': 1,
        'state': 'verified',
        'decision': 'pass',
        'verdict': 'pass',
        'sourceRoot': str(source_root),
        'sourceManifestSha256': source['manifestSha256'],
        'sourceFileCount': len(source['actual']),
        'evidenceIndexSha256': index_sha,
        'entryCount': validation.get('entryCount'),
        'passed': validation.get('passed'),
        'total': validation.get('total'),
        'checks': {
            'sourceManifest': True,
            'evidenceIndex': True,
            'rawMembers': True,
            'derivedDecision': 'pass',
        },
        'targetExecutions': 0,
        'realContainers': 0,
        'realBpftrace': 0,
        'formalTargets': '0/16',
        'r3': 'blocked',
        'createdAt': utc_now(),
    }
    data = (json.dumps(payload, sort_keys=True, indent=1) + chr(10)).encode('utf-8')
    out_path = Path(out_path)
    written = _atomic_write_bytes(out_path, data, 'proof')
    try:
        info = out_path.lstat()
    except OSError:
        info = None
    try:
        verified = verify_proof(out_path, evidence_index, source_root=source_root)
        if type(verified) is not dict or verified.get('ok') is not True:
            reason = verified.get('reason') if type(verified) is dict else 'shape'
            raise ValueError('built-proof-unverified:%s' % reason)
    except BaseException:
        _remove_if_same_inode(out_path, info)
        raise
    return {'ok': True, 'path': str(out_path), 'sha256': written['sha256'],
            'verified': verified}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=str(ROOT))
    parser.add_argument("--evidence-index", required=True)
    parser.add_argument("--proof", required=True)
    parser.add_argument("--phase-result", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--closure-manifest", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    result = run_gate(
        source_root=Path(args.source_root),
        evidence_index=Path(args.evidence_index),
        proof_path=Path(args.proof),
        phase_result=Path(args.phase_result),
        report_path=Path(args.report),
        closure_manifest=Path(args.closure_manifest),
        archive_function=None,
    )
    payload = json.dumps(result, sort_keys=True, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["state"] in {"completed",
                                    "pending-independent-review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
