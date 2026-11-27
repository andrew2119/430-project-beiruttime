import { schemaVersion } from './contract.mjs';
// Synthetic uncommitted responses; none records a completed transaction.
const base = {
  schema_version: schemaVersion, operation_id: 'operation-1', subject_id: 'buyer-1',
  watch_id: 'watch-1', actor_id: 'buyer-1', organization_id: null,
  assignment_id: 'assignment-1', assignment_revision: 2,
  quote_id: 'quote-1', quote_revision: 3, policy_revision: 1,
  expected_revision: 4, revision: 4, state: 'pending', pending_reason: 'confirmation_missing',
  next_actor: 'operator-1', next_review_at: '2026-11-18T12:00:00Z',
};
export const fixtures = Object.freeze({
  request: { ...base },
  success: { ...base, state: 'confirmed', revision: 5, pending_reason: null },
  denied: { ...base, state: 'denied', pending_reason: null },
  stale: { ...base, expected_revision: 3, state: 'denied', pending_reason: null },
  lost_response: null,
  timeout: { ...base, state: 'unavailable', pending_reason: null },
  duplicate: { ...base },
});
