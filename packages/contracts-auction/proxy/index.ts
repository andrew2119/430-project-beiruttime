export type MaximumCommandV1={amount_minor:number;fee_quote_id:string;expected_revision:number};
export type PrivateMaximumV1={bidder_id:string;amount_minor:number;sequence:number};
/** Internal Auction transaction only. Never expose this aggregate to a browser. */
export type ProxyStateV1={current_minor:number;opening_minor:number;leader_id:string|null;sequence:number;increment_bands:{from_minor:number;step_minor:number}[];maxima:PrivateMaximumV1[]};
export type ProxyCommandV1={kind:'manual'|'maximum';bidder_id:string;amount_minor:number;sequence:number};
export type ProxyResultV1={leader_id:string;current_minor:number;maxima:PrivateMaximumV1[];bids:{bidder_id:string;amount_minor:number;automatic:boolean}[]};

export type PrivateMaximumV2 = PrivateMaximumV1 & {active:boolean};
/** Private transaction state; never serialize to public history or diagnostics. */
export type ProxyStateV2 = Omit<ProxyStateV1,'maxima'> & {maxima:PrivateMaximumV2[]};
export type ProxyCommandV2 = ProxyCommandV1;
export type ProxyResultV2 = Omit<ProxyResultV1,'maxima'> & {maxima:PrivateMaximumV2[]};
export type HistoricalAuctionAccess = {schema_version:1;auction_id:string;actor_id:string;revision:number};
export type OwnMaximumV2 = {schema_version:2;auction_id:string;watch_id:string;actor_id:string;revision:number;amount_minor:number|null;active:boolean;standing:'leading'|'outbid'|null};
export type MaximumOperationV2 = {
  schema_version:2;operation_id:string;actor_id:string;organization_id:null;
  subject_id:string;watch_id:string;expected_revision:number;revision:number;
  quote_id:string;quote_revision:number;policy_revision:string;
  state:'accepted'|'denied'|'stale'|'pending';pending_reason:string|null;
  next_actor:string|null;next_review_at:string|null;
};

export type MaximumCommandV2 = {amount_minor:number;fee_quote_id:string;expected_revision:number;watch_id:string;quote_revision:number;policy_revision:string};

export type EarlierBidPage = {
  auction_id: string;
  items: {operation_id:string;recorded_at:string;state:'accepted'|'denied'|'stale'}[];
  next_cursor: string | null;
};
