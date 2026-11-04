export type WorkspaceSection<T> = { state: 'available'|'unavailable'; items: T[]; next_cursor: string|null };
export type BuyerBid = {
  auction_id: string; listing_id: string; status: 'leading'|'outbid'; current_price_minor: number;
  currency: 'USD'|'LBP'; revision: number; ends_at: string; is_demo: boolean;
  next_action: {kind:'view_auction'; href:string};
};
export type BuyerReservation = {
  reservation_id: string; listing_id:string; state:'awaiting_payment'; total_minor:number;
  currency:'USD'|'LBP'; revision:number; expires_at:string; is_demo:boolean;
  next_action:{kind:'review_reservation';href:string}; payment_available:false; delivery_available:false;
};
export type BuyerWorkspace = {
  version:1; as_of:string; bids:WorkspaceSection<BuyerBid>; reservations:WorkspaceSection<BuyerReservation>;
  final_results_available:false;
};
