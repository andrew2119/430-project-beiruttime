import assert from 'node:assert/strict';
import test from 'node:test';
import { emailContract } from './email-contract.mjs';

for (const mode of ['journey', 'negative', 'recovery']) {
  test(`email ${mode} uses a local producer contract without connected certification`, async () => {
    const actor = { actor_id: 'test-buyer' };
    const record = { schema_version: 'transaction-email.v1', operation_id: 'test-email-operation',
      actor_id: actor.actor_id, synthetic: true, state: 'captured' };
    let captures = 0, reads = 0, reloads = 0, destinations = 0;
    const shown = [];
    await emailContract(mode, actor, {
      capture: async () => { captures++; return record; },
      open: async (operation, role) => {
        reads++;
        assert.equal(operation, record.operation_id);
        return role === 'buyer2' ? { status: 404, json: { error: { code: 'not_found' } } }
          : { status: 200, json: { ...record } };
      },
      reload: async () => { reloads++; },
      visible: async value => { shown.push(value); },
      destination: async operation => {
        destinations++;
        assert.equal(operation, record.operation_id);
        return { status: 200, json: { url: '/inbox' } };
      },
    });
    assert.equal(captures, 1);
    assert.equal(reads, mode === 'recovery' ? 2 : 1);
    assert.equal(reloads, mode === 'recovery' ? 1 : 0);
    assert.equal(destinations, mode === 'negative' ? 0 : 1);
    assert.deepEqual(shown, mode === 'negative' ? ['denied'] :
      Array(mode === 'recovery' ? 2 : 1).fill(record.operation_id));
  });
}

test('email recovery rejects a different operation reference', async () => {
  let reads = 0;
  const record = { schema_version: 'transaction-email.v1', operation_id: 'test-email-operation',
    actor_id: 'test-buyer', synthetic: true, state: 'captured' };
  await assert.rejects(emailContract('recovery', { actor_id: record.actor_id }, {
    capture: async () => record,
    open: async () => ({ status: 200, json: { ...record,
      operation_id: ++reads === 1 ? record.operation_id : 'test-other-operation' } }),
    visible: async () => {}, reload: async () => {},
    destination: async () => assert.fail('changed reference must not navigate'),
  }));
});
