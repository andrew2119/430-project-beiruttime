/** Service-private canonical transaction contract. */
export type KernelModeV4 = 'bidding' | 'first_bid_pending' | 'listing_edit_pending' |
  'prebid_pending' | 'prebid_reserved' | 'cancellation_pending' | 'cancelled' |
  'ended_legacy_review' | 'closed_no_sale' | 'closed_winner';
export type KernelCommandV4 = {
  schema_version: 'auction-kernel.v4'; operation_id: string; auction_id: string;
  watch_id: string; actor_id: string; organization_id: string | null;
  expected_revision: number; policy_revision: number;
  action: 'cancel' | 'confirm_cancellation' | 'close' | 'resolve_legacy_no_sale';
};
export type KernelReceiptV4 = Omit<KernelCommandV4, 'action'> & {
  state: 'succeeded' | 'denied' | 'pending'; code: string;
  mode: KernelModeV4; revision: number; server_time: string;
  pending_reason: string | null; next_actor: string | null; next_review_at: string | null;
};
export type KernelCurrentStateV4 = {
  schema_version: 'auction-kernel.v4'; mode: KernelModeV4; revision: number;
  end_version: number; close_version: number;
  status: 'scheduled' | 'live' | 'ended' | 'cancelled'; current_minor: number;
  scheduled_ends_at: string; server_time: string;
  pending_reason: string | null; next_actor: string | null; next_review_at: string | null;
};
