'use client';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {Button,Card,Input,BidiReference} from '@beirut-time/ui';
import type {SlotContext} from '@/registry-types';
import type {AuctionSnapshot} from '@contracts/contracts-auction/core';
import {ApiError,request} from '@/lib/api/client';
import {refreshSession,signInHref,useBuyerSession} from './session';
import {MAX_QUOTE_MINOR,previewMaximum,reviewMaximum,sendMaximum,type MaximumIntent,type MaximumQuote} from './maximum-api';
import {formatMinor,parseMaximum} from './money';
import en from './en.json';
import ar from './ar.json';

type FormProps={auctionId:string;revision:number;currency:'USD'|'LBP';locale:'en'|'ar';onRefresh:()=>void;signInNext?:string;getQuote?:(amount:number,signal:AbortSignal)=>Promise<MaximumQuote>};
export function MaximumForm(props:FormProps) {
  const session=useBuyerSession();
  return <MaximumFormForBuyer key={`${session.fingerprint}:${props.auctionId}`} {...props} session={session}/>;
}
function MaximumFormForBuyer({auctionId,revision,currency,locale,onRefresh,getQuote,signInNext,session}:FormProps&{session:ReturnType<typeof useBuyerSession>}) {
  const t=locale==='ar'?ar:en;
  const [value,setValue]=useState(''),[savedQuote,setQuote]=useState<MaximumQuote|null>(null);
  const quote=savedQuote?.auction_revision===revision?savedQuote:null;
  const [state,setState]=useState<'idle'|'quoting'|'quoted'|'quoteUnavailable'|'quoteExpired'|'sending'|'acknowledged'|'invalidAmount'|'denied'|'stale'|'uncertain'|'offline'>('idle');
  const intent=useRef<MaximumIntent|null>(null),generation=useRef(0),cancellation=useRef<AbortController|null>(null);
  const review=useRef<{key:string;quote:MaximumQuote;acknowledged:boolean}|null>(null);
  const allowed=Boolean(session.state==='authenticated'&&session.signedIn&&session.subjectId&&session.fingerprint&&session.roles.includes('buyer'));
  useEffect(()=>()=>{generation.current++;cancellation.current?.abort();intent.current=null;review.current=null;},[]);
  async function submit() {
    if(!allowed||state==='sending'||state==='quoting'||!session.fingerprint||!getQuote) return;
    if(navigator.onLine===false) {setState(intent.current?'uncertain':'offline');return;}
    const amount=parseMaximum(value);
    if(amount===null) {setState('invalidAmount');return;}
    const epoch=generation.current;
    cancellation.current??=new AbortController();
    const signal=cancellation.current.signal;
    if(!quote&&!intent.current) {
      setState('quoting');
      try {
        const preview=await getQuote(amount,signal);
        if(epoch!==generation.current) return;
        if(preview.amount_minor!==amount||preview.auction_revision!==revision||!Number.isSafeInteger(preview.buyer_fee_minor)||preview.buyer_fee_minor<0||
          !Number.isSafeInteger(preview.total_minor)||preview.total_minor<amount||preview.currency!==currency||
          !preview.fee_quote_id||!(Date.parse(preview.expires_at)>Date.now())) throw new Error('invalid_quote');
        setQuote(preview);setState('quoted');
      } catch(error) {
        if(epoch===generation.current) setState(error instanceof ApiError&&[401,403].includes(error.status)?'denied':error instanceof ApiError&&error.status===422?'invalidAmount':'quoteUnavailable');
      }
      return;
    }
    // An uncertain operation always retries the exact original body/key, even
    // after quote expiry. Only the authoritative runtime can reconcile it.
    if(!intent.current&&quote&&Date.parse(quote.expires_at)<=Date.now()) {setQuote(null);setState('quoteExpired');return;}
    intent.current??={key:crypto.randomUUID(),amount_minor:amount,fee_quote_id:quote!.fee_quote_id,revision,owner:session.fingerprint};
    const pending=intent.current;
    review.current??={key:crypto.randomUUID(),quote:quote!,acknowledged:false};
    const acknowledgement=review.current;
    setState('sending');
    try {
      if(!acknowledgement.acknowledged) {
        await reviewMaximum(acknowledgement.quote,acknowledgement.key,signal);
        acknowledgement.acknowledged=true;
      }
      const result=await sendMaximum(auctionId,pending,signal);
      if(epoch!==generation.current||pending.owner!==session.fingerprint) return;
      if(result.status==='succeeded') {intent.current=null;review.current=null;setValue('');setQuote(null);setState('acknowledged');onRefresh();}
      else if(result.status==='denied') {intent.current=null;review.current=null;setQuote(null);setState('denied');onRefresh();}
      else setState('uncertain');
    } catch(error) {
      if(epoch!==generation.current) return;
      if(error instanceof ApiError&&[409,412].includes(error.status)) {intent.current=null;review.current=null;setQuote(null);setState('stale');}
      else if(error instanceof ApiError&&[400,401,403,404,422].includes(error.status)) {intent.current=null;review.current=null;setQuote(null);setState('denied');}
      else setState('uncertain');
    }
  }
  const frozen=state==='sending'||state==='uncertain'||state==='quoting';
  const privacyId=`proxy-privacy-${auctionId}`,feedbackId=`proxy-feedback-${auctionId}`,limitId=`proxy-limit-${auctionId}`;
  return <Card className="proxy-panel"><h2>{t.privateMaximum}</h2><p id={privacyId}>{t.privacy}</p>
    {session.state==='restoring'?<p role="status">{t.loading}</p>:session.state==='unavailable'?<><p role="status">{t.unavailable}</p><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></>:!allowed?<><p>{session.signedIn?t.accessDenied:t.signIn}</p>{!session.signedIn&&<Link className="button" href={signInHref(signInNext??'/buyer',locale)}>{t.account}</Link>}</>:!getQuote?<p role="status">{t.unavailable}</p>:<form onSubmit={event=>{event.preventDefault();void submit();}}>
      <label htmlFor={`maximum-${auctionId}`}>{t.maximumLabel} <BidiReference>{currency}</BidiReference></label>
      <p id={limitId} className="buyer-note">{t.quoteLimit}: <BidiReference>{formatMinor(MAX_QUOTE_MINOR,currency,locale)}</BidiReference></p>
      <Input id={`maximum-${auctionId}`} inputMode="decimal" autoComplete="off" type="text" value={value} maxLength={18}
        disabled={frozen} aria-describedby={`${privacyId} ${feedbackId} ${limitId}`} onChange={event=>{setValue(event.target.value);setQuote(null);setState('idle');}}/>
      {quote&&<div className="proxy-quote"><p>{t.sampleFeePolicy}</p><p>{t.quoteBasis}</p><dl>
        <div><dt>{t.quoteFee}</dt><dd><BidiReference>{formatMinor(quote.buyer_fee_minor,quote.currency,locale)}</BidiReference></dd></div>
        <div><dt>{t.quoteTotal}</dt><dd><BidiReference>{formatMinor(quote.total_minor,quote.currency,locale)}</BidiReference></dd></div>
      </dl></div>}
      <p id={feedbackId} role="status" aria-live="polite">{state==='quoted'&&savedQuote&&!quote?t.stale:state==='idle'?'':state==='sending'?t.sending:t[state]}</p>
      <div className="proxy-actions"><Button type="submit" disabled={state==='sending'||state==='quoting'}>{state==='uncertain'?t.retry:state==='sending'?t.sending:quote?t.setMaximum:t.previewMaximum}</Button>
        {state==='stale'&&<Button type="button" onClick={onRefresh}>{t.refreshAuction}</Button>}</div>
    </form>}
  </Card>;
}

/** L04 supplies the listing id; Auction owns its canonical lot and revision. */
export default function ProxyBidSlot({locale,resourceId}:SlotContext) {
  const t=locale==='ar'?ar:en,cache=useQueryClient(),session=useBuyerSession();
  // SlotContext.resourceId is the listing id, as on the published manual bid slot.
  // Share its canonical query so two bid controls do not double the poll budget.
  const query=useQuery({queryKey:['listing-auction',resourceId],enabled:Boolean(resourceId),
    queryFn:({signal})=>request<{items:AuctionSnapshot[]}>(
      `/api/web/v1/auction/v1/auctions?listing_id=${encodeURIComponent(resourceId!)}`,{signal}),refetchInterval:1000,retry:false});
  const validPage=Array.isArray(query.data?.items)&&query.data.items.length<=100;
  const auction=validPage?query.data!.items[0]:undefined;
  if(!resourceId||(!auction&&query.isSuccess&&validPage)) return null;
  if(auction&&typeof auction.id==='string'&&auction.listing_id===resourceId&&auction.status==='live'&&(auction.currency==='USD'||auction.currency==='LBP')&&Number.isSafeInteger(auction.revision)&&auction.revision>0) {
    return <MaximumForm auctionId={auction.id} revision={auction.revision} currency={auction.currency} locale={locale}
      signInNext={`/buyer/auctions/${resourceId}`} getQuote={(amount,signal)=>previewMaximum(auction,amount,{subjectId:session.subjectId!,accessFingerprint:session.fingerprint!},signal)}
      onRefresh={()=>{void query.refetch();void cache.invalidateQueries({queryKey:['L06','buyer-workspace']});}}/>;
  }
  const message=query.isPending?t.loading:auction?.status==='scheduled'?t.auctionScheduled:auction?.status==='ended'?t.auctionEnded:t.unavailable;
  return <Card className="proxy-panel"><h2>{t.privateMaximum}</h2><p>{t.privacy}</p><p role="status">{message}</p>
    {query.isError&&<Button onClick={()=>void query.refetch()}>{t.retry}</Button>}</Card>;
}
