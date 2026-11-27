import test from 'node:test';
import assert from 'node:assert/strict';
import { operations, journeys, states, messages, validateEnvelope, reconcile, money, beforeDeadline } from './contract.mjs';
import { fixtures as f } from './fixtures.mjs';
import { requirements, summarize } from './manifest.mjs';
const current = { actor_id: 'buyer-1', organization_id: null, revision: 4, allowed: true,
  assignment_id: 'assignment-1', assignment_revision: 2,
  quote_id: 'quote-1', quote_revision: 3, policy_revision: 1 };
test('all journeys have bounded lookup and bilingual recovery states', () => {
  for (const journey of journeys) {
    assert.equal(operations[journey].offline_queue, false);
    assert.equal(operations[journey].max_attempts, 2);
    assert.equal(operations[journey].timeout_ms, 5000);
  }
  for (const state of states) assert.ok(messages[state].every(value => value.length > 0));
});
test('success, denied, stale, lost response, timeout and duplicate contracts', () => {
  for (const value of Object.values(f).filter(Boolean)) validateEnvelope(value);
  assert.equal(reconcile(f.request, f.success, current), 'confirmed');
  assert.equal(reconcile(f.request, f.denied, current), 'denied');
  assert.equal(reconcile(f.request, f.stale, current), 'denied');
  assert.equal(reconcile(f.request, f.lost_response, current), 'pending');
  assert.equal(reconcile(f.request, f.timeout, current), 'unavailable');
  assert.equal(reconcile(f.request, f.duplicate, current), 'pending');
  assert.equal(reconcile(f.request, f.success, { ...current, revision: 5 }), 'denied');
});
test('every receipt binding rejects substitution', () => {
  for (const key of ['operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id']) {
    assert.equal(reconcile(f.request, { ...f.success, [key]: 'other' }, current), 'denied');
  }
});
test('identity, organization and access changes purge even a successful response', () => {
  for (const changed of [{ actor_id: 'buyer-2' }, { organization_id: 'business-2' }, { allowed: false }]) {
    assert.equal(reconcile(f.request, f.success, { ...current, ...changed }), 'purge');
  }
});
test('invalid revisions, missing recovery and unsafe money fail closed', () => {
  for (const revision of [-1, 1.5, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => validateEnvelope({ ...f.request, revision }));
  }
  assert.throws(() => validateEnvelope({ ...f.request, next_actor: null }));
  assert.throws(() => validateEnvelope({ ...f.request, next_review_at: 'tomorrow' }));
  for (const value of [-1, 0.01, NaN, Infinity, '500000', Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => money(value));
  assert.equal(money(515000), 515000);
  assert.equal(money(500000), 500000);
});
test('deadline is strict before, never equal or after', () => {
  const deadline = '2026-11-18T12:00:00Z';
  assert.equal(beforeDeadline('2026-11-18T11:59:59Z', deadline), true);
  assert.equal(beforeDeadline(deadline, deadline), false);
  assert.equal(beforeDeadline('2026-11-18T12:00:01Z', deadline), false);
  assert.throws(() => beforeDeadline('2026-11-18T12:00:00', deadline));
});
test('matrix is complete and fixtures cannot certify connected acceptance', () => {
  assert.equal(requirements.length, 1920);
  assert.equal(new Set(requirements.map(row => row.id)).size, 1920);
  assert.equal(summarize().remaining.length, 1920);
  assert.equal(summarize().complete, false);
  assert.throws(() => summarize([{ id: requirements[0].id, result: 'pass', source: 'fixture' }]));
  const skip = { id: requirements[0].id, result: 'skip', reason: 'Separate release clearance required' };
  assert.equal(summarize([skip]).remaining.length, 1920);
  assert.throws(() => summarize([skip, skip]));
});
test('phone observations require actual viewport and a physical device', () => {
  const pass = { result: 'pass', source: 'connected', reference: 'external-record-1', observed_at: '2026-11-18T12:00:00Z' };
  const phone = requirements.find(row => row.device === '390x844');
  assert.throws(() => summarize([{ ...pass, id: phone.id, innerWidth: 389, innerHeight: 844 }]));
  assert.equal(summarize([{ ...pass, id: phone.id, innerWidth: 390, innerHeight: 844 }]).passed, 1);
  const physical = requirements.find(row => row.device === 'physical-phone');
  assert.throws(() => summarize([{ ...pass, id: physical.id }]));
});

test('retained quote, policy and assignment substitutions never confirm', () => {
  for (const [key, value] of Object.entries({
    assignment_id: 'assignment-2', assignment_revision: 1,
    quote_id: 'quote-2', quote_revision: 2, policy_revision: 0, expected_revision: 3,
  })) {
    assert.equal(reconcile(f.request, { ...f.success, [key]: value }, current), 'denied');
  }
  assert.equal(reconcile(f.request, { ...f.success, revision: 3 }, current), 'denied');
});
test('current assignment revocation purges before missing or late responses', () => {
  for (const changed of [
    { assignment_id: 'assignment-2' }, { assignment_revision: 3 },
    { assignment_id: null, assignment_revision: null }, { assignment_revision: undefined },
  ]) {
    for (const response of [f.success, null]) {
      assert.equal(reconcile(f.request, response, { ...current, ...changed }), 'purge');
    }
  }
});
test('current retained terms and source revision fail closed before reconciliation', () => {
  for (const changed of [
    { quote_id: 'quote-2' }, { quote_revision: 4 }, { policy_revision: 2 },
    { revision: 5 }, { quote_revision: undefined }, { policy_revision: undefined },
  ]) {
    for (const response of [f.success, null]) {
      assert.equal(reconcile(f.request, response, { ...current, ...changed }), 'denied');
    }
  }
});
test('bindings require explicit applicability and safe revisions', () => {
  for (const key of ['assignment_id', 'assignment_revision', 'quote_id', 'quote_revision', 'policy_revision']) {
    const missing = { ...f.request };
    delete missing[key];
    assert.throws(() => validateEnvelope(missing));
  }
  for (const key of ['assignment_revision', 'quote_revision', 'policy_revision']) {
    for (const value of [-1, 0.5, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      assert.throws(() => validateEnvelope({ ...f.request, [key]: value }));
    }
  }
  const unscoped = { assignment_id: null, assignment_revision: null, quote_id: null, quote_revision: null };
  assert.equal(reconcile({ ...f.request, ...unscoped }, { ...f.success, ...unscoped },
    { ...current, ...unscoped }), 'confirmed');
  assert.throws(() => validateEnvelope({ ...f.request, quote_id: null }));
  assert.throws(() => validateEnvelope({ ...f.request, assignment_revision: null }));
});
