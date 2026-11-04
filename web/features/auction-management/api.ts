import { request, ApiError } from '@/lib/api/client';
import { authenticatedRequest } from '@/features/identity/session';
import type { QuoteInput } from '@contracts/contracts-pricing/quotes';
export const auctionBase = '/api/web/v1/auction/v1';
export type { AuctionSnapshot as Auction, AuctionOutcome as Outcome } from '@contracts/contracts-auction/core';
import type { AuctionSnapshot as Auction, AuctionOutcome as Outcome } from '@contracts/contracts-auction/core';
export const readAuction = (id:string, signal?:AbortSignal) => request<Auction>(`${auctionBase}/auctions/${encodeURIComponent(id)}`,{signal});
export const readLots = (listingId?:string, signal?:AbortSignal) => request<{items:Auction[]}>(`${auctionBase}/auctions${listingId?`?listing_id=${encodeURIComponent(listingId)}`:''}`,{signal});
// CP F-24: keep the exact logical command and key during uncertain reconciliation.
export async function command(path:string, body:unknown, key:string, signal?:AbortSignal, accessFingerprint?:string):Promise<Outcome> {
  try {
    return await authenticatedRequest<Outcome>(`${auctionBase}${path}`,{method:'POST',signal,accessFingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)});
  } catch(error) {
    if(error instanceof ApiError && error.status>=500 && !signal?.aborted) {
      const scopeQuery=path.includes('?')?path.slice(path.indexOf('?')):'';
      try { return await authenticatedRequest<Outcome>(`${auctionBase}/auction-operations/by-key/${encodeURIComponent(key)}${scopeQuery}`,{signal,accessFingerprint}); }
      catch { /* Unknown is not a refusal or success: caller retains the command for explicit retry. */ }
    }
    throw error;
  }
}
export type QuotePreview={id:string;buyer_fee_minor:number;shipping_minor:number;tax_minor:number;total_minor:number;expires_at:string;auction_revision:number;quote_revision:number;sample:true;request:QuoteInput};
export function quotePreview(value:unknown,amountMinor:number,revision:number,auctionId:string,ownerId:string,currency:'USD'|'LBP'):QuotePreview {
  const fail=()=>{throw new ApiError(503,'malformed_quote','');};
  if(!value||typeof value!=='object'||Array.isArray(value)||!Number.isSafeInteger(amountMinor)||amountMinor<=0||amountMinor>9000000000000) return fail();
  const raw=value as Record<string,unknown>;
  const safeMinor=(amount:unknown):amount is number=>typeof amount==='number'&&Number.isSafeInteger(amount)&&amount>=0&&amount<=18000000000000;
  if(typeof raw.id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(raw.id)
    ||raw.owner_id!==ownerId||raw.subject_id!==auctionId||raw.subject_revision!==revision
    ||raw.purpose!=='bid'||raw.price_minor!==amountMinor||raw.currency!==currency
    ||raw.schedule_id!=='sample-v1'||raw.sample!==true||raw.source!=='sample'||raw.source_verified!==false
    ||raw.minor_unit_exponent!==2||raw.rounding!=='half_up'
    ||typeof raw.revision!=='number'||!Number.isSafeInteger(raw.revision)||raw.revision<1
    ||!safeMinor(raw.buyer_fee_minor)||!safeMinor(raw.shipping_minor)||!safeMinor(raw.tax_minor)||!safeMinor(raw.payable_minor)
    ||raw.payable_minor!==amountMinor+raw.buyer_fee_minor+raw.shipping_minor+raw.tax_minor
    ||typeof raw.expires_at!=='string'||raw.expires_at.length>64||!/(Z|[+-]\d{2}:\d{2})$/.test(raw.expires_at)
    ||!Number.isFinite(Date.parse(raw.expires_at))) return fail();
  return {id:raw.id,buyer_fee_minor:raw.buyer_fee_minor,shipping_minor:raw.shipping_minor,tax_minor:raw.tax_minor,total_minor:raw.payable_minor,expires_at:raw.expires_at,auction_revision:revision,quote_revision:raw.revision,sample:true,
    request:{subject_id:auctionId,subject_revision:revision,purpose:'bid',currency,price_minor:amountMinor,schedule_id:'sample-v1',source:'sample'}};
}
export function minor(value:string):number {
  const normalized=value.replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-1632)).replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-1776)).replace('٫','.');
  if(!/^\d{1,14}(\.\d{1,2})?$/.test(normalized)) throw new Error('invalid');
  const [whole,fraction='']=normalized.split('.');
  const exact=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
  if(exact<1n||exact>9000000000000000n) throw new Error('invalid');
  return Number(exact);
}
export function incrementBands(step:string,extra:readonly {from:string;step:string}[]) {
  if(extra.length>19) throw new Error('invalid');
  const bands=[{from_minor:0,step_minor:minor(step)},...extra.map(band=>({from_minor:minor(band.from),step_minor:minor(band.step)}))];
  if(bands.some((band,index)=>index>0&&band.from_minor<=bands[index-1].from_minor)) throw new Error('invalid');
  return bands;
}
export function displayMinor(value:number,currency:string,locale:string) {
  if(!Number.isSafeInteger(value)||value<0||value>9000000000000000) throw new Error('invalid_minor_units');
  const language=locale==='ar'?'ar-LB':'en-US'; const exact=BigInt(value);
  const fraction=new Intl.NumberFormat(language,{useGrouping:false,minimumIntegerDigits:2,maximumFractionDigits:0}).format(exact%100n);
  // Format the integer and replace only its fraction: no binary floating-point cent rounding.
  return new Intl.NumberFormat(language,{style:'currency',currency,minimumFractionDigits:2,maximumFractionDigits:2})
    .formatToParts(exact/100n).map(part=>part.type==='fraction'?fraction:part.value).join('');
}
export function errorCopy(error:unknown,t:Record<string,string>) {
  if(error instanceof ApiError) return t[error.code]??(error.status===403?t.denied:error.status===401?t.signin:error.status>=500?t.unavailable:t.invalid);
  return t.invalid;
}
