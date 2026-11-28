export type Currency = 'USD' | 'LBP';
export type QuoteInput = {subject_id:string; subject_revision:number; purpose:'bid'|'offer'|'purchase'|'business_quote'; currency:Currency; price_minor:number; schedule_id:'sample-v1'|'usd-v2'; source?:'sample'|'listing'};
export type Quote = QuoteInput & {id:string; owner_id:string; source_verified:boolean; revision:number; minor_unit_exponent:2; buyer_fee_minor:number; seller_commission_minor:number; seller_net_minor:number; shipping_minor:number; tax_minor:number; payable_minor:number; sample:boolean; created_at:string; expires_at:string; reviewed_at:string|null; rounding:'half_up'; fx:null;commission_basis:'price_excluding_buyer_fee_shipping_tax';policy:{revision?:1|2;buyer_fee_bps:300;seller_commission_bps:500;shipping:'sample_zero';tax:'sample_zero';fx:'not_applied';currency_exponents:{USD:2;LBP:2}}};
export type ValidatedReservationQuote = {quote_id:string;buyer_id:string;listing_id:string;listing_revision:number;currency:Currency;total_minor:number;expires_at:string;status:'valid'};
export type OfferDraft = {id:string; subject_id:string; subject_revision:number; currency:Currency; amount_minor:number; revision:number; updated_at:string; status:'draft'};

export type QuotePage = {items:Quote[];total:number;page:number;page_size:number};
