export type SensitiveAction = 'seller_payout' | 'business_payout' | 'privileged_review' | 'factor_change';
export type TwoFactorResult = {
  schema_version: 1; watch_id: null; operation_id: string; subject_id: string; actor_id: string;
  organization_id: string | null; expected_revision: number; revision: number;
  state: 'enrolling' | 'enabled' | 'proved' | 'consumed' | 'pending' | 'sign_in_required';
  pending_reason: 'session_revocation' | null; next_actor: string | null; next_review_at: string | null;
  proof_id?: string; expires_at?: string;
  secret?: string; recovery_codes?: string[];
};
