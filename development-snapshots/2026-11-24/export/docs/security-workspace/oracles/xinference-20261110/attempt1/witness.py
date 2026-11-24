"""Benign method-level witness. Execute only in the dedicated no-network VM container."""
import __future__
import ast
from hashlib import sha256
import json
from pathlib import Path
import sys

root = Path('/src')
sources = json.loads(Path('/protocol.json').read_bytes())['sources']
product = 17389 * 7919
vectors = [
    ('json-string', '{"name":"lookup","parameters":{"value":"hello"}}',
     {'value': 'hello'}, {'value': 'hello'}),
    ('python-literals', "{'name':'lookup','parameters':{'flag':True,'empty':None}}",
     {'flag': True, 'empty': None}, {'flag': True, 'empty': None}),
    ('json-boolean', '{"name":"lookup","parameters":{"flag":true}}', None, {'flag': True}),
    ('arithmetic-expression', '{"name":"lookup","parameters":{"value":17389 * 7919}}',
     {'value': product}, None),
    ('benign-builtin-call', '{"name":"lookup","parameters":{"value":str(17389 * 7919)}}',
     {'value': str(product)}, None),
    ('invalid-text', 'not a tool call', None, None),
    ('wrong-shape', '[]', None, None),
]
results = []
for row in sources:
    path = root / row['file']
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != row['sha256']:
        raise ValueError('Source digest mismatch')
    tree = ast.parse(raw.decode(), filename=str(path))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'Llama3ToolParser')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'extract_tool_calls')
    method_digest = sha256(ast.dump(method, include_attributes=True).encode()).hexdigest()
    if method_digest != row['method']['astSha256']:
        raise ValueError('Original method changed')
    namespace = {'ast': ast, 'json': json}
    # Compile the unchanged AST node at its original line numbers. Module imports,
    # registry decorators, class initialization and package services are not run.
    code = compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec',
                   flags=__future__.annotations.compiler_flag, dont_inherit=True)
    exec(code, namespace)
    for name, value, before, fixed in vectors:
        events = []

        def trace(frame, event, argument):
            caller = frame.f_back
            if event == 'call' and frame.f_code.co_filename == '<string>' and caller is not None:
                if caller.f_code.co_filename == str(path) and caller.f_code.co_name == method.name:
                    events.append({'callerLine': caller.f_lineno, 'dynamicFilename': '<string>'})
            return trace

        sys.settrace(trace)
        try:
            observed = namespace[method.name](None, value)
        finally:
            sys.settrace(None)
        parameters = before if row['file'] == 'before.py' else fixed
        expected = [(value, None, None)] if parameters is None else [(None, 'lookup', parameters)]
        if observed != expected:
            raise ValueError('Unexpected benign parser result')
        if row['file'] == 'fixed.py' and events:
            raise ValueError('Unexpected dynamic evaluation in patched method')
        if row['file'] == 'before.py' and name in ['arithmetic-expression', 'benign-builtin-call']:
            if len(events) != 1 or events[0]['callerLine'] != 46:
                raise ValueError('Original eval witness missing')
        results.append({'source': row['file'], 'sourceSha256': row['sha256'],
                        'methodAstSha256': method_digest, 'vector': name,
                        'input': value, 'result': observed, 'dynamicFrames': events,
                        'expectedMatched': True})
print(json.dumps({'state': 'passed', 'pythonVersion': sys.version.split()[0],
                  'methodOnly': True, 'fullApiTested': False, 'observations': results}))
