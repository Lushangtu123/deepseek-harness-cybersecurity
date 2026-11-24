"""Associate Python review evidence with a fixed source inventory and scan export."""
import argparse
import ast
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


MAPPING_PROTOCOL = 'python-sink-locations-1'


def location_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return sha256(raw).hexdigest()


def node_span(source, node):
    raw = source.encode('utf-8')
    offsets = [0]
    offsets.extend(index + 1 for index, byte in enumerate(raw) if byte == 10)
    def position(line, column):
        return {'line': line, 'col': column + 1, 'offset': offsets[line - 1] + column}
    return {'start': position(node.lineno, node.col_offset),
            'end': position(node.end_lineno, node.end_col_offset)}


def call_name(node):
    if isinstance(node.func, ast.Name):
        return node.func.id
    if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'builtins' and node.func.attr in {'eval', 'exec'}):
        return 'builtins.' + node.func.attr
    return None


def call_location(source, node, name):
    source_sha = sha256(source.encode('utf-8')).hexdigest()
    span = node_span(source, node)
    identity = {'sourceSha256': source_sha, 'callee': name, 'call': span}
    return {**identity, 'id': location_digest(identity), 'builtinIdentity': 'unverified',
            'argument': node_span(source, node.args[0]) if node.args and not isinstance(node.args[0], ast.Starred) else None}


def location_inventory(sources):
    if not isinstance(sources, dict) or not 1 <= len(sources) <= MAX_FILES:
        raise ValueError('invalid location sources')
    files = {}
    total = 0
    for name, source in sorted(sources.items()):
        if not RELATIVE_PY.fullmatch(name) or not isinstance(source, str):
            raise ValueError('invalid location source')
        raw = source.encode('utf-8')
        total += len(raw)
        if len(raw) > MAX_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('location source limit')
        entry = {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'state': 'completed', 'points': []}
        files[name] = entry
        try:
            if any(byte == 13 and raw[index:index+2] != b'\r\n' for index, byte in enumerate(raw)):
                raise ValueError('unsupported line ending')
            tree = ast.parse(source)
            points = [call_location(source, node, call_name(node)) for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and call_name(node) in {'eval', 'exec', 'builtins.eval', 'builtins.exec'}]
            if len(points) > MAX_CHECKS:
                entry.update(state='unavailable', reason='point-limit')
            else:
                entry['points'] = sorted(points, key=lambda point: point['call']['start']['offset'])
        except (SyntaxError, ValueError, RecursionError):
            entry.update(state='unavailable', reason='source-parse-unavailable')
    return {'version': 1, 'protocol': MAPPING_PROTOCOL, 'runtimePython': sys.version.split()[0], 'files': files}


def valid_source_span(source, start, end):
    raw = source.encode('utf-8')
    def valid(point):
        if not isinstance(point, dict) or set(point) != {'line', 'col', 'offset'}:
            return False
        if any(type(value) is not int for value in point.values()):
            return False
        offset = point['offset']
        if not 0 <= offset <= len(raw) or offset < len(raw) and raw[offset] & 0xc0 == 0x80:
            return False
        line = raw[:offset].count(b'\n') + 1
        column = offset - (raw.rfind(b'\n', 0, offset) + 1) + 1
        return (point['line'], point['col']) == (line, column)
    return valid(start) and valid(end) and start['offset'] < end['offset']


def map_findings(sources, inventory, hits):
    if inventory != location_inventory(sources):
        raise ValueError('location inventory changed')
    if not isinstance(hits, list) or len(hits) > 2000:
        raise ValueError('location finding limit')
    mappings = []
    for index, hit in enumerate(hits):
        row = {'index': index, 'state': 'unmatched', 'reason': 'invalid-finding'}
        mappings.append(row)
        if not isinstance(hit, dict):
            continue
        name = hit.get('path', '').removeprefix('/src/') if isinstance(hit.get('path'), str) else ''
        rule = hit.get('check_id')
        row.update(path=name, rule=rule, scannerSpan={'start': hit.get('start'), 'end': hit.get('end')})
        if not isinstance(rule, str):
            continue
        if rule not in GUARD_RULES:
            row.update(state='ignored', reason='unsupported-rule')
            continue
        if name not in sources:
            row['reason'] = 'source-not-in-inventory'
            continue
        start, end = hit.get('start'), hit.get('end')
        if not valid_source_span(sources[name], start, end):
            row['reason'] = 'missing-or-invalid-span'
            continue
        entry = inventory['files'][name]
        if entry['state'] != 'completed':
            row['reason'] = entry['reason']
            continue
        expected = {'policy.harness.python.eval': 'eval', 'policy.harness.python.exec': 'exec'}.get(rule)
        points = entry['points']
        candidates = []
        for point in points:
            call = point['call']
            contained = start['offset'] <= call['start']['offset'] and call['end']['offset'] <= end['offset']
            argument = point['argument']
            focused = expected is None and argument is not None and argument == {'start': start, 'end': end}
            if contained or focused:
                candidates.append((point, 'argument' if focused else 'call'))
        if len(candidates) != 1:
            row['reason'] = 'ambiguous-execution-points' if candidates else 'no-supported-execution-point'
            continue
        point, match = candidates[0]
        if expected is not None and point['callee'].split('.')[-1] != expected:
            row['reason'] = 'rule-execution-point-mismatch'
            continue
        row.pop('reason')
        row.update(state='bound', pointId=point['id'], match=match, point=point)
    return mappings


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
    inventory = location_inventory(sources)
    frozen_locations = manifest.get('locations', manifest.get('locationBinding', {}).get('inventory'))
    if frozen_locations is not None and frozen_locations != inventory:
        raise ValueError('frozen locations changed')
    mappings = map_findings(sources, inventory, hits)
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
            caller_calls = [node for node in ast.walk(ast.parse(sources[caller])) if isinstance(node, ast.Call) and node.lineno == evidence['callLine']]
            sink_points = [point for point in inventory['files'][callee]['points'] if point['call']['start']['line'] == evidence['sinkLine']]
            if len(caller_calls) == len(sink_points) == 1:
                import_evidence.append({**evidence, 'callerFile': caller, 'calleeFile': callee,
                    'callerLocation': call_location(sources[caller], caller_calls[0], call_name(caller_calls[0]) or 'unresolved'),
                    'sinkLocation': sink_points[0]})
    import_count = len(seen)
    seen = set()
    for hit, mapping in zip(hits, mappings):
        if not isinstance(hit, dict) or not isinstance(hit.get('path'), str) or not isinstance(hit.get('check_id'), str):
            continue
        name, rule, start = hit['path'].removeprefix('/src/'), hit['check_id'], hit.get('start')
        if name not in sources or rule not in GUARD_RULES:
            continue
        line = start.get('line') if isinstance(start, dict) else None
        if type(line) is not int or line < 1:
            continue
        precise = mapping['state'] == 'bound'
        legacy = 'end' not in hit and set(start) == {'line'}
        if not precise and not legacy:
            continue
        key = (name, rule, mapping['pointId'] if precise else line)
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > MAX_CHECKS:
            raise ValueError('guard check limit exceeded')
        point = mapping['point'] if precise else None
        if point is not None and point['callee'].startswith('builtins.'):
            continue
        expected_sink = {'policy.harness.python.eval': 'eval', 'policy.harness.python.exec': 'exec'}.get(rule)
        sink_line = point['call']['start']['line'] if precise else line
        span = point['call'] if precise else None
        finding = {'rule': rule, 'file': name, 'line': line}
        if precise:
            finding.update(pointId=point['id'], executionPoint=point, scannerSpan=mapping['scannerSpan'])
        evidence = review_eval_guard(sources[name], sink_line, call_span=span) if expected_sink != 'exec' else None
        if evidence:
            guard_evidence.append({'finding': finding, 'evidence': evidence})
        evidence = review_plain_string_guard(sources[name],sink_line,call_span=span)
        if evidence and (expected_sink is None or evidence['sink'] == expected_sink):
            plain_string_evidence.append({'finding':finding,'evidence':evidence})
    return {'version': 2, 'locations': inventory, 'findingLocations': mappings, 'guardChecks': len(seen), 'importChecks': import_count,
            'discoveredImportChecks': len(discovered),
            'guardEvidence': guard_evidence, 'importEvidence': import_evidence,
            'plainStringEvidence': plain_string_evidence}


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--managed':
        request = json.loads(sys.stdin.buffer.read(MAX_BYTES + 1))
        print(json.dumps(review_batch(Path(sys.argv[2]), {'files':request['files'],'discoverImports':True},
                                      {'results':request['results']})))
        raise SystemExit
    locating = len(sys.argv)>1 and sys.argv[1]=='--locations'
    if locating:sys.argv.pop(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('scan', type=Path, nargs='?' if locating else None)
    args = parser.parse_args()
    try:
        manifest = json.loads(read_bounded(args.manifest, MAX_BYTES))
        scan_raw = b'{"results":[]}' if locating else read_bounded(args.scan, MAX_TOTAL_BYTES)
        if not isinstance(manifest, dict) or manifest.get('scanSha256') != sha256(scan_raw).hexdigest():
            raise ValueError('scan digest mismatch')
        scan = json.loads(scan_raw)
        if not isinstance(scan, dict):
            raise ValueError('invalid scan export')
        if locating:
            report={'version':2,'operation':'locations','locations':location_inventory(pinned_sources(args.root.resolve(),manifest['files'])),'findingLocations':[]}
        else:report = review_batch(args.root.resolve(), manifest, scan)
    except (OSError, ValueError, RecursionError) as error:
        parser.exit(1, f'Batch rejected: {error}\n')
    print(json.dumps(report))
