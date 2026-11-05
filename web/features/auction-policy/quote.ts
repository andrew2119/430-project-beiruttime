import { ApiError } from '@/lib/api/client';
export type PrebidQuote={id:string;revision:number;subject_revision:number;buyer_fee_minor:number;shipping_minor:number;tax_minor:number;payable_minor:number;expires_at:string;request:Record<string,unknown>};
export function validPrebidQuote(raw:unknown,binding:{auctionId:string;listingId:string;buyerId:string;revision:number;currency:string;price:number}):PrebidQuote{
  const fail=():never=>{throw new ApiError(503,'quote_invalid','');};
  if(!raw||typeof raw!=='object'||Array.isArray(raw))return fail();
  const value=raw as Record<string,unknown>;
  const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0&&v<=18_000_000_000_000;
  if(typeof value.id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value.id)
    ||value.subject_id!==binding.auctionId||value.auction_id!==binding.auctionId||value.listing_id!==binding.listingId||value.owner_id!==binding.buyerId||value.subject_revision!==binding.revision
    ||typeof value.watch_id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value.watch_id)||!integer(value.listing_revision)||value.listing_revision<1
    ||value.currency!==binding.currency||value.price_minor!==binding.price||value.purpose!=='purchase'||value.kind!=='prebid'||value.source!=='auction'||value.source_verified!==true
    ||!integer(value.revision)||value.revision<1||!integer(value.buyer_fee_minor)||!integer(value.shipping_minor)||!integer(value.tax_minor)||!integer(value.payable_minor)
    ||value.payable_minor!==binding.price+value.buyer_fee_minor+value.shipping_minor+value.tax_minor
    ||value.sample!==true||value.schedule_id!=='sample-v1'||value.rounding!=='half_up'||value.minor_unit_exponent!==2
    ||typeof value.expires_at!=='string'||!/(Z|[+-]\d{2}:\d{2})$/.test(value.expires_at)||!Number.isFinite(Date.parse(value.expires_at)))return fail();
  return {id:value.id,revision:value.revision,subject_revision:binding.revision,buyer_fee_minor:value.buyer_fee_minor,shipping_minor:value.shipping_minor,tax_minor:value.tax_minor,payable_minor:value.payable_minor,expires_at:value.expires_at,
    request:{auction_id:binding.auctionId,expected_revision:binding.revision}};
}
