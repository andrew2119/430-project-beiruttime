'use client';
import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { usesFoundationShell } from '@/shell/foundation/path';
import { Button, Input, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody, PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useSession, useSessionState, refreshSession } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import { signalRead } from './read';
import { copy } from './copy';

function CurrentSignals({fingerprint}:{fingerprint:string}) {
  const locale=useLocale();
  const t=copy[locale==='ar'?'ar':'en'];
  const [page,setPage]=useState(1);
  const [query,setQuery]=useState('');
  const result=usePageRead(signalRead(fingerprint,page));
  const denied=result.error instanceof ApiError && [401,403].includes(result.error.status);
  const data=denied?undefined:result.data;
  return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody>
    <Input label={t.query} id="signal-query" value={query} onValueChange={value=>setQuery(value.slice(0,128))}/>
    {result.isPending?<PageLoading label={t.loading}/>:result.isError?<State kind="error" title={denied?t.denied:t.unavailable} body={denied?t.deniedBody:t.unavailableBody}><Button onClick={()=>void result.refetch()}>{t.retry}</Button></State>:null}
    {data && <>
      <p>{t.count}: {formatNumber(data.total,locale)}</p>
      {result.isFetching && <p role="status">{t.pending}</p>}
      {data.items.filter(item=>item.operation_id.includes(query)).map(item=><article key={item.operation_id}>
        <h2>{item.state==='review_required'?t.review:t.clear}</h2>
        <p>{t.operation}: <bdi>{item.operation_id}</bdi></p>
        {item.reasons.map(reason=><p key={reason.kind}>{reason.kind==='exact_photo_reuse'?t.photo:t.pair}: {formatNumber(reason.count,locale)}</p>)}
        <p>{t.follow}: <bdi>{new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(item.next_review_at))}</bdi></p>
      </article>)}
      {!data.items.some(item=>item.operation_id.includes(query)) && <State title={t.empty} body={t.emptyBody}/>}
      <Button disabled={page===1 || result.isFetching} onClick={()=>setPage(value=>value-1)}>{t.previous}</Button>
      <Button disabled={page*data.page_size>=data.total || result.isFetching} onClick={()=>setPage(value=>value+1)}>{t.next}</Button>
    </>}
  </PageBody></PageFrame>;
}

export default function SignalsView() {
  const path=usePathname();
  const session=useSession();
  const sessionState=useSessionState();
  const locale=useLocale();
  const t=copy[locale==='ar'?'ar':'en'];
  if(!session && sessionState==='restoring')return <PageFrame><PageHeader title={t.title}/><PageBody><PageLoading label={t.loading}/></PageBody></PageFrame>;
  if(!session && sessionState==='unavailable')return <PageFrame><PageHeader title={t.title}/><PageBody><State kind="error" title={t.unavailable} body={t.unavailableBody}><Button onClick={()=>void refreshSession().catch(()=>undefined)}>{t.retry}</Button></State></PageBody></PageFrame>;
  if(!session)return <PageFrame><PageHeader title={t.title}/><PageBody><State kind="error" title={t.denied} body={t.deniedBody}/></PageBody></PageFrame>;
  if(!path || !usesFoundationShell(path))return <PageFrame><PageHeader title={t.title}/><PageBody><State kind="error" title={t.unavailable} body={t.unavailableBody}/></PageBody></PageFrame>;
  return <CurrentSignals key={session.access_fingerprint} fingerprint={session.access_fingerprint}/>;
}
