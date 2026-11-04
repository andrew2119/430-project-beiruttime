export type MaximumCommandV1={amount_minor:number;fee_quote_id:string;expected_revision:number};
export type PrivateMaximumV1={bidder_id:string;amount_minor:number;sequence:number};
/** Internal Auction transaction only. Never expose this aggregate to a browser. */
export type ProxyStateV1={current_minor:number;opening_minor:number;leader_id:string|null;sequence:number;increment_bands:{from_minor:number;step_minor:number}[];maxima:PrivateMaximumV1[]};
export type ProxyCommandV1={kind:'manual'|'maximum';bidder_id:string;amount_minor:number;sequence:number};
export type ProxyResultV1={leader_id:string;current_minor:number;maxima:PrivateMaximumV1[];bids:{bidder_id:string;amount_minor:number;automatic:boolean}[]};
