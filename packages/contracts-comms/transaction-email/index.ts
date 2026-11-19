export type EmailState = 'captured' | 'recorded' | 'failed' | 'possibly_sent';
export type EmailKind = 'confirmation' | 'quote' | 'ready' | 'refund' | 'receipt-link';
export interface EmailRecord {
  schema_version: 'transaction-email.v1'; operation_id: string; subject_id: string;
  watch_id: string; actor_id: string; organization_id: string | null;
  expected_revision: number; revision: number; state: EmailState;
  attempt_id: string | null; locale: 'en' | 'ar'; kind: EmailKind; synthetic: true;
  pending_reason: string | null; next_actor: string;
  next_review_at: string | null; available_at: string; authenticated_link: string;
}
export interface EmailPage { items: EmailRecord[]; total: number; offset: number; limit: number }
