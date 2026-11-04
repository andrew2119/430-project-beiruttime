'use client';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BidiReference, Button, ButtonLink, Card, Input, State } from '@beirut-time/ui';
import { useLocale } from '@/shell/locale-context';
import { useSession, signInHref } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { AllocationOperation } from '@contracts/contracts-orders/allocation';
import { buyNowApi } from './api';
import { copy, errorText, uuid, canonicalReference, validatedReservation } from './copy';
import { recallReservation, rememberReservation, purgeReservation, reservationMemoryEpoch } from './memory';

export default function Checkout(){
  const locale=useLocale();const t=copy(locale);const session=useSession();
  useEffect(()=>{window.addEventListener('bt:access-change',purgeReservation);return()=>window.removeEventListener('bt:access-change',purgeReservation);},[]);
  const boundary=useQuery({queryKey:['l08-orders',session?.access_fingerprint??'restore'],queryFn:({signal})=>buyNowApi.orders(signal),retry:false});
  if(!session){
    const outage=boundary.error instanceof ApiError&&boundary.error.status>=500;
    return <State title={t.title} body={boundary.isPending?t.loading:outage?t.unavailable:t.signInBody}>{outage?<Button onClick={()=>void boundary.refetch()}>{t.reload}</Button>:!boundary.isPending&&<ButtonLink href={signInHref('/checkout',locale)}>{t.signIn}</ButtonLink>}</State>;
  }
  return <CheckoutBody key={session.access_fingerprint} fingerprint={session.access_fingerprint} buyerId={session.principal.actor.subject_id}/>;
}
function CheckoutBody({fingerprint,buyerId}:{fingerprint:string;buyerId:string}){
  const locale=useLocale();const t=copy(locale);const cache=useQueryClient();
  const[generation]=useState(reservationMemoryEpoch);
  const[initial]=useState(()=>recallReservation(fingerprint));
  const[watch,setWatch]=useState(()=>initial?.pending?initial.watch:canonicalReference((typeof window!=='undefined'?new URLSearchParams(window.location.search).get('watch'):null)??initial?.watch??''));
  const[quote,setQuote]=useState(()=>initial?.pending?initial.quote:canonicalReference((typeof window!=='undefined'?new URLSearchParams(window.location.search).get('quote'):null)??initial?.quote??''));const[checked,setChecked]=useState(initial?.checked??'');
  const[busy,setBusy]=useState(false);const[error,setError]=useState<unknown>(null);const[uncertain,setUncertain]=useState(!!initial?.pending);
  const[result,setResult]=useState<AllocationOperation|null>(null);
  const operation=useRef(initial?.pending??null);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{rememberReservation({owner:fingerprint,watch,quote,checked,pending:operation.current},generation);},[fingerprint,watch,quote,checked,uncertain,generation]);
  const availability=useQuery({queryKey:['l08-availability',checked],queryFn:({signal})=>buyNowApi.availability(checked,signal),enabled:uuid.test(checked),retry:false});
  const orders=useQuery({queryKey:['l08-orders',fingerprint],queryFn:({signal})=>buyNowApi.orders(signal),retry:false});
  function check(event:FormEvent){event.preventDefault();if(reservationMemoryEpoch()!==generation)return;if(!uuid.test(watch)){setError(new ApiError(422,'invalid',''));return;}setError(null);setResult(null);if(checked===watch)void availability.refetch();else setChecked(watch);}
  const reserve=useCallback(async():Promise<AllocationOperation|null>=>{
    if(reservationMemoryEpoch()!==generation)return null;
    if(!operation.current){if(!availability.data||availability.data.watch_id!==watch||!uuid.test(quote))return null;operation.current={body:{watch_id:watch,quote_id:quote,expected_revision:availability.data.revision},key:crypto.randomUUID()};}
    rememberReservation({owner:fingerprint,watch,quote,checked,pending:operation.current},generation);
    setBusy(true);setError(null);
    try{
      const value=validatedReservation(await buyNowApi.reserve(operation.current.body,operation.current.key),operation.current.body.watch_id,buyerId);
      if(!alive.current||reservationMemoryEpoch()!==generation)return null;
      setResult(value);setUncertain(false);operation.current=null;
      rememberReservation({owner:fingerprint,watch,quote,checked,pending:null},generation);
      void cache.invalidateQueries({queryKey:['l08-orders',fingerprint]});void cache.invalidateQueries({queryKey:['l08-availability']});void cache.invalidateQueries({queryKey:['l08-listing-availability']});return value;
    }catch(reason){if(alive.current&&reservationMemoryEpoch()===generation){setError(reason);setUncertain(!(reason instanceof ApiError)||reason.status>=500);if(reason instanceof ApiError&&reason.status<500){operation.current=null;rememberReservation({owner:fingerprint,watch,quote,checked,pending:null},generation);}}return null;}
    finally{if(alive.current&&reservationMemoryEpoch()===generation)setBusy(false);}
  },[availability.data,watch,quote,checked,fingerprint,buyerId,generation,cache]);
  useEffect(()=>{
    const switchLocale=(event:MouseEvent)=>{
      const anchor=event.target instanceof Element?event.target.closest<HTMLAnchorElement>('a.locale-control'):null;
      if(reservationMemoryEpoch()!==generation||!anchor||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      const destination=new URL(anchor.href),language=/^\/(en|ar)(?:\/|$)/.exec(destination.pathname)?.[1];
      if(destination.origin!==window.location.origin||!language)return;
      event.preventDefault();event.stopPropagation();if(busy)return;
      const move=(outcome:AllocationOperation|null)=>{
        if(outcome?.order){destination.pathname=`/${language}/checkout/${outcome.order.id}`;destination.search='';}
        else{if(uuid.test(watch))destination.searchParams.set('watch',watch);else destination.searchParams.delete('watch');if(uuid.test(quote))destination.searchParams.set('quote',quote);else destination.searchParams.delete('quote');}
        window.dispatchEvent(new Event('bt:before-locale-change'));document.cookie=`bt-locale=${language}; Path=/; Max-Age=31536000; SameSite=Lax`;window.location.assign(destination.href);
      };
      // A full locale navigation must not abandon an uncertain reservation or its operation key.
      if(uncertain)void reserve().then(outcome=>{if(outcome&&alive.current&&reservationMemoryEpoch()===generation)move(outcome);});else move(result);
    };
    document.addEventListener('click',switchLocale,true);return()=>document.removeEventListener('click',switchLocale,true);
  },[busy,uncertain,watch,quote,result,reserve,generation]);
  const state=availability.data;const allowed=state?.status==='available'&&state.sale_mode==='fixed'&&state.watch_id===watch&&uuid.test(quote);
  return <div className="checkout-page"><header><p className="eyebrow">{t.eyebrow}</p><h1>{t.title}</h1><p>{t.intro}</p></header>
    <div className="checkout-grid"><Card><form className="checkout-form" method="post" autoComplete="off" onSubmit={check}>
      <label>{t.watch}<Input name="watch_id" dir="ltr" value={watch} onChange={e=>{setWatch(canonicalReference(e.target.value));setResult(null);}} maxLength={36} required disabled={busy||uncertain} autoComplete="off"/></label>
      <label>{t.quote}<Input name="quote_id" dir="ltr" value={quote} onChange={e=>{setQuote(canonicalReference(e.target.value));setResult(null);}} maxLength={36} disabled={busy||uncertain} autoComplete="off"/><small>{t.quoteHelp}</small></label>
      <Button type="submit" className="button-secondary" disabled={busy||uncertain}>{t.load}</Button>
    </form>
    {availability.isFetching&&<p role="status">{t.loading}</p>}
    {state&&<div className="checkout-status"><strong>{t[state.status]}</strong>{state.is_demo&&<p>{t.sample}</p>}<p>{t.revision} <BidiReference>{state.revision}</BidiReference></p>{state.sale_mode!=='fixed'&&<p>{t.auction}</p>}</div>}
    {(error||availability.error)&&<div className="checkout-error" role="alert"><p>{errorText(error??availability.error,t)}</p>{error instanceof ApiError&&error.requestId&&<small>{t.support}: <BidiReference>{error.requestId}</BidiReference></small>}</div>}
    {uncertain&&<p role="status">{t.uncertain}</p>}
    <div className="checkout-actions"><Button disabled={busy||(!allowed&&!uncertain)||result?.status==='succeeded'} onClick={()=>void reserve()}>{busy?t.loading:uncertain?t.retry:t.reserve}</Button><ButtonLink className="button-secondary" href={`/${locale}/prices${state?'?listing_id='+encodeURIComponent(state.listing_id):''}`}>{t.quoteLink}</ButtonLink></div>
    {result&&<div className="checkout-status" role="status"><h2>{result.status==='succeeded'?t.saved:t[result.code??'denied']??t.denied}</h2>{result.order&&<><p>{t[result.order.state]}</p><p>{t.deadline}: <time dateTime={result.order.deadline}>{new Date(result.order.deadline).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time></p><ButtonLink href={`/${locale}/checkout/${result.order.id}`}>{t.open}</ButtonLink></>}</div>}
    </Card><aside><Card><h2>{t.yourOrders}</h2>{orders.isPending&&<p role="status">{t.loading}</p>}{orders.error&&<div role="alert"><p>{errorText(orders.error,t)}</p><Button className="button-secondary" onClick={()=>void orders.refetch()}>{t.reload}</Button></div>}
    {orders.data?.items.length===0&&<p>{t.empty}</p>}<ul className="checkout-orders">{orders.data?.items.map(order=><li key={order.id}><a href={`/${locale}/checkout/${order.id}`}><BidiReference>{order.id}</BidiReference></a><p>{t[order.state]}</p>{order.is_demo&&<small>{t.sample}</small>}</li>)}</ul></Card></aside></div>
    <div className="checkout-status">{t.paymentNotice}</div></div>;
}
