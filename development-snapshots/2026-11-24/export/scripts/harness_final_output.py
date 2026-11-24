"""Collect CLI final records from complete captured stdout before diagnostic truncation."""
from hashlib import sha256
import json


def capture_final_output(stdout):
    finals = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('type') == 'final':
            if not isinstance(value.get('text'), str):
                raise ValueError('CLI final text must be a string')
            finals.append(value['text'])
    raw = stdout.encode()
    return {'finalCount': len(finals), 'finalText': finals[0] if len(finals) == 1 else None,
            'stdoutSha256': sha256(raw).hexdigest(), 'stdoutBytes': len(raw)}


def bind_final_output(stdout, assistant_text, scrub):
    """Bind exact raw text in memory, then redact both stored representations."""
    output = capture_final_output(stdout)
    if output['finalCount'] != 1 or not isinstance(assistant_text, str):
        raise ValueError('One final and one assistant text are required')
    raw_final = output['finalText']
    if raw_final != assistant_text:
        raise ValueError('Raw CLI final and assistant text differ')
    redacted_final = scrub(raw_final)
    redacted_assistant = scrub(assistant_text)
    if not isinstance(redacted_final, str) or redacted_final != redacted_assistant:
        raise ValueError('Redaction must produce matching text strings')
    output.update(finalText=redacted_final, assistantText=redacted_assistant,
                  rawBinding={'rawTextMatch': True, 'comparison': 'exact-before-redaction',
                              'finalSha256': sha256(raw_final.encode()).hexdigest(),
                              'assistantSha256': sha256(assistant_text.encode()).hexdigest(),
                              'redactionChangedFinal': raw_final != redacted_final})
    return output
