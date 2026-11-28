import operationSchema from '../../../packages/contracts-auction/proxy/operation.v2.schema.json';
import type {AuctionOutcome,AuctionSnapshot} from '@contracts/contracts-auction/core';
import type {EarlierBidPage,HistoricalAuctionAccess,MaximumCommandV2,MaximumOperationV2,OwnMaximumV2} from '@contracts/contracts-auction/proxy';
import type {Quote,QuoteInput} from '@contracts/contracts-pricing/quotes';
import {ApiError} from '@/lib/api/client';
import {authenticatedRequest} from './session';
import type {ConfirmMissingQuote} from './quote-availability';

// pricing.quotes.v1 bound; the Auction engine independently supports larger caps.
export const MAX_QUOTE_MINOR=9_000_000_000_000;
export type BuyerScope=Readonly<{subjectId:string;accessFingerprint:string}>;
type BidQuoteInput=QuoteInput & {currency:'USD'};
const BID_SCHEDULE='usd-v2';
const BID_POLICY_REVISION=2;
export type MaximumQuote={
  fee_quote_id:string;amount_minor:number;currency:'USD';buyer_fee_minor:number;total_minor:number;
  expires_at:string;auction_revision:number;quote_revision:number;policy_revision:string;owner_id:string;access_fingerprint:string;sample:true;binding:BidQuoteInput;
};
export type MaximumIntent=Readonly<{key:string;amount_minor:number;fee_quote_id:string;revision:number;owner:string;actor_id:string;watch_id:string|null;quote_revision:number;policy_revision:string}>;
export type MaximumReference=Omit<MaximumIntent,'amount_minor'>;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const minor=(value:number,max=MAX_QUOTE_MINOR)=>Number.isSafeInteger(value)&&value>=0&&value<=max;
const PREVIEW_LIFETIME_MS=15*60*1000;
const instant=(value:unknown)=>typeof value==='string'&&/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));

// Compare server instants without discarding precision below the millisecond.
const submillisecond=(value:string)=>value.match(/\.\d{3}(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1].replace(/0+$/,'')??'';

function before(left:string,right:string) {
  const milliseconds=Date.parse(left)-Date.parse(right);
  return milliseconds===0?submillisecond(left)<submillisecond(right):milliseconds<0;
}

function hasPreviewLifetime(created:string,expires:string) {
  return Date.parse(expires)-Date.parse(created)===PREVIEW_LIFETIME_MS&&
    submillisecond(created)===submillisecond(expires);
}

function validateQuote(snapshot:Quote,binding:BidQuoteInput,owner:BuyerScope):MaximumQuote {
  const policy=snapshot?.policy;
  if(!snapshot||!uuid.test(snapshot.id??'')||snapshot.owner_id!==owner.subjectId||snapshot.subject_id!==binding.subject_id||
    snapshot.subject_revision!==binding.subject_revision||snapshot.purpose!=='bid'||snapshot.currency!==binding.currency||
    snapshot.price_minor!==binding.price_minor||snapshot.schedule_id!==BID_SCHEDULE||snapshot.source!=='sample'||
    snapshot.source_verified!==false||snapshot.sample!==true||snapshot.minor_unit_exponent!==2||
    !Number.isSafeInteger(snapshot.revision)||snapshot.revision<1||snapshot.rounding!=='half_up'||snapshot.fx!==null||
    snapshot.commission_basis!=='price_excluding_buyer_fee_shipping_tax'||
    !minor(snapshot.buyer_fee_minor)||!minor(snapshot.seller_commission_minor)||!minor(snapshot.seller_net_minor)||
    snapshot.shipping_minor!==0||snapshot.tax_minor!==0||!minor(snapshot.payable_minor,MAX_QUOTE_MINOR*2)||
    !instant(snapshot.created_at)||!instant(snapshot.expires_at)||!hasPreviewLifetime(snapshot.created_at,snapshot.expires_at)||
    typeof snapshot.reviewed_at==='undefined'||
    (snapshot.reviewed_at!==null&&!instant(snapshot.reviewed_at))||
    policy?.revision!==BID_POLICY_REVISION||policy.buyer_fee_bps!==300||policy.seller_commission_bps!==500||policy.shipping!=='sample_zero'||
    policy.tax!=='sample_zero'||policy.fx!=='not_applied'||policy.currency_exponents?.USD!==2) {
    throw new ApiError(503,'invalid_fee_preview','');
  }
  const price=BigInt(binding.price_minor);
  const buyerFee=(price*BigInt(policy.buyer_fee_bps)+5000n)/10000n;
  const sellerCommission=(price*BigInt(policy.seller_commission_bps)+5000n)/10000n;
  if(BigInt(snapshot.buyer_fee_minor)!==buyerFee||BigInt(snapshot.payable_minor)!==price+buyerFee||
    BigInt(snapshot.seller_commission_minor)!==sellerCommission||BigInt(snapshot.seller_net_minor)!==price-sellerCommission) {
    throw new ApiError(503,'invalid_fee_preview','');
  }
  return {fee_quote_id:snapshot.id,amount_minor:binding.price_minor,currency:binding.currency,
    buyer_fee_minor:snapshot.buyer_fee_minor,total_minor:snapshot.payable_minor,expires_at:snapshot.expires_at,
    auction_revision:snapshot.subject_revision,quote_revision:snapshot.revision,policy_revision:String(policy.revision),
    owner_id:owner.subjectId,access_fingerprint:owner.accessFingerprint,sample:true,binding};
}

/** Bid-purpose private quote, never the purchase-only reservation validation API. */
export async function previewMaximum(auction:Pick<AuctionSnapshot,'id'|'revision'|'currency'>,amount:number,owner:BuyerScope,signal:AbortSignal,key:string):Promise<MaximumQuote> {
  signal.throwIfAborted();
  if(!owner.subjectId||!owner.accessFingerprint) throw new ApiError(401,'unauthorized','');
  if(!Number.isSafeInteger(amount)||amount<=0||amount>MAX_QUOTE_MINOR) throw new ApiError(422,'invalid_amount','');
  if(auction.currency!=='USD') throw new ApiError(422,'invalid_currency','');
  const binding:BidQuoteInput={subject_id:auction.id,subject_revision:auction.revision,purpose:'bid',currency:auction.currency,
    price_minor:amount,schedule_id:BID_SCHEDULE,source:'sample'};
  const snapshot=await authenticatedRequest<Quote>('/api/web/v1/pricing/v1/quotes',{
    signal,accessFingerprint:owner.accessFingerprint,method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(binding),
  });
  return validateQuote(snapshot,binding,owner);
}

/** Exact retained review acknowledgement; this is NOT payment/bid authority. */
export async function reviewMaximum(quote:MaximumQuote,key:string,signal:AbortSignal,confirmMissing?:ConfirmMissingQuote):Promise<void> {
  signal.throwIfAborted();
  let snapshot:Quote;
  try {
    snapshot=await authenticatedRequest<Quote>(`/api/web/v1/pricing/v1/quotes/${encodeURIComponent(quote.fee_quote_id)}/review`,{
      signal,accessFingerprint:quote.access_fingerprint,method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},
      body:JSON.stringify({...quote.binding,quote_revision:quote.quote_revision,payable_minor:quote.total_minor}),
    });
  } catch(error) {
    if(error instanceof ApiError&&error.status===404&&error.code==='not_found'&&
      await confirmMissing?.(quote.fee_quote_id,quote.access_fingerprint,signal)) {
      throw new ApiError(404,'quote_not_found',error.requestId);
    }
    throw error;
  }
  // An exact review replay may return the original acknowledgement after expiry;
  // Auction still owns current expiry checks and idempotent bid reconciliation.
  const reviewed=validateQuote(snapshot,quote.binding,{subjectId:quote.owner_id,accessFingerprint:quote.access_fingerprint});
  if(reviewed.fee_quote_id!==quote.fee_quote_id||reviewed.quote_revision!==quote.quote_revision||reviewed.policy_revision!==quote.policy_revision||
    reviewed.total_minor!==quote.total_minor||reviewed.buyer_fee_minor!==quote.buyer_fee_minor||reviewed.expires_at!==quote.expires_at||
    snapshot.reviewed_at===null||!instant(snapshot.reviewed_at)||before(snapshot.reviewed_at,snapshot.created_at)||
    !before(snapshot.reviewed_at,snapshot.expires_at)) throw new ApiError(503,'invalid_fee_review','');
}

/** Preserve the immutable body/key and abort signal across uncertain retries. */
function maximumRequest<T>(auctionId:string,accessFingerprint:string,signal:AbortSignal,body:object,key?:string) {
  return authenticatedRequest<T>(`/api/web/v1/auction/v1/auctions/${encodeURIComponent(auctionId)}/maximum`,{
    signal,accessFingerprint,cache:'no-store',method:'POST',
    headers:{'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},
    body:JSON.stringify(body),
  });
}

export function sendMaximum(auctionId:string,intent:MaximumIntent,signal:AbortSignal):Promise<MaximumOperationV2> {
  signal.throwIfAborted();
  return maximumRequest<MaximumOperationV2>(auctionId,intent.owner,signal,{action:'submit_v2',command:{
    amount_minor:intent.amount_minor,fee_quote_id:intent.fee_quote_id,expected_revision:intent.revision,
    watch_id:intent.watch_id,quote_revision:intent.quote_revision,policy_revision:intent.policy_revision,
  }},intent.key).then(result=>validateReceipt(result,auctionId,intent));
}

/** Reconstruct the original review body from the buyer's retained quote. */
async function readBoundQuote(auctionId:string,reference:MaximumReference,signal:AbortSignal,requireReview:boolean) {
  const snapshot=await authenticatedRequest<Quote>(`/api/web/v1/pricing/v1/quotes/${encodeURIComponent(reference.fee_quote_id)}`,{
    signal,accessFingerprint:reference.owner,cache:'no-store',
  });
  const amount=snapshot?.price_minor;
  if(!minor(amount)||amount===0) throw new ApiError(503,'invalid_fee_review','');
  const quote=validateQuote(snapshot,{subject_id:auctionId,subject_revision:reference.revision,purpose:'bid',
    currency:'USD',price_minor:amount,schedule_id:BID_SCHEDULE,source:'sample'},
  {subjectId:reference.actor_id,accessFingerprint:reference.owner});
  if(quote.fee_quote_id!==reference.fee_quote_id||quote.quote_revision!==reference.quote_revision||quote.policy_revision!==reference.policy_revision||
    (requireReview&&(!snapshot.reviewed_at||before(snapshot.reviewed_at,snapshot.created_at)||!before(snapshot.reviewed_at,snapshot.expires_at)))) {
    throw new ApiError(503,'invalid_fee_review','');
  }
  return quote;
}

export async function restoreMaximumReview(auctionId:string,reference:MaximumReference,signal:AbortSignal,confirmMissing?:ConfirmMissingQuote) {
  try {
    return await readBoundQuote(auctionId,reference,signal,false);
  } catch(error) {
    if(error instanceof ApiError&&error.status===404&&error.code==='not_found'&&
      await confirmMissing?.(reference.fee_quote_id,reference.owner,signal)) {
      throw new ApiError(404,'quote_not_found',error.requestId);
    }
    throw error;
  }
}

export async function restoreMaximumIntent(auctionId:string,reference:MaximumReference,signal:AbortSignal):Promise<MaximumIntent> {
  const quote=await readBoundQuote(auctionId,reference,signal,true);
  return {...reference,amount_minor:quote.amount_minor};
}

export type OwnMaximum=OwnMaximumV2;

export type EarlierMaximumCommand=Pick<MaximumCommandV2,'amount_minor'|'fee_quote_id'|'expected_revision'>;

export function earlierMaximumCommand(intent:MaximumIntent):EarlierMaximumCommand {
  return {amount_minor:intent.amount_minor,fee_quote_id:intent.fee_quote_id,expected_revision:intent.revision};
}

export function recoverLegacyMaximum(auctionId:string,intent:MaximumIntent,signal:AbortSignal) {
  return replayEarlierMaximum(auctionId,intent.key,earlierMaximumCommand(intent),intent.owner,signal);
}

export async function replayEarlierMaximum(auctionId:string,key:string,command:EarlierMaximumCommand,access:string,signal:AbortSignal) {
  const result=await maximumRequest<AuctionOutcome>(auctionId,access,signal,{action:'recover_v1',command},key);
  return legacyOutcome(result,auctionId,command.expected_revision);
}
export async function readOwnMaximum(auctionId:string,owner:BuyerScope,signal:AbortSignal):Promise<OwnMaximum|HistoricalAuctionAccess> {
  const result=await maximumRequest<OwnMaximum|HistoricalAuctionAccess>(auctionId,owner.accessFingerprint,signal,{action:'read_v2'});
  if(result?.schema_version===1&&result.auction_id===auctionId&&result.actor_id===owner.subjectId&&Number.isSafeInteger(result.revision)&&result.revision>0) return result;
  if(!result||result.schema_version!==2||!uuid.test(result.watch_id)||result.auction_id!==auctionId||result.actor_id!==owner.subjectId||
    !Number.isSafeInteger(result.revision)||result.revision<1||typeof result.active!=='boolean'||
    (result.amount_minor!==null&&(!minor(result.amount_minor,9_000_000_000_000_000)||result.amount_minor===0))||
    (result.standing!==null&&result.standing!=='leading'&&result.standing!=='outbid')||
    (result.active&&(result.amount_minor===null||result.standing!=='leading'))) throw new ApiError(503,'invalid_private_maximum','');
  return result;
}

/** Receipt recovery remains available after the scheduled auction end. */
export async function lookupMaximum(auctionId:string,intent:MaximumReference,signal:AbortSignal) {
  const result=await maximumRequest<MaximumOperationV2>(auctionId,intent.owner,signal,{action:'lookup_v2',operation_id:intent.key});
  return validateReceipt(result,auctionId,intent);
}

function receiptId(value:unknown):value is string {
  return typeof value==='string'&&uuid.test(value);
}

function positiveRevision(value:unknown):value is number {
  return typeof value==='number'&&Number.isSafeInteger(value)&&value>0;
}

function reviewInstant(value:unknown) {
  if(typeof value!=='string'||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]00:00)$/.test(value)||
    !instant(value)) return false;
  return new Date(value).toISOString().slice(0,19)===value.slice(0,19);
}

function validateReceipt(result:MaximumOperationV2,auctionId:string,intent:MaximumReference) {
  if(!result||typeof result!=='object'||Array.isArray(result)||
    Object.keys(result).length!==operationSchema.required.length||
    !operationSchema.required.every(field=>Object.hasOwn(result,field))||
    result.schema_version!==2||!receiptId(result.operation_id)||result.operation_id!==intent.key||
    !receiptId(result.actor_id)||result.actor_id!==intent.actor_id||result.organization_id!==null||
    !receiptId(result.subject_id)||result.subject_id!==auctionId||
    !receiptId(result.watch_id)||result.watch_id!==intent.watch_id||
    !receiptId(result.quote_id)||result.quote_id!==intent.fee_quote_id||
    !positiveRevision(result.expected_revision)||result.expected_revision!==intent.revision||
    !positiveRevision(result.quote_revision)||result.quote_revision!==intent.quote_revision||
    !positiveRevision(result.revision)||
    typeof result.policy_revision!=='string'||result.policy_revision.length<1||result.policy_revision.length>100||
    result.policy_revision!==intent.policy_revision||
    !['accepted','denied','stale','pending'].includes(result.state)||
    (result.state==='accepted'&&result.revision<=intent.revision)||
    (result.pending_reason!==null&&(typeof result.pending_reason!=='string'||result.pending_reason.length>100))||
    (result.next_actor!==null&&!receiptId(result.next_actor))||
    (result.next_review_at!==null&&!reviewInstant(result.next_review_at))) {
    throw new ApiError(503,'invalid_operation','');
  }
  return result;
}

/** Check an earlier receipt through the original owner-scoped lookup. */
export async function lookupMaximumV1(auctionId:string,key:string,command:EarlierMaximumCommand,accessFingerprint:string,signal:AbortSignal) {
  const result=await maximumRequest<AuctionOutcome>(auctionId,accessFingerprint,signal,{action:'lookup_v1',operation_key:key,command});
  return legacyOutcome(result,auctionId,command.expected_revision);
}

function legacyOutcome(result:AuctionOutcome,auctionId:string,revision?:number):'accepted'|'stale'|'denied'|'pending' {
  if(!result||!uuid.test(result.operation_id)||result.auction_id!==auctionId||
    typeof result.revision!=='number'||!Number.isSafeInteger(result.revision)||result.revision<1||
    (revision!==undefined&&result.status==='succeeded'&&result.revision<=revision)||
    (result.status==='succeeded'&&result.code!=='bid_accepted')||
    !['succeeded','denied','pending'].includes(result.status)) throw new ApiError(503,'invalid_operation','');
  return result.status==='pending'?'pending':result.status==='succeeded'?'accepted':result.code==='stale_revision'?'stale':'denied';
}

export async function listEarlierBids(auctionId:string,access:string,before:string|null,signal:AbortSignal) {
  const page=await maximumRequest<EarlierBidPage>(auctionId,access,signal,{action:'list_bid_receipts_v1',before});
  if(page?.auction_id!==auctionId||!Array.isArray(page.items)||page.items.length>20||
    page.items.some(row=>!row||typeof row.operation_id!=='string'||!uuid.test(row.operation_id)||
      !instant(row.recorded_at)||!['accepted','denied','stale'].includes(row.state))||
    new Set(page.items.map(row=>row.operation_id)).size!==page.items.length||
    (page.next_cursor!==null&&(page.items.length!==20||page.next_cursor===before||
      page.next_cursor!==page.items.at(-1)?.operation_id))) throw new ApiError(503,'invalid_operation','');
  return page;
}
