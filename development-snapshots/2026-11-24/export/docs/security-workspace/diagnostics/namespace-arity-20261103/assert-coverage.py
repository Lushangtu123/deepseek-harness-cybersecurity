"""TDD assertion over real Semgrep receipts, not a JSON-shape imitation."""
from pathlib import Path
import ast, json, sys
w = Path(__file__).resolve().parent
cases = json.loads((w/'cases.json').read_text())
result = json.loads((w/(sys.argv[1]+'-scan.json')).read_text())
assert result['scannerExitCode']==0 and not result['native']['result']['errors']
assert all(result[k] for k in ['runtimeRulesUnchanged','scannerManifestUnchanged','containerAbsent','temporaryRemoved'])
scanned = {Path(p).name for p in result['native']['result']['paths']['scanned']}
assert scanned == {r['file'] for r in cases}
sites = {(r['check_id'],Path(r['path']).name,r['start']['line'],r['start']['col'],r['end']['line'],r['end']['col']) for r in result['native']['result']['results']}
missing = []
for row in cases:
    if not row['requiredArityCoverage']: continue
    call, = [n for n in ast.walk(ast.parse(row['source'])) if isinstance(n,ast.Call)
             and isinstance(n.func,ast.Name) and n.func.id in ['eval','exec']]
    rule = 'policy.harness.python.'+(call.func.id if len(call.args)==1 else 'dynamic-code-namespace')
    expected = (rule,row['file'],call.lineno,call.col_offset+1,call.end_lineno,call.end_col_offset+1)
    if expected not in sites: missing.append(row['id'])
assert not missing, 'Missing dynamic-code sites: '+', '.join(missing)
print(json.dumps({'ok':True,'requiredCases':6,'actuallyScanned':len(scanned)}))
