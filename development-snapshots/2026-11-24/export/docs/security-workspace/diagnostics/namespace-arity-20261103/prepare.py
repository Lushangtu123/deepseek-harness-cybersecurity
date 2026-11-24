"""Author diagnostic controls; none is an independent vulnerability oracle."""
from pathlib import Path
from hashlib import sha256
import ast, datetime, json

w = Path(__file__).resolve().parent
repo = w.parents[1] / 'exports/deepseek-harness-vm'
docs = repo / 'docs/security-workspace'
marker = 17389 * 7919
cases = []
vectors = []
if (w/'intent.json').exists():
    raise SystemExit('Frozen artifacts already exist. Use a new experiment directory; do not regenerate this record.')

def add(name, source, role, tests, required=False):
    raw = source.encode()
    tree = ast.parse(source)
    sites = [{'line':n.lineno, 'column':n.col_offset + 1,
              'callee':ast.unparse(n.func), 'positionalArguments':len(n.args)}
             for n in ast.walk(tree) if isinstance(n, ast.Call)
             and (isinstance(n.func, ast.Name) and n.func.id in ['eval','exec','evaluate']
                  or isinstance(n.func, ast.Attribute) and n.func.attr in ['eval','exec'])]
    (w / 'src').mkdir(exist_ok=True)
    (w / 'src' / (name + '.py')).write_bytes(raw)
    cases.append({'id':name, 'file':name+'.py', 'source':source,
                  'sha256':sha256(raw).hexdigest(), 'role':role,
                  'independent':False, 'qualifiesForR3':False,
                  'requiredArityCoverage':required, 'sites':sites})
    for number, test in enumerate(tests):
        vectors.append({'id':name+'-'+str(number), 'caseId':name, **test})

for op in ['eval','exec']:
    allowed = '6*7' if op == 'eval' else 'answer=6*7'
    alternate = '7*8' if op == 'eval' else 'answer=7*8'
    expression = '17389*7919' if op == 'eval' else 'answer=17389*7919'
    for arity in [1,2,3]:
        # Separate locals for arity three; arity-one exec uses Python 3.12 locals.
        prefix = "def run(value):\n    scope = {'__builtins__': {}}\n    local_scope = {}\n"
        call = f'{op}(value' + ['', ', scope', ', scope, local_scope'][arity-1] + ')'
        if op == 'eval': body = '    return '+call+'\n'
        elif arity == 1: body = '    '+call+'\n    return locals().get("answer")\n'
        else: body = '    '+call+'\n    return '+('scope' if arity==2 else 'local_scope')+'.get("answer")\n'
        add(f'plain-{op}-{arity}',prefix+body,'authored-unconstrained-argument',
            [{'args':[expression], 'expected':marker, 'dynamicFrames':1}],required=True)

    header = 'def run(value, other=None, enforce=True):\n'
    guard = f'    if value not in ({allowed!r}, {alternate!r}):\n        raise ValueError("outside fixed set")\n'
    body = "    scope = {'__builtins__': {}}\n"
    body += ('    return eval(value, scope)\n' if op == 'eval'
             else '    exec(value, scope)\n    return scope.get("answer")\n')
    add('guard-complete-'+op, header+guard+body, 'authored-complete-constraint',
        [{'args':[allowed], 'expected':42, 'dynamicFrames':1},
         {'args':[expression], 'error':'ValueError', 'dynamicFrames':0}])
    branch = f'    if enforce and value not in ({allowed!r}, {alternate!r}):\n        raise ValueError("conditional check")\n'
    add('guard-conditional-'+op,header+branch+body,'authored-conditional-bypass',
        [{'args':[allowed], 'expected':42, 'dynamicFrames':1},
         {'args':[expression,None,False], 'expected':marker, 'dynamicFrames':1}])
    add('guard-overwrite-'+op,header+guard+'    value = other\n'+body,
        'authored-after-check-overwrite',
        [{'args':[allowed,allowed], 'expected':42, 'dynamicFrames':1},
         {'args':[allowed,expression], 'expected':marker, 'dynamicFrames':1}])
    add('guard-append-'+op,header+guard+'    value += other\n'+body,
        'authored-after-check-mutation',
        [{'args':[allowed,''], 'expected':42, 'dynamicFrames':1},
         {'args':[allowed,'+137703449'], 'expected':marker, 'dynamicFrames':1}])
    choice = f'    value = {{"allowed": {allowed!r}}}.get(value, {alternate!r})\n'
    add('mapping-'+op,header+choice+body,'authored-fixed-selection',
        [{'args':['allowed'], 'expected':42, 'dynamicFrames':1},
         {'args':[expression], 'expected':56, 'dynamicFrames':1}])
    literalbody = (f'    return eval({allowed!r}, scope)\n' if op=='eval'
                   else f'    exec({allowed!r}, scope)\n    return scope.get("answer")\n')
    add('literal-'+op,header+"    scope = {'__builtins__': {}}\n"+literalbody,
        'authored-fixed-literal', [{'args':[expression], 'expected':42, 'dynamicFrames':1}])
    shadow = f'def {op}(value, namespace):\n    return value\ndef run(value):\n    return {op}(value, {{}})\n'
    add('shadow-'+op,shadow,'authored-shadowed-non-builtin',
        [{'args':[expression], 'expected':expression, 'dynamicFrames':0}])
    for style in ['qualified','alias']:
        pre = 'import builtins\n' if style=='qualified' else f'from builtins import {op} as evaluate\n'
        callee = 'builtins.'+op if style=='qualified' else 'evaluate'
        statement = (f'    return {callee}(value, scope)\n' if op=='eval'
                     else f'    {callee}(value, scope)\n    return scope.get("answer")\n')
        add(style+'-'+op,pre+'def run(value):\n'+"    scope = {'__builtins__': {}}\n"+statement,
            'authored-import-resolution-observation',
            [{'args':[expression], 'expected':marker, 'dynamicFrames':1}])

# Reused upstream normal files: development regression, never fresh holdout.
archive = docs / 'oracles/cpython-normal-20261103'
for name in ['stdlib_ast.py','stdlib_collections.py']:
    raw = (archive/name).read_bytes()
    cases.append({'id':name[:-3], 'file':name, 'source':raw.decode(),
                  'sha256':sha256(raw).hexdigest(), 'role':'reused-upstream-normal-source',
                  'independent':False, 'qualifiesForR3':False,
                  'requiredArityCoverage':False})

(w/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
intent = {'version':1, 'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'scope':'bare eval/exec with two or three positional arguments; sink inventory only',
          'baselineSha256':sha256((repo/'work/harness-purge-improved/security-rules.json').read_bytes()).hexdigest(),
          'combined19Sha256':sha256((docs/'ordinary-rules-combined.candidate.json').read_bytes()).hexdigest(),
          'datasetSha256':sha256((w/'cases.json').read_bytes()).hexdigest(),
          'cases':{r['file']:r['sha256'] for r in cases},
          'qualification':'development diagnostics only; zero new independent qualification cases',
          'requiredCoverage':[r['id'] for r in cases if r['requiredArityCoverage']],
          'candidateMayAlertNormalCode':True, 'rulesDeployed':False, 'r3Qualified':False}
(w/'intent.json').write_text(json.dumps(intent,indent=2)+'\n')
plan = {'version':1, 'imageId':'sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7',
        'probeSha256':sha256((w/'probe.py').read_bytes()).hexdigest(),
        'sources':{r['file']:r['sha256'] for r in cases if r['role']!='reused-upstream-normal-source'},
        'vectors':vectors, 'independentCases':0, 'qualifiesForR3':False,
        'scope':'fixed plain-string arithmetic only; direct controlled calls, no HTTP or vulnerability truth'}
(w/'protocol.json').write_text(json.dumps(plan,indent=2)+'\n')
print(json.dumps({'cases':len(cases),'authored':len(cases)-2,'vectors':len(vectors),'requiredCoverage':intent['requiredCoverage']}))
