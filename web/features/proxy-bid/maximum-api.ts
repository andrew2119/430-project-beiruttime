import type {AuctionOutcome,AuctionSnapshot} from '@contracts/contracts-auction/core';
import {ApiError} from '@/lib/api/client';
import {authenticatedRequest} from './session';
export type MaximumQuote={fee_quote_id:string;amount_minor:number;currency:'USD'|'LBP';buyer_fee_minor:number;total_minor:number;expires_at:string;auction_revision:number};
type FeePreview={id:string;buyer_fee_minor:number;total_minor:number;expires_at:string;auction_revision:number};
/** Published Auction bid-preview request contract. The actual Pricing service
 * computes fees; no local policy, synthetic fee or fallback success is supplied.
 */
export async function previewMaximum(auction:AuctionSnapshot,amount:number,signal:AbortSignal):Promise<MaximumQuote> {
  signal.throwIfAborted();
  if(!Number.isSafeInteger(amount)||amount<=0||amount>9_000_000_000_000_000) throw new ApiError(422,'invalid_amount','');
  const preview=await authenticatedRequest<FeePreview>('/api/web/v1/pricing/v1/quotes',{
    signal,method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},
    body:JSON.stringify({auction_id:auction.id,listing_id:auction.listing_id,amount_minor:amount,currency:auction.currency,rules_version:auction.rules_version,auction_revision:auction.revision}),
  });
  if(!preview||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(preview.id??'')||
    preview.auction_revision!==auction.revision||!Number.isSafeInteger(preview.buyer_fee_minor)||preview.buyer_fee_minor<0||
    !Number.isSafeInteger(preview.total_minor)||preview.total_minor<amount||preview.buyer_fee_minor>preview.total_minor||
    typeof preview.expires_at!=='string'||!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(preview.expires_at)||
    !(Date.parse(preview.expires_at)>Date.now())) throw new ApiError(503,'invalid_fee_preview','');
  return {fee_quote_id:preview.id,amount_minor:amount,currency:auction.currency,buyer_fee_minor:preview.buyer_fee_minor,
    total_minor:preview.total_minor,expires_at:preview.expires_at,auction_revision:preview.auction_revision};
}
export type MaximumIntent=Readonly<{key:string;amount_minor:number;fee_quote_id:string;revision:number;owner:string}>;
/** Retain one immutable command body/key for uncertain retries. Identity owns
 * refresh; the caller's abort signal fences its retry across account changes.
 */
export function sendMaximum(auctionId:string,intent:MaximumIntent,signal:AbortSignal):Promise<AuctionOutcome> {
  signal.throwIfAborted();
  return authenticatedRequest<AuctionOutcome>(`/api/web/v1/auction/v1/auctions/${encodeURIComponent(auctionId)}/maximum`,{
    signal,method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':intent.key},
    body:JSON.stringify({amount_minor:intent.amount_minor,fee_quote_id:intent.fee_quote_id,expected_revision:intent.revision}),
  });
}
