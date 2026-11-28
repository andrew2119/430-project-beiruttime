/** Auction kernel v2. All mutations retain one canonical transaction/lock. */
export type AuctionMode='bidding'|'first_bid_pending'|'listing_edit_pending'|'prebid_pending'|'prebid_reserved'|'closed_no_sale'|'closed_winner';
export type AuctionKernelVersion={revision:number;end_version:number;close_version:number;mode:AuctionMode;first_bid_committed:boolean;ends_at:string};
export type AuctionQuoteContext={auction_id:string;listing_id:string;listing_revision:number;watch_id:string;buyer_id:string;seller_id:string;seller_organization_id:string|null;revision:number;end_version:number;close_version:number;mode:AuctionMode;currency:'USD'|'LBP';price_minor:number;ends_at:string};
