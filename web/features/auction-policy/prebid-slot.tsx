'use client';
import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Card, Checkbox, RowSkeleton, State } from '@beirut-time/ui';
import type { SlotContext } from '@/registry-types';
import type { PrebidCommand, PrebidOutcome } from '@contracts/contracts-auction/policy';
import { authenticatedRequest, useSession, useSessionState, refreshSession, signInHref } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { displayMinor, readLots } from '@/features/auction-management/api';
import { useOperationScope } from '@/features/auction-management/operation-scope';
import { prebid, readPolicy, root } from './api';
import { validPrebidQuote, type PrebidQuote } from './quote';
import en from './en.json';
import ar from './ar.json';

type PrebidProps=SlotContext&{standalone?:boolean};
export default function PrebidSlot(props:PrebidProps){const session=useSession();return <PrebidView key={`${props.resourceId}:${session?.access_fingerprint??'public'}`} {...props}/>;}
function PrebidView({resourceId,locale,standalone=false}:PrebidProps){
  const t=locale==='ar'?ar:en;const session=useSession();const sessionState=useSessionState();const scopeFor=useOperationScope();
  const owner=session?.access_fingerprint;
  const lots=useQuery({queryKey:['prebid-lots',resourceId],enabled:!!resourceId,queryFn:({signal})=>readLots(resourceId,signal),retry:false,refetchInterval:5000});
  const lot=lots.data?.items[0];
  const policy=useQuery({queryKey:['prebid-policy',lot?.id],enabled:!!lot,queryFn:({signal})=>readPolicy(lot!.id,signal),retry:false,refetchInterval:2000});
  const mine=useQuery({queryKey:['my-prebid',owner,lot?.id],enabled:!!owner&&!!lot&&session?.principal.roles.includes('buyer'),queryFn:({signal})=>authenticatedRequest<{operation:PrebidOutcome|null}>(`${root}/auctions/${lot!.id}/my-prebid`,{signal,accessFingerprint:owner}),retry:false,refetchInterval:2000});
  const [quote,setQuote]=useState<PrebidQuote|null>(null);const [agreed,setAgreed]=useState(false);const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [outcome,setOutcome]=useState<PrebidOutcome|null>(null);const [uncertain,setUncertain]=useState(false);
  const attempt=useRef<{body:PrebidCommand;key:string;reviewKey:string;phase:'review'|'reserve';quote:PrebidQuote}|null>(null);
  const value=policy.data;const result=mine.data?.operation??outcome;
  const currentQuote=quote&&quote.subject_revision===value?.revision?quote:null;
  const body=()=>({auction_id:lot!.id,expected_revision:value!.revision});
  function errorMessage(error:unknown){return error instanceof ApiError?(t[error.code as keyof typeof t]??(error.status===403?t.denied:t.unavailable)):t.unavailable;}
  async function preview(){if(!lot||!value?.buy_now_minor||!session||!owner||busy||uncertain)return;const scope=scopeFor();setBusy(true);setQuote(null);setAgreed(false);
    try{const response=await authenticatedRequest<{status:string;quote:unknown}>('/api/web/v1/pricing/v1/auction-quotes',{method:'POST',accessFingerprint:owner,signal:scope.controller.signal,headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(body())});
      if(response.status!=='succeeded')throw new ApiError(503,'quote_invalid','');
      const snapshot=validPrebidQuote(response.quote,{auctionId:lot.id,listingId:lot.listing_id,revision:value.revision,buyerId:session.principal.actor.subject_id,currency:lot.currency,price:value.buy_now_minor});
      if(scope.active){setQuote(snapshot);setMessage('');}
    }catch(error){if(scope.active)setMessage(errorMessage(error));}finally{if(scope.active)setBusy(false);}
  }
  async function purchase(){if(!lot||!owner||busy||(!uncertain&&(!currentQuote||!agreed)))return;const scope=scopeFor();setBusy(true);setMessage(t.pending);
    try{if(!attempt.current){if(!currentQuote)return;attempt.current={body:{expected_revision:currentQuote.subject_revision,quote_id:currentQuote.id},key:crypto.randomUUID(),reviewKey:crypto.randomUUID(),phase:'review',quote:currentQuote};}
      const current=attempt.current;
      if(current.phase==='review'){await authenticatedRequest(`/api/web/v1/pricing/v1/auction-quotes/${current.quote.id}/review`,{method:'POST',accessFingerprint:owner,signal:scope.controller.signal,headers:{'Content-Type':'application/json','Idempotency-Key':current.reviewKey},body:JSON.stringify({quote_revision:current.quote.revision,payable_minor:current.quote.payable_minor})});if(!scope.active)return;current.phase='reserve';}
      const response=await prebid(lot.id,current.body,current.key,owner,scope.controller.signal);
      if(!scope.active)return;setOutcome(response);setUncertain(false);setMessage(response.status==='pending'?t.pending:response.status==='succeeded'?t.reserved:t.reservation_denied);attempt.current=null;void mine.refetch();void policy.refetch();
    }catch(error){if(!scope.active)return;const unknown=!(error instanceof ApiError)||error.status>=500;setUncertain(unknown);if(!unknown)attempt.current=null;setMessage(errorMessage(error));}finally{if(scope.active)setBusy(false);}
  }
  if(!resourceId)return null;
  if(lots.isError||policy.isError)return <Card><State kind="error" title={t.buyNow} body={t.unavailable}><Button onClick={()=>{void lots.refetch();void policy.refetch();}}>{t.retry}</Button></State></Card>;
  if(lots.isPending||lot&&policy.isPending)return <Card><RowSkeleton/><p role="status">{t.loading}</p></Card>;
  if(!lot||!value||!value.buy_now_minor)return standalone?<Card><State title={t.buyNow} body={t.disabled}/></Card>:null;
  return <Card className="auction-policy-panel"><h2>{t.buyNow}</h2><p>{t.boundary}</p>
    <p>{displayMinor(value.buy_now_minor,lot.currency,locale)}</p>
    {!result&&!uncertain&&(value.frozen||lot.status!=='live')?<p role="status">{value.mode!=='bidding'?t.held:value.frozen?t.first_bid_exists:t.auction_ended}</p>:!session?sessionState==='restoring'?<p role="status">{t.loading}</p>:sessionState==='unavailable'?<State kind="error" title={t.buyNow} body={t.unavailable}><Button onClick={()=>void refreshSession().catch(()=>{})}>{t.retry}</Button></State>:<ButtonLink href={signInHref(`/watches/${resourceId}`,locale)}>{t.signBuyer}</ButtonLink>:
      !session.principal.roles.includes('buyer')||session.principal.actor.organization_id?<p>{t.signBuyer}</p>:mine.isPending?<p role="status">{t.loading}</p>:mine.isError?<State kind="error" title={t.buyNow} body={t.unavailable}><Button onClick={()=>mine.refetch()}>{t.retry}</Button></State>:result?<div role="status"><p>{result.status==='succeeded'?t.reserved:result.status==='denied'?t.reservation_denied:t.pending}</p>{result.status==='succeeded'&&result.order_id&&<ButtonLink href={`/${locale}/checkout?order_id=${encodeURIComponent(result.order_id)}&quote_id=${encodeURIComponent(result.quote_id??'')}`}>{t.continue}</ButtonLink>}</div>:
      <div className="auction-policy-form"><Button disabled={busy||uncertain} onClick={preview}>{t.review}</Button>
        {currentQuote&&<><p className="muted">{t.sample}</p><dl><div><dt>{t.buyerFee}</dt><dd>{displayMinor(currentQuote.buyer_fee_minor,lot.currency,locale)}</dd></div><div><dt>{t.shipping}</dt><dd>{displayMinor(currentQuote.shipping_minor,lot.currency,locale)}</dd></div><div><dt>{t.tax}</dt><dd>{displayMinor(currentQuote.tax_minor,lot.currency,locale)}</dd></div><div><dt>{t.total}</dt><dd>{displayMinor(currentQuote.payable_minor,lot.currency,locale)}</dd></div><div><dt>{t.expiry}</dt><dd><BidiReference>{currentQuote.expires_at}</BidiReference></dd></div></dl><Checkbox checked={agreed} disabled={busy||uncertain} onChange={event=>setAgreed(event.target.checked)}>{t.confirm}</Checkbox></>}
        <Button disabled={busy||(!uncertain&&(!currentQuote||!agreed))} onClick={purchase}>{uncertain?t.retry:t.purchase}</Button>
      </div>}
    <p role="status" aria-live="polite">{message}</p>
  </Card>;
}
