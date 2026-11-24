"""Record exact read-only review inputs and confirm the original zero-check outputs."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
package = root.parents[1] / 'exports/deepseek-harness-vm/work/harness-purge-improved/package'
sources = json.loads((root / 'source-provenance-pre-run.json').read_bytes())['sources']
records = []
for phase in ['baseline', 'candidate']:
    scan_file = root / (phase + '-scan.json')
    scan = json.loads(scan_file.read_bytes())['native']['result']
    request = {'files': {row['file']: row['sha256'] for row in sources}, 'results': scan['results']}
    body = json.dumps(request)
    argv = ['python3', '-I', '-B', str(package / 'scripts/eval_evidence_batch.py'), '--managed', str(root)]
    run = subprocess.run(argv, input=body, capture_output=True, text=True, check=True, timeout=20)
    if json.loads(run.stdout) != json.loads((root / (phase + '-review.json')).read_bytes()):
        raise ValueError('Original static review output changed')
    records.append({'phase': phase, 'argv': argv, 'requestSha256': sha256(body.encode()).hexdigest(),
                    'request': request, 'scanFileSha256': sha256(scan_file.read_bytes()).hexdigest(),
                    'response': json.loads(run.stdout), 'exitCode': run.returncode})
(root / 'review-replay.json').write_text(json.dumps({'state': 'passed', 'records': records,
    'capturedAt': datetime.now(timezone.utc).isoformat(), 'originalOutputsMatched': True,
    'scope': 'Post-review replay with recorded bindings. No claim that the original inline command was a pre-existing script file.'},
    ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'state': 'passed', 'originalOutputsMatched': True, 'recordedInvocations': len(records)}))
