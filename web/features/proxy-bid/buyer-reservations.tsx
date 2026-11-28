'use client';

import {AnimatedList,Button,ButtonLink,Card,RowSkeleton,State,StatusBadge} from '@beirut-time/ui/foundation';
import {useEffect,useState} from 'react';
import type {BuyerWorkspace} from '@contracts/contracts-comms/buyer-workspace';
import {ApiError} from '@/lib/api/client';
import {definePageRead} from '@/lib/page-speed/definition';
import {usePageRead} from '@/lib/page-speed/read';
import {AnswerArrival} from '@/lib/page-speed/arrival';
import {useLocale} from '@/shell/locale-context';
import {formatMinor} from './money';
import {buyerDateFormatter} from './buyer-date';
import {authenticatedRequest} from './session';
import en from './en.json';
import ar from './ar.json';

export const reservationsRead=definePageRead<[access:string,authorizationEpoch?:string,cursor?:string],BuyerWorkspace['reservations']>({
  key:(access,authorizationEpoch,cursor)=>[
    'L16','buyer-reservations',access,...(authorizationEpoch?[authorizationEpoch]:[]),...(cursor?['cursor',cursor]:[]),
  ],
  fresh:0,warm:'open-only',
  ask:async(signal,access,_authorizationEpoch,cursor)=>{
    const params=new URLSearchParams({section:'reservations'});
    if(cursor) params.set('cursor',cursor);
    return authenticatedRequest<BuyerWorkspace['reservations']>(
      `/api/web/v1/communications/v1/buyer-workspace?${params}`,{signal,accessFingerprint:access,cache:'no-store'});
  },
});

export function BuyerReservations({fingerprint,authorizationEpoch}:{fingerprint:string;authorizationEpoch?:string}) {
  const locale=useLocale(),t=locale==='ar'?ar:en;
  const [pages,setPages]=useState<string[]>([]);
  const cursor=pages.at(-1);
  const query=usePageRead(reservationsRead(fingerprint,authorizationEpoch,cursor));
  const {refetch}=query;
  useEffect(()=>{
    const timer=setInterval(()=>void refetch(),15000);
    return ()=>clearInterval(timer);
  },[refetch]);
  const denied=query.error instanceof ApiError&&[401,403].includes(query.error.status);
  const reservations=query.isError||query.isFetchedAfterMount===false?undefined:query.data;
  const next=reservations?.next_cursor;
  const canAdvance=Boolean(next&&!pages.includes(next));
  const date=buyerDateFormatter(locale);
  return <Card aria-label={t.reservations}>
    <h2>{t.reservations}</h2>
    {denied?<State title={t.accessDenied} body={t.retryBody}>
      <Button onClick={()=>void query.refetch()}>{t.retry}</Button>
    </State>:query.isPending||query.isFetchedAfterMount===false?<><State title={t.loading} body={t.reservations} kind="loading"/><RowSkeleton/></>:
      reservations?.state!=='available'?<State title={t.unavailable} body={t.retryBody} kind="error">
        <Button onClick={()=>void query.refetch()}>{t.retry}</Button>
      </State>:<AnswerArrival view="buyer-reservations">
        <AnimatedList className="buyer-activity" scopeKey={fingerprint} items={reservations.items.filter(row=>row.currency==='USD')}
          getKey={row=>row.reservation_id} empty={<State title={cursor||canAdvance?t.emptyReservationPage:t.emptyReservations} body={t.pendingNotice}/>}>
          {row=><article className="buyer-activity-row">
            <StatusBadge>{t[row.state]}</StatusBadge> {row.is_demo&&<StatusBadge>{t.demo}</StatusBadge>}
            <p className="buyer-reference"><bdi>{row.reservation_id}</bdi></p>
            <p>{row.currency==='USD'&&Number.isSafeInteger(row.total_minor)&&row.total_minor>=0
              ?<bdi>{formatMinor(row.total_minor,'USD',locale)}</bdi>:t.unknownTotal}</p>
            <p>{row.expires_at&&Number.isFinite(Date.parse(row.expires_at))
              ?<>{t.expires} <time dateTime={row.expires_at}>{date.format(new Date(row.expires_at))}</time></>:t.unknownExpiry}</p>
            <ButtonLink href={`/${locale}/checkout/${encodeURIComponent(row.reservation_id)}`}>{t.reviewReservation}</ButtonLink>
            <p className="buyer-note">{t.paymentUnavailable}</p>
          </article>}
        </AnimatedList>
        {canAdvance&&<Button variant="outline" disabled={query.isFetching}
          onClick={()=>{if(next) setPages([...pages,next]);}}>{t.nextPage}</Button>}
      </AnswerArrival>}
    {pages.length>0&&!denied&&<>
      <Button variant="outline" disabled={query.isFetching} onClick={()=>setPages(pages.slice(0,-1))}>{t.previousPage}</Button>
      <Button variant="outline" disabled={query.isFetching} onClick={()=>setPages([])}>{t.firstPage}</Button>
    </>}
    <ButtonLink variant="outline" href={`/${locale}/checkout`}>{t.reviewRequests}</ButtonLink>
  </Card>;
}
