export type ExtensionPolicy = 'none.v1' | 'last-two-minutes.v1';
export type ConfigurePolicy = {extension_policy:ExtensionPolicy;buy_now_minor:number|null};
export type PolicySnapshot = ConfigurePolicy & {auction_id:string;revision:number;end_version:number;current_ends_at:string;server_time:string;frozen:boolean;reserve_set:boolean;reserve_met:boolean;mode:'bidding'|'listing_edit_pending'|'first_bid_pending'|'prebid_pending'|'prebid_reserved'|'closed_no_sale'|'closed_winner'};
export type PrebidCommand = {expected_revision:number;quote_id:string};
export type PrebidOutcome = {operation_id:string;auction_id:string;status:'pending'|'succeeded'|'denied';code:string;reservation_id?:string;order_id?:string;quote_id?:string;revision?:number};
