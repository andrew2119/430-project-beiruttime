import assert from 'node:assert/strict';
import { deferred } from './browser.mjs';

// These contracts can be exercised locally without certifying a connected page.
// A mounted page must supply current bindings and perform its own commands.
export const pending = {
  F33: { role: 'private-seller', schema: 'orders.releases.v1', success: 'paid_out',
    fields: ['subject_id', 'watch_id', 'organization_id', 'quote_id', 'quote_revision', 'policy_revision', 'recipient_id', 'recipient_revision'],
    missing: 'ReleaseDesk has no published route or current order binding' },
  F34: { role: 'operator', schema: 'refunds.v1', success: 'confirmed',
    fields: ['subject_id', 'watch_id', 'organization_id', 'source_revision', 'quote_id', 'quote_revision', 'policy_revision', 'basis_id'],
    missing: 'RefundView has no published route or scope-bound RefundPort' },
  F45: { role: 'brand', schema: 'brand-assessment.v1', success: 'assessed',
    fields: ['subject_id', 'watch_id', 'organization_id', 'request_revision', 'assignment_revision', 'capability_revision'],
    missing: 'AssessmentForm has no published route bound to the current request and quote composition' },
  F46: { role: 'reviewer', schema: 'eligibility-command.v1', success: 'eligible',
    fields: ['consent_id'],
    missing: 'The consent page has no published assignment read supplying current consent and decision revision' },
  F48: { role: 'brand', schema: 'orders.brand-jobs.v1', success: 'authorized',
    fields: ['subject_id', 'watch_id', 'organization_id', 'quote_id', 'quote_revision', 'policy_revision'],
    missing: 'BrandJobStatus has no mounted production and material change journey or current job binding' },
};

export function disconnectedPage(feature) {
  return { current: async () => deferred(feature, pending[feature].missing) };
}

function commandFor(feature, current, actor, reference) {
  const spec = pending[feature];
  assert.ok(Number.isInteger(current.revision) && current.revision >= 0);
  const command = { schema_version: spec.schema, operation_id: reference,
    expected_revision: current.revision };
  for (const field of spec.fields) {
    assert.ok(Object.hasOwn(current, field), `Missing current binding: ${field}`);
    command[field] = current[field];
  }
  if (feature !== 'F46') command.actor_id = actor.actor_id;
  if (feature === 'F34') {
    assert.ok(current.remaining_minor > 0);
    command.amount_minor = Math.min(100, current.remaining_minor);
    command.currency = 'USD';
  }
  if (feature === 'F45') Object.assign(command, { kind: 'assess', replacement_id: null,
    feasibility: 'manual', parts: [], limitations: 'test current scope requires review',
    lead_time_basis: 'test current parts availability', reason: '' });
  if (feature === 'F46') Object.assign(command, { kind: 'review', verdict: 'eligible',
    reason: 'test independent review of current synthetic facts' });
  if (feature === 'F48') {
    // The private authorization command has no schema_version member.
    delete command.schema_version;
    command.kind = 'customization';
  }
  return Object.freeze(command);
}

function checkReceipt(feature, value, command, actor) {
  assert.equal(value.operation_id, command.operation_id);
  assert.equal(value.actor_id, actor.actor_id);
  for (const key of ['subject_id', 'watch_id', 'organization_id', 'expected_revision']) {
    if (Object.hasOwn(command, key)) assert.equal(value[key], command[key]);
  }
  assert.equal(value.state, pending[feature].success);
  assert.ok(Number.isInteger(value.revision) && value.revision > command.expected_revision);
  const schema = feature === 'F46' ? 'eligibility-result.v1' : pending[feature].schema;
  assert.equal(value.schema_version, schema);
  if (feature === 'F33') {
    assert.equal(value.simulated, true);
    assert.deepEqual(value.missing, []);
    assert.equal(value.pending_reason, null);
    assert.equal(value.gross_minor, value.fee_minor + value.net_minor);
  }
  if (feature === 'F34') {
    assert.equal(value.simulated, true);
    assert.equal(value.amount_minor, command.amount_minor);
    assert.equal(value.currency, 'USD');
  }
  if (feature === 'F48') {
    assert.ok(value.job_id);
    assert.ok(value.assignee_id);
    assert.equal(value.permitted_start_state, 'requires_current_start_check');
  }
}

// Port methods represent page interactions: current reads displayed source
// bindings, submit fills and sends the form, lookup restores its same reference,
// and visible checks the rendered outcome. No local result enters matrix proof.
export async function runPending(feature, mode, actor, reference, port) {
  assert.ok(['journey', 'negative', 'recovery'].includes(mode));
  const current = await port.current();
  const command = commandFor(feature, current, actor, reference());
  if (mode === 'negative') {
    const invalid = Object.freeze({ ...command, expected_revision: command.expected_revision + 1 });
    const refusal = await port.submit(invalid);
    assert.ok([403, 409, 422].includes(refusal.status));
    assert.ok(refusal.json?.code || refusal.json?.error || refusal.json?.detail);
    const operation = refusal.json?.request_id || refusal.json?.error?.request_id || refusal.request_id;
    assert.ok(operation, 'Refusal requires the returned request reference');
    await port.visible('refused', operation);
    return { operation_id: operation, actor_id: actor.actor_id };
  }
  const first = await port.submit(command);
  // A lost response is not a failed command; lookup must use the frozen bytes.
  assert.ok(first === null ? mode === 'recovery' : first.status >= 200 && first.status < 300);
  const result = mode === 'recovery' ? await port.lookup(command) : first;
  assert.ok(result.status >= 200 && result.status < 300);
  checkReceipt(feature, result.json, command, actor);
  if (first) assert.deepEqual(result.json, first.json);
  await port.visible(pending[feature].success, command.operation_id);
  return { operation_id: result.json.operation_id, actor_id: actor.actor_id };
}
