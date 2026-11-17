export type Binding = {
  subject_id: string; watch_id: string; organization_id: string; request_id: string;
  request_revision: number; consent_revision: number; quote_id: string; quote_revision: number;
  policy_revision: 'identity-v1'; source_revision: number; commitment_id: string;
  purpose: 'brand-request-identity';
};
export type ReviewState = 'assigned'|'under_review'|'correction'|'eligible'|'not_eligible'|'invalidated';
export type Review = {
  schema_version: 'eligibility.private-review.v1'; case_id: string; reviewer_id: string;
  revision: number; assignment_revision: number; state: ReviewState; binding: Binding;
  execution_authorized: false; operation_id: string|null; actor_id: string; subject_id: string;
  watch_id: string; organization_id: string; expected_revision: number; pending_reason: string|null;
  next_actor: string; next_review_at: string|null;
};
export type Command = {
  schema_version: 'eligibility.private-review.v1'; operation_id: string; case_id: string;
  expected_revision: number; assignment_revision: number; binding: Binding;
  kind: 'claim'|'reassign'|'correct'|'decide'; reviewer_id?: string;
  verdict?: 'eligible'|'not_eligible'; reason: string;
};
export type Decision = {
  operation_id: string; actor_id: string; reviewer_id: string; assignment_revision: number;
  review_revision: number; binding: Binding; verdict: 'eligible'|'not_eligible'|'correction';
  reason?: string; reviewed_at: string;
};
export type History = { items: Decision[]; total: number; page: number; page_size: 25 };
export type Evidence = { synthetic: true; identity_match: 'match'|'mismatch'|'unclear'; document_valid: boolean };
