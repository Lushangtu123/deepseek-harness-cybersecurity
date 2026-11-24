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
             and isinstance(n.func,ast.Name) and n.func.id in ['eval','exec'] and len(n.args) in [2,3]]
    call = sorted(calls,key=lambda n:(n.lineno,n.col_offset))[index]
    raw=source.encode();starts=[0]+[i+1 for i,b in enumerate(raw) if b==10]
    return {'line':call.lineno,'col':call.col_offset+1,'endLine':call.end_lineno,'endCol':call.end_col_offset+1,
            'offset':starts[call.lineno-1]+call.col_offset,'endOffset':starts[call.end_lineno-1]+call.end_col_offset}

class NamespaceReviewTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WORKER.exists(), 'Missing offline namespace evidence reviewer')
        spec = importlib.util.spec_from_file_location('namespace_candidate',WORKER)
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
    def review(self,source,index=0):
        compile(source,'<namespace-control>','exec')
        return self.module.review_namespace_call(source,anchor(source,index))
    def unknown(self,source):
        row = self.review(source)
        self.assertEqual(row['constraint']['state'],'unresolved')
        self.assertEqual(row['disposition'],'unverified')
        self.assertEqual(row['callee']['builtinIdentity'],'unverified')
        self.assertEqual(row['source']['externalControl'],'unverified')
        return row
    def test_lambda_parameter_shadow_is_not_no_direct_conflict(self):
        source='def f(value):\n    return (lambda eval: eval(value, {}))(print)\n'
        row=self.module.review_namespace_call(source,anchor(source))
        self.assertEqual(row['callee']['staticBinding'],'unsupported-scope')
        self.assertEqual(row['constraint']['state'],'unresolved')

    def test_class_method_parameter_is_observed_through_protected_try_body(self):
        source = ('class Parser:\n'
                  '    def parse(self, model_output: str):\n'
                  '        try:\n'
                  '            data = eval(model_output, {}, {})\n'
                  '            return data\n'
                  '        except Exception as model_output:\n'
                  '            return None\n')
        row = self.review(source)
        self.assertEqual(row['source']['kind'], 'parameter-name-observed')
        self.assertEqual(row['source']['assignmentLines'], [])
        self.assertEqual(row['callee']['staticBinding'], 'no-direct-conflict-observed')
        self.assertEqual(row['source']['externalControl'], 'unverified')
        self.assertEqual(row['constraint']['state'], 'unresolved')

    def test_method_prefix_assignments_and_bindings_are_not_parameter_origin(self):
        variants = [
            ('        value = replacement\n', 'local-reassignment-observed', [3]),
            ('        import replacement as value\n', 'local-binding-observed', []),
            ('        try:\n            pass\n        except Exception as value:\n            pass\n',
             'local-binding-observed', []),
        ]
        for prefix, expected, lines in variants:
            with self.subTest(prefix=prefix):
                source = ('class Parser:\n    def parse(self, value):\n' + prefix
                          + '        try:\n            return eval(value, {})\n'
                          + '        except Exception:\n            return None\n')
                row = self.review(source)
                self.assertEqual(row['source']['kind'], expected)
                self.assertEqual(row['source']['assignmentLines'], lines)
                self.assertEqual(row['constraint']['state'], 'unresolved')

    def test_class_attribute_does_not_bind_the_method_bare_eval_name(self):
        source = ('class Parser:\n    eval = custom\n'
                  '    def parse(self, value):\n        return eval(value, {})\n')
        row = self.review(source)
        self.assertEqual(row['callee']['staticBinding'], 'no-direct-conflict-observed')
        self.assertEqual(row['source']['kind'], 'parameter-name-observed')
        self.assertEqual(row['constraint']['state'], 'unresolved')
        shadowed = source.replace('def parse(self, value)', 'def parse(self, value, eval)')
        self.assertEqual(self.review(shadowed)['callee']['staticBinding'], 'local-binding-conflict-observed')

    def test_try_branch_handlers_loops_and_nested_methods_stay_unresolved(self):
        bodies = [
            '        if flag:\n            return eval(value, {})\n',
            '        for value in items:\n            return eval(value, {})\n',
            '        try:\n            pass\n        except Exception as value:\n            return eval(value, {})\n',
            '        try:\n            pass\n        finally:\n            return eval(value, {})\n',
            '        def inner(value):\n            return eval(value, {})\n',
        ]
        for body in bodies:
            with self.subTest(body=body):
                row = self.review('class Parser:\n    def parse(self, value):\n' + body)
                self.assertEqual(row['source']['kind'], 'expression-unresolved')
                self.assertEqual(row['constraint']['state'], 'unresolved')

    def test_method_headers_and_nested_classes_do_not_gain_body_parameter_evidence(self):
        sources = [
            'class Parser:\n    def parse(self, value=eval(raw, {})):\n        return value\n',
            'def outer():\n    class Parser:\n        def parse(self, value):\n            return eval(value, {})\n',
            'class Outer:\n    class Parser:\n        def parse(self, value):\n            return eval(value, {})\n',
            'class Parser:\n    async def parse(self, value):\n        return eval(value, {})\n',
        ]
        for source in sources:
            with self.subTest(source=source):
                row = self.review(source)
                self.assertEqual(row['source']['kind'], 'expression-unresolved')
                self.assertEqual(row['callee']['staticBinding'], 'unsupported-scope')

    def test_nested_try_prefix_and_same_line_write_are_accounted_before_call(self):
        source = ('class Parser:\n    def parse(self, value):\n'
                  '        try:\n            value = replacement\n'
                  '            try:\n                data = value; return eval(data, {})\n'
                  '            except Exception:\n                return None\n'
                  '        except Exception:\n            return None\n')
        row = self.review(source)
        self.assertEqual(row['source']['kind'], 'local-reassignment-observed')
        self.assertEqual(row['source']['assignmentLines'], [6])
        self.assertEqual(row['source']['externalControl'], 'unverified')

    def test_method_fixed_set_guard_does_not_become_a_validated_constraint(self):
        source = 'class Parser:\n' + ''.join('    ' + line + '\n' for line in source_for().splitlines())
        row = self.review(source)
        self.assertEqual(row['source']['kind'], 'parameter-name-observed')
        self.assertEqual(row['constraint']['state'], 'unresolved')
        self.assertEqual(row['disposition'], 'unverified')

    def test_try_path_budget_accepts_eight_levels_and_declines_nine(self):
        for depth in [8, 9]:
            with self.subTest(depth=depth):
                lines = ['class Parser:', '    def parse(self, value):']
                for level in range(depth):
                    lines.append(' ' * (8 + level * 4) + 'try:')
                lines.append(' ' * (8 + depth * 4) + 'return eval(value, {})')
                for level in reversed(range(depth)):
                    lines.append(' ' * (8 + level * 4) + 'except Exception:')
                    lines.append(' ' * (12 + level * 4) + 'return None')
                row = self.review('\n'.join(lines) + '\n')
                expected = 'parameter-name-observed' if depth == 8 else 'expression-unresolved'
                self.assertEqual(row['source']['kind'], expected)
                self.assertEqual(row['constraint']['state'], 'unresolved')
                self.assertEqual(row['disposition'], 'unverified')

    def test_module_function_try_observations_do_not_gain_guard_proof(self):
        source = ('def parse(value):\n    try:\n        return eval(value, {})\n'
                  '    except Exception:\n        return None\n')
        row = self.review(source)
        self.assertEqual(row['source']['kind'], 'parameter-name-observed')
        self.assertEqual(row['constraint']['state'], 'unresolved')
        self.assertEqual(row['source']['externalControl'], 'unverified')

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
                    self.assertEqual(row['source']['kind'],'parameter-name-observed')
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
            source_for(extra='    global state\n'),
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
        self.assertEqual(row['source']['kind'],'parameter-name-observed')
        self.assertEqual(row['source']['assignmentLines'],[])
        self.assertEqual(row['constraint']['state'],'fixed-set-guard-observed')
    def test_excessive_write_lines_leave_only_this_anchor_unmatched(self):
        source='def run(value):\n'+''.join('    value = value\n' for _ in range(65))+'    return eval(value, {})\n'
        self.assertIsNone(self.review(source))
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
               'start':{'line':location['line'],'col':location['col'],'offset':location['offset']},
               'end':{'line':location['endLine'],'col':location['endCol'],'offset':location['endOffset']}}
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
        hit={'check_id':RULE,'path':'/src/example.py','start':{'line':location['line'],'col':location['col'],'offset':location['offset']},
             'end':{'line':location['endLine'],'col':location['endCol'],'offset':location['endOffset']}}
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
    def test_direct_and_aliased_namespace_effects_invalidate_the_binding_hint(self):
        variants=[
            source_for(header='def run[eval](value):'),
            'exec("eval = custom")\n'+source_for(),
            '__builtins__["eval"] = custom\n'+source_for(),
            'del __builtins__["eval"]\n'+source_for(),
            'import builtins\nbuiltins.__dict__["eval"] = custom\n'+source_for(),
            'import builtins\nbuiltins.__dict__.update({"eval": custom})\n'+source_for(),
            'g = globals\ng()["eval"] = custom\n'+source_for(),
            'execute = exec\nexecute("eval = custom")\n'+source_for(),
        ]
        for source in variants:
            with self.subTest(source=source):
                compile(source,'<namespace-control>','exec')
                row=self.unknown(source)
                self.assertNotEqual(row['callee']['staticBinding'],'no-direct-conflict-observed')
    def test_byte_offset_disagreement_is_partial_even_when_columns_match(self):
        source=source_for();location=anchor(source)
        raw=source.encode();starts=[0]
        for i,b in enumerate(raw):
            if b==10:starts.append(i+1)
        hit={'check_id':RULE,'path':'/src/example.py',
             'start':{'line':location['line'],'col':location['col'],'offset':starts[location['line']-1]+location['col']},
             'end':{'line':location['endLine'],'col':location['endCol'],'offset':starts[location['endLine']-1]+location['endCol']-1}}
        with TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'example.py').write_text(source)
            report=self.module.review_namespace_batch(root,{'files':{'example.py':sha256(source.encode()).hexdigest()}},{'results':[hit]})
            self.assertEqual(report['state'],'partial');self.assertEqual(report['observations'],[])
    def test_unrecognized_rule_prefix_is_counted_and_not_completed(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();source=source_for();(root/'example.py').write_text(source)
            report=self.module.review_namespace_batch(root,{'files':{'example.py':sha256(source.encode()).hexdigest()}},
                {'results':[{'check_id':'other.'+RULE,'path':'/src/example.py'}]})
            self.assertEqual(report['state'],'partial')
            self.assertEqual(report['ignoredHits']['unsupported-rule-prefix'],1)
    def test_loop_import_exception_match_and_lambda_are_not_parameter_provenance(self):
        variants=[
            'def run(value):\n    while flag:\n        eval(value, {})\n        value = other\n',
            source_for(extra='    import module as value\n'),
            source_for(extra='    try:\n        load()\n    except Exception as value:\n        pass\n'),
            source_for(extra='    match other:\n        case value:\n            pass\n'),
            'def run(value):\n    return lambda: eval(value, {})\n',
        ]
        for source in variants:
            with self.subTest(source=source):
                row=self.unknown(source)
                self.assertNotEqual(row['source']['kind'],'parameter-name-observed')
    def test_definition_headers_bind_in_enclosing_scope(self):
        for prefix in ['def helper(x=(eval := custom)):\n    pass\n',
                       'helper = lambda x=(eval := custom): x\n',
                       'class Owner((eval := custom)):\n    pass\n',
                       'def helper(x: (eval := custom)):\n    pass\n',
                       'def helper() -> (eval := custom):\n    pass\n',
                       '@(eval := decorate)\ndef helper():\n    pass\n']:
            with self.subTest(prefix=prefix):
                row=self.unknown(prefix+source_for())
                self.assertNotEqual(row['callee']['staticBinding'],'no-direct-conflict-observed')
        source=source_for(extra='    def helper(x=(value := other)):\n        pass\n')
        row=self.unknown(source)
        self.assertEqual(row['source']['kind'],'local-reassignment-observed')
    def test_renamed_builtins_imports_are_namespace_effects(self):
        for prefix in ['import builtins as b\nb.__dict__["eval"] = custom\n',
                       'from builtins import __dict__ as d\nd["eval"] = custom\n',
                       'from builtins import eval as renamed\n']:
            with self.subTest(prefix=prefix):
                row=self.unknown(prefix+source_for())
                self.assertEqual(row['callee']['staticBinding'],'namespace-effects-observed')
    def test_non_utf8_cookies_are_unmatched_instead_of_false_guard_evidence(self):
        source='# coding: utf-7\n'+source_for(extra='    #+AAo-    value = other\n')
        raw=source.encode('utf-8')
        # Compare the two parser interpretations without executing either program.
        compile(raw,'<cookie-control>','exec')
        utf8_tree=ast.parse(source);runtime_tree=ast.parse(raw)
        stores=lambda t:sum(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id=='value' for n in ast.walk(t))
        self.assertEqual(stores(utf8_tree),0);self.assertEqual(stores(runtime_tree),1)
        for candidate in [source,'# coding: latin-1\n'+source_for(),
                          '#!python\n# coding=cp1252\n'+source_for(),
                          '# coding: unknown_codec\n'+source_for()]:
            with self.subTest(cookie=candidate.splitlines()[:2]):
                self.assertIsNone(self.module.review_namespace_call(candidate,anchor(candidate)))
        with TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'cookie.py').write_bytes(raw);loc=anchor(source)
            hit={'check_id':RULE,'path':'/src/cookie.py',
                 'start':{'line':loc['line'],'col':loc['col'],'offset':loc['offset']},
                 'end':{'line':loc['endLine'],'col':loc['endCol'],'offset':loc['endOffset']}}
            report=self.module.review_namespace_batch(root,{'files':{'cookie.py':sha256(raw).hexdigest()}},{'results':[hit]})
            self.assertEqual(report['state'],'partial');self.assertEqual(report['observations'],[])
    def test_standard_utf8_cookies_retain_conditional_observations(self):
        for prefix in ['# coding: utf-8\n','# coding: UTF_8\n','#!/usr/bin/python\n# coding=utf8\n']:
            with self.subTest(prefix=prefix):
                row=self.review(prefix+source_for())
                self.assertEqual(row['constraint']['state'],'fixed-set-guard-observed')

if __name__=='__main__': unittest.main()
