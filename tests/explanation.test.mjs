import test from 'node:test';
import assert from 'node:assert/strict';
import { ExplanationLoader } from '../static/explanation.js';

const session = () => ({ id: 'trip', revision: 2, agent: { explanation_status: 'pending' }, response_timing: { limit_seconds: 10, elapsed_seconds: 1 } });

test('a late explanation cannot replace a newer trip revision', async () => {
  let current = session();
  let release;
  let updates = 0;
  const loader = new ExplanationLoader({
    getSession: () => current,
    request: () => new Promise(resolve => { release = resolve; }),
    apply: () => { updates++; }
  });
  const task = loader.load();
  current = { ...current, revision: 3 };
  release({ revision: 2, agent: { mode: 'llm' } });
  await task;
  assert.equal(updates, 0);
});

test('explanation updates only its panel, once per revision', async () => {
  const current = session();
  let calls = 0;
  let received;
  const loader = new ExplanationLoader({
    getSession: () => current,
    request: async () => { calls++; return { revision: 2, agent: { mode: 'llm' } }; },
    apply: agent => { received = agent; }
  });
  await loader.load();
  await loader.load();
  assert.equal(calls, 1);
  assert.equal(received.mode, 'llm');
  assert.equal(current.revision, 2);
});

test('network failure retains facts with an honest local notice', async () => {
  const current = session();
  current.agent.facts = [{ id: 'verified' }];
  let received;
  const loader = new ExplanationLoader({
    getSession: () => current,
    request: async () => { throw new Error('offline'); },
    apply: agent => { received = agent; }
  });
  await loader.load();
  assert.equal(received.mode, 'local');
  assert.deepEqual(received.facts, current.agent.facts);
  assert.ok(received.notice);
});

test('cancelling an obsolete request aborts it without replacing the panel', async () => {
  const current = session();
  let signal;
  let updates = 0;
  const loader = new ExplanationLoader({
    getSession: () => current,
    request: async (_, options) => { signal = options.signal; return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('abort')))); },
    apply: () => { updates++; }
  });
  const task = loader.load();
  loader.cancel();
  await task;
  assert.ok(signal.aborted);
  assert.equal(updates, 0);
});
