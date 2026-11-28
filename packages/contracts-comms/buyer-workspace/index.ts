export type WorkspaceSection<T> = { state: 'available'|'unavailable'; items: T[]; next_cursor: string|null };
export type BuyerBid = {
  auction_id: string; listing_id: string; status: 'leading'|'outbid'; current_price_minor: number;
  currency: 'USD'|'LBP'; revision: number; ends_at: string; is_demo?: boolean;
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

export type ActivityView = 'leading'|'outbid'|'calendar'|'won'|'lost'|'no_sale'|'unpaid'|'released';
export type CurrentBid = Omit<BuyerBid,'next_action'|'is_demo'|'currency'|'status'> & {status:BuyerBid['status']|null;is_demo:boolean;currency:'USD';lifecycle:'scheduled'|'live';starts_at:string;listing_title?:string|null};
export type CurrentResult = Omit<import('../../contracts-auction/results').BuyerResult,'buyer_id'>;
export type CurrentActivity = {schema_version:2;state:'available'|'unavailable';items:(CurrentBid|CurrentResult)[];total:number|null;next_cursor:string|null};
