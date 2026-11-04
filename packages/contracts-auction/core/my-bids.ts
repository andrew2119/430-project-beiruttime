/** Owner-private response from GET /v1/my-bids. No private maximum or final sale outcome. */
export type AuctionMyBidV1={
  id:string;
  auction_id:string;
  listing_id:string;
  buyer_id:string;
  currency:'USD'|'LBP';
  opening_minor:number;
  current_minor:number;
  current_price_minor:number;
  next_minimum_minor:number;
  increment_bands:{from_minor:number;step_minor:number}[];
  starts_at:string;
  ends_at:string;
  server_time:string;
  revision:number;
  accepted_sequence:number;
  rules_version:string;
  extension_policy:string;
  high_value_minor:number;
  reserve_set:boolean;
  leader:string|null;
  status:'live'|'scheduled'|'ended';
  my_status:'leading'|'outbid';
  next_action:'auction_ended'|'review_bid';
};
export type AuctionMyBidsV1={items:AuctionMyBidV1[];next_cursor:string|null};
