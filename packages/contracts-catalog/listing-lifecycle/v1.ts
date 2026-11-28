export type Action = 'pause' | 'renew' | 'relist';
export interface Command {
  schema_version: 'listing-lifecycle.v1'; operation_id: string; subject_id: string;
  watch_id: string; actor_id: string; organization_id: string | null;
  expected_revision: number; kind: Action; proof_id: string | null;
  quote_id: string | null; quote_revision: number | null; policy_revision: string | null;
}
export interface Receipt extends Command {
  state: 'pending' | 'denied' | 'succeeded'; revision: number;
  pending_reason: string | null; next_actor: string | null; next_review_at: string | null;
  responsible_operator_id: string | null; next_action: 'resolve_confirmation' | null; escalate_at: string | null;
  listing_id: string | null; auction_id: string | null; previous_auction_id: string | null;
}
