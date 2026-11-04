export type AuctionTimingV1={
  auction_id:string;listing_id:string;starts_at:string;scheduled_ends_at:string;current_ends_at:string;
  server_time:string;status:'scheduled'|'live'|'ended';revision:number;rules_version:string;extension_policy:string;
};
export type AuctionTimingPageV1={version:1;items:AuctionTimingV1[];server_time:string;missing_listing_ids:string[];next_cursor:string|null};
