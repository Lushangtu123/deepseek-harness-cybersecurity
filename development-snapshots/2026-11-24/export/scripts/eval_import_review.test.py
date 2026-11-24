import unittest

import sys
from pathlib import Path as ModulePath

sys.path.insert(0, str(ModulePath(__file__).resolve().parents[1] / 'work/harness-purge-improved/package/scripts'))

from eval_import_review import review_import_flow

CALLER = '''from flask import request
from evaluator import run as execute

def route():
    code = request.args.get("code")
    return execute(code)
'''
CALLEE = '''def run(value):
    return eval(value)
'''


class ImportFlowTest(unittest.TestCase):
    @unittest.skipUnless(sys.version_info >= (3, 12), 'Python generic syntax requires 3.12')
    def test_generic_type_parameters_do_not_become_builtin_or_import_identity(self):
        for suffix in ['', ', {}', ', {}, {}']:
            with self.subTest(suffix=suffix):
                callee = 'def run[eval](value):\n    return eval(value' + suffix + ')\n'
                self.assertIsNone(review_import_flow(CALLER, 'evaluator', callee, 6))

    @unittest.skipUnless(sys.version_info >= (3, 12), 'Python generic syntax requires 3.12')
    def test_generic_caller_bindings_do_not_become_flask_query_identity(self):
        callee = 'def run(value):\n    return eval(value, {})\n'
        for name in ['request', 'execute', 'eval']:
            with self.subTest(type_parameter=name):
                caller = CALLER.replace('def route():', 'def route[' + name + ']():')
                self.assertIsNone(review_import_flow(caller, 'evaluator', callee, 6))

    def test_empty_literal_namespaces_preserve_conditional_import_flow(self):
        for sink in ['eval', 'exec']:
            for namespaces in [', {}', ', {}, {}']:
                with self.subTest(sink=sink, namespaces=namespaces):
                    statement = 'return ' if sink == 'eval' else ''
                    callee = 'def run(value):\n    ' + statement + sink + '(value' + namespaces + ')\n'
                    row = review_import_flow(CALLER, 'evaluator', callee, 6)
                    self.assertIsNotNone(row)
                    self.assertEqual(row['sourceLine'], 5)
                    self.assertEqual(row['callLine'], 6)
                    self.assertEqual(row['definitionLine'], 1)
                    self.assertEqual(row['sinkLine'], 2)
                    self.assertEqual(row['sink'], sink)
                    self.assertEqual(row['disposition'], 'unverified')

    def test_namespace_forms_outside_the_explicit_contract_stay_unknown(self):
        for call in ['eval(value, scope)', 'eval(value, factory())',
                     'eval(value, {"__builtins__": {}})', 'eval(value, {}, {}, {})',
                     'eval(value, globals={})', 'eval(value, *scopes)',
                     'eval(transform(value), {})', 'execute(value, {})']:
            with self.subTest(call=call):
                callee = 'def run(value):\n    return ' + call + '\n'
                self.assertIsNone(review_import_flow(CALLER, 'evaluator', callee, 6))

    def test_namespace_sink_support_does_not_relax_the_imported_call_site(self):
        callee = 'def run(value):\n    return eval(value, {}, {})\n'
        for caller in [CALLER.replace('execute(code)', 'execute(code, {})'),
                       CALLER.replace('execute(code)', 'execute(code=code)'),
                       CALLER.replace('execute(code)', 'execute(*code)'),
                       CALLER.replace('execute(code)', 'execute("constant")'),
                       CALLER.replace('request.args.get', 'custom.args.get')]:
            with self.subTest(caller=caller):
                self.assertIsNone(review_import_flow(caller, 'evaluator', callee, 6))

    def test_explicit_import_and_both_execution_points(self):
        for callee, sink in [(CALLEE, 'eval'), (CALLEE.replace('return eval', 'exec'), 'exec')]:
            with self.subTest(sink=sink):
                self.assertEqual(review_import_flow(CALLER, 'evaluator', callee, 6), {
                    'observation': 'direct-import-execution-flow-observed',
                    'sourceLine': 5, 'importLine': 2, 'callLine': 6,
                    'definitionLine': 1, 'sinkLine': 2, 'sink': sink, 'disposition': 'unverified',
                })

    def test_module_resolution_and_target_shape(self):
        self.assertIsNone(review_import_flow(CALLER, 'different', CALLEE, 6))
        self.assertIsNone(review_import_flow(CALLER.replace('from evaluator', 'from .evaluator'), 'evaluator', CALLEE, 6))
        for callee in (CALLEE.replace('eval(value)', 'eval("1")'),
                       CALLEE.replace('    return', '    value = "1"\n    return'),
                       CALLEE + '\nrun = print\n', '@wrapper\n' + CALLEE):
            with self.subTest(callee=callee):
                self.assertIsNone(review_import_flow(CALLER, 'evaluator', callee, 6))

    def test_binding_and_input_boundaries(self):
        for caller in (CALLER.replace('execute(code)', 'execute("1")'),
                       CALLER.replace('def route():', 'def route(execute):'),
                       CALLER.replace('    return', '    execute = print\n    return'),
                       CALLER + '\nexecute = print\n',
                       CALLER.replace('request.args.get', 'custom.args.get'),
                       CALLER.replace('from evaluator', 'from helper\nfrom evaluator'),
                       CALLER.replace('def route():', 'def route():\n    global code'),
                       CALLER.replace('    return', '    code = "1"\n    return')):
            with self.subTest(caller=caller):
                line = next(i for i, text in enumerate(caller.splitlines(), 1) if 'return execute(' in text)
                self.assertIsNone(review_import_flow(caller, 'evaluator', CALLEE, line))

    def test_bad_input_and_wrong_location(self):
        self.assertIsNone(review_import_flow(CALLER, 'evaluator', CALLEE, 5))
        self.assertIsNone(review_import_flow(CALLER, '../evaluator', CALLEE, 6))
        self.assertIsNone(review_import_flow(CALLER, 'evaluator', 'invalid !', 6))
        self.assertIsNone(review_import_flow(CALLER, 'evaluator', '#' * 1048577, 6))


if __name__ == '__main__':
    unittest.main()
