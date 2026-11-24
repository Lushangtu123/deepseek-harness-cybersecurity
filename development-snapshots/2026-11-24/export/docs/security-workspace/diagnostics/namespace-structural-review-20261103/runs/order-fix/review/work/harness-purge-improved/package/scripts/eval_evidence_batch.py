"""Associate Python review evidence with a fixed source inventory and scan export."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

if sys.flags.isolated:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_guard_review import MAX_BYTES, review_eval_guard, review_plain_string_guard
from eval_import_review import discover_import_calls, review_import_flow

DIGEST = re.compile(r'[0-9a-f]{64}')
RELATIVE_PY = re.compile(r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}/){0,12}[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\.py')
GUARD_RULES = {
    'policy.harness.python.eval',
    'policy.harness.python.exec',
    'policy.harness.python.request-to-dynamic-code',
}
MAX_FILES = 64
MAX_CHECKS = 64
MAX_TOTAL_BYTES = 8 * MAX_BYTES


def read_bounded(file, limit):
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('input must be an ordinary file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('input exceeds byte limit')
    return raw


def pinned_sources(root, files):
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('invalid file inventory')
    if not root.is_dir() or root.resolve() != root:
        raise ValueError('source root must be a canonical directory')
    sources = {}
    remaining = MAX_TOTAL_BYTES
    for name, digest in files.items():
        if not RELATIVE_PY.fullmatch(name) or not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError('invalid pinned file')
        file = root / name
        if not file.is_file() or file.resolve() != file:
            raise ValueError('pinned file is missing or linked')
        raw = read_bounded(file, min(remaining, MAX_BYTES))
        if sha256(raw).hexdigest() != digest:
            raise ValueError('source digest mismatch')
        remaining -= len(raw)
        sources[name] = raw.decode('utf-8')
    return sources


def discovered_requests(sources):
    siblings = {}
    for name in sources:
        path = PurePosixPath(name)
        siblings.setdefault(path.parent, {})[path.stem] = name
    for caller, source in sources.items():
        path = PurePosixPath(caller)
        modules = {module: name for module, name in siblings[path.parent].items() if name != caller}
        if modules:
            for module, line in discover_import_calls(source, modules):
                yield caller, modules[module], line


def review_batch(root, manifest, scan):
    sources = pinned_sources(root, manifest.get('files'))
    discovery = manifest.get('discoverImports', False)
    if type(discovery) is not bool:
        raise ValueError('invalid import discovery option')
    requests = manifest.get('imports', [])
    hits = scan.get('results')
    if not isinstance(requests, list) or len(requests) > MAX_CHECKS or not isinstance(hits, list) or len(hits) > 2000:
        raise ValueError('invalid scan results or import requests')
    import_evidence, guard_evidence, plain_string_evidence = [], [], []
    seen = set()
    for request in requests:
        if not isinstance(request, dict) or set(request) != {'caller', 'callee', 'line'}:
            raise ValueError('invalid import request')
        caller, callee, line = request['caller'], request['callee'], request['line']
        if (not isinstance(caller, str) or not isinstance(callee, str)
                or caller not in sources or callee not in sources or caller == callee
                or PurePosixPath(caller).parent != PurePosixPath(callee).parent
                or type(line) is not int or line < 1):
            raise ValueError('invalid import request')
        key = (caller, callee, line)
        if key in seen:
            raise ValueError('duplicate import request')
        seen.add(key)
    discovered = set()
    if discovery:
        for key in discovered_requests(sources):
            discovered.add(key)
            seen.add(key)
            if len(seen) > MAX_CHECKS:
                raise ValueError('import check limit exceeded')
    for caller, callee, line in sorted(seen):
        evidence = review_import_flow(sources[caller], PurePosixPath(callee).stem, sources[callee], line)
        if evidence:
            import_evidence.append({**evidence, 'callerFile': caller, 'calleeFile': callee})
    import_count = len(seen)
    seen = set()
    for hit in hits:
        if not isinstance(hit, dict) or not isinstance(hit.get('path'), str) or not isinstance(hit.get('check_id'), str):
            raise ValueError('invalid scan finding')
        name, rule, start = hit['path'].removeprefix('/src/'), hit['check_id'], hit.get('start')
        if name not in sources or rule not in GUARD_RULES:
            continue
        line = start.get('line') if isinstance(start, dict) else None
        if type(line) is not int or line < 1:
            raise ValueError('invalid scan finding location')
        key = (name, rule, line)
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > MAX_CHECKS:
            raise ValueError('guard check limit exceeded')
        expected_sink = {'policy.harness.python.eval': 'eval', 'policy.harness.python.exec': 'exec'}.get(rule)
        evidence = review_eval_guard(sources[name], line) if expected_sink != 'exec' else None
        if evidence:
            guard_evidence.append({'finding': {'rule': rule, 'file': name, 'line': line}, 'evidence': evidence})
        evidence = review_plain_string_guard(sources[name],line)
        if evidence and (expected_sink is None or evidence['sink'] == expected_sink):
            plain_string_evidence.append({'finding':{'rule':rule,'file':name,'line':line},'evidence':evidence})
    return {'version': 1, 'guardChecks': len(seen), 'importChecks': import_count,
            'discoveredImportChecks': len(discovered),
            'guardEvidence': guard_evidence, 'importEvidence': import_evidence,
            'plainStringEvidence': plain_string_evidence}


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--managed':
        request = json.loads(sys.stdin.buffer.read(MAX_BYTES + 1))
        print(json.dumps(review_batch(Path(sys.argv[2]), {'files':request['files'],'discoverImports':True},
                                      {'results':request['results']})))
        raise SystemExit
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('scan', type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(read_bounded(args.manifest, MAX_BYTES))
        scan_raw = read_bounded(args.scan, MAX_TOTAL_BYTES)
        if not isinstance(manifest, dict) or manifest.get('scanSha256') != sha256(scan_raw).hexdigest():
            raise ValueError('scan digest mismatch')
        scan = json.loads(scan_raw)
        if not isinstance(scan, dict):
            raise ValueError('invalid scan export')
        report = review_batch(args.root.resolve(), manifest, scan)
    except (OSError, ValueError, RecursionError) as error:
        parser.exit(1, f'Batch rejected: {error}\n')
    print(json.dumps(report))
