'use client';

import {useEffect,useRef,useState} from 'react';
import {Button,State} from '@beirut-time/ui/foundation';
import {ApiError} from '@/lib/api/client';
import type {EarlierBidPage} from '@contracts/contracts-auction/proxy';
import {listEarlierBids} from './maximum-api';
import {buyerDateFormatter} from './buyer-date';
import en from './en.json';
import ar from './ar.json';

export function EarlierBids({auctionId,access,locale,onDenied}:{auctionId:string;access:string;locale:'en'|'ar';onDenied:()=>void}) {
  const t=locale==='ar'?ar:en;
  const [page,setPage]=useState<EarlierBidPage|null>(null);
  const [status,setStatus]=useState<'idle'|'loading'|'available'|'unavailable'>('idle');
  const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>request.current?.abort(),[]);
  const date=buyerDateFormatter(locale);

  async function load(before:string|null) {
    if(request.current) return;
    const controller=new AbortController();
    request.current=controller;
    setPage(null);
    setStatus('loading');
    try {
      const current=await listEarlierBids(auctionId,access,before,controller.signal);
      if(controller.signal.aborted) return;
      setPage(current);
      setStatus('available');
    } catch(error) {
      if(controller.signal.aborted) return;
      if(error instanceof ApiError&&[401,403].includes(error.status)) onDenied();
      else setStatus('unavailable');
    } finally {
      request.current=null;
    }
  }

  return <section aria-label={t.earlierBidHistory}>
    <Button type="button" busy={status==='loading'} onClick={()=>void load(null)}>{t.earlierBidHistory}</Button>
    {status==='loading'&&<State kind="loading" title={t.loading} body={t.earlierBidHistory}/>}
    {status==='unavailable'&&<State kind="error" title={t.unavailable} body={t.retryBody}/>}
    {page?.items.length===0&&<p role="status">{t.noEarlierBidReceipts}</p>}
    {page&&page.items.length>0&&<ul>{page.items.map(row=><li key={row.operation_id}>
      <time dateTime={row.recorded_at}>{date.format(new Date(row.recorded_at))}</time>
      {' · '}{t[row.state==='accepted'?'legacyAccepted':row.state]}
      {' · '}{t.receiptReference} <bdi>{row.operation_id}</bdi>
    </li>)}</ul>}
    {page?.next_cursor&&<Button type="button" onClick={()=>void load(page.next_cursor)}>{t.moreEarlierBids}</Button>}
  </section>;
}
