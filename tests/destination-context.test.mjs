import test from 'node:test';
import assert from 'node:assert/strict';
import { DestinationLoader, validExternal } from '../static/destination-context.js';

test('destination loader ignores stale data and never changes trip state', async () => {
  let session = { id: 'a', revision: 1, requirements: { destination: 'Сочи' } };
  let resolve;
  const updates = [];
  const loader = new DestinationLoader({ current: () => session, update: data => updates.push(data),
    request: () => new Promise(done => { resolve = done; }) });
  const task = loader.load();
  session = { ...session, revision: 2 };
  resolve({ revision: 1 });
  await task;
  assert.equal(updates.length, 0);
  assert.equal(session.revision, 2);
});

test('repeated render loads each revision once and failures are visible', async () => {
  const session = { id: 'a', revision: 2, requirements: { destination: 'Сочи' } };
  let calls = 0;
  let result;
  const loader = new DestinationLoader({ current: () => session, update: data => { result = data; },
    request: async () => { calls++; throw new Error('offline'); } });
  await loader.load();
  await loader.load();
  assert.equal(calls, 1);
  assert.equal(result.status, 'unavailable');
});

test('external links reject arbitrary hosts and executable URLs', () => {
  for (const url of ['javascript:alert(1)', 'https://evil.test/', 'https://www.openstreetmap.org.evil.test/', 'https://key:secret@www.openstreetmap.org/']) assert.equal(validExternal(url), null);
  assert.ok(validExternal('https://www.openstreetmap.org/node/123'));
});
