"""Regression controls for an offline, non-authoritative structural reviewer."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import ast, importlib.util, json, sys, unittest

WORKER = Path(__file__).with_name('python_namespace_review.py')
RULE = 'policy.harness.python.dynamic-code-namespace'

def source_for(op='eval', arity=2, guard=None, extra='', header='def run(value):'):
    text = header+'\n'
    if guard is None: guard = 'if value not in ("6*7", "7*8"):\n        raise ValueError("outside")'
    text += '    '+guard+'\n'+extra
    text += '    scope = {"__builtins__": {}}\n'
    text += '    local_scope = {}\n' if arity==3 else ''
    call = op+'(value, scope'+(', local_scope' if arity==3 else '')+')'
    return text+'    '+('return ' if op=='eval' else '')+call+'\n'

def anchor(source,index=0):
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Call)
             and isinstance(n.func,ast.Name) and n.func.id in ['eval','exec']]
    call = sorted(calls,key=lambda n:(n.lineno,n.col_offset))[index]
    return {'line':call.lineno,'col':call.col_offset+1,'endLine':call.end_lineno,'endCol':call.end_col_offset+1}

class NamespaceReviewTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WORKER.exists(), 'Missing offline namespace evidence reviewer')
        spec = importlib.util.spec_from_file_location('namespace_candidate',WORKER)
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
    def review(self,source,index=0): return self.module.review_namespace_call(source,anchor(source,index))
    def unknown(self,source):
        row = self.review(source)
        self.assertEqual(row['constraint']['state'],'unresolved')
        self.assertEqual(row['disposition'],'unverified')
        self.assertEqual(row['callee']['builtinIdentity'],'unverified')
        self.assertEqual(row['source']['externalControl'],'unverified')
        return row
    def test_fixed_set_guard_two_and_three_arguments_is_only_conditional_evidence(self):
        for op in ['eval','exec']:
            for arity in [2,3]:
                with self.subTest(op=op,arity=arity):
                    source = source_for(op,arity);row = self.review(source)
                    self.assertEqual(row['anchor'],anchor(source))
                    self.assertEqual(row['constraint']['state'],'fixed-set-guard-observed')
                    self.assertEqual(row['constraint']['literalCount'],2)
                    self.assertEqual(row['constraint']['runtimeStringSemantics'],'unverified')
                    self.assertTrue(row['constraint']['fixedValuesMayExecuteCode'])
                    self.assertEqual(row['source']['kind'],'function-parameter-observed')
                    self.assertEqual(row['source']['externalControl'],'unverified')
                    self.assertEqual(row['callee']['builtinIdentity'],'unverified')
                    self.assertEqual(row['disposition'],'unverified')
                    self.assertNotIn('6*7',json.dumps(row))
    def test_conditional_nonterminating_and_wrong_value_checks_stay_unresolved(self):
        for guard in ['if enabled and value not in ("6*7",):\n        raise ValueError()',
                      'if value not in ("6*7",):\n        pass',
                      'if other not in ("6*7",):\n        raise ValueError()',
                      'if value not in dynamic:\n        return "bad"',
                      'if value not in "6*7":\n        return "bad"']:
            with self.subTest(guard=guard): self.unknown(source_for(guard=guard))
    def test_after_check_overwrite_append_and_side_effect_stay_unresolved(self):
        for extra in ['    value = other\n','    value += suffix\n','    mutate()\n',
                      '    scope = mutate()\n','    if condition:\n        value = other\n']:
            with self.subTest(extra=extra): self.unknown(source_for(extra=extra))
    def test_module_and_local_bindings_do_not_become_builtin_proof(self):
        variants = [
            'def eval(value, scope):\n    return value\n'+source_for(),
            source_for(header='def run(value, eval):'),
            source_for(extra='    eval = custom\n'),
            'from custom import eval\n'+source_for(),
            'from custom import *\n'+source_for(),
            'globals()["eval"] = custom\n'+source_for(),
            'import builtins\nbuiltins.eval = custom\n'+source_for(),
            source_for(extra='    global value\n'),
        ]
        for source in variants:
            with self.subTest(source=source):
                row = self.unknown(source)
                self.assertNotEqual(row['callee']['staticBinding'],'no-direct-conflict-observed')
    def test_nested_calls_decorators_defaults_and_annotations_are_not_guard_proof(self):
        variants = ['@decorate\n'+source_for(),
                    source_for(header='def run(value=load()):'),
                    source_for(header='def run(value: custom):'),
                    source_for().replace('    return eval(value, scope)', '    return consume(eval(value, scope))'),
                    source_for().replace('    return eval(value, scope)', '    if flag:\n        return eval(value, scope)'),
                    'class Owner:\n'+''.join('    '+s+'\n' for s in source_for().splitlines())]
        for source in variants:
            with self.subTest(source=source): self.unknown(source)
    def test_unknown_namespace_expressions_and_unproven_mapping_stay_unresolved(self):
        for replacement in ['factory()','custom_mapping','scope.attr','scope["nested"]']:
            self.unknown(source_for().replace('eval(value, scope)','eval(value, '+replacement+')'))
    def test_location_includes_rule_independent_exact_start_and_end(self):
        source = source_for().replace('return eval(value, scope)', 'eval(value, scope); exec(value, scope)')
        first = self.review(source);second = self.review(source,1)
        self.assertEqual(first['sink'],'eval');self.assertEqual(second['sink'],'exec')
        self.assertNotEqual(first['anchor'],second['anchor'])
        bad = anchor(source);bad['col']+=1
        self.assertIsNone(self.module.review_namespace_call(source,bad))
        bad = anchor(source);bad['endCol']+=1
        self.assertIsNone(self.module.review_namespace_call(source,bad))
    def test_fixed_literals_are_never_equated_to_benign_code(self):
        source = source_for(guard='if value not in ("dangerous()",):\n        return "bad"')
        row = self.review(source)
        self.assertEqual(row['constraint']['state'],'fixed-set-guard-observed')
        self.assertTrue(row['constraint']['fixedValuesMayExecuteCode'])
        self.assertEqual(row['disposition'],'unverified')
    def test_assignment_target_is_written_after_the_execution_not_before_it(self):
        source = source_for().replace('return eval(value, scope)','value = eval(value, scope)')
        row = self.review(source)
        self.assertEqual(row['source']['kind'],'function-parameter-observed')
        self.assertEqual(row['source']['assignmentLines'],[])
        self.assertEqual(row['constraint']['state'],'fixed-set-guard-observed')
    def test_default_argument_call_is_not_in_the_functions_local_body(self):
        row = self.review('def run(eval, value=eval(raw, {})):\n    return value\n')
        self.assertEqual(row['callee']['staticBinding'],'unsupported-scope')
        self.assertEqual(row['source']['kind'],'expression-unresolved')
        self.assertEqual(row['constraint']['state'],'unresolved')
    def test_inputs_are_bounded_and_parsed_without_executing_source(self):
        for source,location in [('bad !',{'line':1,'col':1,'endLine':1,'endCol':2}),
                                ('#'*1048577,{'line':1,'col':1,'endLine':1,'endCol':2}),
                                (source_for(),{'line':True,'col':1,'endLine':1,'endCol':2})]:
            self.assertIsNone(self.module.review_namespace_call(source,location))
        row = self.review('raise RuntimeError("SOURCE_EXECUTED")\n'+source_for())
        self.assertEqual(row['disposition'],'unverified')
    def test_batch_pins_sources_and_full_scan_anchors_without_changing_findings(self):
        source = source_for();location = anchor(source)
        hit = {'check_id':RULE,'path':'/src/example.py',
               'start':{'line':location['line'],'col':location['col']},
               'end':{'line':location['endLine'],'col':location['endCol']}}
        scan = {'results':[hit]};frozen = json.dumps(scan,sort_keys=True)
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();(root/'example.py').write_text(source)
            manifest = {'files':{'example.py':sha256(source.encode()).hexdigest()}}
            report = self.module.review_namespace_batch(root,manifest,scan)
            row, = report['observations']
            self.assertEqual(row['file'],'example.py');self.assertEqual(row['rule'],RULE)
            self.assertEqual(row['sourceSha256'],manifest['files']['example.py'])
            self.assertFalse(report['r3Qualified']);self.assertFalse(report['changesFindingDisposition'])
            self.assertEqual(json.dumps(scan,sort_keys=True),frozen)
            (root/'example.py').write_text(source+'# drift\n')
            with self.assertRaisesRegex(ValueError,'digest'): self.module.review_namespace_batch(root,manifest,scan)
    def test_batch_rejects_incomplete_anchor_and_ignores_unpinned_paths(self):
        source = source_for();location = anchor(source)
        hit = {'check_id':RULE,'path':'/src/example.py','start':{'line':location['line']}}
        with TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'example.py').write_text(source)
            manifest={'files':{'example.py':sha256(source.encode()).hexdigest()}}
            with self.assertRaises(ValueError): self.module.review_namespace_batch(root,manifest,{'results':[hit]})
            hit['path']='/etc/passwd'
            self.assertEqual(self.module.review_namespace_batch(root,manifest,{'results':[hit]})['observations'],[])
    def test_batch_deduplicates_exact_hits_and_reports_unmatched_span_as_partial(self):
        source=source_for();location=anchor(source)
        hit={'check_id':RULE,'path':'/src/example.py','start':{'line':location['line'],'col':location['col']},
             'end':{'line':location['endLine'],'col':location['endCol']}}
        with TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'example.py').write_text(source)
            manifest={'files':{'example.py':sha256(source.encode()).hexdigest()}}
            report=self.module.review_namespace_batch(root,manifest,{'results':[hit,hit]})
            self.assertEqual(report['checks'],1);self.assertEqual(len(report['observations']),1)
            hit['end']['col']+=1
            report=self.module.review_namespace_batch(root,manifest,{'results':[hit]})
            self.assertEqual(report['state'],'partial');self.assertEqual(report['observations'],[])
            self.assertEqual(len(report['unmatchedAnchors']),1)
    def test_cli_requires_the_exact_raw_scan_digest(self):
        import subprocess
        with TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'example.py').write_text(source_for())
            (root/'scan.json').write_text('{"results":[]}')
            (root/'manifest.json').write_text(json.dumps({'files':{'example.py':sha256(source_for().encode()).hexdigest()},'scanSha256':'0'*64}))
            p=subprocess.run([sys.executable,'-I','-B',str(WORKER),str(root),str(root/'manifest.json'),str(root/'scan.json')],capture_output=True,text=True,timeout=5)
            self.assertNotEqual(p.returncode,0);self.assertIn('scan digest mismatch',p.stderr)

if __name__=='__main__': unittest.main()
