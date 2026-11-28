export type CurrentPrincipal = {
  actor: { subject_id: string; session_id: string; organization_id: string | null };
  roles: string[]; permissions: string[]; organizations: string[];
  organization_grants: { organization_id: string; roles: string[]; permissions: string[] }[];
};
export type Session = {
  access_token: string; token_type: 'Bearer'; expires_in: number;
  account: { id: string; email: string; display_name: string };
  principal: CurrentPrincipal; access_fingerprint: string;
};
export type PrivateApplication = {
  id: string; subject_id: string; revision: number;
  status: 'pending' | 'correction' | 'approved' | 'rejected' | 'suspended';
  identity_name: string; contact: string; payout_reference: string; reason: string;
  created_at: string; updated_at: string;
};
export type ListingPossession = {
  schema_version: 'identity.listing-possession.v1'; operation_id: string;
  subject_id: string; watch_id: string; actor_id: string; organization_id: null;
  expected_revision: number; revision: number; state: 'issued'|'pending'|'expired'|'stale'|'approved'|'correction'|'rejected'|'suspended';
  review?: {challenge_id:string;proof_revision:number;watch_revision:number;listing_revision:number;verdict:'approved'|'correction'|'rejected'|'suspended';reviewer_id:string;assignment_revision:number;review_revision:number;reason:string};
  pending_reason: string|null; next_actor: 'seller'|'assigned_reviewer'; next_review_at: string|null;
  listing_id: string; listing_revision: number; watch_revision: number;
  challenge_id: string; code: string; issued_at: string; expires_at: string; submitted_at: string|null;
};
