import assert from 'node:assert/strict';
import test from 'node:test';
import { pending, runPending } from './pending-scenarios.mjs';

for (const feature of Object.keys(pending)) {
  for (const mode of ['journey', 'negative', 'recovery']) {
    test(`${feature} ${mode} exercises its published binding with a local page stub`, async () => {
      const actor = { actor_id: 'test-actor' };
      const current = { revision: 2, remaining_minor: 250 };
      for (const field of pending[feature].fields) current[field] = field.endsWith('revision') ? 2 : `test-${field}`;
      let frozen, outcome, effects = 0, shown;
      const port = {
        current: async () => current,
        submit: async command => {
          frozen = command;
          if (command.expected_revision !== current.revision) return {
            status: 409, json: { code: 'stale', request_id: 'test-refusal' },
          };
          effects++;
          outcome = { ...command, actor_id: actor.actor_id, state: pending[feature].success,
            schema_version: feature === 'F46' ? 'eligibility-result.v1' : pending[feature].schema,
            revision: command.expected_revision + 1, simulated: true, missing: [], pending_reason: null, gross_minor: 100, fee_minor: 10,
            net_minor: 90, job_id: 'test-job', assignee_id: 'test-assignee',
            permitted_start_state: 'requires_current_start_check' };
          return mode === 'recovery' ? null : { status: 200, json: outcome };
        },
        lookup: async command => {
          assert.equal(command, frozen, 'recovery must retain the frozen command');
          return { status: 200, json: outcome };
        },
        visible: async (state, reference) => { shown = [state, reference]; },
      };
      const proof = await runPending(feature, mode, actor, () => 'test-operation', port);
      assert.deepEqual(proof, { operation_id: mode === 'negative' ? 'test-refusal' : 'test-operation', actor_id: actor.actor_id });
      assert.equal(effects, mode === 'negative' ? 0 : 1);
      assert.deepEqual(shown, [mode === 'negative' ? 'refused' : pending[feature].success, proof.operation_id]);
      assert.equal(current.revision, 2);
    });
  }
  test(`${feature} cannot accept an unrelated recovery receipt`, async () => {
    const current = { revision: 2, remaining_minor: 100 };
    for (const field of pending[feature].fields) current[field] = field.endsWith('revision') ? 2 : `test-${field}`;
    await assert.rejects(runPending(feature, 'recovery', { actor_id: 'test-actor' }, () => 'test-operation', {
      current: async () => current, submit: async () => null,
      lookup: async () => ({ status: 200, json: { operation_id: 'test-other' } }),
      visible: async () => assert.fail('unrelated receipt must not be shown as successful'),
    }));
  });
}
