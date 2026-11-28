import type { PrivateReview } from './index';
/** Private read contracts. Every value is loaded under current authorization. */
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
export type PossessionState = 'issued' | 'pending' | 'approved' | 'correction' | 'rejected' | 'suspended';
export type ListingProof = {
  subject_id: string; watch_id: string; watch_revision: number; listing_revision: number;
  revision: number; state: PossessionState | null; challenge_id: string | null;
  expires_at: string | null; assignment_revision: number; reviewer_id: string | null;
  can_issue: boolean; can_submit: boolean; can_assign: boolean; can_decide: boolean;
  evidence_available: boolean;
};
export type ProofHistory = { revision: number; state: PossessionState; reason: string; recorded_at: string };
export type StaffMember = { subject_id: string; revision: number; state: 'active'|'suspended'|'revoked'; permissions: string[]; ordinary: boolean };
export type StaffWorkspace = Page<StaffMember> & {
  organization_id: string; actor_id: string; can_manage: boolean; ceiling_revision: number;
  ceiling: string[]; responsibilities_current: boolean;
  jobs: { job_id: string; responsible_id: string; revision: number }[];
  replacements: { subject_id: string; revision: number }[];
};
export type BusinessResult = {
  operation_id: string; operation_state: 'pending'|'committed'; state: 'issued'|'pending'|'approved'|'correction'|'rejected'|'suspended'|'active'|'revoked';
  revision: number; pending_reason?: string | null; next_actor?: string | null; next_review_at?: string | null;
};
export const workspaceOperations = {
  listing: '/v2/listing-possession/listings/',
  history: '/v2/listing-possession/history/',
  staff: '/v2/business-staff/workspaces/',
  command: '/v2/business-staff/commands',
  lookup: '/v2/business-operations/',
} as const;

export type PersonReviewHistory = PrivateReview & {
  history: { revision:number; state:PrivateReview['state']; reason:string; created_at:string }[];
  history_total:number;
  history_before_revision:number|null;
};
