from pathlib import Path
from copy import deepcopy
from hashlib import sha256
from tempfile import TemporaryDirectory
import importlib.util,json,unittest
SOURCE=Path(__file__).resolve().parents[1]/'harness_http_coverage.py'
class Coverage(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.exists(),'HTTP coverage contract implementation is missing')
        spec=importlib.util.spec_from_file_location('coverage_probe',SOURCE);self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.assets={f'/assets/{n}.{ext}':(f'synthetic {n} {ext}').encode() for n,ext in [('a','js'),('b','css'),('c','js'),('d','css')]}
        self.contract={'version':1,'origin':'http://127.0.0.1:49226','rounds':3,'pageTitle':'DeepSeek Harness','assets':{p:{'bytes':len(v),'sha256':sha256(v).hexdigest(),'contentTypes':['text/css'] if p.endswith('.css') else ['text/javascript']} for p,v in self.assets.items()}}
    def html(self,paths=None):
        paths=list(self.assets) if paths is None else paths
        return ('<html><title>DeepSeek Harness</title>'+''.join('<script src=".'+p+'"></script>' if p.endswith('.js') else '<link rel="stylesheet" href="'+p+'">' for p in paths)+'</html>').encode()
    def run_probe(self,mutate=None):
        seen=[]
        def fetch(path):
            seen.append(path)
            value=(200,{'content-type':'text/html','content-length':str(len(self.html()))},self.html()) if path=='/' else (200,{'content-type':'text/css' if path.endswith('.css') else 'text/javascript'},self.assets[path])
            value=mutate(path,value) if mutate else value
            if path=='/' and 'content-length' in value[1]:value=(value[0],{**value[1],'content-length':str(len(value[2]))},value[2])
            return value
        report=self.m.run_probe(self.contract,fetch,authenticated=True)
        return report,seen
    def test_exact_three_rounds_and_hashes_pass(self):
        report,seen=self.run_probe();self.assertTrue(report['passed'],report);self.assertEqual(len(seen),15)
    def test_html_missing_reference_fails_even_when_all_planned_gets_return_200(self):
        report,_=self.run_probe(lambda p,v:(200,v[1],self.html(list(self.assets)[:-1])) if p=='/' else v)
        self.assertFalse(report['passed']);self.assertIn('html-asset-set',str(report['issues']))
    def test_zero_resources_fails(self):
        report,_=self.run_probe(lambda p,v:(200,v[1],self.html([])) if p=='/' else v);self.assertFalse(report['passed'])
    def test_same_count_wrong_resource_fails(self):
        report,_=self.run_probe(lambda p,v:(200,v[1],self.html(list(self.assets)[:-1]+['/assets/other.css'])) if p=='/' else v);self.assertFalse(report['passed'])
    def test_foreign_reference_is_not_requested_or_recorded(self):
        raw=self.html()+b'<script src="https://example.invalid/app.js?private=do-not-record"></script>'
        report,seen=self.run_probe(lambda p,v:(200,v[1],raw) if p=='/' else v)
        self.assertFalse(report['passed']);self.assertNotIn('example.invalid',json.dumps(report));self.assertTrue(all(p=='/' or p in self.assets for p in seen))
    def test_comment_and_inline_script_strings_are_not_html_references(self):
        raw=self.html()+b'<!-- <script src="/assets/fake.js"></script> --><script>const x="/assets/fake.js";</script>'
        report,_=self.run_probe(lambda p,v:(200,v[1],raw) if p=='/' else v);self.assertTrue(report['passed'],report)
    def test_wrong_hash_and_html_200_asset_fallback_fail(self):
        report,_=self.run_probe(lambda p,v:(200,v[1],b'<html>fallback</html>') if p.endswith('a.js') else v);self.assertFalse(report['passed'])
    def test_failed_http_read_fails(self):
        report,_=self.run_probe(lambda p,v:(503,v[1],b'') if p.endswith('b.css') else v);self.assertFalse(report['passed'])
    def test_incomplete_read_is_recorded_as_failure(self):
        from http.client import IncompleteRead
        def mutate(p,v):
            if p.endswith('c.js'):raise IncompleteRead(b'partial',10)
            return v
        report,_=self.run_probe(mutate);self.assertFalse(report['passed']);self.assertIn('IncompleteRead',str(report))
    def test_missing_or_duplicated_round_read_fails(self):
        report,_=self.run_probe();rows=deepcopy(report['reads']);rows[-1]=deepcopy(rows[-2])
        v=self.m.evaluate(self.contract,rows,authenticated=True);self.assertFalse(v['passed'])
        v=self.m.evaluate(self.contract,report['reads'][:-5],authenticated=True);self.assertFalse(v['passed'])
    def test_third_round_html_change_fails(self):
        count=0
        def mutate(p,v):
            nonlocal count
            if p=='/':
                count+=1
                if count==3:return 200,v[1],self.html([])
            return v
        report,_=self.run_probe(mutate);self.assertFalse(report['passed'])
    def test_unauthenticated_run_fails(self):
        report,_=self.run_probe();self.assertFalse(self.m.evaluate(self.contract,report['reads'],authenticated=False)['passed'])
    def test_unsafe_contract_path_rejected(self):
        value=deepcopy(self.contract);value['assets']['https://example.invalid/x.js']=value['assets'].pop('/assets/a.js')
        with self.assertRaises(ValueError):self.m.validate_contract(value)
    def test_duplicate_attribute_and_base_are_rejected(self):
        for suffix in [b'<script src="https://example.invalid/a.js" src="/assets/a.js"></script>',b'<base href="https://example.invalid/">']:
            report,_=self.run_probe(lambda p,v:(200,v[1],self.html()+suffix) if p=='/' else v);self.assertFalse(report['passed'])
    def test_declared_relative_base_and_bootstraps_are_inventoried_without_query_retention(self):
        self.contract['baseHref']='./'
        self.contract['bootstrapScripts']=[{'path':'/plugins/','queryPresent':True},{'path':'/__harness/banner.js','queryPresent':False},{'path':'/__harness/storage.js','queryPresent':False}]
        html=self.html()+b'<base href="./"><script src="plugins/?token=synthetic-do-not-record"></script><script src="/__harness/banner.js"></script><script src="/__harness/storage.js"></script>'
        report,seen=self.run_probe(lambda p,v:(200,v[1],html) if p=='/' else v)
        self.assertTrue(report['passed'],report);self.assertEqual(len(seen),15)
        self.assertNotIn('synthetic-do-not-record',json.dumps(report))
        self.assertNotIn('/plugins/',seen)
    def test_missing_declared_bootstrap_fails(self):
        self.contract['bootstrapScripts']=[{'path':'/__harness/banner.js','queryPresent':False}]
        report,_=self.run_probe();self.assertFalse(report['passed'])
    def method(self,name):
        value=getattr(self.m,name,None);self.assertTrue(callable(value),'Missing '+name);return value
    def test_extra_preload_or_prefetch_asset_fails(self):
        for rel in ['preload','prefetch']:
            report,_=self.run_probe(lambda p,v:(200,v[1],self.html()+('<link rel="'+rel+'" as="script" href="/assets/extra.js">').encode()) if p=='/' else v)
            self.assertFalse(report['passed'])
    def test_empty_query_separator_is_present(self):
        self.contract['bootstrapScripts']=[{'path':'/plugins/','queryPresent':False}]
        html=self.html()+b'<script src="/plugins/?"></script>'
        report,_=self.run_probe(lambda p,v:(200,v[1],html) if p=='/' else v);self.assertFalse(report['passed'])
        self.contract['bootstrapScripts'][0]['queryPresent']=True
        report,_=self.run_probe(lambda p,v:(200,v[1],html) if p=='/' else v);self.assertTrue(report['passed'],report)
    def test_bootstrap_path_must_be_unique(self):
        self.contract['bootstrapScripts']=[{'path':'/plugins/','queryPresent':False},{'path':'/plugins/','queryPresent':True}]
        with self.assertRaises(ValueError):self.m.validate_contract(self.contract)
    def test_alternate_self_consistent_contract_is_rejected_by_cli_loader(self):
        raw=json.dumps({**self.contract,'rounds':1}).encode()
        with self.assertRaises(ValueError):self.method('load_contract')(raw,sha256(raw).hexdigest())
    def test_pinned_real_contract_is_accepted_by_cli_loader(self):
        path=SOURCE.parent.parent/'docs/security-workspace/daily-http-contract.candidate.json'
        raw=path.read_bytes();self.assertEqual(self.method('load_contract')(raw,sha256(raw).hexdigest())['rounds'],3)
    def wire(self,raw):
        from http.client import HTTPResponse
        import io
        class Stream:
            def makefile(self,*args,**kwargs):return io.BytesIO(raw)
        response=HTTPResponse(Stream());response.begin();return response
    def test_content_length_body_is_verified(self):
        r=self.wire(b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nabc')
        self.assertEqual(self.method('read_response')(r,require_framing=True),b'abc')
    def test_short_content_length_body_is_rejected(self):
        from http.client import IncompleteRead
        r=self.wire(b'HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nabc')
        with self.assertRaises(IncompleteRead):self.method('read_response')(r,require_framing=True)
    def test_chunked_body_is_verified(self):
        r=self.wire(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n')
        self.assertEqual(self.method('read_response')(r,require_framing=True),b'abc')
    def test_truncated_chunked_body_is_rejected(self):
        from http.client import IncompleteRead
        r=self.wire(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n')
        with self.assertRaises(IncompleteRead):self.method('read_response')(r,require_framing=True)
    def test_unframed_close_delimited_homepage_is_rejected(self):
        r=self.wire(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n<html>prefix')
        with self.assertRaises(ValueError):self.method('read_response')(r,require_framing=True)
    def test_ambiguous_duplicate_lengths_are_rejected(self):
        r=self.wire(b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Length: 4\r\n\r\nabc')
        with self.assertRaises(ValueError):self.method('read_response')(r,require_framing=True)
    def test_transfer_encoding_and_length_are_rejected(self):
        r=self.wire(b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n')
        with self.assertRaises(ValueError):self.method('read_response')(r,require_framing=True)
    def test_missing_homepage_framing_cannot_pass_reference_inventory(self):
        report,_=self.run_probe(lambda p,v:(200,{'content-type':'text/html'},self.html()) if p=='/' else v)
        self.assertFalse(report['passed'])
    def test_declared_bootstrap_preload_count_is_separate_from_script_execution(self):
        self.contract['bootstrapPreloads']=[{'path':'/plugins/','queryPresent':True,'count':2}]
        hints=b'<link rel="preload" as="script" href="/plugins/?one"><link rel="preload" as="script" href="/plugins/?two">'
        report,_=self.run_probe(lambda p,v:(200,v[1],self.html()+hints) if p=='/' else v)
        self.assertTrue(report['passed'],report)
        self.assertNotIn('?one',json.dumps(report))
        report,_=self.run_probe(lambda p,v:(200,v[1],self.html()+b'<link rel="preload" as="script" href="/plugins/?one">') if p=='/' else v)
        self.assertFalse(report['passed'])
    def test_output_is_exclusive_and_private(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'result.json'
            with self.m.exclusive_output(p) as f:f.write('original')
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):self.m.exclusive_output(p)
            self.assertEqual(p.read_text(),'original')
if __name__=='__main__':unittest.main()
