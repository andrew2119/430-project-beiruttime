export type EligibilityCommand = {
  schema_version: 'eligibility-command.v1'; operation_id: string; consent_id: string;
  expected_revision: number; kind: 'review' | 'prepare' | 'consume' | 'revoke';
  verdict?: 'eligible' | 'not_eligible' | 'correction'; reason: string;
  grant_id?: string; use?: 'approval' | 'execution';
};
export type EligibilityResult = {
  schema_version: 'eligibility-result.v1'; operation_id: string; subject_id: string;
  watch_id: string | null; actor_id: string; organization_id: string;
  expected_revision: number; revision: number;
  state: 'pending' | 'stale' | 'denied' | 'eligible' | 'not_eligible' | 'correction' | 'prepared' | 'consumed' | 'revoked';
  reason_code?: string; pending_reason: string | null; next_actor: string | null; next_review_at: string | null;
  grant?: {grant_id: string; grant_revision: number; expires_at: string};
};
