export type { AuctionTimingV1, AuctionTimingPageV1 } from './timing';
export type Currency = 'USD' | 'LBP';
export type IncrementBand = { from_minor:number;step_minor:number };
export type AuctionSnapshot = {
  id:string;listing_id:string;currency:Currency;opening_minor:number;current_minor:number;
  next_minimum_minor:number;increment_bands:IncrementBand[];starts_at:string;ends_at:string;
  server_time:string;revision:number;accepted_sequence:number;rules_version:string;
  extension_policy:string;high_value_minor:number;reserve_set:boolean;leader:string|null;
  status:'live'|'scheduled'|'ended';
};
// Owner-private seller read only; never use this in discovery/history/notices.
export type SellerAuctionSnapshot = AuctionSnapshot & {reserve_minor:number|null};
export type BidCommand = { amount_minor:number;fee_quote_id:string;expected_revision:number };
export type AuctionOutcome = {
  operation_id:string;status:'succeeded'|'denied';code:string;auction_id:string;
  revision?:number;accepted_sequence?:number;current_minor?:number;next_minimum_minor?:number;
  server_time?:string;auction?:AuctionSnapshot;
};
export type {AuctionMyBidV1 as MyBidSummary,AuctionMyBidsV1 as MyBidPage} from './my-bids';
export type PublicBid = { sequence:number;bidder:string;amount_minor:number;automatic:boolean;received_at:string };
export type BidHistory = {items:PublicBid[];has_more:boolean;next_sequence:number;snapshot:AuctionSnapshot};
// Service-private event only. Never use this shape as a public history DTO.
export type BidAcceptedEventData = {
  auction_id:string;listing_id:string;sequence:number;revision:number;current_minor:number;
  currency:Currency;ends_at:string;bidder_id:string;previous_leader_id:string|null;leader_id:string;
};
export type { KernelModeV4, KernelCommandV4, KernelReceiptV4, KernelCurrentStateV4 } from './kernel-v4';
