"""Add one sink-only research rule; preserve all previous definitions verbatim."""
from pathlib import Path
from hashlib import sha256
import datetime, json
w = Path(__file__).resolve().parent
repo = w.parents[1] / 'exports/deepseek-harness-vm'
intent = json.loads((w/'intent.json').read_text())
if (w/'candidate-freeze.json').exists():
    raise SystemExit('Frozen candidate already exists. Use a new experiment directory.')
base = (repo/'work/harness-purge-improved/security-rules.json').read_bytes()
combined = (repo/'docs/security-workspace/ordinary-rules-combined.candidate.json').read_bytes()
assert sha256(base).hexdigest()==intent['baselineSha256']
assert sha256(combined).hexdigest()==intent['combined19Sha256']
original = json.loads(base)['rules']
previous = json.loads(combined)['rules']
assert len(original)==16 and len(previous)==19 and previous[:16]==original
addition = {'id':'harness.python.dynamic-code-namespace', 'languages':['python'],
            'severity':'WARNING',
            'message':'动态执行点含 globals/locals 参数：需核对输入来源、名称绑定及约束是否覆盖执行点；这不是已确认漏洞',
            'metadata':{'category':'security', 'cwe':['CWE-95'], 'confidence':'LOW',
                        'source':'Harness local sink-inventory research candidate',
                        'requires-manual-review':True, 'evidence-level':'sink-only',
                        'qualification':'unverified', 'no-automatic-suppression':True,
                        'scope':'two or three positional arguments; no callee identity or input-source proof'},
            'pattern-either':[{'pattern':op+'('+args+')'} for op in ['eval','exec']
                             for args in ['$CODE, $GLOBALS','$CODE, $GLOBALS, $LOCALS']]}
freeze = {'version':1, 'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'intentSha256':sha256((w/'intent.json').read_bytes()).hexdigest(),
          'datasetSha256':intent['datasetSha256'], 'rulesDeployed':False,
          'r3Qualified':False, 'independentQualificationCases':0, 'packs':{}}
for name, rules in [('arity17',original),('combined20',previous)]:
    assert addition['id'] not in {r['id'] for r in rules}
    output = (json.dumps({'rules':rules+[addition]},ensure_ascii=False,indent=2)+'\n').encode()
    assert json.loads(output)['rules'][:-1]==rules
    (w/(name+'.candidate.json')).write_bytes(output)
    freeze['packs'][name] = {'sha256':sha256(output).hexdigest(), 'ruleCount':len(rules)+1,
                              'preservedIds':[r['id'] for r in rules], 'addedId':addition['id']}
(w/'candidate-freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
print(json.dumps(freeze['packs']))
