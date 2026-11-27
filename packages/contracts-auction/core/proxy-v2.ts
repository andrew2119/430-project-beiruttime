/** Private transaction-only state. Never serialize maxima in public projections. */
export type PrivateMaximumV2 = {bidder_id:string;amount_minor:number;sequence:number;active:boolean};
export type PrivateBidStateV2 = {opening_minor:number;current_minor:number;leader_id:string|null;sequence:number;increment_bands:{from_minor:number;step_minor:number}[];maxima:PrivateMaximumV2[]};
export type BidCommandV2 = {kind:'manual'|'maximum';bidder_id:string;amount_minor:number;sequence:number};
export type BidResultV2 = {leader_id:string;current_minor:number;maxima:PrivateMaximumV2[];bids:{bidder_id:string;amount_minor:number;automatic:boolean}[]};
export type ImmediatelyOutbidV2 = {auction_id:string;listing_id:string;sequence:number;revision:number;bidder_id:string;current_minor:number;currency:'USD'};
