'use client';
import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authenticatedRequest } from '@/features/identity/session';
import { request } from '@/lib/api/client';
import { Button, ButtonLink, Card, Input, LoadingRows, SectionState, StatusBadge, BidiReference } from '@beirut-time/ui';
import type { Quote, QuoteInput } from '@contracts/contracts-pricing/quotes';
import type { Offer, OfferOutcome } from '@contracts/contracts-pricing/offers';
import { money, parseMinor } from '@/features/pricing/money';
import { orderReviewHref } from './order-link';
import { offerRoute } from './admission';
import { QuoteDesk, QuoteGate, QuoteScope, QuoteFailure, SamplePolicy, useQuoteCopy, useQuoteScope, quoteBase, post, expiry } from '@/features/pricing/s2-shared';

type Listing={id:string;revision:number;status:string;facts:{brand:string;model:string;currency:'USD'|'LBP';price_minor:number|null;sale_mode:string};is_demo:boolean};
type Availability={listing_id:string;status:string;sale_mode:string};
function Fees({quote}:{quote:Quote}){
 const {locale,t}=useQuoteCopy();return <dl className="l14-fees">{([['price_minor',t.price],['buyer_fee_minor',t.platformFee],['payable_minor',t.total],['seller_commission_minor',t.commission],['seller_net_minor',t.net]] as const).map(([field,label])=><div key={field} className={field==='payable_minor'?'l14-total':''}><dt>{label}</dt><dd><BidiReference>{money(quote[field],quote.currency,locale)}</BidiReference></dd></div>)}</dl>;
}
function Make({listingId,onSaved}:{listingId:string;onSaved:()=>void}){
 const {locale,t}=useQuoteCopy(),[amount,setAmount]=useState(''),[preview,setPreview]=useState<Quote|null>(null),keys=useRef(new Map<string,string>());
 const stable=(name:string)=>{if(!keys.current.has(name))keys.current.set(name,crypto.randomUUID());return keys.current.get(name)!;};
 const source=useQuery({queryKey:['l14','offer-source',listingId],queryFn:({signal})=>request<Listing>(`/api/web/v1/catalog/v1/listings/${listingId}`,{signal})});
 const availability=useQuery({queryKey:['l14','offer-availability',listingId],queryFn:({signal})=>request<Availability>(`/api/web/v1/orders/v1/listings/${listingId}/availability`,{signal})});
 const build=useMutation({mutationFn:async()=>{
  const listing=source.data!;const body:QuoteInput={subject_id:listing.id,subject_revision:listing.revision,purpose:'offer',currency:listing.facts.currency,price_minor:parseMinor(amount,listing.facts.currency),schedule_id:'usd-v2',source:'sample'};
  const token='preview:'+JSON.stringify(body);let quote=await authenticatedRequest<Quote>(`${quoteBase}/quotes`,post(body,stable(token)));
  if(Date.parse(quote.expires_at)<=Date.now()){keys.current.set(token,crypto.randomUUID());quote=await authenticatedRequest<Quote>(`${quoteBase}/quotes`,post(body,stable(token)));}
  return quote;
 },onSuccess:setPreview});
 const send=useMutation({mutationFn:async()=>{
  const q=preview!;const review={subject_id:q.subject_id,subject_revision:q.subject_revision,purpose:q.purpose,currency:q.currency,price_minor:q.price_minor,schedule_id:q.schedule_id,source:q.source??'sample',quote_revision:q.revision,payable_minor:q.payable_minor};
  await authenticatedRequest(`${quoteBase}/quotes/${q.id}/review`,post(review,stable('review:'+q.id)));
  return authenticatedRequest<OfferOutcome>(`${quoteBase}/offers`,post({listing_id:q.subject_id,listing_revision:q.subject_revision,amount_minor:q.price_minor,currency:q.currency,schedule_id:q.schedule_id,fee_quote_id:q.id},stable('offer:'+q.id)));
 },onSuccess:()=>{setPreview(null);setAmount('');keys.current.clear();onSaved();}});
 return <Card className="l14-stack" data-offer-compose><h2>{t.newOffer}</h2>{source.isPending||availability.isPending?<LoadingRows label={t.loading}/>:source.isError||availability.isError?null:source.isSuccess&&source.data&&source.data.status==='published'&&source.data.facts.currency==='USD'&&availability.data?.listing_id===listingId&&availability.data.status==='available'&&offerRoute(source.data.facts.sale_mode,availability.data.sale_mode)?<><p>{source.data.facts.brand} · {source.data.facts.model}</p>{source.data.is_demo&&<div className="l14-row"><StatusBadge>{t.sampleListing}</StatusBadge></div>}<form className="l14-form" onSubmit={event=>{event.preventDefault();build.mutate();}}><label>{t.amount}<Input name="offer-amount" inputMode="decimal" dir="ltr" required maxLength={20} value={amount} onChange={event=>{setAmount(event.target.value);setPreview(null);}}/></label><Button disabled={build.isPending} type="submit">{build.isPending?t.working:t.preview}</Button></form>{preview&&<><Fees quote={preview}/><p>{t.expires}: <BidiReference>{expiry(preview.expires_at,locale)}</BidiReference></p><p>{t.offerValidity}</p><Button disabled={send.isPending} onClick={()=>send.mutate()}>{send.isPending?t.working:t.sendOffer}</Button></>}{send.isSuccess&&<p role="status">{t.offerSent}</p>}</>:<SectionState title={t.offerUnavailable} body={t.offerUnavailableBody}/>}<QuoteFailure error={source.error||availability.error||build.error||send.error}/></Card>;
}
function Offers({initialListing}:{initialListing?:string}){
 const {session,scope,organization,setOrganization,suffix}=useQuoteScope(),{locale,t}=useQuoteCopy(),cache=useQueryClient(),keys=useRef(new Map<string,string>());
 const rows=useQuery({queryKey:['l14',scope,'offers'],queryFn:({signal})=>authenticatedRequest<{items:Offer[]}>(`${quoteBase}/offers${suffix}`,{signal})});
 const refresh=()=>{void cache.invalidateQueries({queryKey:['l14',scope,'offers']});if(initialListing){void cache.invalidateQueries({queryKey:['l14','offer-source',initialListing]});void cache.invalidateQueries({queryKey:['l14','offer-availability',initialListing]});}};
 const action=useMutation({mutationFn:async({offer,kind}:{offer:Offer;kind:'accept'|'reject'|'reconcile'|'block'|'unblock'})=>{
  const token=`${offer.id}:${kind}:${offer.revision}`;if(!keys.current.has(token))keys.current.set(token,crypto.randomUUID());
  return authenticatedRequest<OfferOutcome>(`${quoteBase}/offers/${offer.id}/${kind==='accept'||kind==='reject'?'answer':kind}${suffix}`,post(kind==='accept'||kind==='reject'?{expected_revision:offer.revision,action:kind}:{},keys.current.get(token)!));
 },onSuccess:refresh,onError:refresh});
 return <><QuoteScope value={organization} onChange={setOrganization}/><Button variant="outline" onClick={refresh}>{t.refresh}</Button><SamplePolicy/>{initialListing&&!organization&&<Make key={`${scope}:${initialListing}`} listingId={initialListing} onSaved={refresh}/>}<ButtonLink href={`/${locale}/watches`}>{t.browse}</ButtonLink><QuoteFailure error={rows.error||action.error} retry={refresh}/>{rows.isPending?<Card><LoadingRows label={t.loading}/></Card>:rows.isError?null:rows.data?.items.length===0?<Card><SectionState title={t.empty} body={t.emptyBody}/></Card>:<div className="l14-grid">{rows.data?.items.map(offer=>{
 const isBuyer=offer.buyer_id===session!.principal.actor.subject_id&&!organization;
 return <Card key={offer.id} data-offer-id={offer.id} className="l14-stack"><div className="l14-row"><ButtonLink variant="ghost" href={`/${locale}/watches/${offer.listing_id}`}>{t.watchContext}</ButtonLink><StatusBadge hue={offer.state==='accepted'?'green':offer.state==='acceptance_pending'?'orange':'neutral'}>{t[offer.state]}</StatusBadge></div><Fees quote={offer.quote}/><p className="l14-copy">{t.expires}: <BidiReference>{expiry(offer.expires_at,locale)}</BidiReference> · {t.revision} {offer.revision}</p>{!isBuyer&&offer.state==='open'&&<div className="l14-row"><Button disabled={action.isPending} onClick={()=>action.mutate({offer,kind:'accept'})}>{t.acceptOffer}</Button><Button variant="outline" disabled={action.isPending} onClick={()=>action.mutate({offer,kind:'reject'})}>{t.rejectOffer}</Button></div>}{offer.state==='acceptance_pending'&&<p role="status">{t.pending}</p>}{!isBuyer&&offer.state==='acceptance_pending'&&<Button disabled={action.isPending} onClick={()=>action.mutate({offer,kind:'reconcile'})}>{t.reconcile}</Button>}{offer.order_id&&<ButtonLink href={orderReviewHref(locale,offer.order_id)}>{t.review}</ButtonLink>}<Button variant="ghost" disabled={action.isPending} onClick={()=>action.mutate({offer,kind:'block'})}>{t.block}</Button><Button variant="ghost" disabled={action.isPending} onClick={()=>action.mutate({offer,kind:'unblock'})}>{t.unblock}</Button></Card>;
 })}</div>}</>;
}
export default function OffersPage({initialListing}:{initialListing?:string}){const {session}=useQuoteScope();return <QuoteDesk kind="offers"><QuoteGate next={initialListing?`/offers?listing=${encodeURIComponent(initialListing)}`:'/offers'}>{session&&<Offers key={session.access_fingerprint} initialListing={initialListing}/>}</QuoteGate></QuoteDesk>;}
