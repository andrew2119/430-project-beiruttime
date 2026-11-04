'use client';
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BidiReference, Button, Card, Checkbox, Input, StatusBadge } from '@beirut-time/ui';
import type { SlotContext } from '@/registry-types';
import { request, ApiError } from '@/lib/api/client';
import { authenticatedRequest, useSession, useSessionState, refreshSession, signInHref } from '@/features/identity/session';
import { auctionBase, command, displayMinor, errorCopy, minor, Outcome, quotePreview, QuotePreview, readLots } from './api';
import en from './en.json';
import ar from './ar.json';
import { useOperationScope } from './operation-scope';

type History={items:{sequence:number;bidder:string;amount_minor:number;received_at:string}[]};
export default function BidSlot(props:SlotContext) {
  const session=useSession(); const sessionState=useSessionState();
  return <BidView key={`${session?.access_fingerprint??'signed-out'}:${props.resourceId??''}`} {...props} session={session} sessionState={sessionState}/>;
}
function BidView({resourceId,locale,session,sessionState}:SlotContext&{session:ReturnType<typeof useSession>;sessionState:ReturnType<typeof useSessionState>}) {
  const owner=session?.access_fingerprint; const t=locale==='ar'?ar:en; const cache=useQueryClient(); const operationScope=useOperationScope();
  const lots=useQuery({queryKey:['listing-auction',resourceId],enabled:!!resourceId,queryFn:({signal})=>readLots(resourceId,signal),refetchInterval:1000,retry:false});
  const lot=lots.data?.items[0]; const [amount,setAmount]=useState(''); const [savedQuote,setQuote]=useState<QuotePreview|null>(null);
  const quote=savedQuote?.auction_revision===lot?.revision?savedQuote:null;
  const [reviewed,setReviewed]=useState(false); const [message,setMessage]=useState(''); const [pending,setPending]=useState(false); const [uncertain,setUncertain]=useState(false); const [outcome,setOutcome]=useState<Outcome|null>(null);
  const attempt=useRef<{key:string;reviewKey:string;body:unknown;quote:QuotePreview;phase:'review'|'bid'}|null>(null);
  const history=useQuery({queryKey:['auction-history',lot?.id,lot?.revision],enabled:!!lot,queryFn:({signal})=>request<History>(`${auctionBase}/auctions/${lot!.id}/history?limit=10`,{signal}),retry:false});
  async function preview() {
    if(!lot||!session||!owner||pending||uncertain) return;
    const scope=operationScope(); setPending(true); setQuote(null);setReviewed(false);
    try {
      const amount_minor=minor(amount);
      const result=await authenticatedRequest<unknown>('/api/web/v1/pricing/v1/quotes',{method:'POST',signal:scope.controller.signal,accessFingerprint:owner,headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({subject_id:lot.id,subject_revision:lot.revision,purpose:'bid',currency:lot.currency,price_minor:amount_minor,schedule_id:'sample-v1',source:'sample'})});
      if(!scope.active) return;
      setQuote(quotePreview(result,amount_minor,lot.revision,lot.id,session.principal.actor.subject_id,lot.currency));setMessage('');
    } catch(error) {if(scope.active) setMessage(errorCopy(error,t));}
    finally {if(scope.active) setPending(false);}
  }
  async function submit(event:React.FormEvent) {
    event.preventDefault(); if(!lot||!owner||pending||(!uncertain&&(!quote||!reviewed))) return;
    const scope=operationScope(); setPending(true);setMessage(t.pending);
    try {
      if(!attempt.current) { if(!quote) throw new ApiError(409,'fee_preview_required',''); attempt.current={key:crypto.randomUUID(),reviewKey:crypto.randomUUID(),body:{amount_minor:minor(amount),fee_quote_id:quote.id,expected_revision:lot.revision},quote,phase:'review'}; }
      const current=attempt.current;
      if(current.phase==='review') {
        await authenticatedRequest(`/api/web/v1/pricing/v1/quotes/${current.quote.id}/review`,{method:'POST',signal:scope.controller.signal,accessFingerprint:owner,headers:{'Content-Type':'application/json','Idempotency-Key':current.reviewKey},body:JSON.stringify({...current.quote.request,quote_revision:current.quote.quote_revision,payable_minor:current.quote.total_minor})});
        if(!scope.active) return;
        current.phase='bid';
      }
      const result=await command(`/auctions/${lot.id}/bids`,current.body,current.key,scope.controller.signal,owner);
      if(!scope.active) return;
      setOutcome(result);setUncertain(false);setMessage(result.status==='succeeded'?t.accepted:(t[result.code as keyof typeof t]??t.notConfirmed));
      attempt.current=null;setQuote(null);setReviewed(false);void cache.invalidateQueries({queryKey:['listing-auction',resourceId]});
    } catch(error) {
      if(!scope.active) return;
      const unknown=!(error instanceof ApiError)||error.status>=500;setUncertain(unknown);
      if(!unknown) attempt.current=null;
      setMessage(errorCopy(error,t));
    } finally {if(scope.active) setPending(false);}
  }
  if(!resourceId) return null;
  if(lots.isError) return <Card className="auction-feature"><p role="status">{errorCopy(lots.error,t)}</p><Button onClick={()=>lots.refetch()}>{t.retry}</Button></Card>;
  if(!lot) return lots.isPending?<Card className="auction-feature"><p role="status">{t.pending}</p></Card>:null;
  return <Card className="auction-feature auction-bid-panel"><div className="auction-row"><h2>{t.bid}</h2><StatusBadge hue={lot.status==='live'?'green':lot.status==='scheduled'?'blue':'neutral'}>{t[lot.status]}</StatusBadge></div>
    <div className="auction-price"><span>{t.current}</span><strong>{displayMinor(lot.current_minor||lot.opening_minor,lot.currency,locale)}</strong><small>{t.next}: {displayMinor(lot.next_minimum_minor,lot.currency,locale)}</small></div>
    <details><summary>{t.rules}</summary><dl><div><dt>{t.starts}</dt><dd><BidiReference>{lot.starts_at}</BidiReference></dd></div><div><dt>{t.ends}</dt><dd><BidiReference>{lot.ends_at}</BidiReference></dd></div><div><dt>{t.server}</dt><dd><BidiReference>{lot.server_time}</BidiReference></dd></div></dl><p>{lot.reserve_set?t.reserveSet:t.reserveNone} · {t.extension}</p><p>{t.highValue} {displayMinor(lot.high_value_minor,lot.currency,locale)}</p><ul>{lot.increment_bands.map(b=><li key={b.from_minor}>{displayMinor(b.from_minor,lot.currency,locale)} + {displayMinor(b.step_minor,lot.currency,locale)}</li>)}</ul></details>
    {!session?sessionState==='restoring'?<p role="status">{t.pending}</p>:sessionState==='unavailable'?<div><p>{t.unavailable}</p><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></div>:<p>{t.signinBuyer} <a href={signInHref(`/watches/${resourceId}`,locale)}>{t.signin}</a></p>:<form onSubmit={submit} className="auction-bid-form"><label>{t.amount}<Input value={amount} inputMode="decimal" required disabled={pending||uncertain} onChange={e=>{setAmount(e.target.value);setQuote(null);setReviewed(false);}} /></label>
      <Button type="button" disabled={pending||uncertain||!amount||lot.status!=='live'} onClick={preview}>{t.fees}</Button>
      {quote&&<div className="auction-fee-preview"><p className="muted">{t.samplePolicy}</p><dl><div><dt>{t.buyerFee}</dt><dd>{displayMinor(quote.buyer_fee_minor,lot.currency,locale)}</dd></div><div><dt>{t.shipping}</dt><dd>{displayMinor(quote.shipping_minor,lot.currency,locale)}</dd></div><div><dt>{t.tax}</dt><dd>{displayMinor(quote.tax_minor,lot.currency,locale)}</dd></div><div><dt>{t.total}</dt><dd>{displayMinor(quote.total_minor,lot.currency,locale)}</dd></div></dl><Checkbox className="auction-check" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}>{t.confirmFees}</Checkbox></div>}
      <Button disabled={pending||(!uncertain&&(!reviewed||!quote||lot.status!=='live'))}>{uncertain?t.retry:t.bid}</Button></form>}
    <p role="status" aria-live="polite">{message}</p>{outcome&&<p className="muted">{t.record}: <BidiReference>{outcome.operation_id}</BidiReference> · {outcome.accepted_sequence}</p>}
    <h3>{t.history}</h3>{history.isError?<p>{t.unavailable}</p>:!history.data?.items.length?<p className="muted">{t.noBids}</p>:<ol className="auction-history">{history.data.items.map(b=><li key={b.sequence}><BidiReference>#{b.sequence} · {b.bidder}</BidiReference><strong>{displayMinor(b.amount_minor,lot.currency,locale)}</strong><time dateTime={b.received_at}><BidiReference>{b.received_at}</BidiReference></time></li>)}</ol>}
  </Card>;
}
