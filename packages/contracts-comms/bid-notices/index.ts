export type BidNotice = {
  id:string;kind:'bid_accepted'|'outbid';auction_id:string;listing_id:string;sequence:number;
  current_minor:number;currency:'USD'|'LBP';ends_at:string;created_at:string;
  href:string;inbox_delivery:'pending'|'delivered';
};
export type BidNoticeList = {items:BidNotice[];has_more:boolean;next_cursor:string|null};
export type OpenedBidNotice = {
  notice:BidNotice;
  current:null|{id:string;current_minor:number;next_minimum_minor:number;currency:'USD'|'LBP';
    ends_at:string;server_time:string;revision:number;accepted_sequence:number;status:'live'|'scheduled'|'ended'};
  current_status:'available'|'unavailable';requires_new_fee_preview:true;
};
