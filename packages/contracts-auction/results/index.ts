export type ResultState = 'won'|'lost'|'no_sale';
export type ResultFinancialState = 'pending'|'unknown'|'paid_held'|'unpaid'|'unpaid_released'|'released';
export type BuyerResult = {
  is_demo:boolean;auction_id:string;watch_id:string;listing_id:string;buyer_id:string;revision:number;
  state:ResultState;currency:'USD';final_minor:number|null;ended_at:string;
  order_id:string|null;financial_state:ResultFinancialState|null;allocation_state?:'denied';completed_sale:boolean;
  next_action:'view_auction'|'review_order'|'contact_support';
};
export type ResultsPage = {schema_version:2;state:'available'|'unavailable';items:BuyerResult[];total:number|null;next_cursor:string|null};
