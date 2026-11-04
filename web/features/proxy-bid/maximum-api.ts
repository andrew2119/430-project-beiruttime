import type {AuctionOutcome,AuctionSnapshot} from '@contracts/contracts-auction/core';
import type {Quote,QuoteInput} from '@contracts/contracts-pricing/quotes';
import {ApiError} from '@/lib/api/client';
import {authenticatedRequest} from './session';

// pricing.quotes.v1 bound; the Auction engine independently supports larger caps.
export const MAX_QUOTE_MINOR=9_000_000_000_000;
export type BuyerScope=Readonly<{subjectId:string;accessFingerprint:string}>;
export type MaximumQuote={
  fee_quote_id:string;amount_minor:number;currency:'USD'|'LBP';buyer_fee_minor:number;total_minor:number;
  expires_at:string;auction_revision:number;quote_revision:number;owner_id:string;access_fingerprint:string;sample:true;binding:QuoteInput;
};
export type MaximumIntent=Readonly<{key:string;amount_minor:number;fee_quote_id:string;revision:number;owner:string}>;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const minor=(value:number,max=MAX_QUOTE_MINOR)=>Number.isSafeInteger(value)&&value>=0&&value<=max;
const instant=(value:unknown)=>typeof value==='string'&&/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));

function validateQuote(snapshot:Quote,binding:QuoteInput,owner:BuyerScope,fresh:boolean):MaximumQuote {
  const policy=snapshot?.policy;
  if(!snapshot||!uuid.test(snapshot.id??'')||snapshot.owner_id!==owner.subjectId||snapshot.subject_id!==binding.subject_id||
    snapshot.subject_revision!==binding.subject_revision||snapshot.purpose!=='bid'||snapshot.currency!==binding.currency||
    snapshot.price_minor!==binding.price_minor||snapshot.schedule_id!=='sample-v1'||snapshot.source!=='sample'||
    snapshot.source_verified!==false||snapshot.sample!==true||snapshot.minor_unit_exponent!==2||
    !Number.isSafeInteger(snapshot.revision)||snapshot.revision<1||snapshot.rounding!=='half_up'||snapshot.fx!==null||
    snapshot.commission_basis!=='price_excluding_buyer_fee_shipping_tax'||
    !minor(snapshot.buyer_fee_minor)||!minor(snapshot.seller_commission_minor)||!minor(snapshot.seller_net_minor)||
    snapshot.shipping_minor!==0||snapshot.tax_minor!==0||!minor(snapshot.payable_minor,MAX_QUOTE_MINOR*2)||
    !instant(snapshot.created_at)||!instant(snapshot.expires_at)||Date.parse(snapshot.expires_at)<=Date.parse(snapshot.created_at)||
    (fresh&&Date.parse(snapshot.expires_at)<=Date.now())||typeof snapshot.reviewed_at==='undefined'||
    (snapshot.reviewed_at!==null&&!instant(snapshot.reviewed_at))||
    policy?.buyer_fee_bps!==300||policy.seller_commission_bps!==500||policy.shipping!=='sample_zero'||
    policy.tax!=='sample_zero'||policy.fx!=='not_applied'||policy.currency_exponents?.USD!==2||policy.currency_exponents?.LBP!==2) {
    throw new ApiError(503,'invalid_fee_preview','');
  }
  // Validate snapshot balance without inventing or recomputing commercial fees.
  if(BigInt(snapshot.price_minor)+BigInt(snapshot.buyer_fee_minor)!==BigInt(snapshot.payable_minor)||
    BigInt(snapshot.price_minor)-BigInt(snapshot.seller_commission_minor)!==BigInt(snapshot.seller_net_minor)) {
    throw new ApiError(503,'invalid_fee_preview','');
  }
  return {fee_quote_id:snapshot.id,amount_minor:binding.price_minor,currency:binding.currency,
    buyer_fee_minor:snapshot.buyer_fee_minor,total_minor:snapshot.payable_minor,expires_at:snapshot.expires_at,
    auction_revision:snapshot.subject_revision,quote_revision:snapshot.revision,owner_id:owner.subjectId,access_fingerprint:owner.accessFingerprint,sample:true,binding};
}

/** Bid-purpose private quote, never the purchase-only reservation validation API. */
export async function previewMaximum(auction:Pick<AuctionSnapshot,'id'|'revision'|'currency'>,amount:number,owner:BuyerScope,signal:AbortSignal):Promise<MaximumQuote> {
  signal.throwIfAborted();
  if(!owner.subjectId||!owner.accessFingerprint) throw new ApiError(401,'unauthorized','');
  if(!Number.isSafeInteger(amount)||amount<=0||amount>MAX_QUOTE_MINOR) throw new ApiError(422,'invalid_amount','');
  const binding:QuoteInput={subject_id:auction.id,subject_revision:auction.revision,purpose:'bid',currency:auction.currency,
    price_minor:amount,schedule_id:'sample-v1',source:'sample'};
  const snapshot=await authenticatedRequest<Quote>('/api/web/v1/pricing/v1/quotes',{
    signal,accessFingerprint:owner.accessFingerprint,method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(binding),
  });
  return validateQuote(snapshot,binding,owner,true);
}

/** Exact retained review acknowledgement; this is NOT payment/bid authority. */
export async function reviewMaximum(quote:MaximumQuote,key:string,signal:AbortSignal):Promise<void> {
  signal.throwIfAborted();
  const snapshot=await authenticatedRequest<Quote>(`/api/web/v1/pricing/v1/quotes/${encodeURIComponent(quote.fee_quote_id)}/review`,{
    signal,accessFingerprint:quote.access_fingerprint,method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},
    body:JSON.stringify({...quote.binding,quote_revision:quote.quote_revision,payable_minor:quote.total_minor}),
  });
  // An exact review replay may return the original acknowledgement after expiry;
  // Auction still owns current expiry checks and idempotent bid reconciliation.
  const reviewed=validateQuote(snapshot,quote.binding,{subjectId:quote.owner_id,accessFingerprint:quote.access_fingerprint},false);
  if(reviewed.fee_quote_id!==quote.fee_quote_id||reviewed.quote_revision!==quote.quote_revision||
    reviewed.total_minor!==quote.total_minor||reviewed.buyer_fee_minor!==quote.buyer_fee_minor||reviewed.expires_at!==quote.expires_at||
    !instant(snapshot.reviewed_at)||Date.parse(snapshot.reviewed_at!)<Date.parse(snapshot.created_at)||
    Date.parse(snapshot.reviewed_at!)>=Date.parse(snapshot.expires_at)) throw new ApiError(503,'invalid_fee_review','');
}

/** Preserve the immutable body/key and abort signal across uncertain retries. */
export function sendMaximum(auctionId:string,intent:MaximumIntent,signal:AbortSignal):Promise<AuctionOutcome> {
  signal.throwIfAborted();
  return authenticatedRequest<AuctionOutcome>(`/api/web/v1/auction/v1/auctions/${encodeURIComponent(auctionId)}/maximum`,{
    signal,accessFingerprint:intent.owner,method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':intent.key},
    body:JSON.stringify({amount_minor:intent.amount_minor,fee_quote_id:intent.fee_quote_id,expected_revision:intent.revision}),
  });
}
