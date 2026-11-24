"""Independent raw-evidence verification. Does not import the collector."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json

MODES = ('unqueued', 'existing-queue')
MANAGER_SHA = '69cc27ae32ba7be4362e6a4d94a4f253ac54d573380c98f58fa40bdb8758e401'


def need(condition, message):
    if not condition: raise ValueError(message)


def analyze(root):
    root = Path(root)
    contract_raw = (root/'execution-contract.json').read_bytes()
    result_raw = (root/'control-results.json').read_bytes()
    contract = json.loads(contract_raw); result = json.loads(result_raw)
    need(result['contractSha256'] == sha256(contract_raw).hexdigest(), 'Contract digest mismatch')
    required = {'tooling/admission.py', 'record-analysis.py', 'tooling/regression.test.py',
                'tooling/analysis.test.py', 'tooling/r2.test.py', 'inputs/manage.py'}
    need(required <= set(contract['sources']), 'Missing source gate')
    for name, expected in contract['sources'].items():
        path = Path(name)
        need(not path.is_absolute() and '..' not in path.parts, 'Invalid source path')
        need(sha256((root/path).read_bytes()).hexdigest() == expected, 'Source digest mismatch')
    need(contract['sources']['inputs/manage.py'] == MANAGER_SHA, 'Wrong manager snapshot')
    planned = [(r['block'], r['mode']) for r in contract['schedule']]
    need(len(planned) == 8 and set(planned) == {(b,m) for b in range(4) for m in MODES},
         'Incomplete or repeated schedule')
    trials = result['trials']
    need([(t['block'], t['mode']) for t in trials] == planned, 'Collected schedule mismatch')
    need(contract['maxClients'] == 48, 'Unexpected sample budget')
    counts = {m: Counter() for m in MODES}; errors = {m: Counter() for m in MODES}
    not_sent_reasons = {m: Counter() for m in MODES}; responses_without_completion = 0
    for trial in trials:
        mode = trial['mode']; count = counts[mode]; count['trials'] += 1
        need(trial['workersReaped'] is True and trial['serverStopped'] is True, 'Cleanup unconfirmed')
        if 'cleanup' in trial: need(trial['cleanup']['ok'] is True, 'Cleanup had exceptions or cancellation')
        clients = trial['clients']
        need(len(clients) == 6 and sorted(c['index'] for c in clients) == list(range(6)), 'Worker mismatch')
        responded = set(); last_accept = 0
        need(type(trial['releaseMonoNs']) is int and trial['releaseMonoNs'] > 0, 'Invalid release time')
        need(len(trial['serverEvents']) <= sum(c['commandCalls'] for c in clients), 'Too many accepts')
        for event in trial['serverEvents']:
            accepted = event.get('acceptedMonoNs')
            need(type(accepted) is int and accepted >= trial['releaseMonoNs'] and
                 accepted >= last_accept, 'Invalid accept time or order')
            last_accept = accepted
            need(type(event.get('responseSent')) is bool and type(event.get('requestBytes')) is int and
                 event['requestBytes'] in (0,1) and event['responseSent'] == (event['requestBytes'] == 1),
                 'Invalid response event schema')
            if event['responseSent'] is True:
                index = event.get('requestIndex')
                need(type(index) is int and 0 <= index < 6 and index not in responded and event['requestBytes'] == 1,
                     'Invalid or duplicate server response')
                client = next(c for c in clients if c['index'] == index)
                need(client['commandCalls'] == 1 and client['connected'] is True and
                     accepted >= client['exchangeStartedMonoNs'], 'Response lacks an attempted connection')
                if client['complete']:
                    need(accepted <= client['exchangeEndedMonoNs'], 'Accept follows completed exchange')
                responded.add(index)
            else:
                need(event.get('requestIndex') is None, 'Empty request carries an index')
        for client in clients:
            need(type(client['connected']) is bool and type(client['complete']) is bool, 'Outcome types invalid')
            need(type(client['commandCalls']) is int and client['commandCalls'] in (0,1), 'Invalid executor count')
            need(type(client['returncode']) is int and client['returncode'] in (0,1), 'Invalid outcome code')
            timing = ['requestEnteredMonoNs', 'requestEndedMonoNs']
            if client['commandCalls'] == 0:
                need(client.get('requestState') == 'not-sent' and not client['complete'] and
                     not client['connected'] and client['returncode'] == 1 and
                     client.get('errorStage') == 'queue' and client.get('errorType') == 'SSHNotSent' and
                     not any(k in client for k in ['exchangeStartedMonoNs', 'exchangeEndedMonoNs', 'connectReturnedMonoNs']) and
                     client['index'] not in responded, 'Unproven not-sent state')
                count['notSent'] += 1
                not_sent_reasons[mode]['queue|SSHNotSent|'+str(client.get('errno'))] += 1
            else:
                timing.insert(1, 'exchangeStartedMonoNs'); timing.insert(2, 'exchangeEndedMonoNs')
                if client['connected']: timing.insert(2, 'connectReturnedMonoNs')
                else: need('connectReturnedMonoNs' not in client, 'Unconnected outcome has connect timestamp')
                if client['complete']:
                    need(client.get('requestState') == 'complete' and client['connected'] and
                         client['returncode'] == 0 and not client.get('errorType') and client['index'] in responded,
                         'Completion lacks consistent client/server evidence')
                    count['complete'] += 1
                else:
                    need(client.get('requestState') == 'failed' and client['returncode'] == 1 and
                         isinstance(client.get('errorType'),str) and bool(client['errorType']), 'Inconsistent failure')
                    count['failed'] += 1
                    errors[mode][client.get('errorStage','unknown')+'|'+client['errorType']+'|'+str(client.get('errno'))] += 1
                    responses_without_completion += client['index'] in responded
            values = [client[k] for k in timing]
            need(all(type(v) is int and v > 0 for v in values) and values == sorted(values), 'Timestamp order invalid')
            count['clients'] += 1; count['connected'] += client['connected']
    aggregates = []
    for mode in MODES:
        counter = counts[mode]
        row = {key: counter[key] for key in ['trials','clients','connected','complete','failed','notSent']}
        row.update(mode=mode, errors=dict(errors[mode]), notSentReasons=dict(not_sent_reasons[mode]))
        need(row['clients'] == row['complete']+row['failed']+row['notSent'], 'Outcome denominator mismatch')
        aggregates.append(row)
    need(aggregates == result['aggregates'], 'Stored aggregate differs from raw evidence')
    return dict(state='independently-verified', independentlyRecomputed=True, sourcesVerified=True,
                generatorSha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                contractSha256=sha256(contract_raw).hexdigest(), resultSha256=sha256(result_raw).hexdigest(),
                aggregates=aggregates, responsesWithoutClientCompletion=responses_without_completion,
                optimizationSafeExplicitChecks=True, newVmRequests=0,
                scope='raw evidence verification, not production cause or complete tool safety proof')


def write_analysis(root):
    result = analyze(root)
    with (Path(root)/'analysis.json').open('x') as stream: json.dump(result, stream, indent=2)
    return result


if __name__ == '__main__':
    result = write_analysis(Path(__file__).resolve().parent)
    print(json.dumps(result, indent=2))
