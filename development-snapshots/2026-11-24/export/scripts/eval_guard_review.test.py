from textwrap import dedent
import unittest

import sys
from pathlib import Path as ModulePath

sys.path.insert(0, str(ModulePath(__file__).resolve().parents[1] / 'work/harness-purge-improved/package/scripts'))

from eval_guard_review import review_eval_guard, review_plain_string_guard


def review(guard, body='return eval(value)', assignment='value = request.args.get("expr")'):
    source = dedent("""\
        from flask import request
        def route():
            SOURCE
            if GUARD:
                BODY
        """).replace('SOURCE', assignment).replace('GUARD', guard).replace('BODY', body)
    line = next(i for i, text in enumerate(source.splitlines(), 1) if 'eval(' in text)
    return review_eval_guard(source, line)


class GuardReviewTest(unittest.TestCase):
    def test_exact_literal_guards_record_conditional_evidence(self):
        for guard in ('value == "foo" or value == "bar"', 'value in ("foo", "bar")'):
            with self.subTest(guard=guard):
                self.assertEqual(review(guard), {
                    'observation': 'literal-identifier-guard-observed',
                    'assignmentLine': 3, 'guardLine': 4, 'evalLine': 5, 'literalCount': 2,
                    'disposition': 'unverified',
                })

    @unittest.skipUnless(sys.version_info >= (3, 12), 'Python generic syntax requires 3.12')
    def test_generic_annotation_scopes_leave_literal_guard_unknown(self):
        for name in ['request', 'eval', 'T']:
            with self.subTest(type_parameter=name):
                source = ('from flask import request\ndef route[' + name + ']():\n'
                          '    value = request.args.get("expr")\n'
                          '    if value == "foo":\n        return eval(value)\n')
                self.assertIsNone(review_eval_guard(source, 5))

    def test_widened_guards_and_unsupported_literals_are_not_evidence(self):
        for guard in ('value == "foo" or allowed()', 'value in dynamic',
                      'value in "foobar"', 'other == "foo" or value == "bar"',
                      'value in ("foo()", "bar")', 'value in ("__builtins__", "bar")',
                      'value == "foo" or True'):
            with self.subTest(guard=guard):
                self.assertIsNone(review(guard))

    def test_binding_and_first_statement_boundaries(self):
        self.assertIsNone(review('value == "foo"', body='value = read(); return eval(value)'))
        self.assertIsNone(review('value == "foo"', body='return eval(other)'))
        self.assertIsNone(review('value == "foo"', body='return eval(value, {})'))
        self.assertIsNone(review('value == "foo"', assignment='value = custom.args.get("expr")'))
        self.assertIsNone(review('value == "foo"', assignment='value = request.args.get("expr", type=custom)'))
        self.assertIsNone(review('value == "foo"', assignment='global value; value = request.args.get("expr")'))
        self.assertIsNone(review('value == "foo"', assignment='value = request.args.get("expr"); verify()'))

    def test_request_rebind_is_unknown(self):
        source = ('from flask import request\nrequest = custom\ndef view():\n'
                  '    value = request.args.get("expr")\n'
                  '    if value == "foo":\n        return eval(value)\n')
        self.assertIsNone(review_eval_guard(source, 6))

    def test_same_line_dynamic_calls_are_ambiguous(self):
        self.assertIsNone(review('value == "foo"', body='eval(value); exec(other)'))

    def test_wrong_location_invalid_and_oversized_input(self):
        for source, line in [('invalid !', 1), ('x = 1', 0), ('#' * 1048577, 1)]:
            self.assertIsNone(review_eval_guard(source, line))



class PlainStringGuardTest(unittest.TestCase):
    SOURCE = """from flask import request
def route():
    value = request.args.get("expr")
    if not value.startswith("'") or not value.endswith("'") or "'" in value[1:-1]:
        return "invalid"
    try:
        return eval(value)
    except Exception:
        return "error"
"""

    def test_eval_and_exec_guards_record_locations(self):
        for sink in ('eval', 'exec'):
            source = self.SOURCE.replace('eval(value)', sink + '(value)')
            evidence = review_plain_string_guard(source, 7)
            self.assertEqual(evidence, {
                'observation':'plain-string-guard-observed', 'guardLine':4,
                'executionLine':7, 'sink':sink, 'disposition':'unverified',
            })

    @unittest.skipUnless(sys.version_info >= (3, 12), 'Python generic syntax requires 3.12')
    def test_generic_annotation_scopes_leave_string_guard_unknown(self):
        for name in ['request', 'eval', 'exec', 'T']:
            for sink in ['eval', 'exec']:
                with self.subTest(type_parameter=name, sink=sink):
                    source = self.SOURCE.replace('def route():', 'def route[' + name + ']():')
                    source = source.replace('eval(value)', sink + '(value)')
                    self.assertIsNone(review_plain_string_guard(source, 7))

    def test_changed_values_weak_checks_and_wrong_branches_are_unknown(self):
        for source in (
            self.SOURCE.replace('    try:', '    value = request.args.get("other")\n    try:'),
            self.SOURCE.replace('or "\'" in value[1:-1]', ''),
            self.SOURCE.replace('value.endswith', 'other.endswith'),
            self.SOURCE.replace('value[1:-1]', 'value[1:-2]'),
            self.SOURCE.replace('return "invalid"', 'pass'),
            self.SOURCE.replace('or', 'and'),
            self.SOURCE.replace('return eval(value)', 'return eval(other)'),
            self.SOURCE.replace('return eval(value)', 'return eval(value, {})'),
            self.SOURCE.replace('return eval(value)', 'return consume(value, eval(value))'),
            self.SOURCE.replace('def route():', 'def route():\n    global value'),
            self.SOURCE.replace('def route():', 'def route(exec):').replace('eval(value)', 'exec(value)'),
        ):
            with self.subTest(source=source):
                line = next(i for i,text in enumerate(source.splitlines(),1) if 'eval(' in text or 'exec(' in text)
                self.assertIsNone(review_plain_string_guard(source,line))

    def test_scanner_grouping_line_is_bound_to_the_same_execution(self):
        source = self.SOURCE.replace('return eval(value)', 'return (\n            eval(value)\n        )')
        evidence = review_plain_string_guard(source,7)
        self.assertEqual(evidence['executionLine'],8)
        self.assertIsNone(review_plain_string_guard(source,6))
        self.assertIsNone(review_plain_string_guard(source,9))

    def test_same_line_other_sink_and_nonlocal_origins_are_unknown(self):
        for source in (
            self.SOURCE.replace('return eval(value)', 'eval(value); exec(other)'),
            self.SOURCE.replace('    value = request.args.get("expr")\n', ''),
            self.SOURCE.replace('def route():', 'def route(value):').replace('    value = request.args.get("expr")\n', ''),
        ):
            line = next(i for i,text in enumerate(source.splitlines(),1) if 'eval(' in text)
            with self.subTest(source=source):
                self.assertIsNone(review_plain_string_guard(source,line))

    def test_local_assignment_evidence_does_not_claim_request_provenance(self):
        source = self.SOURCE.replace('value = request.args.get("expr")', 'value = compute()')
        self.assertIsNotNone(review_plain_string_guard(source,7))
        self.assertIsNone(review_plain_string_guard(source + '    value = ""\n',7))

    def test_nested_route_and_constant_error_message(self):
        source = """from flask import request
def register(app):
    @app.route("/evaluate")
    def view():
        response = ""
        value = request.args.get("expr")
        if not value.startswith("'") or not value.endswith("'") or "'" in value[1:-1]:
            response += "invalid"
            return response
        try:
            response += eval(value)
        except:
            return "error"
        return response
"""
        self.assertEqual(review_plain_string_guard(source,11)['guardLine'],7)
        unsafe = source.replace('response += "invalid"', 'value = request.args.get("other")')
        self.assertIsNone(review_plain_string_guard(unsafe,11))


if __name__ == '__main__':
    unittest.main()
