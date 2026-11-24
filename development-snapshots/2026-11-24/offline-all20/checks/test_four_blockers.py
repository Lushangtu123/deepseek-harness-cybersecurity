"""Zero-VM controls. Fake suites are labelled unit-only; never detection evidence."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import unittest

R = Path(__file__).resolve().parents[1]
SOURCE = hashlib.sha256((R/'candidate/protocol-manifest.json').read_bytes()).hexdigest()


def load(name, p):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


m = load('four_blockers_batch', R/'operator/full20_batch.py')
b = load('four_blockers_bounded', R/'operator/bounded.py')
plan = json.loads((R/'operator/suite-plan.json').read_bytes())


def identity(pid=2147483647):
    return {'pid': pid, 'pgid': pid, 'starttime': 1,
            'bootId': '00000000-0000-0000-0000-000000000001', 'groupLeader': True}


class FourBlockers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=R/'checks')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'candidate').mkdir(); (self.root/'evidence').mkdir()

    def test_registry_accepts_actual_admitted_source(self):
        self.assertTrue(m.validate_registry(plan, SOURCE))
        bad = copy.deepcopy(plan); bad['sourceManifestSha256'] = '0'*64
        with self.assertRaises(ValueError): m.validate_registry(bad, SOURCE)

    def test_binding_checks_actual_manifest_bytes(self):
        fn = getattr(m, 'validate_binding', None)
        self.assertTrue(callable(fn), 'missing pure pre-resource binding check')
        raw = (R/'candidate/protocol-manifest.json').read_bytes()
        registry = json.dumps(plan).encode()
        self.assertEqual(fn(raw, registry, SOURCE), plan)
        for source, reg, admitted in [(raw+b' ', registry, SOURCE),
                                     (raw, registry, '0'*64),
                                     (raw, json.dumps(dict(plan, sourceManifestSha256='0'*64)).encode(), SOURCE)]:
            with self.assertRaises(ValueError): fn(source, reg, admitted)

    def test_host_and_guest_check_binding_before_resource_entry(self):
        for file, function in [('run_vm.py','_admission'), ('consumer_vm.py','_validate_packet')]:
            tree = ast.parse((R/'operator'/file).read_bytes())
            fn = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == function)
            self.assertTrue(any(isinstance(n,ast.Call) and
                            ((isinstance(n.func,ast.Name) and n.func.id=='validate_binding') or
                             (isinstance(n.func,ast.Attribute) and n.func.attr=='validate_binding'))
                            for n in ast.walk(fn)), file)

    def query(self, record, *, role=False, group_state='exited'):
        folder = self.root/('candidate/roles' if role else 'evidence/consumer-12')
        folder.mkdir(parents=True, exist_ok=True)
        (folder/('process-client-identity.json' if role else 'process.json')).write_text(json.dumps(record))
        if not role:
            (folder/'intent.json').write_text(json.dumps({'suite':'consumer-12','identityRequired':True,'createdBeforeProcess':True,'cwd':str(self.root/'candidate'),'command':['unit-only']}))
            (folder/'capture.json').write_text(json.dumps({'suite':'consumer-12','pid':record.get('pid'),'cleanupConfirmed':True,'unitOnly':True}))
        g = SimpleNamespace(group_state=Mock(return_value={'state': group_state}),
                            spawn_group_state=Mock(return_value={'state':'exited'}),
                            process_state=Mock(return_value={'state':'unknown','detail':'wrong-schema'}))
        with patch.object(m,'_load_guard',return_value=g), patch.object(m,'_owned_proc_state',return_value='absent',create=True):
            result = m._actual_process_quiescence(self.root, {})
        return result, g

    def test_wrapper_uses_group_identity_contract(self):
        (ok, detail), g = self.query({'pid':2147483647,'processGroup':2147483647,
                                     'originalPopenChild':True,'identity':identity()})
        self.assertTrue(ok, detail)
        g.group_state.assert_called_once_with(identity())
        g.spawn_group_state.assert_not_called(); g.process_state.assert_not_called()

    def test_role_uses_spawn_contract(self):
        rec = {'role':'client','preflightId':'a'*32,'spawnState':'started','identity':identity()}
        (ok, detail), g = self.query(rec, role=True)
        self.assertTrue(ok, detail)
        g.spawn_group_state.assert_called_once_with(rec)
        g.process_state.assert_not_called(); g.group_state.assert_not_called()

    def test_missing_wrapper_identity_stays_unknown(self):
        (ok, detail), g = self.query({'pid':2147483647,'processGroup':2147483647,'originalPopenChild':True})
        self.assertFalse(ok, detail); g.group_state.assert_not_called()

    def test_reused_identity_is_not_exit(self):
        (ok, detail), g = self.query({'pid':2147483647,'processGroup':2147483647,
                                     'originalPopenChild':True,'identity':identity()},group_state='reused')
        self.assertFalse(ok, detail)

    def test_self_declared_synthetic_does_not_skip_unknown(self):
        (ok, detail), g = self.query({'pid':2147483647,'processGroup':2147483647,
                                     'originalPopenChild':True,'synthetic':True,'kind':'fault-wrapper'})
        self.assertFalse(ok, detail)

    def test_unreadable_directory_unknown(self):
        hidden = self.root/'candidate/hidden'; hidden.mkdir()
        (hidden/'process-client-identity.json').write_text('{}')
        hidden.chmod(0)
        try:
            with self.assertRaises(PermissionError): list(os.scandir(hidden))
            with patch.object(m,'_load_guard',return_value=SimpleNamespace()):
                ok, detail = m._actual_process_quiescence(self.root, {})
        finally: hidden.chmod(0o700)
        self.assertFalse(ok, detail)

    def test_missing_required_tree_unknown(self):
        (self.root/'candidate').rmdir()
        with patch.object(m,'_load_guard',return_value=SimpleNamespace()):
            ok, detail = m._actual_process_quiescence(self.root, {})
        self.assertFalse(ok, detail)

    def test_linked_subtree_unknown(self):
        (self.root/'candidate/link').symlink_to(self.root/'evidence',target_is_directory=True)
        with patch.object(m,'_load_guard',return_value=SimpleNamespace()):
            ok, detail = m._actual_process_quiescence(self.root, {})
        self.assertFalse(ok, detail)

    def test_unclassified_record_returns_unknown_not_exception(self):
        (self.root/'evidence/process.json').write_text('{}')
        with patch.object(m,'_load_guard',return_value=SimpleNamespace()):
            ok, detail = m._actual_process_quiescence(self.root, {})
        self.assertFalse(ok, detail)

    def batch(self, query_mode):
        launches = []; captures = {}; queries = []
        manifest_raw = (R/'candidate/protocol-manifest.json').read_bytes()
        registry_raw = json.dumps(plan).encode()
        (self.root/'candidate/protocol-manifest.json').write_bytes(manifest_raw)
        (self.root/'operator').mkdir()
        (self.root/'operator/suite-plan.json').write_bytes(registry_raw)
        inputs = {'candidate/protocol-manifest.json':manifest_raw, 'operator/suite-plan.json':registry_raw}
        source = {'manifestSha256':SOURCE,'actual':{}}
        counts = dict(zip(plan['order'],[12,13,15,27,21,24,15,28,13,24,12,13,20,11,29,57,6,87,116,300]))
        def run(root, suite, args, expected, immutable, **kwargs):
            launches.append(suite)
            cap = Path(args[args.index('--run-dir')+1]); cap.mkdir(parents=True)
            (cap/'run.json').write_text('{}')
            output = Path(kwargs['result_file']); output.write_text('{"unitOnly":true,"semanticDecision":"unknown"}')
            producer = args[args.index('--')+1:]
            captures[str(cap/'run.json')] = {'capture':{'suite':suite,'command':producer,'returncode':0,
                'sourceUnchanged':True,'sourceClosureOk':True,
                'sourceManifestBefore':dict(source,ok=True,entries={}),
                'sourceManifestAfter':dict(source,ok=True,entries={})},'result':{'unitOnly':True},'artifacts':[]}
            row={'suite':suite,'pid':2147483647,'passed':True,'cleanupConfirmed':True,'immutableFilesUnchanged':True,'unitOnly':True}
            out=root/'evidence'/suite;out.mkdir(parents=True,exist_ok=True)
            (out/'intent.json').write_text(json.dumps({'suite':suite,'identityRequired':True,'createdBeforeProcess':True,'cwd':str(root/'candidate'),'command':['unit-only']}))
            (out/'process.json').write_text(json.dumps({'pid':2147483647,'processGroup':2147483647,'originalPopenChild':True,'identity':identity()}))
            (out/'capture.json').write_text(json.dumps(row))
            return row
        def query(*args,**kwargs):
            queries.append(len(launches))
            if not launches or query_mode=='normal': return True,{'state':'quiescent','unitOnly':True}
            if query_mode=='raise': raise OSError('unit-query-unreadable')
            return False,{'state':'unknown','unitOnly':True}
        g = SimpleNamespace(_FIXED_COUNTS=counts,_source_state=lambda *_:source,
            _validate_baseline_entry=lambda *_:(1,1),
            _validate_independent_entry=lambda _v,s,*_:(counts[s],counts[s]),
            _validate_ordinary_entry=lambda _v,s,*_:(counts[s],counts[s]),
            resolve_capture_artifacts=lambda _c,p,*_:captures[str(self.root/'candidate'/p)],
            build_evidence_index=lambda *_:{'unitOnly':True},build_proof=lambda *_:{'ok':True,'sha256':'unit-only'},
            run_gate=lambda *_:{'state':'pending-independent-review','archiveCalls':0,'unitOnly':True})
        def write_unit(path,value):
            path = Path(path); self.assertTrue(path.is_relative_to(self.root))
            path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value))
        bounded = SimpleNamespace(run_one=run,usage=lambda *_:0,budget_admitted=lambda *_:True,write_json=write_unit)
        original_read = m._read_json
        with patch.object(m,'validate_registry',return_value=True), \
             patch.object(m,'_verify_files',return_value=True), patch.object(m,'_capacity',return_value=(0,10**12)), \
             patch.object(m,'_resource_log_empty',return_value=(True,None)), \
             patch.object(m,'_load_path',return_value=g), \
             patch.object(m,'_load_guard',return_value=SimpleNamespace(process_identity=identity)), \
             patch.object(m,'_read_json',side_effect=lambda p:plan if Path(p).name=='suite-plan.json' else original_read(p)), \
             patch.object(m,'_actual_process_quiescence',side_effect=query):
            result = m.run_batch(self.root,{'sourceManifestSha256':SOURCE},inputs,bounded,
                                 SimpleNamespace(),lambda *_:(True,{'unitOnly':True},[]))
        return result, launches, queries

    def test_unknown_after_first_group_stops_second(self):
        result, launches, queries = self.batch('unknown')
        self.assertEqual(launches,['consumer-12']); self.assertFalse(result['complete'])
        self.assertEqual(len(result['rows']),1); self.assertEqual(len(result['groups']),1)

    def test_query_exception_preserves_first_group(self):
        result, launches, queries = self.batch('raise')
        self.assertEqual(launches,['consumer-12']); self.assertFalse(result['complete'])
        self.assertEqual(len(result['rows']),1); self.assertEqual(len(result['captures']),1)

    def test_semantic_unknown_with_exited_resources_continues(self):
        result, launches, queries = self.batch('normal')
        self.assertEqual(launches,plan['order']); self.assertTrue(result['complete'])
        self.assertGreaterEqual(len(queries),21)

    def bounded_control(self, mode):
        self.assertIn('identity_reader',inspect.signature(b.run_one).parameters,'identity API missing')
        output = self.root/'unit-result.json'
        value = {'passed':1,'total':1,'checks':[{'passed':True}], 'unitOnly':True}
        code = 'from pathlib import Path;Path('+repr(str(output))+').write_text('+repr(json.dumps(value))+')'
        def reader(pid):
            if mode=='missing': return None
            if mode=='raise': raise PermissionError('unit identity read')
            return identity(pid)
        write = b.write_json
        def writing(p,v):
            if mode=='write-failure' and Path(p).name=='process.json': raise OSError('unit identity journal write')
            return write(p,v)
        with patch.object(b,'write_json',side_effect=writing):
            result = b.run_one(self.root,'unit-'+mode,[sys.executable,'-I','-B','-c',code],1,[],
                               result_file=output,identity_reader=reader)
        return result,self.root/'evidence'/('unit-'+mode)/'process.json'

    def test_new_wrapper_identity_record(self):
        result,p = self.bounded_control('normal'); record=json.loads(p.read_bytes())
        self.assertTrue(result['passed'],result)
        self.assertEqual(record['identity']['pid'],record['pid'])
        self.assertEqual(record['identity']['pgid'],record['processGroup'])

    def test_missing_identity_not_success(self):
        result,p = self.bounded_control('missing')
        self.assertFalse(result['passed']); self.assertFalse(result['cleanupConfirmed'])
        self.assertIsNone(json.loads(p.read_bytes())['identity'])

    def test_identity_read_failure_not_success(self):
        result,p = self.bounded_control('raise')
        self.assertFalse(result['passed']); self.assertFalse(result['cleanupConfirmed']); self.assertTrue(p.is_file())

    def test_identity_write_failure_not_success(self):
        result,p = self.bounded_control('write-failure')
        self.assertFalse(result['passed']); self.assertFalse(result['cleanupConfirmed'])
        self.assertTrue((p.parent/'capture.json').is_file())


if __name__=='__main__': unittest.main(verbosity=2)
