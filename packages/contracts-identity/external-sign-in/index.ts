export type ExternalState = 'ready' | 'pending' | 'signed_in' | 'linked' | 'denied' | 'stale' | 'unavailable';
export type ExternalOperation = {
  schema_version: 1; operation_id: string; subject_id: string | null;
  watch_id: null; actor_id: string | null; organization_id: string | null;
  expected_revision: number; state: ExternalState; revision: number;
  pending_reason: 'identity_unavailable' | null; next_actor: 'buyer' | 'identity'; next_review_at: null;
};
export type ExternalCallback = {schema_version: 1; operation_id: string; expected_revision: number; state: string; code: string};
