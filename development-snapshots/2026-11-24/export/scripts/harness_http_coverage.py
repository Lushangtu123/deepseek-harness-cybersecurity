"""Verify an explicit main-page HTTP resource contract on the existing daily entry."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException, IncompleteRead
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import importlib.util
import json
import os
import re
import time

ORIGIN = 'http://127.0.0.1:49226'
MAX_BODY = 4 * 1024 * 1024
BASELINE_CONTRACT_SHA256 = 'a2c0e10664cd70caf40cdb75c42f38dea42686588db1b2b813cdbdfb2f4473a3'
BOOTSTRAP_PATHS = {'/plugins/', '/__harness/banner.js', '/__harness/storage.js'}


def asset_path(value):
    if not isinstance(value, str):
        return None
    if value.startswith('./'):
        value = value[2:]
    if not value.startswith('/'):
        value = '/' + value
    return value if re.fullmatch(r'/assets/[A-Za-z0-9_.-]{1,180}\.(?:js|css)', value) else None


def validate_contract(contract):
    if not isinstance(contract, dict) or contract.get('version') != 1 or contract.get('origin') != ORIGIN:
        raise ValueError('Invalid contract version or origin')
    rounds = contract.get('rounds')
    assets = contract.get('assets')
    if type(rounds) is not int or not 1 <= rounds <= 5 or not isinstance(assets, dict) or not 1 <= len(assets) <= 16:
        raise ValueError('Invalid bounded coverage plan')
    if not isinstance(contract.get('pageTitle'), str) or not 1 <= len(contract['pageTitle']) <= 100:
        raise ValueError('Invalid expected page title')
    if contract.get('baseHref') not in (None, './', '/'):
        raise ValueError('Unsupported document base')
    bootstraps=contract.get('bootstrapScripts',[])
    if not isinstance(bootstraps,list) or len(bootstraps)>3:
        raise ValueError('Invalid bootstrap inventory')
    keys=[]
    for entry in bootstraps:
        if not isinstance(entry,dict) or entry.get('path') not in BOOTSTRAP_PATHS or type(entry.get('queryPresent')) is not bool:
            raise ValueError('Invalid bootstrap reference')
        keys.append(entry['path'])
    if len(set(keys))!=len(keys):
        raise ValueError('Duplicate bootstrap expectation')
    hints=contract.get('bootstrapPreloads',[])
    if not isinstance(hints,list) or len(hints)>3:
        raise ValueError('Invalid bootstrap preload inventory')
    hint_paths=[]
    for entry in hints:
        if not isinstance(entry,dict) or entry.get('path') not in BOOTSTRAP_PATHS or type(entry.get('queryPresent')) is not bool or type(entry.get('count')) is not int or not 1<=entry['count']<=4:
            raise ValueError('Invalid bootstrap preload')
        hint_paths.append(entry['path'])
    if len(hint_paths)!=len(set(hint_paths)) or sum(e['count'] for e in hints)>8:
        raise ValueError('Duplicate or excessive bootstrap preload expectation')
    for path, entry in assets.items():
        if asset_path(path) != path or not isinstance(entry, dict):
            raise ValueError('Invalid contract asset path')
        if type(entry.get('bytes')) is not int or not 0 < entry['bytes'] <= MAX_BODY:
            raise ValueError('Invalid asset size')
        if not isinstance(entry.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            raise ValueError('Invalid asset digest')
        mime = entry.get('contentTypes')
        allowed = {'text/css'} if path.endswith('.css') else {'text/javascript', 'application/javascript'}
        if not isinstance(mime, list) or not mime or any(value not in allowed for value in mime):
            raise ValueError('Invalid asset MIME contract')
    return contract


def load_contract(raw, expected_digest):
    if expected_digest != BASELINE_CONTRACT_SHA256 or sha256(raw).hexdigest() != BASELINE_CONTRACT_SHA256:
        raise ValueError('Contract is not the pinned baseline')
    return validate_contract(json.loads(raw))


class PageReferences(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.assets = set()
        self.unsafe = 0
        self.in_title = False
        self.title = []
        self.base_hrefs = []
        self.bootstrap_scripts = []
        self.bootstrap_preloads = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'title':
            self.in_title = True
        if tag == 'base':
            value=values.get('href')
            self.base_hrefs.append(value if value in ('./','/') else '[unsupported]')
            if value not in ('./','/') or sum(name=='href' for name,_ in attrs)!=1:
                self.unsafe += 1
        href = values.get('href')
        href_path = urlsplit(href).path.lower() if isinstance(href, str) else ''
        link_asset = asset_path(href) is not None or href_path.endswith(('.js', '.css')) or (values.get('as') or '').lower() in {'script', 'style'}
        relevant = 'src' if tag == 'script' else 'href' if tag == 'link' and (link_asset or set((values.get('rel') or '').lower().split()) & {'stylesheet', 'modulepreload'}) else None
        if relevant is None:
            return
        if any(sum(name == key for name, _ in attrs) > 1 for key in [relevant, 'rel']):
            self.unsafe += 1
        if relevant not in values and tag == 'script':
            return  # Inline script text is not a direct resource reference.
        path = asset_path(values.get(relevant))
        if path is not None:
            self.assets.add(path)
            return
        # Explicit known local bootstrap paths are inventoried, not requested.
        value=values.get(relevant)
        parsed=urlsplit(value) if isinstance(value,str) else None
        local=parsed.path if parsed else ''
        if local.startswith('./'):local=local[2:]
        if not local.startswith('/'):local='/'+local
        if tag=='script' and parsed and not parsed.scheme and not parsed.netloc and not parsed.fragment and local in BOOTSTRAP_PATHS:
            self.bootstrap_scripts.append({'path':local,'queryPresent':'?' in value.split('#',1)[0]})
        elif tag=='link' and parsed and not parsed.scheme and not parsed.netloc and not parsed.fragment and local in BOOTSTRAP_PATHS and (values.get('rel') or '').lower()=='preload' and (values.get('as') or '').lower()=='script':
            self.bootstrap_preloads.append({'path':local,'queryPresent':'?' in value.split('#',1)[0]})
        else:
            self.unsafe += 1

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def header(headers, name):
    pairs = headers.items() if isinstance(headers, dict) else headers
    return next((value for key, value in pairs if key.lower() == name), '')


class UnverifiableResponseFraming(ValueError):
    pass


def response_framing(headers):
    pairs = list(headers.items()) if isinstance(headers, dict) else headers
    lengths = [value.strip() for key, value in pairs if key.lower() == 'content-length']
    encodings = [value.strip().lower() for key, value in pairs if key.lower() == 'transfer-encoding']
    if len(lengths) > 1 or len(encodings) > 1 or lengths and encodings:
        raise UnverifiableResponseFraming('Ambiguous response framing')
    if lengths and re.fullmatch('[0-9]+', lengths[0]):
        return 'content-length'
    if encodings == ['chunked']:
        return 'chunked'
    raise UnverifiableResponseFraming('No verifiable homepage length framing')


def read_response(response, *, require_framing):
    if require_framing:
        mode = response_framing(response.getheaders())
        if mode == 'chunked' and not response.chunked:
            raise UnverifiableResponseFraming('Unsupported chunked framing')
        if mode == 'content-length' and response.length != int(response.getheader('Content-Length')):
            raise UnverifiableResponseFraming('Inconsistent length framing')
    body = response.read(MAX_BODY + 1)
    if len(body) <= MAX_BODY and response.length not in (None, 0):
        raise IncompleteRead(body, response.length)
    return body


def measure(contract, fetch, round_number, path):
    row = {'round': round_number, 'path': path}
    start = time.monotonic()
    try:
        status, headers, body = fetch(path)
        row.update(status=status, bytes=len(body), contentType=header(headers, 'content-type').split(';', 1)[0].strip().lower())
        if len(body) > MAX_BODY:
            row['failure'] = 'BodyLimitExceeded'
        elif path == '/':
            row['responseFraming'] = response_framing(headers)
            if row['responseFraming'] == 'content-length' and int(header(headers, 'content-length')) != len(body):
                raise UnverifiableResponseFraming('Received homepage length mismatch')
            page = PageReferences()
            page.feed(body.decode('utf-8'))
            page.close()
            row.update(observedAssets=sorted(page.assets), unsafeReferences=page.unsafe,
                       baseHrefs=page.base_hrefs, bootstrapPreloads=sorted(page.bootstrap_preloads,key=lambda x:(x['path'],x['queryPresent'])), bootstrapScripts=sorted(page.bootstrap_scripts,key=lambda x:(x['path'],x['queryPresent'])),
                       titleMatches=''.join(page.title).strip() == contract['pageTitle'])
        else:
            row['sha256'] = sha256(body).hexdigest()
    except (OSError, HTTPException, ValueError) as error:
        row['failure'] = type(error).__name__
    row['elapsedMs'] = round((time.monotonic() - start) * 1000)
    return row


def evaluate(contract, reads, *, authenticated):
    validate_contract(contract)
    issues = []
    planned = ['/', *sorted(contract['assets'])]
    def issue(code, round_number=None, path=None):
        issues.append({'code': code, 'round': round_number, 'path': path})
    if authenticated is not True:
        issue('authentication-not-confirmed')
    if len(reads) != contract['rounds'] * len(planned):
        issue('total-read-count')
    if any(type(row.get('round')) is not int or row['round'] not in range(1, contract['rounds'] + 1) for row in reads):
        issue('unexpected-round')
    for number in range(1, contract['rounds'] + 1):
        group = [row for row in reads if row.get('round') == number]
        if Counter(row.get('path') for row in group) != Counter(planned):
            issue('round-read-set', number)
        for row in group:
            path = row.get('path')
            if path not in planned:
                issue('unexpected-read-path', number)
                continue
            if row.get('status') != 200 or row.get('failure') or type(row.get('bytes')) is not int or row['bytes'] <= 0:
                issue('read-failed', number, path)
            if path == '/':
                if row.get('responseFraming') not in {'content-length', 'chunked'}:
                    issue('html-framing', number, path)
                if row.get('contentType') != 'text/html' or row.get('titleMatches') is not True:
                    issue('html-identity', number, path)
                if row.get('observedAssets') != sorted(contract['assets']) or row.get('unsafeReferences') != 0:
                    issue('html-asset-set', number, path)
                expected_base=[] if contract.get('baseHref') is None else [contract['baseHref']]
                expected_bootstraps=sorted(contract.get('bootstrapScripts',[]),key=lambda x:(x['path'],x['queryPresent']))
                expected_hints=sorted([{'path':e['path'],'queryPresent':e['queryPresent']} for e in contract.get('bootstrapPreloads',[]) for _ in range(e['count'])],key=lambda x:(x['path'],x['queryPresent']))
                if row.get('baseHrefs')!=expected_base or row.get('bootstrapScripts')!=expected_bootstraps or row.get('bootstrapPreloads')!=expected_hints:
                    issue('html-bootstrap-inventory', number, path)
            else:
                expected = contract['assets'][path]
                if row.get('bytes') != expected['bytes'] or row.get('sha256') != expected['sha256']:
                    issue('asset-content', number, path)
                if row.get('contentType') not in expected['contentTypes']:
                    issue('asset-mime', number, path)
    return {'passed': not issues, 'issues': issues, 'reads': reads, 'expectedRounds': contract['rounds'],
            'expectedAssets': sorted(contract['assets']), 'expectedReads': len(planned) * contract['rounds'],
            'authenticationConfirmed': authenticated is True,
            'scope': 'main /assets/ bundles and HTML reference inventory; declared bootstrap bodies/query values and dynamic resources are not validated',
            'bootstrapBodiesValidated':False}


def run_probe(contract, fetch, *, authenticated):
    validate_contract(contract)
    reads = []
    for number in range(1, contract['rounds'] + 1):
        reads.append(measure(contract, fetch, number, '/'))
        with ThreadPoolExecutor(max_workers=4) as pool:
            reads.extend(pool.map(lambda path: measure(contract, fetch, number, path), sorted(contract['assets'])))
    return evaluate(contract, reads, authenticated=authenticated)


def exclusive_output(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--contract-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Reserve first: a previous result must never be overwritten or trigger new network work.
    try:
        output = exclusive_output(args.output)
    except OSError:
        parser.error('Cannot exclusively create output')
    with output:
        try:
            raw = args.contract.read_bytes()
            contract = load_contract(raw, args.contract_sha256)
            manager_path = Path.home() / 'Library/Application Support/Harness Purge Original/host-tools/manage.py'
            spec = importlib.util.spec_from_file_location('daily_coverage_manager', manager_path)
            manager = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(manager)
            manager.validate()
            if not manager.web_entry_listener_owned():
                raise RuntimeError('Managed entry is not listening')
            address = urlsplit((manager.ROOT / 'access-url.txt').read_text().strip())
            if address.scheme != 'http' or address.hostname != '127.0.0.1' or address.port != 49226 or address.path != '/' or not re.fullmatch(r'token=[A-Za-z0-9_-]+', address.query):
                raise ValueError('Unexpected private entry URL')
            cookie = ''
            def fetch(path):
                conn = HTTPConnection('127.0.0.1', 49226, timeout=15)
                try:
                    conn.request('GET', path, headers={'Cookie': cookie, 'Connection': 'close'})
                    response = conn.getresponse()
                    body = read_response(response, require_framing=path == '/')
                    return response.status, response.getheaders(), body
                finally:
                    conn.close()
            login_status, login_headers, _ = fetch('/?' + address.query)
            cookies = SimpleCookie()
            for name, value in login_headers:
                if name.lower() == 'set-cookie':
                    cookies.load(value)
            cookie = '; '.join(key + '=' + value.value for key, value in cookies.items())
            report = run_probe(contract, fetch, authenticated=login_status == 303 and bool(cookie))
            report.update(contractSha256=sha256(raw).hexdigest(), managedEntryOwned=True,
                          loginStatus=login_status, localEntry=ORIGIN, retries=0)
        except Exception as error:
            report = {'passed': False, 'state': 'setup-failed', 'failure': type(error).__name__, 'reads': []}
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(json.dumps({'passed': report['passed'], 'selectedReads': len(report['reads']),
                      'issueCount': len(report.get('issues', [])), 'failure': report.get('failure')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
