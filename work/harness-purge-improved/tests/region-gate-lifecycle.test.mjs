import assert from 'node:assert/strict';
import test from 'node:test';
import { installRegionGate } from '../package/lib/net-scope.js';

function gate() {
  let beforeStep;
  installRegionGate({ on(name, handler) { if (name === 'agent/pre-step') beforeStep = handler; } });
  return beforeStep;
}

function payload(session, turn = 1) {
  return {
    turn,
    step: 1,
    agent: { session },
    messages: [{ id: 'fixture-user', role: 'user', source: { kind: 'user' },
      content: [{ type: 'text', text: 'Scan and exploit http://203.0.113.10/' }] }],
  };
}

test('a gate reply ends the proposed turn instead of admitting a duplicate first step', async () => {
  const records = [];
  const session = { append(type, data) { records.push({ type, data }); } };
  let forwarded = 0;
  const decision = await gate()(payload(session), () => { forwarded++; return { kind: 'enter', messages: [] }; });
  assert.equal(decision.kind, 'reject');
  assert.equal(forwarded, 0);
  assert.deepEqual(records.filter(event => event.type.startsWith('step/')).map(event => event.type),
    ['step/start', 'step/end']);
  assert.equal(records.filter(event => event.type === 'assistant/message').length, 1);
});

test('a denied task remains rejected if the reply cannot be written', async () => {
  const session = { append() { throw new Error('fixture write failure'); } };
  let forwarded = 0;
  const decision = await gate()(payload(session), () => { forwarded++; return { kind: 'enter', messages: [] }; });
  assert.equal(decision.kind, 'reject');
  assert.equal(forwarded, 0);
});

test('an ordinary local question still delegates to the next pre-step handler', async () => {
  const session = { append() { assert.fail('ordinary input should not create a gate reply'); } };
  const input = payload(session);
  input.messages[0].content[0].text = 'Explain this Python function.';
  let forwarded = 0;
  const expected = { kind: 'enter', messages: input.messages };
  const decision = await gate()(input, () => { forwarded++; return expected; });
  assert.equal(decision, expected);
  assert.equal(forwarded, 1);
});
